"""Adapter lookup.

Imports are lazy so the mock pipeline runs with no vendor SDK installed, and so
a missing optional dependency only breaks the provider that needs it.
"""

from __future__ import annotations

from typing import Callable

from ..config import ProviderCfg
from .base import BaseProvider

ADAPTERS = ("mock", "anthropic", "openai", "openai_compatible", "google")


def _load(adapter: str) -> Callable[[ProviderCfg], BaseProvider]:
    if adapter == "mock":
        from .mock import MockProvider

        return MockProvider
    if adapter == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider
    if adapter == "openai":
        from .openai import OpenAIProvider

        return OpenAIProvider
    if adapter == "openai_compatible":
        from .openai import OpenAICompatibleProvider

        return OpenAICompatibleProvider
    if adapter == "google":
        from .google import GoogleProvider

        return GoogleProvider
    raise ValueError(f"unknown adapter {adapter!r}; known adapters: {', '.join(ADAPTERS)}")


def build_provider(cfg: ProviderCfg) -> BaseProvider:
    return _load(cfg.adapter)(cfg)
