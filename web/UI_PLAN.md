# Lily Chat UI — Plan

Tracking all UI improvements for Lily's web chat interface.

---

## Done

### Chat Layout (commit 9bb261f)
- [x] User messages aligned right with accent-colored bubble
- [x] Agent (Lily) messages stay left
- [x] Chat-style rounded corners (sharp bottom-right on user bubbles)
- [x] Max-width 75% on user bubbles

### Dynamic Chat History (commit 784f01c)
- [x] Removed hardcoded "Recents" sidebar entries
- [x] Sessions persist to localStorage, titled by first user message
- [x] Click a session to restore full message history
- [x] Delete button (×) on hover per session
- [x] Active session highlighted in sidebar
- [x] "New chat" clears conversation and resets state
- [x] Recents section hidden when no sessions exist

### Major UI Upgrade (commit 4786e62)
- [x] **Markdown rendering** — react-markdown + remark-gfm for headers, tables, code blocks, lists, bold/italic
- [x] **Dark mode** — full CSS variable theming, persisted to localStorage, respects prefers-color-scheme
- [x] **Copy-to-clipboard** — hover-revealed copy button on every assistant message with "Copied" feedback
- [x] **Collapsible tool-call steps** — chevron toggle, collapsed when done, expanded while running
- [x] **Retry button** — appears on failed/error messages to re-send last user message
- [x] **Message timestamps** — relative time ("2m ago", "1h ago") on all messages
- [x] **Lily avatar** — branded leaf icon next to assistant name
- [x] **Responsive layout** — sidebar slides in as overlay on mobile (<768px), hamburger menu
- [x] **Keyboard shortcuts** — Cmd/Ctrl+K new chat, Escape blur/close
- [x] **Accessibility** — aria-labels on buttons, role="log" on conversation, aria-live="polite"
- [x] **Shortcut hint** on welcome screen

### Settings Modal (commit 56cf462)
- [x] **Profile** — editable display name, role/team, avatar initial (replaces hardcoded "Brett")
- [x] **Appearance** — three-option segmented control (Light/Dark/System), font size (Compact/Default/Large)
- [x] **AI Preferences** — response style (Concise/Balanced/Detailed), editable API endpoint URL
- [x] **Memory** — add/delete facts, scrollable list with per-item delete, clear-all with confirmation (localStorage only, not wired to backend)
- [x] **Sessions** — chat count, export all as JSON, clear all with confirmation, editable quick action buttons
- [x] **Shortcuts** — read-only reference table of all keybindings
- [x] Gear icon in sidebar footer + Cmd/Ctrl+, shortcut to open
- [x] Modal closes on Escape and backdrop click

---

## To Do — Next Priorities

### Recommendation Cards (high impact)
- [ ] Parse Lily's RAISE/LOWER/KEEP outputs into structured cards
- [ ] Color-coded signals: blue for RAISE, orange for LOWER, gray for KEEP (colorblind-safe)
- [ ] Confidence badge (percentage pill or progress bar)
- [ ] Key metric pulled out as headline number
- [ ] Card layout: signal color left border, title, confidence, reasoning summary

### Wire Up Settings to Agent Behavior
- [ ] Pass `responseStyle` (concise/balanced/detailed) as system prompt modifier to backend
- [ ] Pass `memory` entries as context in API requests
- [ ] Connect `apiUrl` setting to the actual fetch call (done in code, needs backend support)

### Loading Skeleton
- [ ] Replace bouncing dots with shimmer skeleton matching assistant message shape
- [ ] 2-3 gray placeholder bars that fade to real content

### Inline Data Visualization
- [ ] Render simple tables from Lily's tool results inline
- [ ] Sparkline or mini bar charts for period-over-period data
- [ ] Consider lightweight chart library (e.g., recharts) for trend visualization

### Export & Share
- [ ] Copy single message as formatted text
- [ ] Export individual analysis as PDF or PNG
- [ ] Share link to a specific session (would need backend)

---

## Backlog — Lower Priority

- [ ] Search within settings (unnecessary at current scale, revisit if categories grow)
- [ ] Notification preferences (needs backend)
- [ ] Avatar image upload (currently just initial letter)
- [ ] Workspace vs personal settings separation (needs multi-user support)
- [ ] Integration settings for external services (Slack, Teams push)
- [ ] Animated theme transition (crossfade between light/dark)
- [ ] Message reactions / thumbs up-down feedback
- [ ] Drag-to-reorder quick actions
- [ ] Pin/favorite important sessions
- [ ] Session search / filter in sidebar

---

## Architecture Notes

- All settings stored in `localStorage` under key `lily-settings`
- Memory stored separately under `lily-memory` (flat list of {id, text, ts} objects)
- Chat sessions under `lily-chat-sessions`
- No backend database for settings/memory yet — plan is to wire to a real store later
- Settings modal is a standalone React component (`SettingsModal`) rendered as overlay
- Theme applied via `data-theme` attribute on `<html>`, font size via `data-font-size`
- CSS uses full variable system for theming — adding new themes is just a new `[data-theme="x"]` block
