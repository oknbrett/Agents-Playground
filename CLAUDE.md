# Agents Playground — Handoff

> 🟢 **NEXT UP — Kofi integration.** The current focus is adding **Kofi**, a **web-search
> research tool** that Lily dispatches when she needs external context (seasonality, weather,
> competitor activity, market trends). Kofi is a tool, not a chat agent — Lily calls him,
> he searches, returns a distilled report with citations. Design doc:
> **[`docs/KOFI.md`](docs/KOFI.md)**.

> Last refreshed: 2026-06-21. Lily is now **full-scope** (forward plan **and**
> backward forecast performance — Billy merged in) and runs on a **rich synthetic
> dataset** (`sql/generate_synthetic.py`, ~1.14M rows) built in the real warehouse
> shape. The real SAP sample tables are thinner — see "The data" below. Fiscal year
> starts **November**. See `PROGRESS.md` for the running log.

## What this project is

Testing whether an LLM agent can reason over demand-planning data and recommend
whether a planner should **RAISE / LOWER / KEEP** a forecast (or flag **UNCERTAIN**)
— from the numbers only, with no business context handed to it. The agent reads
finished numbers and has to figure out the picture itself.

**The key thing that makes it work:** the model drives the tool loop, not the
platform. Lily keeps calling tools — her choice, her order — until *she* decides
she has enough evidence. One-shot platforms (Copilot Studio) can't do this. This
is read-only: no agent modifies data.

---

## The agent: Lily (full-scope)

Lily is a **full-scope** demand-planning analyst — forward plan **and** backward
performance. She reads:
- the current **demand forecast** (forward periods, two cut versions),
- the **statistical baseline** (naive model) — demand − statistical = the planner's override,
- the **sales budget** (top-down finance target),
- current **inventory** (coverage),
- the **full actuals sales history** (3 years), and
- **past lagged forecasts** of closed periods → **forecast accuracy & bias** (lag-2 basis).

**Billy is merged in:** forecast accuracy/bias is now Lily's job, not a separate
backward agent. The only thing she still doesn't do is re-derive metrics by hand —
she reads pre-computed WMAPE / bias from the views. Read-only throughout.

---

## The data — two datasets

There are **two** datasets in this repo. Lily currently runs on the synthetic one.

### 1. Synthetic dev dataset — what Lily runs on now
**[`sql/generate_synthetic.py`](sql/generate_synthetic.py)** builds ~**1.14M rows** in
the real warehouse shape, loads them into `sql/lily_local.duckdb`, applies the views,
and verifies. Themed to Evergreen/Pokon, deliberately rich so Lily has real signal:

- **1 region** (`2510`), **25 customers**, **200 SKUs** with a 4-level product
  hierarchy (`dim_product`: L1 division → L4 product line).
- **3 years** of actuals (FY2024–26), **24 months** forward demand forecast (FY2027–28,
  2 cut versions), a **statistical baseline**, a **top-down budget**, an **inventory**
  snapshot, and **past lagged forecasts** (lags 1/2/3 → accuracy & bias).
- **Fiscal year starts November** (P1=Nov, P4=Feb, P7=May, P12=Oct).
- Baked-in signal: per-family seasonality, SKU lifecycles (growing/stable/declining/new),
  budget↔forecast divergence, planner overrides vs the model, flat-forecast & negative-
  margin traps, and lifecycle-driven forecast bias (growing under-forecast, declining over).
- Rebuild anytime (seeded, reproducible): `python sql/generate_synthetic.py`.

### 2. Real SAP sample tables — thinner, for shape reference
Four final-shape SAP fact tables Bart delivered (2026-06-17), single-org **shape
samples** — correct columns/grain but mostly disjoint, no history, no statistical
stream. Loaded by **[`sql/build_local_db.py`](sql/build_local_db.py)** (overwrites the
same `lily_local.duckdb`). **Column-level reference: [`sql/DATA_MODEL.md`](sql/DATA_MODEL.md).**
Run the synthetic generator to get the rich DB back.

Semantics (apply to both): **`sales_org` = region/BU** (`2510` ≈ NL / Evergreen Pokon);
**customer_code** (Triad Region) = the customer; **`material_id` = SKU** (string);
`fiscal_period_key` `202608` = P8 FY2026.

### Serving layer (Lily never sees raw rows or writes SQL)
- **[`sql/lily_views_runnable.sql`](sql/lily_views_runnable.sql)** — the ~17 `lily.*`
  views (foundation per stream + comparisons + accuracy/bias + cross-SKU/family scans).
  **Dialect-portable** — same file runs on DuckDB (dev) and Postgres (prod); moving
  over is a connection swap only.
