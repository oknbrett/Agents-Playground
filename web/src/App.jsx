import { useState, useRef, useEffect } from 'react'

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

const API_URL = 'http://localhost:8000/api/chat/stream'

/* Human-readable progress labels for Lily's tool calls */
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

export default function App() {
  const [sessions, setSessions] = useState(loadSessions)
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [steps, setSteps] = useState([])
  const taRef = useRef(null)
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, steps])

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
  }

  const switchToSession = (session) => {
    if (loading) return
    setMessages(session.messages)
    setActiveId(session.id)
    setSteps([])
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

    const history = [...messages, { role: 'user', content: text }]
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

      // Parse the SSE stream: lines of `data: {json}` separated by blank lines.
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
        buffer = parts.pop() // keep incomplete chunk
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
        },
      ]
      setMessages(updated)
      persistSession(chatId, updated)
    } finally {
      setLoading(false)
      setSteps([])
    }
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
        />
        <div className="composer-bar">
          <span className="model-pill">Lily · Claude Sonnet 4.6</span>
          <button className="send-btn" onClick={send} disabled={!input.trim() || loading}>
            <Send />
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><Leaf /> Lily</div>

        <button className="new-chat" onClick={startNewChat}>
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
                  <span className="chat-list-delete" onClick={(e) => deleteSession(e, s.id)}>×</span>
                </button>
              ))}
            </div>
          </>
        )}

        <div className="user-row">
          <div className="avatar">B</div>
          <div className="user-meta">
            <div className="name">Brett</div>
            <div className="plan">Demand Planning</div>
          </div>
        </div>
      </aside>

      <main className="main">
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
          </div>
        ) : (
          <>
            <div className="conversation">
              <div className="thread">
                {messages.map((m, i) => (
                  <div key={i} className={`msg ${m.role}`}>
                    {m.role === 'user' ? (
                      <div className="bubble">{m.content}</div>
                    ) : (
                      <>
                        <div className="role">Lily</div>
                        {m.steps?.length > 0 && (
                          <div className="steps done">
                            {m.steps.map((s, j) => (
                              <div key={j} className="step"><span className="tick">✓</span> {s}</div>
                            ))}
                          </div>
                        )}
                        <div className="body">{m.content}</div>
                        {m.usage && (
                          <div className="usage">
                            {m.usage.turns} step{m.usage.turns === 1 ? '' : 's'} ·{' '}
                            {(m.usage.total_tokens / 1000).toFixed(1)}k tokens ·{' '}
                            ${m.usage.cost_usd.toFixed(3)}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                ))}
                {loading && (
                  <div className="msg assistant">
                    <div className="role">Lily</div>
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
