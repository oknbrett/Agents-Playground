-- ============================================================================
-- LILY — Postgres serving views on the REAL warehouse schema (rev. 2026-06-24)
-- Source: warehouse.fact_{forecast,actuals,budget,inventory} + dims
-- Output schema: lily      Supersedes lily_views_runnable.sql (DuckDB/synthetic).
--
-- WHY THIS IS A REWRITE, NOT A RENAME (vs the synthetic-era file):
--   * Keys are TEXT and not chronologically sortable:
--       fiscal_period_key   '008.2026'  (NOT year*100+period; '012.2025' > '001.2026')
--       forecast_version_key '35.2026'  (a weekly VINTAGE; recency = week_start_date)
--     -> all period/version ordering goes through dim_fiscal_period / dim_fiscal_week.
--   * NO statistical baseline stream exists -> vw_statistical and
--     vw_demand_vs_statistical are DROPPED (decision 2026-06-24).
--   * NO separate forecast-history table. The VINTAGES are the history:
--       lag = target_period_idx - cut_period_idx, cut period via dim_fiscal_week.
--   * material_group is only on a sparse helper (>90% combos absent) -> families
--     come from dim_product_hierarchy via dim_material instead.
--
-- SEMANTICS:
--   sales_org      = sales_organization_key (region/BU: 1010 DE, 1210 FR, 2510 Benelux,
--                    3710 Pokon, 1110 UK, 1810 PL, 1910 AT, 3010 AU)
--   customer_code  = customer_group_key (the customer; renamed from customer_attribute_4)
--   material_id    = material_key (SKU, string)
--   COGS stored NEGATIVE -> margin = revenue - ABS(cogs).
--   "Now" = latest closed actuals period (currently 008.2026 = P8 FY2026).
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS lily;

-- ----------------------------------------------------------------------------
-- 0. CALENDAR HELPERS  (make text keys sortable; resolve vintage cut period)
-- ----------------------------------------------------------------------------

-- sortable period index: chronological ordering for text fiscal_period_key
CREATE OR REPLACE VIEW lily.vw_calendar AS
SELECT fiscal_period_key,
       fiscal_year,
       fiscal_period_number                       AS fiscal_period,
       (fiscal_year * 12 + fiscal_period_number)  AS period_idx
FROM warehouse.dim_fiscal_period;

-- the latest CLOSED actuals period (the "now" anchor) — chronological, not string
CREATE OR REPLACE VIEW lily.vw_latest_closed AS
SELECT c.fiscal_period_key, c.fiscal_year, c.fiscal_period, c.period_idx
FROM warehouse.fact_actuals a
JOIN lily.vw_calendar c USING (fiscal_period_key)
GROUP BY c.fiscal_period_key, c.fiscal_year, c.fiscal_period, c.period_idx
ORDER BY c.period_idx DESC
LIMIT 1;

-- version (= weekly vintage) -> the fiscal period it was CUT in + recency date.
-- This is the dim_fiscal_week bridge Bart built (the 4-4-5 mapping).
CREATE OR REPLACE VIEW lily.vw_version_cut AS
SELECT w.fiscal_week_key      AS forecast_version_key,
       w.fiscal_period_key    AS cut_period_key,
       w.week_start_date,
       c.period_idx           AS cut_period_idx
FROM warehouse.dim_fiscal_week w
JOIN lily.vw_calendar c ON c.fiscal_period_key = w.fiscal_period_key;

-- the most recent vintage (by week_start_date, NOT by string max)
CREATE OR REPLACE VIEW lily.vw_latest_vintage AS
SELECT forecast_version_key, cut_period_key, week_start_date, cut_period_idx
FROM lily.vw_version_cut
ORDER BY week_start_date DESC
LIMIT 1;

-- product family per SKU (the COMPLETE path: via dim_material -> product hierarchy)
CREATE OR REPLACE VIEW lily.vw_material_family AS
SELECT dm.material_key                                          AS material_id,
       NULLIF(ph.level_1_description, 'Not assigned')           AS l1_division,
       NULLIF(ph.level_2_description, 'Not assigned')           AS l2_category
