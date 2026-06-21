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
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[2]))

import anthropic

from agents.dash.build_pptx import build_pptx
from agents.dash.build_pdf import build_pdf

# ── Config ─────────────────────────────────────────────────────────────────────

DASH_MODEL = os.environ.get("DASH_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096
MAX_TOOL_TURNS = 15

# ── System prompt ──────────────────────────────────────────────────────────────

DASH_SYSTEM_PROMPT = """You are Dash, a report and presentation builder for a \
demand planning team. Your teammate Lily analyses the internal numbers and \
produces forecast recommendations. Your job is to turn analysis into polished \
deliverables — PPTX slide decks and PDF reports — that the planner can take \
straight into a meeting.

## How you work

- You receive either a **Lily handoff document** (structured analysis with \
findings, numbers, and a recommendation) or **freeform instructions** from the \
planner describing what they want built.
- You have NO access to the database or Lily's data tools. You work entirely \
from the text you're given. If you need more information, ask the planner.
- **Always confirm the structure** before building. Propose the outline (number \
of slides/sections, what goes on each) and ask if the planner wants to adjust. \
Don't build until they approve — unless they explicitly say "just build it."
- When building, use your tools: `create_pptx` for slide decks, `create_pdf` \
for written reports. You can build both in one conversation if asked.
- After building, offer to revise. The planner may want to tweak wording, \
reorder slides, add/remove content, or switch format.

## Slide deck principles

- **Less text, more signal.** Bullets, not paragraphs. One idea per slide.
- **Lead with the recommendation.** Don't bury the punchline on slide 8.
- **Numbers front and center.** Revenue, growth %, WMAPE, bias — the things \
that make someone act.
- **Consistent structure.** Title slide → situation → findings → risk/opp → \
recommendation → next steps. Adjust to fit, but default to this flow.

## PDF report principles

- **Executive summary up top.** The busy reader gets the headline in 2 sentences.
- **Sections with clear headings.** Findings, Supporting Data, Risks, \
Recommendation, Next Steps.
- **Bullet points over prose** where the content is a list of findings.

## Communication style

Professional but direct. You're preparing materials for a planning review — \
be clear, concise, and confident. If the handoff is ambiguous, ask a short \
clarifying question rather than guessing.
"""

# ── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "create_pptx",
        "description": (
            "Build a PowerPoint slide deck. Pass a list of slides, each with a "
            "layout type and content. Returns the filename to give the user. "
            "Layouts: 'title_slide' (title + subtitle), 'section' (section divider), "
            "'content' (heading + bullets list), 'two_column' (heading + left/right "
            "each with title + bullets)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slides": {
                    "type": "array",
                    "description": "List of slide specs.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "layout": {
                                "type": "string",
                                "enum": ["title_slide", "section", "content", "two_column"],
                                "description": "Slide layout type.",
                            },
                            "title": {"type": "string", "description": "For title_slide or section layout."},
                            "subtitle": {"type": "string", "description": "For title_slide layout."},
                            "heading": {"type": "string", "description": "For content or two_column layout."},
                            "bullets": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Bullet points for content layout.",
                            },
                            "left": {
                                "type": "object",
                                "description": "Left column for two_column layout.",
                                "properties": {
                                    "title": {"type": "string"},
                                    "bullets": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                            "right": {
                                "type": "object",
                                "description": "Right column for two_column layout.",
                                "properties": {
                                    "title": {"type": "string"},
                                    "bullets": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                        "required": ["layout"],
                    },
                },
                "filename": {
                    "type": "string",
                    "description": "Optional output filename (without path). Defaults to an auto-generated name.",
                },
            },
            "required": ["slides"],
        },
    },
    {
        "name": "create_pdf",
        "description": (
            "Build a PDF report. Pass a list of sections, each with a type and "
            "content. Returns the filename to give the user. Section types: "
            "'heading', 'subheading', 'body' (paragraph text), 'bullet_list' "
            "(items array), 'spacer', 'hr'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Report title, displayed at the top of the first page.",
                },
                "sections": {
                    "type": "array",
                    "description": "List of section specs.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["heading", "subheading", "body", "bullet_list", "spacer", "hr"],
                                "description": "Section type.",
                            },
                            "text": {"type": "string", "description": "Text content (for heading, subheading, body)."},
                            "items": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Bullet items (for bullet_list type).",
                            },
                            "height_mm": {"type": "number", "description": "Height in mm (for spacer type, default 8)."},
                        },
                        "required": ["type"],
                    },
                },
                "filename": {
                    "type": "string",
                    "description": "Optional output filename (without path). Defaults to an auto-generated name.",
                },
            },
            "required": ["sections"],
        },
    },
]

# ── Tool dispatch ────────────────────────────────────────────────────────────

TOOL_DISPATCH: dict[str, Any] = {
    "create_pptx": lambda **kw: build_pptx(kw.pop("slides"), kw.get("filename")),
    "create_pdf": lambda **kw: build_pdf(kw.pop("sections"), kw.get("filename"), kw.get("title")),
}


def _dispatch_tool(name: str, inputs: dict) -> dict:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**inputs)
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
) -> str:
    """Drive Dash's tool-calling loop. Same interface as Lily's run_agent_loop."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    system = system or _system_blocks()
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
            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    if on_event is not None:
                        on_event({
                            "type": "tool_call",
                            "name": block.name,
                            "input": block.input,
                        })
                    result = _dispatch_tool(block.name, block.input)
                    if on_event is not None and "path" in result:
                        on_event({
                            "type": "file_ready",
                            "filename": result.get("filename", ""),
                            "path": result.get("path", ""),
                        })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
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

def format_handoff_message(handoff: dict[str, Any]) -> str:
    """Turn a structured Lily handoff dict into the opening message for a Dash chat."""
    parts = ["Here's a handoff from Lily for you to build into a deliverable:\n"]
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
        parts.append(f"\n**Suggested deliverable:** {handoff['suggested_deliverable']}")
    parts.append("\nPlease propose an outline, then build it once I approve.")
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
