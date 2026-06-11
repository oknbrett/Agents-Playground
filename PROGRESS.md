# PROGRESS.md — Lily Web App: Status & Handoff

> Last updated: 2026-06-12 · Repo: `oknbrett/agents-playground`

## What this is

Lily is a demand-planning reasoning agent: she reads sales history (actuals + DP forecast + stat forecast + business plan) and recommends **RAISE / LOWER / KEEP / UNCERTAIN** per SKU — from numbers only, no business context given. The core idea: **the model drives the analysis loop** — Lily keeps calling data tools until *she* decides she has enough evidence. This is what one-shot platforms (Copilot Studio) can't do, and it's why she catches things nobody designed into the test data.

Background: see `CLAUDE.md` and `README.md`.

## The four test scenarios (and how Lily performed)

The dataset is synthetic with hidden patterns baked in per SKU — no label columns, so Lily has to find them herself. We ran 4 of the 8 cases end-to-end:

**Test 1 — SKU001 (Premium Olive Oil): recurring seasonal peak**
*Designed:* every year, period 5 sells ~1.75× the baseline, across all customers. *Expected:* RAISE.
*Result:* ✅ **RAISE.** Lily found the P5 peaks at 1.75×, 1.69×, 1.73× across the 3 years, confirmed it held for all 4 customers, and quantified that the DP forecast was under-forecasting P5 2025 by ~55%. **Beyond expectations:** she also flagged that *neither* the DP nor the stat model captures the P5 pattern structurally — a model-quality observation we didn't design the test to check for.

**Test 2 — SKU002 (Greek Yoghurt): one-time spike, the trap case**
*Designed:* a single 2.46× spike in P8 2023 that never recurred. The trap: a naive analysis sees "P8 is big" and says RAISE. *Expected:* UNCERTAIN (recognize it as one-time).
*Result:* ✅ **LOWER — smarter than the designed answer.** Lily verified P8 reverted to 1.02× in 2024 (one-time event), then caught something we hadn't designed: both the DP and stat forecasts for 2025 are still *contaminated* by the 2023 spike — they're forecasting elevated volumes for an event that won't repeat. She recommended lowering to the ~6,200–6,350 baseline.

**Test 3 — SKU005 (Protein Bar): which forecast source to trust**
*Designed:* the statistical model is dramatically more accurate than the human DP forecast (MAPE 1.9% vs 15.3%). *Expected:* LOWER (defer to the stat model).
*Result:* ✅ **LOWER.** Found the accuracy gap decisively. **Beyond expectations:** she discovered a structured *error wave* in the DP forecast — systematic under-forecasting in P1–P4 and over-forecasting in P5–P10 — a pattern that was never designed into the data. It emerged from the noise generation, and she found it unprompted.

**Test 4 — SKU006 (Cold Brew / Carrefour): customer-specific pattern**
*Designed:* a P11 peak (×2.10) that exists *only* for Carrefour — invisible in the aggregate. Tests whether she drills down to customer level. *Expected:* RAISE, scoped to Carrefour.
*Result:* ✅ **RAISE (Carrefour scope).** She isolated the peak at Carrefour, verified other customers show no P11 uplift, and quantified the gap: DP 2025 P11 at 969 vs ~1,519 historical actuals.

**Cross-model comparison (SKU001, same tools + prompt):** GPT-5 via the Microsoft Agent Framework found the same pattern with the same numbers but said KEEP (overall forecast fine) while flagging P5 — more conservative than Claude's RAISE. The loop architecture worked identically on both; reasoning depth was comparable. Takeaway: the architecture transfers across models, and model choice changes the risk posture of recommendations.

**Score: 4/4 correct, with two emergent findings (SKU002 contamination, SKU005 error wave) that exceeded the designed expectations.** Both emergent findings trace back to the same capability: Lily loops until *she* decides she has enough evidence — the ability we lacked in Copilot Studio.

## Deployment direction

Two paths were explored, and both remain viable:

