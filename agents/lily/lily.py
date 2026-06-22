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
from agents.kofi.kofi import external_research
from agents.shared import ASK_PLANNER_TOOL_DEF, ASK_PLANNER_TOOL_NAME, is_ask_planner_call

# ── Constants ─────────────────────────────────────────────────────────────────

LOOP_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
MAX_TOOL_TURNS = 20

DEFAULT_DATA_FILE = str(Path(__file__).parents[2] / "data" / "demand_data.xlsx")

# ── System prompt ─────────────────────────────────────────────────────────────

LILY_SYSTEM_PROMPT = """You are Lily, a demand planning analyst. You give demand \
planners the full picture of a product: the forward plan — top SKUs and \
customers, product economics, demand vs the statistical baseline and the budget, \
inventory coverage — AND how recent forecasts have actually performed (accuracy \
and bias). You read figures your tools have already calculated rather than \
computing them yourself.

## Fiscal calendar

The fiscal year starts in NOVEMBER: P1=Nov, P4=Feb, P7=May, P12=Oct. "Now" is the \
period just after the latest closed actuals period; that latest closed period is \
your anchor for anything "recent". Translate periods to months when it helps the \
planner (e.g. "P7 = May").

## Hard guardrails

- Forecast accuracy and bias ARE your job now. Measure on a LAG-2 basis (Evergreen's \
operational lag) unless asked otherwise — WMAPE for accuracy, signed (F−A)/A for \
bias. The one thing still not yours: you read pre-computed accuracy, you don't \
re-derive a different metric by hand.
- Never assert that a pattern, trend, or issue exists unless the data you \
actually retrieved shows it. If you're inferring something the data doesn't \
directly state — e.g. calling something a "trend" when you've only confirmed \
it in one year — say plainly that it's your inference, not a fact, and show \
what would confirm or break it.
- If a question falls outside what your views can answer, say plainly that it \
isn't available and why. An honest "not available" is always correct; a guess is not.

## What to focus on (triage)

When a planner asks what to focus on right now, pull the per-SKU performance scan \
(recent accuracy/bias + materiality at the latest closed period) and decide the \
shortlist YOURSELF — don't just echo a sorted list. Rank by revenue impact by \
default (a big SKU you got wrong matters more than a tiny one), but SAY that you \
ranked by revenue, and note that volume would reorder it if supply strain is the \
concern. For each pick give the why: the revenue at stake and the specific \
performance problem (e.g. "forecast running 13% high three periods straight").

## Communication style

You're collaborative and exploratory — you show your evidence, you don't \
just issue a verdict from nowhere. But you do have to land on one: every \
analysis ends with a clear RAISE, LOWER, or KEEP recommendation (or \
UNCERTAIN, if the evidence genuinely doesn't support a direction), with a \
confidence level. Scale how directly you push back to your confidence, not \
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

## Asking the planner

When there are genuinely different directions to go — which SKUs to focus on, \
what angle of research to pursue via Kofi, whether to drill into accuracy or \
inventory first — use `ask_planner` to present 2-4 options as clickable cards \
instead of a long-form question. Don't overuse it; reserve it for real forks \
where the planner's preference shapes the analysis, not routine decisions you \
can make yourself.
"""

# ── Anthropic tool definitions ─────────────────────────────────────────────────

