# Lily SQL Views — Planning Document

Working iteratively. Capture decisions here as we go, write SQL in one shot when ready.

**Status: design locked. Ready to craft views once Bart confirms the version keys (see Parked).**

---

## Scope

**Building for Lily only.** BR-07, BR-10, BR-12 dropped. BR-01 through BR-05 belong to Billy.

Active BRs: **BR-06, BR-08, BR-09, BR-11**

---

## DW Schema (source tables)

**Dimensions**
- `dw.dim_customer_attribute_4` — customer_attribute_4, customer_attribute_4_name
- `dw.dim_fiscal_period` — fiscal_period_key, fiscal_year, period
- `dw.dim_fiscal_week` — fiscal_week_key, fiscal_period_key, fiscal_year, period, week
- `dw.dim_material` — material_id, material_description, material_type_id, cross_plant_material_status, product_hierarchy_id, product_hierarchy_level_1–4 (id + description)
- `dw.dim_material_group` — material_id, sales_organization_id, material_group_1–5 (id + description)
- `dw.dim_plant` — plant_id, plant_name
- `dw.dim_sales_organization` — sales_organization_id, sales_organization_name

**Facts**
- `dw.fct_actuals` — sales_organization_id, material_id, customer_attribute_4, plant_id, fiscal_period_key, actual_quantity, actual_revenue_eur, load_id
- `dw.fct_forecast` — sales_organization_id, material_id, customer_attribute_4, plant_id, forecast_version_key, fiscal_period_key, forecast_quantity, forecast_revenue_eur, forecast_cogs_eur, load_id
- `dw.fct_inventory` — sales_organization_id, material_id, plant_id, fiscal_period_key, inventory_quantity, unit_of_measure, stock_value_eur, load_id

> Note: `fct_inventory` has no `customer_attribute_4`. Physical stock lives at material + plant level — cannot be split by customer. Correct from a planning standpoint.

---

## Architectural Decisions (locked)

### 1. This is a One Big Table (OBT) serving layer for an AI agent

The goal: Lily does **zero** SQL work — no joins, no aggregation, no calculation. Everything is pre-joined, pre-aggregated, and pre-calculated in advance. Lily's tools do a pinpoint lookup by key and get back rows where every number is already computed. Lily spends her effort on intelligence, not data plumbing.

This is the documented 2026 best practice for serving data to AI agents ("provide the agent with One Big Table — straightforward reads, no SQL JOINs"). The data layer is the moat.

### 2. Base views are MATERIALIZED

A regular view re-runs its whole query every time it is read. A **materialized view** stores the computed result as a physical table on disk; reads are instant lookups with no recomputation. The stored result must be **refreshed** on a schedule — once nightly, right after the DW's ETL load.

- Base views (`v_planning_*`) and `v_br06_inventory_coverage` → **MATERIALIZED** (heavy aggregation + window logic, paid once per night)
- `v_br08_forecast_versions_*` → regular views (queries already narrow; cheap)

Refresh: `REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_planning_sku;` etc., wired into the nightly load. (CONCURRENTLY needs a unique index on each matview — included in the build.)

### 3. Pre-compute every meaningful comparison as a column

Lily must never subtract two numbers. Each base view carries the four raw streams **and** all meaningful deltas as ready columns. See "Pre-computed comparison columns" below.

### 4. Three base views by grain — NOT one universal table

The #1 OBT anti-pattern in 2026 is the "universal OBT" — one giant table for everything. We avoid it with three focused, grain-specific base views. A SKU-level view has already collapsed customer rows, so customer questions need their own grain.

| View | Grain | When Lily uses it |
|---|---|---|
| `v_planning_sku` | Sales Org + SKU + Period | "How is SKU001 tracking in NL?" |
| `v_planning_customer` | Sales Org + Customer + Period | "How is Albert Heijn tracking?" |
| `v_planning_sku_customer` | Sales Org + SKU + Customer + Period | "How is SKU001 at Albert Heijn?" |

Sales org is always in context (the planner works within their own region), so it is always a filter.

### 5. Footnote — semantic-layer alternative (revisit later)

If EGC later adopts a semantic-layer tool (dbt Semantic Layer, Cube, Databricks/Snowflake Metric Views), the 3 grain-views could collapse into one metric definition that rolls up by dimension at runtime. For raw PostgreSQL + Bart's backend today, materialized views by grain are the right pragmatic call. Not a now-problem.

---

## Four data streams

