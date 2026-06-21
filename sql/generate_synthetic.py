"""
Generate a themed synthetic demand-planning dataset (Evergreen / Pokon flavour)
in the real warehouse shape, load it into sql/lily_local.duckdb, apply Lily's
views, and verify. ~500k rows so Lily has something real to reason over.

Run:  python sql/generate_synthetic.py     (overwrites lily_local.duckdb)
       LILY_DB_PATH still points the tools at this same file — no other change.

Shape: 1 region (2510), 25 customers, 200 SKUs with a 4-level product hierarchy,
3 years of actuals (FY2024-2026), 24 months of demand forecast (FY2027-2028, two
cut versions), past lagged forecasts of closed periods (lags 1/2/3 -> forecast
accuracy & bias), a top-down annual budget, and a current inventory snapshot.
FISCAL YEAR STARTS IN NOVEMBER (P1=Nov, P4=Feb, P7=May, P12=Oct).

The numbers are random but themed: seasonal profiles per product family, SKU
lifecycles (growing / stable / declining / new), a top-down budget that diverges
from the bottom-up forecast, lifecycle-driven forecast bias (so accuracy/bias are
real signals), and deliberate traps (flat placeholder forecasts, negative margins,
over/under-stock) for Lily to catch.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb

SEED = 42
SALES_ORG = 2510
SQL_DIR = Path(__file__).resolve().parent
DB_PATH = SQL_DIR / "lily_local.duckdb"
VIEWS_SQL = SQL_DIR / "lily_views_runnable.sql"

ACTUAL_YEARS = [2024, 2025, 2026]          # 3 years of history
FORECAST_YEARS = [2027, 2028]              # 24 months forward
VERSIONS = [2026045, 2026050]              # two forward forecast cuts (week 45, week 50 of 2026)
INV_PERIOD = 202612                        # snapshot = latest closed actuals period
PERIODS = list(range(1, 13))               # SAP fiscal periods 1..12
LAGS = [1, 2, 3]                           # historical forecast lags; lag-2 = Evergreen's operational basis
PRIMARY_LAG = 2

# 25 customers, codes FA..FY (first letter tracks org 2510 per DATA_MODEL.md),
# each with a size weight so the customer mix isn't uniform.
CUSTOMERS = [f"F{c}" for c in "ABCDEFGHIJKLMNOPQRSTUVWXY"]

# ── Product hierarchy: (L1, L2, L3, L4, season_profile, margin_band) ──────────
# Some branches go deep; some collapse (L3==L4) where there's one product line.
HIERARCHY = [
    ("Garden & Outdoor", "Plant Nutrition",  "Liquid Feed",     "Rose & Flower Liquid",  "garden_spring", "mid"),
    ("Garden & Outdoor", "Plant Nutrition",  "Liquid Feed",     "Tomato & Veg Liquid",   "garden_spring", "mid"),
    ("Garden & Outdoor", "Plant Nutrition",  "Granular Feed",   "Universal Granular",    "garden_spring", "mid"),
    ("Garden & Outdoor", "Plant Nutrition",  "Slow Release",    "Slow Release Sticks",   "garden_spring", "high"),
    ("Garden & Outdoor", "Growing Media",    "Potting Soil",    "Universal Potting Mix", "garden_spring", "low"),
    ("Garden & Outdoor", "Growing Media",    "Bark & Mulch",    "Decorative Bark",       "garden_spring", "low"),
    ("Garden & Outdoor", "Pest & Disease",   "Organic Pest",    "Bug Spray Organic",     "pest",          "high"),
    ("Garden & Outdoor", "Pest & Disease",   "Chemical Pest",   "Bug Concentrate",       "pest",          "high"),
    ("Garden & Outdoor", "Seeds & Bulbs",    "Flower Seeds",    "Wildflower Mix",        "seeds",         "mid"),
    ("Garden & Outdoor", "Seeds & Bulbs",    "Veg Seeds",       "Tomato Seeds",          "seeds",         "mid"),
    ("Indoor & Houseplant", "Houseplant Feed", "Drops & Sticks", "Orchid Drops",         "indoor_flat",   "high"),
    ("Indoor & Houseplant", "Houseplant Feed", "Drops & Sticks", "Green Plant Drops",    "indoor_flat",   "high"),
    ("Indoor & Houseplant", "Houseplant Soil", "Specialty Mix",  "Cactus & Succulent Mix","indoor_flat",  "mid"),
    ("Indoor & Houseplant", "Houseplant Soil", "Specialty Mix",  "Orchid Bark Mix",      "indoor_flat",   "mid"),
    ("Indoor & Houseplant", "Houseplant Care", "Care",           "Houseplant Care",      "indoor_flat",   "high"),  # collapsed L3=L4
    ("Lawn & Turf",  "Lawn Feed",     "Granular Lawn",  "Spring Lawn Feed",  "lawn", "mid"),
    ("Lawn & Turf",  "Lawn Feed",     "Granular Lawn",  "Autumn Lawn Feed",  "lawn", "mid"),
    ("Lawn & Turf",  "Weed Control",  "Weed & Feed",    "Lawn Weed & Feed",  "lawn", "mid"),
    ("Lawn & Turf",  "Grass Seed",    "Grass Seed",     "Grass Seed",        "lawn", "low"),   # collapsed
    ("Professional", "Professional Nutrition", "Pro Liquid", "Pro Liquid",   "pro_steady", "low"),  # collapsed L3=L4
    ("Professional", "Professional Media",     "Pro Media",  "Pro Media",    "pro_steady", "low"),  # collapsed
]

# Seasonality. FISCAL YEAR STARTS IN NOVEMBER (P1=Nov, P4=Feb, P7=May, P12=Oct).
# Defined by calendar MONTH (Northern-hemisphere garden calendar), then mapped into
# fiscal-period order so the peaks land on the right periods.
_FISCAL_MONTH_ORDER = [10, 11, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]   # P1..P12 -> month idx (Nov..Oct)
_SEASON_BY_MONTH = {   # Jan..Dec multipliers (mean ~1)
    "garden_spring": [0.4, 0.6, 1.0, 1.6, 1.9, 1.7, 1.2, 1.0, 0.8, 0.6, 0.5, 0.5],  # peak Apr-Jun
    "lawn":          [0.4, 0.5, 1.0, 1.5, 1.7, 1.5, 1.4, 1.3, 1.2, 0.9, 0.5, 0.4],  # Mar-Sep
    "pest":          [0.4, 0.4, 0.6, 1.0, 1.5, 1.9, 1.9, 1.6, 1.0, 0.6, 0.4, 0.4],  # May-Aug
    "seeds":         [0.6, 1.2, 1.8, 1.6, 1.0, 0.6, 0.5, 0.6, 1.0, 1.4, 1.1, 0.7],  # spring sow + autumn bulbs
    "indoor_flat":   [1.0, 1.0, 1.0, 1.0, 0.95, 0.9, 0.9, 0.9, 0.95, 1.0, 1.15, 1.25],  # slight Nov-Dec gifting
    "pro_steady":    [1.0, 1.0, 1.05, 1.1, 1.1, 1.05, 1.0, 1.0, 1.0, 0.95, 0.95, 0.95],
}
SEASON = {k: np.array([v[m] for m in _FISCAL_MONTH_ORDER]) for k, v in _SEASON_BY_MONTH.items()}
MARGIN_BAND = {"low": (0.10, 0.22), "mid": (0.25, 0.40), "high": (0.45, 0.62)}
LIFECYCLES = ["growing", "stable", "declining", "new"]
PLANTS = ["A400", "A500", "A501"]

rng = np.random.default_rng(SEED)


def make_products() -> pd.DataFrame:
    """200 SKUs spread across the hierarchy, each with its own economics + behaviour."""
    rows = []
    for i in range(200):
        l1, l2, l3, l4, season, band = HIERARCHY[i % len(HIERARCHY)]
        lo, hi = MARGIN_BAND[band]
        margin = rng.uniform(lo, hi)
        # a few deliberate loss-makers (cost > price) for Lily to flag
        if rng.random() < 0.04:
            margin = -rng.uniform(0.05, 0.20)
        rows.append({
            "material": f"{10000 + i*7}{'N' if i % 9 == 0 else ''}",   # string SKU, some letter suffix
            "l1_division": l1, "l2_category": l2, "l3_subcategory": l3, "l4_product_line": l4,
            "season_profile": season,
            "lifecycle": LIFECYCLES[i % len(LIFECYCLES)],
            "unit_price_eur": round(rng.uniform(3, 45), 2),
            "margin": margin,
            "base_monthly_qty": float(rng.integers(20, 800)),
            # bulk media sold in KG/M3 as well as EA; everything else EA only
            "bulk_uom": "KG" if l2 == "Growing Media" and rng.random() < 0.5 else None,
            "flat_forecast": rng.random() < 0.10,   # placeholder-forecast trap
        })
    return pd.DataFrame(rows)


def _trend(lifecycle: str, year_idx: int) -> float:
    """Year-over-year multiplier. year_idx 0 = earliest year."""
    return {
        "growing":   1.0 + 0.18 * year_idx,
        "declining": 1.0 - 0.15 * year_idx,
        "stable":    1.0 + rng.uniform(-0.03, 0.03),
        "new":       0.0 if year_idx == 0 else 0.5 + 0.4 * year_idx,   # launches in year 2
    }[lifecycle]


def _cust_weights() -> dict[str, float]:
    w = rng.uniform(0.3, 2.5, len(CUSTOMERS))
    return dict(zip(CUSTOMERS, w / w.mean()))


CUST_W = _cust_weights()


def _series(p: pd.Series, years: list[int], year0: int) -> pd.DataFrame:
    """Build a (customer x year x period) quantity grid for one product, themed."""
    season = SEASON[p.season_profile]
    recs = []
    for cust, cw in CUST_W.items():
        for y in years:
            yfac = _trend(p.lifecycle, y - year0)
            if yfac <= 0:
                continue                                   # not launched yet
            base = p.base_monthly_qty * cw * yfac
            qty = base * season * rng.uniform(0.8, 1.2, 12)   # seasonal + noise
            recs.append(pd.DataFrame({
                "triad_region": cust, "material": p.material,
                "fiscal_period_key": [y * 100 + m for m in PERIODS],
                "qty": np.round(qty).astype(int),
            }))
    df = pd.concat(recs, ignore_index=True)
    return df[df.qty > 0]


def build_actuals(prods: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, p in prods.iterrows():
        s = _series(p, ACTUAL_YEARS, ACTUAL_YEARS[0])
        s["actual_quantity"] = s.qty
        s["actual_revenue_eur"] = (s.qty * p.unit_price_eur).round(2)
        s["sales_org"] = SALES_ORG
        s["plant"] = rng.choice(PLANTS, len(s))
        parts.append(s.drop(columns="qty"))
    df = pd.concat(parts, ignore_index=True)
    # realism: ~0.5% returns (negative qty), a couple of nulls
    neg = rng.random(len(df)) < 0.005
    df.loc[neg, ["actual_quantity", "actual_revenue_eur"]] *= -1
    df.loc[rng.random(len(df)) < 0.0005, "actual_quantity"] = np.nan
    return df


def build_forecast(prods: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    """Bottom-up forecast off the latest actual year's run-rate, per version."""
    last_year = max(ACTUAL_YEARS)
    parts = []
    for _, p in prods.iterrows():
        s = _series(p, FORECAST_YEARS, ACTUAL_YEARS[0])         # continue the trend unbroken from history origin
        if p.flat_forecast:                                     # placeholder trap: flat across periods, per customer
            s["qty"] = s.groupby("triad_region").qty.transform("mean").round().astype(int)
        for v in VERSIONS:
            vq = np.round(s.qty * (1.0 if v == VERSIONS[-1] else rng.uniform(0.9, 1.1, len(s)))).astype(int)
            f = s.copy()
            f["forecast_quantity"] = vq
            f["forecast_version_key"] = v
            f["forecast_revenue_eur"] = (vq * p.unit_price_eur).round(2)
            f["forecast_cogs_eur"] = -(vq * p.unit_price_eur * (1 - p.margin)).round(2)  # stored NEGATIVE
            f["sales_org"] = SALES_ORG
            parts.append(f.drop(columns="qty"))
    return pd.concat(parts, ignore_index=True)


