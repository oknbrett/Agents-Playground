"""Dash — report & presentation builder agent.

Dash takes a Lily handoff (or freeform user instructions) and builds polished
PPTX slide decks and PDF reports. He is a separate chat agent with his own
conversation — no database access, no data tools. He works entirely from text.

Two entry paths:
1. Lily handoff → new Dash chat pre-seeded with the handoff doc.
2. Direct start → user opens Dash and describes what they want.

Usage:
    # Standalone test
    python agents/dash/dash.py --handoff "SKU 10042N forecast review. RAISE rec, ..."
    python agents/dash/dash.py --prompt "Build a 3-slide deck summarising Q3 outlook"

Design doc: docs/DASH.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[2]))

import anthropic

from agents.dash import sandbox
from agents.shared import ASK_PLANNER_TOOL_DEF, ASK_PLANNER_TOOL_NAME, is_ask_planner_call

# ── Config ─────────────────────────────────────────────────────────────────────

DASH_MODEL = os.environ.get("DASH_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096
MAX_TOOL_TURNS = 15

# Distillation of Lily's full analysis into a tight handoff brief runs on a cheap
# model — it's pure extraction, not reasoning. Override with DASH_HANDOFF_MODEL.
HANDOFF_EXTRACT_MODEL = os.environ.get("DASH_HANDOFF_MODEL", "claude-haiku-4-5-20251001")

# ── System prompt ──────────────────────────────────────────────────────────────

DASH_SYSTEM_PROMPT = """You are Dash, a report and presentation builder for a \
demand planning team. Your teammate Lily analyses the internal numbers and \
produces forecast recommendations. Your job is to turn analysis into polished \
deliverables — PowerPoint decks (.pptx), PDF reports (.pdf), and Word documents \
(.docx) — that the planner can take straight into a meeting.

You build documents the way a skilled operator does: you READ a document skill, \
WRITE a build script, RUN it in your workspace, and the finished file is handed \
to the planner. You are not limited to fixed templates — you write the code.

## How you work

- You receive either a **Lily handoff document** (structured analysis with \
findings, numbers, and a recommendation) or **freeform instructions** from the \
planner describing what they want built.
- You have NO access to the database or Lily's data tools. You work entirely \
from the text you're given. If you need a number that isn't in the brief, ask \
the planner — don't invent it.
- **When a handoff arrives, do intake FIRST, in one turn.** Acknowledge the \
context in a line or two (show you understood the SKU and the recommendation), \
then ask ONE short question covering what you still need: who it's for, what \
format, and anything to emphasise. Keep it to a single plain-text question — \
not a chain of questions, not a forced multiple-choice card.
- **Then build as soon as you have enough.** Once the planner tells you the \
format and audience, go straight to building — do NOT re-confirm with an outline \
or an approval gate. Infer the format from their words: "deck"/"slides"/ \
"presentation" → .pptx; "report"/"memo"/"write-up"/"document" → .docx or .pdf; \
"PDF" → .pdf; "both" → build both. If they already specified everything up front \
("make me a 5-slide deck for Tuesday's review"), skip intake and just build.
- If the planner is vague AND the request genuinely forks (e.g. deck vs report, \
exec-summary vs detailed), THEN you may use `ask_planner`. Reserve it for real \
forks — never as a routine confirmation step.
- After building, offer to revise. The planner may want to tweak wording, \
reorder slides, add/remove content, or switch format.

## How you build — skills + code

You have a code workspace and the official Anthropic document skills (docx, pdf, \
pptx) vendored locally. The build loop:

