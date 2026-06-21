import { useState, useRef, useEffect, useCallback } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/* Small inline icons (no dependency) */
const Leaf = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
       stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 20A7 7 0 0 1 4 13c0-5 4-9 9-9 0 0 1 4-2 7" />
    <path d="M11 20c0-6 3-10 9-12" />
  </svg>
)
const DashIcon = ({ size = 22 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
       stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2" />
    <path d="M7 8h10M7 12h6M7 16h8" />
  </svg>
)
const Plus = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
)
const Send = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12h14M13 6l6 6-6 6" /></svg>
)
const CopyIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
)
const RetryIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M1 4v6h6" /><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
  </svg>
)
const MenuIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round">
    <path d="M3 12h18M3 6h18M3 18h18" />
  </svg>
)
const ChevronIcon = ({ open }) => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
       style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.15s ease' }}>
    <path d="M9 18l6-6-6-6" />
  </svg>
)
const GearIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.32 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
)
const TrashIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
  </svg>
)
const DownloadIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
  </svg>
)
const CloseIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round">
    <path d="M18 6L6 18M6 6l12 12" />
  </svg>
)
const AttachIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
)
const HandoffIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
)

/* ── Agent configuration ─────────────────────────────── */
const AGENTS = {
  lily: {
    id: 'lily',
    name: 'Lily',
    subtitle: 'Demand planning analyst',
    icon: Leaf,
    streamUrl: 'http://localhost:8000/api/chat/stream',
    modelLabel: 'Claude Sonnet 4.6',
    placeholder: 'Ask Lily about a SKU, forecast, or demand pattern…',
    quickActions: ['Analyse a SKU', 'Compare forecasts', 'Find demand patterns', 'Flag forecast bias'],
  },
  dash: {
    id: 'dash',
    name: 'Dash',
    subtitle: 'Report & presentation builder',
    icon: DashIcon,
    streamUrl: 'http://localhost:8000/api/dash/chat/stream',
    modelLabel: 'Claude Sonnet 4.6',
    placeholder: 'Tell Dash what to build — a slide deck, PDF report, or summary…',
    quickActions: ['Build a forecast review deck', 'Create an executive summary', 'Turn analysis into slides', 'Draft a planning report'],
  },
}

const AGENT_KEY = 'lily-last-agent'
const SETTINGS_KEY = 'lily-settings'
const MEMORY_KEY = 'lily-memory'
const STORAGE_KEY = 'lily-chat-sessions'

const DEFAULT_SETTINGS = {
  displayName: 'Brett',
  role: 'Demand Planning',
  avatarInitial: 'B',
  theme: 'system',
  fontSize: 'default',
  responseStyle: 'balanced',
  quickActions: ['Analyse a SKU', 'Compare forecasts', 'Find demand patterns', 'Flag forecast bias'],
}

function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY)) }
  } catch { return { ...DEFAULT_SETTINGS } }
}

function saveSettings(s) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s))
}

function loadMemory() {
  try {
    return JSON.parse(localStorage.getItem(MEMORY_KEY)) || []
  } catch { return [] }
}

function saveMemory(m) {
  localStorage.setItem(MEMORY_KEY, JSON.stringify(m))
}

const SETTINGS_TABS = [
  { id: 'profile', label: 'Profile' },
  { id: 'appearance', label: 'Appearance' },
  { id: 'ai', label: 'AI Preferences' },
  { id: 'memory', label: 'Memory' },
  { id: 'sessions', label: 'Sessions' },
  { id: 'shortcuts', label: 'Shortcuts' },
]

const SHORTCUTS = [
  { keys: ['Enter'], desc: 'Send message' },
  { keys: ['Shift', 'Enter'], desc: 'New line' },
  { keys: ['⌘/Ctrl', 'K'], desc: 'New chat' },
  { keys: ['Esc'], desc: 'Close / blur' },
  { keys: ['⌘/Ctrl', ','], desc: 'Open settings' },
]

