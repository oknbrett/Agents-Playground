# UI element inventory — Lily chat assistant

This is a **content/element list**, not a design brief. You own all the visual
design — layout, color, type, spacing, motion, everything. This just tells you
*what has to be on screen* so the mockup covers the whole app.

The product: an internal chat assistant with three switchable agents — **Lily**
(demand-planning analyst), **Kofi** (web research), and **Dash** (document builder).
One chat interface, three agents.

Please mock up **two states** (empty + active conversation) and show **every element
below at least once**. A settings modal is a nice-to-have. Deliver it as a single
self-contained file, and include a light and a dark version.

---

## Screen 1 — empty / new chat

- A greeting (e.g. "Good morning, [name]") with a short subline prompting the user.
- The message composer (see below).
- A few suggestion shortcuts the user can click to start — each a short title plus a
  one-line description. Examples: "Analyse a SKU", "Find demand patterns",
  "Flag forecast bias".

## Screen 2 — active conversation

A back-and-forth that surfaces every in-chat element listed under "Message content".

---

## Sidebar

- A "new chat" action.
- A search field for conversations.
- Conversation history, grouped by recency (Today / Yesterday / Previous 7 days),
  each a single-line title (long titles truncate), with the current one indicated.
- The signed-in user: avatar, name, email, and a sign-out action.

## Top bar (above the conversation)

- An **agent switcher**: shows the current agent and lets the user switch between
  **Lily**, **Kofi**, and **Dash**.
- Secondary actions: overflow menu, share, export, new chat.

## Composer

- A multi-line text input with a placeholder.
- A toggle for a deeper web-research mode.
- An attach-file control.
- A send control.

## Message content (in an active conversation)

1. **User message** — what the person typed.
2. **Agent message** — the agent's avatar + name + timestamp, then a rich body that
   can contain headings, **tables**, bold text, and bullet lists. (Lily writes
   structured analyses with tables, so tables need to be first-class.)
3. **Recommendation** — a stand-out verdict label: one of `RAISE` / `LOWER` /
   `KEEP` / `UNCERTAIN`, plus a confidence tag (high / medium / low).
4. **Tool-step trace** — a compact, expandable list of the steps an agent took, with
   a done indicator per step (e.g. "Reading the demand forecast", "Checking forecast
   accuracy"), and an in-progress indicator on the running step.
5. **Status line** — a short interim note shown while the agent works, before results
   (e.g. "Sending Kofi to research the market while I pull the actuals…").
6. **Research sources panel (Kofi)** — an expandable summary bar showing counts and
   cost (e.g. "4 searches · 20 sources · $0.15"), which opens to a list of the search
   queries, each with its source links (title + url).
7. **File card** — a downloadable document the Dash agent produced, shown as a file
   name + type (.pptx / .pdf / .docx) + a download action. A message may have 1–3.
8. **Usage line** — a small footer under a message: step count, token count (and how
   many were cached), and cost (e.g. "3 steps · 5.3k tokens (4.9k cached) · $0.003").

## Settings modal (optional)

Tabbed: Profile, Appearance, Memory, Sessions, Shortcuts.

---

When you're happy with it, the file comes back to be wired into the live app, so it
helps if the structure is clean and the colors/spacing run through CSS variables —
but the design itself is entirely yours.