FROM warehouse.dim_material dm
LEFT JOIN warehouse.dim_product_hierarchy ph
       ON ph.product_hierarchy_key = dm.product_hierarchy_key;


-- ----------------------------------------------------------------------------
-- 1. FOUNDATION  (one cleaned view per fact table)
-- ----------------------------------------------------------------------------

-- forward demand forecast, ALL vintages, margin/price pre-computed.
-- GRAIN: sales_org + customer + material + version + period
CREATE OR REPLACE VIEW lily.vw_forecast_future AS
SELECT
    f.sales_organization_key                                 AS sales_org,
    f.customer_group_key                                     AS customer_code,
    f.material_key                                           AS material_id,
    f.forecast_version_key,
    vc.cut_period_key,
    cal.fiscal_period_key,
    cal.fiscal_year,
    cal.fiscal_period,
    cal.period_idx,
    f.quantity                                              AS forecast_quantity,
    f.revenue                                               AS forecast_revenue_eur,
    ABS(f.cogs)                                             AS forecast_cogs_eur,
    (f.revenue - ABS(f.cogs))                              AS forecast_margin_eur,
    CASE WHEN f.revenue > 0
         THEN ROUND((f.revenue - ABS(f.cogs)) / f.revenue * 100, 1) END AS forecast_margin_pct,
    CASE WHEN f.quantity > 0
         THEN ROUND(f.revenue / f.quantity, 2) END         AS unit_selling_price_eur
FROM warehouse.fact_forecast f
JOIN lily.vw_calendar    cal ON cal.fiscal_period_key = f.fiscal_period_key
JOIN lily.vw_version_cut vc  ON vc.forecast_version_key = f.forecast_version_key
WHERE cal.period_idx >= (SELECT period_idx FROM lily.vw_latest_closed)
  AND f.quantity IS NOT NULL;

-- only the most recent vintage
CREATE OR REPLACE VIEW lily.vw_forecast_latest AS
SELECT *
FROM lily.vw_forecast_future
WHERE forecast_version_key = (SELECT forecast_version_key FROM lily.vw_latest_vintage);

-- the single latest closed period — a sanity anchor
CREATE OR REPLACE VIEW lily.vw_actuals_latest AS
SELECT
    a.sales_organization_key                                AS sales_org,
    a.customer_group_key                                    AS customer_code,
    a.material_key                                          AS material_id,
    a.plant_key                                             AS plant,
    a.fiscal_period_key,
    cal.fiscal_year,
    cal.fiscal_period,
    a.quantity                                             AS actual_quantity,
    a.revenue                                              AS actual_revenue_eur
FROM warehouse.fact_actuals a
JOIN lily.vw_calendar cal ON cal.fiscal_period_key = a.fiscal_period_key
WHERE cal.period_idx = (SELECT period_idx FROM lily.vw_latest_closed);

-- FULL actuals history, aggregated across plant
CREATE OR REPLACE VIEW lily.vw_actuals_history AS
SELECT
    a.sales_organization_key                               AS sales_org,
    a.customer_group_key                                   AS customer_code,
    a.material_key                                         AS material_id,
    a.fiscal_period_key,
    cal.fiscal_year,
    cal.fiscal_period,
    cal.period_idx,
    SUM(a.quantity)                                       AS actual_quantity,
    ROUND(SUM(a.revenue), 2)                              AS actual_revenue_eur
FROM warehouse.fact_actuals a
JOIN lily.vw_calendar cal ON cal.fiscal_period_key = a.fiscal_period_key
GROUP BY a.sales_organization_key, a.customer_group_key, a.material_key,
         a.fiscal_period_key, cal.fiscal_year, cal.fiscal_period, cal.period_idx;

-- the sales target (budget), per customer + material + period
CREATE OR REPLACE VIEW lily.vw_budget AS
SELECT
    b.sales_organization_key                               AS sales_org,
    b.customer_group_key                                   AS customer_code,
    b.material_key                                         AS material_id,
    b.fiscal_period_key,
    cal.fiscal_year,
    cal.fiscal_period,
    cal.period_idx,
    b.quantity                                            AS budget_quantity,
    b.value                                                AS budget_value_eur
