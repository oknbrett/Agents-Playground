# Lily — Persistent, Team-Shared Memory (design, not yet built)

**Drafted 2026-06-18.** Plan only — no code. Grounded in mid-2026 agent-memory
practice (mem0, Zep/Graphiti, Letta) and tailored to Lily + the Bolders Postgres
+ the internal web app.

---

## 1. What this memory actually is

This is **not** chat-history memory and **not** the numbers. It's a third layer:

| Layer | Question it answers | Where it lives |
|---|---|---|
| Fact layer (the views) | *What* are the numbers? | Bolders Postgres `dw.*` → `lily.*` views |
| Conversation layer | What did we say in *this* chat? | per-session transcript (already handled) |
| **Memory layer (this doc)** | ***Why*** are the numbers like this? What does the team know that the data can't show? | **new — to be designed** |

The memory layer is the **qualitative "why" overlay** on the quantitative "what."
Example, end to end:
- Bart tells Lily: *"P8 demand for SKU UNI40 is set high because of a Q3 retail promotion at that customer."*
- Lily **stores** that as a memory, linked to `material=UNI40`, `customer=…`, valid for the promo window, attributed to Bart.
- Next week a different planner asks Lily *"why is UNI40's plan so high in P8?"* — Lily **recalls** it and answers: *"Per Bart (2026-06-17), a Q3 promotion at that customer; the uplift is intentional, not a forecasting error."*

That single capability gives the whole team a shared point of view. The numbers
never explained the promo; the memory does. **This is the product.**

