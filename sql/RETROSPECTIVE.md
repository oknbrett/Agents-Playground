# Lily Views — Retrospective

A record of how this round went: what was asked, what we built, where Bart pushed back, what we learned, and where it landed. Written so the reasoning isn't lost.

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

## Deliverables in this folder

- `lily_views_runnable.sql` — views that execute on the data Bart provided (the demo-ready set).
- `lily_view_catalog.md` — the full 13-comparison design with business use cases and data-readiness.
- `PLAN.md`, `lily_br_views.sql`, `README.md` — earlier four-stream design work (superseded on the version-key wiring and materialization, kept for history).

## What to take to Bart

A runnable file for what the data allows, plus one line: *"the rest is designed and ready — switch it on when I get (1) how statistical/budget are stored + that data, (2) actuals history, (3) a second forecast version."* That moves the blockers back to where they actually are: the data, not the design.
