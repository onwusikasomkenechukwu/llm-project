"""Deterministic offline provider: the whole pipeline with zero API spend.

Two modes:
  * answer -- produces a short stance-bearing answer and embeds a hidden marker
    carrying the stance it "believes".
  * judge  -- reads that marker back out and emits rubric JSON.

The marker is what lets an end-to-end mock run produce coherent consistency and
variance numbers instead of noise, so the analysis code is exercised on data
with real structure. Given no marker, the judge falls back to a seeded draw.

Everything is seeded from grid coordinates, so a mock run is byte-identical on
re-run -- which is what the resume and determinism tests rely on.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from typing import Any

from .base import BaseProvider, CompletionRequest, CompletionResult
from ..retry import TransientProviderError

MARKER_RE = re.compile(r"\[\[stance=(-?\d)\]\]", re.IGNORECASE)

_AGREE_TEMPLATES = {
    2: "I agree with this without reservation. {reason}",
    1: "On balance I agree, with some caveats. {reason}",
    0: "This depends on how the terms are defined, so I would not commit either way. {reason}",
    -1: "On balance I disagree, though the point is arguable. {reason}",
    -2: "I disagree with this without reservation. {reason}",
}

_REASONS = [
    "The evidence I am aware of points that way.",
    "The claim as stated is broader than the support for it.",
    "Most practitioners in the field would say the same.",
    "The framing leaves out cases that matter here.",
]


def _seed_int(*parts: Any) -> int:
    payload = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


class MockProvider(BaseProvider):
    adapter_name = "mock"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        params = dict(cfg.params or {})
        self.mode: str = params.get("mode", "answer")
        self.seed: int = int(params.get("seed", 0))
        self.failure_rate: float = float(params.get("failure_rate", 0.0))
        self.failure_status: int = int(params.get("failure_status", 429))
        self.malformed_rate: float = float(params.get("malformed_rate", 0.0))
        self.refusal_rate: float = float(params.get("refusal_rate", 0.0))
        self.flip_noise: float = float(params.get("flip_noise", 0.1))
        self.latency_ms: int = int(params.get("latency_ms", 0))
        # Per-cell call counter, so an injected failure can be retried and then
        # succeed. Seeding the failure draw on cell_id alone would make a doomed
        # cell fail identically on every retry, and the backoff path would never
        # be seen to recover.
        self._attempts: dict[str, int] = {}
        if self.mode not in {"answer", "judge"}:
            raise ValueError(f"mock provider {cfg.id!r}: params.mode must be answer or judge")

    # -- helpers -------------------------------------------------------------

    def _rng(self, *parts: Any) -> random.Random:
        return random.Random(_seed_int(self.seed, self.id, *parts))

    def _maybe_fail(self, rng: random.Random) -> None:
        if self.failure_rate > 0 and rng.random() < self.failure_rate:
            raise TransientProviderError(
                f"mock injected failure (status {self.failure_status})",
                status_code=self.failure_status,
            )

    # -- answer mode ---------------------------------------------------------

    def _answer(self, req: CompletionRequest) -> str:
        meta = req.meta
        # Seeded WITHOUT polarity: the underlying belief is a property of the
        # claim, so the stance flips with polarity and consistency is meaningful.
        belief_rng = self._rng(
            "belief", meta.get("question_id"), meta.get("perspective_id"), meta.get("provider_id")
        )
        base_stance = belief_rng.choice([-2, -1, -1, 0, 1, 1, 2])

        draw_rng = self._rng(
            "draw",
            meta.get("question_id"),
            meta.get("perspective_id"),
            meta.get("provider_id"),
            meta.get("run_index"),
            meta.get("polarity"),
        )
        stance = -base_stance if meta.get("polarity") == "neg" else base_stance
        # Run-to-run wobble, so the D duplicates have something to measure.
        if draw_rng.random() < self.flip_noise:
            stance = max(-2, min(2, stance + draw_rng.choice([-1, 1])))

        if draw_rng.random() < self.refusal_rate:
            return (
                "I am not comfortable taking a position on this framed as a personal "
                "view. [[stance=0]] [[refusal]]"
            )

        body = _AGREE_TEMPLATES[stance].format(reason=draw_rng.choice(_REASONS))
        return f"{body} [[stance={stance}]]"

    # -- judge mode ----------------------------------------------------------

    def _judge(self, req: CompletionRequest) -> str:
        blob = "\n".join(m.get("content", "") for m in req.messages)
        rng = self._rng("judge", req.meta.get("cell_id"), blob[:256])

        match = MARKER_RE.search(blob)
        if match:
            score = int(match.group(1))
        else:
            score = rng.choice([-2, -1, 0, 1, 2])
        refusal = "[[refusal]]" in blob

        payload = {
            "agreement_score": score,
            "refusal": refusal,
            "non_responsive": False,
            "justification_quality": rng.choice([2, 3, 3, 4, 5]),
            "rationale": "mock judgement derived from the embedded stance marker",
        }
        # A re-prompted judge complies, as a real one usually does, so the repair
        # path is exercised end to end rather than failing identically twice.
        being_repaired = "could not be parsed as JSON" in blob
        if not being_repaired and self.malformed_rate > 0 and rng.random() < self.malformed_rate:
            # Truncated JSON wrapped in prose: the realistic failure mode.
            return "Here is my assessment: " + json.dumps(payload)[:-1]
        return json.dumps(payload)

    # -- interface -----------------------------------------------------------

    async def _call(self, req: CompletionRequest) -> CompletionResult:
        key = str(req.meta.get("cell_id"))
        nth = self._attempts.get(key, 0)
        self._attempts[key] = nth + 1
        rng = self._rng("fail", key, req.meta.get("attempt_epoch"), nth)
        self._maybe_fail(rng)
        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000.0)

        text = self._judge(req) if self.mode == "judge" else self._answer(req)

        prompt_chars = len(req.system or "") + sum(len(m.get("content", "")) for m in req.messages)
        return CompletionResult(
            text=text,
            input_tokens=max(1, prompt_chars // 4),
            output_tokens=max(1, len(text) // 4),
            model_reported=self.model,
            finish_reason="stop",
            provider_request_id=f"mock-{_seed_int(req.meta.get('cell_id'), self.id) % 10**10:010d}",
        )
