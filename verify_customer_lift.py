"""Verify the customer-mirror views against the node-lift views.
Key check: customer views summed across customers should equal the node views.
Beta region = Pokon (3710). Zero Anthropic credit (pure SQL)."""
import subprocess, psycopg2, os, shutil

AZ = os.environ.get("LILY_AZ_CMD",
                     shutil.which("az") or r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd")
token = subprocess.check_output(
    [AZ, "account", "get-access-token", "--resource-type", "oss-rdbms",
     "--query", "accessToken", "-o", "tsv"], text=True).strip()
conn = psycopg2.connect(
    host="billy-ai-postgresql.postgres.database.azure.com",
    dbname="ai-agent-db", user="Ong.KhoiNguyen@evergreengarden.com",
    password=token, sslmode="require")
conn.autocommit = True
cur = conn.cursor()
SO = '3710'

def q(sql, p=()):
    cur.execute(sql, p); return cur.fetchall()

def q1(sql, p=()):
    cur.execute(sql, p); return cur.fetchone()

# pick top-3 L2 nodes by revenue from the trusted rollup
nodes = q("""SELECT node_path, node_name
             FROM lily.vw_hierarchy_rollup
             WHERE sales_org=%s AND level=2
             ORDER BY trailing_revenue_eur DESC NULLS LAST LIMIT 3""", (SO,))

print(f"=== Pokon ({SO}) — customer mirror verification ===")
print(f"=== Checking: customer views summed across customers = node views ===\n")

ok = 0
fail = 0

def check(label, got, expected, tolerance=0.01):
    global ok, fail
    if got is None and expected is None:
        ok += 1; return
    if got is None or expected is None:
        print(f"    FAIL {label}: got={got}  expected={expected}")
        fail += 1; return
    diff = abs(float(got) - float(expected))
    threshold = max(abs(float(expected)) * tolerance, 0.5) if expected != 0 else 0.5
    if diff <= threshold:
        ok += 1
    else:
        print(f"    FAIL {label}: got={got}  expected={expected}  diff={diff}")
        fail += 1

for (path, name) in nodes:
    print(f"NODE: {name}  [{path}]")

    # 1. Forecast: sum customer_forecast across customers vs node_forecast
    cf = q1("""SELECT COALESCE(SUM(demand_qty),0), ROUND(COALESCE(SUM(revenue_eur),0),2),
                      COUNT(DISTINCT fiscal_period_key), COUNT(DISTINCT customer_code)
               FROM lily.vw_customer_forecast
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    nf = q1("""SELECT COALESCE(SUM(demand_qty),0), ROUND(COALESCE(SUM(revenue_eur),0),2),
                      COUNT(DISTINCT fiscal_period_key)
               FROM lily.vw_node_forecast
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    print(f"  forecast: customer_sum demand={cf[0]} rev={cf[1]} periods={cf[2]} customers={cf[3]}")
    print(f"  forecast: node         demand={nf[0]} rev={nf[1]} periods={nf[2]}")
    check("forecast demand_qty", cf[0], nf[0])
    check("forecast revenue_eur", cf[1], nf[1])

    # 2. Economics: sum customer_economics vs node_economics
    ce = q1("""SELECT COALESCE(SUM(total_forecast_qty),0),
                      ROUND(COALESCE(SUM(total_forecast_revenue_eur),0),2),
                      ROUND(COALESCE(SUM(total_forecast_margin_eur),0),2),
                      COUNT(DISTINCT customer_code)
               FROM lily.vw_customer_economics
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    ne = q1("""SELECT total_forecast_qty,
                      total_forecast_revenue_eur,
                      total_forecast_margin_eur
               FROM lily.vw_node_economics
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    print(f"  economics: customer_sum qty={ce[0]} rev={ce[1]} margin={ce[2]} customers={ce[3]}")
    print(f"  economics: node         qty={ne[0]} rev={ne[1]} margin={ne[2]}")
    check("economics qty", ce[0], ne[0])
    check("economics rev", ce[1], ne[1])
    check("economics margin", ce[2], ne[2])

    # 3. Actuals history: sum customer_actuals vs node_actuals
    ca = q1("""SELECT COALESCE(SUM(actual_qty),0),
                      ROUND(COALESCE(SUM(actual_revenue_eur),0),2),
                      COUNT(DISTINCT fiscal_period_key),
                      COUNT(DISTINCT customer_code)
               FROM lily.vw_customer_actuals_history
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    na = q1("""SELECT COALESCE(SUM(actual_qty),0),
                      ROUND(COALESCE(SUM(actual_revenue_eur),0),2),
                      COUNT(DISTINCT fiscal_period_key)
               FROM lily.vw_node_actuals_history
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    print(f"  actuals: customer_sum qty={ca[0]} rev={ca[1]} periods={ca[2]} customers={ca[3]}")
    print(f"  actuals: node         qty={na[0]} rev={na[1]} periods={na[2]}")
    check("actuals qty", ca[0], na[0])
    check("actuals rev", ca[1], na[1])

    # 4. Bias: sum customer_bias F and A, recompute bias vs node_bias
    cb = q1("""SELECT COALESCE(SUM(actual_qty),0), COALESCE(SUM(forecast_qty),0),
                      COUNT(DISTINCT customer_code)
               FROM lily.vw_customer_bias
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    nb = q1("""SELECT COALESCE(SUM(actual_qty),0), COALESCE(SUM(forecast_qty),0)
               FROM lily.vw_node_bias
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    print(f"  bias: customer_sum actual={cb[0]} forecast={cb[1]} customers={cb[2]}")
    print(f"  bias: node         actual={nb[0]} forecast={nb[1]}")
    check("bias actual_qty", cb[0], nb[0])
    check("bias forecast_qty", cb[1], nb[1])

    # 5. Revision: sum customer_revision vs node_revision
    cr = q1("""SELECT COALESCE(SUM(cur_qty),0), COALESCE(SUM(pri_qty),0),
                      COALESCE(SUM(qty_delta),0), COUNT(DISTINCT customer_code)
               FROM lily.vw_customer_forecast_revision
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    nr = q1("""SELECT COALESCE(SUM(cur_qty),0), COALESCE(SUM(pri_qty),0),
                      COALESCE(SUM(qty_delta),0)
               FROM lily.vw_node_forecast_revision
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    print(f"  revision: customer_sum cur={cr[0]} pri={cr[1]} delta={cr[2]} customers={cr[3]}")
    print(f"  revision: node         cur={nr[0]} pri={nr[1]} delta={nr[2]}")
    check("revision cur_qty", cr[0], nr[0])
    check("revision pri_qty", cr[1], nr[1])
    check("revision qty_delta", cr[2], nr[2])

    # 6. Customer scan: check it has rows and names resolve
    cs = q1("""SELECT COUNT(*), COUNT(DISTINCT customer_code),
                      COUNT(*) FILTER (WHERE customer_name IS NOT NULL)
               FROM lily.vw_customer_scan
               WHERE sales_org=%s AND node_path=%s""", (SO, path))
    print(f"  customer_scan: rows={cs[0]} distinct_customers={cs[1]} with_name={cs[2]}")
    if cs[0] == 0:
        print(f"    FAIL customer_scan is EMPTY")
        fail += 1
    else:
        ok += 1
    print()

print(f"=== RESULT: {ok} passed, {fail} failed ===")
conn.close()
