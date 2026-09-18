"""Google Gemini adapter (google-genai SDK).

Attribute access on the response is defensive because this adapter has not been
exercised against a live key in this repository -- see the adapter status table
in the README before trusting it in a paid run.
"""

from __future__ import annotations

from typing import Any

from .base import BaseProvider, CompletionRequest, CompletionResult


class GoogleProvider(BaseProvider):
    adapter_name = "google"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "the google adapter needs the 'google-genai' package: "
                "uv sync --extra providers"
            ) from exc

        self._genai = genai
        self._client = genai.Client(api_key=self.require_api_key())

    def _build_config(self, req: CompletionRequest) -> dict[str, Any]:
        params = dict(self.cfg.params or {})
        config: dict[str, Any] = {"max_output_tokens": req.max_tokens}
        if req.system:
            config["system_instruction"] = req.system
        if params.pop("send_temperature", True):
            config["temperature"] = req.temperature
        if params.pop("response_format", None) == "json":
            config["response_mime_type"] = "application/json"
        config.update(params)
        return config

    async def _call(self, req: CompletionRequest) -> CompletionResult:
        contents = [
            {"role": "user" if m.get("role") != "assistant" else "model",
             "parts": [{"text": m.get("content", "")}]}
            for m in req.messages
        ]
        resp = await self._client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=self._build_config(req),
        )

        text = getattr(resp, "text", None) or ""
        usage = getattr(resp, "usage_metadata", None)
        finish_reason = None
        candidates = getattr(resp, "candidates", None)
        if candidates:
            finish_reason = str(getattr(candidates[0], "finish_reason", "") or "") or None

        return CompletionResult(
            text=text,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            model_reported=getattr(resp, "model_version", None) or self.model,
            finish_reason=finish_reason,
            provider_request_id=getattr(resp, "response_id", None),
        )
