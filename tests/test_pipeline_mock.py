"""Full pipeline on the mock provider: zero API spend, all four phases."""

from __future__ import annotations

from pathlib import Path

import pytest

from llmbench.analyze import analyze_phase, load_tidy
from llmbench.config import ExperimentConfig, load_config
from llmbench.grid import build_grid, write_grid
from llmbench.judge import judge_phase
from llmbench.questions import load_questions
from llmbench.runner import run_phase
from llmbench.storage import iter_jsonl_dir

from .conftest import make_config_dict

REPO_ROOT = Path(__file__).resolve().parents[1]


async def _full_pipeline(cfg: ExperimentConfig) -> tuple[Path, dict]:
    run_dir = cfg.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_grid(run_dir / "grid.jsonl", build_grid(cfg, load_questions(cfg.questions.path)))
    await run_phase(cfg, run_dir, progress_every=0)
    await judge_phase(cfg, run_dir, progress_every=0)
    tables = analyze_phase(cfg, run_dir, n_boot=200)
    return run_dir, tables


async def test_end_to_end_with_zero_spend(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs", refusal_rate=0.1)
    )
    run_dir, tables = await _full_pipeline(cfg)

    n_cells = len(load_questions(cfg.questions.path)) * cfg.cells_per_question()

    assert (run_dir / "grid.jsonl").exists()
    assert list((run_dir / "responses").glob("*.jsonl"))
    assert list((run_dir / "judgments").glob("*.jsonl"))
    assert list(run_dir.glob("manifest-*.json"))

    tidy = tables["tidy"]
    assert len(tidy) == n_cells, "one judgment row per cell"
    assert tidy["cell_id"].nunique() == n_cells

    for table in ("score_by_provider", "score_by_perspective", "perspective_spread",
                  "consistency", "run_variance", "cost_latency"):
        assert not tables[table].empty, f"{table} should not be empty"

    for name in ("tidy", "score_by_provider", "consistency"):
        assert (run_dir / "analysis" / f"{name}.csv").exists()


