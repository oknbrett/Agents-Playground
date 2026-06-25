# Handoff — Lily on real Postgres: region + hierarchy rollout

> Updated 2026-06-25 (pm). Start the next session by reading this file. The data
> layer is live on the real Azure warehouse; region-scoping + a pre-aggregated
> product-hierarchy backbone landed earlier, and **the option-A node/category lift
> is now DONE and verified** (see "Node lift" below). **Next up = the CUSTOMER
> mirror: the same lift at customer grain.**

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

## Node lift (option A) — DONE & verified 2026-06-25
Principle (Brett's): **every view we have on a SKU, we should also have at product-category
(hierarchy node) and at customer.** The node lift is built; the customer mirror is next.

**Backbone:** `lily.vw_material_node` — the period-grain analogue of the rollup's `sku_base`
CTE: one row per (material × level) with `node_path`/`parent_path` in the SAME convention as
`vw_hierarchy_rollup`, so a node filters by `node_path` exactly like `hierarchy_view`. Each
node view JOINs its OWN fact to the bridge, so each draws its population from that fact (e.g.
node history includes discontinued SKUs that the forecast-driven `vw_sku_divergence` drops).

**Six node views (all in `sql/lily_views_pg.sql`, applied to live DB, none empty):**
`vw_node_forecast` (forward series ≙ get_forecast) · `vw_node_economics` (priced-only margin/
price/COGS ≙ product_economics) · `vw_node_actuals_history` + `vw_node_bias` (actuals + lag-2
bias per period ≙ actuals_history + bias-by-period) · `vw_node_inventory` (coverage + stockout/
overstock counts ≙ inventory_coverage) · `vw_node_forecast_revision` (node delta between the two
latest vintages) · `vw_node_sku_scan` (the unified within-node SKU scan: revenue + budget + YoY
+ **accuracy + inventory** together — closes the `divergence_scan` gap).

**Two tools** (Brett chose the 2-tool surface over 6 separate): `node_detail(sales_org, node,
aspect)` where aspect = forecast | economics | inventory | timeseries | revision, and
`node_sku_scan(sales_org, node, order_by, n)`. Both in `agents/lily/tools.py`; defs+dispatch in
`lily.py`; prompt guidance in `server.py _data_landscape()`. Node addressing reuses the
`hierarchy_view` resolver (name or code, shallowest level on a tie).

**Accuracy freeze respected:** the node views CONSUME `vw_forecast_accuracy/_bias/_actual_matched`,
never redefine them — still frozen pending Romuald's "single vs twin structure" answer.

**Verification (`verify_node_lift.py`, Pokon 3710, top-3 L2 nodes):** node_forecast demand,
node_economics qty/rev/margin (vs `product_economics` summed over members), node_sku_scan
membership, and node_inventory stockout counts all tie to the trusted rollup EXACTLY. Two views
read intentionally HIGHER than the rollup — `vw_node_actuals_history` and `vw_node_bias` — because
they use the fuller fact population (incl. SKUs with no forward demand). **Note:** node bias is
computed DIRECTLY from raw F/A (like `forecast_performance`), so it's MORE precise than the
rollup's headline bias, which reconstructs from each SKU's already-rounded `bias_pct`; the two
can differ a few points, most near zero. This is expected, not a bug — confirmed: restricting
node_bias to the rollup's forecast-having SKU set reproduces the rollup figure (GROWING MEDIA
10.0 = 10.0).

## NEXT — the CUSTOMER mirror (second pass)
Same lift at customer grain: customer × category, customer-level accuracy/budget/forecast/etc.
The facts already carry `customer_code` (customer_group_key); `vw_node_*` views currently sum
across customers. Decide the addressing (customer × node? customer totals?) and whether it's a
parallel `vw_customer_node` bridge or a customer_code passthrough on the existing node views.

Reference question catalog (validated with Brett): the HomePest-anchored map of planner
questions → which are covered vs which need these builds. The node views + customer pass close
all the gaps.

## Other open items
- **CLAUDE.md is stale** (says FY=Nov, 15 tools, statistical stream, single-region 2510,
  lily_views_runnable as prod). Update when convenient.
- **Foundry / GPT path** (2026-06-25 check): deps now installed (`agent-framework` 1.9,
  `azure-identity`); `lily_msft.py` imports clean and its `AGENT_TOOLS` is now SYNCED — it had
  been missing `hierarchy_view` AND the new node tools, so it would have deployed without the
  category capabilities. All 17 tools convert to framework schemas (`normalize_tools` OK — the
  `str | int` unions infer fine). **Still cannot do a live run:** needs Sandeep's
  `AZURE_AI_PROJECT_ENDPOINT` + a Foundry credential (az login to that resource). ⚠️ Installing
  `agent-framework>=1.0` (the meta-package) pulled a huge tree (boto3, openai-agents, qdrant,
  redis, mem0, ollama…) and downgraded `anthropic` 0.109→0.80 / `fastapi` 0.136→0.133 (still
  within requirements floors; both backends still import). **Recommend isolating the Foundry
  backend in its own venv, or narrowing requirements to `agent-framework-core` +
  `agent-framework-foundry`**, so it doesn't pollute/downgrade the main app env.
- **"Twin structure"** accuracy question → Romuald (see above).

## Files to know
| File | What |
|---|---|
| `sql/lily_views_pg.sql` | All prod views incl. `vw_hierarchy_rollup` + `vw_material_node` + the six `vw_node_*` lift views (applied to live DB) |
| `agents/lily/tools.py` | Tools incl. `hierarchy_view`, `node_detail`, `node_sku_scan`, `_resolve_node`; `_db_lock`; Entra `_connect()` |
| `agents/lily/lily.py` | Prompt + tool defs + dispatch (region map in `_SALES_ORG`) |
| `server.py` | `_data_landscape()` (orientation + region/level + node-tool rules); $/day cap |
| `apply_views.py` · `verify_node_lift.py` · `test_tools_pg.py` · `explore_schema.py` | re-apply / cross-check node lift vs rollup / smoke-test / schema dump |
| `LILY_DATA_INTEGRITY_AUDIT_REPORT.md` · `AUDIT_PROMPT_FOR_CODEX.md` | audit report + the brief |
| `sql/SCHEMA_DUMP.md` | real warehouse schema (13 tables) |
