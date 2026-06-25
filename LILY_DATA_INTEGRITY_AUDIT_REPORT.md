# Lily data-integrity audit report

Audit date: 2026-06-25

Scope:
- `sql/lily_views_pg.sql`
- `agents/lily/tools.py`
- live Azure Postgres `warehouse.*` and `lily.*`

Verification commands run:
- `python apply_views.py`
- `python test_tools_pg.py`
- `python -m py_compile agents\lily\tools.py`

## Executive summary

I found and fixed seven material serving-layer defects:

1. Forecast revenue/margin/value fields treated missing pricing as real zeroes outside priced periods.
2. `get_overview()` used text `MIN/MAX(fiscal_period_key)` and reported the wrong forecast horizon.
3. `vw_demand_vs_budget` hid demand-only and budget-only rows, and value deltas mixed unpriced demand revenue with budget value.
4. `vw_sku_divergence` and `actuals_history()` compared partial FY2026 against full FY2025.
5. `vw_family_divergence` averaged SKU-level percentages instead of weighting by quantity.
6. `vw_forecast_version_delta` used an inner join and hid new/dropped forecast rows between vintages.
7. Forecast accuracy/bias scored only overlap rows, excluding forecast-only false positives and actual-only misses.

I also added context to inventory coverage for zero-demand periods. I did not change its main flag definition because the full-horizon average can be a legitimate business definition, but the alternate active-demand basis is now visible.

## Problems found and fixed

### 1. Forecast revenue and margin contamination from unpriced periods

Failure:
`vw_forecast_future` exposed `revenue = 0`, `margin = revenue - ABS(cogs)`, and `unit_price = revenue / quantity` even when revenue was not loaded. That leaked into `get_forecast`, `top_skus`, `vw_demand_vs_budget.value_delta_eur`, and revenue rankings.

Proof query:

```sql
SELECT sales_org, material_id, fiscal_year, fiscal_period, fiscal_period_key,
       SUM(forecast_quantity) AS qty,
       SUM(forecast_revenue_eur) AS revenue,
       SUM(forecast_cogs_eur) AS cogs_abs,
       SUM(forecast_margin_eur) AS current_margin
FROM lily.vw_forecast_latest
GROUP BY 1,2,3,4,5
HAVING SUM(forecast_revenue_eur) = 0
   AND SUM(forecast_cogs_eur) > 0
   AND SUM(forecast_quantity) > 0
ORDER BY SUM(forecast_margin_eur)
LIMIT 10;
```

Before fix examples:
- SKU `107899`, org `3010`, P12 FY2027: qty `168477`, revenue `0`, cogs `545060.02`, margin `-545060.02`.
- SKU `199052`, org `3010`, P11 FY2026: qty `15554`, revenue `0`, cogs `430000.21`, margin `-430000.21`.

Post-fix check:

```sql
SELECT fiscal_year, fiscal_period, fiscal_period_key,
       SUM(forecast_quantity) AS qty,
       SUM(forecast_revenue_eur) AS revenue,
       SUM(forecast_margin_eur) AS margin
FROM lily.vw_forecast_latest
GROUP BY 1,2,3
ORDER BY fiscal_year DESC, fiscal_period DESC
LIMIT 4;
```

Post-fix result for FY2028 P5-P8: revenue and margin are `NULL`, not authoritative zeroes.

Severity:
High. It can directly produce wrong raise/lower/keep reasoning on profitability and value gaps.

Fix:
`forecast_revenue_eur = NULLIF(revenue, 0)`, margin/unit price only on `revenue > 0`, revenue ranks use `NULLS LAST`, and `top_skus(..., by="revenue")` filters out null-revenue periods.

### 2. Tool horizon used text-key ordering

Failure:
`get_overview()` used `MIN/MAX(fiscal_period_key)` over text keys. Text ordering reported the latest forecast horizon as `001.2027` to `012.2027`.

Proof query:

```sql
SELECT MIN(fiscal_period_key) AS text_min_period,
       MAX(fiscal_period_key) AS text_max_period,
       (SELECT fiscal_period_key FROM lily.vw_forecast_latest
        ORDER BY fiscal_year, fiscal_period LIMIT 1) AS chrono_first_period,
       (SELECT fiscal_period_key FROM lily.vw_forecast_latest
        ORDER BY fiscal_year DESC, fiscal_period DESC LIMIT 1) AS chrono_last_period
FROM lily.vw_forecast_latest;
```