def build_forecast_history(prods: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    """Past forecasts of now-CLOSED periods, at lags 1/2/3 (the Billy data).

    For each closed period we generate the forecast that was made `lag` periods
    earlier, derived from the actual that landed: F = A * (1 + bias + lag_noise).
    Bias is lifecycle-driven so accuracy/bias come out meaningful, not random:
    growing SKUs are under-forecast (planner lags the growth), declining are
    over-forecast (slow to cut), flat-forecast SKUs drift. Noise widens with lag.
    cut_period_key records when the forecast was made, so lag = target - cut."""
    a = actuals.dropna(subset=["actual_quantity"]).copy()
    a = a[a.actual_quantity > 0]                                      # a forecast doesn't target a return
    a = a.groupby(["triad_region", "material", "fiscal_period_key"], as_index=False)["actual_quantity"].sum()
    attr = prods.set_index("material")[["unit_price_eur", "lifecycle", "flat_forecast"]]
    a = a.join(attr, on="material")
    bias_map = {"growing": -0.10, "declining": 0.12, "stable": 0.0, "new": 0.05}
    a["bias"] = a.lifecycle.map(bias_map) + np.where(a.flat_forecast, 0.08, 0.0)

    k = a.fiscal_period_key.to_numpy()
    target_ord = (k // 100) * 12 + (k % 100 - 1)                      # period ordinal (continuous across years)
    noise_std = {1: 0.05, 2: 0.12, 3: 0.20}
    parts = []
    for lag in LAGS:
        f = a.copy()
        fq = a.actual_quantity * (1 + a.bias + rng.normal(0, noise_std[lag], len(a)))
        f["forecast_quantity"] = np.clip(np.round(fq), 0, None).astype(int)
        f["forecast_revenue_eur"] = (f.forecast_quantity * a.unit_price_eur).round(2)
        cut_ord = target_ord - lag
        f["cut_period_key"] = (cut_ord // 12) * 100 + (cut_ord % 12 + 1)
        f["lag"] = lag
        f["sales_org"] = SALES_ORG
        parts.append(f[["sales_org", "triad_region", "material", "fiscal_period_key",
                        "cut_period_key", "lag", "forecast_quantity", "forecast_revenue_eur"]])
    return pd.concat(parts, ignore_index=True)


def build_statistical(prods: pd.DataFrame) -> pd.DataFrame:
    """Naive statistical baseline (the 'dumb model'): carry the last actual-year
    level forward with learned seasonality, flat across years, NO lifecycle trend
    and NO planner override. The gap demand - statistical IS the planner's manual
    adjustment — the sharpest signal of where human judgment was applied."""
    level_idx = len(ACTUAL_YEARS) - 1            # the level the model last 'saw' (FY2026)
    parts = []
    for _, p in prods.iterrows():
        season = SEASON[p.season_profile]
        level = _trend(p.lifecycle, level_idx)
        if level <= 0:
            continue
        for cust, cw in CUST_W.items():
            base = p.base_monthly_qty * cw * level
            for y in FORECAST_YEARS:             # model projects same level each year
                q = np.round(base * season * rng.uniform(0.95, 1.05, 12)).astype(int)  # tight noise: models are smooth
                parts.append(pd.DataFrame({
                    "sales_org": SALES_ORG, "triad_region": cust, "material": p.material,
                    "fiscal_period_key": [y * 100 + m for m in PERIODS],
                    "statistical_quantity": q,
                }))
    df = pd.concat(parts, ignore_index=True)
    return df[df.statistical_quantity > 0]


def build_budget(prods: pd.DataFrame, forecast: pd.DataFrame) -> pd.DataFrame:
    """Top-down annual target: a stretch on run-rate, spread across the year.
    Set independently of the bottom-up forecast, so the two diverge — half the
    SKUs get a flat 1/12 spread (finance default), half a rough seasonal spread."""
    latest = forecast[forecast.forecast_version_key == VERSIONS[-1]]
    parts = []
    for _, p in prods.iterrows():
        season = SEASON[p.season_profile]
        for y in FORECAST_YEARS:
            for cust, cw in CUST_W.items():
                annual = p.base_monthly_qty * 12 * cw * _trend(p.lifecycle, y - ACTUAL_YEARS[0])
                annual *= rng.uniform(1.0, 1.25)                      # finance stretch
                if annual <= 0:
                    continue
                spread = np.ones(12) / 12 if rng.random() < 0.5 else season / season.sum()
                bq = np.round(annual * spread).astype(int)
                parts.append(pd.DataFrame({
                    "sales_org": SALES_ORG, "triad_region": cust, "material": p.material,
                    "fiscal_period_key": [y * 100 + m for m in PERIODS],
                    "budget_quantity": bq,
                    "budget_value_eur": (bq * p.unit_price_eur).round(2),
                }))
    return pd.concat(parts, ignore_index=True)


def build_inventory(prods: pd.DataFrame, forecast: pd.DataFrame) -> pd.DataFrame:
    """Snapshot at INV_PERIOD. Stock = coverage_months × avg forward demand, with
    coverage drawn to spread across stockout / ok / overstock."""
    latest = forecast[forecast.forecast_version_key == VERSIONS[-1]]
    avg = (latest.groupby("material").forecast_quantity.sum() / latest.fiscal_period_key.nunique())
    parts = []
    for _, p in prods.iterrows():
        a = float(avg.get(p.material, 0))
        if a <= 0:
            continue
        cov = rng.choice([0.5, 3, 6, 9, 18], p=[0.15, 0.3, 0.3, 0.15, 0.1])  # months of cover
        ea_qty = int(a * cov)
        parts.append({
            "sales_org": SALES_ORG, "material": p.material, "plant": rng.choice(PLANTS),
            "fiscal_period_key": INV_PERIOD, "uom": "EA",
            "stock_quantity": ea_qty, "stock_value_eur": round(ea_qty * p.unit_price_eur * (1 - p.margin), 2),
        })
        if isinstance(p.bulk_uom, str):                  # mixed-UoM material (NaN-safe: None becomes NaN in pandas)
            kg = int(a * cov * rng.uniform(50, 200))
            parts.append({
                "sales_org": SALES_ORG, "material": p.material, "plant": rng.choice(PLANTS),
                "fiscal_period_key": INV_PERIOD, "uom": p.bulk_uom,
                "stock_quantity": kg, "stock_value_eur": round(kg * 0.5, 2),
            })
    return pd.DataFrame(parts)


def main() -> None:
    prods = make_products()
    actuals = build_actuals(prods)
    forecast = build_forecast(prods, actuals)
    forecast_history = build_forecast_history(prods, actuals)
    statistical = build_statistical(prods)
    budget = build_budget(prods, forecast)
    inventory = build_inventory(prods, forecast)

    dim_product = prods.drop(columns=["season_profile", "base_monthly_qty",
                                      "margin", "bulk_uom", "flat_forecast"])

    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS dw")
    for name, df in {"fct_actuals": actuals, "fct_forecast": forecast,
                     "fct_forecast_history": forecast_history,
                     "fct_statistical": statistical, "fct_budget": budget,
                     "fct_inventory": inventory, "dim_product": dim_product}.items():
        con.register("df", df)
        con.execute(f"CREATE TABLE dw.{name} AS SELECT * FROM df")
        con.unregister("df")
        print(f"  dw.{name:20s} {len(df):>8,} rows")
    total = (len(actuals) + len(forecast) + len(forecast_history) + len(statistical)
             + len(budget) + len(inventory))
    print(f"  {'TOTAL facts':15s} {total:>8,} rows")

    con.execute(VIEWS_SQL.read_text())

    # ── verify: the views must populate (this is the runnable check) ──────────
    print("\nView row counts:")
    for v in ["vw_forecast_latest", "vw_sku_forecast_ranked", "vw_statistical",
              "vw_demand_vs_statistical", "vw_demand_vs_budget",
              "vw_budget_vs_last_year", "vw_inventory_coverage",
              "vw_forecast_version_delta", "vw_flat_forecast_check",
              "vw_actuals_history", "vw_forecast_actual_matched",
              "vw_forecast_accuracy", "vw_forecast_bias", "vw_sku_performance",
              "vw_sku_divergence", "vw_family_divergence"]:
        n = con.execute(f"SELECT COUNT(*) FROM lily.{v}").fetchone()[0]
        print(f"  lily.{v:30s} {n:>8,}")
        assert n > 0, f"{v} is empty — generator/view mismatch"

    print("\nCoverage flag spread:")
    print(con.execute("SELECT coverage_flag, COUNT(*) FROM lily.vw_inventory_coverage "
                      "GROUP BY 1 ORDER BY 2 DESC").fetchdf().to_string(index=False))
    print("\nPlanner override spread (demand vs statistical):")
    print(con.execute("SELECT override_flag, COUNT(*) FROM lily.vw_demand_vs_statistical "
                      "GROUP BY 1 ORDER BY 2 DESC").fetchdf().to_string(index=False))
    print(f"\nForecast accuracy/bias by lifecycle (lag-{PRIMARY_LAG}, should track: "
          "growing under-forecast, declining over-forecast):")
    print(con.execute(f"""
        SELECT p.lifecycle,
               ROUND(AVG(a.wmape_pct), 1)      AS avg_wmape_pct,
               ROUND(AVG(a.bias_pct), 1)       AS avg_bias_pct
        FROM lily.vw_forecast_accuracy a
        JOIN dw.dim_product p ON a.material_id = p.material
        GROUP BY 1 ORDER BY 2 DESC""").fetchdf().to_string(index=False))
    con.close()
    print(f"\nDone -> {DB_PATH}")


if __name__ == "__main__":
    main()
