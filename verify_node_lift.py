"""Verify the option-A node-lift views against the trusted vw_hierarchy_rollup.
Beta region = Pokon (3710). Zero Anthropic credit (pure SQL)."""
import subprocess, psycopg2

AZ = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd"
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

# pick the top 3 L2 nodes by revenue in Pokon from the trusted rollup
nodes = q("""SELECT node_path, node_name, n_skus, demand_qty, trailing_revenue_eur,
                    demand_vs_budget_pct, yoy_growth_pct, wmape_pct, bias_pct, accuracy_pct,
                    stockout_skus
             FROM lily.vw_hierarchy_rollup
             WHERE sales_org=%s AND level=2
             ORDER BY trailing_revenue_eur DESC NULLS LAST LIMIT 3""", (SO,))

print(f"=== Pokon ({SO}) — top-3 L2 nodes; rollup (trusted) vs node-lift views ===\n")
for (path, name, n_skus, demand, rev, dvb, yoy, wmape, bias, acc, stk) in nodes:
    print(f"NODE {name}  [{path}]")
    print(f"  rollup:        n_skus={n_skus}  demand_qty={demand}  trail_rev={rev}  "
          f"dvb%={dvb}  yoy%={yoy}  wmape%={wmape}  bias%={bias}  acc%={acc}  stockout={stk}")

    # membership + forward demand
    sc = q("""SELECT COUNT(DISTINCT material_id) FROM lily.vw_node_sku_scan
              WHERE sales_org=%s AND node_path=%s""", (SO, path))[0][0]
    nf = q("""SELECT COALESCE(SUM(demand_qty),0), MAX(n_skus),
                     COUNT(DISTINCT fiscal_period_key)
              FROM lily.vw_node_forecast WHERE sales_org=%s AND node_path=%s""", (SO, path))[0]
    print(f"  node_forecast: demand_qty={nf[0]}  max n_skus/period={nf[1]}  periods={nf[2]}   "
          f"|  sku_scan distinct materials={sc}")

    # economics: node_economics row vs product_economics summed over member SKUs
    ne = q("""SELECT total_forecast_qty, total_forecast_revenue_eur, total_forecast_margin_eur,
                     margin_pct, priced_periods, total_periods, n_skus
              FROM lily.vw_node_economics WHERE sales_org=%s AND node_path=%s""", (SO, path))
    pe = q("""SELECT ROUND(SUM(pe.total_forecast_qty),0),
                     ROUND(SUM(pe.total_forecast_revenue_eur),2),
                     ROUND(SUM(pe.total_forecast_margin_eur),2)
              FROM lily.vw_product_economics pe
              JOIN lily.vw_material_node n ON n.material_id=pe.material_id
              WHERE pe.sales_org=%s AND n.node_path=%s""", (SO, path))[0]
    if ne:
        ne = ne[0]
        print(f"  node_economics: qty={ne[0]}  rev={ne[1]}  margin={ne[2]}  margin%={ne[3]}  "
              f"priced={ne[4]}/{ne[5]}  n_skus={ne[6]}")
        print(f"  product_econ sum: qty={pe[0]}  rev={pe[1]}  margin={pe[2]}   "
              f"(should equal node_economics qty/rev/margin)")

    # actuals: node last-12-closed revenue vs rollup trailing_revenue_eur
    na = q("""WITH closed AS (
                SELECT fiscal_period_key, RANK() OVER (ORDER BY period_idx DESC) recency
                FROM (SELECT DISTINCT a.fiscal_period_key, c.period_idx
                      FROM warehouse.fact_actuals a
                      JOIN lily.vw_calendar c USING (fiscal_period_key)) x)
              SELECT ROUND(SUM(h.actual_revenue_eur),2)
              FROM lily.vw_node_actuals_history h
              JOIN closed c USING (fiscal_period_key)
              WHERE h.sales_org=%s AND h.node_path=%s AND c.recency<=12""", (SO, path))[0][0]
    print(f"  node_actuals trailing-12 rev={na}   (rollup trail_rev={rev})")

    # bias: node weighted bias over all scored lag-2 periods vs rollup bias%
    nb = q("""SELECT ROUND(SUM(forecast_qty-actual_qty)/NULLIF(SUM(actual_qty),0)*100,1),
                     ROUND(SUM(ABS(forecast_qty-actual_qty))/NULLIF(SUM(actual_qty),0)*100,1)
              FROM lily.vw_node_bias WHERE sales_org=%s AND node_path=%s""", (SO, path))[0]
    print(f"  node_bias weighted: bias%={nb[0]}  wmape%(period-abs)={nb[1]}   "
          f"(rollup bias%={bias})")

    # revision presence
    nr = q("""SELECT COUNT(*), COALESCE(SUM(qty_delta),0)
              FROM lily.vw_node_forecast_revision WHERE sales_org=%s AND node_path=%s""", (SO, path))[0]
    ni = q("""SELECT stock_qty_ea, coverage_periods, stockout_skus, overstock_skus, n_skus
              FROM lily.vw_node_inventory WHERE sales_org=%s AND node_path=%s""", (SO, path))
    print(f"  node_revision: rows={nr[0]}  sumqty_delta={nr[1]}   |  node_inventory: "
          f"{ni[0] if ni else 'NO INVENTORY ROW'}")
    print()

conn.close()
