-- ============================================================================
-- LILY — Views that RUN on the data Bart provided (June 2026)
-- Source files: FY26P06W27 - Forecast.xlsx, FY26P07 - Actuals.xlsx
-- Target tables: dw.fct_forecast, dw.fct_actuals   |   Output schema: lily
--
-- This file contains ONLY views the current data can actually run:
--   - one demand-forecast stream (forecast_quantity)
--   - one forecast version loaded (week 27 / FY2026)
--   - one closed actuals period (P07 FY2026), kept as a reference snapshot
--
-- Views needing statistical/budget streams, actuals history, or a 2nd
-- forecast version are NOT here — they are blocked on data, not design.
-- See lily_view_catalog.md for the full set and what each one waits on.
--
-- Key encoding (per Bart's "Lily Dataset Overview" doc):
--   forecast_version_key  2026027  -> FY2026 week 27   (year*1000 + week)
--   fiscal_period_key     202608   -> FY2026 period 08 (year*100  + period)
-- "Future" = any period after the latest closed actuals period.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS lily;


-- ============================================================================
-- 1. FOUNDATION
-- ============================================================================

-- vw_forecast_future: all future forecast, all versions, SAP fields made
-- business-readable, with margin / selling price pre-computed.
-- GRAIN: sales_org + material + customer_group + plant + version + period
CREATE OR REPLACE VIEW lily.vw_forecast_future AS
SELECT
    f.sales_organization_id,
    f.material_id,
    f.customer_attribute_4                                   AS customer_group,
    f.plant_id,
    f.forecast_version_key,
    (f.forecast_version_key / 1000)                          AS forecast_version_year,
    (f.forecast_version_key % 1000)                          AS forecast_version_week,
    f.fiscal_period_key,
    (f.fiscal_period_key / 100)                              AS fiscal_year,
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
WHERE f.fiscal_period_key > (SELECT MAX(fiscal_period_key) FROM dw.fct_actuals)
  AND f.forecast_quantity IS NOT NULL;


-- vw_forecast_latest: only the most recently loaded forecast version.
-- USE FOR: "what is the current plan" — no version confusion.
CREATE OR REPLACE VIEW lily.vw_forecast_latest AS
SELECT *
FROM lily.vw_forecast_future
WHERE forecast_version_key = (SELECT MAX(forecast_version_key) FROM dw.fct_forecast);


-- vw_actuals_latest: the single most recent closed period. Reference snapshot
-- only (a sanity anchor), NOT for past-performance reporting (that's Billy).
CREATE OR REPLACE VIEW lily.vw_actuals_latest AS
SELECT
    a.sales_organization_id,
    a.material_id,
    a.customer_attribute_4                                   AS customer_group,
    a.plant_id,
    a.fiscal_period_key,
    (a.fiscal_period_key / 100)                              AS fiscal_year,
    (a.fiscal_period_key % 100)                              AS fiscal_period,
    a.actual_quantity,
    a.actual_revenue_eur
FROM dw.fct_actuals a
WHERE a.fiscal_period_key = (SELECT MAX(fiscal_period_key) FROM dw.fct_actuals);


-- ============================================================================
-- 2. VALUE  (the questions planners ask most)
-- ============================================================================

-- vw_sku_forecast_ranked: SKUs ranked within each future period.
-- USE FOR: "top 5 SKUs by units expected in P05 next year"
--          -> filter fiscal_year + fiscal_period, take rank_by_qty <= 5.
CREATE OR REPLACE VIEW lily.vw_sku_forecast_ranked AS
SELECT
    fiscal_year,
    fiscal_period,
    fiscal_period_key,
    material_id,
    SUM(forecast_quantity)                                   AS total_qty,
    SUM(forecast_revenue_eur)                                AS total_revenue_eur,
    SUM(forecast_margin_eur)                                 AS total_margin_eur,
    RANK() OVER (PARTITION BY fiscal_period_key ORDER BY SUM(forecast_quantity)    DESC) AS rank_by_qty,
    RANK() OVER (PARTITION BY fiscal_period_key ORDER BY SUM(forecast_revenue_eur) DESC) AS rank_by_revenue
FROM lily.vw_forecast_latest
GROUP BY fiscal_year, fiscal_period, fiscal_period_key, material_id;


-- vw_customer_forecast_ranked: customer groups ranked within each future period.
-- USE FOR: "top 5 customers by forecast revenue in a period".
CREATE OR REPLACE VIEW lily.vw_customer_forecast_ranked AS
SELECT
    fiscal_year,
    fiscal_period,
    fiscal_period_key,
    customer_group,
    SUM(forecast_quantity)                                   AS total_qty,
    SUM(forecast_revenue_eur)                                AS total_revenue_eur,
    SUM(forecast_margin_eur)                                 AS total_margin_eur,
    RANK() OVER (PARTITION BY fiscal_period_key ORDER BY SUM(forecast_revenue_eur) DESC) AS rank_by_revenue
FROM lily.vw_forecast_latest
GROUP BY fiscal_year, fiscal_period, fiscal_period_key, customer_group;


-- vw_product_economics: per-product economics across the whole horizon.
-- USE FOR: "what's the COGS / selling price of this SKU?" and
--          "if we sell 20,000 units, what's the revenue?" (qty * avg_selling_price).
CREATE OR REPLACE VIEW lily.vw_product_economics AS
SELECT
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
GROUP BY material_id;


-- ============================================================================
-- 3. QUALITY
-- ============================================================================

-- vw_flat_forecast_check: SKU + customer combos whose forecast is identical or
-- near-identical across 3+ future periods — likely copy-paste placeholders.
CREATE OR REPLACE VIEW lily.vw_flat_forecast_check AS
WITH period_qty AS (
    SELECT material_id, customer_group, fiscal_period_key,
           SUM(forecast_quantity) AS qty
    FROM lily.vw_forecast_latest
    GROUP BY material_id, customer_group, fiscal_period_key
),
stats AS (
    SELECT
        material_id,
        customer_group,
        COUNT(*)               AS periods,
        COUNT(DISTINCT qty)    AS distinct_values,
        MIN(qty)               AS min_qty,
        MAX(qty)               AS max_qty,
        ROUND(AVG(qty), 0)     AS avg_qty
    FROM period_qty
    GROUP BY material_id, customer_group
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
-- 4. VERSION MOVEMENT  (structure runs now; populates once a 2nd week loads)
-- ============================================================================

-- vw_forecast_version_delta: compares the two most recent forecast versions,
-- per SKU + customer + future period. Returns 0 rows until version 2 exists
-- (currently only week 27 is loaded).
CREATE OR REPLACE VIEW lily.vw_forecast_version_delta AS
WITH versions AS (
    SELECT DISTINCT forecast_version_key,
           RANK() OVER (ORDER BY forecast_version_key DESC) AS rnk
    FROM dw.fct_forecast
    WHERE fiscal_period_key > (SELECT MAX(fiscal_period_key) FROM dw.fct_actuals)
),
cur AS (
    SELECT material_id, customer_group, fiscal_period_key, fiscal_year, fiscal_period,
           SUM(forecast_quantity)    AS cur_qty,
           SUM(forecast_revenue_eur) AS cur_rev
    FROM lily.vw_forecast_future
    WHERE forecast_version_key = (SELECT forecast_version_key FROM versions WHERE rnk = 1)
    GROUP BY material_id, customer_group, fiscal_period_key, fiscal_year, fiscal_period
),
pri AS (
    SELECT material_id, customer_group, fiscal_period_key,
           SUM(forecast_quantity)    AS pri_qty,
           SUM(forecast_revenue_eur) AS pri_rev
    FROM lily.vw_forecast_future
    WHERE forecast_version_key = (SELECT forecast_version_key FROM versions WHERE rnk = 2)
    GROUP BY material_id, customer_group, fiscal_period_key
)
SELECT
    c.material_id,
    c.customer_group,
    c.fiscal_year,
    c.fiscal_period,
    c.fiscal_period_key,
    c.cur_qty,
    COALESCE(p.pri_qty, 0)                                   AS pri_qty,
    (c.cur_qty - COALESCE(p.pri_qty, 0))                     AS qty_delta,
    CASE WHEN COALESCE(p.pri_qty, 0) = 0 THEN NULL
         ELSE ROUND((c.cur_qty - p.pri_qty) / p.pri_qty::numeric * 100, 1) END AS qty_delta_pct,
    c.cur_rev,
    COALESCE(p.pri_rev, 0)                                   AS pri_rev,
    (c.cur_rev - COALESCE(p.pri_rev, 0))                     AS revenue_delta_eur
FROM cur c
LEFT JOIN pri p
       ON c.material_id       = p.material_id
      AND c.customer_group    = p.customer_group
      AND c.fiscal_period_key = p.fiscal_period_key;


-- ============================================================================
-- VERIFY (run after creating)
-- ============================================================================
-- SELECT COUNT(*) FROM lily.vw_forecast_future;            -- expect ~8,600 rows
-- SELECT DISTINCT forecast_version_key FROM lily.vw_forecast_latest;  -- one week
-- SELECT * FROM lily.vw_sku_forecast_ranked WHERE rank_by_qty <= 5 ORDER BY fiscal_period_key;
-- SELECT * FROM lily.vw_product_economics ORDER BY total_forecast_revenue_eur DESC LIMIT 10;
-- SELECT * FROM lily.vw_flat_forecast_check LIMIT 20;
-- SELECT COUNT(*) FROM lily.vw_forecast_version_delta;     -- 0 until a 2nd week loads
