-- ============================================================================
-- EGC Demand Planning — Lily Serving-Layer Views
-- Database : PostgreSQL   |   Schema : dw
-- Pattern  : One Big Table (OBT) serving layer for an AI agent.
--            Everything pre-joined, pre-aggregated, pre-calculated.
--            Lily reads finished numbers — she never joins or computes.
--
-- Scope    : BR-06, BR-08, BR-09, BR-11 (Lily only).
--            BR-09 and BR-11 are served by the base views (no own view).
--
-- ⚠⚠⚠  BEFORE RUNNING — replace these THREE placeholder tokens everywhere:
--        <<STAT_VERSION_KEY>>    statistical forecast version key
--        <<DEMAND_VERSION_KEY>>  demand-planner consensus version key
--        <<BUDGET_VERSION_KEY>>  sales / budget version key
--      Find them with:
--        SELECT DISTINCT forecast_version_key, COUNT(*)
--        FROM dw.fct_forecast GROUP BY 1 ORDER BY 2 DESC;
--
-- ⚠ NOTE: This draft is written against the schema on paper only — not yet
--   run against real data. Treat as a reviewed first draft for Bart to run.
-- ============================================================================


-- ============================================================================
-- HELPER VIEWS  (cheap, regular views — give every view a shared notion of
-- chronological period order and "what is the current period")
-- ============================================================================

-- Chronological rank of every fiscal period. Periods 1..12 are chronological
-- within a fiscal year (P1 = October), so ORDER BY (fiscal_year, period) is the
-- true timeline. period_rank lets us compute "periods_from_now" robustly.
CREATE OR REPLACE VIEW dw.v_period_order AS
SELECT
    fiscal_period_key,
    fiscal_year,
    period,
    ROW_NUMBER() OVER (ORDER BY fiscal_year, period) AS period_rank
FROM dw.dim_fiscal_period;

-- "Current period" = the latest period that has any actuals. Actuals only exist
-- for closed/current periods, so their max rank is the present. Anything beyond
-- is the future. This avoids needing a calendar-date mapping.
CREATE OR REPLACE VIEW dw.v_current_period AS
SELECT MAX(po.period_rank) AS current_rank
FROM dw.fct_actuals a
JOIN dw.v_period_order po ON a.fiscal_period_key = po.fiscal_period_key;