FROM warehouse.fact_budget b
JOIN lily.vw_calendar cal ON cal.fiscal_period_key = b.fiscal_period_key;

-- current stock snapshot, aggregated to sales_org + material. EA-guarded.
CREATE OR REPLACE VIEW lily.vw_inventory_latest AS
WITH latest AS (
    SELECT i.*
    FROM warehouse.fact_inventory i
    JOIN lily.vw_calendar cal ON cal.fiscal_period_key = i.fiscal_period_key
    WHERE cal.period_idx = (
        SELECT MAX(cal2.period_idx)
        FROM warehouse.fact_inventory i2
        JOIN lily.vw_calendar cal2 ON cal2.fiscal_period_key = i2.fiscal_period_key)
)
SELECT
    sales_organization_key                                 AS sales_org,
    material_key                                           AS material_id,
    fiscal_period_key,
    SUM(quantity) FILTER (WHERE unit_of_measure = 'EA')    AS stock_qty_ea,
    SUM(value)                                             AS stock_value_eur,
    BOOL_OR(unit_of_measure <> 'EA')                       AS has_non_ea_stock,
    STRING_AGG(DISTINCT unit_of_measure, ',' ORDER BY unit_of_measure) AS uom_present,
    COUNT(DISTINCT plant_key)                              AS plants_holding
FROM latest
GROUP BY sales_organization_key, material_key, fiscal_period_key;


-- ----------------------------------------------------------------------------
-- 2. VALUE  (forecast-only rankings + economics)
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW lily.vw_sku_forecast_ranked AS
SELECT
    sales_org, fiscal_year, fiscal_period, fiscal_period_key,
    material_id,
    SUM(forecast_quantity)                                 AS total_qty,
    SUM(forecast_revenue_eur)                              AS total_revenue_eur,
    SUM(forecast_margin_eur)                               AS total_margin_eur,
    RANK() OVER (PARTITION BY sales_org, fiscal_period_key ORDER BY SUM(forecast_quantity)    DESC) AS rank_by_qty,
    RANK() OVER (PARTITION BY sales_org, fiscal_period_key ORDER BY SUM(forecast_revenue_eur) DESC) AS rank_by_revenue
FROM lily.vw_forecast_latest
GROUP BY sales_org, fiscal_year, fiscal_period, fiscal_period_key, material_id;

CREATE OR REPLACE VIEW lily.vw_customer_forecast_ranked AS
SELECT
    sales_org, fiscal_year, fiscal_period, fiscal_period_key,
    customer_code,
    SUM(forecast_quantity)                                 AS total_qty,
    SUM(forecast_revenue_eur)                              AS total_revenue_eur,
    SUM(forecast_margin_eur)                               AS total_margin_eur,
    RANK() OVER (PARTITION BY sales_org, fiscal_period_key ORDER BY SUM(forecast_revenue_eur) DESC) AS rank_by_revenue
FROM lily.vw_forecast_latest
GROUP BY sales_org, fiscal_year, fiscal_period, fiscal_period_key, customer_code;

