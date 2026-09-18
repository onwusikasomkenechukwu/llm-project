"""Loader for data/questions.jsonl.

One line per claim, carrying its own negation. Negations are authored once and
stored, never generated at runtime -- so the consistency metric is measuring the
model, not a fresh negation of unknown quality.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ids import validate_component


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    positive: str
    negative: str
    source: str = "unspecified"
    human_verified: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator("question_id")
    @classmethod
    def _id_safe(cls, v: str) -> str:
        return validate_component(v, "question_id")

    @field_validator("positive", "negative")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("claim text must not be empty")
        return v

    def text(self, polarity: Literal["pos", "neg"]) -> str:
        return self.positive if polarity == "pos" else self.negative


class QuestionSetError(ValueError):
    pass


def load_questions(
    path: str | Path,
    limit: int | None = None,
    require_verified_negation: bool = True,
) -> list[Question]:
    p = Path(path)
    if not p.exists():
        raise QuestionSetError(f"questions file not found: {p}")

    questions: list[Question] = []
    seen: set[str] = set()

    with p.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                raw: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                raise QuestionSetError(f"{p}:{lineno} is not valid JSON: {exc}") from exc
            try:
                q = Question.model_validate(raw)
            except Exception as exc:
                raise QuestionSetError(f"{p}:{lineno} failed validation: {exc}") from exc
            if q.question_id in seen:
                raise QuestionSetError(
                    f"{p}:{lineno} duplicate question_id {q.question_id!r}; "
                    "cell IDs would collide"
                )
            seen.add(q.question_id)
            questions.append(q)

    if not questions:
        raise QuestionSetError(f"{p} contained no questions")

    if require_verified_negation:
        unverified = [q.question_id for q in questions if not q.human_verified]
        if unverified:
            shown = ", ".join(unverified[:5])
            more = f" (+{len(unverified) - 5} more)" if len(unverified) > 5 else ""
            raise QuestionSetError(
                f"{len(unverified)} of {len(questions)} questions have "
                f"human_verified=false: {shown}{more}. Negation quality drives the "
                "consistency metric directly. Verify them, or set "
                "questions.require_verified_negation: false to proceed knowingly."
            )

    if limit is not None:
        questions = questions[:limit]
    return questions
