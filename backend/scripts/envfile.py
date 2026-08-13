"""Read a value out of the local `.env`.

Scripts are run by a person at a terminal, not by the app, so they do not go
through `Settings` — which requires the full production set (JWT secret, both
OAuth client ids) and would refuse to load for want of a value no script uses.
It also echoes the values it dislikes into its error message, which is how a
secret ends up in a terminal transcript.
"""

from __future__ import annotations

from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def read_env(name: str) -> str:
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") and not line.startswith("#"):
            return line.partition("=")[2].strip().strip('"').strip("'")
    raise SystemExit(f"{name} not found in {ENV_FILE}")
