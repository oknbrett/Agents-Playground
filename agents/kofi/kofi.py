"""Kofi — external research agent (web search), dispatched by Lily.

Lily reasons over the *internal* numbers. When a signal might be driven by
something the data can't show — a season turning, a heatwave, a competitor's
launch, a category trend — she calls `external_research(query, context)`.
Kofi runs his own small Claude loop with Anthropic's native `web_search`
server tool, then returns a distilled, cited findings report. Lily never sees
the raw search results, so her context window stays lean — that isolation is
the whole point of making Kofi a tool rather than a second voice in the chat.

Design + contract: docs/KOFI.md.

Standalone test:
    python agents/kofi/kofi.py --query "Dutch garden-product demand spring 2026"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running from repo root: python agents/kofi/kofi.py
sys.path.insert(0, str(Path(__file__).parents[2]))

import anthropic

from agents.lily.costing import (
    add_usage,
    cost_usd_haiku,
    new_usage,
    total_tokens,
)

# Every Kofi dispatch appends one JSON line here (queries, sources, tokens, cost)
# so there's always a developer trail for what web research actually did + cost.
TRACE_LOG = Path(os.environ.get("KOFI_TRACE_LOG", str(Path(__file__).parent / ".kofi_trace.jsonl")))

# ── Config ─────────────────────────────────────────────────────────────────────
# Kofi summarizes search results rather than doing deep reasoning, so he defaults
# to a lighter (cheaper) model than Lily. Override with KOFI_MODEL. Bound a single
# dispatch with a search cap + a continuation cap so one call can't run away.

KOFI_MODEL = os.environ.get("KOFI_MODEL", "claude-haiku-4-5-20251001")
KOFI_MAX_SEARCHES = int(os.environ.get("KOFI_MAX_SEARCHES", "5"))
MAX_TOKENS = 2048
MAX_PAUSE_CONTINUATIONS = 6  # web search can pause_turn on long runs; bound the retries

# ── System prompt ───────────────────────────────────────────────────────────────

KOFI_SYSTEM_PROMPT = """You are Kofi, an external research agent for a demand \
planning team. Your teammate Lily reads the company's INTERNAL numbers (forecast, \
actuals, accuracy, budget, inventory). You do the opposite: you reach OUTSIDE the \
data for real-world context the numbers can't show — seasonality, weather, \
competitor activity, category/market trends, pricing moves, and regulatory or \
supply-chain news.

## How you work

- ALWAYS use web search first. Never answer from memory or guess — if you didn't \
find it in a search, it doesn't go in your findings.
- Lily gives you a research question and (usually) some context about the product \
and her current read. Focus your searches on that. If her question is too narrow \
to be useful, also search the angle she should have asked.
- Prefer recent, authoritative sources (meteorological services, trade press, \
company filings, official statistics). Note the date of what you find.
- If you find something that CONTRADICTS Lily's current read, say so plainly in \
`conflicts_with_internal` — that's the most valuable thing you can return.
- Be honest about gaps. If the web doesn't have a clear answer, return an empty or \
low-confidence finding and say so. A truthful "couldn't find solid evidence" is \
always better than a confident guess.

## Output format — STRICT

Return ONLY a single JSON object, no prose before or after, in exactly this shape:

{
  "summary": "one or two sentences — the headline a busy planner reads first",
  "findings": [
    {
      "topic": "short label, e.g. 'Seasonal outlook'",
      "summary": "what you found, with the key number/date",
      "relevance": "why it matters for this product's demand",
      "confidence": "high" | "medium" | "low",
      "sources": ["https://...", "https://..."]
    }
  ],
  "conflicts_with_internal": ["plain-language note(s) where your findings push against Lily's read; [] if none"],
  "suggested_follow_up": "a sharper research thread worth pulling next, or null"
}

