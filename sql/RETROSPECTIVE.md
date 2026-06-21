# Lily Views — Retrospective

**Last updated: 2026-06-17.** A record of how this round went: what was asked, what we built, where Bart pushed back, what we learned, and where it landed. Written so the reasoning isn't lost.

> **Note for anyone (or any Claude) reading this later:** check the dates below before trusting any file. There are two distinct waves of work — an earlier solo attempt on **2026-05-29**, and the current design round on **2026-06-15/16**. Don't treat the older files as current.

## Timeline (so nothing gets confused)

| When | What | Where it lives |
|---|---|---|
| **2026-05-29** | Brett's earlier solo attempt — a working 10-view `lily_views.sql` built directly on Bart's sample data | `C:/Users/Brett/OneDrive - HAN/Desktop/Lily/` (NOT in this repo) |
| **2026-06-15** | Four-stream OBT design round: `PLAN.md`, `lily_br_views.sql`, `README.md` | `archive/sql/` — **superseded** on version-key wiring + materialization |
| **2026-06-16** | Corrected, runnable deliverables after reading Bart's two SAP samples: `lily_views_runnable.sql`, `lily_view_catalog.md` | this folder — superseded by 06-17 |
| **2026-06-17** | Bart delivered the **four final-shape fact tables**. Read all four; wrote `DATA_MODEL.md`; corrected + extended `lily_views_runnable.sql` (budget + inventory streams, 3 new views) | this folder — **current** |

The May 29 file and today's `lily_views_runnable.sql` overlap a lot (top SKUs, customer split, margin, flat-forecast, version delta) — today's is the cleaned, business-scoped version of that earlier work, aligned to the catalog.

## The task as given

"Create the PostgreSQL views for Lily." No spec, no sample of the final data, little guidance. The brief was effectively: figure out what data, at what grain, in what shape, Lily needs to answer demand-planning questions — and produce SQL views.

## What we designed

A serving layer following the **One Big Table (OBT)** pattern — the 2026 best practice for feeding an AI agent: pre-join, pre-aggregate, pre-calculate everything so Lily reads finished numbers and never does SQL, joins, or math herself. Specifically:

- **Four data streams** per period: actuals, statistical forecast, demand forecast, budget. Comparing these is the core of demand planning.
- **Base views at three grains** (SKU / customer / SKU-in-customer) so customer-level detail isn't lost.
- **Pre-computed comparison columns** (e.g. "demand +22% vs last year") baked in, so Lily reads the answer.
- **Wide views, Lily filters the window** — no per-horizon (3m/6m/12m) duplicates.
- Initially proposed **materialized views** for speed.

## What we prepared for Bart

A first SQL draft (`lily_br_views.sql`) with the four-stream design and placeholder version keys, plus a README explaining the pattern and run order.

## Where Bart pushed back

1. **Materialized views** — "out of scope if we index the fact/dimension tables; our data loads on-demand (Power Automate / SharePoint), not nightly. Justify the need." **He was right.** Lily queries one SKU at a time — a narrow, indexed lookup that's milliseconds even on millions of rows, and dwarfed by LLM latency anyway. Materialization buys nothing here and adds a refresh headache against on-demand loads. → **Conceded: regular views + indexes.**
2. **"load_id as a proxy"** — he didn't understand the question. Correctly so: the question only made sense if you didn't know what `forecast_version_key` was. We didn't yet.
3. **Version keys** — pointed us to his Word doc instead of answering.

## What reading Bart's real files changed

The Word doc + the two SAP Excel samples corrected several assumptions:

- **`forecast_version_key` is the *week the forecast was made*** (e.g. 2026027 = FY2026 wk27), **not** a statistical/demand/budget identifier. Our four-stream wiring (splitting streams by version key) was wrong — streams need a *different* separator we don't yet know.
- The current forecast feed is **demand only** (one quantity), **one version loaded** (week 27).
- Actuals = **latest closed period only** (P07 FY2026). No history. Loads lag — a period must close before it loads.
- **No inventory data** in scope.
- COGS exists on the forecast side (margin computable); not on actuals.
- Forecast is org 2510 only / no plant; actuals span 8 orgs / have plant — so forecast↔actuals only join cleanly for 2510, across plant.