1. **Read the right skill FIRST.** Call `read_skill` before writing any build \
code, and actually follow its guidance — especially the design rules.
   - New .pptx → `read_skill("pptx", "pptxgenjs.md")` (build with the `pptxgenjs` \
Node library). Also read `read_skill("pptx")` for the design/QA guidance.
   - New .docx → `read_skill("docx")` and follow "Creating New Documents" (build \
with the `docx` Node library, a.k.a. docx-js).
   - New .pdf → `read_skill("pdf", "reference.md")` (build with `reportlab` in \
Python, or the HTML→PDF route the skill describes).
2. **Write the build script** with `write_file` — `build.js` for the Node \
libraries, `build.py` for Python. Create files this way; do NOT paste code into \
shell heredocs (keep it OS-portable).
3. **Run it** with `run_bash`: `node build.js` or `python build.py`. The output \
document must be written into your workspace (current dir). Any .pptx/.pdf/.docx \
you produce is delivered to the planner automatically — you don't need a separate \
"send" step.
4. **Verify, don't assume.** If `run_bash` exits non-zero, READ the error and fix \
the script — never tell the planner a file is ready unless the run succeeded and \
the file was written. You can re-run as many times as needed.

### Environment
- Node libraries available: `pptxgenjs`, `docx`. Python libraries: `reportlab`, \
`pypdf`, `pdfplumber`, `python-docx`, `python-pptx`, `markdown`.
- The vendored skills live at `$DASH_SKILLS_DIR` (set in your shell). Their helper \
scripts are runnable, e.g. `python "$DASH_SKILLS_DIR/docx/scripts/office/validate.py" out.docx`.
- LibreOffice-based steps (rendering slides to images, editing existing templates, \
visual thumbnails) may NOT be installed in this environment. Stick to building \
from scratch with the code libraries; if a skill step needs `soffice`/`pdftoppm` \
and it isn't available, note it and continue rather than failing the build.

### Quality bar (apply the skill's design guidance)
- **Lead with the recommendation** — never bury the call on slide 8 / page 3.
- **Numbers front and centre** — revenue, growth %, WMAPE, bias, override %. Use \
big stat callouts, not dense paragraphs.
- **Don't make boring, generic documents.** Follow the skill's palette, \
typography, and layout advice. No plain title-and-bullets slides; no accent lines \
under titles (a hallmark of AI slop the pptx skill calls out).
- Default deck flow: title → situation → key findings → risk/opportunity → \
recommendation → next steps. Default report flow: exec summary → findings → \
supporting data → risks → recommendation → next steps. Adapt to fit.

## Communication style

Professional but direct. You're preparing materials for a planning review — \
be clear, concise, and confident. If the handoff is ambiguous, ask a short \
clarifying question rather than guessing.

## Uploaded files

The planner can drop files (Excel, CSV, images, PDFs, etc.) into the chat. \
When a message mentions an uploaded file, use `read_uploaded_file` to read it \
before building. For spreadsheets you get the first rows as JSON — enough to \
understand the structure and pull key numbers into slides/reports. For text/PDF \
you get the raw content.

## Asking the planner

When there are genuinely different directions to go — structure choices, format \
decisions, emphasis trade-offs — use `ask_planner` to present options as \
clickable cards instead of asking a long-form question. Don't overuse it; \
reserve it for real forks, not every minor detail.

