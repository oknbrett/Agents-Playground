# Handoff — Lily on real Postgres: region + hierarchy rollout

> Updated 2026-06-25. Start the next session by reading this file. The data layer
> is live on the real Azure warehouse; this session added region-scoping and a
> pre-aggregated product-hierarchy backbone. **Next up = option A: finish the
> node/category lift of the SKU views, then mirror to customer grain.**

## How to run the demo (servers are currently STOPPED)
```bash
# backend (live warehouse via Entra token):
LILY_USE_ENTRA=1 python -m uvicorn server:app --port 8000 --host 127.0.0.1
# frontend:
cd web && npm run dev          # → http://localhost:5173
```
- Auth: the `az` token lasts ~24h. If DB calls fail with "refresh token expired",
  run: `az login --tenant 082b2774-8177-4c5b-9144-5072d07332cd --use-device-code`.
- Backend auto-selects Anthropic (Sonnet 4.6) because `ANTHROPIC_API_KEY` is in `.env`.
  $2/day spend cap in `costing.py` (`LILY_DAILY_USD_CAP`).
- Do NOT add a health-check watchdog — it floods the console; the crash it guarded
  is fixed (see DB lock below).

## Key facts the next session needs
- **Regions** (sales_org code = region): 1010 Germany, **1110 UK**, 1210 France,
  1810 Poland, 1910 Austria, 2510 Benelux, 3010 Australia, **3710 Pokon**.
  Beta rollout is **Pokon (3710) users only**, but build region-agnostic.
- **Budget exists for Pokon (3710) + Benelux (2510) only** — other 6 regions have none.
- **FY starts October** (P1=Oct … P12=Sep). `fiscal_period_key` is **text** (`008.2026`),
  NOT chronologically sortable — order via `fiscal_year, fiscal_period`. "Now" = P8 FY2026.
- **No statistical-baseline stream.** Forecast = 11 weekly vintages; accuracy/bias
  rebuilt from vintages, lag-2.
- **Approved accuracy calc** (Romuald=analyst, Kenton=stats; spreadsheet
  `Demand Planning Query - Calculation Examples.xlsx`): BIAS = SUM(FC−Sales)/SUM(Sales);
  WMAPE/MAE at **MATERIAL×period grain** (sum customers FIRST, then abs); MAE capped at 1;
  **Accuracy = 1−MAE**; zero-actual (forecast-only) AND zero-forecast (actual-only) rows
  scored. ⚠️ **OPEN: spreadsheet says "Single or Twin structure (twin preferred)" — meaning
  unknown; ASK ROMUALD before any further accuracy-view restructure.**
- **DB connection is shared + serialized** with a lock (`_db_lock` in `tools.py`).
  Concurrent threads on one psycopg2 connection segfault the process — the lock fixes it.
  Don't remove it.

## What this session built (all live + verified, uncommitted bits now committed)
1. **Real-warehouse migration** — `sql/lily_views_pg.sql` (the prod views, applied to live
   DB via `apply_views.py`); `_connect()` Entra token; `?`→`%s` + Decimal→float fixes.
2. **Data-integrity audit** (Codex, `LILY_DATA_INTEGRITY_AUDIT_REPORT.md`) — 7 fixes
   (NULL unpriced revenue/margin, chrono ordering, full-outer demand-vs-budget, YTD-vs-YTD
   YoY, weighted family %, version-delta new/dropped, full-frame accuracy).
3. **Accuracy aligned to the approved calc** — material grain + capped `accuracy_pct`.
4. **Economics fix** — `vw_product_economics` computes over PRICED periods only (revenue is
   loaded for ~7 of 24 forecast periods; averaging over all faked a loss).
5. **Crash fix** — the `_db_lock` above (was a silent segfault on Lily→Dash / concurrent use).
6. **Streaming UI** — interleaved play-by-play timeline (narration + expandable action chips);
   fixed the missing `@keyframes lilyspin` so spinners rotate (`web/src/App.jsx`, `index.css`).
7. **Orientation** — data landscape injected into the system prompt (`server.py _data_landscape`),
   so Lily NO LONGER calls get_overview to "explore" — she starts oriented.
