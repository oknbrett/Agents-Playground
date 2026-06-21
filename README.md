# Agents Playground

A multi-agent demand-planning system. Three agents work together to help
planners analyse forecasts, research market context, and build deliverables.

---

## The agents

| Agent | Role | Type | Model |
|---|---|---|---|
| **Lily** | Demand-planning analyst — reads forecast, actuals, accuracy, budget, inventory. 15 tools. The brain. | Chat agent | Claude Sonnet 4.6 (or Cerebras/Groq free) |
| **Kofi** | External web-research — Lily dispatches him for market context (season, weather, competitors). | Tool (behind `external_research`) | Claude Haiku 4.5 |
| **Dash** | Report & presentation builder — PPTX slide decks and PDF reports. | Chat agent | Claude Sonnet 4.6 |

**Lily** is the main analyst. She calls **Kofi** as a tool when she needs
external context. The planner can hand off Lily's analysis to **Dash** to turn
it into a slide deck or report. Dash can also be used directly.

Both Lily and Dash support **ask_planner** — interactive structured choices
where the agent pauses and asks the planner to pick a direction before continuing.

---

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Build the synthetic database (~1.14M rows, 200 SKUs)
python sql/generate_synthetic.py

# 3. Set your API key
export ANTHROPIC_API_KEY=your_key_here

# 4. Run the web app
uvicorn server:app --reload --port 8000
# second terminal:
cd web && npm install && npm run dev
# Open http://localhost:5173
```

### Free backends (no Anthropic key needed for Lily)

```bash
# Cerebras (recommended free path, ~1M tokens/day)
export CEREBRAS_API_KEY=...    # https://cloud.cerebras.ai
# Groq (100K tokens/day)
export GROQ_API_KEY=...        # https://console.groq.com
```

Note: Kofi (web search) and Dash always require `ANTHROPIC_API_KEY`.

### CLI

```bash
python agents/lily/lily.py --sku 10000N           # Lily (paid)
python agents/lily/lily_cerebras.py --sku 10000N   # Lily (free)
python agents/kofi/kofi.py --query "Dutch garden-product demand outlook spring 2026"
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Planner (user)                     │
│         ┌──────────────┐   ┌───────────────┐       │
│         │  Lily chat   │──▶│  Dash chat    │       │
│         │ (analysis)   │   │ (build deck)  │       │
│         └──────┬───────┘   └───────────────┘       │
│                │                                    │
│         calls Kofi tool              builds PPTX/PDF│
│         calls data tools             NO data access │
└─────────────────────────────────────────────────────┘
```

---

## Documentation

| Doc | What it covers |
|---|---|
| **[`CLAUDE.md`](CLAUDE.md)** | Full project handoff — data model, tools, backends, key decisions |
| **[`PROGRESS.md`](PROGRESS.md)** | Running status log |
| **[`docs/KOFI.md`](docs/KOFI.md)** | Kofi design doc (v1 built) |
| **[`docs/DASH.md`](docs/DASH.md)** | Dash design doc (v1 built) |
| **[`docs/MEMORY_DESIGN.md`](docs/MEMORY_DESIGN.md)** | Team-shared memory plan (not built) |
| **[`sql/DATA_MODEL.md`](sql/DATA_MODEL.md)** | Column-level reference for the SAP sample tables |
