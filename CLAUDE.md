# Agents Playground — Handoff

## What this project is

Testing whether an LLM agent can reason over demand planning data and suggest
whether a demand planner should **RAISE**, **LOWER**, or **KEEP** a forecast —
without being told about promotions, seasons, or any other business context.
The agent reads numbers only and has to figure out patterns itself.

This is a **reasoning test**, not a production system. No agent modifies data.
Everything is read-only.

---

## The agent: Lily

Lily is a demand planning analyst agent. She:
1. Loads a demand planning dataset (actuals + DP forecast + stat forecast + business plan)
2. Calls tools in a loop — her own choice, her own order — until she has enough evidence
3. Produces a structured recommendation per SKU: pattern detected, confidence, recommendation, reasoning, flags

**The key thing that makes her work:** the model drives the loop, not the platform.
She keeps calling tools until *she* decides she's done. This is what Copilot Studio
agents don't do — they're one-shot. Lily is not.

---

## Two versions, same tools and prompt

| File | Framework | Model | Status |
|---|---|---|---|
| `agents/lily/lily.py` | Anthropic SDK (raw loop) | Claude Sonnet 4.6 | ✅ Tested, 4/4 |
| `agents/lily/lily_msft.py` | Microsoft Agent Framework 1.0 | GPT-5 via Azure Foundry | ✅ Tested, working |

The tools (`agents/lily/tools.py`) and system prompt (`LILY_SYSTEM_PROMPT` in `lily.py`)
are **identical between both versions**. Only the model client and loop wiring differ.

---

## Test results (Anthropic version, Claude Sonnet)

All 4 test cases passed with strong reasoning:

**SKU001 — Premium Olive Oil** → RAISE
- Found P5 peaks at 1.75×, 1.69×, 1.73× baseline across 3 years, all 4 customers
- Correctly identified DP was under-forecasting P5 by ~55% in 2025
- Flagged that neither DP nor stat model captures the P5 pattern structurally

**SKU002 — Greek Yoghurt** → LOWER (smarter than expected)
- Found P8 2023 spike was 2.46× but reverted to 1.02× in 2024 — one-time event
- Caught that both DP and stat model are still contaminated by the 2023 spike
- Recommended lowering to ~6,200–6,350 baseline, not raising

**SKU005 — Protein Bar** → LOWER
- Stat MAPE: 1.9% vs DP MAPE: 15.3% — decisive gap
- Found a hidden DP error wave pattern (under-forecasts P1–P4, over-forecasts P5–P10) not designed into the data — emergent finding

**SKU006 — Cold Brew / Carrefour** → RAISE
- Isolated a customer-specific P11 peak (×2.10) visible only at Carrefour
- Other customers show no P11 uplift — had to drill to customer level to find it
- DP 2025 P11 at 969 vs stat at 1,493 and actuals historically ~1,519

**GPT-5 comparison (SKU001):**
- Found the same pattern, same numbers
- Said KEEP (overall DP fine) + flagged P5 structurally — more conservative than Claude's RAISE
- The loop worked the same way; reasoning depth was comparable

---

## Dataset

`data/demand_data.xlsx` — 1,248 rows, fully synthetic, seeded (reproducible).

**Schema:** period (1–13), year (2023–2025), sku_id, sku_name, customer, region,
actuals, dp_forecast, stat_forecast, business_plan

**Customers:** Carrefour (FR), Lidl (DE), Tesco (NL), Albert Heijn (NL)

**Hidden patterns per SKU (no label columns):**

| SKU | Pattern | Expected |
|---|---|---|
| SKU001 | P5 peak ×1.75 every year, all customers | RAISE |
| SKU002 | P8 spike 2023 only (×2.46), flat 2024 | LOWER (one-time) |
| SKU003 | +18% YoY growth, stat underestimates | RAISE |
| SKU004 | BP 24–28% over actuals every year | LOWER + flag BP |
| SKU005 | Stat MAPE 1.9% vs DP 15%+ | LOWER |
| SKU006 | Carrefour-only P11 peak ×2.10 | RAISE (Carrefour scope) |
| SKU007 | Declining −17%/yr, BP in denial | LOWER |
| SKU008 | Wide noise, no pattern | KEEP/UNCERTAIN |

