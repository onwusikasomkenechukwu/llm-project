"""Append-only JSONL storage and the resume index.

Two rules hold everywhere in this module:
  1. A raw file is never rewritten. New runs append, or open a new timestamped file.
  2. Nothing is dropped. A failed call is a row with an error field.

Those two rules are in tension with "skip cells already present", because a
failed cell IS present. The resolution lives in `ResumeIndex`: a cell is done
only when it has a status="ok" row. A cell whose only rows are errors is retried
with attempt_epoch incremented, and the old error rows stay on disk.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .records import ResponseRecord


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _next_path(directory: Path, prefix: str, suffix: str = ".jsonl") -> Path:
    """A fresh, never-before-used filename in `directory`.

    The timestamp has second resolution, so two invocations inside the same
    second would collide and the second would append into the first file. That
    loses no data, but it breaks the guarantee that a file already on disk never
    changes -- which is what makes a completed file safe to copy, hash or ship
    while another run is in progress.

    Every name carries a zero-padded ordinal, so all files share one shape and
    lexicographic order is chronological order. That matters: `iter_jsonl_dir`
    reads in filename order, and `latest_ok_responses` takes the last row it
    sees. A bare `-1` suffix would sort BEFORE the unsuffixed name and silently
    invert that.
    """
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{prefix}-{timestamp_slug()}"
    for n in range(1000):
        candidate = directory / f"{base}-{n:03d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find an unused filename for {base} in {directory}")


def new_response_path(run_dir: Path) -> Path:
    return _next_path(run_dir / "responses", "responses")


def new_judgment_path(run_dir: Path, judge_provider_id: str, judge_run_index: int) -> Path:
    return _next_path(
        run_dir / "judgments", f"judgments-{judge_provider_id}-r{judge_run_index}"
    )


class JsonlWriter:
    """Append-only line writer.

    Flushes and fsyncs every line. A few thousand calls at a few seconds each
    leaves the syscall cost irrelevant, and it means a hard kill loses at most
    the row currently in flight.
    """

    def __init__(self, path: Path | str, fsync: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fsync = fsync
        self._fh = None
        self.lines_written = 0

    def __enter__(self) -> JsonlWriter:
        self._fh = self.path.open("a", encoding="utf-8", newline="\n")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def write(self, obj: Any) -> None:
        if self._fh is None:
            raise RuntimeError("JsonlWriter used outside its context manager")
        payload = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj
        self._fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()
        if self._fsync:
            os.fsync(self._fh.fileno())
        self.lines_written += 1

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def iter_jsonl(path: Path | str, strict: bool = False) -> Iterator[dict[str, Any]]:
    """Yield objects from one JSONL file.

    A truncated final line (the classic result of a kill mid-write) is skipped
    unless strict=True, so a crashed run can still be resumed.
    """
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                if strict:
                    raise
                # Tolerate only a truncated tail, never a corrupt middle.
                remainder = fh.read().strip()
                if remainder:
                    raise ValueError(
                        f"{p}:{lineno} is malformed JSON and is not the final line"
                    )
                return


def iter_jsonl_dir(directory: Path | str, pattern: str = "*.jsonl") -> Iterator[dict[str, Any]]:
    """Yield objects from every matching file, in filename order.

    Filenames carry a UTC timestamp, so filename order is chronological.
    """
    d = Path(directory)
    if not d.exists():
        return
    for path in sorted(d.glob(pattern)):
        yield from iter_jsonl(path)


class ResumeIndex:
    """What has already been done, built by scanning the output directory."""

    def __init__(self) -> None:
        self.ok_cells: set[str] = set()
        self.max_epoch: dict[str, int] = {}
        self.error_cells: set[str] = set()
        self.rows_scanned = 0

    @classmethod
    def from_responses(cls, run_dir: Path | str) -> ResumeIndex:
        idx = cls()
        for row in iter_jsonl_dir(Path(run_dir) / "responses"):
            cell = row.get("cell_id")
            if not cell:
                continue
            idx.rows_scanned += 1
            epoch = int(row.get("attempt_epoch", 0) or 0)
            idx.max_epoch[cell] = max(idx.max_epoch.get(cell, 0), epoch)
            if row.get("status") == "ok":
                idx.ok_cells.add(cell)
                idx.error_cells.discard(cell)
            elif cell not in idx.ok_cells:
                idx.error_cells.add(cell)
        return idx

    def is_done(self, cell_id: str) -> bool:
        return cell_id in self.ok_cells

    def next_epoch(self, cell_id: str) -> int:
        """Epoch to stamp on the next attempt at this cell."""
        if cell_id not in self.max_epoch:
            return 0
        return self.max_epoch[cell_id] + 1

    def partition(self, cell_ids: Iterable[str]) -> tuple[list[str], list[str], list[str]]:
        """Split cells into (fresh, retry_after_error, already_done)."""
        fresh, retry, done = [], [], []
        for cid in cell_ids:
            if cid in self.ok_cells:
                done.append(cid)
            elif cid in self.error_cells:
                retry.append(cid)
            else:
                fresh.append(cid)
        return fresh, retry, done


def latest_ok_responses(run_dir: Path | str) -> dict[str, ResponseRecord]:
    """The response to judge for each cell: the last successful row on disk.

    Later files win over earlier ones, and later lines win within a file, so a
    cell that failed and was retried is judged on the attempt that succeeded.
    """
    out: dict[str, ResponseRecord] = {}
    for row in iter_jsonl_dir(Path(run_dir) / "responses"):
        if row.get("status") != "ok":
            continue
        try:
            rec = ResponseRecord.model_validate(row)
        except Exception:
            continue
        out[rec.cell_id] = rec
    return out


def existing_judgment_ids(run_dir: Path | str) -> set[str]:
    """Judgment IDs already on disk, for judge-phase resume.

    Only rows that parsed successfully count as done. A row whose judge output
    could not be parsed is retried on the next judge pass; both rows survive.
    """
    done: set[str] = set()
    for row in iter_jsonl_dir(Path(run_dir) / "judgments"):
        jid = row.get("judgment_id")
        if jid and row.get("parse_ok") is True:
            done.add(jid)
    return done


def write_manifest(run_dir: Path, payload: dict[str, Any]) -> Path:
    """Manifest is append-only too: one file per invocation, never overwritten."""
    path = _next_path(Path(run_dir), "manifest", suffix=".json")
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path
