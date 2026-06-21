"""Lily web backend — a thin FastAPI wrapper around the Anthropic agent loop.

Exposes one endpoint, POST /api/chat, that the React frontend calls. It takes
the conversation so far (plain text turns), runs Lily's tool-calling loop, and
returns her final reply.

The agent loop, tools, and system prompt all live in agents/lily/lily.py — this
file only handles HTTP, CORS, and turning chat history into Anthropic messages.

Run:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=your_key        # PowerShell: $env:ANTHROPIC_API_KEY="..."
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import datetime
import json
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from agents.lily.lily import LILY_SYSTEM_PROMPT
from agents.dash.dash import run_dash_loop, format_handoff_message, DASH_SYSTEM_PROMPT

# .env (incl. GROQ_API_KEY) is loaded on import of the agents.lily package
# (see agents/lily/__init__.py), so it's already in os.environ here.

# Auto-select backend. A present ANTHROPIC_API_KEY is an explicit opt-in to the
# paid path. Otherwise prefer the free backends, biggest free budget first:
# Cerebras (~1M tokens/day) > Groq (100K/day).
if os.environ.get("ANTHROPIC_API_KEY"):
    from agents.lily.lily import run_agent_loop
    _BACKEND = "anthropic"
elif os.environ.get("CEREBRAS_API_KEY"):
    from agents.lily.lily_cerebras import run_agent_loop
    _BACKEND = "cerebras"
elif os.environ.get("GROQ_API_KEY"):
    from agents.lily.lily_groq import run_agent_loop
    _BACKEND = "groq"
else:
    from agents.lily.lily import run_agent_loop
    _BACKEND = "anthropic"

from agents.lily.costing import cost_usd, new_usage, total_tokens

# ── Spend guard ───────────────────────────────────────────────────────────────
# Hard daily budget so a chat session can't silently burn through API credit.
# Override with the LILY_DAILY_USD_CAP env var.

DAILY_USD_CAP = float(os.environ.get("LILY_DAILY_USD_CAP", "2.00"))
SPEND_FILE = Path(__file__).parent / ".lily_spend.json"
_spend_lock = threading.Lock()


def _load_spend() -> dict[str, Any]:
    today = datetime.date.today().isoformat()
    try:
        data = json.loads(SPEND_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if data.get("date") != today:
        data = {"date": today, "usd": 0.0, "requests": 0}
    return data


def _record_spend(usd: float) -> dict[str, Any]:
    with _spend_lock:
        data = _load_spend()
        data["usd"] += usd
        data["requests"] += 1
        SPEND_FILE.write_text(json.dumps(data))
        return data


def _budget_exceeded() -> bool:
    with _spend_lock:
        return _load_spend()["usd"] >= DAILY_USD_CAP

app = FastAPI(title="Lily API")

# The Vite dev server runs on a different port, so the browser needs CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:5183", "http://127.0.0.1:5183"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    reply: str


# Overrides the CLI prompt's "call load_data first" workflow: in the web chat,
# Lily is conversational by default and only escalates to tools when the
# question genuinely needs data analysis.
CHAT_MODE_GUIDANCE = """

## Conversation mode (web chat)

You are chatting with a demand planner in a chat interface. Not every message
needs analysis:

- For greetings, small talk, questions about what you can do, clarifications,
  or anything answerable from the conversation so far — just reply naturally.
  Do NOT call tools for these.
- Only use your tools when the user's question actually requires looking at
  the data (a SKU forecast evaluation, a demand-vs-budget check, inventory
  coverage, product economics, or a top-SKUs ranking). Then dig as deep as
  you need to.
- Call get_overview at most ONCE per conversation. Once you've seen the
  overview (regions, customers, materials, streams), you already have it —
  do not call it again; answer directly from what it returned. For example,
  to list the customers, read customer_codes from the overview you already have.
- For quick factual lookups, one or two tool calls may be enough — you don't
  need the full structured recommendation block unless the user asks for a
  forecast evaluation or recommendation.
- If it's unclear whether the user wants a full analysis, ask a short
  clarifying question instead of launching one.