- **[`sql/lily_view_catalog.md`](sql/lily_view_catalog.md)** — comparison design + readiness.

---

## Tools (`agents/lily/tools.py`)

Read-only queries against the `lily.*` views (DuckDB now, Postgres later — isolated
in one `_connect()`). All return decision-ready JSON; Lily never does SQL or math.

13 tools (defs + dispatch in `lily.py`, shared by all backends):

| Tool | What it returns |
|---|---|
| `get_overview()` | Regions, customer/material counts, horizon, latest actuals, which streams exist, fiscal calendar. Call first. |
| `get_forecast(material_id, …)` | Forward demand series + revenue/margin/price + shape summary. |
| `demand_vs_statistical(material_id, …)` | Demand vs the naive model baseline — the planner's override (RAISED/LOWERED/IN LINE). Period-grain. |
| `demand_vs_budget(material_id, …)` | Demand vs the top-down budget per period. Period-grain. |
| `inventory_coverage(material_id, …)` | Stock vs forward demand; coverage + STOCKOUT/OVERSTOCK (EA-guarded). |
| `product_economics(material_id, …)` | COGS, unit price, margin across the horizon. |
| `top_skus(fiscal_year, fiscal_period, …)` | Top-N SKUs in a period by qty or revenue. |
| `forecast_performance(material_id, …, lag=2)` | **Accuracy & bias** — WMAPE + signed bias + bias-by-period (lag-2). |
| `actuals_history(material_id, …)` | Full sales history per period + per-year totals + YoY. |
| `latest_actuals(material_id, …)` | The single latest closed-period actuals — anchor. |
| `sku_performance_scan(…)` | **Triage inputs** — per-SKU recent accuracy/bias + materiality (for "what to focus on"). |
| `family_scan(…)` | **Cross-family rollup** in one call — revenue, override %, YoY growth per family. |
| `divergence_scan(category?, …)` | **Cross-SKU scan** in one call — every SKU's override (+escalation), budget gap, revenue, YoY. Use instead of looping. |

`load_data()` is a thin back-compat alias of `get_overview`. For broad
("biggest family / where does it diverge") questions Lily uses `family_scan` →
`divergence_scan` rather than looping the per-SKU tools — complete coverage, far
cheaper. Period-grain aggregation on the `demand_vs_*` tools keeps payloads light.

---

## Three backends — same tools, same prompt

The system prompt (`LILY_SYSTEM_PROMPT`) and `TOOL_DEFINITIONS` / `TOOL_DISPATCH`
live in `lily.py`; the other two backends import them, so all three stay in sync.

| File | Framework | Model | Key | Cost |
|---|---|---|---|---|
| `agents/lily/lily.py` | Anthropic SDK (raw loop) | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | paid |
| `agents/lily/lily_cerebras.py` | Cerebras (OpenAI-compatible) | `gpt-oss-120b` | `CEREBRAS_API_KEY` | **free, ~1M tok/day** |
| `agents/lily/lily_groq.py` | Groq (OpenAI-style) | `llama-3.3-70b-versatile` | `GROQ_API_KEY` | free, 100K tok/day |
| `agents/lily/lily_msft.py` | Microsoft Agent Framework | `gpt-5` via Azure Foundry | Foundry auth | paid |

**`server.py` auto-selects** (free first): `ANTHROPIC_API_KEY` set → paid Claude
(explicit opt-in); else `CEREBRAS_API_KEY` → Cerebras; else `GROQ_API_KEY` → Groq.
Cerebras is the default free path (~1M tokens/day; **note its free tier caps
context at 8,192 tokens**, so it's sized for single-SKU questions, not huge
transcripts). The free backends let us run Lily live without burning Anthropic credit.

---

## How to run

**0. Build the local DB once** (needed by the tools):
```bash
pip install -r requirements.txt
python sql/generate_synthetic.py        # → sql/lily_local.duckdb (rich synthetic, ~1.14M rows)
# (or  python sql/build_local_db.py  for the thin real-SAP sample instead)
```

**1a. Free — Cerebras / gpt-oss-120b (recommended, ~1M tokens/day):**
```bash
# key in .env: CEREBRAS_API_KEY=...   (free, no card: https://cloud.cerebras.ai)
python agents/lily/lily_cerebras.py --sku 10000N    # CLI (Lily picks sales_org via tools)
```

