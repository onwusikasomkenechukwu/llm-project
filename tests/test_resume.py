"""Resume: no duplicated work, no lost cells, failures retried rather than dropped."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from llmbench.config import ExperimentConfig
from llmbench.grid import build_grid, load_grid, write_grid
from llmbench.questions import load_questions
from llmbench.runner import run_phase
from llmbench.storage import (
    ResumeIndex,
    iter_jsonl,
    iter_jsonl_dir,
    latest_ok_responses,
)

from .conftest import make_config_dict


def _generate(cfg: ExperimentConfig) -> Path:
    run_dir = cfg.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    questions = load_questions(cfg.questions.path)
    write_grid(run_dir / "grid.jsonl", build_grid(cfg, questions))
    return run_dir


def _rows(run_dir: Path) -> list[dict]:
    return list(iter_jsonl_dir(run_dir / "responses"))


# -- ResumeIndex semantics --------------------------------------------------


def test_index_treats_ok_as_done_and_error_only_as_retryable(tmp_path):
    d = tmp_path / "responses"
    d.mkdir(parents=True)
    (d / "responses-1.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"cell_id": "c_ok", "status": "ok", "attempt_epoch": 0},
                {"cell_id": "c_err", "status": "error", "attempt_epoch": 0},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    idx = ResumeIndex.from_responses(tmp_path)
    assert idx.is_done("c_ok")
    assert not idx.is_done("c_err")
    assert idx.next_epoch("c_err") == 1
    assert idx.next_epoch("c_never_seen") == 0

    fresh, retry, done = idx.partition(["c_ok", "c_err", "c_new"])
    assert fresh == ["c_new"] and retry == ["c_err"] and done == ["c_ok"]


def test_a_later_ok_clears_an_earlier_error(tmp_path):
    d = tmp_path / "responses"
    d.mkdir(parents=True)
    (d / "responses-1.jsonl").write_text(
        json.dumps({"cell_id": "c1", "status": "error", "attempt_epoch": 0}) + "\n",
        encoding="utf-8",
    )
    (d / "responses-2.jsonl").write_text(
        json.dumps({"cell_id": "c1", "status": "ok", "attempt_epoch": 1}) + "\n",
        encoding="utf-8",
    )
    idx = ResumeIndex.from_responses(tmp_path)
    assert idx.is_done("c1")
    assert "c1" not in idx.error_cells


def test_truncated_final_line_does_not_block_resume(tmp_path):
    """A kill mid-write must not make the whole run unreadable."""
    p = tmp_path / "responses.jsonl"
    p.write_text(
        json.dumps({"cell_id": "c1", "status": "ok"}) + "\n" + '{"cell_id": "c2", "sta',
        encoding="utf-8",
    )
    rows = list(iter_jsonl(p))
    assert len(rows) == 1 and rows[0]["cell_id"] == "c1"


def test_corrupt_middle_line_is_an_error(tmp_path):
    p = tmp_path / "responses.jsonl"
    p.write_text(
        json.dumps({"cell_id": "c1"}) + "\nNOT JSON\n" + json.dumps({"cell_id": "c3"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        list(iter_jsonl(p))


# -- end-to-end resume over the mock provider -------------------------------


async def test_resume_produces_no_duplicates_and_no_gaps(tmp_path, questions_file):
    """The core guarantee: restart mid-run, end with exactly one ok row per cell."""
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs", failure_rate=0.25)
    )
    run_dir = _generate(cfg)
    all_cells = {c.cell_id for c in load_grid(run_dir / "grid.jsonl")}

    # Interrupt deliberately: only part of the grid on the first pass.
    first = await run_phase(cfg, run_dir, limit=20, progress_every=0)
    assert first.planned == 20

    # Resume repeatedly until the run reports nothing left to do.
    for _ in range(10):
        stats = await run_phase(cfg, run_dir, progress_every=0)
        if stats.planned == 0:
            break

    rows = _rows(run_dir)
    ok_counts = Counter(r["cell_id"] for r in rows if r["status"] == "ok")

    assert set(ok_counts) == all_cells, "every grid cell must end with an ok row (no gaps)"
    assert all(n == 1 for n in ok_counts.values()), "no cell may be called twice successfully"


async def test_failed_cells_are_recorded_not_dropped(tmp_path, questions_file):
    """A cell that cannot succeed must leave an error row, and keep being retried.

    mock-b fails every attempt here, so the outcome is deterministic rather than
    depending on a lucky retry draw.
    """
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs", failure_rate=1.0)
    )
    run_dir = _generate(cfg)
    all_cells = {c.cell_id: c for c in load_grid(run_dir / "grid.jsonl")}
    doomed = {cid for cid, c in all_cells.items() if c.provider_id == "mock-b"}

    first = await run_phase(cfg, run_dir, progress_every=0)
    assert first.failed == len(doomed)
    assert first.ok == len(all_cells) - len(doomed)
    assert first.errors_by_type, "the error type should be recorded for reporting"

    rows = _rows(run_dir)
    errors = {r["cell_id"]: r for r in rows if r["status"] == "error"}
    assert set(errors) == doomed, "every failing cell needs a row, not a silent drop"
    for row in errors.values():
        assert row["error"]["type"]
        assert row["error"]["message"]
        assert row["error"]["retryable"] is True
        assert row["error"]["http_status"] == 429
        assert row["prompt"]["messages"], "the prompt must be recorded even on failure"
        assert row["attempt_epoch"] == 0

    # Resuming retries exactly the failed cells, at a higher epoch, keeping the
    # old rows. The succeeded cells are not called again.
    second = await run_phase(cfg, run_dir, progress_every=0)
    assert second.planned == len(doomed)
    assert second.retry_after_error == len(doomed)

    rows = _rows(run_dir)
    for cell in doomed:
        epochs = sorted(r["attempt_epoch"] for r in rows if r["cell_id"] == cell)
        assert epochs == [0, 1], "the earlier error row must survive alongside the retry"
    assert not [r for r in rows if r["status"] == "ok" and r["cell_id"] in doomed]


async def test_rerunning_a_complete_run_calls_nothing(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs")
    )
    run_dir = _generate(cfg)
    await run_phase(cfg, run_dir, progress_every=0)
    before = len(_rows(run_dir))

    again = await run_phase(cfg, run_dir, progress_every=0)
    assert again.planned == 0
    assert again.ok == 0
    assert len(_rows(run_dir)) == before, "a no-op resume must not append rows"


async def test_raw_files_are_never_rewritten(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs", failure_rate=0.3)
    )
    run_dir = _generate(cfg)
    await run_phase(cfg, run_dir, limit=15, progress_every=0)

    first_file = sorted((run_dir / "responses").glob("*.jsonl"))[0]
    snapshot = first_file.read_bytes()

    await run_phase(cfg, run_dir, progress_every=0)

    assert first_file.read_bytes() == snapshot, "an existing response file must never change"
    assert len(list((run_dir / "responses").glob("*.jsonl"))) >= 2


async def test_latest_ok_response_wins_for_judging(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs", failure_rate=0.3)
    )
    run_dir = _generate(cfg)
    for _ in range(6):
        if (await run_phase(cfg, run_dir, progress_every=0)).planned == 0:
            break

    latest = latest_ok_responses(run_dir)
    all_cells = {c.cell_id for c in load_grid(run_dir / "grid.jsonl")}
    assert set(latest) == all_cells
    assert all(r.status == "ok" for r in latest.values())


async def test_dry_run_spends_nothing_and_writes_nothing(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs")
    )
    run_dir = _generate(cfg)
    stats = await run_phase(cfg, run_dir, dry_run=True, progress_every=0)
    assert stats.planned > 0
    assert stats.ok == 0
    assert not list((run_dir / "responses").glob("*.jsonl"))