Result:
- Text min/max: `001.2027` to `012.2027`.
- Correct chronological horizon: `009.2026` to `008.2028`.

Severity:
Medium. It is orienting metadata, but it can make Lily reason over the wrong planning window.

Fix:
`get_overview()` now orders by `fiscal_year, fiscal_period`.

### 3. Demand-vs-budget silently dropped most non-overlap rows

Failure:
`vw_demand_vs_budget` used an inner join between latest forecast demand and budget. It showed only overlap rows, hiding demand without budget and budget without demand. `vw_sku_divergence` then mixed full-horizon `demand_qty` with a budget percentage calculated only over overlap rows.

Proof query:

```sql
WITH d AS (
  SELECT sales_org, customer_code, material_id, fiscal_period_key, SUM(forecast_quantity) qty
  FROM lily.vw_forecast_latest GROUP BY 1,2,3,4
),
b AS (
  SELECT sales_org, customer_code, material_id, fiscal_period_key, SUM(budget_quantity) qty
  FROM lily.vw_budget GROUP BY 1,2,3,4
),
j AS (
  SELECT d.qty d_qty, b.qty b_qty
  FROM d FULL OUTER JOIN b USING (sales_org, customer_code, material_id, fiscal_period_key)
)
SELECT COUNT(*) AS full_rows,
       COUNT(*) FILTER (WHERE d_qty IS NOT NULL AND b_qty IS NOT NULL) AS overlap_rows,
       COUNT(*) FILTER (WHERE d_qty IS NOT NULL AND b_qty IS NULL) AS demand_only_rows,
       COUNT(*) FILTER (WHERE d_qty IS NULL AND b_qty IS NOT NULL) AS budget_only_rows,
       SUM(COALESCE(d_qty,0)) AS full_demand_qty,
       SUM(d_qty) FILTER (WHERE d_qty IS NOT NULL AND b_qty IS NOT NULL) AS overlap_demand_qty
FROM j;
```

Before fix result:
- Full rows `480822`
- Overlap rows `9652`
- Demand-only rows `442573`
- Budget-only rows `28597`
- Full demand qty `221639931`
- Overlap demand qty `3694048`

Post-fix check:

```sql
SELECT comparison_status, COUNT(*) rows, SUM(demand_qty), SUM(budget_qty)
FROM lily.vw_demand_vs_budget
GROUP BY comparison_status;
```

Post-fix result:
- `OVERLAP`: `9652` rows
- `DEMAND_ONLY`: `442573` rows
- `BUDGET_ONLY`: `3064` future rows

Severity:
High for budget-gap scans. It can hide the fact that a SKU has no budget coverage and can make a gap look comparable when it is not.

Fix:
`vw_demand_vs_budget` is now full-outer over future periods, with `comparison_status`, demand row/pricing counts, and null value deltas where demand revenue is unpriced. Tools now report overlap/demand-only/budget-only counts.

### 4. Partial FY2026 vs full FY2025 YoY

Failure:
`vw_sku_divergence.yoy_growth_pct` and `actuals_history()` compared FY2026 P1-P8 against full FY2025 P1-P12.

Proof query:

```sql
WITH latest AS (SELECT fiscal_year AS y, fiscal_period AS p FROM lily.vw_latest_closed),
agg AS (
 SELECT
  SUM(actual_quantity) FILTER (WHERE fiscal_year = (SELECT y FROM latest)) AS cur_qty,
  SUM(actual_quantity) FILTER (WHERE fiscal_year = (SELECT y FROM latest)-1) AS prior_full_qty,
  SUM(actual_quantity) FILTER (WHERE fiscal_year = (SELECT y FROM latest)-1
                               AND fiscal_period <= (SELECT p FROM latest)) AS prior_ytd_qty
 FROM lily.vw_actuals_history
)
SELECT (cur_qty-prior_full_qty)/prior_full_qty*100 AS served_yoy_pct,
       (cur_qty-prior_ytd_qty)/prior_ytd_qty*100 AS comparable_ytd_yoy_pct
FROM agg;
```

Before fix result:
- Full-year-style YoY: `-29.2%`
- Comparable P1-P8 YoY: `-3.4%`

Severity:
High. This directly changes growth/decline interpretation.

