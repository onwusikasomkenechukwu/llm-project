"""Grid construction and dispatch order."""

from __future__ import annotations

import pytest

from llmbench.config import ExperimentConfig
from llmbench.grid import build_grid, execution_order, load_grid, write_grid
from llmbench.questions import QuestionSetError, load_questions

from .conftest import SAMPLE_QUESTIONS, make_config_dict, write_questions


def test_grid_size_is_the_full_cartesian_product(cfg):
    questions = load_questions(cfg.questions.path)
    cells = list(build_grid(cfg, questions))
    assert len(cells) == len(questions) * cfg.cells_per_question()
    assert len(cells) == len(questions) * 2 * 2 * 2 * 2


def test_grid_ids_are_unique(cfg):
    cells = list(build_grid(cfg, load_questions(cfg.questions.path)))
    assert len({c.cell_id for c in cells}) == len(cells)


def test_grid_order_is_deterministic(cfg):
    questions = load_questions(cfg.questions.path)
    a = [c.cell_id for c in build_grid(cfg, questions)]
    b = [c.cell_id for c in build_grid(cfg, questions)]
    assert a == b


def test_grid_round_trips_through_disk(cfg, run_dir):
    cells = list(build_grid(cfg, load_questions(cfg.questions.path)))
    n = write_grid(run_dir / "grid.jsonl", cells)
    assert n == len(cells)
    loaded = load_grid(run_dir / "grid.jsonl")
    assert [c.cell_id for c in loaded] == [c.cell_id for c in cells]
    assert loaded[0].config_hash == cfg.config_hash


def test_every_cell_carries_all_five_coordinates(cfg):
    cell = next(iter(build_grid(cfg, load_questions(cfg.questions.path))))
    for field in ("question_id", "polarity", "perspective_id", "provider_id", "run_index"):
        assert getattr(cell, field) is not None


def test_execution_order_is_a_deterministic_permutation(cfg):
    cells = list(build_grid(cfg, load_questions(cfg.questions.path)))
    a = execution_order(cells, seed=42)
    b = execution_order(cells, seed=42)
    c = execution_order(cells, seed=43)

    assert [x.cell_id for x in a] == [x.cell_id for x in b]
    assert {x.cell_id for x in a} == {x.cell_id for x in cells}
    assert [x.cell_id for x in a] != [x.cell_id for x in c]
    assert [x.cell_id for x in a] != [x.cell_id for x in cells], "order should be shuffled"


def test_adding_a_provider_does_not_change_existing_cell_ids(tmp_path, questions_file):
    """Resumability across a config edit: old cells keep their identity."""
    base = make_config_dict(questions_file, tmp_path / "runs")
    cfg_a = ExperimentConfig.model_validate(base)
    before = {c.cell_id for c in build_grid(cfg_a, load_questions(questions_file))}

    extended = make_config_dict(questions_file, tmp_path / "runs")
    extended["providers"].append(
        {
            "id": "mock-c",
            "adapter": "mock",
            "model": "mock-c-v1",
            "pricing": {"input_per_mtok": 1.0, "output_per_mtok": 1.0},
            "params": {"mode": "answer", "seed": 3},
        }
    )
    cfg_b = ExperimentConfig.model_validate(extended)
    after = {c.cell_id for c in build_grid(cfg_b, load_questions(questions_file))}

    assert before < after, "existing cells must survive unchanged when a provider is added"


def test_load_grid_errors_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_grid(tmp_path / "nope.jsonl")


# -- question set validation ------------------------------------------------


def test_duplicate_question_ids_are_rejected(tmp_path):
    rows = SAMPLE_QUESTIONS + [SAMPLE_QUESTIONS[0]]
    path = write_questions(tmp_path / "dupes.jsonl", rows)
    with pytest.raises(QuestionSetError, match="duplicate"):
        load_questions(path)


def test_unverified_negations_are_refused_by_default(tmp_path):
    rows = [dict(SAMPLE_QUESTIONS[0], human_verified=False)]
    path = write_questions(tmp_path / "unverified.jsonl", rows)
    with pytest.raises(QuestionSetError, match="human_verified"):
        load_questions(path)
    assert load_questions(path, require_verified_negation=False)


def test_limit_truncates(tmp_path, questions_file):
    assert len(load_questions(questions_file, limit=2)) == 2


def test_empty_claim_text_is_rejected(tmp_path):
    rows = [dict(SAMPLE_QUESTIONS[0], negative="   ")]
    path = write_questions(tmp_path / "empty.jsonl", rows)
    with pytest.raises(QuestionSetError):
        load_questions(path)


def test_question_id_with_a_delimiter_is_rejected(tmp_path):
    rows = [dict(SAMPLE_QUESTIONS[0], question_id="bad id")]
    path = write_questions(tmp_path / "badid.jsonl", rows)
    with pytest.raises(QuestionSetError):
        load_questions(path)