| Path | Status |
|---|---|
| **Internal web app (current)** | ✅ Active. Full loop control, model freedom (Claude or GPT-5), custom UI showing Lily's reasoning steps. |
| **Azure Foundry Hosted Agent → Teams** | 🔄 Open. This is *why* `lily_msft.py` exists on the Microsoft Agent Framework — Lily can be containerized and deployed to Foundry Agent Service with a Teams channel later, same tools and prompt. |
| Copilot Studio | ❌ Ruled out: one-shot agents — the platform controls when the agent stops, which kills the multi-step reasoning loop that produced the results above. |

**Why web-app-first:** the channel is not the product — the reasoning is. A web app is zero-friction (everyone can open a URL, same as ChatGPT), ships fastest, and gives us full control of the UX while we prove value. If Teams presence becomes a requirement, we have two routes ready: embed the web app as a Teams tab, or deploy `lily_msft.py` as a Foundry Hosted Agent — without rebuilding anything.

## What's built (this week)

1. **Chat web app** (`web/`) — React + Vite, minimalist ChatGPT-style UI
2. **API backend** (`server.py`) — FastAPI wrapping Lily's loop; stateless `/api/chat` + streaming `/api/chat/stream` (SSE)
3. **Adaptive looping** — conversational by default; the tool-analysis loop only triggers when the question needs data. The model decides — no router
4. **Live "thinking steps" UI** — tool calls stream into the chat as Lily works ("Reading history for SKU001…"), so planners see *how* she reached the conclusion
5. **Cost guardrails** (`agents/lily/costing.py`) — per-reply cost shown in the UI, daily spend ledger, $2/day cap (`LILY_DAILY_USD_CAP`), `GET /api/usage`
6. **Eval harness** (`evals/run_evals.py`) — scores Lily against all 8 SKUs' ground truth, prints scorecard + cost. `--list` previews cases for free

## Scaling: how Lily handles a million rows

**She never sees them — that's the entire trick.** Lily's tools don't return rows; they return pre-computed summaries (`analyze_period_pattern` returns a ratio, `compare_forecasts` returns a MAPE). Her token cost is roughly constant whether the table has 1,200 rows or 10 million, because raw data never enters the model's context.

Scaling is therefore a **data-layer problem, not a model problem**. The plan for real data:

- **Pre-aggregated SQL views, roughly one per tool**, in the database (Snowflake / Azure SQL / Databricks):
  - `v_sku_history` — actuals/forecasts by SKU × period × year × customer
  - `v_period_patterns` — period-vs-baseline ratios pre-computed
  - `v_forecast_accuracy` — MAPE + bias per forecast source per SKU per year
- The tools change from "pandas over Excel" to thin SQL queries against those views. **Lily's prompt, loop, and UI don't change at all.** The database does the heavy lifting it was built for; Lily does the reasoning.

**The real scaling question is SKU count, not row count.** One Lily analysis is cheap; "analyse all SKUs" across thousands of real SKUs is thousands of agent runs. Likely answer: a two-tier design — a cheap screening pass (simple stats or a small model) shortlists the SKUs worth attention, then full Lily reasoning runs only on those. To be worked out with the team.

## Reusability: Lily as a template

The architecture is domain-agnostic. What transfers to any future analysis agent as-is: the agent loop, streaming/steps UI, backend, cost meter, and eval-harness pattern, plus the prompt *principles* (quantify everything, cite tool results, never guess causes, structured output). What changes per agent: the tools (data access) and the domain content of the prompt. The skeleton is free; writing good tools for a new domain is where the effort goes.

## Verified vs. pending

✅ Verified without API spend: UI ↔ backend ↔ agent loop ↔ Anthropic API, all plumbing confirmed to the billing layer.
⏳ **Blocked on API credit**: first live streamed chat + the full 8-SKU eval run (expect ~$0.20–0.40).

## Next steps

1. Top up Anthropic credit → live chat + 8-SKU eval → capture the scorecard
2. **Real dataset** (~100k rows, expected soon) → only `agents/lily/tools.py` needs rework; web app, backend, prompt all stay
3. Scaling design with the team: pre-aggregated views + two-tier screening (see Scaling section)
4. Polish: conversation persistence, markdown rendering of replies
5. Deploy internally (server/domain TBD); Teams tab or Foundry Hosted Agent if needed later

## Running it locally (Mac)

```bash
cd agents-playground
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # from Anthropic console
uvicorn server:app --reload --port 8000

# second terminal
cd web && npm install && npm run dev
```
