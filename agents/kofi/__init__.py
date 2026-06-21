"""Kofi — external web-research agent that Lily dispatches as a tool.

Kofi reaches *outside* the internal demand data (seasonality, weather,
competitor activity, market/category news) using Anthropic's native web
search, and returns distilled, cited findings. He is not a chat agent — the
planner never talks to Kofi directly; Lily calls him via `external_research`.

The .env loading lives in agents.lily (imported by the backends), so by the
time Kofi runs ANTHROPIC_API_KEY is already in os.environ.
"""

from agents.kofi.kofi import external_research

__all__ = ["external_research"]
