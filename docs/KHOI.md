# Khoi — next agent to integrate (PLANNED · scoping)

> **This is the next-session topic.** When Brett opens a new session and points here,
> the agenda is: **design how Khoi integrates with Lily.** Brett will describe Khoi in
> detail — the notes below are a stub to fill in, not a spec yet. Nothing is built.

## What Khoi is (one-liner — Brett to expand)

A **thinking partner for the demand planner**. Where **Lily** reasons over the
*internal* numbers (forecast, actuals, accuracy, budget, inventory), **Khoi reaches
outside the data** — **web search** and external context — to help the planner think.
(Full scope to be described by Brett.)

## Open questions to settle next session

- **Scope** — what does Khoi actually do? Market / competitor / weather / news / pricing
  context? Brainstorming? Challenging the planner's assumptions? Explaining *why* demand
  might move that the numbers can't show?
- **Relationship to Lily** — separate agent, a tool Lily can call, or a mode of the same
  chat? Shared conversation or its own surface in the web app?
- **Web search** — which search tool/API; what triggers a search; how results are grounded
  and **cited** so the planner can trust them.
- **Boundary between the three layers** — Khoi (external/qualitative context) vs Lily
  (internal numbers) vs the planned **memory layer** (`docs/MEMORY_DESIGN.md`, the "why"
  humans record). How do they fit without overlap?
- **Tech** — search provider + cost; where Khoi runs (same FastAPI backend + a new module
  under `agents/`? shares the `server.py` auto-select + spend cap?).
- **Output** — how Khoi's findings feed an actual forecast decision (RAISE/LOWER/KEEP).

## Status

Not started. Awaiting Brett's detailed description of Khoi next session.
