"""Cost estimation.

Prices come from the config, never from a table baked into the code: the
numbers reported in a paper have to be reproducible from the config file months
later, after the vendors have changed their price lists.
"""

from __future__ import annotations

from .config import PricingCfg

# Rough characters-per-token for pre-call estimates only. This is deliberately
# not a real tokenizer: it exists to reserve budget before a call, and it is
# reconciled against the provider's own token counts immediately afterwards.
CHARS_PER_TOKEN = 3.6


def cost_usd(input_tokens: int, output_tokens: int, pricing: PricingCfg) -> float:
    return (
        input_tokens * pricing.input_per_mtok / 1_000_000.0
        + output_tokens * pricing.output_per_mtok / 1_000_000.0
    )


def estimate_input_tokens(*texts: str | None) -> int:
    chars = sum(len(t) for t in texts if t)
    return max(1, int(chars / CHARS_PER_TOKEN) + 1)


def precall_estimate(
    input_tokens_est: int,
    max_output_tokens: int,
    pricing: PricingCfg,
    headroom: float = 1.15,
) -> float:
    """Worst-case cost of a call that has not happened yet.

    Output tokens are unknowable in advance, so this assumes the full
    max_tokens. With headroom applied, this is what gets reserved against the
    spend cap at dispatch -- reserving at dispatch rather than at completion is
    what stops C in-flight calls from overshooting the cap by C calls' worth.
    """
    return cost_usd(input_tokens_est, max_output_tokens, pricing) * headroom
