"""Lily eval harness — scores her recommendations against the dataset's
known ground truth.

The synthetic dataset (data/generate_dataset.py, seed=42) has one designed
pattern per SKU, so every recommendation has a right answer. Each case runs
Lily fresh (no shared context), parses the RECOMMENDATION line from her
structured output block, and checks it against the accepted set.

⚠️ COSTS MONEY: each case is a full agent run (multiple Sonnet calls).
Use --list to see the cases without spending anything.

Usage:
    python evals/run_evals.py --list           # show cases, no API calls
    python evals/run_evals.py --sku SKU001     # run one case
    python evals/run_evals.py                  # run all 8 (asks first)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from agents.lily.costing import cost_usd, new_usage, total_tokens
from agents.lily.lily import DEFAULT_DATA_FILE, _build_user_message, run_agent_loop

# ── Ground truth ──────────────────────────────────────────────────────────────
# Accepted sets, from README/CLAUDE.md. SKU002: UNCERTAIN was the designed
# answer but LOWER is the smarter one (forecasts still contaminated by the
# one-time 2023 spike) — both count. SKU008 is noise: KEEP or UNCERTAIN.


@dataclass
class EvalCase:
    sku: str
    pattern: str
    accepted: set[str]
    customer: str | None = None


CASES = [
    EvalCase("SKU001", "Recurring P5 peak ×1.75, 3 years", {"RAISE"}),
    EvalCase("SKU002", "One-time P8 spike 2023 only", {"LOWER", "UNCERTAIN"}),
    EvalCase("SKU003", "Consistent +18%/yr growth", {"RAISE"}),
    EvalCase("SKU004", "Business plan 24-28% over actuals", {"LOWER"}),
    EvalCase("SKU005", "Stat MAPE 1.9% vs DP 15.3%", {"LOWER"}),
    EvalCase("SKU006", "Carrefour-only P11 peak ×2.10", {"RAISE"}, customer="Carrefour"),
    EvalCase("SKU007", "Declining -17%/yr", {"LOWER"}),
    EvalCase("SKU008", "High noise, no pattern", {"KEEP", "UNCERTAIN"}),
]


@dataclass
class CaseResult:
    case: EvalCase
    recommendation: str | None
    passed: bool
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_recommendation(text: str, sku: str) -> str | None:
    """Pull the RECOMMENDATION value from Lily's structured block for `sku`.

    Looks inside the block mentioning the SKU first; falls back to the first
    RECOMMENDATION line anywhere (single-SKU runs only have one block).
    """
    blocks = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    candidates = [b for b in blocks if sku in b] or [text]
    for block in candidates:
        m = re.search(r"RECOMMENDATION:\s*\**([A-Z]+)", block)
        if m:
            return m.group(1)
    return None


# ── Runner ────────────────────────────────────────────────────────────────────

def run_case(case: EvalCase) -> CaseResult:
    user_message = _build_user_message(case.sku, case.customer, DEFAULT_DATA_FILE)
    usage = new_usage()
    try:
        reply = run_agent_loop(
            [{"role": "user", "content": user_message}], usage=usage
        )
    except Exception as exc:
        return CaseResult(case, None, False, usage, error=str(exc))

    rec = parse_recommendation(reply, case.sku)
    return CaseResult(case, rec, passed=rec in case.accepted, usage=usage)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Lily evals against ground truth")
    parser.add_argument("--sku", help="Run only this SKU (e.g. SKU001)")
    parser.add_argument("--list", action="store_true", help="List cases, no API calls")
    parser.add_argument("--yes", action="store_true", help="Skip the cost confirmation")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.sku or c.sku == args.sku]
    if not cases:
        sys.exit(f"No case for {args.sku}")

    if args.list:
        for c in cases:
            scope = f" / {c.customer}" if c.customer else ""
            print(f"{c.sku}{scope}: {c.pattern}  ->  {' or '.join(sorted(c.accepted))}")
        return

    if not args.yes:
        est = len(cases)
        answer = input(
            f"About to run {est} agent run(s) — this spends real API credit "
            "(rough order: a few cents each). Continue? [y/N] "
        )
        if answer.strip().lower() != "y":
            print("Aborted.")
            return

    results = [run_case(c) for c in cases]

    print("\n" + "=" * 72)
    print(f"{'SKU':<10}{'Expected':<20}{'Got':<12}{'Result':<8}{'Tokens':<10}{'Cost'}")
    print("-" * 72)
    total_cost = 0.0
    for r in results:
        expected = " or ".join(sorted(r.case.accepted))
        got = r.recommendation or (f"ERROR: {r.error}" if r.error else "UNPARSED")
        verdict = "PASS" if r.passed else "FAIL"
        tokens = total_tokens(r.usage) if r.usage.get("turns") else 0
        cost = cost_usd(r.usage) if r.usage.get("turns") else 0.0
        total_cost += cost
        print(f"{r.case.sku:<10}{expected:<20}{got:<12}{verdict:<8}{tokens:<10}${cost:.3f}")
    print("-" * 72)
    passed = sum(r.passed for r in results)
    print(f"Score: {passed}/{len(results)}    Total cost: ${total_cost:.3f}")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
