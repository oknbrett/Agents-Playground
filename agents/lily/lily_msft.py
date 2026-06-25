"""Lily — demand planning reasoning agent (Microsoft Agent Framework / Foundry).

Same reasoning logic and tools as lily.py but runs on the Microsoft Agent Framework
with GPT 5.4 via Azure AI Foundry. The framework handles the agentic tool-calling
loop internally — Lily keeps calling tools until she decides she has enough evidence,
same as the Anthropic version, but we don't write the loop ourselves.

Tools are registered by passing the Python functions directly — the framework
discovers names, descriptions (from docstrings), and parameter schemas (from type
annotations). The system prompt (`LILY_SYSTEM_PROMPT`) is imported from lily.py so
both backends stay in sync. NOTE: this backend hand-lists its tools (below) rather
than importing TOOL_DEFINITIONS, so keep AGENT_TOOLS in sync with lily.py whenever a
tool is added — it must include the hierarchy + node-lift tools.

Required environment:
    AZURE_AI_PROJECT_ENDPOINT — Foundry project endpoint
        e.g. https://<name>.services.ai.azure.com/api/projects/<project>

Auth: DefaultAzureCredential (az login locally; managed identity in prod).
      Falls back to InteractiveBrowserCredential for local dev.

Usage:
    python agents/lily/lily_msft.py --sku 10833
    python agents/lily/lily_msft.py --sku all
    python agents/lily/lily_msft.py --sku 10833 --customer 25001
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

from agents.lily.lily import LILY_SYSTEM_PROMPT, _build_user_message
from agents.lily import tools as tools_module
from agents.kofi.kofi import external_research

LOOP_MODEL = os.environ.get("LILY_MSFT_MODEL", "gpt-5.4")

# All data tools from tools.py + Kofi's external research.
# The Agent Framework discovers each tool's description from the first line
# of its docstring and infers parameter schemas from type annotations.
# ask_planner is excluded here — it requires special UI wiring (web app only).
AGENT_TOOLS = [
    tools_module.get_overview,
    tools_module.get_forecast,
    tools_module.demand_vs_budget,
    tools_module.inventory_coverage,
    tools_module.product_economics,
    tools_module.top_skus,
    tools_module.forecast_performance,
    tools_module.sku_performance_scan,
    tools_module.family_scan,
    tools_module.divergence_scan,
    tools_module.hierarchy_view,
    tools_module.node_detail,
    tools_module.node_sku_scan,
    tools_module.actuals_history,
    tools_module.latest_actuals,
    tools_module.load_data,
    external_research,
]


def _make_credential():
    """DefaultAzureCredential for prod/CI; falls back to interactive browser for
    local dev where az login might not be current."""
    try:
        cred = DefaultAzureCredential()
        cred.get_token("https://management.azure.com/.default")
        return cred
    except Exception:
        return InteractiveBrowserCredential()


def _make_client() -> FoundryChatClient:
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        raise RuntimeError(
            "AZURE_AI_PROJECT_ENDPOINT is not set.\n"
            "Set it to your Foundry project endpoint, e.g.:\n"
            "  export AZURE_AI_PROJECT_ENDPOINT="
            "https://<name>.services.ai.azure.com/api/projects/<project>"
        )
    return FoundryChatClient(
        project_endpoint=endpoint,
        model=LOOP_MODEL,
        credential=_make_credential(),
    )


def _make_agent(client: FoundryChatClient) -> Agent:
    """Create Lily with her full data + research toolset (see AGENT_TOOLS)."""
    return client.as_agent(
        name="Lily",
        instructions=LILY_SYSTEM_PROMPT,
        tools=AGENT_TOOLS,
    )


async def run_lily_async(user_message: str) -> str:
    """Run the agent and return Lily's final text response.

    The Agent Framework handles the multi-turn tool-calling loop internally.
    Lily calls tools as many times as she decides she needs, then produces
    her structured recommendation.
    """
    client = _make_client()
    agent = _make_agent(client)
    session = agent.create_session()
    response = await agent.run(user_message, session=session)
    return response.text


def run_lily(user_message: str) -> str:
    return asyncio.run(run_lily_async(user_message))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lily — demand planning agent (Microsoft Agent Framework / Foundry)"
    )
    parser.add_argument(
        "--sku", required=True,
        help="Material ID to analyse (e.g. 10833) or 'all' for overview.",
    )
    parser.add_argument(
        "--customer", default=None,
        help="Optional: filter to one customer code (e.g. 25001).",
    )
    args = parser.parse_args()

    user_message = _build_user_message(args.sku, args.customer)

    print(
        f"Lily (Agent Framework / {LOOP_MODEL}) is analysing {args.sku}"
        + (f" / {args.customer}" if args.customer else "")
        + " ...\n"
    )

    result = run_lily(user_message)
    print(result)


if __name__ == "__main__":
    main()
