import { useState, useRef, useEffect } from 'react'
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

const QUICK_ACTIONS = [
  'Analyse a SKU',
  'Compare forecasts',
  'Find demand patterns',
  'Flag forecast bias',
]

const STORAGE_KEY = 'lily-chat-sessions'

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

const API_URL = 'http://localhost:8000/api/chat/stream'

function stepLabel({ name, input }) {
  const cust = input?.customer ? ` — ${input.customer}` : ''
  switch (name) {
    case 'load_data':
      return 'Loading the demand dataset'
    case 'get_sku_history':
      return `Reading history for ${input?.sku_id ?? 'SKU'}${cust}`
    case 'analyze_period_pattern':
      return `Checking period ${input?.period ?? '?'} across years for ${input?.sku_id ?? 'SKU'}${cust}`
    case 'compare_forecasts':
      return `Scoring forecast accuracy for ${input?.sku_id ?? 'SKU'} (${input?.year ?? '?'})${cust}`
    default:
      return name
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

export default function App() {
  const [sessions, setSessions] = useState(loadSessions)
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [steps, setSteps] = useState([])
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('lily-dark-mode')
    if (saved !== null) return saved === 'true'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })
  const taRef = useRef(null)
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, steps])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light')
    localStorage.setItem('lily-dark-mode', darkMode)
  }, [darkMode])

  useEffect(() => {
    const handleKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        startNewChat()
        taRef.current?.focus()
      }
      if (e.key === 'Escape') {
        taRef.current?.blur()
        setSidebarOpen(false)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [])

  const persistSession = (id, msgs) => {
    setSessions((prev) => {
      const existing = prev.find((s) => s.id === id)
      let next
      if (existing) {
        next = prev.map((s) => s.id === id ? { ...s, messages: msgs, title: sessionTitle(msgs) } : s)
      } else {
        next = [{ id, messages: msgs, title: sessionTitle(msgs) }, ...prev]
      }
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

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    const chatId = activeId || crypto.randomUUID()
    if (!activeId) setActiveId(chatId)

    const history = [...messages, { role: 'user', content: text, ts: Date.now() }]
    const apiHistory = history.map(({ role, content }) => ({ role, content }))
    setMessages(history)
    persistSession(chatId, history)
    setInput('')
    if (taRef.current) taRef.current.style.height = 'auto'
    setLoading(true)
    setSteps([])

    try {
      const res = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: apiHistory }),
      })
      if (!res.ok) throw new Error(`Server responded ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let liveSteps = []
      let reply = null
      let usage = null

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
            liveSteps = [...liveSteps, stepLabel(event)]
            setSteps(liveSteps)
          } else if (event.type === 'reply') {
            reply = event.text
          } else if (event.type === 'usage') {
            usage = event
          } else if (event.type === 'error') {
            reply = `⚠️ Lily hit an error: ${event.message}`
          }
        }
      }

      const updated = [
        ...history,
        {
          role: 'assistant',
          content: reply ?? '⚠️ The stream ended without a reply.',
          steps: liveSteps,
          usage,
          ts: Date.now(),
        },
      ]
      setMessages(updated)
      persistSession(chatId, updated)
    } catch (err) {
      const updated = [
        ...history,
        {
          role: 'assistant',
          content:
            `⚠️ Couldn't reach Lily's backend (${err.message}). ` +
            'Make sure the API is running: uvicorn server:app --reload --port 8000',
          isError: true,
          ts: Date.now(),
        },
      ]
      setMessages(updated)
      persistSession(chatId, updated)
    } finally {
      setLoading(false)
      setSteps([])
    }
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

  const composer = (
    <div className="composer-wrap">
      <div className="composer">
        <textarea
          ref={taRef}
          rows={1}
          placeholder="Ask Lily about a SKU, forecast, or demand pattern…"
          value={input}
          onChange={(e) => { setInput(e.target.value); autoGrow(e.target) }}
          onKeyDown={onKey}
          aria-label="Message input"
        />
        <div className="composer-bar">
          <span className="model-pill">Lily · Claude Sonnet 4.6</span>
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
        <div className="brand"><Leaf /> Lily</div>

        <button className="new-chat" onClick={startNewChat} aria-label="New chat">
          <Plus /> New chat
        </button>

        <nav className="nav">
          <button className="nav-item">SKUs</button>
          <button className="nav-item">Saved analyses</button>
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
                  <span className="chat-list-title">{s.title}</span>
                  <span className="chat-list-delete" onClick={(e) => deleteSession(e, s.id)} aria-label="Delete chat">{'×'}</span>
                </button>
              ))}
            </div>
          </>
        )}

        <div className="sidebar-footer">
          <button className="theme-toggle" onClick={() => setDarkMode(!darkMode)} aria-label="Toggle dark mode">
            {darkMode ? '☀️' : '☽'}
          </button>
          <div className="user-row">
            <div className="avatar">B</div>
            <div className="user-meta">
              <div className="name">Brett</div>
              <div className="plan">Demand Planning</div>
            </div>
          </div>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <button className="menu-btn" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Toggle sidebar">
            <MenuIcon />
          </button>
          <span className="topbar-title">Lily</span>
        </div>

        {messages.length === 0 ? (
          <div className="welcome">
            <div className="greeting"><Leaf size={32} /> Good morning, Brett</div>
            {composer}
            <div className="quick-actions">
              {QUICK_ACTIONS.map((q) => (
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
                {messages.map((m, i) => (
                  <div key={i} className={`msg ${m.role}`}>
                    {m.role === 'user' ? (
                      <>
                        <div className="bubble">{m.content}</div>
                        {m.ts && <div className="timestamp">{timeAgo(m.ts)}</div>}
                      </>
                    ) : (
                      <>
                        <div className="msg-header">
                          <div className="lily-avatar"><Leaf size={16} /></div>
                          <div className="role">Lily</div>
                          {m.ts && <div className="timestamp">{timeAgo(m.ts)}</div>}
                        </div>
                        <CollapsibleSteps steps={m.steps} />
                        <div className="body markdown-body">
                          <Markdown remarkPlugins={[remarkGfm]}>{m.content}</Markdown>
                        </div>
                        <div className="msg-actions">
                          <CopyButton text={m.content} />
                          {m.isError && (
                            <button className="retry-btn" onClick={retry} aria-label="Retry">
                              <RetryIcon /> Retry
                            </button>
                          )}
                        </div>
                        {m.usage && (
                          <div className="usage">
                            {m.usage.turns} step{m.usage.turns === 1 ? '' : 's'} {'·'}{' '}
                            {(m.usage.total_tokens / 1000).toFixed(1)}k tokens {'·'}{' '}
                            ${m.usage.cost_usd.toFixed(3)}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}
                {loading && (
                  <div className="msg assistant">
                    <div className="msg-header">
                      <div className="lily-avatar"><Leaf size={16} /></div>
                      <div className="role">Lily</div>
                    </div>
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
    </div>
  )
}