**Important:** when you use `ask_planner`, ALWAYS write the full proposal in \
your message text FIRST — e.g. spell out the slide-by-slide outline — and only \
then call `ask_planner`. The card options are short labels (e.g. "Looks good, \
build it"); they cannot carry the outline themselves. An option that says \
"build it as outlined above" is meaningless if you never wrote the outline in \
your message. Never call `ask_planner` as your only output.
"""

# ── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "read_skill",
        "description": (
            "Read a vendored document skill for guidance before you build. Returns "
            "the skill's markdown. Read the relevant skill BEFORE writing build "
            "code and follow its design + workflow advice. skill is one of 'docx', "
            "'pdf', 'pptx'. file is an optional reference within the skill — e.g. "
            "pptx: 'pptxgenjs.md' (build from scratch), 'editing.md'; pdf: "
            "'reference.md', 'forms.md'. Omit file to get the top-level SKILL.md."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill": {"type": "string", "enum": ["docx", "pdf", "pptx"]},
                "file": {
                    "type": "string",
                    "description": "Optional reference file within the skill (e.g. 'pptxgenjs.md'). Omit for SKILL.md.",
                },
            },
            "required": ["skill"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write a file into your build workspace (e.g. 'build.js' or 'build.py'). "
            "Overwrites if it exists. Use this to create your build scripts rather "
            "than shell heredocs. Paths are relative to the workspace."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the workspace, e.g. 'build.js'."},
                "content": {"type": "string", "description": "Full file contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_bash",
        "description": (
            "Run a shell command in your build workspace and get back the exit code "
            "and output. Use it to run your build script (`node build.js` / "
            "`python build.py`) and skill helper scripts. Any .pptx/.pdf/.docx you "
            "produce in the workspace is delivered to the planner automatically. "
            "Create files with write_file, not heredocs, so commands stay portable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a file back from your workspace (e.g. to inspect generated output "
            "or re-check a script). Returns text content, truncated if large."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the workspace."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_uploaded_file",
        "description": (
            "Read a file the planner uploaded/dropped into the chat. For "
            "spreadsheets (.xlsx, .csv) returns the first rows as JSON so you "
            "can extract numbers. For text/markdown/JSON returns the raw content. "
            "For PDFs returns extracted text. Call this when the planner mentions "
            "an uploaded file and you need its content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path to the uploaded file (provided in the upload event).",
                },
                "max_rows": {
                    "type": "integer",
                    "description": "For spreadsheets: max rows to return (default 50).",
                },
            },
            "required": ["file_path"],
        },
    },
    ASK_PLANNER_TOOL_DEF,
]

# ── File reader ──────────────────────────────────────────────────────────────

def _read_uploaded_file(file_path: str, max_rows: int = 50) -> dict:
    """Read an uploaded file and return its content in a useful format."""
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}
    ext = p.suffix.lower()
    try:
        if ext in (".csv", ".tsv"):
            import pandas as pd
            sep = "\t" if ext == ".tsv" else ","
            df = pd.read_csv(p, sep=sep, nrows=max_rows)
            return {"type": "table", "columns": list(df.columns), "rows": df.to_dict("records"), "total_rows": len(df)}
        if ext in (".xlsx", ".xls"):
            import pandas as pd
            df = pd.read_excel(p, nrows=max_rows)
            return {"type": "table", "columns": list(df.columns), "rows": df.to_dict("records"), "total_rows": len(df)}
        if ext in (".txt", ".md", ".json"):
            text = p.read_text(errors="replace")[:20_000]
            return {"type": "text", "content": text, "truncated": len(p.read_text()) > 20_000}
        if ext == ".pdf":
            try:
                from reportlab.lib.utils import open_for_read  # noqa: F401
            except ImportError:
                pass
            return {"type": "binary", "note": f"PDF file ({p.stat().st_size} bytes). PDF text extraction not yet supported — ask the planner to paste key content."}
        return {"type": "binary", "note": f"File type {ext} ({p.stat().st_size} bytes). Cannot read directly — ask the planner to describe the content."}
    except Exception as exc:
        return {"error": str(exc)}


# ── Tool dispatch ────────────────────────────────────────────────────────────

def _dispatch_tool(name: str, inputs: dict, session_id: str) -> dict:
    """Route a Dash tool call. Sandbox tools are scoped to the conversation's
    workspace via session_id; skill/upload reads are stateless."""
    try:
        if name == "read_skill":
            return sandbox.read_skill(inputs["skill"], inputs.get("file"))
        if name == "write_file":
            return sandbox.write_file(session_id, inputs["path"], inputs["content"])
        if name == "run_bash":
            return sandbox.run_bash(session_id, inputs["command"])
        if name == "read_file":
            return sandbox.read_file(session_id, inputs["path"])
        if name == "read_uploaded_file":
            return _read_uploaded_file(inputs["file_path"], inputs.get("max_rows", 50))
        return {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        return {"error": str(exc), "tool": name, "inputs": inputs}


# ── System blocks ────────────────────────────────────────────────────────────

def _system_blocks() -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": DASH_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


# ── Agent loop ───────────────────────────────────────────────────────────────

def run_dash_loop(
    messages: list[dict[str, Any]],
    system: list[dict[str, Any]] | None = None,
    on_event: Any = None,
    usage: dict[str, int] | None = None,
    session_id: str | None = None,
) -> str:
    """Drive Dash's tool-calling loop. `session_id` scopes the build workspace to
    this conversation so Dash can iterate on files across turns."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    system = system or _system_blocks()
    session_id = session_id or uuid.uuid4().hex
    delivered: set[tuple[str, int]] = set()  # output artifacts already sent to the UI
    final_text = ""

    for turn in range(MAX_TOOL_TURNS):
        response = client.messages.create(
            model=DASH_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if usage is not None:
            from agents.lily.costing import add_usage
            add_usage(usage, response.usage)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            # Surface any text Dash wrote alongside his tool calls (e.g. "building
            # the deck now…") so the UI shows it before the build step streams.
            narration = "".join(
                b.text for b in response.content if getattr(b, "type", None) == "text"
            ).strip()
            if narration and on_event is not None:
                on_event({"type": "narration", "text": narration})

            # Check for ask_planner — if present, pause the loop and let the
            # frontend collect the planner's choice. The next call to run_dash_loop
            # will include the tool_result from the frontend.
            for block in response.content:
                if is_ask_planner_call(block):
                    if on_event is not None:
                        on_event({
                            "type": "ask_planner",
                            "tool_use_id": block.id,
                            "question": block.input.get("question", ""),
                            "options": block.input.get("options", []),
                            "allow_multi_select": block.input.get("allow_multi_select", False),
                        })
                    # Return the outline/preamble Dash wrote in the SAME turn as
                    # the card, so the frontend renders it above the options.
                    # Without this the options ("build it as outlined above")
                    # reference an outline the planner never sees. The stream
                    # ends here; the frontend resumes with the planner's choice.
                    return "".join(
                        b.text for b in response.content
                        if getattr(b, "type", None) == "text"
                    )

            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    if on_event is not None:
                        on_event({
                            "type": "tool_call",
                            "name": block.name,
                            "input": block.input,
                        })
                    result = _dispatch_tool(block.name, block.input, session_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            # Any finished document produced this turn is delivered to the planner.
            for out in sandbox.collect_new_outputs(session_id, delivered):
                if on_event is not None:
                    on_event({
                        "type": "file_ready",
                        "filename": out["filename"],
                        "display": out["display"],
                        "path": out["path"],
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        final_text = "".join(
            b.text for b in response.content
            if getattr(b, "type", None) == "text"
        )
        break

    return final_text


# ── Handoff helpers ──────────────────────────────────────────────────────────

HANDOFF_EXTRACT_PROMPT = """You distill a demand planner's forecast analysis into \
a tight handoff brief for a report-builder. You do NOT add, infer, or embellish — \
you only pull what's already in the text. Keep findings and numbers verbatim where \
you can; a builder will put them on slides, so accuracy matters more than polish.

Return ONLY a single JSON object, no prose before or after, in exactly this shape:

{
  "subject": "short title, e.g. 'SKU 10833 — Forecast Evaluation'",
  "recommendation": "the headline call, e.g. 'LOWER' or 'KEEP' — or '' if none stated",
  "confidence": "high | medium | low — or '' if not stated",
  "key_findings": ["3 to 6 of the most decision-relevant findings, each one short line"],
  "numbers": {"label": "value", "...": "..."},
  "suggested_deliverable": "what Lily proposed building, or '' if she didn't say"
}

Pick the 4-8 numbers that matter most (revenue, margin, growth %, WMAPE, bias, \
override %, budget gap, coverage). Use the planner's own figures exactly."""


def extract_handoff_brief(
    analysis_text: str, *, usage: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Distill Lily's full analysis into a structured handoff brief via a cheap
    extraction model. Pure extraction (no reasoning), so it runs on Haiku. If the
    API key is missing or the parse fails, falls back to a minimal brief that
    carries the raw analysis through, so a handoff never hard-fails."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    fallback = {
        "subject": "Handoff from Lily",
        "recommendation": "",
        "confidence": "",
        "key_findings": [],
        "numbers": {},
        "suggested_deliverable": "",
        "_raw": analysis_text.strip(),
    }
    if not api_key:
        return fallback

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=HANDOFF_EXTRACT_MODEL,
            max_tokens=1024,
            system=HANDOFF_EXTRACT_PROMPT,
            messages=[{"role": "user", "content": analysis_text.strip()}],
        )
        if usage is not None:
            from agents.lily.costing import add_usage
            add_usage(usage, response.usage)
        text = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        ).strip()
    except Exception:
        return fallback

    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            brief = json.loads(text[start : end + 1])
            # Defend against a model that drops fields.
            for k, v in fallback.items():
                brief.setdefault(k, v)
            return brief
        except Exception:
            pass
    return fallback


def format_handoff_message(handoff: dict[str, Any]) -> str:
    """Turn a structured Lily handoff dict into the opening message for a Dash chat.

    This is the clean brief Dash sees — not Lily's full markdown. Dash reads it,
    does a one-line intake, and builds. The closing line invites intake rather
    than forcing an outline-approval gate (that behaviour lives in the prompt)."""
    parts = ["**Handoff from Lily** — here's the analysis to build from:\n"]
    if handoff.get("subject"):
        parts.append(f"**Subject:** {handoff['subject']}")
    if handoff.get("recommendation"):
        parts.append(f"**Recommendation:** {handoff['recommendation']}"
                     + (f" (confidence: {handoff['confidence']})" if handoff.get("confidence") else ""))
    if handoff.get("key_findings"):
        parts.append("\n**Key findings:**")
        for f in handoff["key_findings"]:
            parts.append(f"- {f}")
    if handoff.get("numbers"):
        parts.append("\n**Key numbers:**")
        for k, v in handoff["numbers"].items():
            parts.append(f"- {k}: {v}")
    if handoff.get("suggested_deliverable"):
        parts.append(f"\n**Lily suggested:** {handoff['suggested_deliverable']}")
    # Fallback path: extraction failed, so pass the raw analysis through.
    if not handoff.get("key_findings") and not handoff.get("recommendation") and handoff.get("_raw"):
        parts.append(handoff["_raw"])
    return "\n".join(parts)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Dash — report & presentation builder")
    parser.add_argument("--handoff", default=None, help="Structured handoff JSON string or plain text from Lily.")
    parser.add_argument("--prompt", default=None, help="Freeform prompt (direct start, no handoff).")
    args = parser.parse_args()

    if not args.handoff and not args.prompt:
        parser.error("Provide --handoff or --prompt")

    if args.handoff:
        try:
            handoff_dict = json.loads(args.handoff)
            user_msg = format_handoff_message(handoff_dict)
        except json.JSONDecodeError:
            user_msg = f"Here's a handoff from Lily:\n\n{args.handoff}\n\nPlease propose an outline and build a deliverable."
    else:
        user_msg = args.prompt

    print("Dash is preparing your deliverable...\n")
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]

    def log_event(e):
        if e.get("type") == "tool_call":
            print(f"  🔧 {e['name']}(...)")
        elif e.get("type") == "file_ready":
            print(f"  📄 File ready: {e['path']}")

    reply = run_dash_loop(messages, on_event=log_event)
    print(reply)


if __name__ == "__main__":
    main()
