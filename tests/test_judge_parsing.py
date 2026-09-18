"""Judge output parsing: structured, validated, and never silently corrected."""

from __future__ import annotations

import json

import pytest

from llmbench.judge import extract_json_object, parse_judgment
from llmbench.records import ParsedJudgment

VALID = {
    "agreement_score": -1,
    "refusal": False,
    "non_responsive": False,
    "justification_quality": 4,
    "rationale": "Leans against the claim, citing scope.",
}


def test_clean_json():
    parsed, err = parse_judgment(json.dumps(VALID))
    assert err is None
    assert parsed.agreement_score == -1


def test_fenced_json():
    parsed, err = parse_judgment("```json\n" + json.dumps(VALID) + "\n```")
    assert err is None
    assert parsed.justification_quality == 4


def test_bare_fence():
    parsed, err = parse_judgment("```\n" + json.dumps(VALID) + "\n```")
    assert err is None


def test_json_wrapped_in_prose():
    text = f"Sure, here is my assessment:\n{json.dumps(VALID)}\nLet me know if you need more."
    parsed, err = parse_judgment(text)
    assert err is None
    assert parsed.agreement_score == -1


def test_braces_inside_strings_do_not_confuse_the_scanner():
    payload = dict(VALID, rationale='The answer said "{not json}" verbatim.')
    parsed, err = parse_judgment("Assessment follows. " + json.dumps(payload))
    assert err is None
    assert parsed.rationale == 'The answer said "{not json}" verbatim.'


def test_truncated_json_is_a_parse_failure():
    parsed, err = parse_judgment("Here it is: " + json.dumps(VALID)[:-1])
    assert parsed is None
    assert err


def test_empty_output():
    parsed, err = parse_judgment("")
    assert parsed is None
    assert "empty" in err


def test_prose_only_output():
    parsed, err = parse_judgment("I think the model broadly agreed with the claim.")
    assert parsed is None
    assert "no JSON object" in err


@pytest.mark.parametrize("score", [-3, 3, 99, -100])
def test_out_of_range_score_is_rejected_not_clamped(score):
    """A clamped score would silently corrupt the primary outcome variable."""
    parsed, err = parse_judgment(json.dumps(dict(VALID, agreement_score=score)))
    assert parsed is None
    assert "validation" in err


def test_non_integer_score_is_rejected():
    parsed, err = parse_judgment(json.dumps(dict(VALID, agreement_score=1.5)))
    assert parsed is None


def test_missing_required_field_is_rejected():
    payload = dict(VALID)
    del payload["refusal"]
    parsed, err = parse_judgment(json.dumps(payload))
    assert parsed is None
    assert "validation" in err


def test_unexpected_field_is_rejected():
    """Silent extra keys usually mean the judge answered a different rubric."""
    parsed, err = parse_judgment(json.dumps(dict(VALID, confidence="high")))
    assert parsed is None


def test_justification_quality_is_optional():
    payload = dict(VALID)
    del payload["justification_quality"]
    parsed, err = parse_judgment(json.dumps(payload))
    assert err is None
    assert parsed.justification_quality is None


@pytest.mark.parametrize("score", [-2, -1, 0, 1, 2])
def test_full_score_range_accepted(score):
    parsed, _ = parse_judgment(json.dumps(dict(VALID, agreement_score=score)))
    assert parsed.agreement_score == score


def test_single_object_wrapped_in_an_array_is_recovered():
    """Lenient on purpose: recovering the judgment beats paying for a repair call."""
    obj, err = extract_json_object(json.dumps([VALID]))
    assert err is None
    assert obj["agreement_score"] == -1


def test_boolean_flags_round_trip():
    payload = dict(VALID, refusal=True, non_responsive=True, agreement_score=0)
    parsed, err = parse_judgment(json.dumps(payload))
    assert err is None
    assert parsed.refusal and parsed.non_responsive


def test_parsed_judgment_model_rejects_extras_directly():
    with pytest.raises(Exception):
        ParsedJudgment.model_validate(dict(VALID, surprise=1))
