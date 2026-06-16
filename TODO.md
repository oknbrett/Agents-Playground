# Lily — To-Do (split by session)

Two separate workstreams from here on. Keep them in separate chats so one
doesn't drag the other's context along. Say "we're doing the system prompt"
or "we're doing skills" at the start of a new chat and point Claude at this
file — it should not need to re-derive any of this from scratch.

Old/superseded design docs have been moved to `archive/sql/` so they don't
get pulled into a fresh session's context by accident. See
`sql/RETROSPECTIVE.md` for why they're superseded.

---

## Track 1 — System prompt (`agents/lily/lily.py` → `LILY_SYSTEM_PROMPT`)

**Status:** v3 rewrite written to `agents/lily/lily.py` (commit pending in
this session). All items below are done — Track 1's wording work is
complete for now.

- [x] Removed the "forecasts that look like placeholders" example from the
      identity paragraph — replaced with a general rule: never assert a
      pattern/issue exists unless the data actually retrieved shows it.
- [x] Removed guardrails that described *today's* data limits (e.g. "only
      the most recently closed actuals period", "inventory not wired in
      yet"). The system prompt now describes Lily's permanent role against
      the *ideal* future dataset — data-readiness facts live in the skill
      instead.
- [x] Replaced the "BR-06, BR-08, BR-09, BR-11" references with
      plain-language scope.
- [x] Added an explicit mention of the statistical baseline forecast stream.
- [x] Dropped the "never write SQL, joins" framing; kept only the
      arithmetic point, reframed positively ("read figures your tools have
      already calculated rather than computing them yourself").
- [x] Restored an explicit verdict requirement in "Communication style":
      every analysis ends with RAISE / LOWER / KEEP / UNCERTAIN + confidence.
- [x] Added an assumption-transparency rule: Lily must flag her own
      inferences explicitly as inferences, never present them as fact (the
      "trend visible in one year but not another" example).
- [x] Persona decision (settled, don't revisit without new input): tone may
      vary by role, but pushback strength scales with confidence/evidence
      only — never with gender. Do not give Lily/Billy gendered personality
      traits.

**Next action, if anyone opens this track again:** re-read the prompt fresh
and stress-test it against a real SKU run once the SQL tool (see Track 2)
exists — right now it's still aspirational, since Lily's tools don't query
`lily.*` views yet.

---

## Track 2 — Skills (`agents/lily/skills/demand-planning-analysis/SKILL.md`)

**Status:** first version exists (commit `c3fd704`), grounded in the real
`lily.*` Postgres views (`sql/lily_views_runnable.sql`,
`sql/lily_view_catalog.md`). Known issues, carried over from the same review
pass as the system prompt, not yet fixed:

- [ ] Output format block (`QUESTION SCOPE / ANSWER / FLAGS`) has no verdict
      slot — needs a RAISE/LOWER/KEEP field once the system prompt settles
      on its exact wording (Track 1 should land first, or at least the
      verdict language should be decided jointly).
- [ ] YAML `description` still says "placeholder-looking forecasts" — same
      presupposed-finding issue removed from the system prompt; fix in the
      same direction.
- [ ] "BR-06" reference in the "Not available yet" section — same
      undefined-jargon issue as the system prompt; replace with plain
      language.
- [ ] "Never write SQL joins, aggregations, or percentage math yourself" —
      same questioned line as the system prompt's dropped SQL/joins framing.

**Bigger, blocking gaps (design work, not just wording):**
- [ ] No SQL tool exists yet. `agents/lily/tools.py`, and the
      `TOOL_DEFINITIONS`/`TOOL_DISPATCH` in `lily.py` / `lily_msft.py`, still
      only have the four old pandas tools over the synthetic dataset. There
      is no tool that queries `lily.*` views. The skill currently describes
      capabilities Lily doesn't have.
- [ ] No skill-loading mechanism exists in either runtime (`lily.py`,
      `lily_msft.py`). `SKILL.md` is not injected into context anywhere
      today — it's a design artifact, not yet wired up.
- [ ] Per the demand planner's actual workflow (input still needed): figure
      out which additional skills are worth building beyond
      `demand-planning-analysis` — this was the original motivation for
      starting the skills track ("creating skills based on the dataset and
      info from the demand planner on how they work").

**Next action (separate chat):** talk through demand-planner workflows to
figure out what skill(s) are actually needed, then fix the four wording
issues above, then tackle the SQL-tool + skill-loader build.

---

## Archive

`archive/sql/` — `PLAN.md`, `lily_br_views.sql`, `README.md`: the 2026-06-15
four-stream design draft, superseded by `sql/lily_views_runnable.sql` +
`sql/lily_view_catalog.md` (2026-06-16). Kept for history, moved out of
`sql/` so it doesn't get pulled into a fresh session's context by accident.
See `sql/RETROSPECTIVE.md` for the full story of what changed and why.
