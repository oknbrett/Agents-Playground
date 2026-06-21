# Dash — report & presentation builder (BUILT · v1)

> Last updated: 2026-06-21. v1 built: agent loop, PPTX/PDF generation, file
> upload, ask_planner, full frontend integration with agent switcher and handoff.

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

## Dash's tools

4 tools defined in `agents/dash/dash.py`:

| Tool | What it does |
|---|---|
| `create_pptx(slides)` | Takes a structured slide spec and generates a .pptx file. 4 layout types: title, section, content, two_column. |
| `create_pdf(sections, title?)` | Takes structured sections and generates a PDF report. 6 section types: heading, subheading, body, bullet_list, spacer, hr. |
| `read_uploaded_file(file_path)` | Reads a user-uploaded file. Handles CSV/TSV/XLSX (returns structured table with columns + rows) and text/md/json (returns raw content). Max 50 rows for tabular data. |
| `ask_planner(question, options)` | Pause and ask the planner to choose a direction. Shared tool from `agents/shared/`. |

Implementation files:
- `agents/dash/build_pptx.py` — python-pptx builder, Evergreen palette (`#1B3A2D` / `#2E7D32` / `#E8F5E9`).
- `agents/dash/build_pdf.py` — reportlab builder.
- Output directory: `DASH_OUTPUT_DIR` env var or `/tmp/dash_output`.

## Tech decisions

| Decision | Choice | Notes |
|---|---|---|
| **Agent type** | Separate chat agent, own conversation. | NOT a tool Lily calls (unlike Kofi). Has its own system prompt, own chat history. |
| **Data access** | None. | Works from handoff text + user instructions only. No DB queries. |
| **Where Dash lives** | `agents/dash/dash.py` | Own module under `agents/`. |
| **Model** | `claude-sonnet-4-6` (override with `DASH_MODEL` env var). | Document structure needs good reasoning, not just summarization — heavier than Kofi. |
| **Web app integration** | Agent switcher + handoff button. | "Hand off to Dash" button on Lily's latest reply. Agent switcher pill in composer bar. User can also navigate to Dash directly via sidebar or switcher. |
| **File delivery** | `GET /api/dash/download/{filename}` | Generated files served via FastAPI `FileResponse`. |
| **File upload** | `POST /api/upload` → `read_uploaded_file` tool. | Files stored in `/tmp/dash_uploads` with UUID prefix. Frontend has drag-and-drop + attach button (Dash only). |
| **ask_planner** | Shared tool from `agents/shared/`. | Loop pauses, SSE event emitted, frontend renders choice cards. User's pick sent as regular text message — stateless. |

## Server endpoints

| Endpoint | Method | What it does |
|---|---|---|
| `/api/dash/chat/stream` | POST | SSE streaming chat — same contract as Lily's `/api/chat/stream` + `file_ready` and `ask_planner` event types. |
| `/api/dash/download/{filename}` | GET | Serves generated PPTX/PDF files. |
| `/api/dash/handoff` | POST | Converts a structured Lily handoff dict into a Dash opening message. |
| `/api/upload` | POST | File upload (multipart). Allowed extensions: csv, tsv, xlsx, xls, json, txt, md. Returns `{filename, path}`. |

## Frontend integration

- **Agent switcher** — pill in the composer bar shows current agent + model. Click
  to switch between Lily and Dash. Default = last-used agent (localStorage).
- **Handoff button** — "Hand off to Dash" appears on Lily's latest reply. Creates
  a new Dash chat pre-seeded with Lily's analysis and auto-sends.
- **File attach/drop** — Dash-only paperclip button + drag-and-drop on the composer.
  Uploads via `/api/upload`, injects `[Uploaded file: ... — path: ...]` into input.
- **FileCard** — download links rendered in the chat when Dash generates files.
- **AskPlannerCards** — interactive choice cards when Dash calls `ask_planner`.

## Open questions / next steps

- **Templates** — should we ship a default PPTX template (branded, with master
  slides)? Or let Dash build from scratch every time? A template makes output
  more consistent but adds a design dependency.
- **Chart generation** — if the planner wants charts in the deck, Dash would need
  matplotlib/plotly to render them as images and embed. Not in v1.
- **Live testing** — needs `ANTHROPIC_API_KEY` to test the full flow (handoff,
  document generation, ask_planner cards, file upload processing).

## Status

**v1 built.** Files: `agents/dash/dash.py`, `agents/dash/build_pptx.py`,
`agents/dash/build_pdf.py`, `agents/dash/__init__.py`, `agents/shared/__init__.py`.
Server endpoints in `server.py`. Frontend in `web/src/App.jsx` + `index.css`.