-- ============================================================================
-- LAYER 1 — BASE VIEWS (MATERIALIZED)
-- Four data streams + every pre-computed comparison, one row per grain×period.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- v_planning_sku   —   Grain: Sales Org × SKU × Period
-- ----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS dw.v_planning_sku CASCADE;
CREATE MATERIALIZED VIEW dw.v_planning_sku AS
WITH
-- Actuals aggregated to the view grain, carrying year/period for the LY join.
actuals AS (
    SELECT
        a.sales_organization_id,
        a.material_id,
        a.fiscal_period_key,
        fp.fiscal_year,
        fp.period,
        SUM(a.actual_quantity)    AS actual_qty,
        SUM(a.actual_revenue_eur) AS actual_revenue_eur
    FROM dw.fct_actuals a
    JOIN dw.dim_fiscal_period fp ON a.fiscal_period_key = fp.fiscal_period_key
    GROUP BY 1, 2, 3, 4, 5
),
-- Forecast pivoted: one column per version key (statistical / demand / budget).
forecast AS (
    SELECT
        f.sales_organization_id,
        f.material_id,
        f.fiscal_period_key,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<STAT_VERSION_KEY>>')   AS statistical_forecast_qty,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<DEMAND_VERSION_KEY>>')  AS demand_forecast_qty,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<BUDGET_VERSION_KEY>>')  AS budget_qty
    FROM dw.fct_forecast f
    GROUP BY 1, 2, 3
),
-- Spine: every (grain × period) that appears in either fact table.
spine AS (
    SELECT sales_organization_id, material_id, fiscal_period_key FROM actuals
    UNION
    SELECT sales_organization_id, material_id, fiscal_period_key FROM forecast
)
SELECT
    -- Grain / dimensions ----------------------------------------------------
    s.sales_organization_id,
    so.sales_organization_name,
    s.material_id,
    m.material_description,
    m.product_hierarchy_level_1_description,
    m.product_hierarchy_level_2_description,
    m.product_hierarchy_level_3_description,
    m.product_hierarchy_level_4_description,
    mg.material_group_description,
    po.fiscal_year,
    po.period,
    s.fiscal_period_key,
    -- Time position ---------------------------------------------------------
    (po.period_rank > cp.current_rank)        AS is_future,
    (po.period_rank - cp.current_rank)        AS periods_from_now,  -- neg=past, 0=current, pos=future
    -- Raw streams -----------------------------------------------------------
    a.actual_qty,
    a.actual_revenue_eur,
    ly.actual_qty                             AS actual_qty_ly,
    f.statistical_forecast_qty,
    f.demand_forecast_qty,
    f.budget_qty,
    -- Pre-computed comparisons (★ high value) -------------------------------
    (f.demand_forecast_qty - ly.actual_qty)                                                              AS demand_vs_ly_delta,
    ROUND((f.demand_forecast_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                   AS demand_vs_ly_pct,
    (f.demand_forecast_qty - f.statistical_forecast_qty)                                                 AS demand_vs_stat_delta,
    ROUND((f.demand_forecast_qty - f.statistical_forecast_qty) / NULLIF(f.statistical_forecast_qty, 0) * 100, 1) AS demand_vs_stat_pct,
    (f.demand_forecast_qty - f.budget_qty)                                                               AS demand_vs_budget_delta,
    ROUND((f.demand_forecast_qty - f.budget_qty) / NULLIF(f.budget_qty, 0) * 100, 1)                     AS demand_vs_budget_pct,
    -- Pre-computed comparisons (medium / context) ---------------------------
    ROUND((f.statistical_forecast_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)             AS stat_vs_ly_pct,
    ROUND((f.budget_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                           AS budget_vs_ly_pct,
    ROUND((a.actual_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                           AS actual_yoy_pct,
    ROUND((a.actual_qty - f.demand_forecast_qty) / NULLIF(a.actual_qty, 0) * 100, 1)                    AS demand_bias_pct
FROM spine s
JOIN dw.v_period_order po              ON s.fiscal_period_key = po.fiscal_period_key
CROSS JOIN dw.v_current_period cp
JOIN dw.dim_sales_organization so      ON s.sales_organization_id = so.sales_organization_id
JOIN dw.dim_material m                 ON s.material_id = m.material_id
LEFT JOIN dw.dim_material_group mg     ON s.material_id = mg.material_id          -- assumed 1:1 per (material, org)
                                      AND s.sales_organization_id = mg.sales_organization_id
LEFT JOIN actuals a                    ON s.sales_organization_id = a.sales_organization_id
                                      AND s.material_id = a.material_id
                                      AND s.fiscal_period_key = a.fiscal_period_key
LEFT JOIN forecast f                   ON s.sales_organization_id = f.sales_organization_id
                                      AND s.material_id = f.material_id
                                      AND s.fiscal_period_key = f.fiscal_period_key
LEFT JOIN actuals ly                   ON ly.sales_organization_id = s.sales_organization_id  -- same period, prior FY
                                      AND ly.material_id = s.material_id
                                      AND ly.fiscal_year = po.fiscal_year - 1
                                      AND ly.period = po.period;

-- Unique index required for REFRESH ... CONCURRENTLY
CREATE UNIQUE INDEX ux_planning_sku
    ON dw.v_planning_sku (sales_organization_id, material_id, fiscal_period_key);


-- ----------------------------------------------------------------------------
-- v_planning_customer   —   Grain: Sales Org × Customer × Period
-- ----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS dw.v_planning_customer CASCADE;
CREATE MATERIALIZED VIEW dw.v_planning_customer AS
WITH
actuals AS (
    SELECT
        a.sales_organization_id,
        a.customer_attribute_4,
        a.fiscal_period_key,
        fp.fiscal_year,
        fp.period,
        SUM(a.actual_quantity)    AS actual_qty,
        SUM(a.actual_revenue_eur) AS actual_revenue_eur
    FROM dw.fct_actuals a
    JOIN dw.dim_fiscal_period fp ON a.fiscal_period_key = fp.fiscal_period_key
    GROUP BY 1, 2, 3, 4, 5
),
forecast AS (
    SELECT
        f.sales_organization_id,
        f.customer_attribute_4,
        f.fiscal_period_key,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<STAT_VERSION_KEY>>')   AS statistical_forecast_qty,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<DEMAND_VERSION_KEY>>')  AS demand_forecast_qty,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<BUDGET_VERSION_KEY>>')  AS budget_qty
    FROM dw.fct_forecast f
    GROUP BY 1, 2, 3
),
spine AS (
    SELECT sales_organization_id, customer_attribute_4, fiscal_period_key FROM actuals
    UNION
    SELECT sales_organization_id, customer_attribute_4, fiscal_period_key FROM forecast
)
SELECT
    s.sales_organization_id,
    so.sales_organization_name,
    s.customer_attribute_4,
    ca.customer_attribute_4_name,
    po.fiscal_year,
    po.period,
    s.fiscal_period_key,
    (po.period_rank > cp.current_rank)        AS is_future,
    (po.period_rank - cp.current_rank)        AS periods_from_now,
    a.actual_qty,
    a.actual_revenue_eur,
    ly.actual_qty                             AS actual_qty_ly,
    f.statistical_forecast_qty,
    f.demand_forecast_qty,
    f.budget_qty,
    (f.demand_forecast_qty - ly.actual_qty)                                                              AS demand_vs_ly_delta,
    ROUND((f.demand_forecast_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                   AS demand_vs_ly_pct,
    (f.demand_forecast_qty - f.statistical_forecast_qty)                                                 AS demand_vs_stat_delta,
    ROUND((f.demand_forecast_qty - f.statistical_forecast_qty) / NULLIF(f.statistical_forecast_qty, 0) * 100, 1) AS demand_vs_stat_pct,
    (f.demand_forecast_qty - f.budget_qty)                                                               AS demand_vs_budget_delta,
    ROUND((f.demand_forecast_qty - f.budget_qty) / NULLIF(f.budget_qty, 0) * 100, 1)                     AS demand_vs_budget_pct,
    ROUND((f.statistical_forecast_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)             AS stat_vs_ly_pct,
    ROUND((f.budget_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                           AS budget_vs_ly_pct,
    ROUND((a.actual_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                           AS actual_yoy_pct,
    ROUND((a.actual_qty - f.demand_forecast_qty) / NULLIF(a.actual_qty, 0) * 100, 1)                    AS demand_bias_pct
FROM spine s
JOIN dw.v_period_order po              ON s.fiscal_period_key = po.fiscal_period_key
CROSS JOIN dw.v_current_period cp
JOIN dw.dim_sales_organization so      ON s.sales_organization_id = so.sales_organization_id
JOIN dw.dim_customer_attribute_4 ca    ON s.customer_attribute_4 = ca.customer_attribute_4
LEFT JOIN actuals a                    ON s.sales_organization_id = a.sales_organization_id
                                      AND s.customer_attribute_4 = a.customer_attribute_4
                                      AND s.fiscal_period_key = a.fiscal_period_key
LEFT JOIN forecast f                   ON s.sales_organization_id = f.sales_organization_id
                                      AND s.customer_attribute_4 = f.customer_attribute_4
                                      AND s.fiscal_period_key = f.fiscal_period_key
LEFT JOIN actuals ly                   ON ly.sales_organization_id = s.sales_organization_id
                                      AND ly.customer_attribute_4 = s.customer_attribute_4
                                      AND ly.fiscal_year = po.fiscal_year - 1
                                      AND ly.period = po.period;

CREATE UNIQUE INDEX ux_planning_customer
    ON dw.v_planning_customer (sales_organization_id, customer_attribute_4, fiscal_period_key);


-- ----------------------------------------------------------------------------
-- v_planning_sku_customer   —   Grain: Sales Org × SKU × Customer × Period
-- ----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS dw.v_planning_sku_customer CASCADE;
CREATE MATERIALIZED VIEW dw.v_planning_sku_customer AS
WITH
actuals AS (
    SELECT
        a.sales_organization_id,
        a.material_id,
        a.customer_attribute_4,
        a.fiscal_period_key,
        fp.fiscal_year,
        fp.period,
        SUM(a.actual_quantity)    AS actual_qty,
        SUM(a.actual_revenue_eur) AS actual_revenue_eur
    FROM dw.fct_actuals a
    JOIN dw.dim_fiscal_period fp ON a.fiscal_period_key = fp.fiscal_period_key
    GROUP BY 1, 2, 3, 4, 5, 6
),
forecast AS (
    SELECT
        f.sales_organization_id,
        f.material_id,
        f.customer_attribute_4,
        f.fiscal_period_key,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<STAT_VERSION_KEY>>')   AS statistical_forecast_qty,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<DEMAND_VERSION_KEY>>')  AS demand_forecast_qty,
        SUM(f.forecast_quantity) FILTER (WHERE f.forecast_version_key = '<<BUDGET_VERSION_KEY>>')  AS budget_qty
    FROM dw.fct_forecast f
    GROUP BY 1, 2, 3, 4
),
spine AS (
    SELECT sales_organization_id, material_id, customer_attribute_4, fiscal_period_key FROM actuals
    UNION
    SELECT sales_organization_id, material_id, customer_attribute_4, fiscal_period_key FROM forecast
)
SELECT
    s.sales_organization_id,
    so.sales_organization_name,
    s.material_id,
    m.material_description,
    m.product_hierarchy_level_1_description,
    m.product_hierarchy_level_2_description,
    s.customer_attribute_4,
    ca.customer_attribute_4_name,
    po.fiscal_year,
    po.period,
    s.fiscal_period_key,
    (po.period_rank > cp.current_rank)        AS is_future,
    (po.period_rank - cp.current_rank)        AS periods_from_now,
    a.actual_qty,
    a.actual_revenue_eur,
    ly.actual_qty                             AS actual_qty_ly,
    f.statistical_forecast_qty,
    f.demand_forecast_qty,
    f.budget_qty,
    (f.demand_forecast_qty - ly.actual_qty)                                                              AS demand_vs_ly_delta,
    ROUND((f.demand_forecast_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                   AS demand_vs_ly_pct,
    (f.demand_forecast_qty - f.statistical_forecast_qty)                                                 AS demand_vs_stat_delta,
    ROUND((f.demand_forecast_qty - f.statistical_forecast_qty) / NULLIF(f.statistical_forecast_qty, 0) * 100, 1) AS demand_vs_stat_pct,
    (f.demand_forecast_qty - f.budget_qty)                                                               AS demand_vs_budget_delta,
    ROUND((f.demand_forecast_qty - f.budget_qty) / NULLIF(f.budget_qty, 0) * 100, 1)                     AS demand_vs_budget_pct,
    ROUND((f.statistical_forecast_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)             AS stat_vs_ly_pct,
    ROUND((f.budget_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                           AS budget_vs_ly_pct,
    ROUND((a.actual_qty - ly.actual_qty) / NULLIF(ly.actual_qty, 0) * 100, 1)                           AS actual_yoy_pct,
    ROUND((a.actual_qty - f.demand_forecast_qty) / NULLIF(a.actual_qty, 0) * 100, 1)                    AS demand_bias_pct
FROM spine s
JOIN dw.v_period_order po              ON s.fiscal_period_key = po.fiscal_period_key
CROSS JOIN dw.v_current_period cp
JOIN dw.dim_sales_organization so      ON s.sales_organization_id = so.sales_organization_id
JOIN dw.dim_material m                 ON s.material_id = m.material_id
JOIN dw.dim_customer_attribute_4 ca    ON s.customer_attribute_4 = ca.customer_attribute_4
LEFT JOIN actuals a                    ON s.sales_organization_id = a.sales_organization_id
                                      AND s.material_id = a.material_id
                                      AND s.customer_attribute_4 = a.customer_attribute_4
                                      AND s.fiscal_period_key = a.fiscal_period_key
LEFT JOIN forecast f                   ON s.sales_organization_id = f.sales_organization_id
                                      AND s.material_id = f.material_id
                                      AND s.customer_attribute_4 = f.customer_attribute_4
                                      AND s.fiscal_period_key = f.fiscal_period_key
LEFT JOIN actuals ly                   ON ly.sales_organization_id = s.sales_organization_id
                                      AND ly.material_id = s.material_id
                                      AND ly.customer_attribute_4 = s.customer_attribute_4
                                      AND ly.fiscal_year = po.fiscal_year - 1
                                      AND ly.period = po.period;

CREATE UNIQUE INDEX ux_planning_sku_customer
    ON dw.v_planning_sku_customer (sales_organization_id, material_id, customer_attribute_4, fiscal_period_key);


-- ============================================================================
-- LAYER 2 — BR-SPECIFIC VIEWS
-- ============================================================================

-- ----------------------------------------------------------------------------
-- BR-06 · v_br06_inventory_coverage  (MATERIALIZED)
-- How many future periods of demand can today's stock cover? Cutoff is computed
-- per SKU/plant from a running total of forecast demand vs current inventory.
-- Grain: Sales Org × SKU × Plant × Future Period (up to next 12 periods)
-- ----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS dw.v_br06_inventory_coverage CASCADE;
CREATE MATERIALIZED VIEW dw.v_br06_inventory_coverage AS
WITH
-- Current stock = the latest inventory snapshot per SKU/plant.
latest_inv AS (
    SELECT DISTINCT ON (sales_organization_id, material_id, plant_id)
        sales_organization_id,
        material_id,
        plant_id,
        inventory_quantity AS current_inventory_qty
    FROM dw.fct_inventory
    ORDER BY sales_organization_id, material_id, plant_id, fiscal_period_key DESC
),
-- Demand forecast for the next 12 future periods, aggregated across customers.
future_demand AS (
    SELECT
        f.sales_organization_id,
        f.material_id,
        f.plant_id,
        f.fiscal_period_key,
        po.fiscal_year,
        po.period,
        po.period_rank,
        (po.period_rank - cp.current_rank) AS periods_from_now,
        SUM(f.forecast_quantity)           AS demand_forecast_qty
    FROM dw.fct_forecast f
    JOIN dw.v_period_order po ON f.fiscal_period_key = po.fiscal_period_key
    CROSS JOIN dw.v_current_period cp
    WHERE f.forecast_version_key = '<<DEMAND_VERSION_KEY>>'
      AND po.period_rank >  cp.current_rank                 -- future only
      AND po.period_rank <= cp.current_rank + 12            -- next 12 periods
    GROUP BY 1, 2, 3, 4, 5, 6, 7, cp.current_rank
),
-- Running cumulative demand from now forward, per SKU/plant.
cumulative AS (
    SELECT
        fd.*,
        SUM(fd.demand_forecast_qty) OVER (
            PARTITION BY fd.sales_organization_id, fd.material_id, fd.plant_id
            ORDER BY fd.period_rank
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_forecast_qty
    FROM future_demand fd
)
SELECT
    c.sales_organization_id,
    so.sales_organization_name,
    c.material_id,
    m.material_description,
    c.plant_id,
    pl.plant_name,
    li.current_inventory_qty,
    c.fiscal_year                                          AS future_fiscal_year,
    c.period                                               AS future_period,
    c.periods_from_now,
    c.demand_forecast_qty,
    c.cumulative_forecast_qty,
    (c.cumulative_forecast_qty <= li.current_inventory_qty) AS still_covered,
    -- First future period where cumulative demand exceeds stock (relative to now).
    MIN(CASE WHEN c.cumulative_forecast_qty > li.current_inventory_qty
             THEN c.periods_from_now END)
        OVER (PARTITION BY c.sales_organization_id, c.material_id, c.plant_id)
                                                            AS coverage_cutoff_periods_from_now
FROM cumulative c
JOIN latest_inv li                ON c.sales_organization_id = li.sales_organization_id
                                 AND c.material_id = li.material_id
                                 AND c.plant_id = li.plant_id
JOIN dw.dim_sales_organization so ON c.sales_organization_id = so.sales_organization_id
JOIN dw.dim_material m            ON c.material_id = m.material_id
JOIN dw.dim_plant pl              ON c.plant_id = pl.plant_id;

CREATE UNIQUE INDEX ux_br06_inventory_coverage
    ON dw.v_br06_inventory_coverage (sales_organization_id, material_id, plant_id, future_fiscal_year, future_period);

-- NOTE: "weeks_cover" (from the old BR-05) is intentionally omitted. The cumulative
-- month-coverage / cutoff model above is the metric the business actually described.


-- ----------------------------------------------------------------------------
-- BR-08 · Forecast Version Comparison  (regular views — queries are narrow)
-- How has the forecast for a given FUTURE period changed across planning cycles?
-- Versions ordered by load_id (proxy for cycle order — see PLAN.md parked item).
-- Three grains: SKU, Customer, SKU+Customer.
-- ----------------------------------------------------------------------------

-- BR-08a · by SKU
CREATE OR REPLACE VIEW dw.v_br08_forecast_versions_sku AS
WITH versioned AS (
    SELECT
        f.sales_organization_id,
        f.material_id,
        f.fiscal_period_key,
        f.forecast_version_key,
        f.load_id,
        SUM(f.forecast_quantity) AS forecast_qty
    FROM dw.fct_forecast f
    JOIN dw.v_period_order po ON f.fiscal_period_key = po.fiscal_period_key
    CROSS JOIN dw.v_current_period cp
    WHERE po.period_rank > cp.current_rank             -- future periods only
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    v.sales_organization_id,
    so.sales_organization_name,
    v.material_id,
    m.material_description,
    po.fiscal_year   AS future_fiscal_year,
    po.period        AS future_period,
    v.forecast_version_key,
    v.load_id,
    v.forecast_qty,
    LAG(v.forecast_qty) OVER w AS forecast_qty_prior_version,
    (v.forecast_qty - LAG(v.forecast_qty) OVER w)                                   AS version_delta,
    ROUND((v.forecast_qty - LAG(v.forecast_qty) OVER w)
          / NULLIF(LAG(v.forecast_qty) OVER w, 0) * 100, 1)                         AS version_delta_pct
FROM versioned v
JOIN dw.v_period_order po         ON v.fiscal_period_key = po.fiscal_period_key
JOIN dw.dim_sales_organization so ON v.sales_organization_id = so.sales_organization_id
JOIN dw.dim_material m            ON v.material_id = m.material_id
WINDOW w AS (
    PARTITION BY v.sales_organization_id, v.material_id, v.fiscal_period_key
    ORDER BY v.load_id
);

-- BR-08b · by Customer
CREATE OR REPLACE VIEW dw.v_br08_forecast_versions_customer AS
WITH versioned AS (
    SELECT
        f.sales_organization_id,
        f.customer_attribute_4,
        f.fiscal_period_key,
        f.forecast_version_key,
        f.load_id,
        SUM(f.forecast_quantity) AS forecast_qty
    FROM dw.fct_forecast f
    JOIN dw.v_period_order po ON f.fiscal_period_key = po.fiscal_period_key
    CROSS JOIN dw.v_current_period cp
    WHERE po.period_rank > cp.current_rank
    GROUP BY 1, 2, 3, 4, 5
)
SELECT
    v.sales_organization_id,
    so.sales_organization_name,
    v.customer_attribute_4,
    ca.customer_attribute_4_name,
    po.fiscal_year   AS future_fiscal_year,
    po.period        AS future_period,
    v.forecast_version_key,
    v.load_id,
    v.forecast_qty,
    LAG(v.forecast_qty) OVER w AS forecast_qty_prior_version,
    (v.forecast_qty - LAG(v.forecast_qty) OVER w)                                   AS version_delta,
    ROUND((v.forecast_qty - LAG(v.forecast_qty) OVER w)
          / NULLIF(LAG(v.forecast_qty) OVER w, 0) * 100, 1)                         AS version_delta_pct
FROM versioned v
JOIN dw.v_period_order po           ON v.fiscal_period_key = po.fiscal_period_key
JOIN dw.dim_sales_organization so   ON v.sales_organization_id = so.sales_organization_id
JOIN dw.dim_customer_attribute_4 ca ON v.customer_attribute_4 = ca.customer_attribute_4
WINDOW w AS (
    PARTITION BY v.sales_organization_id, v.customer_attribute_4, v.fiscal_period_key
    ORDER BY v.load_id
);

-- BR-08c · by SKU + Customer
CREATE OR REPLACE VIEW dw.v_br08_forecast_versions_sku_customer AS
WITH versioned AS (
    SELECT
        f.sales_organization_id,
        f.material_id,
        f.customer_attribute_4,
        f.fiscal_period_key,
        f.forecast_version_key,
        f.load_id,
        SUM(f.forecast_quantity) AS forecast_qty
    FROM dw.fct_forecast f
    JOIN dw.v_period_order po ON f.fiscal_period_key = po.fiscal_period_key
    CROSS JOIN dw.v_current_period cp
    WHERE po.period_rank > cp.current_rank
    GROUP BY 1, 2, 3, 4, 5, 6
)
SELECT
    v.sales_organization_id,
    so.sales_organization_name,
    v.material_id,
    m.material_description,
    v.customer_attribute_4,
    ca.customer_attribute_4_name,
    po.fiscal_year   AS future_fiscal_year,
    po.period        AS future_period,
    v.forecast_version_key,
    v.load_id,
    v.forecast_qty,
    LAG(v.forecast_qty) OVER w AS forecast_qty_prior_version,
    (v.forecast_qty - LAG(v.forecast_qty) OVER w)                                   AS version_delta,
    ROUND((v.forecast_qty - LAG(v.forecast_qty) OVER w)
          / NULLIF(LAG(v.forecast_qty) OVER w, 0) * 100, 1)                         AS version_delta_pct
FROM versioned v
JOIN dw.v_period_order po           ON v.fiscal_period_key = po.fiscal_period_key
JOIN dw.dim_sales_organization so   ON v.sales_organization_id = so.sales_organization_id
JOIN dw.dim_material m              ON v.material_id = m.material_id
JOIN dw.dim_customer_attribute_4 ca ON v.customer_attribute_4 = ca.customer_attribute_4
WINDOW w AS (
    PARTITION BY v.sales_organization_id, v.material_id, v.customer_attribute_4, v.fiscal_period_key
    ORDER BY v.load_id
);


-- ============================================================================
-- NIGHTLY REFRESH  (run after the DW ETL load completes)
-- CONCURRENTLY keeps the views readable during refresh (needs the unique
-- indexes created above). BR-08 views are regular views — no refresh needed.
-- ============================================================================
-- REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_planning_sku;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_planning_customer;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_planning_sku_customer;
-- REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_br06_inventory_coverage;


-- ============================================================================
-- SANITY CHECKS  (run after first build)
-- ============================================================================
-- SELECT COUNT(*) FROM dw.v_planning_sku;
-- SELECT * FROM dw.v_planning_sku
--   WHERE material_id = '<<SOME_SKU>>' AND sales_organization_id = '<<SOME_ORG>>'
--   ORDER BY fiscal_year, period;
-- SELECT * FROM dw.v_br06_inventory_coverage
--   WHERE material_id = '<<SOME_SKU>>' ORDER BY periods_from_now;
-- -- Confirm the three version keys resolved (no all-NULL forecast columns):
-- SELECT COUNT(*) FILTER (WHERE statistical_forecast_qty IS NOT NULL) AS stat_rows,
--        COUNT(*) FILTER (WHERE demand_forecast_qty      IS NOT NULL) AS demand_rows,
--        COUNT(*) FILTER (WHERE budget_qty               IS NOT NULL) AS budget_rows
-- FROM dw.v_planning_sku;
