"""Dash's code sandbox — the workspace + execution layer behind the skill tools.

Dash works like Claude Code does with the document skills: it reads a SKILL.md,
writes a build script (pptxgenjs / docx-js / reportlab), runs it, and a finished
.pptx / .pdf / .docx lands in its workspace. This module is the thin, auditable
boundary that makes that possible.

Each Dash conversation gets its OWN workspace dir (keyed by session id) so it can
iterate across turns — write a script, run it, inspect output, fix, re-run. The
vendored skills live next door and are exposed to scripts via $DASH_SKILLS_DIR;
Node deps (pptxgenjs, docx) resolve from agents/dash/node_modules via NODE_PATH.

⚠️ SECURITY: run_bash executes model-generated commands on the host. That is the
whole point (it's how skills work), but it means Dash must run behind the same
trust boundary as an internal tool — localhost / an authenticated internal app,
never an anonymous public endpoint. Commands are confined to the session
workspace (cwd) and bounded by a timeout, but this is NOT a hardened jail. For a
public deployment, put this behind a container or a restricted user.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

DASH_DIR = Path(__file__).resolve().parent
REPO_ROOT = DASH_DIR.parents[1]
SKILLS_DIR = DASH_DIR / "skills"
NODE_MODULES = DASH_DIR / "node_modules"
ASSETS_DIR = REPO_ROOT / "assets"
WORKSPACE_ROOT = Path(os.environ.get("DASH_WORKSPACE", str(DASH_DIR / "workspace")))
# Finished docs are copied here so the existing /api/dash/download/<file> endpoint
# (a flat dir keyed by filename) can serve them without per-session URL routing.
OUTPUT_DIR = Path(os.environ.get("DASH_OUTPUT_DIR", "/tmp/dash_output"))

OUTPUT_EXTS = (".pptx", ".pdf", ".docx", ".xlsx")
MAX_OUTPUT_CHARS = 12_000
DEFAULT_TIMEOUT = int(os.environ.get("DASH_EXEC_TIMEOUT", "180"))


def session_dir(session_id: str) -> Path:
    """Workspace for one Dash conversation. Stable across turns so Dash can iterate.
    Brand assets (logo) are copied in on first creation so build scripts can reference
    them as ./evergreen-logo.png."""
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "default"
    d = WORKSPACE_ROOT / safe
    fresh = not d.exists()
    d.mkdir(parents=True, exist_ok=True)
    if fresh and ASSETS_DIR.is_dir():
        for asset in ASSETS_DIR.glob("*"):
            if asset.is_file():
                dest = d / asset.name
                if not dest.exists():
                    shutil.copy2(asset, dest)
    return d


def _exec_env() -> dict[str, str]:
    env = dict(os.environ)
    # `require('pptxgenjs')` / `require('docx')` resolve from the dash-level
    # node_modules even though scripts run inside the session workspace.
    node_path = str(NODE_MODULES)
    if env.get("NODE_PATH"):
        node_path += os.pathsep + env["NODE_PATH"]
    env["NODE_PATH"] = node_path
    # Skill scripts (validators, soffice wrapper, thumbnailers) are referenced by
    # absolute path; expose their root so Dash can call them portably.
    env["DASH_SKILLS_DIR"] = str(SKILLS_DIR)
    return env


def _within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def write_file(session_id: str, path: str, content: str) -> dict:
    """Write a file into the session workspace. Paths can't escape the workspace."""
    base = session_dir(session_id)
    target = base / path
    if not _within(base, target):
        return {"error": f"path '{path}' escapes the workspace"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target.relative_to(base)), "bytes": len(content.encode())}


def read_file(session_id: str, path: str, max_chars: int = MAX_OUTPUT_CHARS) -> dict:
    base = session_dir(session_id)
    target = base / path
    if not _within(base, target):
        return {"error": f"path '{path}' escapes the workspace"}
    if not target.exists():
        return {"error": f"no such file: {path}"}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"error": f"could not read {path}: {exc}"}
    return {"content": text[:max_chars], "truncated": len(text) > max_chars}


def run_bash(session_id: str, command: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a shell command inside the session workspace. Returns exit code + output
    (stdout, then stderr), truncated. Confined to cwd + bounded by a timeout."""
    base = session_dir(session_id)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(base),
            env=_exec_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "output": f"[command timed out after {timeout}s]", "truncated": False}
    out = proc.stdout or ""
    if proc.stderr:
        out += ("\n" if out else "") + "[stderr]\n" + proc.stderr
    return {
        "exit_code": proc.returncode,
        "output": out[:MAX_OUTPUT_CHARS] or "[no output]",
        "truncated": len(out) > MAX_OUTPUT_CHARS,
    }


def read_skill(skill: str, file: str | None = None) -> dict:
    """Return a vendored skill file (SKILL.md by default, or a named reference like
    'pptxgenjs.md', 'editing.md', 'reference.md', 'forms.md')."""
    skill = (skill or "").strip().lower()
    sd = SKILLS_DIR / skill
    if not sd.is_dir():
        if not SKILLS_DIR.is_dir() or not any(SKILLS_DIR.iterdir()):
            return {"error": (
                "Doc skills are not installed. They are Anthropic proprietary and "
                "not committed to this repo — run `python agents/dash/fetch_skills.py` "
                "to fetch docx/pdf/pptx into agents/dash/skills/."
            )}
        return {"error": f"unknown skill '{skill}'. Available: docx, pdf, pptx."}
    target = sd / (file or "SKILL.md")
    if not _within(sd, target) or not target.is_file():
        avail = sorted(p.name for p in sd.glob("*.md"))
        return {"error": f"no file '{file}' in {skill} skill. Markdown files: {avail}"}
    return {
        "skill": skill,
        "file": target.name,
        "skills_dir": str(SKILLS_DIR),
        "content": target.read_text(encoding="utf-8", errors="replace"),
    }


def collect_new_outputs(session_id: str, seen: set[tuple[str, int]]) -> list[dict]:
    """Find finished documents in the workspace not yet delivered this run, copy
    each into OUTPUT_DIR under a unique name, and return download descriptors.
    `seen` is mutated so the same artifact isn't re-emitted across turns."""
    base = session_dir(session_id)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    found: list[dict] = []
    for p in base.rglob("*"):
        if p.suffix.lower() not in OUTPUT_EXTS or not p.is_file():
            continue
        key = (str(p), int(p.stat().st_mtime))
        if key in seen:
            continue
        seen.add(key)
        dl_name = f"{p.stem}-{uuid.uuid4().hex[:6]}{p.suffix}"
        try:
            shutil.copy2(p, OUTPUT_DIR / dl_name)
        except Exception:
            continue
        found.append({"filename": dl_name, "display": p.name, "path": str(OUTPUT_DIR / dl_name)})
    return found
