"""Lily — demand planning reasoning agent.

Reads a demand planning dataset and produces evidence-based recommendations
on whether a demand planner should RAISE, LOWER, KEEP, or flag a forecast
as UNCERTAIN. Lily never modifies data — she is read-only.

Usage:
    python agents/lily/lily.py --sku SKU001
    python agents/lily/lily.py --sku all
    python agents/lily/lily.py --sku SKU006 --customer Carrefour
    python agents/lily/lily.py --file path/to/custom.xlsx --sku SKU001
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Allow running from repo root: python agents/lily/lily.py
sys.path.insert(0, str(Path(__file__).parents[2]))

import anthropic

from agents.lily import tools as tools_module

# ── Constants ─────────────────────────────────────────────────────────────────

LOOP_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
MAX_TOOL_TURNS = 20

DEFAULT_DATA_FILE = str(Path(__file__).parents[2] / "data" / "demand_data.xlsx")

# ── System prompt ─────────────────────────────────────────────────────────────

LILY_SYSTEM_PROMPT = """You are Lily, a demand planning analyst. You help demand \
planners sanity-check the current forecast plan against live warehouse data — \
surfacing top SKUs and customers, product economics, and forecasts that look \
like placeholders — by reading the pre-computed `lily` schema views. You never \
write SQL, joins, or arithmetic yourself: every number you cite is already a \
column in a view.

## Hard guardrails

- You are forward-looking only. You hold the current forecast plus, at most, \
the single most recently closed actuals period as a reference snapshot — never \
a forecast accuracy history.
- You do not evaluate forecast accuracy, bias, or how good the demand or \
statistical forecast has historically been. That is Billy's responsibility, \
not yours. If asked, say so plainly and point the planner to Billy rather than \
constructing an accuracy judgment from what's available.
- You do not cover inventory or stock coverage. That feed is not wired in yet.
- Your scope is BR-06, BR-08, BR-09, and BR-11. If a question falls outside \
this scope, or outside what your current views can answer, say plainly that \
it isn't available and why. An honest "not available yet" is always correct; \
a guess is not.

## Communication style

