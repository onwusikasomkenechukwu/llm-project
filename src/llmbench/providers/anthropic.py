"""Anthropic adapter.

Two things worth knowing before changing this file:

  * SDK-level retries are disabled (max_retries=0). This harness owns retry and
    backoff, and records attempts_used and latency per call. Leaving the SDK's
    default of 2 in place would silently double the retry count and make the
    recorded latency uninterpretable.

  * Sampling parameters are rejected by current models. temperature/top_p/top_k
    return a 400 on Opus 5, Opus 4.8/4.7, Sonnet 5 and the Fable family. So
    temperature is sent only when explicitly configured, never by default.
"""

from __future__ import annotations

from typing import Any

from .base import BaseProvider, CompletionRequest, CompletionResult


class AnthropicProvider(BaseProvider):
    adapter_name = "anthropic"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "the anthropic adapter needs the 'anthropic' package: "
                "uv sync --extra providers"
            ) from exc

        self._client = AsyncAnthropic(
            api_key=self.require_api_key(),
            timeout=cfg.request_timeout_s,
            max_retries=0,
            base_url=cfg.base_url or None,
        )

    async def aclose(self) -> None:
        await self._client.close()

    def _build_kwargs(self, req: CompletionRequest) -> dict[str, Any]:
        params = dict(self.cfg.params or {})
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": req.max_tokens,
            "messages": req.messages,
        }
        if req.system:
            kwargs["system"] = req.system

        # Opt-in only: rejected with a 400 by current models.
        if params.pop("send_temperature", False):
            kwargs["temperature"] = req.temperature

        if params.pop("response_format", None) == "json":
            kwargs["output_config"] = {
                **params.pop("output_config", {}),
                "format": {"type": "json_schema", "schema": params.pop("json_schema", {})},
            }

        # Anything else in params (thinking, output_config.effort, ...) passes
        # through untouched, so the config can reach knobs this file predates.
        kwargs.update(params)
        return kwargs

    async def _call(self, req: CompletionRequest) -> CompletionResult:
        resp = await self._client.messages.create(**self._build_kwargs(req))

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        usage = getattr(resp, "usage", None)
        return CompletionResult(
            text=text,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            model_reported=getattr(resp, "model", None),
            finish_reason=getattr(resp, "stop_reason", None),
            provider_request_id=getattr(resp, "_request_id", None) or getattr(resp, "id", None),
        )
