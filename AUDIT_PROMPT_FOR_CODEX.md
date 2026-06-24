# Codex task — data-integrity audit of Lily's serving layer

Hey Codex. I need a **thorough, take-as-long-as-you-need audit** of this project's
SQL serving views and the tool layer that reads them, hunting for one dangerous
class of bug (and its relatives): **aggregations that fold in rows/periods where the
underlying data doesn't actually exist, producing numbers that look authoritative
but are wrong.**

Do not rush this. Read the code, reason about the data shape, and **verify every
suspicion against the live database** before reporting it. I'd rather you find ten
real problems slowly than guess.

---

## Why this matters — the bug we already found (your template)

Lily is an LLM demand-planning analyst. She never writes SQL — she reads
"decision-ready" JSON from a set of `lily.*` views over a real Azure Postgres
warehouse. If a view hands her a wrong number, she reasons confidently on top of it
and produces a wrong, high-confidence recommendation. The model cannot smell a bad
input; **the views must be correct.**

Concrete example we already fixed (use it as the pattern to generalize from):

- `warehouse.fact_forecast` loads **revenue for only the ~7 near-term periods** of a
  24-period horizon. Every out-year period has **quantity and COGS but `revenue = 0`**
  (pricing/contracts not loaded that far out). Some far-future rows have quantity but
  **both revenue AND cogs = 0**.
- `lily.vw_product_economics` computed `avg_price = SUM(revenue)/SUM(quantity)` and
  `margin = SUM(revenue) − SUM(cogs)` **across the whole horizon** — dividing real
  revenue by full-horizon quantity, and subtracting COGS that mostly sits on
  revenue-less periods.
- Result: SKU `107899` showed **−12.2% margin / "selling at a loss"**. The truth, on
  the periods that actually carry pricing, is **+46.1% margin (€5.96 price vs €3.21
  COGS)**. A profitable SKU was reported as a structural loss-maker.
- Fix: compute price/COGS/margin **only over priced periods** and expose
  `priced_periods` / `total_periods` so the consumer knows pricing is partial. (See
  the current `vw_product_economics` in `sql/lily_views_pg.sql` for the corrected
  shape — that one's already done; don't re-fix it, learn from it.)

**The general failure:** a SUM / AVG / ratio / per-unit / cross-stream comparison
whose population silently includes rows where the measure is `NULL`, `0`, or simply
not loaded — so the denominator, the numerator, or one side of a difference is
computed over a different (or emptier) set than the other.

---

## What I want you to scan for

Go view-by-view through `sql/lily_views_pg.sql` and tool-by-tool through
`agents/lily/tools.py`. For **each** view/column and tool, ask:

1. **Sparse-measure contamination** — does any `SUM`/`AVG`/ratio include periods or
   rows where the measure is absent (revenue=0, cogs=0, qty=0, NULL)? Per-unit
   prices, margins, coverage ratios, and "% of" metrics are prime suspects.
2. **Mismatched populations in a single expression** — is one side of a subtraction
   or ratio summed over a different set of periods/rows than the other? (Revenue over
   7 periods minus COGS over 24 is the bug above. Look for more.)
