"""Lily — demand planning reasoning agent (Microsoft Agent Framework 1.0).

Same reasoning logic as lily.py but runs on Microsoft Agent Framework 1.0
with GPT-5 via Azure AI Foundry. The agentic loop (model drives multi-step
tool calls until it decides it has enough evidence) is handled internally
by the framework — no manual stop_reason checking needed.

Required environment variable:
    AZURE_AI_PROJECT_ENDPOINT  — your Foundry project endpoint
    e.g. https://<name>.services.ai.azure.com/api/projects/<project>

Auth: DefaultAzureCredential (run `az login` locally; managed identity in prod).

Usage:
    python agents/lily/lily_msft.py --sku SKU001
    python agents/lily/lily_msft.py --sku all
    python agents/lily/lily_msft.py --sku SKU006 --customer Carrefour
    python agents/lily/lily_msft.py --file path/to/custom.xlsx --sku SKU001
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Allow running from repo root: python agents/lily/lily_msft.py
sys.path.insert(0, str(Path(__file__).parents[2]))

from azure.identity import InteractiveBrowserCredential

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

# Reuse the system prompt and helpers from the Anthropic version — nothing there
# is Anthropic-specific; it's pure business logic.
from agents.lily.lily import (
    LILY_SYSTEM_PROMPT,
    DEFAULT_DATA_FILE,
    _build_user_message,
)
from agents.lily import tools as tools_module

# ── Constants ─────────────────────────────────────────────────────────────────

LOOP_MODEL = "gpt-5"

# ── Agent setup ───────────────────────────────────────────────────────────────

def _make_client() -> FoundryChatClient:
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
    if not endpoint:
        raise RuntimeError(
            "AZURE_AI_PROJECT_ENDPOINT is not set.\n"
            "Set it to your Foundry project endpoint, e.g.:\n"
            "  export AZURE_AI_PROJECT_ENDPOINT=https://<name>.services.ai.azure.com/api/projects/<project>"
        )
    return FoundryChatClient(
        project_endpoint=endpoint,
        model=LOOP_MODEL,
        credential=InteractiveBrowserCredential(),
    )


def _make_agent(client: FoundryChatClient) -> Agent:
    """Create Lily with her four data tools.

    Agent Framework discovers each tool's description from the first line
    of its docstring and infers parameter types from type annotations.
    No JSON schema definitions needed — tools.py functions are passed directly.
    """
    return client.as_agent(
        name="Lily",
        instructions=LILY_SYSTEM_PROMPT,
        tools=[
            tools_module.load_data,
            tools_module.get_sku_history,
            tools_module.analyze_period_pattern,
            tools_module.compare_forecasts,
        ],
    )


# ── Run ───────────────────────────────────────────────────────────────────────

async def run_lily_async(user_message: str) -> str:
    """Run the agent and return Lily's final text response.

    The Agent Framework handles the multi-turn tool-calling loop internally.
    Lily will call tools as many times as she decides she needs to, then
    produce her final structured recommendation.
    """
    client = _make_client()
    agent = _make_agent(client)

    # create_session() is the equivalent of starting a fresh conversation thread.
    session = agent.create_session()

    response = await agent.run(user_message, session=session)
    return response.text


def run_lily(user_message: str) -> str:
    """Sync wrapper around run_lily_async for CLI use."""
    return asyncio.run(run_lily_async(user_message))


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lily — demand planning reasoning agent (Microsoft Agent Framework)"
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

    print(f"Lily (Microsoft Agent Framework / {LOOP_MODEL}) is analysing {args.sku}"
          + (f" / {args.customer}" if args.customer else "")
          + " ...\n")

    result = run_lily(user_message)
    print(result)


if __name__ == "__main__":
    main()