Fix:
`vw_sku_divergence` now uses current FY YTD vs prior FY same periods and exposes `yoy_current_ytd_qty`, `yoy_prior_ytd_qty`, `yoy_compared_periods`, and `yoy_basis`. `actuals_history()` now sets `latest_full_year_yoy_pct` to `None` when the latest year is incomplete and adds `latest_ytd_yoy_pct`.

### 5. Family average-of-ratios skew

Failure:
`vw_family_divergence` used `AVG(demand_vs_budget_pct)` and `AVG(yoy_growth_pct)`, so tiny-denominator SKUs dominated family metrics.

Proof query:

```sql
SELECT l1_division, l2_category, COUNT(*) n_skus,
       AVG(demand_vs_budget_pct) AS old_avg_budget_pct,
       (SUM(budget_scope_demand_qty)-SUM(budget_qty))/SUM(budget_qty)*100 AS weighted_budget_pct,
       AVG(yoy_growth_pct) AS old_avg_yoy_pct,
       (SUM(yoy_current_ytd_qty)-SUM(yoy_prior_ytd_qty))/SUM(yoy_prior_ytd_qty)*100 AS weighted_yoy_pct
FROM lily.vw_sku_divergence
GROUP BY 1,2
HAVING COUNT(*) >= 5;
```

Examples:
- `HOME PEST CONTROLS / OTHER PESTS`: old budget avg `375.6%`, weighted `-32.5%`.
- `GARDEN CONTROLS / GARDEN CONTROLS`: old budget avg `294.9%`, weighted `-6.3%`.
- `GROWING MEDIA / GROWING MEDIA`: old YoY avg `92.2%`, weighted `7.1%`.

Severity:
High for family scan decisions. It can flip the sign of a category-level recommendation.

Fix:
`vw_family_divergence` keeps the existing column names for compatibility but now computes weighted family percentages from summed quantities. It also exposes SKU counts with valid budget/YoY comparisons.

### 6. Forecast version delta inner join hid new and dropped rows

Failure:
`vw_forecast_version_delta` used an inner join between current and prior vintages. The SQL coalesced prior quantity to zero, but that branch could never fire for current-only rows.

Proof query:

```sql
WITH versions AS (
    SELECT forecast_version_key,
           DENSE_RANK() OVER (ORDER BY week_start_date DESC) AS rnk
    FROM lily.vw_version_cut
),
cur AS MATERIALIZED (
    SELECT f.sales_organization_key AS sales_org,
           f.customer_group_key AS customer_code,
           f.material_key AS material_id,
           f.fiscal_period_key,
           SUM(f.quantity) AS cur_qty,
           SUM(f.revenue) AS cur_rev
    FROM warehouse.fact_forecast f
    JOIN versions v
      ON v.forecast_version_key = f.forecast_version_key
     AND v.rnk = 1
    GROUP BY 1,2,3,4
),
pri AS MATERIALIZED (
    SELECT f.sales_organization_key AS sales_org,
           f.customer_group_key AS customer_code,
           f.material_key AS material_id,
           f.fiscal_period_key,
           SUM(f.quantity) AS pri_qty,
           SUM(f.revenue) AS pri_rev
    FROM warehouse.fact_forecast f
    JOIN versions v
      ON v.forecast_version_key = f.forecast_version_key
     AND v.rnk = 2
    GROUP BY 1,2,3,4
),
j AS (
  SELECT c.cur_qty, p.pri_qty
  FROM cur c FULL OUTER JOIN pri p
  USING (sales_org, customer_code, material_id, fiscal_period_key)
)
SELECT COUNT(*) AS full_rows,
       COUNT(*) FILTER (WHERE cur_qty IS NOT NULL AND pri_qty IS NOT NULL) AS overlap_rows,
       COUNT(*) FILTER (WHERE cur_qty IS NOT NULL AND pri_qty IS NULL) AS current_only_rows,
       COUNT(*) FILTER (WHERE cur_qty IS NULL AND pri_qty IS NOT NULL) AS prior_only_rows
FROM j;
```

Before fix result:
- Full rows `517709`
- Served rows / overlap rows `329891`
- Current-only rows `122334`
- Prior-only rows `65484`

Post-fix future-horizon result:
- Rows `494047`
- Overlap `327601`
- Current-only `122054`
- Prior-only `41543`

Severity:
High for revision/movement analysis. New demand and dropped demand were invisible.

