from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmbench.config import ExperimentConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
JUDGE_PROMPT = REPO_ROOT / "src" / "llmbench" / "prompts" / "judge.md"

SAMPLE_QUESTIONS = [
    {
        "question_id": f"t{i:03d}",
        "positive": f"Claim number {i} is true.",
        "negative": f"Claim number {i} is not true.",
        "source": "test-fixture",
        "human_verified": True,
    }
    for i in range(1, 7)
]


def write_questions(path: Path, rows=None) -> Path:
    rows = SAMPLE_QUESTIONS if rows is None else rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path


def make_config_dict(
    questions_path: Path,
    output_root: Path,
    *,
    duplicates: int = 2,
    n_perspectives: int = 2,
    failure_rate: float = 0.0,
    malformed_rate: float = 0.0,
    refusal_rate: float = 0.0,
    max_total_usd: float = 100.0,
    max_repair_attempts: int = 1,
) -> dict:
    perspectives = [
        {"id": "control", "label": "None", "system_fragment": ""},
        {"id": "physician", "label": "Physician", "system_fragment": "Answer as a physician."},
        {"id": "teacher", "label": "Teacher", "system_fragment": "Answer as a teacher."},
    ][:n_perspectives]

    return {
        "schema_version": 1,
        "run": {
            "name": "testrun",
            "output_root": str(output_root),
            "duplicates": duplicates,
            "shuffle_seed": 42,
        },
        "questions": {
            "path": str(questions_path),
            "polarities": ["pos", "neg"],
            "require_verified_negation": True,
        },
        "perspectives": perspectives,
        "answer_prompt": {
            "placement": "system",
            "system_template": "{perspective_fragment}",
            "user_template": "Consider: {question_text}",
            "max_tokens": 256,
            "temperature": 1.0,
        },
        "providers": [
            {
                "id": "mock-a",
                "adapter": "mock",
                "model": "mock-a-v1",
                "max_concurrency": 4,
                "pricing": {"input_per_mtok": 3.0, "output_per_mtok": 15.0},
                "params": {"mode": "answer", "seed": 1, "flip_noise": 0.1,
                           "refusal_rate": refusal_rate},
            },
            {
                "id": "mock-b",
                "adapter": "mock",
                "model": "mock-b-v1",
                "max_concurrency": 4,
                "pricing": {"input_per_mtok": 1.0, "output_per_mtok": 5.0},
                "params": {"mode": "answer", "seed": 2, "flip_noise": 0.3,
                           "refusal_rate": refusal_rate, "failure_rate": failure_rate},
            },
        ],
        "judge": {
            "provider": {
                "id": "mock-judge",
                "adapter": "mock",
                "model": "mock-judge-v1",
                "max_concurrency": 4,
                "pricing": {"input_per_mtok": 2.0, "output_per_mtok": 10.0},
                "params": {"mode": "judge", "seed": 9, "malformed_rate": malformed_rate},
            },
            "run_index": 0,
            "rubric_version": "v1",
            "prompt_path": str(JUDGE_PROMPT),
            "max_repair_attempts": max_repair_attempts,
        },
        "reliability": {
            "max_attempts": 4,
            "backoff": {"base_s": 0.001, "multiplier": 2.0, "max_s": 0.01, "jitter": "full"},
        },
        "budget": {
            "max_total_usd": max_total_usd,
            "estimate_headroom": 1.15,
            "abort_on_exceed": True,
        },
    }


@pytest.fixture
def questions_file(tmp_path: Path) -> Path:
    return write_questions(tmp_path / "data" / "questions.jsonl")


@pytest.fixture
def cfg(tmp_path: Path, questions_file: Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(
        make_config_dict(questions_file, tmp_path / "runs")
    )


@pytest.fixture
def run_dir(cfg: ExperimentConfig) -> Path:
    d = cfg.run_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d