## Where it landed

- The **four-stream + history design is still correct** — Bart himself said to design for the expected shape. The current data is just a thin subset of it.
- **Regular views + indexes**, not materialized (conceded to Bart).
- **One genuine unknown remains:** how the statistical and budget streams will be stored (separate tables vs a `forecast_type` column vs extra version keys). That's the only thing not derivable from what we were given; it blocks 5 of the 13 comparison views.
- Of the 13 designed comparisons, **4 run on today's data** (top SKUs, top customers, product economics, flat-forecast), the **version views run but stay empty** until a 2nd week loads, and the rest wait on the statistical/budget feed or actuals history.

## 2026-06-17 — Bart delivered the four fact tables

The full final-shape fact tables landed: `Forecast / Actuals / Budget / Inventory.xlsx`. Reading them changed and confirmed several things:

- **Budget and inventory are their own fact tables** (`fct_budget`, `fct_inventory`) — the old "how are the streams stored" unknown is **answered**. Budget is *not* a forecast version key.
- **`Triad Region` is the customer**, not geography (Brett's domain call — beats the SAP label). **`sales_org` is the region / business unit** (`2510` ≈ Netherlands / Evergreen Pokon; will later be names). So the **customer grain is real** — the earlier worry that customer detail was lost is reversed.
- The earlier `lily_views_runnable.sql` was built on **invented forecast columns** (`plant_id`, `customer_attribute_4`) that don't exist — forecast has neither. Corrected to the real shape.
- The four files are **single-org shape samples** (fc 2510 / ac 1010 / bg 3710 / inv 8 orgs) with disjoint materials — so demand-vs-budget and budget-vs-last-year return **0 rows on the sample** but are correct against the real multi-org DB. **Inventory ∩ forecast overlap on org 2510 (245 materials)** — inventory coverage genuinely populates.
- **Statistical forecast: still not delivered** — confirmed (one quantity column = demand only). Stays parked.
- **Inventory has mixed UoM** (EA dominant + KG/M3/L/…). Coverage math is UoM-guarded to EA and flags partial-coverage materials.

**Built this round (all in `lily_views_runnable.sql`):** `vw_budget`, `vw_inventory_latest` (foundation), plus the three the user asked for — `vw_demand_vs_budget` (#5), `vw_budget_vs_last_year` (#2), `vw_inventory_coverage` (BR-06). Full column-level data model written to `DATA_MODEL.md`.

**Still blocked on data, not design:** statistical stream (rows 3/4/6), actuals history (rows 1/2 + full YoY), 2nd weekly version (rows 7–9), and confirming canonical column names against `schema-overview.md` (the repo was 404 to our token — a find-and-replace in the `FROM` clauses when reachable).

## Deliverables in this folder

**Current (2026-06-17) — use these:**
- `DATA_MODEL.md` — column-by-column data model of the four real fact tables + the semantics (sales_org = region/BU, Triad Region = customer). Read this first.
- `lily_views_runnable.sql` — corrected + extended views (now incl. budget, inventory, and the 3 new comparisons).
- `lily_view_catalog.md` — the full comparison design with business use cases and updated data-readiness.

**Earlier (2026-06-15) — superseded, moved to `archive/sql/` to keep it out of future sessions' context:**
- `archive/sql/PLAN.md`, `archive/sql/lily_br_views.sql`, `archive/sql/README.md` — four-stream design work. Superseded on the version-key wiring (it assumed streams live in `forecast_version_key`, which is actually the forecast *week*) and on materialization (dropped per Bart). The four-stream *concept* still stands; the wiring there does not.

**Not in this repo (2026-05-29):**
- `lily_views.sql` on `Desktop/Lily/` — Brett's earlier solo attempt; today's runnable file is its cleaned successor.

## What to take to Bart

A runnable file for what the data allows, plus one line: *"the rest is designed and ready — switch it on when I get (1) how statistical/budget are stored + that data, (2) actuals history, (3) a second forecast version."* That moves the blockers back to where they actually are: the data, not the design.