async def test_tidy_frame_has_every_grid_coordinate(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(make_config_dict(questions_file, tmp_path / "runs"))
    _, tables = await _full_pipeline(cfg)
    tidy = tables["tidy"]
    for col in (
        "question_id", "polarity", "perspective_id", "provider_id", "run_index",
        "agreement_score", "refusal", "non_responsive", "judge_model_requested",
        "rubric_version", "cost_usd_est", "latency_ms", "input_tokens", "output_tokens",
    ):
        assert col in tidy.columns, f"tidy frame is missing {col}"


async def test_judging_is_rerunnable_without_touching_the_answering_models(
    tmp_path, questions_file
):
    """The single most important structural requirement in the brief."""
    cfg = ExperimentConfig.model_validate(make_config_dict(questions_file, tmp_path / "runs"))
    run_dir, _ = await _full_pipeline(cfg)

    response_files = sorted((run_dir / "responses").glob("*.jsonl"))
    snapshots = {p: p.read_bytes() for p in response_files}
    n_responses = len(list(iter_jsonl_dir(run_dir / "responses")))

    # Re-judge the same responses under a different rubric version and judge run.
    cfg2 = cfg.model_copy(deep=True)
    cfg2.judge.run_index = 1
    cfg2.judge.rubric_version = "v2"
    stats = await judge_phase(cfg2, run_dir, progress_every=0)

    assert stats.ok > 0, "a new judge run must produce new judgments"
    assert stats.skipped_done == 0, "a new rubric/run must not be treated as already done"

    for path, blob in snapshots.items():
        assert path.read_bytes() == blob, "re-judging must not touch response files"
    assert len(list(iter_jsonl_dir(run_dir / "responses"))) == n_responses

    tidy = load_tidy(run_dir)
    assert set(tidy["rubric_version"]) == {"v1", "v2"}
    assert set(tidy["judge_run_index"]) == {0, 1}


async def test_second_judge_pass_is_idempotent(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(make_config_dict(questions_file, tmp_path / "runs"))
    run_dir, _ = await _full_pipeline(cfg)
    again = await judge_phase(cfg, run_dir, progress_every=0)
    assert again.planned == 0


async def test_unparseable_judge_output_is_retried_then_recorded(tmp_path, questions_file):
    """Parse failures keep their raw text so a parser fix needs no new calls."""
    cfg = ExperimentConfig.model_validate(
        make_config_dict(
            questions_file, tmp_path / "runs", malformed_rate=1.0, max_repair_attempts=0
        )
    )
    run_dir = cfg.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_grid(run_dir / "grid.jsonl", build_grid(cfg, load_questions(cfg.questions.path)))
    await run_phase(cfg, run_dir, progress_every=0)
    stats = await judge_phase(cfg, run_dir, progress_every=0)

    assert stats.parse_failed == stats.planned
    assert stats.ok == 0
    rows = list(iter_jsonl_dir(run_dir / "judgments"))
    assert all(r["parse_ok"] is False for r in rows)
    assert all(r["judge_raw_text"] for r in rows), "raw judge text must always be stored"
    assert all(r["parse_error"] for r in rows)


async def test_repair_pass_recovers_malformed_output(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(
        make_config_dict(
            questions_file, tmp_path / "runs", malformed_rate=1.0, max_repair_attempts=1
        )
    )
    run_dir = cfg.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    write_grid(run_dir / "grid.jsonl", build_grid(cfg, load_questions(cfg.questions.path)))
    await run_phase(cfg, run_dir, progress_every=0)
    stats = await judge_phase(cfg, run_dir, progress_every=0)

    assert stats.repairs_attempted > 0
    assert stats.ok == stats.planned
    rows = list(iter_jsonl_dir(run_dir / "judgments"))
    assert all(r["repair_attempts"] == 1 for r in rows)


async def test_consistency_metric_reflects_flip_noise(tmp_path, questions_file):
    """mock-b has 3x the flip noise of mock-a and must look less consistent."""
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs", duplicates=3)
    )
    _, tables = await _full_pipeline(cfg)
    cons = tables["consistency"].set_index("provider_id")
    assert cons.loc["mock-a", "mean_inconsistency"] < cons.loc["mock-b", "mean_inconsistency"]

    variance = tables["run_variance"].set_index("provider_id")
    assert (
        variance.loc["mock-a", "mean_within_cell_sd"]
        < variance.loc["mock-b", "mean_within_cell_sd"]
    )


async def test_refusals_are_counted_separately_from_scores(tmp_path, questions_file):
    cfg = ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs", refusal_rate=0.5)
    )
    _, tables = await _full_pipeline(cfg)

    by_provider = tables["score_by_provider"]
    assert (by_provider["refusal_rate"] > 0).any()
    assert (by_provider["n_scored"] < by_provider["n_judgments"]).any(), (
        "refusals must be excluded from the scored denominator"
    )
    cons = tables["consistency"]
    assert (cons["indeterminate_rate"] > 0).any(), (
        "refused pairs must be reported as indeterminate, not as perfect consistency"
    )


def test_shipped_smoke_config_is_valid():
    cfg = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    assert cfg.run.duplicates == 3
    assert len(cfg.perspectives) == 5
    assert len(cfg.providers) == 3
    assert all(p.adapter == "mock" for p in cfg.providers)
    assert cfg.judge.provider.adapter == "mock"


def test_shipped_experiment_config_is_valid_and_matches_the_agreed_grid():
    cfg = load_config(REPO_ROOT / "configs" / "experiment.yaml")
    assert cfg.run.duplicates == 3
    assert len(cfg.perspectives) == 5
    assert len(cfg.providers) == 3
    assert any(p.id == "control" for p in cfg.perspectives), "control perspective is required"
    assert cfg.judge.provider.id not in {p.id for p in cfg.providers}
    assert cfg.cells_per_question() == 2 * 5 * 3 * 3


def test_experiment_config_still_has_placeholders_to_fill_in():
    """Fails the day the advisor fills these in -- which is the point."""
    cfg = load_config(REPO_ROOT / "configs" / "experiment.yaml")
    placeholders = [p.id for p in cfg.providers if "REPLACE-ME" in p.model]
    zero_priced = [
        p.id
        for p in cfg.providers
        if p.pricing.input_per_mtok == 0 and p.pricing.output_per_mtok == 0
    ]
    assert set(placeholders) == set(zero_priced), (
        "a provider with a real model id must also have real pricing"
    )
