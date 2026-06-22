"""Lily — demand planning reasoning agent (Cerebras, free 1M tokens/day).

Same reasoning logic, system prompt, and tools as lily.py, run on Cerebras's
OpenAI-compatible inference API. Free tier: ~1M tokens/day, 30 req/min — far
more headroom than Groq's 100K/day for extensive testing.

Default model is gpt-oss-120b (OpenAI's open model — strong at tool calling and
reasoning). Override with CEREBRAS_MODEL.

Required environment variable:
    CEREBRAS_API_KEY  — get a free key at https://cloud.cerebras.ai

Usage:
    python agents/lily/lily_cerebras.py --sku UNI40
    python agents/lily/lily_cerebras.py --sku all

Note: the free tier currently caps context at 8,192 tokens, so completions are
kept short and the loop is meant for single-SKU questions, not huge transcripts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[2]))

from openai import OpenAI

from agents.lily.lily import (
    LILY_SYSTEM_PROMPT,
    TOOL_DEFINITIONS,
    DEFAULT_DATA_FILE,
    _build_user_message,
    _dispatch_tool,
)

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://api.cerebras.ai/v1"
LOOP_MODEL = os.environ.get("CEREBRAS_MODEL", "gpt-oss-120b")
MAX_TOKENS = 2048           # leave room under the free tier's 8,192-token context cap
MAX_TOOL_TURNS = 20
TOOL_CALL_RETRIES = 3       # re-sample on malformed tool-call generations


# ── Anthropic tool format → OpenAI tool format (Cerebras is OpenAI-compatible) ──

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


def _get_client() -> OpenAI:
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "CEREBRAS_API_KEY is not set.\n"
            "Get a free key at https://cloud.cerebras.ai and add to .env:\n"
            "  CEREBRAS_API_KEY=your_key"
        )
    return OpenAI(api_key=api_key, base_url=BASE_URL)


def _create_with_retry(client: OpenAI, full_messages: list[Any]):
    """Call Cerebras, retrying transient 'tool_use_failed' formatting errors.

    The generation that failed isn't added to history, so re-sampling usually
    succeeds. Any other error is re-raised immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(TOOL_CALL_RETRIES):
        try:
            return client.chat.completions.create(
                model=LOOP_MODEL,
                max_tokens=MAX_TOKENS,
                temperature=0,
                tools=OPENAI_TOOL_DEFINITIONS,
                messages=full_messages,
            )
        except Exception as exc:
            if "tool_use_failed" not in str(exc) and "Failed to call a function" not in str(exc):
                raise
            last_exc = exc
            time.sleep(0.4 * (attempt + 1))
    raise last_exc


# ── Agentic loop ───────────────────────────────────────────────────────────────

def run_agent_loop(
    messages: list[Any],
    system: list[dict] | None = None,
    on_event: Any = None,
    usage: dict | None = None,  # ignored — Cerebras free tier has no token cost
) -> str:
    """Drive the tool-calling loop. Drop-in replacement for lily.run_agent_loop so
    server.py can use this backend interchangeably."""
    client = _get_client()

    if system:
        system_text = "".join(b.get("text", "") for b in system if b.get("type") == "text")
    else:
        system_text = LILY_SYSTEM_PROMPT

    full_messages: list[Any] = [{"role": "system", "content": system_text}] + list(messages)
    final_text = ""

    for _turn in range(MAX_TOOL_TURNS):
        response = _create_with_retry(client, full_messages)
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
    messages: list[Any] = [{"role": "user", "content": user_message}]
    return run_agent_loop(messages)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Lily — demand planning reasoning agent (Cerebras / {LOOP_MODEL})"
    )
    parser.add_argument("--sku", required=True, help="SKU/material to analyse, or 'all'.")
    parser.add_argument("--customer", default=None, help="Optional: filter to one customer code.")
    parser.add_argument("--file", default=DEFAULT_DATA_FILE, help="(unused; data is in the warehouse)")
    args = parser.parse_args()

    user_message = _build_user_message(args.sku, args.customer)
    print(f"Lily (Cerebras / {LOOP_MODEL}) is analysing {args.sku}"
          + (f" / {args.customer}" if args.customer else "") + " ...\n")
    print(run_lily(user_message))


if __name__ == "__main__":
    main()
