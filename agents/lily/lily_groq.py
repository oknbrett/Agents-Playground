"""Lily — demand planning reasoning agent (Groq / Llama 3.3 70B).

Same reasoning logic, system prompt, and tools as lily.py but runs on
Groq's free API using Llama 3.3 70B. Zero cost, no local hardware needed.

Required environment variable:
    GROQ_API_KEY  — get a free key at https://console.groq.com

Usage:
    python agents/lily/lily_groq.py --sku SKU001
    python agents/lily/lily_groq.py --sku all
    python agents/lily/lily_groq.py --sku SKU006 --customer Carrefour
    python agents/lily/lily_groq.py --file path/to/custom.xlsx --sku SKU001
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[2]))

from groq import Groq

from agents.lily.lily import (
    LILY_SYSTEM_PROMPT,
    TOOL_DEFINITIONS,
    DEFAULT_DATA_FILE,
    _build_user_message,
    _dispatch_tool,
)

# ── Constants ─────────────────────────────────────────────────────────────────

LOOP_MODEL = "llama-3.3-70b-versatile"
MAX_TOKENS = 4096
MAX_TOOL_TURNS = 20

# ── Convert Anthropic tool format → OpenAI tool format ────────────────────────
# Anthropic uses "input_schema"; OpenAI/Groq uses "parameters" — same JSON Schema.

def _to_openai_tools(anthropic_tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in anthropic_tools
    ]


OPENAI_TOOL_DEFINITIONS = _to_openai_tools(TOOL_DEFINITIONS)

# ── Agentic loop ───────────────────────────────────────────────────────────────

def _get_client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set.\n"
            "Get a free key at https://console.groq.com and run:\n"
            "  export GROQ_API_KEY=your_key"
        )
    return Groq(api_key=api_key)


def run_agent_loop(
    messages: list[Any],
    system: list[dict] | None = None,
    on_event: Any = None,
    usage: dict | None = None,  # ignored — Groq is free
) -> str:
    """Drive the tool-calling loop over an existing message history.

    Drop-in replacement for lily.run_agent_loop so server.py can use either
    backend. `system` accepts Anthropic-style blocks (list of {"type","text",...})
    or None (falls back to LILY_SYSTEM_PROMPT). `usage` is accepted but ignored
    since Groq has no token cost.
    """
    client = _get_client()

    # Extract plain text from Anthropic-style system blocks if provided
    if system:
        system_text = "".join(b.get("text", "") for b in system if b.get("type") == "text")
    else:
        system_text = LILY_SYSTEM_PROMPT

    full_messages: list[Any] = [{"role": "system", "content": system_text}] + list(messages)
    final_text = ""

    for _turn in range(MAX_TOOL_TURNS):
        response = client.chat.completions.create(
            model=LOOP_MODEL,
            max_tokens=MAX_TOKENS,
            tools=OPENAI_TOOL_DEFINITIONS,
            messages=full_messages,
        )

        choice = response.choices[0]
        full_messages.append(choice.message)

        if choice.finish_reason == "tool_calls":
            for tool_call in choice.message.tool_calls:
                inputs = json.loads(tool_call.function.arguments)
                if on_event is not None:
                    on_event({
                        "type": "tool_call",
                        "name": tool_call.function.name,
                        "input": inputs,
                    })
                result = _dispatch_tool(tool_call.function.name, inputs)
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })
            continue

        final_text = choice.message.content or ""
        break

    return final_text


def run_lily(user_message: str) -> str:
    """Run the agent loop from a single user message (CLI entry point)."""
    messages: list[Any] = [{"role": "user", "content": user_message}]
    return run_agent_loop(messages)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lily — demand planning reasoning agent (Groq / Llama 3.3 70B)"
    )
    parser.add_argument(
        "--sku",
        required=True,
        help="SKU to analyse (e.g. SKU001) or 'all' for all SKUs.",
    )
    parser.add_argument(
        "--customer",
        default=None,
        help="Optional: filter to one customer (e.g. Carrefour).",
    )
    parser.add_argument(
        "--file",
        default=DEFAULT_DATA_FILE,
        help="Path to the demand data file. Defaults to data/demand_data.xlsx.",
    )
    args = parser.parse_args()

    user_message = _build_user_message(args.sku, args.customer, args.file)

    print(f"Lily (Groq / {LOOP_MODEL}) is analysing {args.sku}"
          + (f" / {args.customer}" if args.customer else "")
          + " ...\n")

    result = run_lily(user_message)
    print(result)


if __name__ == "__main__":
    main()