| Stream | Column | Meaning | Source |
|---|---|---|---|
| **A** | `actual_qty` | What actually sold — the only truth | `fct_actuals` |
| **A-LY** | `actual_qty_ly` | Actual, same period last fiscal year — anchor for future rows | `fct_actuals`, fiscal_year − 1 |
| **S** | `statistical_forecast_qty` | Algorithm baseline | `fct_forecast`, statistical version key |
| **D** | `demand_forecast_qty` | Planner's consensus | `fct_forecast`, demand version key |
| **B** | `budget_qty` | Sales commitment | `fct_forecast`, budget version key |

Past periods: `actual_qty` populated. Future periods: the three forecasts populated, `actual_qty_ly` as the historical anchor.

---

## Pre-computed comparison columns (baked into every base view)

Each is a stored column computed at materialize/refresh time. Lily never runs these — she reads the answer. Exact formulas below.

| Column | Formula | Pre-answers | Value |
|---|---|---|---|
| `demand_vs_ly_delta` | `demand_forecast_qty - actual_qty_ly` | Is the plan justified by history? | ★ High |
| `demand_vs_ly_pct` | `(demand_forecast_qty - actual_qty_ly) / NULLIF(actual_qty_ly,0) * 100` | (as %) | ★ High |
| `demand_vs_stat_delta` | `demand_forecast_qty - statistical_forecast_qty` | How hard is the planner overriding the model? | ★ High |
| `demand_vs_stat_pct` | `(demand_forecast_qty - statistical_forecast_qty) / NULLIF(statistical_forecast_qty,0) * 100` | (as %) | ★ High |
| `demand_vs_budget_delta` | `demand_forecast_qty - budget_qty` | Aligned with sales' commitment? | ★ High |
| `demand_vs_budget_pct` | `(demand_forecast_qty - budget_qty) / NULLIF(budget_qty,0) * 100` | (as %) | ★ High |
| `stat_vs_ly_pct` | `(statistical_forecast_qty - actual_qty_ly) / NULLIF(actual_qty_ly,0) * 100` | Is the model baseline grounded in history? | Medium |
| `budget_vs_ly_pct` | `(budget_qty - actual_qty_ly) / NULLIF(actual_qty_ly,0) * 100` | Is the sales target realistic vs last year? | Medium |
| `actual_yoy_pct` | `(actual_qty - actual_qty_ly) / NULLIF(actual_qty_ly,0) * 100` | Realized trend in this SKU (past rows) | Medium |
| `demand_bias_pct` | `(actual_qty - demand_forecast_qty) / NULLIF(actual_qty,0) * 100` | How accurate has the planner historically been? (past rows) | Context |

All deltas: `forecast − reference` (positive = forecasting above the reference). All `_pct` wrap the denominator in `NULLIF(x,0)` to avoid divide-by-zero → returns NULL, not an error.

Three-way combinations (A+D+B, A+D+S) need no extra columns — Lily reads the streams + deltas side by side. This set covers all 6 high-value combinations.

> Rounding: wrap each `_pct` in `ROUND(…, 1)` in the final SQL for clean display.

---

## Full View List — 7 Views

### Layer 1 — Base Views (3, MATERIALIZED)

**`dw.v_planning_sku`** — Grain: Sales Org × SKU × Period

| Column | Source / Notes |
|---|---|
| sales_organization_id, sales_organization_name | dim_sales_organization |
| material_id, material_description | dim_material |
| product_hierarchy_level_1–4_description | dim_material |
| material_group_description | dim_material_group |
| fiscal_year, period, fiscal_period_key | dim_fiscal_period |
| is_future | derived — TRUE if period > current period |
| periods_from_now | derived — signed int, negative = past, positive = future |
| actual_qty, actual_revenue_eur | fct_actuals SUM |
| actual_qty_ly | fct_actuals SUM, fiscal_year − 1, same period |
| statistical_forecast_qty | fct_forecast SUM, statistical version key |
| demand_forecast_qty | fct_forecast SUM, demand version key |
| budget_qty | fct_forecast SUM, budget version key |
| demand_vs_ly_delta, demand_vs_ly_pct | pre-computed (see formulas) |
| demand_vs_stat_delta, demand_vs_stat_pct | pre-computed |
| demand_vs_budget_delta, demand_vs_budget_pct | pre-computed |
| stat_vs_ly_pct, budget_vs_ly_pct | pre-computed |
| actual_yoy_pct, demand_bias_pct | pre-computed (past rows) |

