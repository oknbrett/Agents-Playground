"""Lily's data tools — read-only queries over the SQL serving layer (lily.* views).

Lily reads finished numbers from the lily.* views; she never does SQL, joins, or math.

Two backing stores, same view columns (see _connect()):
  - Azure Postgres (real warehouse) via Entra token — views in sql/lily_views_pg.sql.
  - Local DuckDB (synthetic dev) — views in sql/lily_views_runnable.sql.

Lily is full-scope:
  - demand forecast stream (the planner's plan, latest weekly vintage)
  - budget (sales target) as its own stream
  - inventory coverage (current stock vs forward demand)
  - the full actuals sales history (all closed periods) as forward-decision evidence
  - forecast accuracy/bias (lag-2), rebuilt from the weekly forecast vintages.
NOTE: the real warehouse has NO statistical-baseline stream, so there is no
demand-vs-statistical override tool (removed 2026-06-24).

Semantics: sales_org = sales_organization_key (region/BU: 1010 DE, 1210 FR,
2510 Benelux, 3710 Pokon, …); customer_code = customer_group_key (the customer);
material_id = material_key (SKU). fiscal_period_key is text (008.2026 = P8 FY2026)
and does NOT sort chronologically — the views order via fiscal_year + fiscal_period.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import duckdb

# ── Connection ──────────────────────────────────────────────────────────────
# Three ways to reach the data, checked in order:
#   1. Azure Postgres via Entra ID token  — set LILY_PG_HOST (+ optional overrides).
#      Token is fetched from `az` (Entra/AAD). Bart's recommended path: a direct
#      connection from the agent, no MCP server / Azure Function in between.
#   2. Azure Postgres via plain conn string — set LILY_DB_URL (incl. password).
#      Useful with the admin password Bart can hand out as a fallback.
#   3. Local DuckDB (dev) — the synthetic dataset. Used when neither above is set.
# The lily.* views expose the same columns on Postgres and DuckDB, so the tool
# functions below work unchanged across all three.

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "sql" / "lily_local.duckdb"
_con = None
_is_pg = False   # True once connected to Postgres (drives ?->%s placeholder translation)

# Azure Postgres defaults (override via env). Matches test_postgres.py / HANDOFF.md.
_PG_HOST = os.environ.get("LILY_PG_HOST", "billy-ai-postgresql.postgres.database.azure.com")
_PG_DB   = os.environ.get("LILY_PG_DB", "ai-agent-db")
_PG_USER = os.environ.get("LILY_PG_USER", "Ong.KhoiNguyen@evergreengarden.com")
_AZ_CMD  = os.environ.get("LILY_AZ_CMD",
                          r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd")


def _entra_token() -> str:
    """Fetch an Entra ID access token for Azure Postgres via the `az` CLI."""
    import subprocess
    return subprocess.check_output(
        [_AZ_CMD, "account", "get-access-token",
         "--resource-type", "oss-rdbms",
         "--query", "accessToken", "-o", "tsv"],
        text=True,
    ).strip()


def _connect():
    global _con, _is_pg
    if _con is not None:
        return _con

    import psycopg2  # local import: only needed on the Postgres paths

    # 1. Entra-token path (opt in by setting LILY_PG_HOST or LILY_USE_ENTRA).
    if os.environ.get("LILY_USE_ENTRA") or os.environ.get("LILY_PG_HOST"):
        password = os.environ.get("LILY_PG_PASSWORD") or _entra_token()
        _con = psycopg2.connect(
            host=_PG_HOST, dbname=_PG_DB, user=_PG_USER,
            password=password, sslmode="require",
        )
        _con.set_session(readonly=True, autocommit=True)
        _is_pg = True
        return _con

    # 2. Plain connection-string path (password embedded).
    db_url = os.environ.get("LILY_DB_URL")
    if db_url:
        _con = psycopg2.connect(db_url)
        _con.set_session(readonly=True, autocommit=True)
        _is_pg = True
        return _con

    # 3. Local DuckDB (dev / synthetic).
    db_path = os.environ.get("LILY_DB_PATH", str(_DEFAULT_DB))
    if not Path(db_path).exists():
        raise RuntimeError(
            f"Local DB not found at {db_path}. Build it first: "
            "python sql/generate_synthetic.py"
        )
    _con = duckdb.connect(db_path, read_only=True)
    return _con


def _round(v):
    # Postgres returns numeric columns as Decimal, which isn't JSON-serializable
    # and doesn't compare/sum cleanly with floats — coerce to float here, at the
    # data boundary, so every tool payload is plain JSON. (DuckDB returns floats.)
    if isinstance(v, Decimal):
        v = float(v)
    return round(v, 2) if isinstance(v, float) else v


def _execute(sql: str, params: list | None = None):
    con = _connect()
    if _is_pg:
        # psycopg2 uses %s placeholders; the tool SQL is written with DuckDB's ?.
        # (No literal % appears in the tool SQL, so a plain swap is safe.)
        sql = sql.replace("?", "%s")
        cur = con.cursor()
        cur.execute(sql, params or [])
    else:
        cur = con.execute(sql, params or [])
    return cur


def _query(sql: str, params: list | None = None) -> list[dict]:
    cur = _execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [{c: _round(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def _one(sql: str, params: list | None = None):
    return _round(_execute(sql, params).fetchone()[0])


# ── Tools ─────────────────────────────────────────────────────────────────────

def get_overview() -> dict:
    """Orient: what data the warehouse holds right now — sales orgs (regions),
    customer/material counts, the loaded forecast version + horizon, the latest
    closed actuals period, and which streams exist."""
    orgs = [r["sales_org"] for r in _query(
        "SELECT DISTINCT sales_org FROM lily.vw_forecast_latest ORDER BY sales_org")]
    customers = [r["customer_code"] for r in _query(
        "SELECT DISTINCT customer_code FROM lily.vw_forecast_latest ORDER BY customer_code")]
    span = _query(
        "SELECT MIN(fiscal_period_key) AS first_period, "
        "MAX(fiscal_period_key) AS last_period, "
        "MIN(forecast_version_key) AS version, "
        "COUNT(DISTINCT material_id) AS materials, "
        "COUNT(DISTINCT customer_code) AS customers "
        "FROM lily.vw_forecast_latest")[0]
    actuals_period = _one("SELECT fiscal_period_key FROM lily.vw_latest_closed")
    return {
        "sales_orgs": orgs,
        "sales_org_note": "sales_org = region / business unit (e.g. 1010 Germany, "
                          "1210 France, 2510 Benelux, 3710 Pokon).",
        "customer_count": span["customers"],
        "customer_codes": customers,
        "customer_note": "Customers are identified by customer_group_key (e.g. A2 = MIGROS); "
                         "names live in warehouse.dim_customer_group.",
        "material_count": span["materials"],
        "forecast_version_key": span["version"],
        "forecast_version_note": "forecast_version_key is the weekly VINTAGE the forecast "
                                 "was cut in (e.g. 35.2026); this is the latest cut.",
        "forecast_horizon": [span["first_period"], span["last_period"]],
        "latest_closed_actuals_period": actuals_period,
        "streams_available": {
            "demand_forecast": True,
            "budget": _one("SELECT COUNT(*) FROM lily.vw_budget") > 0,
            "inventory": _one("SELECT COUNT(*) FROM lily.vw_inventory_latest") > 0,
            "actuals_anchor": actuals_period is not None,
            "actuals_history": _one("SELECT COUNT(DISTINCT fiscal_year) FROM lily.vw_actuals_history") > 1,
            "forecast_accuracy": _one("SELECT COUNT(*) FROM lily.vw_forecast_accuracy") > 0,
            "version_movement": _one("SELECT COUNT(*) FROM lily.vw_forecast_version_delta") > 0,
        },
        "actuals_history_span": _query(
            "SELECT MIN(fiscal_year) AS first_year, MAX(fiscal_year) AS last_year, "
            "COUNT(DISTINCT fiscal_period_key) AS periods FROM lily.vw_actuals_history")[0],
        "fiscal_calendar": "FY starts in October: P1=Oct, P5=Feb, P8=May, P12=Sep "
                           "(008.2026 = P8 FY2026 = May 2026). The text key does NOT sort "
                           "chronologically — order via fiscal_year + fiscal_period. "
                           "'Now' = the period after the latest closed actuals.",
        "note": "Full-scope: forward plan (forecast vs budget, economics, inventory, "
                "forecast revision between weekly vintages) AND backward performance "
                "(forecast accuracy/bias, lag-2 basis). No statistical baseline stream "
                "exists in this warehouse — the planner's hand shows as forecast revision "
                "between vintages (vw_forecast_version_delta).",
    }


def get_forecast(material_id: str, sales_org: int | None = None,
                 customer_code: str | None = None) -> dict:
    """The forward demand forecast for one SKU, period by period, with revenue,
    margin and unit price pre-computed. Aggregates across customers unless
    customer_code is given. Includes a shape summary (flat? lumpy? trend?)."""
    where = ["material_id = ?"]
    params: list = [str(material_id)]
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    if customer_code is not None:
        where.append("customer_code = ?"); params.append(customer_code)
    clause = " AND ".join(where)

    rows = _query(
        f"SELECT fiscal_year, fiscal_period, fiscal_period_key, "
        f"SUM(forecast_quantity) AS qty, "
        f"ROUND(SUM(forecast_revenue_eur), 2) AS revenue_eur, "
        f"ROUND(SUM(forecast_margin_eur), 2) AS margin_eur "
        f"FROM lily.vw_forecast_latest WHERE {clause} "
        f"GROUP BY fiscal_year, fiscal_period, fiscal_period_key "
        f"ORDER BY fiscal_year, fiscal_period", params)
    if not rows:
        return {"error": f"No forecast for material '{material_id}'"
                         + (f" / org {sales_org}" if sales_org else "")
                         + (f" / customer {customer_code}" if customer_code else "")}

    qtys = [r["qty"] for r in rows]
    distinct = len(set(qtys))
    summary = {
        "periods": len(rows),
        "total_qty": sum(qtys),
        "min_qty": min(qtys),
        "max_qty": max(qtys),
        "avg_qty": round(sum(qtys) / len(qtys), 1),
        "distinct_qty_values": distinct,
        "shape_flag": ("FLAT - identical every period (possible placeholder)"
                       if distinct == 1 and len(rows) >= 3 else "VARIES"),
    }
    return {
        "material_id": str(material_id),
        "sales_org": sales_org or "all",
        "customer_code": customer_code or "all",
        "records": rows,
        "summary": summary,
    }


def demand_vs_budget(material_id: str, sales_org: int | None = None,
                     customer_code: str | None = None) -> dict:
    """Planner demand forecast vs the sales budget (target), per future period.
    Shows where the plan and the target disagree, and which way."""
    where = ["material_id = ?"]
    params: list = [str(material_id)]
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    if customer_code is not None:
        where.append("customer_code = ?"); params.append(customer_code)
    clause = " AND ".join(where)

    # Aggregate to period grain (sum across customers) unless a customer is named —
    # one row per period, not per customer×period. Keeps tool output small.
    rows = _query(
        f"SELECT fiscal_year, fiscal_period, "
        f"SUM(demand_qty) AS demand_qty, SUM(budget_qty) AS budget_qty, "
        f"SUM(demand_qty) - SUM(budget_qty) AS qty_delta, "
        f"CASE WHEN SUM(budget_qty) > 0 THEN "
        f"  ROUND((SUM(demand_qty) - SUM(budget_qty)) / SUM(budget_qty)::numeric * 100, 1) END AS qty_delta_pct, "
        f"ROUND(SUM(value_delta_eur), 2) AS value_delta_eur "
        f"FROM lily.vw_demand_vs_budget WHERE {clause} "
        f"GROUP BY fiscal_year, fiscal_period, fiscal_period_key "
        f"ORDER BY fiscal_year, fiscal_period", params)
    if not rows:
        return {"material_id": str(material_id), "records": [],
                "note": "No overlapping demand+budget rows for this scope."}
    deltas = [r["qty_delta_pct"] for r in rows if r["qty_delta_pct"] is not None]
    return {
        "material_id": str(material_id),
        "grain": "per period" + ("" if customer_code else ", summed across all customers"),
        "records": rows,
        "summary": {
            "periods": len(rows),
            "periods_demand_above_budget": sum(1 for r in rows if r["qty_delta"] and r["qty_delta"] > 0),
            "periods_demand_below_budget": sum(1 for r in rows if r["qty_delta"] and r["qty_delta"] < 0),
            "avg_delta_pct": round(sum(deltas) / len(deltas), 1) if deltas else None,
        },
    }


# NOTE: demand_vs_statistical was removed 2026-06-24 — this warehouse has no
# statistical-baseline stream, so the "planner override = demand - statistical"
# signal has no source. The vintage-revision view (lily.vw_forecast_version_delta)
# remains available if we later want a forecast_revision tool as the override lens.


def inventory_coverage(material_id: str, sales_org: int | None = None) -> dict:
    """Current on-hand stock vs forward demand, per sales_org (product level —
    inventory has no customer dimension). coverage_periods = stock / avg period
    demand; flags STOCKOUT RISK (<1) and OVERSTOCK (>12). EA units only."""
    where = ["material_id = ?"]
    params: list = [str(material_id)]
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    rows = _query(
        f"SELECT sales_org, stock_qty_ea, avg_period_qty, total_future_qty, "
        f"future_periods, coverage_periods, coverage_flag, has_non_ea_stock, uom_present "
        f"FROM lily.vw_inventory_coverage WHERE {' AND '.join(where)} "
        f"ORDER BY coverage_periods NULLS LAST", params)
    if not rows:
        return {"material_id": str(material_id), "records": [],
                "note": "No inventory↔forecast overlap for this material."}
    return {"material_id": str(material_id), "records": rows}


def product_economics(material_id: str, sales_org: int | None = None) -> dict:
    """COGS, unit selling price, and margin for a SKU. Price/COGS/margin are
    computed ONLY over PRICED periods (where revenue is loaded) — the forecast
    projects quantity further out than pricing, so a horizon-wide average would
    understate price and fake a loss. `priced_periods`/`total_periods` show how
    much of the horizon carries pricing; if priced_periods << total_periods, treat
    the economics as covering only the near term, not the whole plan."""
    where = ["material_id = ?"]
    params: list = [str(material_id)]
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    rows = _query(
        f"SELECT sales_org, total_forecast_qty, priced_qty, priced_periods, total_periods, "
        f"total_forecast_revenue_eur, total_forecast_cogs_eur, total_forecast_margin_eur, "
        f"margin_pct, avg_selling_price_eur, avg_unit_cogs_eur "
        f"FROM lily.vw_product_economics WHERE {' AND '.join(where)} "
        f"ORDER BY sales_org", params)
    if not rows:
        return {"error": f"No economics for material '{material_id}'."}
    return {
        "material_id": str(material_id),
        "note": "price/COGS/margin are over PRICED periods only; if priced_periods "
                "< total_periods, pricing isn't loaded for the full horizon.",
        "records": rows,
    }


def top_skus(fiscal_year: int, fiscal_period: int, sales_org: int | None = None,
             by: str = "qty", n: int = 5) -> dict:
    """Top-N SKUs in a future period. by = 'qty' or 'revenue'."""
    rank_col = "rank_by_revenue" if by == "revenue" else "rank_by_qty"
    where = ["fiscal_year = ?", "fiscal_period = ?", f"{rank_col} <= ?"]
    params: list = [fiscal_year, fiscal_period, n]
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    rows = _query(
        f"SELECT sales_org, material_id, total_qty, total_revenue_eur, "
        f"total_margin_eur, {rank_col} AS rank "
        f"FROM lily.vw_sku_forecast_ranked WHERE {' AND '.join(where)} "
        f"ORDER BY sales_org, rank", params)
    return {"fiscal_year": fiscal_year, "fiscal_period": fiscal_period,
            "ranked_by": by, "records": rows}


_FAMILY_ORDER = {
    "revenue": "family_trailing_revenue_eur DESC NULLS LAST",
    "budget": "ABS(avg_demand_vs_budget_pct) DESC NULLS LAST",
    "growth": "avg_yoy_growth_pct DESC NULLS LAST",
}


def family_scan(order_by: str = "revenue") -> dict:
    """Cross-family rollup in ONE call: every product family (L1/L2 hierarchy)
    with its trailing-12m revenue, average demand-vs-budget gap %, average YoY
    growth, and SKU count. Use this FIRST for 'biggest family' / 'which category'
    questions, then drill with divergence_scan(category=...). Ordered by revenue
    by default ('budget' or 'growth' also available)."""
    order = _FAMILY_ORDER.get(order_by, _FAMILY_ORDER["revenue"])
    rows = _query(
        f"SELECT l1_division, l2_category, n_skus, family_trailing_revenue_eur, "
        f"avg_demand_vs_budget_pct, avg_yoy_growth_pct "
        f"FROM lily.vw_family_divergence ORDER BY {order}")
    return {"ordered_by": order_by, "count": len(rows), "records": rows}


_DIVERGENCE_ORDER = {
    "revenue": "trailing_12m_revenue_eur DESC NULLS LAST",
    "budget": "ABS(demand_vs_budget_pct) DESC NULLS LAST",
    "growth": "yoy_growth_pct DESC NULLS LAST",
}


def divergence_scan(category: str | None = None, order_by: str = "revenue",
                    n: int = 50) -> dict:
    """Cross-SKU scan in ONE call — every SKU's demand-vs-budget gap, trailing-12m
    revenue, YoY actual growth, and family. Use this instead of looping the per-SKU
    tools: it lets you reason over the COMPLETE set, not a sample. Optionally filter
    to one family (L2 category). Ordered by revenue by default; order_by='budget'
    surfaces the biggest plan-vs-target gaps, 'growth' the history."""
    order = _DIVERGENCE_ORDER.get(order_by, _DIVERGENCE_ORDER["revenue"])
    where, params = [], []
    if category is not None:
        where.append("l2_category = ?"); params.append(category)
    wc = ("WHERE " + " AND ".join(where)) if where else ""
    total = _one(f"SELECT COUNT(*) FROM lily.vw_sku_divergence {wc}", params)
    rows = _query(
        f"SELECT material_id, l2_category, demand_qty, "
        f"demand_vs_budget_pct, trailing_12m_revenue_eur, yoy_growth_pct "
        f"FROM lily.vw_sku_divergence {wc} ORDER BY {order} LIMIT ?", params + [n])
    return {
        "category": category or "all families",
        "ordered_by": order_by,
        "returned": len(rows),
        "total_matching": total,
        "note": ("One-call summary of every SKU in scope: demand qty, budget gap, "
                 "revenue, YoY growth. Filter by category or raise n for the full set "
                 "— only the LIMIT trims, nothing is sampled."),
        "records": rows,
    }


def forecast_performance(material_id: str, sales_org: int | None = None,
                         customer_code: str | None = None, lag: int = 2) -> dict:
    """Forecast accuracy and bias for a SKU — how recent forecasts actually
    performed against what sold, on a lag-2 basis by default. WMAPE (volume-
    weighted error) + signed bias (over/under), plus the bias per period so a
    persistent one-directional drift is visible. Aggregates across customers
    unless customer_code is given."""
    where = ["material_id = ?", "lag = ?"]
    params: list = [str(material_id), lag]
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    if customer_code is not None:
        where.append("customer_code = ?"); params.append(customer_code)
    clause = " AND ".join(where)

    card = _query(
        f"SELECT COUNT(DISTINCT fiscal_period_key) AS periods_scored, "
        f"SUM(actual_quantity) AS total_actual_qty, "
        f"ROUND(SUM(abs_error_qty) / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS wmape_pct, "
        f"ROUND(SUM(error_qty)     / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS bias_pct "
        f"FROM lily.vw_forecast_actual_matched WHERE {clause}", params)
    if not card or not card[0]["periods_scored"]:
        return {"material_id": str(material_id), "records": [],
                "note": f"No lag-{lag} forecast history for this scope."}
    trend = _query(
        f"SELECT fiscal_year, fiscal_period, "
        f"SUM(actual_quantity) AS actual_qty, SUM(forecast_quantity) AS forecast_qty, "
        f"ROUND(SUM(forecast_quantity - actual_quantity) / NULLIF(SUM(actual_quantity), 0) * 100, 1) AS bias_pct "
        f"FROM lily.vw_forecast_actual_matched WHERE {clause} "
        f"GROUP BY fiscal_year, fiscal_period, fiscal_period_key "
        f"ORDER BY fiscal_year, fiscal_period", params)
    return {
        "material_id": str(material_id),
        "lag": lag,
        "metric_note": "WMAPE = sum|F-A|/sum(A); bias = sum(F-A)/sum(A); +bias = over-forecast.",
        "scorecard": card[0],
        "bias_by_period": trend,
    }


# Materiality / sort options for the focus scan (whitelisted — no SQL injection).
_SCAN_ORDER = {
    "revenue": "trailing_12m_revenue_eur DESC NULLS LAST",
    "volume": "trailing_12m_qty DESC NULLS LAST",
    "wmape": "recent_wmape_pct DESC NULLS LAST",
    "bias": "ABS(recent_bias_pct) DESC NULLS LAST",
}


def sku_performance_scan(sales_org: int | None = None, order_by: str = "revenue",
                         n: int = 25) -> dict:
    """The triage inputs for 'what should I focus on right now?' — per-SKU recent
    accuracy/bias (last 3 closed periods, lag-2) plus materiality (trailing-12m
    revenue & volume) at the latest closed period. Returns the candidate set
    ordered by `order_by` (revenue | volume | wmape | bias) for convenience; YOU
    decide the focus shortlist and state your basis. Default: top 25 by revenue."""
    order = _SCAN_ORDER.get(order_by, _SCAN_ORDER["revenue"])
    where, params = [], []
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    wc = ("WHERE " + " AND ".join(where)) if where else ""
    rows = _query(
        f"SELECT material_id, l1_division, l2_category, "
        f"trailing_12m_revenue_eur, trailing_12m_qty, recent_wmape_pct, recent_bias_pct "
        f"FROM lily.vw_sku_performance {wc} ORDER BY {order} LIMIT ?", params + [n])
    latest = _one("SELECT fiscal_period_key FROM lily.vw_latest_closed")
    return {
        "latest_closed_period": latest,
        "ordered_by": order_by,
        "count": len(rows),
        "note": "Candidates ordered by " + order_by + " for convenience. Decide the "
                "focus list yourself and state the basis you ranked on.",
        "records": rows,
    }


def actuals_history(material_id: str, sales_org: int | None = None,
                    customer_code: str | None = None) -> dict:
    """The full actuals sales history for a SKU — real sold quantity per period
    across all closed periods (multiple years), with per-year totals and YoY.
    Use to judge whether a forward forecast or planner override is backed by what
    actually happened. Aggregates across customers unless customer_code is given."""
    where = ["material_id = ?"]
    params: list = [str(material_id)]
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    if customer_code is not None:
        where.append("customer_code = ?"); params.append(customer_code)
    clause = " AND ".join(where)

    rows = _query(
        f"SELECT fiscal_year, fiscal_period, "
        f"SUM(actual_quantity) AS actual_qty, "
        f"ROUND(SUM(actual_revenue_eur), 2) AS actual_revenue_eur "
        f"FROM lily.vw_actuals_history WHERE {clause} "
        f"GROUP BY fiscal_year, fiscal_period, fiscal_period_key "
        f"ORDER BY fiscal_year, fiscal_period", params)
    if not rows:
        return {"material_id": str(material_id), "records": [],
                "note": "No actuals history for this scope."}

    by_year: dict[int, float] = {}
    for r in rows:
        by_year[r["fiscal_year"]] = by_year.get(r["fiscal_year"], 0) + (r["actual_qty"] or 0)
    years = sorted(by_year)
    yoy = None
    if len(years) >= 2 and by_year[years[-2]]:
        yoy = round((by_year[years[-1]] - by_year[years[-2]]) / by_year[years[-2]] * 100, 1)
    return {
        "material_id": str(material_id),
        "grain": "per period" + ("" if customer_code else ", summed across all customers"),
        "records": rows,
        "summary": {
            "periods": len(rows),
            "years_covered": years,
            "total_qty_by_year": {str(y): round(by_year[y]) for y in years},
            "latest_full_year_yoy_pct": yoy,
        },
    }


def latest_actuals(material_id: str, sales_org: int | None = None,
                   customer_code: str | None = None) -> dict:
    """The single most recent closed-period actuals for a SKU — a reference
    anchor only (not performance reporting). May be empty if the SKU isn't in
    the latest closed period."""
    where = ["material_id = ?"]
    params: list = [str(material_id)]
    if sales_org is not None:
        where.append("sales_org = ?"); params.append(sales_org)
    if customer_code is not None:
        where.append("customer_code = ?"); params.append(customer_code)
    rows = _query(
        f"SELECT sales_org, customer_code, plant, fiscal_year, fiscal_period, "
        f"actual_quantity, actual_revenue_eur "
        f"FROM lily.vw_actuals_latest WHERE {' AND '.join(where)} "
        f"ORDER BY sales_org, customer_code, plant", params)
    return {"material_id": str(material_id), "records": rows,
            "note": "Latest closed period only; no history (that's Billy)."}


# Backward-compat: the agent loop calls load_data() first. Keep the name as an
# orientation call; the file_path arg is ignored (data now lives in the DB).
def load_data(file_path: str | None = None) -> dict:
    return {"status": "ok", **get_overview()}
