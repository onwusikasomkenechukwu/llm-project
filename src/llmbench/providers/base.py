"""The one interface every provider implements.

Adding a provider -- including a local model served over HTTP later -- means
writing a subclass with a single `_call` method and registering it. Nothing
outside this package knows which vendor is answering.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

from ..config import ProviderCfg


class MissingApiKey(RuntimeError):
    pass


@dataclass
class CompletionRequest:
    """Everything that is sent to a model, plus metadata that never is.

    `meta` carries grid coordinates for the mock provider and for logging. Real
    adapters must not put it on the wire.
    """

    system: str | None
    messages: list[dict[str, str]]
    max_tokens: int
    temperature: float
    meta: dict[str, Any] = field(default_factory=dict)

    def wire_payload(self) -> dict[str, Any]:
        """Exactly what is recorded as `prompt` on the response row."""
        return {
            "system": self.system,
            "messages": self.messages,
            "params": {"max_tokens": self.max_tokens, "temperature": self.temperature},
        }


@dataclass
class CompletionResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model_reported: str | None = None
    finish_reason: str | None = None
    provider_request_id: str | None = None


class BaseProvider:
    """Owns its own concurrency limit, so the cap holds no matter who calls."""

    adapter_name = "base"

    def __init__(self, cfg: ProviderCfg) -> None:
        self.cfg = cfg
        self.id = cfg.id
        self.model = cfg.model
        self._semaphore = asyncio.Semaphore(cfg.max_concurrency)

    # -- subclass hooks ------------------------------------------------------

    async def _call(self, req: CompletionRequest) -> CompletionResult:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None

    # -- public --------------------------------------------------------------

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        async with self._semaphore:
            return await self._call(req)

    def require_api_key(self) -> str:
        if not self.cfg.api_key_env:
            raise MissingApiKey(
                f"provider {self.id!r} needs api_key_env set in the config"
            )
        key = os.environ.get(self.cfg.api_key_env, "")
        if not key:
            raise MissingApiKey(
                f"environment variable {self.cfg.api_key_env} is empty or unset "
                f"(needed by provider {self.id!r}). See .env.example."
            )
        return key

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id} model={self.model}>"
