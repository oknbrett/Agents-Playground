# Handoff — Postgres views live, tool layer aligned & tested

> Updated 2026-06-24 (evening). Start next session by saying:
> **"Read HANDOFF.md."** The real warehouse work is DONE; what's left is Foundry +
> the live LLM run (needs Anthropic credit) and the Wednesday session with Sandeep.

## What's done this session (all against the LIVE Azure Postgres)

Connected via Entra token, explored the real schema, rewrote the serving views to
the real column names, applied them to the warehouse, and verified the whole Lily
tool layer runs on real data — **no LLM, so no Anthropic credit spent.**

- **Schema explored** → `sql/SCHEMA_DUMP.md` (all 13 `warehouse.*` tables: columns,
  types, row counts, PK/FK, samples). Regenerate with `python explore_schema.py`.
- **Views rewritten & APPLIED** → `sql/lily_views_pg.sql` creates the `lily.*` schema
  (25 views) in the live warehouse. All 25 verified populated. Re-apply with
  `python apply_views.py`. **This supersedes `lily_views_runnable.sql`** (which stays
  as the DuckDB/synthetic-dev version).
- **`_connect()` wired for Entra** (`agents/lily/tools.py`): set `LILY_USE_ENTRA=1`
  (or `LILY_PG_HOST`) → fetches an `az` token and connects. `LILY_PG_PASSWORD`
  overrides with Bart's admin password if ever needed. DuckDB stays the default for
  dev. Also fixed a real portability bug: tool SQL uses `?` placeholders → now
  auto-translated to psycopg2 `%s` on the Postgres path.
- **All tools tested on real data** → `python test_tools_pg.py` runs every tool
  against Postgres. Fixed two bugs the synthetic DuckDB hid: text `fiscal_period_key`
  mis-sorting across year boundaries (now order by `fiscal_year, fiscal_period`), and
  missing `NULLS LAST` letting null-revenue noise SKUs rank to the top.

## Key realities of the real warehouse (differ from the synthetic assumptions)

- **8 sales orgs**, all live: 1010 DE, 1110 UK, 1210 FR, 1810 PL, 1910 AT, 2510
  Benelux, 3010 AU, **3710 Pokon**. (Not the single synthetic `2510`; and `2510` is
  Benelux, not Pokon.)
- **No statistical-baseline stream exists** → `demand_vs_statistical` was **dropped**
  (Lily is now **14 tools**). The vintage-revision view `vw_forecast_version_delta`
  is there if we ever want a `forecast_revision` tool as the override lens.
- **Forecast = 11 weekly VINTAGES** (`forecast_version_key` like `35.2026`), bridged
  to a period via `dim_fiscal_week` (Bart's 4-4-5 work). Latest vintage = `35.2026`.
  **Accuracy/bias (Billy) is rebuilt from the vintages** — lag = target − cut period;
  lag-2 gives ~79k matched forecast↔actual rows. Works on real data.
- **`fiscal_period_key` is TEXT** (`008.2026` = P8 FY2026) and does **not** sort
  chronologically — everything orders via `dim_fiscal_period (fiscal_year,
  fiscal_period_number)`.
- **FY starts in OCTOBER** (confirmed by Brett/Bart 2026-06-24, not the old "November"):
  P1=Oct, P2=Nov, P3=Dec, P4=Jan, P5=Feb, P6=Mar, P7=Apr, P8=May, P9=Jun, P10=Jul,
  P11=Aug, P12=Sep. Baked into the prompt, overview, and skill.
- **"Now" anchor = P8 FY2026 = May 2026** (latest closed actuals); "now" = P9 = June,
  which matches the real calendar date. Good sanity check.
- **Families come from `dim_product_hierarchy`** via `dim_material` (91% coverage),
  NOT the sparse `dim_material_sales_organization` helper (>90% of combos absent).
- COGS stored negative → margin = revenue − ABS(cogs).

## Bart's guidance (from the 2026-06-24 call)

- **Direct DB tool call from the Agent Framework — no MCP server, no Azure Function
  in between.** Confirms the current `tools.py` design. He'll hand over the admin
  password if the Entra token flow is ever a pain.
- Only touch the `warehouse` schema (ignore `staging` / `ingestion`).
- Ingestion is fully automated now (drop an Excel file → cleaned + loaded).
- **Never run the DB/view work in "dangerously skip permissions" mode.** (We didn't.)

## What's left

- [x] **FY-start month confirmed = October** (Brett/Bart, 2026-06-24). Baked in.
- [ ] Live end-to-end LLM run on real data — needs **Anthropic credit** (ran out).
      The tool layer is proven; only the model loop is untested on real data.
- [ ] Agent Framework / Foundry: `lily_msft.py` updated (statistical tool removed),
      still untested without a Foundry endpoint. Switch model to GPT 5.4 via Foundry.
- [ ] React ↔ Foundry endpoint wiring (Sandeep sent the webapp repo link).
- [ ] Frontend ownership decision (before Wednesday).
- [ ] SQL templates + audit hooks for compliance.
- [ ] MR to Bart for review.
- [ ] Dash PPTX quality (needs Anthropic top-up to test).
- [ ] **CLAUDE.md is now stale** (says FY=November, 15 tools, statistical stream,
      single region 2510, `lily_views_runnable.sql` as the prod views). Update it
      to match this handoff when convenient.

## Dates
- **Wednesday 2026-06-25** — 2hr session with Sandeep.
- **Friday 2026-06-27** — target release.

## Files to know
| File | What |
|---|---|
| `sql/lily_views_pg.sql` | **The real-warehouse views** (applied to live DB). |
| `sql/SCHEMA_DUMP.md` | Full real schema reference (13 warehouse tables). |
| `agents/lily/tools.py` `_connect()` | Entra-token / admin-password / DuckDB paths. |
| `apply_views.py` | Re-apply + verify the `lily.*` views on Postgres. |
| `test_tools_pg.py` | Smoke-test every tool against Postgres (no credit). |
| `explore_schema.py` | Regenerate `SCHEMA_DUMP.md`. |
| `test_postgres.py` | Minimal connection check. |
