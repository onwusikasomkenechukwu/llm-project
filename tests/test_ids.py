"""Cell ID determinism: the property the whole resume/join story rests on."""

from __future__ import annotations

import subprocess
import sys

import pytest

from llmbench.config import ExperimentConfig
from llmbench.ids import (
    InvalidIdComponent,
    cell_id,
    config_hash,
    judgment_id,
    prompt_hash,
)

COORDS = ("q0137", "neg", "physician", "anthropic-opus5", 2)


def test_cell_id_is_stable_across_calls():
    assert cell_id(*COORDS) == cell_id(*COORDS)


def test_cell_id_is_stable_across_processes():
    """Guards against a hash that is randomised per process (PYTHONHASHSEED)."""
    code = (
        "from llmbench.ids import cell_id;"
        "print(cell_id('q0137','neg','physician','anthropic-opus5',2))"
    )
    outputs = set()
    for seed in ("0", "1", "random"):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={"PYTHONHASHSEED": seed, "PATH": "", "SYSTEMROOT": "C:\\Windows"},
            check=True,
        )
        outputs.add(proc.stdout.strip())
    assert len(outputs) == 1
    assert outputs.pop() == cell_id(*COORDS)


@pytest.mark.parametrize(
    "changed",
    [
        ("q0138", "neg", "physician", "anthropic-opus5", 2),
        ("q0137", "pos", "physician", "anthropic-opus5", 2),
        ("q0137", "neg", "teacher", "anthropic-opus5", 2),
        ("q0137", "neg", "physician", "openai-gpt", 2),
        ("q0137", "neg", "physician", "anthropic-opus5", 3),
    ],
)
def test_every_coordinate_changes_the_id(changed):
    assert cell_id(*changed) != cell_id(*COORDS)


def test_ids_are_unique_across_a_whole_grid():
    seen = set()
    for q in range(40):
        for polarity in ("pos", "neg"):
            for p in range(5):
                for prov in range(3):
                    for run in range(3):
                        seen.add(cell_id(f"q{q:04d}", polarity, f"p{p}", f"prov{prov}", run))
    assert len(seen) == 40 * 2 * 5 * 3 * 3


def test_delimiter_injection_is_rejected():
    """('a|b','c') must not be able to collide with ('a','b|c')."""
    with pytest.raises(InvalidIdComponent):
        cell_id("q1|x", "neg", "physician", "prov", 0)
    with pytest.raises(InvalidIdComponent):
        cell_id("q1", "neg", "physi cian", "prov", 0)
    with pytest.raises(InvalidIdComponent):
        cell_id("", "neg", "physician", "prov", 0)


@pytest.mark.parametrize("bad", [-1, 1.0, "2", True, None])
def test_run_index_must_be_a_non_negative_int(bad):
    with pytest.raises(InvalidIdComponent):
        cell_id("q1", "neg", "physician", "prov", bad)


def test_judgment_id_separates_judge_model_rubric_and_run():
    base = cell_id(*COORDS)
    a = judgment_id(base, "judge1", "model-x", 0, "v1")
    assert a == judgment_id(base, "judge1", "model-x", 0, "v1")
    assert a != judgment_id(base, "judge2", "model-x", 0, "v1")
    assert a != judgment_id(base, "judge1", "model-y", 0, "v1")
    assert a != judgment_id(base, "judge1", "model-x", 1, "v1")
    assert a != judgment_id(base, "judge1", "model-x", 0, "v2")


def test_prompt_hash_ignores_key_order():
    a = {"system": "s", "messages": [{"role": "user", "content": "hi"}]}
    b = {"messages": [{"content": "hi", "role": "user"}], "system": "s"}
    assert prompt_hash(a) == prompt_hash(b)


def test_config_hash_ignores_key_order_but_not_values():
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def test_config_hash_excludes_operational_knobs(questions_file, tmp_path):
    from .conftest import make_config_dict

    base = make_config_dict(questions_file, tmp_path / "runs")
    cfg_a = ExperimentConfig.model_validate(base)

    operational = make_config_dict(questions_file, tmp_path / "runs")
    operational["providers"][0]["max_concurrency"] = 32
    operational["reliability"]["max_attempts"] = 2
    operational["budget"]["max_total_usd"] = 999.0
    cfg_b = ExperimentConfig.model_validate(operational)
    assert cfg_a.config_hash == cfg_b.config_hash, "turning concurrency down is not a new experiment"

    semantic = make_config_dict(questions_file, tmp_path / "runs")
    semantic["answer_prompt"]["user_template"] = "Different: {question_text}"
    cfg_c = ExperimentConfig.model_validate(semantic)
    assert cfg_a.config_hash != cfg_c.config_hash, "changing the prompt IS a new experiment"
