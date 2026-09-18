"""OpenAI adapter, and the OpenAI-compatible adapter that a local model uses.

`openai_compatible` is the same wire format pointed at a base_url, which is what
vLLM, Ollama and llama.cpp all serve. Adding the local model later is a config
entry plus an API key env var that the server ignores -- no new code.
"""

from __future__ import annotations

from typing import Any

from .base import BaseProvider, CompletionRequest, CompletionResult


class OpenAIProvider(BaseProvider):
    adapter_name = "openai"
    requires_key = True

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "the openai adapter needs the 'openai' package: uv sync --extra providers"
            ) from exc

        key = self.require_api_key() if self.requires_key else self._optional_key()
        self._client = AsyncOpenAI(
            api_key=key,
            timeout=cfg.request_timeout_s,
            max_retries=0,  # this harness owns retry; see the anthropic adapter
            base_url=cfg.base_url or None,
        )

    def _optional_key(self) -> str:
        import os

        if not self.cfg.api_key_env:
            return "not-needed"
        return os.environ.get(self.cfg.api_key_env) or "not-needed"

    async def aclose(self) -> None:
        await self._client.close()

    def _build_kwargs(self, req: CompletionRequest) -> dict[str, Any]:
        params = dict(self.cfg.params or {})
        messages = list(req.messages)
        if req.system:
            messages = [{"role": "system", "content": req.system}] + messages

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": req.max_tokens,
        }
        if params.pop("send_temperature", True):
            kwargs["temperature"] = req.temperature
        if params.pop("response_format", None) == "json":
            kwargs["response_format"] = {"type": "json_object"}
        kwargs.update(params)
        return kwargs

    async def _call(self, req: CompletionRequest) -> CompletionResult:
        resp = await self._client.chat.completions.create(**self._build_kwargs(req))

        choice = resp.choices[0] if resp.choices else None
        text = (getattr(choice.message, "content", None) or "") if choice else ""
        usage = getattr(resp, "usage", None)
        return CompletionResult(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model_reported=getattr(resp, "model", None),
            finish_reason=getattr(choice, "finish_reason", None) if choice else None,
            provider_request_id=getattr(resp, "id", None),
        )


class OpenAICompatibleProvider(OpenAIProvider):
    """Same wire format, arbitrary base_url, key optional.

    This is the seam the local model plugs into: point base_url at the vLLM or
    Ollama server and nothing else in the harness changes.
    """

    adapter_name = "openai_compatible"
    requires_key = False

    def __init__(self, cfg) -> None:
        if not cfg.base_url:
            raise ValueError(
                f"provider {cfg.id!r} uses adapter openai_compatible, which requires "
                "base_url (e.g. http://localhost:8000/v1)"
            )
        super().__init__(cfg)
