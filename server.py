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
from agents.dash.dash import (
    run_dash_loop,
    format_handoff_message,
    extract_handoff_brief,
    DASH_SYSTEM_PROMPT,
)

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
    # Stable per-conversation id so Dash's build workspace persists across turns.
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str


# Overrides the CLI prompt's "call load_data first" workflow: in the web chat,
# Lily is conversational by default and only escalates to tools when the
# question genuinely needs data analysis.
CHAT_MODE_GUIDANCE = """

## Conversation mode (web chat)

You are chatting with a demand planner in a chat interface. Not every message
needs analysis:

- For greetings and small talk, reply in one short, warm line and stop — e.g.
  "Hey! What do you want to dig into?" You are talking to demand planners who
  already know what you do, so do NOT introduce yourself or list your
  capabilities unless they explicitly ask "what can you do". Never open with a
  bulleted rundown of your skills.
- For clarifications or anything answerable from the conversation so far — just
  reply naturally. Do NOT call tools for these.
- Only use your tools when the user's question actually requires looking at
  the data (a SKU forecast evaluation, a demand-vs-budget check, inventory
  coverage, product economics, or a top-SKUs ranking). Then dig as deep as
  you need to.
- You are ALREADY oriented: the data landscape (regions, the "now" period,
  fiscal calendar, which streams exist, the forecast horizon) is in your system
  context below. Do NOT call get_overview to explore — go straight to the
  SKU/period tools for the question. Only call get_overview if you genuinely
  need an exact current count, and never as a routine first step.
- For quick factual lookups, one or two tool calls may be enough — you don't
  need the full structured recommendation block unless the user asks for a
  forecast evaluation or recommendation.
- If it's unclear whether the user wants a full analysis, ask a short
  clarifying question instead of launching one.
- **Narrate before slow tools — especially Kofi.** When you dispatch
  `external_research` (Kofi does live web search and takes a while), FIRST write
  one short, natural line in the same turn before the tool call — e.g. "Got it —
  I'll send Kofi to dig into the houseplant-care market while I pull the actuals
  history." This shows the planner what's happening instead of a silent spinner.
  Keep it to a sentence; then make the call. A brief heads-up before any
  multi-step tool run is welcome, but never skip it for Kofi.
"""


_LANDSCAPE_CACHE: str | None = None


def _data_landscape() -> str:
    """A compact, cached snapshot of what's in the warehouse, injected into the
    system prompt so Lily starts ALREADY oriented and doesn't burn her first step
    re-discovering the data with get_overview on every question. Computed once per
    process — the metadata (regions, the 'now' period, fiscal calendar, which
    streams exist) is effectively static."""
    global _LANDSCAPE_CACHE
    if _LANDSCAPE_CACHE is not None:
        return _LANDSCAPE_CACHE
    try:
        from agents.lily import tools as _t
        ov = _t.get_overview()
        streams = ", ".join(k for k, v in ov["streams_available"].items() if v)
        _LANDSCAPE_CACHE = (
            "\n\n## The data you already have (you are oriented — do NOT call get_overview to explore)\n"
            "- Regions (sales_org code = region). Use these EXACT mappings, never guess:\n"
            "    1010 = Germany | 1110 = UK | 1210 = France | 1810 = Poland |\n"
            "    1910 = Austria | 2510 = Benelux | 3010 = Australia | 3710 = Pokon\n"
            "- **WORK IN ONE REGION BY DEFAULT.** A demand planner owns a single region, so when a\n"
            "  region is named (e.g. \"how is HomePest in the UK?\"), pass that sales_org to EVERY\n"
            "  tool — family_scan, divergence_scan, and the per-SKU tools all take sales_org. Never\n"
            "  return global/cross-region numbers when a region was asked. Go cross-region only if\n"
            "  the user explicitly asks to compare regions.\n"
            "- **Product hierarchy = L1 division > L2 category > L3 > L4 > SKU.** For any category /\n"
            "  product-family question use hierarchy_view (pre-aggregated) — NEVER loop SKUs. Default\n"
            "  lens is **level 2**, and SAY which level you're showing (e.g. \"showing the level-2\n"
            "  sub-categories\"). When they ask specifically about sub-categories, drill one more to\n"
            "  **level 3**. Always state the level; honour any explicit level the user names.\n"
            "  - hierarchy_view gives a node's HEADLINE + its children. To go DEEPER on one node\n"
            "    use the category-level tools (the node equivalents of the per-SKU tools):\n"
            "    **node_detail(sales_org, node, aspect)** — aspect = forecast | economics | inventory |\n"
            "    timeseries (actuals + lag-2 bias per period) | revision (change vs the last vintage);\n"
            "    and **node_sku_scan(sales_org, node)** — every SKU inside the node with budget gap,\n"
            "    revenue, YoY, accuracy/bias AND inventory together. Reach for these for \"how has this\n"
            "    category's forecast trended / what's its margin / which SKUs inside it are off\".\n"
            "  - **Customer tools** — the same lift at customer grain:\n"
            "    **customer_scan(sales_org, node?)** — triage: which customers matter (region-wide or\n"
            "    within a node)? One row per customer with demand, budget gap, revenue, YoY, accuracy.\n"
            "    **customer_detail(sales_org, customer_code, node?, aspect)** — aspect = forecast |\n"
            "    economics | timeseries | revision. No inventory (inventory has no customer dimension).\n"
            "    Use customer_scan first to find who to drill into, then customer_detail for the deep read.\n"
            "- Budget is loaded for Pokon (3710) and Benelux (2510) only; the other 6 regions have\n"
            "  no budget — say so plainly rather than implying a global gap.\n"
            f"- \"Now\" = the period after the latest closed actuals; latest closed is "
            f"{ov['latest_closed_actuals_period']}.\n"
            f"- Forward forecast horizon: {ov['forecast_horizon'][0]} to {ov['forecast_horizon'][1]} "
            f"(latest weekly vintage {ov['forecast_version_key']}).\n"
            f"- ~{ov['material_count']} materials (SKUs), ~{ov['customer_count']} customer groups.\n"
            f"- Streams available: {streams}.\n"
            f"- {ov['fiscal_calendar']}\n"
            "Go straight to the SKU/period tools for the question asked."
        )
    except Exception as exc:  # DB unreachable at prompt-build time — degrade gracefully
        _LANDSCAPE_CACHE = (
            "\n\n## Data landscape\nThe warehouse views are available; call get_overview once if "
            f"you need to orient. (live overview unavailable: {exc})"
        )
    return _LANDSCAPE_CACHE