-- ⚠️ Economics are only meaningful on PRICED periods. The forecast projects
-- quantity (and often COGS) further out than revenue — out-year pricing/contracts
-- aren't loaded, so revenue is 0 there. Averaging price/margin over the whole
-- horizon divides real revenue by full-horizon quantity and subtracts COGS that
-- sits on revenue-less periods → a FALSE negative margin. So price, COGS/unit and
-- margin are computed ONLY where revenue > 0, and priced_periods/total_periods
-- tell Lily how much of the horizon actually carries pricing.
CREATE OR REPLACE VIEW lily.vw_product_economics AS
WITH e AS (
    SELECT *, (forecast_revenue_eur > 0) AS is_priced
    FROM lily.vw_forecast_latest
)
-- NOTE: original column order is preserved (so CREATE OR REPLACE works); the
-- priced-coverage columns are appended at the end.
SELECT
    sales_org, material_id,
    SUM(forecast_quantity)                                          AS total_forecast_qty,
    ROUND(SUM(forecast_revenue_eur), 2)                            AS total_forecast_revenue_eur,
    ROUND(SUM(forecast_cogs_eur)   FILTER (WHERE is_priced), 2)    AS total_forecast_cogs_eur,
    ROUND(SUM(forecast_margin_eur) FILTER (WHERE is_priced), 2)    AS total_forecast_margin_eur,
    CASE WHEN SUM(forecast_revenue_eur) > 0
         THEN ROUND(SUM(forecast_margin_eur) FILTER (WHERE is_priced)
                    / SUM(forecast_revenue_eur) * 100, 1) END      AS margin_pct,
    CASE WHEN SUM(forecast_quantity) FILTER (WHERE is_priced) > 0
         THEN ROUND(SUM(forecast_revenue_eur)
                    / SUM(forecast_quantity) FILTER (WHERE is_priced), 2) END AS avg_selling_price_eur,
    CASE WHEN SUM(forecast_quantity) FILTER (WHERE is_priced) > 0
         THEN ROUND(SUM(forecast_cogs_eur) FILTER (WHERE is_priced)
                    / SUM(forecast_quantity) FILTER (WHERE is_priced), 2) END AS avg_unit_cogs_eur,
    SUM(forecast_quantity) FILTER (WHERE is_priced)                AS priced_qty,
    COUNT(DISTINCT fiscal_period_key) FILTER (WHERE is_priced)     AS priced_periods,
    COUNT(DISTINCT fiscal_period_key)                             AS total_periods
FROM e
GROUP BY sales_org, material_id;


-- ----------------------------------------------------------------------------
-- 3. COMPARISONS  (budget + inventory)
-- ----------------------------------------------------------------------------

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
    d.sales_org, d.customer_code, d.material_id,
    d.fiscal_year, d.fiscal_period, d.fiscal_period_key,
    d.demand_qty, b.budget_qty,
    (d.demand_qty - b.budget_qty)                          AS qty_delta,
    CASE WHEN b.budget_qty > 0
         THEN ROUND((d.demand_qty - b.budget_qty) / b.budget_qty::numeric * 100, 1) END AS qty_delta_pct,
    d.demand_revenue_eur, b.budget_value_eur,
    (d.demand_revenue_eur - b.budget_value_eur)            AS value_delta_eur
FROM demand d
JOIN budget b
  ON  d.sales_org         = b.sales_org
  AND d.customer_code     = b.customer_code
  AND d.material_id       = b.material_id
  AND d.fiscal_period_key = b.fiscal_period_key;

-- budget vs what actually sold one FISCAL YEAR earlier (same period number)
CREATE OR REPLACE VIEW lily.vw_budget_vs_last_year AS
SELECT
    b.sales_org, b.customer_code, b.material_id,
    b.fiscal_year, b.fiscal_period, b.fiscal_period_key,
    b.budget_quantity                                      AS budget_qty,
    a.actual_quantity                                      AS last_year_actual_qty,
    (b.budget_quantity - a.actual_quantity)                AS qty_delta,
    CASE WHEN a.actual_quantity > 0
         THEN ROUND((b.budget_quantity - a.actual_quantity) / a.actual_quantity::numeric * 100, 1) END AS qty_delta_pct
FROM lily.vw_budget b
JOIN lily.vw_actuals_history a
  ON  a.sales_org     = b.sales_org
  AND a.customer_code = b.customer_code
  AND a.material_id   = b.material_id
  AND a.fiscal_year   = b.fiscal_year - 1
  AND a.fiscal_period = b.fiscal_period;

