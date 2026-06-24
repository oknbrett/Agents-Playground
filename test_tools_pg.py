"""Call every Lily tool function directly against the live Postgres warehouse.
No LLM involved -> zero Anthropic credit. Validates the connection swap + views."""
import os, json
os.environ["LILY_USE_ENTRA"] = "1"   # force the Entra-token Postgres path

from agents.lily import tools as t

def show(label, obj, keys=None):
    print(f"\n=== {label} ===")
    if isinstance(obj, dict):
        if "error" in obj or "note" in obj and not obj.get("records"):
            print("  ", {k: obj.get(k) for k in ("error", "note")})
        rec = obj.get("records") or obj.get("scorecard")
        if keys:
            print("  ", {k: obj.get(k) for k in keys})
        if isinstance(rec, list):
            print(f"   records: {len(rec)}; first: {rec[0] if rec else '—'}")
        elif rec:
            print("   ", rec)

ov = t.get_overview()
print("=== get_overview ===")
print("   sales_orgs:", ov["sales_orgs"])
print("   material_count:", ov["material_count"], "| version:", ov["forecast_version_key"])
print("   latest_closed:", ov["latest_closed_actuals_period"])
print("   streams:", ov["streams_available"])

# pick a real, material SKU from the divergence scan to exercise per-SKU tools
scan = t.divergence_scan(order_by="revenue", n=3)
print("\n=== divergence_scan(top 3 by revenue) ===")
for r in scan["records"]:
    print("   ", r)
sku = scan["records"][0]["material_id"]
org = None  # let tools aggregate across orgs; or derive
print(f"\n--- exercising per-SKU tools on material_id={sku} ---")

show("get_forecast", t.get_forecast(sku))
show("demand_vs_budget", t.demand_vs_budget(sku))
show("product_economics", t.product_economics(sku))
show("inventory_coverage", t.inventory_coverage(sku))
show("actuals_history", t.actuals_history(sku))
show("latest_actuals", t.latest_actuals(sku))
show("forecast_performance (lag-2)", t.forecast_performance(sku))

print("\n=== family_scan(top 3) ===")
for r in t.family_scan()["records"][:3]:
    print("   ", r)

print("\n=== top_skus(FY2026 P9) ===")
ts = t.top_skus(2026, 9, n=3)
for r in ts["records"][:3]:
    print("   ", r)

print("\n=== sku_performance_scan(top 3 by revenue) ===")
sp = t.sku_performance_scan(order_by="revenue", n=3)
for r in sp["records"]:
    print("   ", r)

# confirm the dropped tool is gone
print("\n=== dropped tool check ===")
print("   demand_vs_statistical present on module:", hasattr(t, "demand_vs_statistical"))

print("\nALL TOOLS RAN.")
