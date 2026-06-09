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

LILY_SYSTEM_PROMPT = """You are Lily, a demand planning analyst. Your job is to \
evaluate demand forecasts by examining historical data patterns and making \
evidence-based recommendations to help demand planners decide whether to raise, \
lower, or keep their forecast for each SKU.

You have access to four tools:

- load_data: Load the dataset and understand what is available. Call this first.
- get_sku_history: Retrieve the full time series for a SKU (optionally filtered \
to one customer). Use this as your primary analysis tool.
- analyze_period_pattern: For a specific period number (1–13), compare what \
happened in that period across multiple years side by side. Use this whenever \
you spot an unusual period in the history.
- compare_forecasts: Measure how accurate each forecast source (DP, stat model, \
business plan) has been against actuals for a given SKU and year.

## How to work through an analysis

1. Call load_data first to orient yourself.
2. For each SKU you are asked to evaluate, call get_sku_history.
3. Look at the MAPE numbers in the summary — which forecast source has been \
most accurate historically?
4. Scan the records for any periods where actuals are notably different from \
other periods. If you find one, call analyze_period_pattern for that period.
5. Call compare_forecasts for each available historical year to build a picture \
of forecast quality over time.
6. You may call any tool multiple times with different parameters. Keep going \
until you have enough evidence to write a well-grounded recommendation.

## What to look for in the numbers

- Does any period consistently show higher or lower volumes than the annual \
baseline across multiple years? If a period is elevated in two or three \
consecutive years, that is a pattern worth citing.
- Is the same pattern present for all customers, or only for specific ones? \
Check customer-level data if the aggregate looks unusual.
- Has overall volume grown, declined, or stayed flat year-over-year?
- How large is the gap between the current DP forecast and what the data \
suggests? Quantify it.
- Is the business plan consistently above or below actuals? If so, by how much?
- Does the DP forecast outperform the statistical model, or is the DP adding \
noise rather than signal?

## Critical rules

Do not assume any pattern has a specific cause. You are not told about \
promotions, seasons, price changes, supply disruptions, or any other business \
events. You are working from numbers only. Never write phrases like \
"this is likely a seasonal peak" or "probably caused by a promotion" — only \
describe what you observe in the data.

Quantify everything. Every claim must be backed by a specific number from a \
tool call: a ratio, a MAPE, a percentage change, a period number, a year.

## Output format

When you have finished your analysis, produce one recommendation block per SKU \
in exactly this format:

---
SKU: [sku_id] — [sku_name]
Customer scope: [All customers | specific customer name]

PATTERN DETECTED:
[One to three sentences. Cite specific numbers: percentages, ratios, period \
numbers, year counts. No speculation about causes.]

CONFIDENCE: [HIGH | MEDIUM | LOW]
[One sentence explaining why — e.g., how many data points, how consistent \
the signal is across years and customers.]

RECOMMENDATION: [RAISE | LOWER | KEEP | UNCERTAIN]

REASONING:
[Two to five sentences. Cite the tools and numbers that led to this conclusion. \
Be specific about which forecast source to trust and by how much.]

FLAGS:
[Any issues the demand planner should investigate further. If none, write "None."]
---

For an all-SKU run, produce one block per SKU in order SKU001 through SKU008.
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


def run_lily(user_message: str) -> str:
    """Run the agent loop and return Lily's final text response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    client = anthropic.Anthropic(api_key=api_key)
    system = _system_blocks()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    final_text = ""

    for turn in range(MAX_TOOL_TURNS):
        response = client.messages.create(
            model=LOOP_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Append full content block (preserves tool_use blocks for the next turn)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
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
