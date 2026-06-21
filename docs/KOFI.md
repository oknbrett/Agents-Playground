# Kofi — external research agent (BUILT · v1)

> Last updated: 2026-06-21. v1 built: Kofi is a tool Lily calls
> (`external_research`), backed by Anthropic's native web search. Needs
> `ANTHROPIC_API_KEY` to run.

## What Kofi is

Kofi is a **web-search research tool** that Lily dispatches when she needs external
context the internal data can't provide. He is **not** a chat agent — the planner
never talks to Kofi directly. Lily is the brain; Kofi is a pair of hands that go
fetch information from the outside world.

Lily already covers the *internal* picture: forecast, actuals, accuracy, budget,
inventory. But she has zero visibility into *why* demand might move — seasonality
shifts, weather, competitor activity, market trends, regulatory changes, pricing
moves. That's Kofi's job.

**Examples of what Kofi researches:**
- What does the upcoming season look like for garden/plant products?
- What's the weather forecast for the Netherlands this spring?
- How are competitors (Scotts Miracle-Gro, etc.) performing this quarter?
- Are there regulatory or supply-chain disruptions in the category?
- What are retail partners signaling about shelf resets or promotions?

## Architecture — Kofi is a tool, not a conversation

```
┌─────────────────────────────────────────────────────┐
│                  Planner (user)                     │
│               talks only to Lily                    │
└──────────────────────┬──────────────────────────────┘
                       │
              ┌────────▼────────┐
              │      Lily       │
              │  (the brain)    │
              │  reasons over   │
              │  internal data  │
              │  + Kofi results │
              └───┬─────────┬───┘
                  │         │
          ┌───────▼──┐  ┌───▼───────┐
          │  Kofi A  │  │  Kofi B   │   ← parallel dispatches
          │ (search) │  │ (search)  │
          └──────────┘  └───────────┘
```

- **Kofi lives behind a tool call.** Lily calls something like
  `external_research(query, context)` — Kofi spins up, does his web-search loop,
  and returns a structured findings report. Lily never sees the raw search results
  or intermediate pages.
- **Parallel Kofis.** Lily can fire multiple research requests simultaneously —
  e.g., one for seasonality trends and one for competitor earnings — and synthesize
  both results when they come back.
- **Context stays tight.** Kofi's return payload is a distilled summary (~200–500
  tokens), not the 20 search results he waded through. Lily's context window stays
  lean.
- **Debate/challenge stays with Lily.** The "thinking partner" / "debate the
  recommendation" role is a prompt skill for Lily, not a separate agent. She already
  has the numbers and now she has Kofi's external context — she does the reasoning.

## How the tool works (design)

### Input (what Lily sends Kofi)

```json
{
  "query": "garden product demand seasonality Netherlands spring 2026",
  "context": {
    "material_id": "10042N",
    "product_family": "Potting Soil — Indoor",
    "current_recommendation": "RAISE",
    "key_signal": "YoY growth +18%, planner override +12% above statistical"
  }
}
```

Lily crafts the query. The `context` block gives Kofi enough to know *why* she's
asking, so he can focus his search and flag anything that contradicts the internal
picture.

### Output (what Kofi returns to Lily)

```json
{
  "findings": [
    {
      "topic": "Seasonal outlook",
      "summary": "Dutch meteorological service forecasts warmer-than-average spring ...",
      "relevance": "Supports extended growing season → higher demand for indoor potting soil",
      "confidence": "medium",
      "sources": ["knmi.nl/...", "reuters.com/..."]
    }
  ],
  "conflicts_with_internal": [],
  "suggested_follow_up": null
}
```

- **Cited sources** — every finding links back to where it came from so the planner
  can verify.
- **Conflicts flag** — if Kofi finds something that contradicts Lily's current
  recommendation, it's called out explicitly so she can re-evaluate.
- **Follow-up** — Kofi can suggest a deeper research thread if initial results are
  inconclusive.

## Kofi's internal loop

1. Receive research prompt + context from Lily.
2. Evaluate: is the query well-scoped? Expand or refine if needed.
3. **Web search** (default behavior — always search first, never guess).
4. Read/scan top results.
5. Synthesize into structured findings with citations.
6. Flag any contradictions with the internal context Lily provided.
7. Return the distilled report.

Later enhancement: add a **deep research** skill for multi-hop queries (search →
read → follow links → search again), but v1 is a single search-and-summarize pass.

## Tech decisions

| Decision | Choice | Notes |
|---|---|---|
| **Relationship to Lily** | Tool, not agent. Lives behind `external_research`. | Planner never talks to Kofi directly. |
| **Search provider** | **Anthropic native web search** (`web_search_20250305` server tool). | No new API key — reuses `ANTHROPIC_API_KEY`. Native citations. Only active when the Anthropic backend's key is present; Cerebras/Groq-only setups would need an external search API (Tavily/Brave) added later. |
| **Where Kofi lives** | `agents/kofi/kofi.py`, registered in Lily's `TOOL_DISPATCH`. | Same backend, no separate server/endpoint. |
| **Model** | `claude-haiku-4-5-20251001` by default (lighter/cheaper — summarization, not deep reasoning). Override with `KOFI_MODEL`. | Kofi runs many searches; keep per-call cost low. |
| **Cost control** | Per-dispatch caps (`KOFI_MAX_SEARCHES`=5, `MAX_PAUSE_CONTINUATIONS`=6) + Kofi's tokens **and** web-search fees fold into Lily's existing daily spend cap. | `costing.py` now counts `web_search_requests` at $10/1k. The daily cap only guards the Anthropic Lily backend; on free backends Kofi is bounded by the per-dispatch caps only. |
| **Context isolation** | Lily passes a small `context` dict (~100 tokens), Kofi returns a distilled findings JSON (~200–500 tokens). Lily's window never sees raw search results. | This is the whole point of the architecture. |

## How to run / test

```bash
export ANTHROPIC_API_KEY=...                # Kofi needs this for web search
# standalone:
python agents/kofi/kofi.py --query "Dutch garden-product demand outlook spring 2026" \
  --material 10042N --signal "YoY +18%, planner override +12% over statistical"
# via Lily: just ask her something market-facing in the web app / CLI and she'll
# dispatch external_research herself when a signal looks externally driven.
```

## Open questions / next steps

- **How Lily decides to call Kofi** — currently autonomous (the tool description
  tells her when external context is relevant) and the planner can also ask. Watch
  real transcripts to see if she over- or under-calls and tune the description.
- **Free-backend support** — Anthropic web search only runs with `ANTHROPIC_API_KEY`.
  To let Kofi work on a Cerebras/Groq-only setup, add a Tavily/Brave provider behind
  the same `external_research` interface.
- **Deep research skill** — v2: multi-hop search (search → read → follow → search).
  v1 is a single search-and-summarize pass bounded by `KOFI_MAX_SEARCHES`.
- **Caching** — repeated "NL garden seasonality" lookups across SKUs could share a
  cached result with a TTL. Not built yet.
- ~~**Surface Kofi in the UI**~~ ✅ Done — the frontend shows "Kofi is researching:
  {query}..." as a distinct step label when Lily calls `external_research`.

## Status

**v1 built.** Files: `agents/kofi/kofi.py` (+ `__init__.py`), registered in
`agents/lily/lily.py` (`TOOL_DEFINITIONS` / `TOOL_DISPATCH` / `USAGE_AWARE_TOOLS`),
web-search cost accounting in `agents/lily/costing.py`. Runs on all three backends'
tool loops; live searches require `ANTHROPIC_API_KEY`.
