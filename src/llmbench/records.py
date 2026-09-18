"""Schemas for every line written to disk.

Reading is deliberately permissive (unknown keys are ignored) so that a file
written by an older version of the harness still loads. Writing always emits the
full current schema, tagged with schema_version.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

Status = Literal["ok", "error"]

# The rubric. agreement_score is the primary outcome: a signed scale where a
# perfectly consistent model scores s and -s on a claim and its negation.
AGREEMENT_MIN = -2
AGREEMENT_MAX = 2
AGREEMENT_LABELS = {
    -2: "strongly disagree",
    -1: "disagree",
    0: "neutral or hedged",
    1: "agree",
    2: "strongly agree",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@lru_cache(maxsize=1)
def code_version() -> str | None:
    """Short git SHA of the harness, stamped on every row.

    Returns None outside a git checkout rather than failing: the field is for
    tracing a result back to the code that produced it, and its absence should
    never stop a run.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    if not sha:
        return None
    dirty = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return f"{sha}-dirty" if dirty.stdout.strip() else sha


class Record(BaseModel):
    """Permissive on read, complete on write."""

    model_config = ConfigDict(extra="ignore")


class Usage(Record):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ErrorInfo(Record):
    type: str
    message: str
    http_status: int | None = None
    retryable: bool = False


class PromptPayload(Record):
    system: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class GridCell(Record):
    """One line of grid.jsonl."""

    cell_id: str
    question_id: str
    polarity: Literal["pos", "neg"]
    perspective_id: str
    provider_id: str
    run_index: int
    config_hash: str


class ResponseRecord(Record):
    """One line of responses/*.jsonl -- one API call outcome, append-only."""

    schema_version: int = SCHEMA_VERSION

    cell_id: str
    question_id: str
    polarity: Literal["pos", "neg"]
    perspective_id: str
    provider_id: str
    run_index: int

    status: Status
    attempt_epoch: int = 0
    attempts_used: int = 1

    prompt: PromptPayload
    prompt_hash: str

    response_text: str | None = None
    finish_reason: str | None = None

    model_requested: str
    model_reported: str | None = None
    provider_request_id: str | None = None

    usage: Usage = Field(default_factory=Usage)
    cost_usd_est: float = 0.0
    pricing_used: dict[str, float] = Field(default_factory=dict)

    latency_ms: int = 0
    started_at: str
    finished_at: str

    error: ErrorInfo | None = None
    config_hash: str
    code_version: str | None = None


class ParsedJudgment(Record):
    """The structured object the judge must return.

    Validation is strict here -- an out-of-range score is a parse failure, not a
    silently clamped value, because a clamped score would quietly corrupt the
    primary outcome variable.
    """

    model_config = ConfigDict(extra="forbid")

    agreement_score: int = Field(ge=AGREEMENT_MIN, le=AGREEMENT_MAX)
    refusal: bool
    non_responsive: bool
    justification_quality: int | None = Field(default=None, ge=1, le=5)
    rationale: str = ""


class JudgmentRecord(Record):
    """One line of judgments/*.jsonl."""

    schema_version: int = SCHEMA_VERSION

    judgment_id: str
    cell_id: str

    question_id: str
    polarity: Literal["pos", "neg"]
    perspective_id: str
    provider_id: str
    run_index: int

    response_line_ref: dict[str, Any] = Field(default_factory=dict)

    judge_provider_id: str
    judge_model_requested: str
    judge_model_reported: str | None = None
    judge_run_index: int
    rubric_version: str

    judge_raw_text: str | None = None
    parse_ok: bool = False
    parse_error: str | None = None
    repair_attempts: int = 0

    parsed: ParsedJudgment | None = None

    judge_prompt: PromptPayload | None = None
    judge_prompt_hash: str

    usage: Usage = Field(default_factory=Usage)
    cost_usd_est: float = 0.0
    pricing_used: dict[str, float] = Field(default_factory=dict)

    latency_ms: int = 0
    created_at: str

    error: ErrorInfo | None = None
    config_hash: str
    code_version: str | None = None