**1a-alt. Free — Groq / Llama (100K tokens/day):**
```bash
# key in .env: GROQ_API_KEY=...        (https://console.groq.com)
python agents/lily/lily_groq.py --sku 10000N
```

**1b. Paid — Anthropic / Claude:**
```bash
export ANTHROPIC_API_KEY=...
python agents/lily/lily.py --sku 10000N
```

**2. Web app** (backend auto-selects per the keys above):
```bash
uvicorn server:app --reload --port 8000
# second terminal:
cd web && npm install && npm run dev
```

---

## Reasoning-test results (historical — on the earlier synthetic data)

Before the real data arrived, Lily was validated on a synthetic seeded dataset with
hidden patterns. She scored **4/4** and produced two findings nobody designed in —
evidence the loop earns its keep:
- **SKU001** → RAISE (found a recurring P5 peak ×1.75 across years/customers).
- **SKU002** → LOWER (caught a 2023-only spike *and* that both forecasts were still
  contaminated by it — smarter than the designed answer).
- **SKU005** → LOWER (decisive accuracy gap + an emergent DP error-wave pattern).
- **SKU006 / Carrefour** → RAISE (a customer-specific peak invisible in the aggregate).

GPT-5 on the same prompt/tools found the same numbers but was more conservative
(KEEP + flag). Takeaway: the architecture transfers across models; model choice
shifts the risk posture. These cases no longer run as-is (different schema, no
history) but the reasoning principles carry over.

---

## Memory (planned, not built)

A persistent, **team-shared** memory layer — the qualitative "why" the numbers
can't show (promotions, listings, deliberate overrides), cited back with
provenance. Full plan: **[`docs/MEMORY_DESIGN.md`](docs/MEMORY_DESIGN.md)**. Settled:
group = region/sales-org team; any planner can write/delete; two kinds of notes
(`stated` by a named human vs `inferred` by Lily, unconfirmed); stored in Postgres
+ self-hosted BGE-M3 embeddings; bi-temporal validity; top-k recall.

---

## Key decisions

- **Why the loop matters** — the model decides when it has enough evidence. That's
  what produced the emergent findings above and what Copilot Studio can't do.
- **Why pre-aggregated views** — Lily reads finished numbers, so her token cost is
  ~constant whether a table has thousands or millions of rows. Scaling is a
  data-layer problem, not a model problem.
- **Full-scope, Billy merged in** — Lily covers the forward plan AND backward
  forecast accuracy/bias (lag-2). The earlier Lily/Billy split was dropped: one
  analyst with the whole picture answers "what to focus on" far better.
- **Fiscal year starts November** (P1=Nov … P12=Oct). "Now" = the period after the
  latest closed actuals; that period anchors anything "recent".
- **Why three backends** — same architecture, swappable model; Groq gives a free
  path, Foundry a Microsoft-native deployment option, Anthropic the strongest reasoning.
- **Prompt principles** — quantify everything, cite tool numbers, never guess
  causes, be honest about data gaps, structured recommendation output.

---

## Repo structure

```
agents-playground/
├── CLAUDE.md                 ← you are here
├── PROGRESS.md               ← running status / handoff log
├── README.md  ·  requirements.txt  ·  server.py   (FastAPI backend, auto-selects model)
├── data/                     ← legacy synthetic dataset + generator (historical)
├── sql/
│   ├── generate_synthetic.py     ← build the rich synthetic DB (what Lily runs on)
│   ├── DATA_MODEL.md             ← column-level model of the real SAP sample tables
│   ├── lily_views_runnable.sql   ← the ~17 lily.* serving views (DuckDB + Postgres)
│   ├── lily_view_catalog.md      ← comparison design + readiness
│   ├── build_local_db.py         ← load the real SAP xlsx sample instead
│   └── RETROSPECTIVE.md
├── docs/
│   └── MEMORY_DESIGN.md          ← team-shared memory plan
├── evals/                    ← eval harness (synthetic-era; needs rework for new data)
├── web/                      ← React + Vite chat UI
├── agents/lily/
│   ├── tools.py              ← read-only view queries (shared by all backends)
│   ├── lily.py               ← Anthropic (Claude) — owns prompt + tool defs (incl. external_research)
│   ├── lily_groq.py          ← Groq (Llama, free)
│   ├── lily_msft.py          ← Microsoft Agent Framework (GPT-5 / Foundry)
│   └── costing.py            ← pricing + daily spend cap (tokens + web-search fees)
└── agents/kofi/
    └── kofi.py               ← external web-research agent; Lily's external_research tool (Anthropic web search)
```