Regenerate anytime: `python data/generate_dataset.py` (always identical, seed=42)

---

## Tools (agents/lily/tools.py)

Four pandas tools. Module-level `_df` populated by `load_data()` first.

| Tool | What it returns |
|---|---|
| `load_data(file_path)` | Dataset summary: SKUs, customers, years, actuals coverage |
| `get_sku_history(sku_id, customer?)` | Full time series + historical MAPE per forecast source |
| `analyze_period_pattern(sku_id, period, customer?)` | That period across all years + ratio vs baseline |
| `compare_forecasts(sku_id, year, customer?)` | MAPE + bias for DP vs stat vs BP, best source, interpretation hint |

Pre-computes ratios and MAPE so Lily doesn't have to do arithmetic — she reasons over results.

---

## How to run

**Anthropic version (Claude Sonnet):**
```bash
export ANTHROPIC_API_KEY=your_key
python agents/lily/lily.py --sku SKU001
python agents/lily/lily.py --sku SKU002
python agents/lily/lily.py --sku SKU006 --customer Carrefour
python agents/lily/lily.py --sku all
```

**Microsoft Agent Framework version (GPT-5 via Azure Foundry):**
```bash
export AZURE_AI_PROJECT_ENDPOINT="https://lilly-dev-resource.services.ai.azure.com/api/projects/lilly-dev"
python agents/lily/lily_msft.py --sku SKU001
```
Auth: opens a browser on first run — sign in with your Microsoft account (same as Foundry).

**Regenerate dataset:**
```bash
python data/generate_dataset.py
```

**Install deps:**
```bash
pip install -r requirements.txt
```

---

## Key decisions made

**Why the loop matters**
Copilot Studio agents are one-shot — platform controls when they stop.
Lily stops when *she* decides she has enough evidence. That's why she caught
the SKU002 model contamination and the SKU005 DP error wave — no one designed
those steps, she chose them.

**Why tools pre-compute ratios**
`analyze_period_pattern` returns `period_vs_baseline_ratio` already calculated.
`compare_forecasts` returns `interpretation_hint` ("stat outperforms DP by 13.4 MAPE points").
This keeps Lily's reasoning focused on *so what*, not arithmetic.

**Why the prompt bans cause-guessing**
`"Do not assume any pattern has a specific cause"` — forces her to cite numbers only.
Without this she'd say "probably a seasonal peak" and the reasoning becomes untestable.

**Why both versions exist**
Side-by-side A/B on same data, same prompt, same tools. Anthropic vs Microsoft,
Claude vs GPT-5. The architecture is identical; only the model differs.

---

## What's next / ideas

- [ ] Connect to a real database (Snowflake, Azure SQL, Databricks) instead of Excel
- [ ] SQL views as the data layer — one view per tool, pre-aggregated at scale
- [ ] Test on real demand data (your actual SKUs, customers, periods)
- [ ] Run all 8 SKUs end-to-end and score recommendations
- [ ] Add a web UI or Teams integration for demand planners to query Lily
- [ ] Explore hosting `lily_msft.py` as a deployed agent in Azure Foundry

---

## Azure Foundry project

Project: `lilly-dev`
Endpoint: `https://lilly-dev-resource.services.ai.azure.com/api/projects/lilly-dev`
Models deployed: GPT-5, Grok-4-20-reasoning
There is also a "Lilyyy" agent configured in the Foundry UI (separate from this codebase).

---

## Repo structure

```
Agents-Playground/
├── CLAUDE.md                      ← you are here
├── README.md                      ← public-facing summary
├── requirements.txt
├── data/
│   ├── generate_dataset.py        ← run to regenerate demand_data files
│   ├── demand_data.csv
│   └── demand_data.xlsx
└── agents/
    └── lily/
        ├── __init__.py
        ├── tools.py               ← all pandas logic, shared by both versions
        ├── lily.py                ← Anthropic SDK version (Claude Sonnet)
        └── lily_msft.py           ← Microsoft Agent Framework version (GPT-5)
```