Fix:
`vw_forecast_version_delta` now uses a full outer join and calculates quantity/revenue deltas for overlap, current-only, and prior-only rows.

### 7. Forecast accuracy/bias excluded forecast-only and actual-only errors

Failure:
`vw_forecast_actual_matched` used an inner join to actuals and `a.actual_quantity > 0`. Forecasts with no actuals and actual sales with no forecast were not scored. It also had a period-lag grain but could include multiple weekly versions in the same cut period.

Proof query:

```sql
WITH scoring_versions(forecast_version_key, cut_period_key, target_period_key, fiscal_year, fiscal_period) AS (VALUES
 ('44.2025','011.2025','001.2026',2026,1),
 ('52.2025','012.2025','002.2026',2026,2),
 ('05.2026','002.2026','004.2026',2026,4),
 ('09.2026','003.2026','005.2026',2026,5),
 ('14.2026','004.2026','006.2026',2026,6),
 ('18.2026','005.2026','007.2026',2026,7),
 ('22.2026','006.2026','008.2026',2026,8)
),
f AS MATERIALIZED (
 SELECT sv.forecast_version_key,
        sv.cut_period_key,
        f.sales_organization_key AS sales_org,
        f.customer_group_key AS customer_code,
        f.material_key AS material_id,
        sv.target_period_key AS fiscal_period_key,
        SUM(f.quantity) AS forecast_qty
 FROM scoring_versions sv
 JOIN warehouse.fact_forecast f
   ON f.forecast_version_key = sv.forecast_version_key
  AND f.fiscal_period_key = sv.target_period_key
 GROUP BY 1,2,3,4,5,6
),
a AS MATERIALIZED (
 SELECT sv.forecast_version_key,
        sv.cut_period_key,
        a.sales_organization_key AS sales_org,
        a.customer_group_key AS customer_code,
        a.material_key AS material_id,
        sv.target_period_key AS fiscal_period_key,
        SUM(a.quantity) AS actual_qty
 FROM scoring_versions sv
 JOIN warehouse.fact_actuals a
   ON a.fiscal_period_key = sv.target_period_key
 GROUP BY 1,2,3,4,5,6
),
fullj AS MATERIALIZED (
 SELECT COALESCE(f.forecast_version_key, a.forecast_version_key) AS forecast_version_key,
        COALESCE(f.sales_org, a.sales_org) AS sales_org,
        COALESCE(f.customer_code, a.customer_code) AS customer_code,
        COALESCE(f.material_id, a.material_id) AS material_id,
        COALESCE(f.fiscal_period_key, a.fiscal_period_key) AS fiscal_period_key,
        COALESCE(f.forecast_qty, 0) AS forecast_qty,
        COALESCE(a.actual_qty, 0) AS actual_qty,
        f.forecast_qty IS NULL AS actual_only,
        a.actual_qty IS NULL AS forecast_only
 FROM f FULL OUTER JOIN a
 USING (forecast_version_key, cut_period_key, sales_org, customer_code, material_id, fiscal_period_key)
),
innerj AS MATERIALIZED (
 SELECT f.forecast_qty, a.actual_qty
 FROM f
 JOIN a
 USING (forecast_version_key, cut_period_key, sales_org, customer_code, material_id, fiscal_period_key)
 WHERE a.actual_qty > 0
)
SELECT COUNT(*) AS full_rows,
       (SELECT COUNT(*) FROM innerj) AS served_like_rows,
       COUNT(*) FILTER (WHERE forecast_only AND forecast_qty <> 0) AS forecast_only_rows,
       SUM(forecast_qty) FILTER (WHERE forecast_only) AS forecast_only_qty,
       COUNT(*) FILTER (WHERE actual_only AND actual_qty <> 0) AS actual_only_rows,
       SUM(actual_qty) FILTER (WHERE actual_only) AS actual_only_qty,
       (SELECT SUM(ABS(forecast_qty - actual_qty)) FROM innerj)
         / NULLIF((SELECT SUM(actual_qty) FROM innerj), 0) * 100 AS served_like_wmape_pct,
       SUM(ABS(forecast_qty - actual_qty))
         / NULLIF(SUM(actual_qty), 0) * 100 AS full_wmape_pct,
       (SELECT SUM(forecast_qty - actual_qty) FROM innerj)
         / NULLIF((SELECT SUM(actual_qty) FROM innerj), 0) * 100 AS served_like_bias_pct,
       SUM(forecast_qty - actual_qty)
         / NULLIF(SUM(actual_qty), 0) * 100 AS full_bias_pct
FROM fullj;
```

