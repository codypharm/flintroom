"""The published API contract, kept honest.

`contracts/openapi.yaml` is what the frontend client is generated from, so it is
the one file in the repo whose staleness is invisible from inside the backend:
every test here passes against the running app, and the app never reads the
contract. A drifted contract shows up as a mobile build compiling against
endpoints that no longer exist.

Committed rather than served live for the same reason the migrations are
committed rather than derived from the models — a generated artefact nobody
reviews is a generated artefact nobody notices changing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.main import create_app

CONTRACT = Path(__file__).resolve().parent.parent.parent / "contracts" / "openapi.yaml"


def test_the_committed_contract_matches_the_application():
    """Regenerate with `uv run python -m scripts.export_openapi` when this fails.

    The failure is the point: adding an endpoint and not publishing it is a
    silent divergence, and the alternative — generating the contract during the
    build — means a breaking change reaches the frontend without anyone having
    read it in a diff.
    """
    published = yaml.safe_load(CONTRACT.read_text())

    assert published == create_app().openapi()
