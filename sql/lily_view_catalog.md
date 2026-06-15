# Lily View Catalog

The full set of views Lily needs, expressed as business use cases. This is the design target; what's runnable on today's data is in `lily_views_runnable.sql`.

**Lily is forward-only.** She holds future forecast + (at most) the latest closed actuals period as a reference. She has no past forecast performance — forecast accuracy / bias is Billy's job, not Lily's.

## One view per comparison — not per horizon

Each comparison is **one view covering the full horizon**. Lily filters the window (1, 3, 6, 12 months) at query time. We do **not** build separate 3-month / 6-month / 12-month views.

Each comparison exists at three grains: **by product · by customer · by product-in-customer** — always within the planner's own region.

## Data-readiness legend

🟢 runs on current data · 🔵 needs statistical/budget stream · 🟣 needs actuals history · 🟠 needs stock feed · ⚪ needs a 2nd weekly forecast load

## The comparisons

| # | What vs what (+ time) | Business use case | Columns / variables | Ready |
|---|---|---|---|---|
| 1 | Demand vs last-year actuals — future month vs same month 1yr earlier | Sanity-check the plan against real past demand | material, customer_group, year+period, demand_qty, last_year_actual_qty, delta, delta_% | 🟣 |
| 2 | Budget vs last-year actuals — same | Is the sales target realistic vs what sold last year | budget_qty, last_year_actual_qty, delta, delta_% | 🔵🟣 |
| 3 | Statistical vs last-year actuals — same | Is the algorithm baseline grounded in history | statistical_qty, last_year_actual_qty, delta, delta_% | 🔵🟣 |
| 4 | Demand vs statistical — same future month | How much the planner overrides the model, which way | demand_qty, statistical_qty, delta, delta_% | 🔵 |
| 5 | Demand vs budget — same future month | Where my plan and sales disagree, flag inconsistencies | demand_qty, budget_qty, delta, delta_% | 🔵 |
| 6 | Statistical vs budget — same future month | Nice-to-have: is the target model-backed | statistical_qty, budget_qty, delta, delta_% | 🔵 |
| 7 | Demand vs its own earlier version — same target month, two cycles | Did I already revise this SKU? How has it moved cycle to cycle? | material, customer_group, period, current_version, prior_version, current_qty, prior_qty, delta, delta_% | ⚪ |
| 8 | Biggest movers — gap between two cycles, ranked by % | Which SKUs/customers shifted most since last cycle | material/customer, period, qty_delta_%, rank | ⚪ |
| 9 | Persistent drift — same direction every cycle | SKU I keep nudging the same way — maybe under-correcting | material/customer, period, per-cycle direction, consecutive-same-direction count | ⚪ |
| 10 | Top-N SKUs for a period | "Top 5 SKUs by units expected in P05 next year" | material, period, total_qty/revenue, rank | 🟢 |
| 11 | Top-N customers for a period | "Top 5 customers by forecast revenue" | customer_group, period, total_revenue, rank | 🟢 |
| 12 | Margin / COGS / selling price per product | "COGS & price of this SKU?" + "if we sell 20k units, what's revenue?" | material, qty, revenue, cogs, unit_price, unit_cogs, margin, margin_% | 🟢 |
| 13 | Flat-forecast check — every month identical | Spot copy-paste / placeholder forecasts | material/customer, distinct monthly values, min, max, flat flag | 🟢 |

## Dropped from Lily

- **Gap / mismatch checks** (forecast-but-no-sales, sales-but-no-forecast, new, discontinued, silent customer) — these are **Billy / rear-view**, not Lily.
- **Concentration views** — no clear planner use case.
- **Forecast vs actual, same period** — impossible: the future hasn't happened. Only forecast-vs-actual is future vs the same period last year (#1–3).

## The one genuine unknown

Rows 2–6 need the **statistical** and **budget** streams. We have no such data, and we don't know how they'll be stored — separate tables (`fct_statistical`, `fct_budget`), a `forecast_type` column inside `fct_forecast`, or extra version keys. The SQL differs completely by choice. This is the single thing that can't be derived from what Bart provided. Everything else is either runnable now or runnable once data volume catches up.
