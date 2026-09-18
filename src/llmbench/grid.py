"""Grid construction: the full cell list, written once, before anything is spent."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Iterator

from .config import ExperimentConfig
from .ids import cell_id
from .questions import Question
from .records import GridCell
from .storage import JsonlWriter, iter_jsonl


def build_grid(cfg: ExperimentConfig, questions: list[Question]) -> Iterator[GridCell]:
    """Canonical order: question, polarity, perspective, provider, run_index.

    grid.jsonl is always written in this order so two machines produce
    byte-identical files. Execution order is shuffled separately, at run time.
    """
    chash = cfg.config_hash
    for q in questions:
        for polarity in cfg.questions.polarities:
            for perspective in cfg.perspectives:
                for provider in cfg.providers:
                    for run_index in range(cfg.run.duplicates):
                        yield GridCell(
                            cell_id=cell_id(
                                q.question_id,
                                polarity,
                                perspective.id,
                                provider.id,
                                run_index,
                            ),
                            question_id=q.question_id,
                            polarity=polarity,
                            perspective_id=perspective.id,
                            provider_id=provider.id,
                            run_index=run_index,
                            config_hash=chash,
                        )


def write_grid(path: Path | str, cells: Iterator[GridCell] | list[GridCell]) -> int:
    """Write grid.jsonl. This is the one file the harness overwrites.

    It is pure derived data -- a deterministic function of config plus questions
    -- so regenerating it destroys nothing. Raw responses are never touched.
    """
    count = 0
    seen: set[str] = set()
    with JsonlWriter(path, fsync=False) as writer:
        for cell in cells:
            if cell.cell_id in seen:
                raise ValueError(
                    f"cell_id collision at {cell.cell_id}: "
                    f"{cell.question_id}/{cell.polarity}/{cell.perspective_id}/"
                    f"{cell.provider_id}/{cell.run_index}"
                )
            seen.add(cell.cell_id)
            writer.write(cell)
            count += 1
    return count


def load_grid(path: Path | str) -> list[GridCell]:
    cells = [GridCell.model_validate(row) for row in iter_jsonl(path)]
    if not cells:
        raise FileNotFoundError(
            f"no grid at {path}. Run `llmbench generate-grid` first."
        )
    return cells


def execution_order(cells: list[GridCell], seed: int) -> list[GridCell]:
    """Shuffle dispatch order.

    Running in nested-loop order aligns provider and perspective with wall-clock
    time, so API-side drift and time-of-day load land unevenly across
    conditions. Shuffling with a recorded seed costs nothing and removes that.
    """
    shuffled = list(cells)
    random.Random(seed).shuffle(shuffled)
    return shuffled
