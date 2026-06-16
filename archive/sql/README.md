# Lily Serving-Layer Views — README for Bart

This folder builds the data layer that **Lily** (the demand-planning agent) reads from.

- [`lily_br_views.sql`](lily_br_views.sql) — the views to run
- [`PLAN.md`](PLAN.md) — the full design reasoning (read if you want the "why" in depth)
- This README — what to run, in what order, and the one thing we need from you

---

## The core idea (why it's built this way)

Lily is an LLM agent. Her job is **analysis**, not data plumbing. We do **not** want her writing SQL, joining tables, aggregating, or computing percentages at question time — that's slow, error-prone, and not what she's good at.

So we do all the heavy lifting **once, in advance**, and hand Lily finished numbers. When a planner asks "how does SKU001's plan compare to last year?", Lily does a single keyed lookup and reads a column that already says `+22%`. She never calculates it.

This is the **One Big Table (OBT) serving-layer** pattern — the current (2026) best practice for feeding data to AI agents: wide, pre-joined, pre-aggregated tables; the agent does straightforward reads with no joins.

### Why MATERIALIZED views

A normal view re-runs its whole query every time it's read. A **materialized view** runs once and stores the result as a physical table on disk — reads are then instant. The trade-off is that the stored result must be **refreshed** when new data lands (see Refresh below).

- The base views and BR-06 are **materialized** — they do heavy aggregation + window math, so we pay that cost once per night, not on every question.
- The BR-08 views are **regular views** — their queries are already narrow and cheap.

### Why three "base" views instead of one giant table

A single universal mega-table is a known anti-pattern (it merges grains and causes misreads). Instead we have three base views, one per **grain** (the level of detail):

| View | Grain | Answers questions like |
|---|---|---|
| `v_planning_sku` | Sales Org × SKU × Period | "How is SKU001 tracking in NL?" |
| `v_planning_customer` | Sales Org × Customer × Period | "How is Albert Heijn tracking?" |
| `v_planning_sku_customer` | Sales Org × SKU × Customer × Period | "How is SKU001 at Albert Heijn?" |

A SKU-level view has already summed across customers, so you can't recover customer detail from it — hence a separate view per grain. The planner always works within their own sales org, so that's always a filter.

---

## ⚠️ The one thing we need from you before this runs

The three forecast streams (statistical, demand, budget) all live in `dw.fct_forecast`, separated by `forecast_version_key`. We don't know the actual key values. Please run:

```sql
SELECT DISTINCT forecast_version_key, COUNT(*) AS rows
FROM dw.fct_forecast
GROUP BY forecast_version_key
ORDER BY rows DESC;
```

Then **find-and-replace these three placeholder tokens** throughout `lily_br_views.sql`:

| Token | Replace with the version key for… |
|---|---|
| `<<STAT_VERSION_KEY>>` | the statistical / algorithm forecast |
| `<<DEMAND_VERSION_KEY>>` | the demand-planner consensus forecast |
| `<<BUDGET_VERSION_KEY>>` | the sales / budget version |

Two more things we'd love confirmed (don't block the run, but affect quality):

1. **Does `forecast_version_key` change per planning cycle** (one key per monthly submission)? BR-08 currently orders versions by `load_id` as a proxy. If the key itself is cycle-stamped, we'll switch to it for cleaner labels.
2. **When does the nightly ETL load finish?** We want to schedule the view refresh right after it (see below).

---

## Run order

The file is already ordered correctly — just run it top to bottom **after** swapping the three tokens. For reference:

1. **Helper views** — `v_period_order`, `v_current_period`
   (give every view a shared sense of period order and "what is "now"")
2. **Base materialized views** — `v_planning_sku`, `v_planning_customer`, `v_planning_sku_customer` (+ their unique indexes)
3. **BR-06 materialized view** — `v_br06_inventory_coverage` (+ unique index)
4. **BR-08 regular views** — `v_br08_forecast_versions_{sku,customer,sku_customer}`

The unique indexes are required so we can refresh `CONCURRENTLY` (refresh without locking reads).

---

## After the first build — sanity checks

The bottom of `lily_br_views.sql` has ready queries. The most important one confirms the version keys resolved — if any column comes back all-NULL, that token is wrong:

```sql
SELECT COUNT(*) FILTER (WHERE statistical_forecast_qty IS NOT NULL) AS stat_rows,
       COUNT(*) FILTER (WHERE demand_forecast_qty      IS NOT NULL) AS demand_rows,
       COUNT(*) FILTER (WHERE budget_qty               IS NOT NULL) AS budget_rows
FROM dw.v_planning_sku;
```

All three counts should be > 0. If `budget_rows = 0`, the budget key is wrong (or budget isn't stored in `fct_forecast` — tell us and we'll adjust).

---

## Refresh (keeping the data current)

The materialized views store a snapshot. Re-run these **once nightly, right after the ETL load**:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_planning_sku;
REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_planning_customer;
REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_planning_sku_customer;
REFRESH MATERIALIZED VIEW CONCURRENTLY dw.v_br06_inventory_coverage;
```

The BR-08 views need no refresh (they're regular views). Tell us your ETL finish time and we'll wire these into the schedule.

---

## Assumptions baked in (flag if any are wrong)

- **"Current period" = the latest period that has actuals.** No calendar-date column exists in the schema, so we infer "now" from the newest actuals. If actuals lag a period, "now" shifts back one. If that's a problem, we can switch to a date-based definition.
- **`dim_material_group` is 1:1 per (material, sales_org).** If a material can map to multiple group rows in one org, the SKU base view could duplicate rows — let us know and we'll pick a single group level.
- **`weeks_cover` is intentionally NOT in BR-06.** That came from the old BR-05. BR-06 here is purely the month-coverage cutoff the business described. Easy to add back if planners want it.

---

## Scope note

These views serve **BR-06, BR-08, BR-09, BR-11** (Lily's forward-looking rules).
- BR-06 and BR-08 have dedicated views.
- **BR-09 and BR-11 have no own view** — Lily reads `v_planning_sku` / `v_planning_customer` directly; every comparison they need is already a pre-computed column there.
- BR-01–05 belong to Billy; BR-07, BR-10, BR-12 are out of scope.