You're collaborative and exploratory — you surface what the data shows, you \
don't issue verdicts. Scale how directly you push back to your confidence, not \
to politeness: a HIGH-confidence finding (e.g. an identical flat forecast \
across periods, a margin that's gone negative) gets stated plainly as a \
problem to fix, not hedged into a vague suggestion. A MEDIUM or LOW-confidence \
observation gets framed as a question or something worth checking, not a \
conclusion. Never soften a high-confidence flag just to be agreeable — the \
planner needs to know when something is actually wrong.

## How to work

Use your demand-planning-analysis skill for which view answers which question, \
what isn't available yet, and the exact output format to use. Consult it \
before answering anything that requires data.
"""

# ── Anthropic tool definitions ─────────────────────────────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "load_data",
        "description": (
            "Load the demand planning dataset from a file path and return a summary "
            "of what is available: which SKUs, customers, regions, and years are "
            "present, plus how many periods have actuals vs. zeros. Call this first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Excel (.xlsx) or CSV demand data file.",
                }
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "get_sku_history",
        "description": (
            "Return the full historical and forecast time series for a given SKU. "
            "Returns actuals, dp_forecast, stat_forecast, and business_plan for "
            "every period and year. Optionally filtered to one customer. "
            "Use this to identify trends, year-over-year changes, and forecast "
            "deviations. The summary includes historical MAPE for each forecast source."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "The SKU identifier, e.g. 'SKU001'.",
                },
                "customer": {
                    "type": "string",
                    "description": (
                        "Optional. If provided, filter to one customer "
                        "(e.g. 'Carrefour'). If omitted, aggregates across all customers."
                    ),
                },
            },
            "required": ["sku_id"],
        },
    },
    {
        "name": "analyze_period_pattern",
        "description": (
            "For a specific period number (1–13), return what actually happened in "
            "that period across all available years side by side. "
            "Pre-computes the average of all other periods (baseline) and the ratio "
            "of this period to that baseline per year. "
            "Use this when you spot an unusual period in the history to check "
            "whether it recurs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "The SKU identifier.",
                },
                "period": {
                    "type": "integer",
                    "description": "Period number 1–13.",
                },
                "customer": {
                    "type": "string",
                    "description": "Optional. Filter to one customer.",
                },
            },
            "required": ["sku_id", "period"],
        },
    },
    {
        "name": "compare_forecasts",
        "description": (
            "Compare the accuracy of DP forecast, statistical forecast, and business "
            "plan against actuals for a given SKU and year. Only periods with "
            "non-zero actuals are included. Returns MAPE and bias for each source, "
            "plus which source performed best and an interpretation hint. "
            "Use this to judge whether the DP adds value over the stat model, "
            "and whether the business plan is directionally accurate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {
                    "type": "string",
                    "description": "The SKU identifier.",
                },
                "year": {
                    "type": "integer",
                    "description": "Year to evaluate (2023 or 2024; 2025 is partial).",
                },
                "customer": {
                    "type": "string",
                    "description": "Optional. Filter to one customer.",
                },
            },
            "required": ["sku_id", "year"],
        },
    },
]

# ── Tool dispatch ──────────────────────────────────────────────────────────────

TOOL_DISPATCH: dict[str, Any] = {
    "load_data": tools_module.load_data,
    "get_sku_history": tools_module.get_sku_history,
    "analyze_period_pattern": tools_module.analyze_period_pattern,
    "compare_forecasts": tools_module.compare_forecasts,
}


def _dispatch_tool(name: str, inputs: dict) -> dict:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return fn(**inputs)
    except Exception as exc:
        return {"error": str(exc), "tool": name, "inputs": inputs}


# ── Agentic loop ───────────────────────────────────────────────────────────────

def _system_blocks() -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": LILY_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def run_agent_loop(
    messages: list[dict[str, Any]],
    system: list[dict[str, Any]] | None = None,
    on_event: Any = None,
    usage: dict[str, int] | None = None,
) -> str:
    """Drive the tool-calling loop over an existing message history.

    `messages` is mutated in place — assistant turns and tool results are
    appended as the loop runs, so the caller ends up with the full transcript.
    `on_event`, if given, is called with a dict for each tool call as it
    happens ({"type": "tool_call", "name": ..., "input": ...}) so a UI can
    show progress while Lily works. `usage`, if given, accumulates token
    counts per API turn (see costing.new_usage). Returns Lily's final text.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    system = system or _system_blocks()
    final_text = ""

    for turn in range(MAX_TOOL_TURNS):
        response = client.messages.create(
            model=LOOP_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if usage is not None:
            from agents.lily.costing import add_usage
            add_usage(usage, response.usage)

        # Append full content block (preserves tool_use blocks for the next turn)
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
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # stop_reason == "end_turn"
        final_text = "".join(
            b.text
            for b in response.content
            if getattr(b, "type", None) == "text"
        )
        break

    return final_text


def run_lily(user_message: str) -> str:
    """Run the agent loop on a single user message and return the final text."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    return run_agent_loop(messages)


# ── CLI ────────────────────────────────────────────────────────────────────────

def _build_user_message(sku: str, customer: str | None, file_path: str) -> str:
    if sku.lower() == "all":
        sku_clause = "all SKUs in the dataset (SKU001 through SKU008)"
    else:
        sku_clause = f"SKU {sku}"

    customer_clause = f" for customer {customer}" if customer else ""

    return (
        f"Please evaluate the demand forecast{customer_clause} for {sku_clause}.\n"
        f"The data file is at: {file_path}\n\n"
        "Start by loading the data, then analyse each SKU thoroughly using all "
        "available tools before producing your structured recommendation."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Lily — demand planning reasoning agent")
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

    print(f"Lily is analysing {args.sku}"
          + (f" / {args.customer}" if args.customer else "")
          + " ...\n")

    result = run_lily(user_message)
    print(result)


if __name__ == "__main__":
    main()
