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

**Status:** mid-rewrite. Current on-disk version (commit `fd6dfab`) is a first
pass — identity paragraph + "Hard guardrails" + "Communication style" + "How
to work" (pointing at the skill instead of inlining procedure). It is **not**
final. The following changes were agreed in chat but not yet written back to
the file:

- [ ] Remove the "forecasts that look like placeholders" example from the
      identity paragraph — it presupposes a finding we haven't verified.
      Replace with a general rule: never assert a pattern/issue exists unless
      the data actually retrieved shows it.
- [ ] Remove guardrails that describe *today's* data limits (e.g. "only the
      most recently closed actuals period", "inventory not wired in yet").
      The system prompt should describe Lily's permanent role against the
      *ideal* future dataset — data-readiness facts belong in the skill
      (which is meant to evolve), not here.
- [ ] Replace the "BR-06, BR-08, BR-09, BR-11" references with plain-language
      scope — Lily was never given the BR numbering, so citing the codes is
      meaningless to her.
- [ ] Add an explicit mention of the statistical baseline forecast stream —
      currently missing entirely.
- [ ] Reconsider the "never write SQL, joins, or arithmetic" line. Keep the
      arithmetic point (read pre-computed figures, don't calculate them), but
      drop the SQL/joins framing — Lily's tools never exposed that capability
      to begin with, so prohibiting it is confusing, not useful.
- [ ] Restore an explicit verdict requirement in "Communication style":
      Lily must end with RAISE / LOWER / KEEP (+ confidence). This is
      distinct from forecast-accuracy judgment (which stays out of scope) —
      a forward-looking verdict comparing plan vs. history/budget/stat
      baseline is allowed; judging *past* DP accuracy is not.
- [ ] Add an assumption-transparency rule: Lily must flag her own inferences
      explicitly as inferences, never present them as fact. Example: if she
      says "there's a trend," she must show it holds across years — calling
      out a pattern seen in one year but not another as a trend, without
      flagging the uncertainty, is the failure mode to prevent.
- [x] Persona decision (settled, don't revisit without new input): tone may
      vary by role, but pushback strength scales with confidence/evidence
      only — never with gender. Do not give Lily/Billy gendered personality
      traits.

**Next action:** draft the full v3 prompt text in chat, get sign-off, write
to `agents/lily/lily.py`, commit + push.

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
