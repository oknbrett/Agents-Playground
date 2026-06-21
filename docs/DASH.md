# Dash — report & presentation builder (DESIGNED · building)

> Last updated: 2026-06-21. Design settled in session with Brett.

## What Dash is

Dash is a **report and presentation builder** that turns Lily's demand-planning
analysis into polished deliverables — **PPTX slide decks** and **PDF reports**.
He is a **separate chat agent**, not a tool Lily calls internally (unlike Kofi).

The planner reaches Dash one of two ways:
1. **Handoff from Lily** — after Lily finishes an analysis, the planner clicks
   "Hand off to Dash." Lily drafts a structured handoff doc (her findings, the
   numbers, the recommendation), and a **new chat** opens with Dash pre-seeded
   with that handoff.
2. **Direct start** — the planner opens a Dash chat directly and describes what
   they want built. No Lily context needed.

**Dash has no database access.** He never queries `lily.*` views or any data
tools. He works entirely from:
- The handoff doc Lily wrote, or
- Whatever the user tells him in the conversation.

His job is structure, layout, narrative, and design — not analysis.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Planner (user)                       │
│         ┌──────────────┐   ┌───────────────┐           │
│         │  Lily chat   │──▶│  Dash chat    │           │
│         │ (analysis)   │   │ (build deck)  │           │
│         └──────────────┘   └───────────────┘           │
│              │                    │                     │
│         uses Kofi tool      builds PPTX / PDF          │
│         uses data tools     NO data access              │
└─────────────────────────────────────────────────────────┘
```

- **Lily** is the analysis brain (data tools + Kofi for external research).
- **Dash** is the document builder (python-pptx + PDF generation).
- They don't share a conversation — Lily hands off via a structured doc.

## The handoff flow

### 1. Lily drafts the handoff

When the planner clicks "Hand off to Dash" after a Lily analysis, the frontend
asks Lily (or constructs from her last reply) a structured handoff document:

```json
{
  "type": "lily_handoff",
  "subject": "SKU 10042N — Potting Soil Indoor, FY2027 forecast review",
  "recommendation": "RAISE",
  "confidence": "HIGH",
  "key_findings": [
    "YoY actuals growth +18% across FY2025-26",
    "Planner override +12% above statistical — directionally right but may undershoot",
    "Budget gap: demand sits 8% below target in H1",
    "Kofi: warm spring forecast supports extended growing season"
  ],
  "numbers": {
    "trailing_12m_revenue": "€1.2M",
    "forecast_horizon": "FY2027 P1-P12",
    "wmape_lag2": "14%",
    "bias": "-6% (under-forecast)"
  },
  "suggested_deliverable": "Executive summary deck for planning review meeting"
}
```

### 2. Dash receives the handoff

A new chat opens. The handoff doc is injected as the first message (or system
context). Dash reads it and confirms what he'll build:

> "Got it — I'll build a forecast review deck for SKU 10042N (Potting Soil Indoor).
> 5 slides: title, situation overview, key findings, risk/opportunity, recommendation.
> Want me to go ahead, or adjust the structure first?"

### 3. The planner iterates with Dash

The planner can:
- Approve and let Dash build
- Adjust the structure ("add a competitive landscape slide," "make it 3 slides")
- Provide extra context Dash doesn't have ("add a note about the Q3 promo plan")
- Request a different format ("actually make it a one-page PDF briefing instead")

### 4. Dash delivers

Dash generates the file(s) and provides a download. The planner can request
revisions in the same chat.

## Output formats

| Format | Library | Notes |
|---|---|---|
| **PPTX** (PowerPoint) | `python-pptx` | Primary output. Clean, professional slides. |
| **PDF** (report) | `reportlab` or `weasyprint` | Written reports / one-pagers. |

## Dash's tools (internal)

Dash doesn't call external data tools, but he has his own document-building tools:

| Tool | What it does |
|---|---|
| `build_pptx(slides)` | Takes a structured slide spec and generates a .pptx file. |
| `build_pdf(sections)` | Takes structured sections and generates a PDF report. |
| `list_templates()` | Shows available deck/report templates. |

These are internal to Dash — the planner doesn't see them, just the output files.

## Tech decisions

| Decision | Choice | Notes |
|---|---|---|
| **Agent type** | Separate chat agent, own conversation. | NOT a tool Lily calls (unlike Kofi). Has its own system prompt, own chat history. |
| **Data access** | None. | Works from handoff text + user instructions only. No DB queries. |
| **Where Dash lives** | `agents/dash/dash.py` | Own module under `agents/`. |
| **Model** | Same as Lily's backend (Sonnet by default). | Document structure needs good reasoning, not just summarization — heavier than Kofi. |
| **Web app integration** | New chat route / tab. | "Hand off to Dash" button appears after Lily's analysis. Opens a new chat seeded with the handoff. User can also navigate to Dash directly. |
| **File delivery** | Generated files served via FastAPI endpoint. | `/api/dash/download/{file_id}` or similar. |

## Open questions / next steps

- **Templates** — should we ship a default PPTX template (branded, with master
  slides)? Or let Dash build from scratch every time? A template makes output
  more consistent but adds a design dependency.
- **Chart generation** — if the planner wants charts in the deck, Dash would need
  matplotlib/plotly to render them as images and embed. Worth adding in v1 or v2?
- **Direct-start flow** — when the user goes straight to Dash without Lily, what's
  the onboarding? Dash asks what they want to build and from what information?
- **Server routing** — Dash needs its own `/api/dash/chat` endpoint (or a mode
  flag on the existing `/api/chat`). Also needs a file-download endpoint.

## Status

Design settled. Building now.