-- current stock vs forward demand, product level
CREATE OR REPLACE VIEW lily.vw_inventory_coverage AS
WITH future_demand AS (
    SELECT sales_org, material_id,
           SUM(period_qty)                                 AS total_future_qty,
           COUNT(DISTINCT fiscal_period_key)               AS future_periods,
           ROUND(AVG(period_qty), 1)                       AS avg_period_qty
    FROM (
        SELECT sales_org, material_id, fiscal_period_key,
               SUM(forecast_quantity) AS period_qty
        FROM lily.vw_forecast_latest
        GROUP BY sales_org, material_id, fiscal_period_key
    ) p
    GROUP BY sales_org, material_id
)
SELECT
    i.sales_org, i.material_id, i.stock_qty_ea, i.stock_value_eur,
    i.has_non_ea_stock, i.uom_present,
    d.avg_period_qty, d.total_future_qty, d.future_periods,
    CASE WHEN d.avg_period_qty > 0
         THEN ROUND(i.stock_qty_ea / d.avg_period_qty, 1) END AS coverage_periods,
    CASE
        WHEN d.avg_period_qty IS NULL OR d.avg_period_qty = 0 THEN 'NO FORWARD DEMAND'
        WHEN i.stock_qty_ea IS NULL                           THEN 'NO EA STOCK'
        WHEN i.stock_qty_ea / d.avg_period_qty < 1            THEN 'STOCKOUT RISK'
        WHEN i.stock_qty_ea / d.avg_period_qty > 12           THEN 'OVERSTOCK'
        ELSE 'OK'
    END                                                      AS coverage_flag
FROM lily.vw_inventory_latest i
JOIN future_demand d
  ON  i.sales_org   = d.sales_org
  AND i.material_id = d.material_id;


-- ----------------------------------------------------------------------------
-- 4. QUALITY
-- ----------------------------------------------------------------------------

