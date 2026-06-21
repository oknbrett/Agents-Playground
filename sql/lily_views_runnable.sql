-- ============================================================================
-- LILY — Runnable views on the real fact-table shape (rev. 2026-06-17)
-- Source: Forecast.xlsx, Actuals.xlsx, Budget.xlsx, Inventory.xlsx
-- Target tables: dw.fct_forecast, dw.fct_actuals, dw.fct_budget, dw.fct_inventory
-- Output schema: lily        Full data model: DATA_MODEL.md
--
-- SEMANTICS (override the literal SAP labels — see DATA_MODEL.md):
--   sales_org      = region / business unit  (2510 ≈ Netherlands / Evergreen Pokon)
--   triad_region   = the CUSTOMER            (not geography)
--   material       = SKU (STRING, may carry letter suffixes)
--   customer key   = (sales_org, triad_region)  -- code's 1st letter tracks org
--
-- KEY ENCODING (warehouse convention, confirm vs schema-overview.md):
--   forecast_version_key  2026027  -> FY2026 week 27   (year*1000 + week)
--   fiscal_period_key     202608   -> FY2026 period 08 (year*100  + period)
--   "Future" = period >= latest closed actuals period.
--   forecast_cogs_eur is stored NEGATIVE -> margin = revenue - ABS(cogs).
--
-- COLUMN NAMES are the working snake_case convention; reconcile to the canonical
-- schema is a find-and-replace in the FROM/SELECT clauses only.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS lily;


-- ============================================================================
-- 1. FOUNDATION  (one cleaned view per fact table)
-- ============================================================================

-- vw_forecast_future: future demand forecast, all versions, business-readable,
-- margin / unit price pre-computed.
-- GRAIN: sales_org + customer + material + version + period
CREATE OR REPLACE VIEW lily.vw_forecast_future AS
SELECT
    f.sales_org,
    f.triad_region                                           AS customer_code,
    f.material                                               AS material_id,
    f.forecast_version_key,
    CAST(f.forecast_version_key / 1000 AS INTEGER)           AS forecast_version_year,
    (f.forecast_version_key % 1000)                          AS forecast_version_week,
    f.fiscal_period_key,
    CAST(f.fiscal_period_key / 100 AS INTEGER)               AS fiscal_year,
    (f.fiscal_period_key % 100)                              AS fiscal_period,
    f.forecast_quantity,
    f.forecast_revenue_eur,
    ABS(f.forecast_cogs_eur)                                 AS forecast_cogs_eur,
    (f.forecast_revenue_eur - ABS(f.forecast_cogs_eur))      AS forecast_margin_eur,
    CASE WHEN f.forecast_revenue_eur > 0
         THEN ROUND((f.forecast_revenue_eur - ABS(f.forecast_cogs_eur))
                    / f.forecast_revenue_eur * 100, 1) END   AS forecast_margin_pct,
    CASE WHEN f.forecast_quantity > 0
         THEN ROUND(f.forecast_revenue_eur / f.forecast_quantity, 2) END AS unit_selling_price_eur
FROM dw.fct_forecast f
WHERE f.fiscal_period_key >= (SELECT MAX(fiscal_period_key) FROM dw.fct_actuals)
  AND f.forecast_quantity IS NOT NULL;


-- vw_forecast_latest: only the most recently loaded forecast version.
CREATE OR REPLACE VIEW lily.vw_forecast_latest AS
SELECT *
FROM lily.vw_forecast_future
WHERE forecast_version_key = (SELECT MAX(forecast_version_key) FROM dw.fct_forecast);