Before/fixed-basis result:
- Old overlap-like rows `64012`
- Full scored rows `132859`
- Forecast-only rows `43464`
- Actual-only rows `23787`
- WMAPE moved from `51.2%` to `73.7%`
- Bias moved from `6.2%` to `9.1%`

Severity:
High. Accuracy/bias was materially optimistic and could hide systematic false positives/misses.

Fix:
`vw_forecast_actual_matched` now builds a full scored frame for closed target periods, uses one primary weekly vintage per cut period, and appends `match_status` and `forecast_version_key`. `vw_forecast_accuracy` and `forecast_performance()` expose overlap/forecast-only/actual-only row counts.

### 8. Inventory coverage zero-demand context

Finding:
`vw_inventory_coverage` averages over all forward forecast periods. That is defensible for full-horizon coverage, but zero-demand periods can inflate coverage for seasonal SKUs.

Proof query:

```sql
WITH periods AS (
 SELECT sales_org, material_id, fiscal_period_key, SUM(forecast_quantity) qty
 FROM lily.vw_forecast_latest GROUP BY 1,2,3
),
alt AS (
 SELECT sales_org, material_id,
        AVG(qty) AS served_avg_qty,
        AVG(qty) FILTER (WHERE qty > 0) AS positive_avg_qty,
        COUNT(*) FILTER (WHERE qty = 0) AS zero_periods
 FROM periods GROUP BY 1,2
)
SELECT COUNT(*) FILTER (WHERE zero_periods > 0) AS rows_with_zero_periods
FROM alt;
```

Result:
- `39` inventory rows have zero-demand periods.
- `3` rows would move from `OVERSTOCK` to `OK` if active-demand-only average were used.

Severity:
Medium. It can change an inventory flag, but the original full-horizon metric is a plausible definition.

Fix:
Kept the original metric and added `zero_demand_periods`, `active_demand_periods`, `active_avg_period_qty`, and `active_coverage_periods` to the view/tool.

## All-clear checks

These areas were checked and did not require a high-severity fix:

- `vw_calendar`, `vw_latest_closed`, `vw_version_cut`, `vw_latest_vintage`: period/version ordering uses calendar/week dates, not raw text keys.
- `vw_material_family`: uses `dim_material -> dim_product_hierarchy`, not the sparse `dim_material_sales_organization` helper. Live latest forecast coverage: `3254/3254` materials have L2 category.
- `dim_material_sales_organization`: not used by the serving views. For the current latest forecast slice it happens to match `3703/3704` material-org combos, but the code no longer depends on it.
- `warehouse.fact_forecast` grain: no duplicate rows at `(sales_org, customer, material, version, period)`.
- `vw_budget_vs_last_year`: budget is FY2026 only and compares against FY2025, which has all 12 actual periods loaded. No partial-current-year leak found there.
- `vw_flat_forecast_check`: no sparse-measure ratios; uses quantity shape only.
- `vw_product_economics`: already fixed before this audit; post-smoke SKU `107899` still reports `46.1%` priced-period margin, `7/24` priced periods.
- `vw_sku_performance` / `sku_performance_scan`: inherits the fixed full-frame accuracy view and trailing-12 materiality uses closed actual periods.

## Post-fix verification

`python apply_views.py` succeeded and verified all 25 `lily.*` views. Key row counts after the fix:

- `vw_forecast_latest`: `452225`
- `vw_demand_vs_budget`: `455289`
- `vw_forecast_version_delta`: `494047`
- `vw_forecast_actual_matched`: `745858`
- `vw_forecast_accuracy`: `4847`
- `vw_sku_divergence`: `3704`
- `vw_family_divergence`: `23`

`python test_tools_pg.py` succeeded: all tools ran against live Postgres.

Focused tool checks:
- `get_overview()["forecast_horizon"]`: `["009.2026", "008.2028"]`
- `actuals_history("107899")["summary"]["latest_full_year_yoy_pct"]`: `null`
- `actuals_history("107899")["summary"]["latest_ytd_yoy_pct"]`: `-1.1`
- `top_skus(2028, 8, by="revenue")`: returns no rows rather than ranking unpriced revenue noise.