function SettingsModal({ settings, onSave, onClose, sessions, onClearSessions }) {
  const [tab, setTab] = useState('profile')
  const [draft, setDraft] = useState({ ...settings })
  const [memory, setMemory] = useState(loadMemory)
  const [newMemory, setNewMemory] = useState('')
  const [confirmClear, setConfirmClear] = useState(null)

  const update = (key, val) => setDraft((d) => ({ ...d, [key]: val }))

  const handleSave = () => {
    saveSettings(draft)
    saveMemory(memory)
    onSave(draft)
    onClose()
  }

  const addMemory = () => {
    const text = newMemory.trim()
    if (!text) return
    const entry = { id: crypto.randomUUID(), text, ts: Date.now() }
    setMemory((m) => [entry, ...m])
    setNewMemory('')
  }

  const deleteMemory = (id) => setMemory((m) => m.filter((e) => e.id !== id))

  const clearAllMemory = () => {
    if (confirmClear === 'memory') {
      setMemory([])
      setConfirmClear(null)
    } else {
      setConfirmClear('memory')
    }
  }

  const clearAllSessions = () => {
    if (confirmClear === 'sessions') {
      onClearSessions()
      setConfirmClear(null)
    } else {
      setConfirmClear('sessions')
    }
  }

  const exportChats = () => {
    const blob = new Blob([JSON.stringify(sessions, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `lily-chats-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const updateQuickAction = (idx, val) => {
    const next = [...draft.quickActions]
    next[idx] = val
    update('quickActions', next)
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="settings-header">
          <h2>Settings</h2>
          <button className="settings-close" onClick={onClose} aria-label="Close settings">
            <CloseIcon />
          </button>
        </div>
        <div className="settings-body">
          <nav className="settings-nav">
            {SETTINGS_TABS.map((t) => (
              <button
                key={t.id}
                className={`settings-nav-item${tab === t.id ? ' active' : ''}`}
                onClick={() => { setTab(t.id); setConfirmClear(null) }}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="settings-content">

            {tab === 'profile' && (
              <div className="settings-section">
                <h3>Profile</h3>
                <p className="settings-desc">Personalize how Lily addresses you.</p>
                <div className="settings-field">
                  <label>Display name</label>
                  <input type="text" value={draft.displayName} onChange={(e) => update('displayName', e.target.value)} />
                </div>
                <div className="settings-field">
                  <label>Role / Team</label>
                  <input type="text" value={draft.role} onChange={(e) => update('role', e.target.value)} />
                </div>
                <div className="settings-field">
                  <label>Avatar initial</label>
                  <input type="text" maxLength={2} value={draft.avatarInitial} onChange={(e) => update('avatarInitial', e.target.value.toUpperCase())} className="input-short" />
                </div>
              </div>
            )}

            {tab === 'appearance' && (
              <div className="settings-section">
                <h3>Appearance</h3>
                <p className="settings-desc">Customize how the app looks.</p>
                <div className="settings-field">
                  <label>Theme</label>
                  <div className="segmented-control">
                    {['light', 'dark', 'system'].map((t) => (
                      <button key={t} className={draft.theme === t ? 'active' : ''} onClick={() => update('theme', t)}>
                        {t === 'light' ? '☀ Light' : t === 'dark' ? '☽ Dark' : '◐ System'}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="settings-field">
                  <label>Font size</label>
                  <div className="segmented-control">
                    {['compact', 'default', 'large'].map((s) => (
                      <button key={s} className={draft.fontSize === s ? 'active' : ''} onClick={() => update('fontSize', s)}>
                        {s.charAt(0).toUpperCase() + s.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {tab === 'ai' && (
              <div className="settings-section">
                <h3>AI Preferences</h3>
                <p className="settings-desc">Adjust response style.</p>
                <div className="settings-field">
                  <label>Response style</label>
                  <div className="segmented-control">
                    {['concise', 'balanced', 'detailed'].map((s) => (
                      <button key={s} className={draft.responseStyle === s ? 'active' : ''} onClick={() => update('responseStyle', s)}>
                        {s.charAt(0).toUpperCase() + s.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {tab === 'memory' && (
              <div className="settings-section">
                <h3>Memory</h3>
                <p className="settings-desc">Things the agents remember about you across sessions. Stored locally in your browser.</p>
                <div className="memory-input-row">
                  <input
                    type="text"
                    placeholder="Add something to remember..."
                    value={newMemory}
                    onChange={(e) => setNewMemory(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') addMemory() }}
                  />
                  <button className="btn-primary" onClick={addMemory} disabled={!newMemory.trim()}>Add</button>
                </div>
                <div className="memory-list">
                  {memory.length === 0 && (
                    <div className="memory-empty">No memories yet. Add facts about your preferences, team, or workflow.</div>
                  )}
                  {memory.map((m) => (
                    <div key={m.id} className="memory-item">
                      <span className="memory-text">{m.text}</span>
                      <button className="memory-delete" onClick={() => deleteMemory(m.id)} aria-label="Delete memory">
                        <TrashIcon />
                      </button>
                    </div>
                  ))}
                </div>
                {memory.length > 0 && (
                  <button className="btn-danger" onClick={clearAllMemory}>
                    {confirmClear === 'memory' ? 'Confirm clear all?' : 'Clear all memories'}
                  </button>
                )}
              </div>
            )}

            {tab === 'sessions' && (
              <div className="settings-section">
                <h3>Sessions</h3>
                <p className="settings-desc">Manage your chat history.</p>
                <div className="settings-field">
                  <label>Chat history</label>
                  <div className="settings-row">
                    <span className="settings-meta">{sessions.length} saved session{sessions.length === 1 ? '' : 's'}</span>
                    <div className="settings-row-actions">
                      <button className="btn-secondary" onClick={exportChats} disabled={sessions.length === 0}>
                        <DownloadIcon /> Export
                      </button>
                      <button className="btn-danger" onClick={clearAllSessions} disabled={sessions.length === 0}>
                        {confirmClear === 'sessions' ? 'Confirm delete all?' : 'Clear all'}
                      </button>
                    </div>
                  </div>
                </div>
                <div className="settings-field">
                  <label>Quick actions</label>
                  <p className="settings-desc">Customize the buttons shown on the welcome screen.</p>
                  <div className="quick-actions-editor">
                    {draft.quickActions.map((q, i) => (
                      <input key={i} type="text" value={q} onChange={(e) => updateQuickAction(i, e.target.value)} />
                    ))}
                  </div>
                </div>
              </div>
            )}

            {tab === 'shortcuts' && (
              <div className="settings-section">
                <h3>Keyboard Shortcuts</h3>
                <p className="settings-desc">Quick reference for available shortcuts.</p>
                <div className="shortcuts-table">
                  {SHORTCUTS.map((s, i) => (
                    <div key={i} className="shortcut-row">
                      <div className="shortcut-keys">
                        {s.keys.map((k, j) => (
                          <span key={j}>{j > 0 && <span className="shortcut-plus">+</span>}<kbd>{k}</kbd></span>
                        ))}
                      </div>
                      <span className="shortcut-desc">{s.desc}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="settings-footer">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={handleSave}>Save changes</button>
        </div>
      </div>
    </div>
  )
}

function loadSessions() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || []
  } catch { return [] }
}

function saveSessions(sessions) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions))
}

function sessionTitle(messages) {
  const first = messages.find((m) => m.role === 'user')
  if (!first) return 'New chat'
  const text = first.content.trim()
  return text.length > 50 ? text.slice(0, 50) + '…' : text
}

function timeAgo(ts) {
  if (!ts) return ''
  const diff = Math.floor((Date.now() - ts) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text)
}

function stepLabel({ name, input }, agent) {
  if (agent === 'dash') {
    switch (name) {
      case 'create_pptx': return 'Building slide deck'
      case 'create_pdf': return 'Building PDF report'
      case 'read_uploaded_file': return 'Reading uploaded file'
      case 'ask_planner': return 'Asking for your input'
      default: return 'Working'
    }
  }
  const mat = input?.material_id ? ` for ${input.material_id}` : ''
  const cust = input?.customer_code ? ` (customer ${input.customer_code})` : ''
  switch (name) {
    case 'get_overview': return 'Exploring what data is available'
    case 'get_forecast': return `Reading the demand forecast${mat}${cust}`
    case 'demand_vs_budget': return `Comparing the plan against the budget${mat}`
    case 'demand_vs_statistical': return `Comparing against the statistical baseline${mat}`
    case 'inventory_coverage': return `Checking inventory coverage${mat}`
    case 'product_economics': return `Looking at price and margin${mat}`
    case 'top_skus': return `Ranking the top SKUs for period ${input?.fiscal_period ?? '?'}`
    case 'latest_actuals': return `Checking the latest actuals${mat}`
    case 'actuals_history': return `Pulling actuals history${mat}`
    case 'forecast_performance': return `Checking forecast accuracy${mat}`
    case 'sku_performance_scan': return 'Scanning SKU performance'
    case 'family_scan': return 'Scanning product families'
    case 'divergence_scan': return 'Scanning for divergences'
    case 'external_research': return `Kofi is researching: ${input?.query?.slice(0, 60) ?? ''}...`
    case 'ask_planner': return 'Asking for your input'
    case 'load_data': return 'Loading the dataset'
    default: return 'Working through the numbers'
  }
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    copyToClipboard(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button className="copy-btn" onClick={handleCopy} aria-label="Copy to clipboard">
      {copied ? <span className="copied-text">Copied</span> : <CopyIcon />}
    </button>
  )
}

function CollapsibleSteps({ steps, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  if (!steps || steps.length === 0) return null
  return (
    <div className="steps-collapsible">
      <button className="steps-toggle" onClick={() => setOpen(!open)}>
        <ChevronIcon open={open} />
        <span>{steps.length} step{steps.length === 1 ? '' : 's'}</span>
      </button>
      {open && (
        <div className="steps done">
          {steps.map((s, j) => (
            <div key={j} className="step"><span className="tick">{'✓'}</span> {s}</div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Ask Planner choice cards ──────────────────────── */
function AskPlannerCards({ data, onSelect, disabled }) {
  const [selected, setSelected] = useState(data.allow_multi_select ? [] : null)

  const toggle = (label) => {
    if (disabled) return
    if (data.allow_multi_select) {
      setSelected((prev) =>
        prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label]
      )
    } else {
      setSelected(label)
    }
  }

  const confirm = () => {
    if (disabled) return
    const choice = data.allow_multi_select ? selected : [selected]
    onSelect(choice)
  }

  const hasSelection = data.allow_multi_select ? selected.length > 0 : selected !== null

  return (
    <div className="ask-planner">
      <div className="ask-planner-question">{data.question}</div>
      <div className="ask-planner-options">
        {data.options.map((opt) => {
          const isSelected = data.allow_multi_select
            ? selected.includes(opt.label)
            : selected === opt.label
          return (
            <button
              key={opt.label}
              className={`ask-planner-option${isSelected ? ' selected' : ''}${opt.recommended ? ' recommended' : ''}`}
              onClick={() => toggle(opt.label)}
              disabled={disabled}
            >
              <div className="ask-planner-option-label">
                {opt.label}
                {opt.recommended && <span className="ask-planner-rec">Recommended</span>}
              </div>
              <div className="ask-planner-option-desc">{opt.description}</div>
            </button>
          )
        })}
      </div>
      <button
        className="btn-primary ask-planner-confirm"
        onClick={confirm}
        disabled={!hasSelection || disabled}
      >
        Continue with {data.allow_multi_select && selected.length > 1 ? `${selected.length} options` : 'selection'}
      </button>
    </div>
  )
}

/* ── File download card ────────────────────────────── */
function FileCard({ filename, display }) {
  const label = display || filename
  const ext = label.split('.').pop()
  const icon = ext === 'pdf' ? '📄' : ext === 'docx' ? '📝' : ext === 'xlsx' ? '📈' : '📊'
  const downloadUrl = `http://localhost:8000/api/dash/download/${filename}`
  return (
    <a href={downloadUrl} download={display || filename} className="file-card" target="_blank" rel="noopener noreferrer">
      <span className="file-card-icon">{icon}</span>
      <span className="file-card-name">{label}</span>
      <DownloadIcon />
    </a>
  )
}

/* ── Kofi web-research activity (dev transparency) ──── */
function KofiActivity({ traces }) {
  const [open, setOpen] = useState(false)
  if (!traces || traces.length === 0) return null
  const searches = traces.flatMap(t => t.searches || [])
  const nSearches = traces.reduce((a, t) => a + (t.n_searches || 0), 0)
  const nSources = traces.reduce((a, t) => a + (t.n_sources || 0), 0)
  const tokens = traces.reduce((a, t) => a + (t.tokens?.total || 0), 0)
  const cost = traces.reduce((a, t) => a + (t.cost_usd || 0), 0)
  return (
    <div className="kofi-activity">
      <button className="kofi-toggle" onClick={() => setOpen(!open)}>
        <span>🔎 Kofi · {nSearches} search{nSearches === 1 ? '' : 'es'} · {nSources} sources · {(tokens / 1000).toFixed(1)}k tok · ${cost.toFixed(4)}</span>
        <span className="kofi-chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="kofi-detail">
          {searches.map((s, i) => (
            <div key={i} className="kofi-search">
              <div className="kofi-query">“{s.query || '(continuation)'}”</div>
              <ul className="kofi-sources">
                {(s.sources || []).map((src, j) => (
                  <li key={j}>
                    <a href={src.url} target="_blank" rel="noopener noreferrer">{src.title || src.url}</a>
                    {src.age && <span className="kofi-age"> · {src.age}</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Agent switcher pill ──────────────────────────── */
function AgentSwitcher({ agent, onChange, disabled }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const current = AGENTS[agent]

  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  return (
    <div className="agent-switcher" ref={ref}>
      <button
        className="agent-switcher-pill"
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
      >
        {current.name} <span className="agent-switcher-dot">{'·'}</span> {current.modelLabel}
        <ChevronIcon open={open} />
      </button>
      {open && (
        <div className="agent-switcher-dropdown">
          {Object.values(AGENTS).map((a) => (
            <button
              key={a.id}
              className={`agent-switcher-item${a.id === agent ? ' active' : ''}`}
              onClick={() => { onChange(a.id); setOpen(false) }}
            >
              <a.icon size={18} />
              <div>
                <div className="agent-switcher-item-name">{a.name}</div>
                <div className="agent-switcher-item-desc">{a.subtitle}</div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [sessions, setSessions] = useState(loadSessions)
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [steps, setSteps] = useState([])
  const [narration, setNarration] = useState('')  // live "sending Kofi…" line during a run
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settings, setSettings] = useState(loadSettings)
  const [activeAgent, setActiveAgent] = useState(
    () => localStorage.getItem(AGENT_KEY) || 'lily'
  )
  const taRef = useRef(null)
  const endRef = useRef(null)
  const fileRef = useRef(null)

  const agentConfig = AGENTS[activeAgent]

  const switchAgent = useCallback((id) => {
    setActiveAgent(id)
    localStorage.setItem(AGENT_KEY, id)
  }, [])

  const resolvedTheme = settings.theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : settings.theme

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, steps])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', resolvedTheme)
    document.documentElement.setAttribute('data-font-size', settings.fontSize)
  }, [resolvedTheme, settings.fontSize])

  useEffect(() => {
    const handleKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        startNewChat()
        taRef.current?.focus()
      }
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault()
        setSettingsOpen(true)
      }
      if (e.key === 'Escape') {
        if (settingsOpen) { setSettingsOpen(false); return }
        taRef.current?.blur()
        setSidebarOpen(false)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [settingsOpen])

  const clearAllSessions = () => {
    setSessions([])
    saveSessions([])
    startNewChat()
  }

  const persistSession = (id, msgs, agent) => {
    setSessions((prev) => {
      const existing = prev.find((s) => s.id === id)
      const updated = existing
        ? { ...existing, messages: msgs, title: sessionTitle(msgs), agent: agent || existing.agent }
        : { id, messages: msgs, title: sessionTitle(msgs), agent: agent || activeAgent }
      // Order the sidebar by most-recent activity: drop any existing copy and
      // prepend the updated one, so the conversation you just chatted in jumps
      // to the top — not frozen at its creation position.
      const next = [updated, ...prev.filter((s) => s.id !== id)]
      saveSessions(next)
      return next
    })
  }

  const startNewChat = () => {
    setMessages([])
    setActiveId(null)
    setInput('')
    setSteps([])
    setSidebarOpen(false)
  }

  const switchToSession = (session) => {
    if (loading) return
    setMessages(session.messages)
    setActiveId(session.id)
    if (session.agent) switchAgent(session.agent)
    setSteps([])
    setSidebarOpen(false)
  }

  const deleteSession = (e, id) => {
    e.stopPropagation()
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id)
      saveSessions(next)
      return next
    })
    if (activeId === id) startNewChat()
  }

  const autoGrow = (el) => {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  const handleFileUpload = async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch('http://localhost:8000/api/upload', {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
      const data = await res.json()
      const prefix = input ? input + '\n\n' : ''
      setInput(prefix + `[Uploaded file: ${data.filename} — path: ${data.path}]`)
    } catch (err) {
      setInput((prev) => prev + `\n\n[File upload failed: ${err.message}]`)
    }
  }

  const onFileDrop = (e) => {
    e.preventDefault()
    const file = e.dataTransfer?.files?.[0]
    if (file) handleFileUpload(file)
  }

  const onFilePick = (e) => {
    const file = e.target?.files?.[0]
    if (file) handleFileUpload(file)
    if (fileRef.current) fileRef.current.value = ''
  }

  /* ── Hand off to Dash ─────────────────────────────── */
  const handoffToDash = async (analysisText) => {
    switchAgent('dash')
    const chatId = crypto.randomUUID()
    setActiveId(chatId)
    setInput('')
    setSteps([])
    setLoading(true)
    // Distill Lily's full analysis into a tight brief server-side (a cheap Haiku
    // pass) rather than dumping her whole markdown into Dash. Falls back to the
    // raw analysis if distillation is unavailable, so handoff never hard-fails.
    let briefText
    try {
      const res = await fetch('http://localhost:8000/api/dash/handoff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis: analysisText }),
      })
      if (!res.ok) throw new Error(`Server responded ${res.status}`)
      briefText = (await res.json()).first_message
    } catch (e) {
      briefText = `**Handoff from Lily** — here's the analysis to build from:\n\n${analysisText}`
    }
    const firstMsg = { role: 'user', content: briefText, ts: Date.now() }
    setMessages([firstMsg])
    persistSession(chatId, [firstMsg], 'dash')
    setLoading(false)
    sendWithMessages([firstMsg], chatId, 'dash')
  }

  /* ── Handle ask_planner response ───────────────── */
  const handlePlannerChoice = (choices) => {
    const choiceText = choices.length === 1
      ? `I'll go with: ${choices[0]}`
      : `I'll go with: ${choices.join(', ')}`
    setInput(choiceText)
    setTimeout(() => {
      const text = choiceText
      const chatId = activeId || crypto.randomUUID()
      if (!activeId) setActiveId(chatId)
      const history = [...messages, { role: 'user', content: text, ts: Date.now() }]
      setMessages(history)
      persistSession(chatId, history)
      setInput('')
      sendWithMessages(history, chatId, activeAgent)
    }, 50)
  }

  /* ── Core send logic (shared) ───────────────────── */
  const sendWithMessages = async (history, chatId, agent) => {
    const apiHistory = history.map(({ role, content }) => ({ role, content }))
    const url = AGENTS[agent].streamUrl
    setLoading(true)
    setSteps([])
    setNarration('')

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: apiHistory, session_id: chatId }),
      })
      if (!res.ok) throw new Error(`Server responded ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let liveSteps = []
      let liveNarration = ''
      let reply = null
      let usage = null
      let askPlanner = null
      let files = []
      let kofiTraces = []

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop()
        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const event = JSON.parse(line.slice(5))
          if (event.type === 'tool_call') {
            liveSteps = [...liveSteps, stepLabel(event, agent)]
            setSteps(liveSteps)
          } else if (event.type === 'narration') {
            liveNarration = liveNarration ? `${liveNarration}\n\n${event.text}` : event.text
            setNarration(liveNarration)
          } else if (event.type === 'reply') {
            reply = event.text
          } else if (event.type === 'usage') {
            usage = event
          } else if (event.type === 'error') {
            reply = `⚠️ Error: ${event.message}`
          } else if (event.type === 'ask_planner') {
            askPlanner = event
          } else if (event.type === 'file_ready') {
            files = [...files, event]
          } else if (event.type === 'kofi_activity') {
            kofiTraces = [...kofiTraces, event.trace]
          }
        }
      }

      const updated = [
        ...history,
        {
          role: 'assistant',
          content: reply || (askPlanner ? '' : '⚠️ The stream ended without a reply.'),
          steps: liveSteps,
          usage,
          askPlanner,
          files,
          kofiTraces,
          agent,
          ts: Date.now(),
        },
      ]
      setMessages(updated)
      persistSession(chatId, updated, agent)
    } catch (err) {
      const updated = [
        ...history,
        {
          role: 'assistant',
          content:
            `⚠️ Couldn't reach the backend (${err.message}). ` +
            'Make sure the API is running: uvicorn server:app --reload --port 8000',
          isError: true,
          agent,
          ts: Date.now(),
        },
      ]
      setMessages(updated)
      persistSession(chatId, updated, agent)
    } finally {
      setLoading(false)
      setSteps([])
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    const chatId = activeId || crypto.randomUUID()
    if (!activeId) setActiveId(chatId)

    const history = [...messages, { role: 'user', content: text, ts: Date.now() }]
    setMessages(history)
    persistSession(chatId, history)
    setInput('')
    if (taRef.current) taRef.current.style.height = 'auto'
    sendWithMessages(history, chatId, activeAgent)
  }

  const retry = () => {
    const lastUserIdx = [...messages].reverse().findIndex((m) => m.role === 'user')
    if (lastUserIdx === -1) return
    const idx = messages.length - 1 - lastUserIdx
    const lastUserMsg = messages[idx]
    setMessages(messages.slice(0, idx))
    setInput(lastUserMsg.content)
    setTimeout(() => {
      setInput(lastUserMsg.content)
      send()
    }, 50)
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const AgentIcon = agentConfig.icon

  const composer = (
    <div className="composer-wrap" onDrop={onFileDrop} onDragOver={(e) => e.preventDefault()}>
      <div className="composer">
        <textarea
          ref={taRef}
          rows={1}
          placeholder={agentConfig.placeholder}
          value={input}
          onChange={(e) => { setInput(e.target.value); autoGrow(e.target) }}
          onKeyDown={onKey}
          aria-label="Message input"
        />
        <div className="composer-bar">
          <div className="composer-bar-left">
            <AgentSwitcher agent={activeAgent} onChange={switchAgent} disabled={loading} />
            {activeAgent === 'dash' && (
              <>
                <button className="attach-btn" onClick={() => fileRef.current?.click()} aria-label="Attach file">
                  <AttachIcon />
                </button>
                <input ref={fileRef} type="file" style={{ display: 'none' }} onChange={onFilePick} />
              </>
            )}
          </div>
          <button className="send-btn" onClick={send} disabled={!input.trim() || loading} aria-label="Send message">
            <Send />
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="app">
      {sidebarOpen && <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />}
      <aside className={`sidebar${sidebarOpen ? ' open' : ''}`}>
        <div className="brand"><AgentIcon /> {agentConfig.name}</div>

        <button className="new-chat" onClick={startNewChat} aria-label="New chat">
          <Plus /> New chat
        </button>

        <nav className="nav">
          {Object.values(AGENTS).map((a) => (
            <button
              key={a.id}
              className={`nav-item${activeAgent === a.id && messages.length === 0 ? ' active-agent' : ''}`}
              onClick={() => { switchAgent(a.id); startNewChat() }}
            >
              <a.icon size={16} /> {a.name}
            </button>
          ))}
        </nav>

        {sessions.length > 0 && (
          <>
            <div className="section-label">Recents</div>
            <div className="chat-list">
              {sessions.map((s) => (
                <button
                  key={s.id}
                  className={`chat-list-item${s.id === activeId ? ' active' : ''}`}
                  onClick={() => switchToSession(s)}
                >
                  <span className="chat-list-agent-dot" data-agent={s.agent || 'lily'} />
                  <span className="chat-list-title">{s.title}</span>
                  <span className="chat-list-delete" onClick={(e) => deleteSession(e, s.id)} aria-label="Delete chat">{'×'}</span>
                </button>
              ))}
            </div>
          </>
        )}

        <div className="sidebar-footer">
          <button className="sidebar-settings-btn" onClick={() => setSettingsOpen(true)} aria-label="Open settings">
            <GearIcon /> Settings
          </button>
          <div className="user-row">
            <div className="avatar">{settings.avatarInitial}</div>
            <div className="user-meta">
              <div className="name">{settings.displayName}</div>
              <div className="plan">{settings.role}</div>
            </div>
          </div>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <button className="menu-btn" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Toggle sidebar">
            <MenuIcon />
          </button>
          <span className="topbar-title">{agentConfig.name}</span>
        </div>

        {messages.length === 0 ? (
          <div className="welcome">
            <div className="greeting"><AgentIcon size={32} /> Good morning, {settings.displayName}</div>
            {composer}
            <div className="quick-actions">
              {agentConfig.quickActions.map((q) => (
                <button key={q} className="quick-action"
                        onClick={() => setInput(q)}>{q}</button>
              ))}
            </div>
            <div className="shortcut-hint">
              <kbd>{navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}</kbd>+<kbd>K</kbd> new chat
            </div>
          </div>
        ) : (
          <>
            <div className="conversation" role="log" aria-live="polite">
              <div className="thread">
                {messages.map((m, i) => {
                  const msgAgent = m.agent || activeAgent
                  const MsgIcon = AGENTS[msgAgent]?.icon || Leaf
                  const msgName = AGENTS[msgAgent]?.name || 'Lily'
                  return (
                    <div key={i} className={`msg ${m.role}`}>
                      {m.role === 'user' ? (
                        <>
                          <div className="bubble">{m.content}</div>
                          {m.ts && <div className="timestamp">{timeAgo(m.ts)}</div>}
                        </>
                      ) : (
                        <>
                          <div className="msg-header">
                            <div className="lily-avatar"><MsgIcon size={16} /></div>
                            <div className="role">{msgName}</div>
                            {m.ts && <div className="timestamp">{timeAgo(m.ts)}</div>}
                          </div>
                          <CollapsibleSteps steps={m.steps} />
                          <KofiActivity traces={m.kofiTraces} />
                          {m.content && (
                            <div className="body markdown-body">
                              <Markdown remarkPlugins={[remarkGfm]}>{m.content}</Markdown>
                            </div>
                          )}
                          {/* File download cards */}
                          {m.files && m.files.length > 0 && (
                            <div className="file-cards">
                              {m.files.map((f, j) => (
                                <FileCard key={j} filename={f.filename} display={f.display} />
                              ))}
                            </div>
                          )}
                          {/* Ask planner choice cards */}
                          {m.askPlanner && (
                            <AskPlannerCards
                              data={m.askPlanner}
                              onSelect={handlePlannerChoice}
                              disabled={loading || i !== messages.length - 1}
                            />
                          )}
                          <div className="msg-actions">
                            <CopyButton text={m.content} />
                            {m.isError && (
                              <button className="retry-btn" onClick={retry} aria-label="Retry">
                                <RetryIcon /> Retry
                              </button>
                            )}
                            {/* Hand off to Dash button */}
                            {msgAgent === 'lily' && m.content && !m.isError && !m.askPlanner && i === messages.length - 1 && !loading && (
                              <button className="handoff-btn" onClick={() => handoffToDash(m.content)}>
                                <HandoffIcon /> Hand off to Dash
                              </button>
                            )}
                          </div>
                          {m.usage && (
                            <div className="usage">
                              {m.usage.turns} step{m.usage.turns === 1 ? '' : 's'} {'·'}{' '}
                              {(m.usage.total_tokens / 1000).toFixed(1)}k tokens
                              {m.usage.cached_tokens > 0 && (
                                <> {' ('}{(m.usage.cached_tokens / 1000).toFixed(1)}k cached{')'}</>
                              )} {'·'}{' '}
                              ${m.usage.cost_usd.toFixed(3)}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  )
                })}
                {loading && (
                  <div className="msg assistant">
                    <div className="msg-header">
                      <div className="lily-avatar"><AgentIcon size={16} /></div>
                      <div className="role">{agentConfig.name}</div>
                    </div>
                    {narration && (
                      <div className="body markdown-body narration">
                        <Markdown remarkPlugins={[remarkGfm]}>{narration}</Markdown>
                      </div>
                    )}
                    {steps.length > 0 && (
                      <div className="steps">
                        {steps.map((s, j) => (
                          <div key={j} className="step">
                            <span className="tick">{j === steps.length - 1 ? '◌' : '✓'}</span> {s}
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="thinking"><span /><span /><span /></div>
                  </div>
                )}
                <div ref={endRef} />
              </div>
            </div>
            <div className="composer-docked">{composer}</div>
          </>
        )}
      </main>

      {settingsOpen && (
        <SettingsModal
          settings={settings}
          sessions={sessions}
          onSave={setSettings}
          onClose={() => setSettingsOpen(false)}
          onClearSessions={clearAllSessions}
        />
      )}
    </div>
  )
}
