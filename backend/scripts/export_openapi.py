"""Write the API contract to `contracts/openapi.yaml`.

Run after adding or changing an endpoint:

    uv run python -m scripts.export_openapi

`tests/test_contract.py` fails until you do, which is the intended order:
backend, then contract, then the generated frontend client (CLAUDE.md → Build
Sequence).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.main import create_app

CONTRACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "openapi.yaml"


def export() -> Path:
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT.write_text(
        yaml.safe_dump(
            create_app().openapi(),
            # Key order is the app's, not alphabetical: reordering on every
            # export would make each diff unreadable, which defeats committing
            # the file at all.
            sort_keys=False,
            allow_unicode=True,
        )
    )
    return CONTRACT


if __name__ == "__main__":
    print(export())
