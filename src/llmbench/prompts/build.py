"""Prompt assembly.

The exact object built here is what gets recorded on every response row, so the
prompt that produced an answer is always recoverable from the data alone --
without re-deriving it from a config that may since have changed.
"""

from __future__ import annotations

from pathlib import Path

from ..config import AnswerPromptCfg, ExperimentConfig, PerspectiveCfg
from ..providers.base import CompletionRequest
from ..questions import Question


def build_answer_request(
    cfg: ExperimentConfig,
    question: Question,
    polarity: str,
    perspective: PerspectiveCfg,
    meta: dict | None = None,
) -> CompletionRequest:
    ap: AnswerPromptCfg = cfg.answer_prompt
    claim = question.text(polarity)  # type: ignore[arg-type]
    user_text = ap.user_template.format(question_text=claim)

    system: str | None = None
    if ap.placement == "system":
        rendered = ap.system_template.format(perspective_fragment=perspective.system_fragment)
        system = rendered.strip() or None
    else:
        # Same fragment, prepended to the user turn instead. Which one a given
        # provider honours differs, so the choice is explicit in config and the
        # result is recorded verbatim either way.
        prefix = perspective.system_fragment.strip()
        if prefix:
            user_text = f"{prefix}\n\n{user_text}"

    return CompletionRequest(
        system=system,
        messages=[{"role": "user", "content": user_text}],
        max_tokens=ap.max_tokens,
        temperature=ap.temperature,
        meta=dict(meta or {}),
    )


def load_judge_template(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"judge prompt template not found: {p}")
    return p.read_text(encoding="utf-8")


def build_judge_request(
    template: str,
    claim: str,
    answer: str,
    max_tokens: int = 500,
    temperature: float = 0.0,
    repair_note: str | None = None,
    meta: dict | None = None,
) -> CompletionRequest:
    body = template.replace("{claim}", claim).replace("{answer}", answer)
    if repair_note:
        body += (
            "\n\nYour previous reply could not be parsed as JSON. "
            f"The parser reported: {repair_note}\n"
            "Reply with the JSON object only."
        )
    return CompletionRequest(
        system=None,
        messages=[{"role": "user", "content": body}],
        max_tokens=max_tokens,
        temperature=temperature,
        meta=dict(meta or {}),
    )