_MATERIAL = {"type": "string", "description": "The SKU / material id, e.g. 'UNI40' or '10491'."}
_SALES_ORG = {"type": "integer", "description": "Optional. Region / business-unit code, e.g. 2510."}
_CUSTOMER = {"type": "string", "description": "Optional. Customer code (Triad Region), e.g. 'FA'."}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_overview",
        "description": (
            "Orient yourself: what the warehouse holds right now — the regions "
            "(sales_orgs), how many customers and materials, the loaded forecast "
            "version and its period horizon, the latest closed actuals period, and "
            "which data streams exist (demand forecast, budget, inventory, actuals; "
            "note statistical forecast is not available). Call this first."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_forecast",
        "description": (
            "The forward demand forecast for a SKU, period by period, with revenue, "
            "margin and unit price pre-computed, plus a shape summary (total, min, "
            "max, average, and whether the forecast is flat/placeholder). Aggregates "
            "across customers unless customer_code is given. Your primary tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": _MATERIAL,
                "sales_org": _SALES_ORG,
                "customer_code": _CUSTOMER,
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "demand_vs_budget",
        "description": (
            "Compare the demand forecast against the sales budget (target) per "
            "future period for a SKU: demand_qty vs budget_qty, the delta and "
            "delta %, plus how many periods the plan sits above vs below target. "
            "Use this to see where the plan and the target disagree."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": _MATERIAL,
                "sales_org": _SALES_ORG,
                "customer_code": _CUSTOMER,
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "demand_vs_statistical",
        "description": (
            "Compare the planner's demand forecast against the naive statistical "
            "baseline per future period for a SKU: demand_qty vs statistical_qty, "
            "the override (delta) and override %, plus a flag (PLANNER RAISED / "
            "PLANNER LOWERED / IN LINE). The gap IS the planner's manual judgment — "
            "use it to see where and how much a human moved off the model, and to "
            "question overrides that aren't backed by a trend."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": _MATERIAL,
                "sales_org": _SALES_ORG,
                "customer_code": _CUSTOMER,
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "inventory_coverage",
        "description": (
            "Current on-hand stock vs forward demand for a SKU (product level): "
            "stock_qty_ea, average period demand, coverage_periods (stock / avg "
            "demand), and a flag — STOCKOUT RISK (<1 period), OVERSTOCK (>12), or "
            "OK. EA units only; flags materials that also hold non-EA stock."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": _MATERIAL,
                "sales_org": _SALES_ORG,
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "product_economics",
        "description": (
            "Per-product economics across the horizon: total quantity, revenue, "
            "COGS, margin, margin %, average unit selling price and unit COGS. Use "
            "for 'what's the price/COGS of this SKU?' and 'if we sell N units, "
            "what's the revenue?' (N * avg_selling_price_eur)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": _MATERIAL,
                "sales_org": _SALES_ORG,
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "top_skus",
        "description": (
            "The top-N SKUs in a given future period, ranked by quantity or "
            "revenue. Use for 'top 5 SKUs by units expected in P8 next year'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fiscal_year": {"type": "integer", "description": "Fiscal year, e.g. 2026."},
                "fiscal_period": {"type": "integer", "description": "Fiscal period 1–12."},
                "sales_org": _SALES_ORG,
                "by": {
                    "type": "string",
                    "enum": ["qty", "revenue"],
                    "description": "Rank by 'qty' (default) or 'revenue'.",
                },
                "n": {"type": "integer", "description": "How many to return (default 5)."},
            },
            "required": ["fiscal_year", "fiscal_period"],
        },
    },
    {
        "name": "family_scan",
        "description": (
            "Cross-FAMILY rollup in one call: every product family (L1/L2) with its "
            "trailing-12m revenue, demand-vs-statistical override %, average YoY "
            "growth, and SKU count. Use this FIRST for 'biggest family' / 'which "
            "category' questions, then drill into a family with divergence_scan. "
            "Ordered by revenue by default ('override' or 'growth' also)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_by": {"type": "string", "enum": ["revenue", "override", "growth"],
                             "description": "Order families by (default 'revenue')."},
            },
            "required": [],
        },
    },
    {
        "name": "divergence_scan",
        "description": (
            "Cross-SKU scan in ONE call — every SKU's demand-vs-statistical override "
            "(whole horizon AND latest forecast year for escalation), demand-vs-budget "
            "gap, trailing-12m revenue, YoY actual growth, and family. Use this "
            "INSTEAD of looping demand_vs_statistical SKU-by-SKU — it lets you reason "
            "over the complete set, not a sample. Optionally filter to one family "
            "(L2 category). order_by: 'revenue' (default), 'override', "
            "'override_latest_year', 'budget', 'growth'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Optional L2 category to filter to (a product family)."},
                "order_by": {"type": "string",
                             "enum": ["revenue", "override", "override_latest_year", "budget", "growth"],
                             "description": "How to order (default 'revenue')."},
                "n": {"type": "integer", "description": "How many SKUs to return (default 50)."},
            },
            "required": [],
        },
    },
    {
        "name": "forecast_performance",
        "description": (
            "Forecast ACCURACY and BIAS for a SKU — how recent forecasts actually "
            "performed vs what sold, on a lag-2 basis by default. Returns WMAPE "
            "(volume-weighted error), signed bias (positive = over-forecast), and "
            "the bias per period so a persistent one-directional drift is visible. "
            "Aggregates across customers unless customer_code is given. Use for "
            "'how accurate / how biased is this SKU's forecast?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": _MATERIAL,
                "sales_org": _SALES_ORG,
                "customer_code": _CUSTOMER,
                "lag": {"type": "integer", "description": "Forecast lag in periods (default 2, Evergreen's operational basis)."},
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "sku_performance_scan",
        "description": (
            "The triage table for 'what should I focus on right now?' — per-SKU "
            "recent accuracy/bias (last 3 closed periods, lag-2) plus materiality "
            "(trailing-12m revenue & volume) at the latest closed period. Returns "
            "the candidate set ordered by 'revenue' (default), 'volume', 'wmape', "
            "or 'bias'. These are decision INPUTS — you pick the focus shortlist "
            "and state the basis you ranked on; don't just echo the order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sales_org": _SALES_ORG,
                "order_by": {
                    "type": "string",
                    "enum": ["revenue", "volume", "wmape", "bias"],
                    "description": "How to order the candidates (default 'revenue').",
                },
                "n": {"type": "integer", "description": "How many SKUs to return (default 25)."},
            },
            "required": [],
        },
    },
    {
        "name": "actuals_history",
        "description": (
            "The full actuals sales history for a SKU — real sold quantity per "
            "period across all closed periods (multiple years), with per-year "
            "totals and year-over-year growth. Use this to judge whether a forward "
            "forecast or planner override is backed by what actually happened "
            "(e.g. a +20% plan against two years of flat actuals). Aggregates "
            "across customers unless customer_code is given. This is raw sales "
            "history — NOT forecast accuracy or bias (that's Billy's domain)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": _MATERIAL,
                "sales_org": _SALES_ORG,
                "customer_code": _CUSTOMER,
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "latest_actuals",
        "description": (
            "The single most recent closed-period actuals for a SKU — a reference "
            "anchor only (not performance reporting). May be empty if the SKU is "
            "not in the latest closed period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "material_id": _MATERIAL,
                "sales_org": _SALES_ORG,
                "customer_code": _CUSTOMER,
            },
            "required": ["material_id"],
        },
    },
    {
        "name": "external_research",
        "description": (
            "Dispatch Kofi, an external web-research agent, to gather real-world "
            "context the internal data CAN'T show — seasonality, weather, competitor "
            "activity, category/market trends, pricing moves, regulatory or supply-"
            "chain news. Kofi runs his own web search and returns distilled findings "
            "with cited source URLs, plus any points that CONFLICT with the internal "
            "read you describe. Use this when an internal signal (a planner override, "
            "a YoY swing, a budget gap, a flat forecast) might be driven by something "
            "outside the numbers, or when the planner asks what's happening in the "
            "market. You may call it more than once for different angles. It returns "
            "external evidence only — YOU still own the RAISE / LOWER / KEEP call and "
            "must weigh Kofi's findings against your data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The research question, specific and self-contained (Kofi has "
                        "no access to your data or this chat). E.g. 'Outlook for Dutch "
                        "consumer garden/plant-care demand spring 2026 and any weather "
                        "or competitor signals'."
                    ),
                },
                "context": {
                    "type": "object",
                    "description": (
                        "Optional. What you're looking at, so Kofi can focus and flag "
                        "contradictions with your read."
                    ),
                    "properties": {
                        "material_id": _MATERIAL,
                        "product_family": {"type": "string", "description": "Product family / category, e.g. 'Potting Soil — Indoor'."},
                        "current_recommendation": {"type": "string", "description": "Your current lean: RAISE / LOWER / KEEP / UNCERTAIN."},
                        "key_signal": {"type": "string", "description": "The internal signal prompting the question, e.g. 'YoY +18%, planner override +12% above statistical'."},
                    },
                },
            },
            "required": ["query"],
        },
    },
    ASK_PLANNER_TOOL_DEF,
]

