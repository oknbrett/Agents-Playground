"""Shared tool: ask_planner — structured choice prompt for agents.

When an agent (Lily or Dash) calls ask_planner, the loop pauses and emits
an SSE event. The frontend renders the choices as clickable cards. The user's
selection is sent back as a tool_result on the next request, and the loop
resumes.

This module provides the tool definition (for TOOL_DEFINITIONS) and the
sentinel that the agent loop checks to know it should pause.
"""

from __future__ import annotations

from typing import Any


ASK_PLANNER_TOOL_DEF: dict[str, Any] = {
    "name": "ask_planner",
    "description": (
        "Pause and ask the planner to choose a direction before you continue. "
        "Use this when there are genuinely different paths and the planner's "
        "preference matters — not for every decision. Present 2-4 clear options "
        "with short descriptions. You may mark one as recommended. The planner's "
        "choice comes back as your tool result; continue from there."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask, e.g. 'Which angle should I research first?'",
            },
            "options": {
                "type": "array",
                "description": "2-4 options for the planner to choose from.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Short option label (1-5 words).",
                        },
                        "description": {
                            "type": "string",
                            "description": "What this option means or what will happen.",
                        },
                        "recommended": {
                            "type": "boolean",
                            "description": "True if this is your recommended option (at most one).",
                        },
                    },
                    "required": ["label", "description"],
                },
                "minItems": 2,
                "maxItems": 4,
            },
            "allow_multi_select": {
                "type": "boolean",
                "description": "If true, the planner can pick more than one option. Default false.",
            },
        },
        "required": ["question", "options"],
    },
}


ASK_PLANNER_TOOL_NAME = "ask_planner"


def is_ask_planner_call(block: Any) -> bool:
    return getattr(block, "type", None) == "tool_use" and block.name == ASK_PLANNER_TOOL_NAME
