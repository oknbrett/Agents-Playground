# Lily — Source Data Model (what the real fact tables actually look like)

> **Heads-up (2026-06-21):** this documents the **real SAP sample** tables only.
> Lily currently runs on a **synthetic superset** built by `sql/generate_synthetic.py`
> (200 SKUs, 3yr history, statistical stream, lagged-forecast accuracy/bias, product
> hierarchy; **fiscal year starts November**). The synthetic data follows the same
> column shape described here but adds streams the real sample lacks. See `CLAUDE.md`
> → "The data" for the two-dataset picture. Everything below remains accurate for the
> real tables.

**Written 2026-06-17**, from reading Bart's delivered files:
`Downloads/Database Data (Shape of the data)/.../Final Shape Fact tables/`
→ `Forecast.xlsx`, `Actuals.xlsx`, `Budget.xlsx`, `Inventory.xlsx`.

These are **single-org shape samples** — each file was exported from one sales org
to show the *columns and grain*, not a joinable dataset. The canonical Postgres
schema (Bolders `postgres-db/docs/schema-overview.md`) is the source of truth for
exact table/column **names**; it was not reachable at write time (private repo,
404 to our token). So column *names* below are the source-file headers + the
snake_case convention used in the SQL; the *meaning and grain* are confirmed.

---

## Two semantics that override the literal column labels

These came from Brett's domain knowledge and beat the raw SAP labels:

| Source column | Literal label | **What it actually is** |
|---|---|---|
| `Sales Organization` | "sales org" (e.g. `2510`) | **A region / business unit.** `2510` ≈ Netherlands / Evergreen Pokon. Will later surface as names, not 4-digit codes. |
| `Triad Region` | "region" (e.g. `FA`, `JZ`) | **The customer.** *Not* geography. A real customer dimension after all — so customer-level views are back in scope. |

Identity note: in the samples the customer code's **first letter tracks the org**
(F→2510, A→1010, J→3710). Until a `dim_customer` confirms the code is globally
unique, treat the customer key as the **full `(sales_org, triad_region)` pair**
for cross-stream joins.

---

## Shared encodings

| Field | Sample value | Means | Storage note |
|---|---|---|---|
| Fiscal Period | `8.2026` (was `008.2026`) | Period **8** of FY **2026** (SAP periods 1–12) | Excel made it a float. Assume warehouse key = `year*100 + period` → `202608`. |
| Forecast Version | `27.2026` | Forecast cut in **week 27 of FY2026** (the *when*, not a stream type) | Assume key = `year*1000 + week` → `2026027`. |
| Material | `10491`, `10504N`, `1010007GR` | The SKU | **String, not integer** — some carry letter suffixes. |
| Sales Organization | `2510` | Region / business unit (see above) | 4-digit integer code today. |
| Triad Region | `FA` | Customer (see above) | 2-char code. |

---

## The four fact tables

### fct_forecast — the *demand* forecast (org 2510 sample, 8,633 rows)
| Column | Values | Meaning |
|---|---|---|
| sales_org | 2510 only | region / BU |
| triad_region (customer) | FA…FK (9) | customer |
| material | 266 SKUs | SKU |
| forecast_version | `27.2026` only | week the forecast was cut |
| fiscal_period | 7.2026 → 2028 (21 periods) | **future** target period |
| quantity | 0–28,860, mean 264, 82 zeros, no neg/null | forecast demand units — **the only forecast stream (no statistical)** |
| revenue | 0–156,690 EUR | forecast revenue |
| cogs | **−65,984 → 0, stored NEGATIVE** | cost. **margin = revenue − ABS(cogs)** |

Only table with COGS → margin / unit price computable here only.

### fct_actuals — latest closed sales (org 1010 sample, 93 rows)
| Column | Values | Meaning |
|---|---|---|
| sales_org | 1010 only | region / BU |
| material | 37 SKUs | SKU |
| triad_region (customer) | A1…AY (15) | customer |
| fiscal_period | **7.2026 only** | the single latest closed period — **no history** |
| plant | A400/A500/A501 | plant/DC — **actuals have plant; forecast doesn't** |
| quantity | −8 → 23,832, 2 neg, 1 null | units sold (negatives = returns) |
| revenue | −33 → 139,894 EUR | actual revenue — **no COGS** |

### fct_budget — the sales target, own table (org 3710 sample, 35,156 rows)
| Column | Values | Meaning |
|---|---|---|
| fiscal_period | **1.2026 → 12.2026 (full FY)** | budget covers the whole year |
| sales_org | 3710 only (header spelled "Organi**s**ation") | region / BU |
| material | 677 SKUs | SKU |
| triad_region (customer) | JA…JZ (21) | customer |
| value | 0–1,035,618 EUR | budgeted money (revenue target) |
| quantity | 0–375,000, 290 zeros | budgeted units |

No version, no COGS, no plant.

### fct_inventory — current stock snapshot, own table (8 orgs, 11,726 rows)
| Column | Values | Meaning |
|---|---|---|
| sales_org | 8 orgs (incl 2510) | region / BU |
| material | 9,088 SKUs (bigger universe) | SKU |
| plant | 53 plants | stock held **per plant** |
| fiscal_period | **7.2026 only** | current snapshot |
| uom | EA 11,457 / KG 170 / M3 67 / L 12 / M 10 / TO 8 / CAR 1 / CS 1 | **mixed units** |
| quantity | 0 → ~1e9, 30 zeros | stock on hand (huge = bulk KG/M3) |
| value | −0.01 → 1,241,050 EUR, 710 zeros | stock value |

**No customer (triad_region) column** → inventory is `sales_org + material + plant`
grain. Coverage is therefore a **product-level** metric, not customer-level.

---

## Join reality (matters for what populates)

- The three demand-side streams are each a **different org** in the samples
  (fc 2510 / ac 1010 / bg 3710), so **demand-vs-budget and *-vs-actuals return 0
  rows on the sample** — correct against the real multi-org DB, empty here.
- **inventory ∩ forecast overlap within org 2510** (245 shared materials), so
  **inventory coverage actually populates** on the sample.
- Cross-stream join key: `(sales_org, material, fiscal_period[, triad_region])`.

## Data-quality flags for Lily

- COGS stored negative (sign in margin math).
- Negatives in actuals = returns/corrections; 1 null qty.
- Many zero quantities in budget/forecast = planned-but-no-volume lines.
- **Inventory mixed UoM**: coverage = stock ÷ demand only valid when both are EA.
  Guard to `uom = 'EA'` and flag materials with non-EA stock.

## Still missing

- **Statistical forecast** — not delivered. Demand-vs-statistical stays parked.
- **Actuals history** — only P7.2026. Year-over-year stays parked until a prior FY loads.
- **Canonical column names** — confirm against `schema-overview.md` when reachable;
  reconcile is a find-and-replace in the view `FROM` clauses only.
