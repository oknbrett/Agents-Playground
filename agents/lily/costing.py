"""Token usage accounting for Lily runs.

Single source of truth for model pricing, shared by the web backend
(server.py) and the eval harness (evals/run_evals.py).
"""

from __future__ import annotations

from typing import Any

# Claude Sonnet 4.6, USD per million tokens (api docs, 2026-06).
PRICE_PER_MTOK = {
    "input": 3.00,
    "output": 15.00,
    "cache_read": 0.30,   # ~0.1x input
    "cache_write": 3.75,  # 1.25x input (5-minute TTL)
}

# Anthropic native web search (Kofi), USD per 1,000 search requests. The model
# tokens Kofi spends are already counted via add_usage; this is the extra
# per-search fee on top. Token pricing here is Sonnet's — Kofi may run a cheaper
# model, so his token cost is a conservative (high) estimate, which is fine for a
# spend guard.
WEB_SEARCH_USD_PER_1K = 10.00


def new_usage() -> dict[str, int]:
    """A fresh usage accumulator, to pass into run_agent_loop(usage=...)."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "web_search_requests": 0,
        "turns": 0,
    }


def add_usage(acc: dict[str, int], response_usage: Any) -> None:
    """Fold one API response's usage block into an accumulator."""
    acc["input_tokens"] += getattr(response_usage, "input_tokens", 0) or 0
    acc["output_tokens"] += getattr(response_usage, "output_tokens", 0) or 0
    acc["cache_read_input_tokens"] += (
        getattr(response_usage, "cache_read_input_tokens", 0) or 0
    )
    acc["cache_creation_input_tokens"] += (
        getattr(response_usage, "cache_creation_input_tokens", 0) or 0
    )
    # Server-side tool use (e.g. Kofi's web searches) carries its own fee.
    server_tool_use = getattr(response_usage, "server_tool_use", None)
    if server_tool_use is not None:
        acc["web_search_requests"] += (
            getattr(server_tool_use, "web_search_requests", 0) or 0
        )
    acc["turns"] += 1


def cost_usd(usage: dict[str, int]) -> float:
    """Dollar cost of an accumulated usage dict."""
    token_cost = (
        usage["input_tokens"] * PRICE_PER_MTOK["input"]
        + usage["output_tokens"] * PRICE_PER_MTOK["output"]
        + usage["cache_read_input_tokens"] * PRICE_PER_MTOK["cache_read"]
        + usage["cache_creation_input_tokens"] * PRICE_PER_MTOK["cache_write"]
    ) / 1_000_000
    search_cost = (
        usage.get("web_search_requests", 0) * WEB_SEARCH_USD_PER_1K / 1_000
    )
    return token_cost + search_cost


def total_tokens(usage: dict[str, int]) -> int:
    return (
        usage["input_tokens"]
        + usage["output_tokens"]
        + usage["cache_read_input_tokens"]
        + usage["cache_creation_input_tokens"]
    )