Every finding MUST cite at least one real source URL you actually visited. Keep it \
tight — 2 to 5 findings, not an essay."""

# ── Web search server tool ──────────────────────────────────────────────────────


def _web_search_tool() -> dict[str, Any]:
    return {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": KOFI_MAX_SEARCHES,
    }


def _format_request(query: str, context: dict | None) -> str:
    parts = [f"Research request from Lily:\n{query.strip()}"]
    if context:
        parts.append(
            "\nContext on the product and Lily's current read "
            "(use it to focus and to spot contradictions):\n"
            + json.dumps(context, indent=2)
        )
    parts.append(
        "\nSearch the web, then return your findings as the strict JSON object."
    )
    return "\n".join(parts)


def _parse_findings(text: str, query: str) -> dict[str, Any]:
    """Lenient parse of Kofi's JSON. Falls back to wrapping raw text so Lily
    always gets a usable payload even if the model added stray prose."""
    text = text.strip()
    if text.startswith("```"):
        # strip a ```json ... ``` fence
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return {
        "query": query,
        "summary": text[:2000],
        "findings": [],
        "conflicts_with_internal": [],
        "suggested_follow_up": None,
        "parse_error": "Kofi did not return valid JSON; raw text in 'summary'.",
    }


# ── Tracing ─────────────────────────────────────────────────────────────────────


def _collect_search_activity(content: Any, searches: list[dict[str, Any]]) -> None:
    """Pull web-search queries + result sources out of one response's content
    blocks and append them to the running `searches` list (across continuations)."""
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "server_tool_use" and getattr(block, "name", "") == "web_search":
            q = (getattr(block, "input", None) or {}).get("query")
            searches.append({"query": q, "sources": []})
        elif btype == "web_search_tool_result":
            results = getattr(block, "content", None)
            sources: list[dict[str, Any]] = []
            if isinstance(results, list):
                for r in results:
                    url = getattr(r, "url", None)
                    if url:
                        sources.append({
                            "title": getattr(r, "title", None),
                            "url": url,
                            "age": getattr(r, "page_age", None),
                        })
            if searches:
                searches[-1]["sources"] = sources
            else:
                searches.append({"query": None, "sources": sources})


def _build_trace(query: str, searches: list[dict], kofi_usage: dict[str, int]) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "query": query,
        "model": KOFI_MODEL,
        "n_searches": sum(1 for s in searches if s.get("query")),
        "n_sources": sum(len(s.get("sources") or []) for s in searches),
        "searches": searches,
        "tokens": {
            "input": kofi_usage["input_tokens"],
            "output": kofi_usage["output_tokens"],
            "cache_read": kofi_usage["cache_read_input_tokens"],
            "cache_write": kofi_usage["cache_creation_input_tokens"],
            "total": total_tokens(kofi_usage),
            "web_search_requests": kofi_usage["web_search_requests"],
        },
        "cost_usd": round(cost_usd_haiku(kofi_usage), 4),
    }


def _log_trace(trace: dict[str, Any]) -> None:
    """Print a readable summary to the server console AND append the full trace
    as one JSON line to TRACE_LOG — a dev trail for every Kofi run. Must never
    raise (it runs inside the agent loop); ASCII-only so Windows consoles
    (cp1252) can't choke on it."""
    try:
        q = (trace.get("query") or "")[:80]
        lines = [
            f"[KOFI] {q!r} - {trace['n_searches']} searches, {trace['n_sources']} sources, "
            f"{trace['tokens']['total']:,} tok, ${trace['cost_usd']:.4f} (haiku)"
        ]
        for s in trace["searches"]:
            lines.append(f"  > search: {s.get('query')!r}")
            for src in (s.get("sources") or [])[:10]:
                lines.append(f"      - {src.get('title')}  {src.get('url')}")
        # Encode-safe for whatever console is attached.
        print("\n".join(lines).encode("ascii", "replace").decode("ascii"), flush=True)
    except Exception:
        pass
    try:
        with open(TRACE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── The tool Lily calls ─────────────────────────────────────────────────────────


def external_research(
    query: str,
    context: dict | None = None,
    *,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Dispatch Kofi to research `query` on the web and return cited findings.

    `context` is an optional dict from Lily (material_id, product_family,
    current_recommendation, key_signal) that focuses the search and lets Kofi
    flag contradictions. `usage`, if given, accumulates Kofi's token + web-search
    cost into the caller's spend accounting (see agents.lily.costing).

    Every run is traced: the result carries a `_trace` (queries, sources, tokens,
    accurate Haiku cost) for the UI/log, and a summary is written to TRACE_LOG.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "error": (
                "Kofi needs ANTHROPIC_API_KEY to run web search (he uses Anthropic's "
                "native web search). Set it to enable external research."
            ),
            "findings": [],
        }

    client = anthropic.Anthropic(api_key=api_key)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _format_request(query, context)}
    ]
    kofi_usage = new_usage()  # local, priced at Haiku → accurate cost for the trace
    searches: list[dict[str, Any]] = []
    final_text = ""

    for _ in range(MAX_PAUSE_CONTINUATIONS):
        response = client.messages.create(
            model=KOFI_MODEL,
            max_tokens=MAX_TOKENS,
            system=KOFI_SYSTEM_PROMPT,
            tools=[_web_search_tool()],
            messages=messages,
        )

        add_usage(kofi_usage, response.usage)  # accurate, local
        if usage is not None:
            add_usage(usage, response.usage)   # caller's spend guard (Sonnet-priced)
        _collect_search_activity(response.content, searches)

        # Preserve server_tool_use / web_search_tool_result blocks for continuation.
        messages.append({"role": "assistant", "content": response.content})

        # Anthropic may pause a long web-search turn; re-send to let it continue.
        if response.stop_reason == "pause_turn":
            continue

        final_text = "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        )
        break

    result = _parse_findings(final_text, query)
    result.setdefault("query", query)
    trace = _build_trace(query, searches, kofi_usage)
    _log_trace(trace)
    result["_trace"] = trace
    return result


# ── CLI (standalone test) ───────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Kofi — external web-research agent")
    parser.add_argument("--query", required=True, help="The research question.")
    parser.add_argument(
        "--material", default=None, help="Optional material_id for context."
    )
    parser.add_argument(
        "--signal", default=None, help="Optional key_signal note for context."
    )
    args = parser.parse_args()

    context = {}
    if args.material:
        context["material_id"] = args.material
    if args.signal:
        context["key_signal"] = args.signal

    print(f"Kofi is researching: {args.query}\n")
    result = external_research(args.query, context or None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