# ── Tool dispatch ──────────────────────────────────────────────────────────────

TOOL_DISPATCH: dict[str, Any] = {
    "get_overview": tools_module.get_overview,
    "get_forecast": tools_module.get_forecast,
    "demand_vs_budget": tools_module.demand_vs_budget,
    "demand_vs_statistical": tools_module.demand_vs_statistical,
    "family_scan": tools_module.family_scan,
    "divergence_scan": tools_module.divergence_scan,
    "inventory_coverage": tools_module.inventory_coverage,
    "product_economics": tools_module.product_economics,
    "top_skus": tools_module.top_skus,
    "forecast_performance": tools_module.forecast_performance,
    "sku_performance_scan": tools_module.sku_performance_scan,
    "actuals_history": tools_module.actuals_history,
    "latest_actuals": tools_module.latest_actuals,
    "external_research": external_research,
}

# Tools that can fold their own API spend into the loop's usage accumulator
# (Kofi runs his own Claude + web-search calls, which cost real money).
USAGE_AWARE_TOOLS = {"external_research"}


def _dispatch_tool(name: str, inputs: dict, usage: dict | None = None) -> dict:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        if name in USAGE_AWARE_TOOLS:
            return fn(**inputs, usage=usage)
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
            # Surface any text Lily wrote in the same turn as her tool calls (e.g.
            # a heads-up that she's dispatching Kofi) so the UI shows it BEFORE the
            # tool step streams — otherwise the planner stares at a silent spinner.
            narration = "".join(
                b.text for b in response.content if getattr(b, "type", None) == "text"
            ).strip()
            if narration and on_event is not None:
                on_event({"type": "narration", "text": narration})

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
                    return ""

            tool_results = []
            for block in response.content:
                if getattr(block, "type", None) == "tool_use":
                    if on_event is not None:
                        on_event({
                            "type": "tool_call",
                            "name": block.name,
                            "input": block.input,
                        })
                    result = _dispatch_tool(block.name, block.input, usage=usage)
                    # Kofi attaches a `_trace` (queries, sources, tokens, cost).
                    # Surface it to the UI as its own event, then strip it from the
                    # tool_result so Lily's context isn't bloated with raw source lists.
                    if isinstance(result, dict) and "_trace" in result:
                        trace = result.pop("_trace")
                        if on_event is not None:
                            on_event({"type": "kofi_activity", "trace": trace})
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

def _build_user_message(sku: str, customer: str | None) -> str:
    sku_clause = "all products in the overview" if sku.lower() == "all" else f"product {sku}"
    customer_clause = f" for customer {customer}" if customer else ""

    return (
        f"Please evaluate the demand forecast{customer_clause} for {sku_clause}.\n\n"
        "Start with get_overview to see what data exists, then analyse using the "
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

    user_message = _build_user_message(args.sku, args.customer)

    print(f"Lily is analysing {args.sku}"
          + (f" / {args.customer}" if args.customer else "")
          + " ...\n")

    result = run_lily(user_message)
    print(result)


if __name__ == "__main__":
    main()