"""


def _system_blocks() -> list[dict[str, Any]]:
    """Base prompt plus chat-mode guidance. Data now lives in the warehouse, so
    Lily orients herself with get_overview — no file path needed."""
    return [
        {
            "type": "text",
            "text": LILY_SYSTEM_PROMPT + CHAT_MODE_GUIDANCE,
            "cache_control": {"type": "ephemeral"},
        }
    ]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/usage")
def usage_today() -> dict[str, Any]:
    with _spend_lock:
        data = _load_spend()
    return {**data, "daily_cap_usd": DAILY_USD_CAP}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    # Stateless: the frontend sends the whole history each turn. Prior turns
    # come in as plain text; the current turn's tool calls are handled inside
    # run_agent_loop and never need to round-trip to the browser.
    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": m.content} for m in req.messages
    ]
    try:
        reply = run_agent_loop(messages, system=_system_blocks())
    except Exception as exc:  # surface the error to the UI instead of a 500 blob
        reply = f"⚠️ Lily hit an error: {exc}"
    return ChatResponse(reply=reply)


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Same as /api/chat, but emits server-sent events while Lily works:

        {"type": "tool_call", "name": ..., "input": ...}   one per tool call
        {"type": "reply", "text": ...}                     the final answer
        {"type": "error", "message": ...}

    The agent loop is synchronous, so it runs in a worker thread and hands
    events to the response generator through a queue.
    """
    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": m.content} for m in req.messages
    ]
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def work() -> None:
        if _budget_exceeded():
            events.put({
                "type": "error",
                "message": (
                    f"Daily budget of ${DAILY_USD_CAP:.2f} reached — Lily is "
                    "pausing until tomorrow. (Override with LILY_DAILY_USD_CAP.)"
                ),
            })
            events.put(None)
            return
        usage = new_usage()
        try:
            reply = run_agent_loop(
                messages, system=_system_blocks(), on_event=events.put,
                usage=usage,
            )
            events.put({"type": "reply", "text": reply})
        except Exception as exc:
            events.put({"type": "error", "message": str(exc)})
        finally:
            if _BACKEND == "anthropic" and usage["turns"] > 0:
                spent = cost_usd(usage)
                day = _record_spend(spent)
                events.put({
                    "type": "usage",
                    "turns": usage["turns"],
                    "total_tokens": total_tokens(usage),
                    "cost_usd": spent,
                    "today_usd": day["usd"],
                })
            events.put(None)  # sentinel: stream is done

    threading.Thread(target=work, daemon=True).start()

    def sse() -> Any:
        while True:
            event = events.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


# ── File upload (shared by Dash and future agents) ───────────────────────────

UPLOAD_DIR = Path(os.environ.get("DASH_UPLOAD_DIR", "/tmp/dash_uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".xlsx", ".xls", ".csv", ".tsv",
    ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".pdf", ".txt", ".md", ".json",
    ".pptx", ".docx",
}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, Any]:
    """Accept a file drop from the planner and store it for Dash to process."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        from fastapi import HTTPException
        raise HTTPException(400, f"Unsupported file type: {ext}")
    file_id = uuid.uuid4().hex[:12]
    safe_name = f"{file_id}_{file.filename}"
    dest = UPLOAD_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {
        "file_id": file_id,
        "filename": file.filename,
        "stored_as": safe_name,
        "path": str(dest),
        "size_bytes": len(content),
    }


# ── Dash endpoints ───────────────────────────────────────────────────────────

DASH_CHAT_MODE_GUIDANCE = """

## Conversation mode (web chat)

You are chatting with a demand planner in a chat interface. They may arrive
via a Lily handoff (the first message will contain Lily's analysis) or by
starting a conversation directly.

- If there's a handoff, acknowledge it and propose an outline before building.
- If they arrive directly, ask what they'd like built and from what information.
- After delivering a file, offer to revise or build a different format.
"""


def _dash_system_blocks() -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": DASH_SYSTEM_PROMPT + DASH_CHAT_MODE_GUIDANCE,
            "cache_control": {"type": "ephemeral"},
        }
    ]


class HandoffRequest(BaseModel):
    handoff: dict[str, Any]


class HandoffResponse(BaseModel):
    first_message: str


@app.post("/api/dash/handoff", response_model=HandoffResponse)
def dash_handoff(req: HandoffRequest) -> HandoffResponse:
    """Convert a structured Lily handoff into the opening message for a Dash chat.
    The frontend calls this, then starts a new Dash chat with the returned message."""
    return HandoffResponse(first_message=format_handoff_message(req.handoff))


@app.post("/api/dash/chat/stream")
def dash_chat_stream(req: ChatRequest) -> StreamingResponse:
    """Dash's streaming chat endpoint — same SSE contract as Lily's.
    Additionally emits {"type": "file_ready", "filename": ..., "path": ...}
    when a PPTX or PDF is generated."""
    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": m.content} for m in req.messages
    ]
    events: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def work() -> None:
        if _budget_exceeded():
            events.put({
                "type": "error",
                "message": (
                    f"Daily budget of ${DAILY_USD_CAP:.2f} reached — Dash is "
                    "pausing until tomorrow. (Override with LILY_DAILY_USD_CAP.)"
                ),
            })
            events.put(None)
            return
        usage = new_usage()
        try:
            reply = run_dash_loop(
                messages, system=_dash_system_blocks(), on_event=events.put,
                usage=usage,
            )
            events.put({"type": "reply", "text": reply})
        except Exception as exc:
            events.put({"type": "error", "message": str(exc)})
        finally:
            if usage["turns"] > 0:
                spent = cost_usd(usage)
                day = _record_spend(spent)
                events.put({
                    "type": "usage",
                    "turns": usage["turns"],
                    "total_tokens": total_tokens(usage),
                    "cost_usd": spent,
                    "today_usd": day["usd"],
                })
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def sse() -> Any:
        while True:
            event = events.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.get("/api/dash/download/{filename}")
def dash_download(filename: str) -> FileResponse:
    """Download a file Dash generated (PPTX or PDF)."""
    from agents.dash.build_pptx import OUTPUT_DIR
    path = OUTPUT_DIR / filename
    if not path.exists() or not path.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    media = "application/pdf" if filename.endswith(".pdf") else \
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return FileResponse(str(path), filename=filename, media_type=media)
