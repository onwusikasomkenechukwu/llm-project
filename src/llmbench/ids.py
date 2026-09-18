"""Deterministic identifiers.

Every ID in this project is a pure function of its coordinates. The same inputs
must always yield the same ID, across machines, Python versions and runs --
that is what makes `run` resumable and makes responses joinable to judgments.

Implementation notes:
  * blake2b, not Python's hash(), which is randomised per process by PYTHONHASHSEED.
  * Components are validated against a restrictive charset that excludes the
    field delimiter, so ("a|b", "c") can never collide with ("a", "b|c").
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

DELIM = "\x1f"  # ASCII unit separator: cannot appear in a validated component
ID_CHARSET = re.compile(r"^[A-Za-z0-9._-]+$")

CELL_PREFIX = "c"
JUDGMENT_PREFIX = "j"
PROMPT_PREFIX = "p"
JUDGE_PROMPT_PREFIX = "jp"
CONFIG_PREFIX = "cfg"


class InvalidIdComponent(ValueError):
    """Raised when a coordinate cannot be used to build a deterministic ID."""


def validate_component(value: str, field: str) -> str:
    """Reject anything that would make IDs ambiguous or non-portable."""
    if not isinstance(value, str) or not value:
        raise InvalidIdComponent(f"{field} must be a non-empty string, got {value!r}")
    if not ID_CHARSET.match(value):
        raise InvalidIdComponent(
            f"{field}={value!r} contains characters outside [A-Za-z0-9._-]; "
            "IDs must stay filesystem- and join-safe"
        )
    return value


def _digest(parts: Iterable[str], prefix: str, size: int = 8) -> str:
    payload = DELIM.join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.blake2b(payload, digest_size=size).hexdigest()}"


def cell_id(
    question_id: str,
    polarity: str,
    perspective_id: str,
    provider_id: str,
    run_index: int,
) -> str:
    """The grid coordinate identity.

    Deliberately excludes config_hash: adding a fourth provider to the config
    must not change the IDs of cells that already ran.
    """
    if not isinstance(run_index, int) or isinstance(run_index, bool) or run_index < 0:
        raise InvalidIdComponent(f"run_index must be a non-negative int, got {run_index!r}")
    parts = [
        validate_component(question_id, "question_id"),
        validate_component(polarity, "polarity"),
        validate_component(perspective_id, "perspective_id"),
        validate_component(provider_id, "provider_id"),
        str(run_index),
    ]
    return _digest(parts, CELL_PREFIX)


def judgment_id(
    cell_id_value: str,
    judge_provider_id: str,
    judge_model: str,
    judge_run_index: int,
    rubric_version: str,
) -> str:
    """Judgment identity.

    Includes the judge model and rubric version so that re-judging with a
    different judge or a revised rubric appends rather than collides.
    """
    if not isinstance(judge_run_index, int) or isinstance(judge_run_index, bool) or judge_run_index < 0:
        raise InvalidIdComponent(
            f"judge_run_index must be a non-negative int, got {judge_run_index!r}"
        )
    parts = [
        validate_component(cell_id_value, "cell_id"),
        validate_component(judge_provider_id, "judge_provider_id"),
        validate_component(judge_model, "judge_model"),
        str(judge_run_index),
        validate_component(rubric_version, "rubric_version"),
    ]
    return _digest(parts, JUDGMENT_PREFIX)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def prompt_hash(payload: Any, prefix: str = PROMPT_PREFIX) -> str:
    """Hash of the exact prompt object sent to a provider."""
    return _digest([_canonical(payload)], prefix)


def judge_prompt_hash(payload: Any) -> str:
    return prompt_hash(payload, prefix=JUDGE_PROMPT_PREFIX)


def config_hash(config_dict: Any) -> str:
    """Hash of the whole resolved config, recorded on every row."""
    return _digest([_canonical(config_dict)], CONFIG_PREFIX)
