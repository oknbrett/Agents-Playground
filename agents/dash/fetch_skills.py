"""Fetch the Anthropic document skills (docx, pdf, pptx) that Dash builds with.

These skills are Anthropic **proprietary** (see each skill's LICENSE.txt: "may not
reproduce, copy, distribute… these materials"). So we deliberately DO NOT vendor
them into this repo — `agents/dash/skills/` is gitignored. Instead, each machine
pulls them directly from Anthropic's own public source on setup. That keeps Dash
working everywhere without us redistributing proprietary files.

Usage:
    python agents/dash/fetch_skills.py        # clones docx/pdf/pptx into agents/dash/skills/

Requires git. Safe to re-run (skips skills already present unless --force).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_REPO = "https://github.com/anthropics/skills.git"
WANTED = ("docx", "pdf", "pptx")
DEST = Path(__file__).resolve().parent / "skills"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Anthropic doc skills for Dash")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if present.")
    args = parser.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    have = [s for s in WANTED if (DEST / s / "SKILL.md").is_file()]
    if len(have) == len(WANTED) and not args.force:
        print(f"All skills already present in {DEST} ({', '.join(WANTED)}). Use --force to refresh.")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        print(f"Cloning {SKILLS_REPO} …")
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", SKILLS_REPO, tmp],
                check=True, capture_output=True, text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            detail = getattr(exc, "stderr", str(exc))
            print(f"ERROR: could not clone the skills repo: {detail}", file=sys.stderr)
            print("Install git, or manually copy docx/pdf/pptx from "
                  "https://github.com/anthropics/skills into agents/dash/skills/.", file=sys.stderr)
            return 1

        src_root = Path(tmp) / "skills"
        for name in WANTED:
            src = src_root / name
            dst = DEST / name
            if not src.is_dir():
                print(f"WARNING: '{name}' not found in the skills repo — skipping.", file=sys.stderr)
                continue
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  ✓ {name}")

    print(f"Done. Skills ready in {DEST}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