-- vw_actuals_latest: the single most recent closed period. Reference snapshot
-- only (a sanity anchor), NOT past-performance reporting (that's Billy).
CREATE OR REPLACE VIEW lily.vw_actuals_latest AS
SELECT
    a.sales_org,
    a.triad_region                                           AS customer_code,
    a.material                                               AS material_id,
    a.plant,
    a.fiscal_period_key,
    CAST(a.fiscal_period_key / 100 AS INTEGER)               AS fiscal_year,
    (a.fiscal_period_key % 100)                              AS fiscal_period,
    a.actual_quantity,
    a.actual_revenue_eur
FROM dw.fct_actuals a
WHERE a.fiscal_period_key = (SELECT MAX(fiscal_period_key) FROM dw.fct_actuals);


-- vw_actuals_history: the FULL actuals history (all closed periods), per
-- customer + material + period, aggregated across plant. Real sold quantity —
-- use to sanity-check whether a forward plan/override is backed by what actually
-- happened. (Forecast accuracy / bias is still Billy's; this is raw sales history.)
CREATE OR REPLACE VIEW lily.vw_actuals_history AS
SELECT
    a.sales_org,
    a.triad_region                                          AS customer_code,
    a.material                                              AS material_id,
    a.fiscal_period_key,
    CAST(a.fiscal_period_key / 100 AS INTEGER)              AS fiscal_year,
    (a.fiscal_period_key % 100)                             AS fiscal_period,
    SUM(a.actual_quantity)                                  AS actual_quantity,
    ROUND(SUM(a.actual_revenue_eur), 2)                     AS actual_revenue_eur
FROM dw.fct_actuals a
GROUP BY a.sales_org, a.triad_region, a.material, a.fiscal_period_key;


-- vw_budget: the sales target, full fiscal year, per customer + material + period.
CREATE OR REPLACE VIEW lily.vw_budget AS
SELECT
    b.sales_org,
    b.triad_region                                           AS customer_code,
    b.material                                               AS material_id,
    b.fiscal_period_key,
    CAST(b.fiscal_period_key / 100 AS INTEGER)               AS fiscal_year,
    (b.fiscal_period_key % 100)                              AS fiscal_period,
    b.budget_quantity,
    b.budget_value_eur
FROM dw.fct_budget b;


-- vw_inventory_latest: current stock snapshot, aggregated to sales_org + material.
-- UoM GUARD: only EA quantities are summed into stock_qty_ea (coverage math needs
-- a single unit). Materials that also hold non-EA stock are flagged so Lily knows
-- the coverage figure is partial. Value is summed across all UoM (EUR is uniform).
CREATE OR REPLACE VIEW lily.vw_inventory_latest AS
WITH latest AS (
    SELECT *
    FROM dw.fct_inventory
    WHERE fiscal_period_key = (SELECT MAX(fiscal_period_key) FROM dw.fct_inventory)
)
SELECT
    sales_org,
    material                                                 AS material_id,
    fiscal_period_key,
    SUM(stock_quantity) FILTER (WHERE uom = 'EA')            AS stock_qty_ea,
    SUM(stock_value_eur)                                     AS stock_value_eur,
    BOOL_OR(uom <> 'EA')                                     AS has_non_ea_stock,
    STRING_AGG(DISTINCT uom, ',' ORDER BY uom)               AS uom_present,
    COUNT(DISTINCT plant)                                    AS plants_holding
FROM latest
GROUP BY sales_org, material, fiscal_period_key;


-- vw_statistical: the naive statistical baseline (model-only, no planner judgment),
-- future periods. Quantity-only stream — value lives on the demand side.
CREATE OR REPLACE VIEW lily.vw_statistical AS
SELECT
    s.sales_org,
    s.triad_region                                          AS customer_code,
    s.material                                              AS material_id,
    s.fiscal_period_key,
    CAST(s.fiscal_period_key / 100 AS INTEGER)              AS fiscal_year,
    (s.fiscal_period_key % 100)                             AS fiscal_period,
    s.statistical_quantity
FROM dw.fct_statistical s
WHERE s.fiscal_period_key >= (SELECT MAX(fiscal_period_key) FROM dw.fct_actuals);


-- ============================================================================
-- 2. VALUE  (the questions planners ask most — forecast only)
-- ============================================================================

-- vw_sku_forecast_ranked: SKUs ranked within each future period.
CREATE OR REPLACE VIEW lily.vw_sku_forecast_ranked AS
SELECT
    sales_org,
    fiscal_year,
    fiscal_period,
    fiscal_period_key,
    material_id,
    SUM(forecast_quantity)                                   AS total_qty,
    SUM(forecast_revenue_eur)                                AS total_revenue_eur,
    SUM(forecast_margin_eur)                                 AS total_margin_eur,
    RANK() OVER (PARTITION BY sales_org, fiscal_period_key ORDER BY SUM(forecast_quantity)    DESC) AS rank_by_qty,
    RANK() OVER (PARTITION BY sales_org, fiscal_period_key ORDER BY SUM(forecast_revenue_eur) DESC) AS rank_by_revenue
FROM lily.vw_forecast_latest
GROUP BY sales_org, fiscal_year, fiscal_period, fiscal_period_key, material_id;


-- vw_customer_forecast_ranked: customers ranked within each future period.
CREATE OR REPLACE VIEW lily.vw_customer_forecast_ranked AS
SELECT
    sales_org,
    fiscal_year,
    fiscal_period,
    fiscal_period_key,
    customer_code,
    SUM(forecast_quantity)                                   AS total_qty,
    SUM(forecast_revenue_eur)                                AS total_revenue_eur,
    SUM(forecast_margin_eur)                                 AS total_margin_eur,
    RANK() OVER (PARTITION BY sales_org, fiscal_period_key ORDER BY SUM(forecast_revenue_eur) DESC) AS rank_by_revenue
FROM lily.vw_forecast_latest
GROUP BY sales_org, fiscal_year, fiscal_period, fiscal_period_key, customer_code;


-- vw_product_economics: per-product economics across the whole horizon.
CREATE OR REPLACE VIEW lily.vw_product_economics AS
SELECT
    sales_org,
    material_id,
    SUM(forecast_quantity)                                   AS total_forecast_qty,
    SUM(forecast_revenue_eur)                                AS total_forecast_revenue_eur,
    SUM(forecast_cogs_eur)                                   AS total_forecast_cogs_eur,
    SUM(forecast_margin_eur)                                 AS total_forecast_margin_eur,
    CASE WHEN SUM(forecast_revenue_eur) > 0
         THEN ROUND(SUM(forecast_margin_eur) / SUM(forecast_revenue_eur) * 100, 1) END AS margin_pct,
    CASE WHEN SUM(forecast_quantity) > 0
         THEN ROUND(SUM(forecast_revenue_eur) / SUM(forecast_quantity), 2) END         AS avg_selling_price_eur,
    CASE WHEN SUM(forecast_quantity) > 0
         THEN ROUND(SUM(forecast_cogs_eur)    / SUM(forecast_quantity), 2) END          AS avg_unit_cogs_eur
FROM lily.vw_forecast_latest
GROUP BY sales_org, material_id;


-- ============================================================================
-- 3. COMPARISONS  (the newly-unblocked views — budget + inventory)
-- ============================================================================

-- vw_demand_vs_budget  (catalog #5): planner's demand forecast vs the sales
-- budget, same customer + material + future period. Shows where the plan and the
-- target disagree, and which way.
-- NOTE: on the single-org samples forecast(2510) and budget(3710) don't overlap,
-- so this returns 0 rows there. Populates against the real multi-org DB.
CREATE OR REPLACE VIEW lily.vw_demand_vs_budget AS
WITH demand AS (
    SELECT sales_org, customer_code, material_id, fiscal_period_key,
           fiscal_year, fiscal_period,
           SUM(forecast_quantity)    AS demand_qty,
           SUM(forecast_revenue_eur) AS demand_revenue_eur
    FROM lily.vw_forecast_latest
    GROUP BY sales_org, customer_code, material_id, fiscal_period_key, fiscal_year, fiscal_period
),
budget AS (
    SELECT sales_org, customer_code, material_id, fiscal_period_key,
           SUM(budget_quantity)  AS budget_qty,
           SUM(budget_value_eur) AS budget_value_eur
    FROM lily.vw_budget
    GROUP BY sales_org, customer_code, material_id, fiscal_period_key
)
SELECT
    d.sales_org,
    d.customer_code,
    d.material_id,
    d.fiscal_year,
    d.fiscal_period,
    d.fiscal_period_key,
    d.demand_qty,
    b.budget_qty,
    (d.demand_qty - b.budget_qty)                            AS qty_delta,
    CASE WHEN b.budget_qty > 0
         THEN ROUND((d.demand_qty - b.budget_qty) / b.budget_qty::numeric * 100, 1) END AS qty_delta_pct,
    d.demand_revenue_eur,
    b.budget_value_eur,
    (d.demand_revenue_eur - b.budget_value_eur)              AS value_delta_eur
FROM demand d
JOIN budget b
  ON  d.sales_org        = b.sales_org
  AND d.customer_code    = b.customer_code
  AND d.material_id      = b.material_id
  AND d.fiscal_period_key = b.fiscal_period_key;


-- vw_demand_vs_statistical (catalog #3): the planner's demand forecast vs the
-- naive statistical baseline, same customer + material + future period. The delta
-- IS the planner's manual override — where human judgment was applied, and which
-- way. RAISED/LOWERED beyond ±10% is a deliberate deviation worth justifying.
CREATE OR REPLACE VIEW lily.vw_demand_vs_statistical AS
WITH demand AS (
    SELECT sales_org, customer_code, material_id, fiscal_period_key,
           fiscal_year, fiscal_period,
           SUM(forecast_quantity) AS demand_qty
    FROM lily.vw_forecast_latest
    GROUP BY sales_org, customer_code, material_id, fiscal_period_key, fiscal_year, fiscal_period
),
stat AS (
    SELECT sales_org, customer_code, material_id, fiscal_period_key,
           SUM(statistical_quantity) AS statistical_qty
    FROM lily.vw_statistical
    GROUP BY sales_org, customer_code, material_id, fiscal_period_key
)
SELECT
    d.sales_org,
    d.customer_code,
    d.material_id,
    d.fiscal_year,
    d.fiscal_period,
    d.fiscal_period_key,
    d.demand_qty,
    s.statistical_qty,
    (d.demand_qty - s.statistical_qty)                      AS override_qty,
    CASE WHEN s.statistical_qty > 0
         THEN ROUND((d.demand_qty - s.statistical_qty) / s.statistical_qty::numeric * 100, 1) END AS override_pct,
    CASE
        WHEN s.statistical_qty = 0                THEN 'NO BASELINE'
        WHEN d.demand_qty > s.statistical_qty * 1.1 THEN 'PLANNER RAISED'
        WHEN d.demand_qty < s.statistical_qty * 0.9 THEN 'PLANNER LOWERED'
        ELSE 'IN LINE'
    END                                                     AS override_flag
FROM demand d
JOIN stat s
  ON  d.sales_org        = s.sales_org
  AND d.customer_code    = s.customer_code
  AND d.material_id      = s.material_id
  AND d.fiscal_period_key = s.fiscal_period_key;


-- vw_budget_vs_last_year  (catalog #2): the sales budget for a period vs what
-- actually sold in the SAME period one fiscal year earlier. "Is the target
-- realistic against real past demand?"
-- NOTE: actuals currently hold only P7.2026 (no prior FY), so this returns 0 rows
-- until last-year actuals load. Structure is correct and ready.
CREATE OR REPLACE VIEW lily.vw_budget_vs_last_year AS
SELECT
    b.sales_org,
    b.customer_code,
    b.material_id,
    b.fiscal_year,
    b.fiscal_period,
    b.fiscal_period_key,
    b.budget_quantity                                        AS budget_qty,
    a.actual_quantity                                        AS last_year_actual_qty,
    (b.budget_quantity - a.actual_quantity)                  AS qty_delta,
    CASE WHEN a.actual_quantity > 0
         THEN ROUND((b.budget_quantity - a.actual_quantity) / a.actual_quantity::numeric * 100, 1) END AS qty_delta_pct
FROM lily.vw_budget b
JOIN dw.fct_actuals a
  ON  a.sales_org    = b.sales_org
  AND a.triad_region = b.customer_code
  AND a.material     = b.material_id
  -- same period, one fiscal year earlier:
  AND a.fiscal_period_key = b.fiscal_period_key - 100;


-- vw_inventory_coverage  (BR-06): current stock vs forward demand, per
-- sales_org + material (product level — inventory has no customer dimension).
-- coverage_periods = on-hand EA stock / average future demand per period.
-- Flags stockout risk (<1 period) and overstock (>12 periods).
CREATE OR REPLACE VIEW lily.vw_inventory_coverage AS
WITH future_demand AS (
    SELECT sales_org, material_id,
           SUM(period_qty)                                   AS total_future_qty,
           COUNT(DISTINCT fiscal_period_key)                 AS future_periods,
           ROUND(AVG(period_qty), 1)                         AS avg_period_qty
    FROM (
        SELECT sales_org, material_id, fiscal_period_key,
               SUM(forecast_quantity) AS period_qty
        FROM lily.vw_forecast_latest
        GROUP BY sales_org, material_id, fiscal_period_key
    ) p
    GROUP BY sales_org, material_id
)
SELECT
    i.sales_org,
    i.material_id,
    i.stock_qty_ea,
    i.stock_value_eur,
    i.has_non_ea_stock,
    i.uom_present,
    d.avg_period_qty,
    d.total_future_qty,
    d.future_periods,
    CASE WHEN d.avg_period_qty > 0
         THEN ROUND(i.stock_qty_ea / d.avg_period_qty, 1) END AS coverage_periods,
    CASE
        WHEN d.avg_period_qty IS NULL OR d.avg_period_qty = 0 THEN 'NO FORWARD DEMAND'
        WHEN i.stock_qty_ea IS NULL                            THEN 'NO EA STOCK'
        WHEN i.stock_qty_ea / d.avg_period_qty < 1             THEN 'STOCKOUT RISK'
        WHEN i.stock_qty_ea / d.avg_period_qty > 12            THEN 'OVERSTOCK'
        ELSE 'OK'
    END                                                       AS coverage_flag
FROM lily.vw_inventory_latest i
JOIN future_demand d
  ON  i.sales_org   = d.sales_org
  AND i.material_id = d.material_id;


-- ============================================================================
-- 4. QUALITY
-- ============================================================================

-- vw_flat_forecast_check: SKU + customer combos whose forecast is identical or
-- near-identical across 3+ future periods — likely copy-paste placeholders.
CREATE OR REPLACE VIEW lily.vw_flat_forecast_check AS
WITH period_qty AS (
    SELECT sales_org, material_id, customer_code, fiscal_period_key,
           SUM(forecast_quantity) AS qty
    FROM lily.vw_forecast_latest
    GROUP BY sales_org, material_id, customer_code, fiscal_period_key
),
stats AS (
    SELECT
        sales_org, material_id, customer_code,
        COUNT(*)               AS periods,
        COUNT(DISTINCT qty)    AS distinct_values,
        MIN(qty)               AS min_qty,
        MAX(qty)               AS max_qty,
        ROUND(AVG(qty), 0)     AS avg_qty
    FROM period_qty
    GROUP BY sales_org, material_id, customer_code
)
SELECT *,
    CASE
        WHEN distinct_values = 1 AND periods >= 3 THEN 'IDENTICAL - likely placeholder'
        WHEN (max_qty - min_qty) < 0.05 * NULLIF(avg_qty, 0) AND periods >= 3 THEN 'NEAR-FLAT'
        ELSE 'OK'
    END AS flat_flag
FROM stats
WHERE periods >= 3
  AND (distinct_values = 1 OR (max_qty - min_qty) < 0.05 * NULLIF(avg_qty, 0));


-- ============================================================================
-- 5. VERSION MOVEMENT  (structure runs now; populates once a 2nd week loads)
-- ============================================================================

-- vw_forecast_version_delta: compares the two most recent forecast versions,
-- per customer + material + future period. 0 rows until version 2 exists.
CREATE OR REPLACE VIEW lily.vw_forecast_version_delta AS
WITH versions AS (
    SELECT DISTINCT forecast_version_key,
           DENSE_RANK() OVER (ORDER BY forecast_version_key DESC) AS rnk  -- distinct versions, not row ties
    FROM dw.fct_forecast
    WHERE fiscal_period_key >= (SELECT MAX(fiscal_period_key) FROM dw.fct_actuals)
),
cur AS (
    SELECT sales_org, customer_code, material_id, fiscal_period_key, fiscal_year, fiscal_period,
           SUM(forecast_quantity)    AS cur_qty,
           SUM(forecast_revenue_eur) AS cur_rev
    FROM lily.vw_forecast_future
    WHERE forecast_version_key = (SELECT forecast_version_key FROM versions WHERE rnk = 1)
    GROUP BY sales_org, customer_code, material_id, fiscal_period_key, fiscal_year, fiscal_period
),
pri AS (
    SELECT sales_org, customer_code, material_id, fiscal_period_key,
           SUM(forecast_quantity)    AS pri_qty,
           SUM(forecast_revenue_eur) AS pri_rev
    FROM lily.vw_forecast_future
    WHERE forecast_version_key = (SELECT forecast_version_key FROM versions WHERE rnk = 2)
    GROUP BY sales_org, customer_code, material_id, fiscal_period_key
)
SELECT
    c.sales_org,
    c.customer_code,
    c.material_id,
    c.fiscal_year,
    c.fiscal_period,
    c.fiscal_period_key,
    c.cur_qty,
    COALESCE(p.pri_qty, 0)                                   AS pri_qty,
    (c.cur_qty - COALESCE(p.pri_qty, 0))                     AS qty_delta,
    CASE WHEN COALESCE(p.pri_qty, 0) = 0 THEN NULL
         ELSE ROUND((c.cur_qty - p.pri_qty) / p.pri_qty::numeric * 100, 1) END AS qty_delta_pct,
    c.cur_rev,
    p.pri_rev,
    (c.cur_rev - p.pri_rev)                                  AS revenue_delta_eur
FROM cur c
JOIN pri p   -- inner: only SKUs present in BOTH cycles (a real revision). 0 rows until a 2nd week loads.
       ON c.sales_org        = p.sales_org
      AND c.customer_code    = p.customer_code
      AND c.material_id      = p.material_id
      AND c.fiscal_period_key = p.fiscal_period_key;


-- ============================================================================
-- 6. BACKWARD — FORECAST ACCURACY & BIAS  (Billy merged in)
-- Past forecasts of now-closed periods (dw.fct_forecast_history, lags 1/2/3)
-- matched to what actually sold. Lag-2 is Evergreen's operational basis.
-- ============================================================================

-- vw_forecast_actual_matched: foundation — each closed period × SKU × customer,
-- the lagged forecast joined to the actual that landed. Carries all lags; the
-- accuracy/bias views below filter to lag-2.
CREATE OR REPLACE VIEW lily.vw_forecast_actual_matched AS
SELECT
    h.sales_org,
    h.triad_region                                          AS customer_code,
    h.material                                              AS material_id,
    h.fiscal_period_key,
    CAST(h.fiscal_period_key / 100 AS INTEGER)              AS fiscal_year,
    (h.fiscal_period_key % 100)                             AS fiscal_period,
    h.lag,
    h.cut_period_key,
    h.forecast_quantity,
    h.forecast_revenue_eur,
    act.actual_quantity,
    act.actual_revenue_eur,
    (h.forecast_quantity - act.actual_quantity)             AS error_qty,
    ABS(h.forecast_quantity - act.actual_quantity)          AS abs_error_qty
FROM dw.fct_forecast_history h
JOIN lily.vw_actuals_history act
  ON  act.sales_org     = h.sales_org
  AND act.customer_code = h.triad_region
  AND act.material_id   = h.material
  AND act.fiscal_period_key = h.fiscal_period_key
WHERE act.actual_quantity > 0;


-- vw_forecast_accuracy: the per-SKU scorecard at lag-2. WMAPE (volume-weighted,
-- the portfolio metric) and signed bias, across all scored periods.
--   WMAPE = sum|F-A| / sum(A) ;  bias = sum(F-A) / sum(A)
CREATE OR REPLACE VIEW lily.vw_forecast_accuracy AS
SELECT
    sales_org,
    material_id,
    lag,
    COUNT(DISTINCT fiscal_period_key)                       AS periods_scored,
    SUM(actual_quantity)                                    AS total_actual_qty,
    ROUND(SUM(abs_error_qty) / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS wmape_pct,
    ROUND(SUM(error_qty)     / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS bias_pct
FROM lily.vw_forecast_actual_matched
WHERE lag = 2
GROUP BY sales_org, material_id, lag;


-- vw_forecast_bias: signed bias per SKU per closed period (lag-2) — the trend,
-- so a persistent one-directional drift (always over / always under) is visible.
CREATE OR REPLACE VIEW lily.vw_forecast_bias AS
SELECT
    sales_org,
    material_id,
    fiscal_year,
    fiscal_period,
    fiscal_period_key,
    SUM(actual_quantity)                                    AS actual_qty,
    SUM(forecast_quantity)                                  AS forecast_qty,
    ROUND(SUM(forecast_quantity - actual_quantity) / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS bias_pct
FROM lily.vw_forecast_actual_matched
WHERE lag = 2
GROUP BY sales_org, material_id, fiscal_year, fiscal_period, fiscal_period_key;


-- vw_sku_performance: the TRIAGE INPUTS for "what should I focus on now?", per
-- SKU at the latest closed period. Recent accuracy/bias (last 3 closed, lag-2) +
-- materiality (trailing-12 actual revenue & volume) + category. Deliberately NOT
-- pre-ranked — Lily reads this and decides the focus list herself, stating her basis.
CREATE OR REPLACE VIEW lily.vw_sku_performance AS
WITH closed AS (
    SELECT fiscal_period_key,
           RANK() OVER (ORDER BY fiscal_period_key DESC) AS recency   -- newest closed = 1
    FROM (SELECT DISTINCT fiscal_period_key FROM dw.fct_actuals)
),
recent_perf AS (   -- last 3 closed periods, lag-2
    SELECT m.sales_org, m.material_id,
           ROUND(SUM(m.abs_error_qty) / NULLIF(SUM(m.actual_quantity), 0) * 100, 1) AS recent_wmape_pct,
           ROUND(SUM(m.error_qty)     / NULLIF(SUM(m.actual_quantity), 0) * 100, 1) AS recent_bias_pct
    FROM lily.vw_forecast_actual_matched m
    JOIN closed c ON c.fiscal_period_key = m.fiscal_period_key
    WHERE m.lag = 2 AND c.recency <= 3
    GROUP BY m.sales_org, m.material_id
),
materiality AS (   -- trailing 12 closed periods
    SELECT h.sales_org, h.material_id,
           ROUND(SUM(h.actual_revenue_eur), 2)             AS trailing_12m_revenue_eur,
           SUM(h.actual_quantity)                          AS trailing_12m_qty
    FROM lily.vw_actuals_history h
    JOIN closed c ON c.fiscal_period_key = h.fiscal_period_key
    WHERE c.recency <= 12
    GROUP BY h.sales_org, h.material_id
)
SELECT
    mat.sales_org,
    mat.material_id,
    d.l1_division,
    d.l2_category,
    mat.trailing_12m_revenue_eur,
    mat.trailing_12m_qty,
    rp.recent_wmape_pct,
    rp.recent_bias_pct,
    (SELECT MAX(fiscal_period_key) FROM dw.fct_actuals)     AS latest_closed_period
FROM materiality mat
LEFT JOIN recent_perf rp
       ON rp.sales_org = mat.sales_org AND rp.material_id = mat.material_id
LEFT JOIN dw.dim_product d ON d.material = mat.material_id;


-- ============================================================================
-- 7. CROSS-SKU / FAMILY SCANS  (answer broad questions in ONE call, no looping)
-- Pre-rolled so Lily reasons over the COMPLETE set, never a hand-picked sample.
-- ============================================================================

-- vw_sku_divergence: one row per SKU with the whole divergence picture — demand
-- vs statistical (full horizon AND latest forecast year, to catch escalation),
-- demand vs budget, trailing-12m revenue (materiality), YoY actual growth (the
-- history that justifies or undermines an override), and product family. This is
-- what lets Lily answer "where does the plan diverge, and is it backed by history"
-- across every SKU at once instead of calling demand_vs_statistical SKU-by-SKU.
CREATE OR REPLACE VIEW lily.vw_sku_divergence AS
WITH ds AS (
    SELECT sales_org, material_id,
           SUM(demand_qty) AS demand_qty, SUM(statistical_qty) AS statistical_qty
    FROM lily.vw_demand_vs_statistical
    GROUP BY sales_org, material_id
),
ds_y2 AS (   -- latest forecast year only (the escalation year)
    SELECT sales_org, material_id,
           SUM(demand_qty) AS demand_qty_y2, SUM(statistical_qty) AS statistical_qty_y2
    FROM lily.vw_demand_vs_statistical
    WHERE fiscal_year = (SELECT MAX(fiscal_year) FROM lily.vw_demand_vs_statistical)
    GROUP BY sales_org, material_id
),
db AS (
    SELECT sales_org, material_id,
           SUM(demand_qty) AS demand_qty_b, SUM(budget_qty) AS budget_qty
    FROM lily.vw_demand_vs_budget
    GROUP BY sales_org, material_id
),
yoy AS (   -- last full FY vs prior FY actuals
    SELECT sales_org, material_id,
       SUM(actual_quantity) FILTER (WHERE fiscal_year = (SELECT MAX(fiscal_year) FROM lily.vw_actuals_history))     AS qty_last_fy,
       SUM(actual_quantity) FILTER (WHERE fiscal_year = (SELECT MAX(fiscal_year) - 1 FROM lily.vw_actuals_history)) AS qty_prior_fy
    FROM lily.vw_actuals_history
    GROUP BY sales_org, material_id
)
SELECT
    ds.sales_org,
    ds.material_id,
    d.l1_division,
    d.l2_category,
    ds.demand_qty,
    ds.statistical_qty,
    (ds.demand_qty - ds.statistical_qty)                                                      AS override_qty,
    ROUND((ds.demand_qty - ds.statistical_qty) / NULLIF(ds.statistical_qty, 0) * 100, 1)      AS override_pct,
    ROUND((ds_y2.demand_qty_y2 - ds_y2.statistical_qty_y2) / NULLIF(ds_y2.statistical_qty_y2, 0) * 100, 1) AS override_pct_latest_year,
    ROUND((db.demand_qty_b - db.budget_qty) / NULLIF(db.budget_qty, 0) * 100, 1)              AS demand_vs_budget_pct,
    perf.trailing_12m_revenue_eur,
    ROUND((yoy.qty_last_fy - yoy.qty_prior_fy) / NULLIF(yoy.qty_prior_fy, 0) * 100, 1)        AS yoy_growth_pct
FROM ds
LEFT JOIN ds_y2 ON ds_y2.sales_org = ds.sales_org AND ds_y2.material_id = ds.material_id
LEFT JOIN db    ON db.sales_org    = ds.sales_org AND db.material_id    = ds.material_id
LEFT JOIN yoy   ON yoy.sales_org   = ds.sales_org AND yoy.material_id   = ds.material_id
LEFT JOIN lily.vw_sku_performance perf ON perf.sales_org = ds.sales_org AND perf.material_id = ds.material_id
LEFT JOIN dw.dim_product d ON d.material = ds.material_id;


-- vw_family_divergence: the same picture rolled up to product family (L1/L2) —
-- revenue, override %, avg YoY growth, SKU count per family. One call answers
-- "which is the biggest family and how far off-model is its plan".
CREATE OR REPLACE VIEW lily.vw_family_divergence AS
SELECT
    l1_division,
    l2_category,
    COUNT(*)                                                                     AS n_skus,
    ROUND(SUM(trailing_12m_revenue_eur), 2)                                      AS family_trailing_revenue_eur,
    SUM(demand_qty)                                                              AS demand_qty,
    SUM(statistical_qty)                                                         AS statistical_qty,
    ROUND(SUM(demand_qty - statistical_qty) / NULLIF(SUM(statistical_qty), 0) * 100, 1) AS override_pct,
    ROUND(AVG(yoy_growth_pct), 1)                                               AS avg_yoy_growth_pct
FROM lily.vw_sku_divergence
GROUP BY l1_division, l2_category;


-- ============================================================================
-- VERIFY (run after creating)
-- ============================================================================
-- SELECT COUNT(*) FROM lily.vw_forecast_future;
-- SELECT * FROM lily.vw_sku_forecast_ranked WHERE rank_by_qty <= 5 ORDER BY fiscal_period_key;
-- SELECT * FROM lily.vw_inventory_coverage ORDER BY coverage_periods NULLS LAST LIMIT 20;  -- populates on org 2510
-- SELECT COUNT(*) FROM lily.vw_demand_vs_budget;        -- 0 on single-org sample
-- SELECT COUNT(*) FROM lily.vw_budget_vs_last_year;     -- 0 until prior-FY actuals load
-- SELECT COUNT(*) FROM lily.vw_forecast_version_delta;  -- 0 until a 2nd week loads