8. **Region scoping** — correct region map in the prompt (UK=1110, not the old wrong 2510=UK);
   `family_scan`, `divergence_scan`, and the per-SKU tools take `sales_org`; **work-in-one-region
   by default** (she scopes to the named region, never returns global numbers).
9. **Pre-aggregated hierarchy backbone**:
   - `lily.vw_hierarchy_rollup` — one finished-numbers row per (region × node) at EVERY level
     L1–L4, with `node_path`/`parent_path` (children = rows WHERE parent_path = node_path).
     Metrics: n_skus, demand_qty, trailing_revenue_eur, demand_vs_budget_pct, yoy_growth_pct,
     wmape_pct, bias_pct, accuracy_pct, stockout_skus, **budget_gap_qty, abs_error_qty**.
   - `hierarchy_view(sales_org, node=None, level=2)` tool — node TOTAL + its immediate children
     in ONE read, no SKU loop. Computes **attribution**: `share_of_budget_miss_pct` /
     `share_of_forecast_error_pct` = how much of the parent's gap/error each child drives
     (NOT revenue share). Tool tells Lily to reason over the whole picture, NOT auto-drill the
     biggest child.
   - Prompt: default lens **L2** and Lily ANNOUNCES it; drill to **L3** when asked about
     sub-categories; always state the level.
   - Verified: "How is HomePest in the UK?" → ONE `hierarchy_view(1110, 'HOME PEST CONTROLS')`
     call (was 5 calls + global numbers + wrong region before). Pokon attribution example:
     Flying Insects is #2 by revenue but drives 90% of the budget miss.

## NEXT — the rollout (option A: node/category first, THEN customer)
Principle (Brett's): **every view we have on a SKU, we should also have at product-category
(hierarchy node) and at customer.** Build the node lift first; mirror to customer after.
All of these hang off the same `sku_base` CTE pattern in `vw_hierarchy_rollup`.

Node-level lift to build (each is the category equivalent of an existing SKU tool):
1. **Node time-series** — actuals/demand + bias over the last N periods for a node
   (category version of `actuals_history` + `forecast_performance.bias_by_period`).
2. **Node economics** — margin / price / COGS rolled to a node (category `product_economics`).
3. **Node inventory** — coverage + stockout/overstock for a node, and the SKUs inside it.
4. **Node forecast** — the forward demand series for a node (category `get_forecast`).
5. **Node forecast revision** — what changed since the last cut, at node level.
6. **Unified SKU scan within a node** — one scan carrying revenue + budget + YoY +
   **accuracy + inventory** together (today `divergence_scan` lacks accuracy/inventory).

Then **customer axis** (second pass): the same lift at customer grain (customer × category,
customer-level accuracy/budget/etc.).

Reference question catalog (validated with Brett): the HomePest-anchored map of planner
questions → which are covered vs which need the builds above. The 6 node views + customer
pass close all the gaps.

## Other open items
- **CLAUDE.md is stale** (says FY=Nov, 15 tools, statistical stream, single-region 2510,
  lily_views_runnable as prod). Update when convenient.
- **Foundry / GPT path** untested — needs Sandeep's `AZURE_AI_PROJECT_ENDPOINT` + deps
  (`agent-framework`, `azure-identity`). `lily_msft.py` is aligned but unrun.
- **"Twin structure"** accuracy question → Romuald (see above).

## Files to know
| File | What |
|---|---|
| `sql/lily_views_pg.sql` | All prod views incl. `vw_hierarchy_rollup` (applied to live DB) |
| `agents/lily/tools.py` | Tools incl. `hierarchy_view`; `_db_lock`; Entra `_connect()` |
| `agents/lily/lily.py` | Prompt + tool defs + dispatch (region map in `_SALES_ORG`) |
| `server.py` | `_data_landscape()` (orientation + region/level rules); $/day cap |
| `apply_views.py` · `test_tools_pg.py` · `explore_schema.py` | re-apply / smoke-test / schema dump |
| `LILY_DATA_INTEGRITY_AUDIT_REPORT.md` · `AUDIT_PROMPT_FOR_CODEX.md` | audit report + the brief |
| `sql/SCHEMA_DUMP.md` | real warehouse schema (13 tables) |
