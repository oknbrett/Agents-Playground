"""Synthetic demand planning dataset generator.

Produces demand_data.csv and demand_data.xlsx in this directory.
Run once: python data/generate_dataset.py

Eight SKUs, four customers, 13 periods, 3 years = 1,248 rows.
Each SKU has a hidden pattern baked in (no label columns).
Seeded with 42 — always produces the same output.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

# ── Constants ─────────────────────────────────────────────────────────────────

SKUS: list[tuple[str, str]] = [
    ("SKU001", "Premium Olive Oil 500ml"),
    ("SKU002", "Greek Yoghurt 1kg"),
    ("SKU003", "Sparkling Water 6-pack"),
    ("SKU004", "Organic Granola 400g"),
    ("SKU005", "Protein Bar Box (12)"),
    ("SKU006", "Cold Brew Coffee 250ml"),
    ("SKU007", "Almond Milk 1L"),
    ("SKU008", "Mixed Nuts 200g"),
]

CUSTOMERS: list[str] = ["Carrefour", "Lidl", "Tesco", "Albert Heijn"]

CUSTOMER_REGION: dict[str, str] = {
    "Carrefour": "FR",
    "Lidl": "DE",
    "Tesco": "NL",
    "Albert Heijn": "NL",
}

YEARS: list[int] = [2023, 2024, 2025]
PERIODS: list[int] = list(range(1, 14))  # P1–P13

# Base volume per (sku_id, customer) — drawn from realistic FMCG ranges
BASE_VOLUMES: dict[tuple[str, str], float] = {
    ("SKU001", "Carrefour"): 1800, ("SKU001", "Lidl"): 1400,
    ("SKU001", "Tesco"): 1100, ("SKU001", "Albert Heijn"): 900,

    ("SKU002", "Carrefour"): 2100, ("SKU002", "Lidl"): 1700,
    ("SKU002", "Tesco"): 1300, ("SKU002", "Albert Heijn"): 1100,

    ("SKU003", "Carrefour"): 1600, ("SKU003", "Lidl"): 1300,
    ("SKU003", "Tesco"): 1000, ("SKU003", "Albert Heijn"): 850,

    ("SKU004", "Carrefour"): 950,  ("SKU004", "Lidl"): 800,
    ("SKU004", "Tesco"): 650,  ("SKU004", "Albert Heijn"): 550,

    ("SKU005", "Carrefour"): 1200, ("SKU005", "Lidl"): 1000,
    ("SKU005", "Tesco"): 800,  ("SKU005", "Albert Heijn"): 700,

    ("SKU006", "Carrefour"): 750,  ("SKU006", "Lidl"): 600,
    ("SKU006", "Tesco"): 480,  ("SKU006", "Albert Heijn"): 420,

    ("SKU007", "Carrefour"): 2200, ("SKU007", "Lidl"): 1800,
    ("SKU007", "Tesco"): 1400, ("SKU007", "Albert Heijn"): 1200,

    ("SKU008", "Carrefour"): 1050, ("SKU008", "Lidl"): 880,
    ("SKU008", "Tesco"): 720,  ("SKU008", "Albert Heijn"): 610,
}


# ── Pattern logic ─────────────────────────────────────────────────────────────

def apply_sku_pattern(
    sku_id: str,
    year: int,
    period: int,
    customer: str,
    base: float,
    rng: np.random.Generator,
) -> tuple[float, float, float, float]:
    """Return (actuals, dp_forecast, stat_forecast, business_plan) for one row.

    Patterns are embedded via multipliers with no label columns.
    Future periods (2025 P7–P13) get actuals = 0.
    """
    is_future = year == 2025 and period >= 7

    if sku_id == "SKU001":
        return _sku001(year, period, base, rng, is_future)
    elif sku_id == "SKU002":
        return _sku002(year, period, base, rng, is_future)
    elif sku_id == "SKU003":
        return _sku003(year, period, base, rng, is_future)
    elif sku_id == "SKU004":
        return _sku004(year, period, base, rng, is_future)
    elif sku_id == "SKU005":
        return _sku005(year, period, base, rng, is_future)
    elif sku_id == "SKU006":
        return _sku006(year, period, customer, base, rng, is_future)
    elif sku_id == "SKU007":
        return _sku007(year, period, base, rng, is_future)
    else:  # SKU008
        return _sku008(year, period, base, rng, is_future)


def _round(v: float) -> float:
    return round(v, 1)


def _sku001(year, period, base, rng, is_future):
    """Recurring P5 peak every year (×1.75). Stat misses it (×1.10). DP under-adjusts (×1.15 future)."""
    peak = period == 5
    noise = 1 + rng.uniform(-0.08, 0.08)

    actuals_mult = 1.75 if peak else 1.0
    actuals = _round(base * actuals_mult * noise) if not is_future else 0.0

    stat_mult = 1.10 if peak else 1.0
    stat = _round(base * stat_mult * (1 + rng.uniform(-0.05, 0.05)))

    if is_future:
        dp_mult = 1.15 if peak else 1.0
        dp = _round(base * dp_mult * (1 + rng.uniform(-0.03, 0.03)))
    else:
        # Past DP: follows stat with small human tweak
        dp = _round(stat * (1 + rng.uniform(-0.06, 0.08)))

    bp = _round(base * 1.20)  # modest annual plan

    return actuals, dp, stat, bp


def _sku002(year, period, base, rng, is_future):
    """One-time P8 spike in 2023 only (×2.40). Stat has a small 2025 P8 bleed (×1.15)."""
    noise = 1 + rng.uniform(-0.08, 0.08)

    if year == 2023 and period == 8:
        actuals = _round(base * 2.40 * noise)
    else:
        actuals = _round(base * noise) if not is_future else 0.0

    if year == 2025 and period == 8:
        stat = _round(base * 1.15 * (1 + rng.uniform(-0.04, 0.04)))
    else:
        stat = _round(base * (1 + rng.uniform(-0.06, 0.06)))

    if is_future:
        dp = _round(stat * (1 + rng.uniform(-0.05, 0.05)))
    else:
        dp = _round(stat * (1 + rng.uniform(-0.07, 0.09)))

    bp = _round(base * 1.15)

    return actuals, dp, stat, bp


def _sku003(year, period, base, rng, is_future):
    """Clear upward YoY trend. Stat lags. DP follows stat."""
    yoy = {2023: 1.00, 2024: 1.18, 2025: 1.38}
    stat_yoy = {2023: 1.00, 2024: 1.08, 2025: 1.24}
    noise = 1 + rng.uniform(-0.07, 0.07)

    actuals = _round(base * yoy[year] * noise) if not is_future else 0.0
    stat = _round(base * stat_yoy[year] * (1 + rng.uniform(-0.05, 0.05)))
    dp = _round(stat * (1 + rng.uniform(-0.04, 0.06))) if not is_future else _round(stat * (1 + rng.uniform(-0.02, 0.03)))
    bp = _round(base * {2023: 1.25, 2024: 1.30, 2025: 1.45}[year])

    return actuals, dp, stat, bp


def _sku004(year, period, base, rng, is_future):
    """BP consistently 24–28% over actuals. Stat is accurate. Future DP anchors to BP."""
    noise = 1 + rng.uniform(-0.07, 0.07)
    bp_mult = {2023: 1.28, 2024: 1.24, 2025: 1.26}[year]

    actuals = _round(base * noise) if not is_future else 0.0
    stat = _round(base * 1.02 * (1 + rng.uniform(-0.04, 0.04)))
    bp = _round(base * bp_mult)

    if is_future:
        dp = _round(base * 1.12 * (1 + rng.uniform(-0.03, 0.03)))
    else:
        dp = _round(stat * (1 + rng.uniform(-0.05, 0.06)))

    return actuals, dp, stat, bp


def _sku005(year, period, base, rng, is_future):
    """Stat very accurate (±3%). Past DP noisy (±15–18%). Future DP elevated ×1.18 with no basis."""
    noise = 1 + rng.uniform(-0.08, 0.08)

    actuals = _round(base * noise) if not is_future else 0.0
    stat = _round(base * (1 + rng.uniform(-0.03, 0.03)))

    if is_future:
        dp = _round(stat * 1.18 * (1 + rng.uniform(-0.02, 0.02)))
    else:
        dp_adjustments = [0.82, 0.84, 0.86, 0.88, 1.12, 1.14, 1.16, 1.18, 1.15, 1.13, 0.85, 0.83, 0.87]
        # pick deterministically by period index
        adj = dp_adjustments[(period - 1) % len(dp_adjustments)]
        dp = _round(stat * adj)

    bp = _round(base * 1.10)

    return actuals, dp, stat, bp


def _sku006(year, period, customer, base, rng, is_future):
    """Carrefour-only P11 peak (×2.10). Other customers flat at P11. DP 2025 P11 Carrefour at ×1.30."""
    carrefour_peak = customer == "Carrefour" and period == 11
    noise = 1 + rng.uniform(-0.08, 0.08)

    actuals_mult = 2.10 if carrefour_peak else 1.0
    actuals = _round(base * actuals_mult * noise) if not is_future else 0.0

    stat_mult = 2.10 if carrefour_peak else 1.0  # stat tracks actuals here
    stat = _round(base * stat_mult * (1 + rng.uniform(-0.06, 0.06)))

    if is_future:
        dp_mult = 1.30 if carrefour_peak else 1.0
        dp = _round(base * dp_mult * (1 + rng.uniform(-0.03, 0.03)))
    else:
        dp = _round(stat * (1 + rng.uniform(-0.07, 0.07)))

    bp = _round(base * 1.15)

    return actuals, dp, stat, bp


def _sku007(year, period, base, rng, is_future):
    """Declining YoY. Stat lags behind (overshoots). BP flat/growing — denial."""
    yoy = {2023: 1.00, 2024: 0.83, 2025: 0.68}
    stat_yoy = {2023: 1.00, 2024: 0.90, 2025: 0.80}
    noise = 1 + rng.uniform(-0.07, 0.07)

    actuals = _round(base * yoy[year] * noise) if not is_future else 0.0
    stat = _round(base * stat_yoy[year] * (1 + rng.uniform(-0.05, 0.05)))
    bp = _round(base * {2023: 1.00, 2024: 1.03, 2025: 1.05}[year])

    if is_future:
        dp = _round(stat * (1 + rng.uniform(-0.04, 0.04)))
    else:
        dp = _round(stat * (1 + rng.uniform(-0.06, 0.07)))

    return actuals, dp, stat, bp


def _sku008(year, period, base, rng, is_future):
    """Highly volatile, no pattern. Wide ±25% noise per row."""
    actuals = _round(base * rng.uniform(0.75, 1.25)) if not is_future else 0.0
    stat = _round(base * rng.uniform(0.90, 1.10))
    dp = _round(stat * rng.uniform(0.92, 1.08))
    bp = _round(base * 1.10)

    return actuals, dp, stat, bp


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    rng = np.random.default_rng(seed=42)
    rows: list[dict] = []

    for sku_id, sku_name in SKUS:
        for customer in CUSTOMERS:
            base = BASE_VOLUMES[(sku_id, customer)]
            region = CUSTOMER_REGION[customer]
            for year in YEARS:
                for period in PERIODS:
                    actuals, dp, stat, bp = apply_sku_pattern(
                        sku_id, year, period, customer, base, rng
                    )
                    rows.append({
                        "period": period,
                        "year": year,
                        "sku_id": sku_id,
                        "sku_name": sku_name,
                        "customer": customer,
                        "region": region,
                        "actuals": actuals,
                        "dp_forecast": dp,
                        "stat_forecast": stat,
                        "business_plan": bp,
                    })

    df = pd.DataFrame(rows)

    out_dir = Path(__file__).parent
    csv_path = out_dir / "demand_data.csv"
    xlsx_path = out_dir / "demand_data.xlsx"

    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False)

    print(f"Generated {len(df)} rows.")
    print(f"  CSV:  {csv_path}")
    print(f"  XLSX: {xlsx_path}")

    # Quick sanity check — SKU001 P5 should be ~1.75× the non-peak average
    sku1 = df[(df["sku_id"] == "SKU001") & (df["actuals"] > 0)]
    p5_avg = sku1[sku1["period"] == 5]["actuals"].mean()
    other_avg = sku1[sku1["period"] != 5]["actuals"].mean()
    print(f"\nSanity check SKU001: P5 avg={p5_avg:.0f}, other avg={other_avg:.0f}, ratio={p5_avg/other_avg:.2f}x (expect ~1.75)")

    # SKU007 decline check
    sku7 = df[(df["sku_id"] == "SKU007") & (df["actuals"] > 0)]
    for yr in [2023, 2024, 2025]:
        avg = sku7[sku7["year"] == yr]["actuals"].mean()
        print(f"  SKU007 {yr} avg actuals: {avg:.0f}")


if __name__ == "__main__":
    main()
