# Kofi — external research agent (DESIGNED · not yet built)

> Last updated: 2026-06-21. Design settled in session with Brett.

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
| **Relationship to Lily** | Tool, not agent. Lives behind a function call. | Planner never talks to Kofi directly. |
| **Search provider** | TBD — candidates: Tavily, Brave Search API, SerpAPI, Perplexity API | Need to evaluate cost, quality, rate limits. |
| **Where Kofi lives** | `agents/kofi/` module, called from Lily's tool dispatch | Same backend, no separate server. |
| **Model** | Can be lighter than Lily — summarization, not deep reasoning. Haiku-class or similar. | Cost optimization: Kofi runs many searches, keep per-call cost low. |
| **Cost control** | Per-call budget + daily cap (like Lily's `costing.py`) | Search API costs + model costs per dispatch. |
| **Context isolation** | Kofi gets ~100-token context from Lily, returns ~200-500 tokens. Lily's window never sees search noise. | This is the whole point of the architecture. |

## Open questions (for next session)

- **Search provider** — which API? Tavily is popular for agent use cases, Brave is
  cheap, Perplexity gives pre-synthesized answers. Need to pick one and test.
- **How Lily decides to call Kofi** — always (for every SKU analysis)? Only when she
  spots something unusual? Only when the planner asks? Probably: Lily decides
  autonomously but the planner can also request it.
- **Deep research skill** — v2 enhancement, multi-hop search for complex questions.
  Scope later.
- **Caching** — if Lily asks about "Netherlands garden seasonality" for SKU A and
  then SKU B, should Kofi cache the first result? Probably yes, with a TTL.

## Status

Design settled. Not yet built. Next steps:
1. Pick a search provider and get an API key.
2. Build `agents/kofi/` with the search loop + structured output.
3. Add `external_research` to Lily's tool definitions.
4. Wire into `server.py` (Kofi is internal to Lily's flow, no separate endpoint needed).