**`dw.v_planning_customer`** — Grain: Sales Org × Customer × Period
Same as above, swap material columns for `customer_attribute_4`, `customer_attribute_4_name`.

**`dw.v_planning_sku_customer`** — Grain: Sales Org × SKU × Customer × Period
All material + all customer columns. No aggregation across either dimension.

---

### Layer 2 — BR-Specific Views (4)

**`dw.v_br06_inventory_coverage`** (MATERIALIZED) — needs `fct_inventory` directly, different grain.
Grain: Sales Org × SKU × Plant × Future Period (12 rows per SKU)

| Column | Source / Notes |
|---|---|
| sales_organization_id, sales_organization_name | dim_sales_organization |
| material_id, material_description | dim_material |
| plant_id | dim_plant — inventory is at plant level |
| current_inventory_qty | fct_inventory, latest fiscal_period_key |
| future_fiscal_year, future_period | dim_fiscal_period |
| periods_from_now | derived — 1 … 12 |
| demand_forecast_qty | fct_forecast, demand version key |
| cumulative_forecast_qty | derived — running SUM of demand_forecast_qty |
| still_covered | derived — TRUE while cumulative ≤ current_inventory_qty |
| coverage_cutoff_month | derived — first period where still_covered flips FALSE |
| weeks_cover | derived — optional, using dim_fiscal_week |

**`dw.v_br08_forecast_versions_sku`** — Sales Org × SKU × Future Period × Version
**`dw.v_br08_forecast_versions_customer`** — Sales Org × Customer × Future Period × Version
**`dw.v_br08_forecast_versions_sku_customer`** — Sales Org × SKU × Customer × Future Period × Version

Shared columns:

| Column | Source / Notes |
|---|---|
| sales_organization_id, sales_organization_name | dim_sales_organization |
| material_id, material_description | SKU views only |
| customer_attribute_4, customer_attribute_4_name | customer views only |
| future_fiscal_year, future_period | the period being forecasted |
| forecast_version_key, load_id | fct_forecast |
| forecast_qty | what we expected to sell as of this version |
| forecast_qty_prior_version | derived — same future period, one version back |
| version_delta, version_delta_pct | derived |

---

### How BR-09 and BR-11 work — no extra views

Both read the base views directly. All comparison columns are already there.

- **BR-09 (Forecast vs Budget vs LY):** Lily queries `v_planning_sku` (or `_customer`) for a future fiscal year. Reads `demand_forecast_qty`, `budget_qty`, `actual_qty_ly`, plus `demand_vs_budget_pct` and `demand_vs_ly_pct` — all pre-computed.
- **BR-11 (Future Forecast vs LY):** Lily queries `v_planning_sku` filtered to `is_future = TRUE`. Reads `demand_forecast_qty`, `actual_qty_ly`, `demand_vs_ly_pct` — pre-computed.

---

## Parked — Confirm with Bart Before Writing SQL

1. **Version keys (blocks all base views):** What are the three `forecast_version_key` values in `fct_forecast` for — statistical forecast, demand forecast, budget? Run:
   ```sql
   SELECT DISTINCT forecast_version_key, COUNT(*) AS rows
   FROM dw.fct_forecast
   GROUP BY forecast_version_key
   ORDER BY rows DESC;
   ```
2. **BR-08 cycle:** Does `forecast_version_key` change per planning cycle (one key per monthly submission)? If yes, version comparison SQL is clean; if no, use `load_id` rank as proxy.
3. **Refresh hook:** Does the DW have a nightly ETL/load schedule we can attach the `REFRESH MATERIALIZED VIEW` calls to? What time does it complete?

---

## Status

- [x] Scope — BR-06, 08, 09, 11 only
- [x] OBT serving-layer architecture (validated 2026 best practice)
- [x] Base views MATERIALIZED; meaning of materialize + refresh strategy locked
- [x] Pre-compute all meaningful comparison columns (6 high-value combos covered)
- [x] Three base views by grain (universal-OBT anti-pattern avoided)
- [x] Semantic-layer footnote recorded for later
- [x] BR-06 / BR-08 dedicated views designed
- [x] BR-09 / BR-11 read base views directly — no extra views
- [x] SQL drafted → `lily_br_views.sql` (placeholder version keys, not yet run on real data)
- [ ] Bart: confirm 3 forecast_version_key values → swap the 3 placeholder tokens
- [ ] Bart: confirm version_key = planning cycle (or keep load_id proxy in BR-08)
- [ ] Bart: confirm nightly refresh hook + timing
- [ ] Run on real DW, check sanity queries, iterate
