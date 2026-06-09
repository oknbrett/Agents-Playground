"""Lily's data tools — pandas operations over the demand planning dataset.

Module-level _df is populated by load_data(). All other tools call _require_data()
which raises if load_data hasn't been called first. This mirrors a clean
"connect then query" pattern without passing DataFrames through every call.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

# ── Module state ──────────────────────────────────────────────────────────────

_df: pd.DataFrame | None = None


def _require_data() -> pd.DataFrame:
    if _df is None:
        raise RuntimeError("Call load_data() first before using other tools.")
    return _df


def _mape(actual: pd.Series, forecast: pd.Series) -> float:
    mask = actual > 0
    if mask.sum() == 0:
        return float("nan")
    return round(float((((forecast[mask] - actual[mask]).abs() / actual[mask]) * 100).mean()), 1)


def _bias(actual: pd.Series, forecast: pd.Series) -> tuple[float, str]:
    mask = actual > 0
    if mask.sum() == 0:
        return float("nan"), "unknown"
    b = round(float(((forecast[mask] - actual[mask]) / actual[mask] * 100).mean()), 1)
    direction = "over" if b > 0 else "under" if b < 0 else "neutral"
    return abs(b), direction


# ── Tools ─────────────────────────────────────────────────────────────────────

def load_data(file_path: str) -> dict:
    """Load the dataset and return an orientation summary."""
    global _df
    path = Path(file_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    if path.suffix == ".xlsx":
        _df = pd.read_excel(path)
    else:
        _df = pd.read_csv(path)

    df = _df

    # Actuals coverage per year
    coverage: dict[str, str] = {}
    for yr in sorted(df["year"].unique()):
        yr_df = df[df["year"] == yr]
        periods_with_actuals = sorted(yr_df[yr_df["actuals"] > 0]["period"].unique())
        future_periods = sorted(yr_df[yr_df["actuals"] == 0]["period"].unique())
        if future_periods:
            coverage[str(yr)] = (
                f"P1–P{periods_with_actuals[-1]} have actuals; "
                f"P{future_periods[0]}–P{future_periods[-1]} are future (actuals=0)"
            )
        else:
            coverage[str(yr)] = f"P1–P13 all have actuals"

    sku_names = (
        df[["sku_id", "sku_name"]]
        .drop_duplicates()
        .set_index("sku_id")["sku_name"]
        .to_dict()
    )

    return {
        "status": "ok",
        "row_count": len(df),
        "skus": sorted(df["sku_id"].unique().tolist()),
        "sku_names": sku_names,
        "customers": sorted(df["customer"].unique().tolist()),
        "regions": sorted(df["region"].unique().tolist()),
        "years": sorted(df["year"].unique().tolist()),
        "periods_per_year": int(df["period"].nunique()),
        "actuals_coverage": coverage,
        "columns": df.columns.tolist(),
    }


def get_sku_history(sku_id: str, customer: str | None = None) -> dict:
    """Return the full time series for one SKU, optionally filtered to one customer."""
    df = _require_data()

    sub = df[df["sku_id"] == sku_id]
    if sub.empty:
        return {"error": f"SKU '{sku_id}' not found."}

    if customer:
        sub = sub[sub["customer"] == customer]
        if sub.empty:
            return {"error": f"No data for SKU '{sku_id}' / customer '{customer}'."}

    # Aggregate across customers if no filter
    agg = (
        sub.groupby(["year", "period"], as_index=False)
        .agg(
            actuals=("actuals", "sum"),
            dp_forecast=("dp_forecast", "sum"),
            stat_forecast=("stat_forecast", "sum"),
            business_plan=("business_plan", "sum"),
        )
        .sort_values(["year", "period"])
    )

    records = agg.to_dict(orient="records")
    for r in records:
        for k in ("actuals", "dp_forecast", "stat_forecast", "business_plan"):
            r[k] = round(r[k], 1)

    historical = agg[agg["actuals"] > 0]
    future = agg[agg["actuals"] == 0]

    dp_mape = _mape(historical["actuals"], historical["dp_forecast"])
    stat_mape = _mape(historical["actuals"], historical["stat_forecast"])
    bp_mape = _mape(historical["actuals"], historical["business_plan"])

    return {
        "sku_id": sku_id,
        "sku_name": df[df["sku_id"] == sku_id]["sku_name"].iloc[0],
        "customer_filter": customer or "all",
        "records": records,
        "summary": {
            "total_periods_with_actuals": int((agg["actuals"] > 0).sum()),
            "total_future_periods": int((agg["actuals"] == 0).sum()),
            "actuals_range": [
                round(float(historical["actuals"].min()), 1),
                round(float(historical["actuals"].max()), 1),
            ],
            "dp_vs_actuals_mape_historical": dp_mape,
            "stat_vs_actuals_mape_historical": stat_mape,
            "bp_vs_actuals_mape_historical": bp_mape,
        },
    }


def analyze_period_pattern(
    sku_id: str, period: int, customer: str | None = None
) -> dict:
    """Compare a specific period across all years to detect recurring patterns."""
    df = _require_data()

    sub = df[df["sku_id"] == sku_id]
    if sub.empty:
        return {"error": f"SKU '{sku_id}' not found."}

    if customer:
        sub = sub[sub["customer"] == customer]
        if sub.empty:
            return {"error": f"No data for SKU '{sku_id}' / customer '{customer}'."}

    # Aggregate across customers if no filter
    agg = (
        sub.groupby(["year", "period"], as_index=False)
        .agg(
            actuals=("actuals", "sum"),
            dp_forecast=("dp_forecast", "sum"),
            stat_forecast=("stat_forecast", "sum"),
        )
    )

    target = agg[agg["period"] == period]
    others = agg[(agg["period"] != period) & (agg["actuals"] > 0)]

    baseline = round(float(others["actuals"].mean()), 1) if not others.empty else None

    yearly_actuals: dict[str, float | str] = {}
    yearly_dp: dict[str, float] = {}
    yearly_stat: dict[str, float] = {}
    period_vs_baseline: dict[str, float | str] = {}

    for _, row in target.iterrows():
        yr = str(int(row["year"]))
        act = round(float(row["actuals"]), 1)
        yearly_actuals[yr] = act if act > 0 else 0.0
        yearly_dp[yr] = round(float(row["dp_forecast"]), 1)
        yearly_stat[yr] = round(float(row["stat_forecast"]), 1)

        if act > 0 and baseline:
            period_vs_baseline[yr] = round(act / baseline, 2)
        else:
            period_vs_baseline[yr] = "no actuals yet"

    return {
        "sku_id": sku_id,
        "period": period,
        "customer_filter": customer or "all",
        "yearly_actuals": yearly_actuals,
        "yearly_dp_forecast": yearly_dp,
        "yearly_stat_forecast": yearly_stat,
        "baseline_average_other_periods": baseline,
        "period_vs_baseline_ratio": period_vs_baseline,
        "note": (
            "2025 actuals are 0 for future periods (P7–P13). "
            "Ratios only calculated where actuals > 0."
        ),
    }


def compare_forecasts(
    sku_id: str, year: int, customer: str | None = None
) -> dict:
    """Measure forecast accuracy (MAPE + bias) for one SKU in one year."""
    df = _require_data()

    sub = df[(df["sku_id"] == sku_id) & (df["year"] == year)]
    if sub.empty:
        return {"error": f"No data for SKU '{sku_id}' year {year}."}

    if customer:
        sub = sub[sub["customer"] == customer]
        if sub.empty:
            return {"error": f"No data for SKU '{sku_id}' year {year} customer '{customer}'."}

    agg = (
        sub.groupby("period", as_index=False)
        .agg(
            actuals=("actuals", "sum"),
            dp_forecast=("dp_forecast", "sum"),
            stat_forecast=("stat_forecast", "sum"),
            business_plan=("business_plan", "sum"),
        )
    )

    historical = agg[agg["actuals"] > 0]
    if historical.empty:
        return {
            "sku_id": sku_id,
            "year": year,
            "customer_filter": customer or "all",
            "periods_evaluated": 0,
            "note": "No periods with actuals in this year.",
        }

    dp_mape = _mape(historical["actuals"], historical["dp_forecast"])
    stat_mape = _mape(historical["actuals"], historical["stat_forecast"])
    bp_mape = _mape(historical["actuals"], historical["business_plan"])

    dp_bias, dp_dir = _bias(historical["actuals"], historical["dp_forecast"])
    stat_bias, stat_dir = _bias(historical["actuals"], historical["stat_forecast"])
    bp_bias, bp_dir = _bias(historical["actuals"], historical["business_plan"])

    scores = {"dp_forecast": dp_mape, "stat_forecast": stat_mape, "business_plan": bp_mape}
    best = min(scores, key=lambda k: scores[k] if not math.isnan(scores[k]) else float("inf"))

    # Build interpretation hint
    others = {k: v for k, v in scores.items() if k != best and not math.isnan(v)}
    if others:
        worst_k = max(others, key=lambda k: others[k])
        diff = round(others[worst_k] - scores[best], 1)
        hint = f"{best} outperforms {worst_k} by {diff} MAPE points in {year}."
    else:
        hint = f"{best} has the lowest MAPE in {year}."

    return {
        "sku_id": sku_id,
        "year": year,
        "customer_filter": customer or "all",
        "periods_evaluated": int(len(historical)),
        "dp_forecast": {"mape": dp_mape, "bias": dp_bias, "bias_direction": dp_dir},
        "stat_forecast": {"mape": stat_mape, "bias": stat_bias, "bias_direction": stat_dir},
        "business_plan": {"mape": bp_mape, "bias": bp_bias, "bias_direction": bp_dir},
        "best_forecast_by_mape": best,
        "interpretation_hint": hint,
    }