def _system_blocks() -> list[dict[str, Any]]:
    """Base prompt + chat-mode guidance + a cached data-landscape snapshot, so Lily
    is oriented from the first token and skips the routine get_overview step."""
    return [
        {
            "type": "text",
            "text": LILY_SYSTEM_PROMPT + CHAT_MODE_GUIDANCE + _data_landscape(),
            "cache_control": {"type": "ephemeral"},
        }
    ]


@app.on_event("startup")
def _prewarm_landscape() -> None:
    """Build the data-landscape snapshot in the BACKGROUND at startup so the first
    question is fast — without blocking the server from accepting connections."""
    if _BACKEND == "anthropic":
        threading.Thread(target=lambda: _safe_prewarm(), daemon=True).start()


def _safe_prewarm() -> None:
    try:
        _data_landscape()
    except Exception:
        pass


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class TitleRequest(BaseModel):
    message: str


class TitleResponse(BaseModel):
    title: str


@app.post("/api/title", response_model=TitleResponse)
def generate_title(req: TitleRequest) -> TitleResponse:
    """Generate a short chat title from the first user message using Haiku."""
    text = req.message.strip()[:500]
    if not text:
        return TitleResponse(title="New chat")
    if _BACKEND != "anthropic" or not os.environ.get("ANTHROPIC_API_KEY"):
        words = text.split()
        return TitleResponse(title=" ".join(words[:6]) + ("…" if len(words) > 6 else ""))
    try:
        import anthropic
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            messages=[{"role": "user", "content": f"Generate a very short title (3-6 words, no quotes) for a chat that starts with this message:\n\n{text}"}],
        )
        title = resp.content[0].text.strip().strip('"').strip("'")
        return TitleResponse(title=title)
    except Exception:
        words = text.split()
        return TitleResponse(title=" ".join(words[:6]) + ("…" if len(words) > 6 else ""))


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
                    "cached_tokens": usage["cache_read_input_tokens"],
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

- For greetings and small talk, reply in one short line and stop. You are
  talking to demand planners who already know what you do, so do NOT introduce
  yourself or list your capabilities unless they explicitly ask. Never open
  with a bulleted rundown of your skills.
- If there's a handoff, acknowledge the context in a line or two, then ask ONE
  short plain-text question for what you still need (audience, format, emphasis).
  Don't propose an outline or force a multiple-choice card. Once they answer with
  enough to proceed, build straight away — no approval gate.
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
    # Lily's full analysis markdown. The server distills it into a tight brief.
    analysis: str


class HandoffResponse(BaseModel):
    first_message: str


@app.post("/api/dash/handoff", response_model=HandoffResponse)
def dash_handoff(req: HandoffRequest) -> HandoffResponse:
    """Distill Lily's analysis into a clean handoff brief — the opening message for
    a Dash chat. A cheap Haiku extraction pulls the recommendation, key findings,
    and numbers out of her full markdown so Dash gets signal, not a wall of text.
    The frontend calls this, then opens a Dash chat seeded with the returned brief."""
    usage = new_usage()
    brief = extract_handoff_brief(req.analysis, usage=usage)
    if _BACKEND == "anthropic" and usage["turns"] > 0:
        _record_spend(cost_usd(usage))
    return HandoffResponse(first_message=format_handoff_message(brief))


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
                usage=usage, session_id=req.session_id,
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
                    "cached_tokens": usage["cache_read_input_tokens"],
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
    """Download a file Dash generated (PPTX, PDF, or DOCX)."""
    from agents.dash.sandbox import OUTPUT_DIR
    # Guard against path traversal in the filename segment.
    path = (OUTPUT_DIR / filename).resolve()
    if OUTPUT_DIR.resolve() not in path.parents or not path.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    media = {
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), filename=filename, media_type=media)