3. **Partial-period comparisons** — YoY / growth metrics that compare a **complete**
   period against an **incomplete** one. (Known instance: actuals cover FY2025 in
   full but FY2026 only through P8 — so `yoy_growth_pct` and the "−31.5% YoY" figure
   compare 12 months against 8. Confirm and flag every place this leaks in:
   `vw_sku_divergence`, `vw_family_divergence`, `actuals_history`'s per-year totals.)
4. **Average-of-ratios skew** — `AVG(some_pct)` where individual rows have tiny or
   zero denominators (new SKUs, near-zero prior-year volume) producing absurd values
   that dominate an average. (Suspect: `avg_yoy_growth_pct`, `avg_demand_vs_budget_pct`
   in `vw_family_divergence`.)
5. **Silent row loss / fan-out through sparse joins** — `dim_material_sales_organization`
   covers only ~6,904 of ~108k possible material×org combos (>90% absent). Any view
   that reaches `material_group` or joins through it may silently drop or mis-count
   rows. Check every join: is it `LEFT` where it must be, and does a missing match
   distort a SUM/COUNT?
6. **Text-key ordering** — `fiscal_period_key` is **text** (`008.2026`), not
   chronologically sortable (`'012.2025' > '001.2026'`). Any `MIN`/`MAX`/`ORDER BY`/
   `LAG`/window over the raw key string is wrong. Confirm every period ordering goes
   through `fiscal_year, fiscal_period_number` (or `period_idx`), not the key.
7. **Lag / vintage correctness** — forecast accuracy/bias is rebuilt from weekly
   forecast vintages (`forecast_version_key` → `dim_fiscal_week` → cut period; lag =
   target − cut). Sanity-check that the lag-2 join in `vw_forecast_actual_matched`
   isn't double-counting, mismatching customer grain, or scoring periods that aren't
   truly closed.
8. **Inventory coverage** — `vw_inventory_coverage` divides EA stock by *average*
   forward demand. Does "average" include the zero/no-demand periods or the unpriced
   tail in a way that distorts coverage? Is the EA-only guard actually holding?

Also flag anything **adjacent** you notice that's just wrong, even if it's not in the
list above.

---

## Data-shape facts you can rely on (don't re-derive these)

- Warehouse schema dump: **`sql/SCHEMA_DUMP.md`** (all 13 `warehouse.*` tables:
  columns, types, row counts, PK/FK, samples).
- 8 sales orgs; `2510`=Benelux, `3710`=Pokon. "Now" = latest closed actuals = **P8
  FY2026** (`008.2026`). FY starts in **October** (P1=Oct … P12=Sep).
- Forecast = **11 weekly vintages**; latest = `35.2026`. Revenue is loaded only for
  near periods; quantity + cogs project the full ~24-period horizon (the bug above).
- COGS is stored **negative** in `fact_forecast.cogs`; views use `ABS(cogs)`.
- `fiscal_period_key` is text; order via `dim_fiscal_period`.
- Families come from `dim_product_hierarchy` (via `dim_material`), NOT the sparse
  `dim_material_sales_organization` helper.
- There is **no statistical-baseline stream** (a `demand_vs_statistical` tool was
  removed for this reason — don't resurrect it).

## How to verify against the live database

The connection works from this machine via an Entra ID token — see
**`test_postgres.py`** for the exact pattern (it shells out to `az` for a token and
connects with `psycopg2`, `sslmode=require`). Reuse that to run your own diagnostic
queries against `warehouse.*` (raw facts) and `lily.*` (the views). **For every bug
you suspect, write a query that proves it** — e.g. show the per-period rows where the
measure is missing, then show the honest figure computed over only the valid rows,
the way `probe_economics.py`-style checks did for the margin bug.

Helper scripts already here: `explore_schema.py` (regenerates the schema dump),
`apply_views.py` (re-applies `sql/lily_views_pg.sql` to the live DB),
`test_tools_pg.py` (smoke-tests every tool against Postgres). **Read-only is the
default — do not modify warehouse data.** Views live in an isolated `lily` schema and
are safe to `CREATE OR REPLACE` if you implement a fix.

## Deliverable

1. A written report — **one entry per problem found**, each with: the view/column or
   tool, the exact failure (which rows/periods get wrongly included), a **query that
   demonstrates it** with before/after numbers, severity (does it change a
   RAISE/LOWER/KEEP call?), and a proposed fix.
2. Fix the high-severity ones in `sql/lily_views_pg.sql` (and the corresponding tool
   in `agents/lily/tools.py` if it needs new context columns, mirroring how
   `product_economics` now surfaces `priced_periods`/`total_periods`). Re-apply with
   `apply_views.py` and re-verify.
3. A short "all clear" list of views you checked and believe are correct, so I know
   the coverage was complete.

Take as long as you need. Thoroughness over speed.

## Files to start with
- `sql/lily_views_pg.sql` — the 25 `lily.*` views (the prime target)
- `agents/lily/tools.py` — the 14 tools that read them (note `_round` coerces Decimal→float)
- `sql/SCHEMA_DUMP.md` — the real warehouse schema
- `HANDOFF.md` — current project state and the realities of the data
- `test_postgres.py` — the live-DB connection pattern
