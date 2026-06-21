"""Lily agent package.

Loads a repo-root .env on import so every entrypoint (web server, CLI, tests)
picks up local secrets like GROQ_API_KEY without the key ever being pasted into
a shell or the chat. A real environment variable always wins (setdefault).
"""

import os
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()