CREATE OR REPLACE VIEW lily.vw_flat_forecast_check AS
WITH period_qty AS (
    SELECT sales_org, material_id, customer_code, fiscal_period_key,
           SUM(forecast_quantity) AS qty
    FROM lily.vw_forecast_latest
    GROUP BY sales_org, material_id, customer_code, fiscal_period_key
),
stats AS (
    SELECT sales_org, material_id, customer_code,
        COUNT(*)            AS periods,
        COUNT(DISTINCT qty) AS distinct_values,
        MIN(qty)            AS min_qty,
        MAX(qty)            AS max_qty,
        ROUND(AVG(qty), 0)  AS avg_qty
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


-- ----------------------------------------------------------------------------
-- 5. VERSION MOVEMENT  (now POPULATES — 11 real vintages loaded)
-- ----------------------------------------------------------------------------

-- compares the two most recent vintages (by date), per customer + material + period
CREATE OR REPLACE VIEW lily.vw_forecast_version_delta AS
WITH versions AS (
    SELECT forecast_version_key, week_start_date,
           DENSE_RANK() OVER (ORDER BY week_start_date DESC) AS rnk
    FROM lily.vw_version_cut
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
    c.sales_org, c.customer_code, c.material_id,
    c.fiscal_year, c.fiscal_period, c.fiscal_period_key,
    c.cur_qty,
    COALESCE(p.pri_qty, 0)                                 AS pri_qty,
    (c.cur_qty - COALESCE(p.pri_qty, 0))                   AS qty_delta,
    CASE WHEN COALESCE(p.pri_qty, 0) = 0 THEN NULL
         ELSE ROUND((c.cur_qty - p.pri_qty) / p.pri_qty::numeric * 100, 1) END AS qty_delta_pct,
    c.cur_rev, p.pri_rev,
    (c.cur_rev - p.pri_rev)                                AS revenue_delta_eur
FROM cur c
JOIN pri p
       ON c.sales_org         = p.sales_org
      AND c.customer_code     = p.customer_code
      AND c.material_id       = p.material_id
      AND c.fiscal_period_key = p.fiscal_period_key;


-- ----------------------------------------------------------------------------
-- 6. BACKWARD — FORECAST ACCURACY & BIAS  (Billy, rebuilt from VINTAGES)
-- lag = target_period_idx - cut_period_idx. Evergreen's basis is lag-2.
-- ----------------------------------------------------------------------------

-- foundation: each vintage's forecast of a now-closed period, matched to actuals.
-- Carries ALL lags; the accuracy/bias views filter to lag-2.
CREATE OR REPLACE VIEW lily.vw_forecast_actual_matched AS
SELECT
    f.sales_organization_key                              AS sales_org,
    f.customer_group_key                                  AS customer_code,
    f.material_key                                        AS material_id,
    f.fiscal_period_key,
    cal.fiscal_year,
    cal.fiscal_period,
    (cal.period_idx - vc.cut_period_idx)                  AS lag,
    vc.cut_period_key,
    f.quantity                                            AS forecast_quantity,
    f.revenue                                             AS forecast_revenue_eur,
    a.actual_quantity,
    a.actual_revenue_eur,
    (f.quantity - a.actual_quantity)                      AS error_qty,
    ABS(f.quantity - a.actual_quantity)                   AS abs_error_qty
FROM warehouse.fact_forecast f
JOIN lily.vw_version_cut vc  ON vc.forecast_version_key = f.forecast_version_key
JOIN lily.vw_calendar    cal ON cal.fiscal_period_key   = f.fiscal_period_key
JOIN lily.vw_actuals_history a
  ON  a.sales_org     = f.sales_organization_key
  AND a.customer_code = f.customer_group_key
  AND a.material_id   = f.material_key
  AND a.fiscal_period_key = f.fiscal_period_key
WHERE a.actual_quantity > 0
  AND (cal.period_idx - vc.cut_period_idx) >= 1;   -- genuine forward forecast of a now-closed period

-- per-SKU scorecard at lag-2: WMAPE + signed bias
CREATE OR REPLACE VIEW lily.vw_forecast_accuracy AS
SELECT
    sales_org, material_id, lag,
    COUNT(DISTINCT fiscal_period_key)                     AS periods_scored,
    SUM(actual_quantity)                                  AS total_actual_qty,
    ROUND(SUM(abs_error_qty) / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS wmape_pct,
    ROUND(SUM(error_qty)     / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS bias_pct
FROM lily.vw_forecast_actual_matched
WHERE lag = 2
GROUP BY sales_org, material_id, lag;

-- signed bias per SKU per closed period (lag-2) — the drift trend
CREATE OR REPLACE VIEW lily.vw_forecast_bias AS
SELECT
    sales_org, material_id, fiscal_year, fiscal_period, fiscal_period_key,
    SUM(actual_quantity)                                  AS actual_qty,
    SUM(forecast_quantity)                                AS forecast_qty,
    ROUND(SUM(forecast_quantity - actual_quantity) / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS bias_pct
FROM lily.vw_forecast_actual_matched
WHERE lag = 2
GROUP BY sales_org, material_id, fiscal_year, fiscal_period, fiscal_period_key;

-- triage inputs for "what should I focus on now?": recent accuracy/bias (last 3
-- closed, lag-2) + materiality (trailing-12 revenue/qty) + family. Not pre-ranked.
CREATE OR REPLACE VIEW lily.vw_sku_performance AS
WITH closed AS (
    SELECT fiscal_period_key, period_idx,
           RANK() OVER (ORDER BY period_idx DESC) AS recency
    FROM (
        SELECT DISTINCT a.fiscal_period_key, cal.period_idx
        FROM warehouse.fact_actuals a
        JOIN lily.vw_calendar cal ON cal.fiscal_period_key = a.fiscal_period_key
    ) x
),
recent_perf AS (
    SELECT m.sales_org, m.material_id,
           ROUND(SUM(m.abs_error_qty) / NULLIF(SUM(m.actual_quantity), 0) * 100, 1) AS recent_wmape_pct,
           ROUND(SUM(m.error_qty)     / NULLIF(SUM(m.actual_quantity), 0) * 100, 1) AS recent_bias_pct
    FROM lily.vw_forecast_actual_matched m
    JOIN closed c ON c.fiscal_period_key = m.fiscal_period_key
    WHERE m.lag = 2 AND c.recency <= 3
    GROUP BY m.sales_org, m.material_id
),
materiality AS (
    SELECT h.sales_org, h.material_id,
           ROUND(SUM(h.actual_revenue_eur), 2)            AS trailing_12m_revenue_eur,
           SUM(h.actual_quantity)                         AS trailing_12m_qty
    FROM lily.vw_actuals_history h
    JOIN closed c ON c.fiscal_period_key = h.fiscal_period_key
    WHERE c.recency <= 12
    GROUP BY h.sales_org, h.material_id
)
SELECT
    mat.sales_org, mat.material_id,
    fam.l1_division, fam.l2_category,
    mat.trailing_12m_revenue_eur, mat.trailing_12m_qty,
    rp.recent_wmape_pct, rp.recent_bias_pct,
    (SELECT fiscal_period_key FROM lily.vw_latest_closed) AS latest_closed_period
FROM materiality mat
LEFT JOIN recent_perf rp
       ON rp.sales_org = mat.sales_org AND rp.material_id = mat.material_id
LEFT JOIN lily.vw_material_family fam ON fam.material_id = mat.material_id;


-- ----------------------------------------------------------------------------
-- 7. CROSS-SKU / FAMILY SCANS  (one call, no looping; statistical cols dropped)
-- ----------------------------------------------------------------------------

-- one row per SKU: demand, budget gap, trailing revenue, YoY actual growth, family.
CREATE OR REPLACE VIEW lily.vw_sku_divergence AS
WITH demand AS (
    SELECT sales_org, material_id, SUM(forecast_quantity) AS demand_qty
    FROM lily.vw_forecast_latest
    GROUP BY sales_org, material_id
),
db AS (
    SELECT sales_org, material_id,
           SUM(demand_qty) AS demand_qty_b, SUM(budget_qty) AS budget_qty
    FROM lily.vw_demand_vs_budget
    GROUP BY sales_org, material_id
),
yoy AS (
    SELECT sales_org, material_id,
       SUM(actual_quantity) FILTER (WHERE fiscal_year = (SELECT MAX(fiscal_year) FROM lily.vw_actuals_history))     AS qty_last_fy,
       SUM(actual_quantity) FILTER (WHERE fiscal_year = (SELECT MAX(fiscal_year) - 1 FROM lily.vw_actuals_history)) AS qty_prior_fy
    FROM lily.vw_actuals_history
    GROUP BY sales_org, material_id
)
SELECT
    dem.sales_org, dem.material_id,
    fam.l1_division, fam.l2_category,
    dem.demand_qty,
    ROUND((db.demand_qty_b - db.budget_qty) / NULLIF(db.budget_qty, 0) * 100, 1) AS demand_vs_budget_pct,
    perf.trailing_12m_revenue_eur,
    ROUND((yoy.qty_last_fy - yoy.qty_prior_fy) / NULLIF(yoy.qty_prior_fy, 0) * 100, 1) AS yoy_growth_pct
FROM demand dem
LEFT JOIN db   ON db.sales_org   = dem.sales_org AND db.material_id   = dem.material_id
LEFT JOIN yoy  ON yoy.sales_org  = dem.sales_org AND yoy.material_id  = dem.material_id
LEFT JOIN lily.vw_sku_performance perf ON perf.sales_org = dem.sales_org AND perf.material_id = dem.material_id
LEFT JOIN lily.vw_material_family fam  ON fam.material_id = dem.material_id;

-- rolled up to product family (L1/L2)
CREATE OR REPLACE VIEW lily.vw_family_divergence AS
SELECT
    l1_division, l2_category,
    COUNT(*)                                              AS n_skus,
    ROUND(SUM(trailing_12m_revenue_eur), 2)               AS family_trailing_revenue_eur,
    SUM(demand_qty)                                       AS demand_qty,
    ROUND(AVG(demand_vs_budget_pct), 1)                   AS avg_demand_vs_budget_pct,
    ROUND(AVG(yoy_growth_pct), 1)                         AS avg_yoy_growth_pct
FROM lily.vw_sku_divergence
GROUP BY l1_division, l2_category;