It is **semantic memory** (durable facts) with **provenance** (who said it) and
**temporal validity** (when it's true) — the three things 2026 practice says make
memory trustworthy in an enterprise.

---

## 2. Two requirements you set

1. **Persistent across conversations** — what's told today is known tomorrow.
2. **Shared within a group** — it's team memory, not one user's private notes.
   One planner's context becomes everyone's context.

Both point to the same thing: memory is **stored centrally (Postgres), scoped to
a group/workspace**, not held in any single chat or user profile.

**Resolved (2026-06-18):**
- **A group = a region / sales-org team.** Every demand planner in, say, Evergreen
  Pokon (`sales_org` ≈ the region/BU) shares **one group, one memory.** Group maps
  to `sales_org`.
- **Lily is group-facing, multi-actor.** She knows she's not talking to one person
  but to a *team over time*. She attributes memories to the named planner who gave
  them and can route people to each other: *"Leonie told me this yesterday — you
  may want to catch up with her on it."* This is "actor-aware" memory: every note
  carries **who** it came from, and recall surfaces that.
- **Any planner can write and delete/supersede** — including marking something
  *"not true anymore, we changed it."*

---

## 3. Design principles (2026 best practice, applied to Lily)

1. **Governed, not a vector dump.** The mature/enterprise pattern ("Pattern 5")
   is a *governed* store: every memory is auditable — who wrote it, when, from
   whom, and whether it's still active. We're in SAP/enterprise territory, so we
   lean governed from day one. (The cheap "flat vector store" is easy to fill and
   impossible to govern — we skip it.)
2. **Entity-scoped.** Every memory links to one or more entities: `material`,
   `customer`, `sales_org` (region/BU), and a period window. Retrieval is
   **entity-first**, then semantic — so Lily pulls the *right* notes, not all notes.
3. **Temporally valid (bi-temporal).** Each memory carries **when it's true in
   the business** (`valid_from`/`valid_to`, often a fiscal-period window) *and*
   **when it was recorded** (`created_at`). This is the fix for the #1 open
   problem in 2026 — *staleness* ("a fact stays confidently wrong after it stops
   being true"). A promo memory simply expires when its window ends.
4. **Provenance / attribution, by named person.** Every memory records **who** —
   the named planner who stated it ("Leonie"), or **Lily herself** if she inferred
   it. So she can cite ("per Bart…") *and* route people to each other ("catch up
   with Leonie"). This is the trust signal you described.
5. **Origin is first-class — the "two kinds of notes."** Each memory is tagged
   `stated` (a human told her) or `inferred` (she figured it out herself,
   unconfirmed). She stores **both**, but she must **say which** when she surfaces
   one: *"I noticed this myself — not yet confirmed by anyone"* vs *"Bart told me."*
   A planner can later **confirm** an inferred note (promoting it) or correct it.
6. **Shared scope.** `group_id` (the region/sales-org team) on every row; all
   members see and contribute. Per-user private notes can come later if needed.
7. **Hybrid retrieval, top-k only.** Structured filter (entity + time + group) →
   semantic rank (pgvector) → rerank → inject only the top handful. **Never load
   all memory into context** — this is what keeps the context window bounded as
   memory grows (your explicit worry).
8. **Explicit lifecycle.** add / edit / **supersede** / soft-delete, plus periodic
   **consolidation**. Conflicts don't overwrite silently — the new memory
   supersedes the old and the old is kept in history (audit + "what did we believe
   when").

---

## 4. Where we store it + the table

In the **same Bolders Postgres** as the facts (colocated, governable, joinable to
entities), in a dedicated schema, e.g. `lily_mem`. mem0's 2026 pattern is exactly
this: Postgres for the durable facts + a vector index for semantic recall.

Illustrative shape (design sketch, **not** final DDL):

```
lily_mem.memory
  memory_id        bigint pk
  group_id         text         -- the region/sales-org team (maps to sales_org)
  content          text         -- the note, in natural language
  memory_type      text         -- context | decision | correction | preference
  -- entity links (nullable; a note can be SKU-wide, customer-wide, etc.)
  sales_org        int          -- region / BU
  customer_code    text         -- the customer (triad_region)
  material_id      text         -- SKU
  period_from      int          -- fiscal_period_key window start (e.g. 202608)
  period_to        int          -- window end
  -- temporal validity (bi-temporal)
  valid_from       date
  valid_to         date         -- null = open-ended; set when it stops being true
  -- origin: the "two kinds of notes"
  origin           text         -- stated | inferred  (human-told vs Lily-figured)
  stated_by        text         -- named person who said it ("Leonie"); null if inferred
  confirmation     text         -- confirmed | unconfirmed  (inferred starts unconfirmed)
  confirmed_by     text         -- planner who later confirmed an inferred note
  -- bookkeeping
  recorded_by      text         -- user in the chat where this was written
  status           text         -- active | superseded | archived
  supersedes_id    bigint       -- points at the memory this replaces
  created_at       timestamptz
  updated_at       timestamptz
  embedding        vector(…)    -- pgvector, for semantic recall
```

- For notes spanning several SKUs/customers, a `lily_mem.memory_entity` link table
  is cleaner than repeating columns — decide once we see real usage.
- Indexes: HNSW on `embedding`; btree on `(group_id, material_id, customer_code,
  sales_org)` and on `(valid_from, valid_to)` for fast entity+time filtering.
- **Never hard-delete by default** — soft-delete to `archived` so the audit trail
  and "right to delete" are both satisfiable.

---

## 5. The tools Lily gets

Alongside the data-query tools, a small memory toolset. **Read path first** (it
delivers value before any write tooling exists).

| Tool | Purpose |
|---|---|
| `recall_memory(query, entities, as_of)` | Hybrid retrieval — the notes relevant to *this* SKU/customer/period, valid as of a date. Called before answering. |
| `add_memory(content, entities, origin, stated_by?, valid_from?, valid_to?)` | Store a new durable fact. `origin=stated` (with `stated_by` = the planner) or `origin=inferred` (Lily's own observation, starts unconfirmed). |
| `confirm_memory(id, confirmed_by)` | A planner promotes one of Lily's inferred notes to confirmed (or corrects it via supersede). |
| `update_memory(id, …)` | Fix a detail (typo, tighten a window). |
| `supersede_memory(id, new_content, …)` | Replace a now-wrong memory; keeps the old in history. *Preferred over edit for changes of substance.* |
| `delete_memory(id, reason)` | Soft-delete (archive) with a reason. |
| `list_memories(entity)` | Enumerate notes on an entity — powers the curation UI. |

**When to recall:** always, before answering anything about a specific
SKU/customer/period — so answers carry the "why," with attribution ("per Leonie…").
**When to write:** two triggers —
- **A planner tells her** a durable, decision-relevant fact not in the numbers
  (promotions, listings, delistings, one-off events, deliberate overrides, data
  caveats) → store as `origin=stated`, `stated_by` = that planner.
- **Lily notices something herself** the planners may have missed (a pattern, an
  anomaly) → store as `origin=inferred`, `unconfirmed`. **Next time she raises it
  she flags it as her own unconfirmed observation** — and invites a planner to
  confirm or correct it. (This is the behaviour you valued: she surfaces what
  nobody noticed, honestly labelled.)

---

## 6. Keeping it sharp (write discipline, conflict, decay)

These are the parts 2026 tooling leaves to you — so we set explicit policy.

- **Capture filter.** Before storing, Lily judges: is this durable? decision-
  relevant? not already in the numbers? For **human-stated** facts that are
  ambiguous, she **confirms with the planner** before writing. For her **own
  inferences** she may write freely *because they're labelled `inferred` /
  unconfirmed* — the label, not a gate, is what prevents poisoning. A confident,
  unlabelled wrong "fact" is the danger; a clearly-marked hypothesis is not.
- **Dedup on write.** `add_memory` first does a `recall` for near-duplicates; if
  one exists, update/merge instead of creating a second.
- **Conflict = supersede, not overwrite.** New contradicting memory supersedes the
  old; old kept with `status=superseded`. Lily can always answer "what did we
  believe, and when."
- **Decay.** Memories with a `valid_to` expire automatically. Open-ended memories
  older than N periods get **flagged for review** rather than trusted forever.
- **Consolidation / reflection (periodic job).** Merge fragmentary notes on the
  same entity into one durable summary; archive stale ones. Keeps both the table
  and the retrieved context small.

---

## 7. Context-window control (your "it gets too big" concern)

Three mechanisms, all standard in 2026:

1. **Retrieve, don't dump.** Only the top-k (≈5–8) entity- and time-relevant
   memories enter context per question. Memory can grow to millions of rows; the
   prompt stays flat. (This is the same trick that lets Lily scale over millions
   of *fact* rows — she reads finished, filtered results, never the whole store.)
2. **Tiering (Letta-style hot/cold).** A tiny set of "core" group-wide notes can
   be pinned/always-on; everything else is "archival," pulled only on demand.
3. **Consolidation** (§6) keeps the recalled set short by merging duplicates.

---

## 8. How it plugs into what we have

- **Store:** `lily_mem` schema in the **same Bolders Postgres** as the facts.
- **Embeddings:** self-hosted **BGE-M3**, generated at write time (in-house, zero
  marginal cost, multilingual). BGE-reranker-v2 if/when reranking is added.
- **Tools:** new memory tools live next to the view-query tools in
  `agents/lily/tools.py`; same read-only-by-default discipline, writes audited.
- **Web app:** a **memory side-panel** — view notes on a SKU, see provenance,
  edit/supersede/delete. This is where *owning the app instead of Azure Foundry
  pays off*: you control the memory store, retrieval, and the cross-team sharing
  rules end to end. (Foundry would have hidden this layer.)
- **Group = workspace** in the app; membership defines who shares a memory.

---

## 9. Phased rollout (when we build)

- **Phase 0 — read path.** Schema + a few hand-seeded memories + `recall_memory`.
  Lily starts citing context. Proves the value with almost no surface area.
- **Phase 1 — write path.** `add` / `supersede` / soft-delete + the capture
  discipline in the prompt. Now the team builds memory by talking to her.
- **Phase 2 — real retrieval + UI.** pgvector hybrid search + reranking; the
  curation side-panel.
- **Phase 3 — hygiene + governance.** Consolidation/reflection job, staleness
  review, audit/lineage polish, access rules.

---

## 10. Decisions

**Settled (2026-06-18):**
1. ✅ **Group granularity.** One shared memory per **region/sales-org team**
   (group maps to `sales_org`). Lily is group-facing and multi-actor — attributes
   to named people and routes planners to each other.
2. ✅ **Who can write/delete.** Any **planner** — including marking a memory no
   longer true.
3. ✅ **Auto-write.** Lily stores **both** human-stated facts *and* her own
   inferences — but origin is always recorded (`stated` vs `inferred`) and she
   discloses inferred ones as unconfirmed when she surfaces them. Planners can
   confirm or correct.

4. ✅ **Embedding model + language. Self-host BGE-M3** (MIT, 100+ languages,
   proven cross-lingual). Why: embeddings are the *cheap* part (computed only on
   write + query; memory write volume is tiny), so the choice is own-vs-rent —
   self-hosting gives **zero marginal cost** and keeps internal business context
   **in-house** (right governance for enterprise/SAP data; fits the own-the-stack
   direction). **Language partitions by group:** because a group = one region,
   each memory is effectively mono/bilingual (NL = Dutch+English, FR = French,
   PL = Polish), so we mostly need strong *within-language* recall (the easy case)
   — cross-lingual rarely fires. Notes stored **verbatim** in their original
   language; Claude bridges languages at answer time. Pair with BGE-reranker-v2
   if reranking is needed.

5. ✅ **Where memory lives, for now. Start in our own local DB** (DuckDB,
   alongside `lily_local.duckdb`) — we don't have Bolders GitHub / Postgres access
   yet. Same pattern as the data layer: build locally, **swap to the Bolders
   Postgres `lily_mem` schema via connection string when access lands** (the views
   and tools don't change). pgvector lives on the Postgres side; for the local
   DuckDB stand-in, use DuckDB's VSS extension or a simple in-table similarity for
   Phase 0. So Phase 0 is **not blocked** on Bart.

---

### Sources (mid-2026 practice)
- [State of AI Agent Memory 2026 — mem0](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Agent Memory Architectures: Patterns & Trade-offs — Atlan](https://atlan.com/know/agent-memory-architectures/)
- [Best AI Agent Memory Frameworks 2026 — Atlan](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)
- [AI Agent Memory: Types, Implementation, Best Practices 2026 — 47Billion](https://47billion.com/blog/ai-agent-memory-types-implementation-best-practices/)
