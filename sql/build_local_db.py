"""
Build a local DuckDB stand-in for the Bolders Postgres, from Bart's four
final-shape fact tables, then create Lily's views on top and verify them.

Why DuckDB: zero-install (pip only), reads Excel directly, and the views in
lily_views_runnable.sql are written dialect-portable so the SAME file also runs
on the real Postgres later (swap the connection, keep the SQL).

Run:  python sql/build_local_db.py
Output: sql/lily_local.duckdb  (+ a verification report to stdout)

The mapping from SAP source headers -> warehouse column names lives here, in one
place. When canonical names are confirmed against schema-overview.md, only this
RENAMES dict and the view FROM clauses change.
"""
from pathlib import Path
import sys
import duckdb
import pandas as pd

# ---- locate inputs -------------------------------------------------------
DATA_DIR = Path(
    r"C:/Users/Brett/Downloads/Database Data (Shape of the data)"
    r"/Database Data (Shape of the data)/Final Shape Fact tables"
)
SQL_DIR = Path(__file__).resolve().parent
DB_PATH = SQL_DIR / "lily_local.duckdb"
VIEWS_SQL = SQL_DIR / "lily_views_runnable.sql"

# ---- source sheet + header mapping per table -----------------------------
# (source header -> warehouse column). Sales org / triad region kept verbatim
# in name but their MEANING is region-BU / customer (see DATA_MODEL.md).
SOURCES = {
    "fct_forecast": {
        "file": "Forecast.xlsx", "sheet": "Forecast",
        "renames": {
            "Sales Organization": "sales_org", "Triad Region": "triad_region",
            "Material": "material", "Forecast Version": "forecast_version_raw",
            "Fiscal Period": "fiscal_period_raw", "Quantity": "forecast_quantity",
            "Revenue": "forecast_revenue_eur", "COGS": "forecast_cogs_eur",
        },
    },
    "fct_actuals": {
        "file": "Actuals.xlsx", "sheet": "ActualsRaw",
        "renames": {
            "Sales Organization": "sales_org", "Material": "material",
            "Triad Region": "triad_region", "Fiscal Period": "fiscal_period_raw",
            "Plant": "plant", "Quantity": "actual_quantity",
            "Revenue": "actual_revenue_eur",
        },
    },
    "fct_budget": {
        "file": "Budget.xlsx", "sheet": "Data inv sales",
        "renames": {
            "Fiscal Period": "fiscal_period_raw", "Sales Organisation": "sales_org",
            "Material": "material", "Triad Region": "triad_region",
            "Value": "budget_value_eur", "Quantity": "budget_quantity",
        },
    },
    "fct_inventory": {
        "file": "Inventory.xlsx", "sheet": "InventoryRaw",
        "renames": {
            "Sales Organization": "sales_org", "Material": "material",
            "Plant": "plant", "Fiscal Period": "fiscal_period_raw",
            "Unit of Measure": "uom", "Quantity": "stock_quantity",
            "Value": "stock_value_eur",
        },
    },
}


def period_key(raw) -> int | None:
    """'8.2026' (period.year, float) -> 202608 (year*100 + period)."""
    if pd.isna(raw):
        return None
    period, year = str(raw).split(".")
    return int(year) * 100 + int(period)


def version_key(raw) -> int | None:
    """'27.2026' (week.year) -> 2026027 (year*1000 + week)."""
    if pd.isna(raw):
        return None
    week, year = str(raw).split(".")
    return int(year) * 1000 + int(week)


def load_table(con, table, spec):
    path = DATA_DIR / spec["file"]
    df = pd.read_excel(path, sheet_name=spec["sheet"])
    df = df.rename(columns=spec["renames"])[list(spec["renames"].values())]

    # derive the integer keys the views expect
    df["fiscal_period_key"] = df["fiscal_period_raw"].map(period_key)
    df = df.drop(columns=["fiscal_period_raw"])
    if "forecast_version_raw" in df.columns:
        df["forecast_version_key"] = df["forecast_version_raw"].map(version_key)
        df = df.drop(columns=["forecast_version_raw"])

    df["material"] = df["material"].astype(str)  # SKU is a string

    con.execute(f"CREATE OR REPLACE TABLE dw.{table} AS SELECT * FROM df")
    n = con.execute(f"SELECT COUNT(*) FROM dw.{table}").fetchone()[0]
    print(f"  loaded dw.{table:14s} {n:>7,} rows  ({spec['file']})")


def main():
    if not DATA_DIR.exists():
        sys.exit(f"Source folder not found: {DATA_DIR}")
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = duckdb.connect(str(DB_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS dw")

    print("Loading fact tables:")
    for table, spec in SOURCES.items():
        load_table(con, table, spec)

    print("\nCreating views from lily_views_runnable.sql ...")
    con.execute(VIEWS_SQL.read_text())

    print("\nVerification:")
    checks = [
        ("forecast_future rows",       "SELECT COUNT(*) FROM lily.vw_forecast_future"),
        ("top-5 SKU rows (org 2510)",  "SELECT COUNT(*) FROM lily.vw_sku_forecast_ranked WHERE rank_by_qty <= 5"),
        ("inventory_coverage rows",    "SELECT COUNT(*) FROM lily.vw_inventory_coverage"),
        ("  -> STOCKOUT RISK",         "SELECT COUNT(*) FROM lily.vw_inventory_coverage WHERE coverage_flag = 'STOCKOUT RISK'"),
        ("  -> OVERSTOCK",             "SELECT COUNT(*) FROM lily.vw_inventory_coverage WHERE coverage_flag = 'OVERSTOCK'"),
        ("demand_vs_budget rows",      "SELECT COUNT(*) FROM lily.vw_demand_vs_budget"),
        ("budget_vs_last_year rows",   "SELECT COUNT(*) FROM lily.vw_budget_vs_last_year"),
        ("forecast_version_delta rows","SELECT COUNT(*) FROM lily.vw_forecast_version_delta"),
        ("flat_forecast_check rows",   "SELECT COUNT(*) FROM lily.vw_flat_forecast_check"),
    ]
    for label, q in checks:
        print(f"  {label:32s} {con.execute(q).fetchone()[0]:>7,}")

    print("\nSample — inventory coverage (org 2510), most at-risk first:")
    sample = con.execute("""
        SELECT material_id, stock_qty_ea, avg_period_qty, coverage_periods,
               coverage_flag, has_non_ea_stock
        FROM lily.vw_inventory_coverage
        WHERE coverage_periods IS NOT NULL
        ORDER BY coverage_periods ASC
        LIMIT 8
    """).fetchdf()
    print(sample.to_string(index=False))

    con.close()
    print(f"\nDone. Local DB at: {DB_PATH}")


if __name__ == "__main__":
    main()
