"""Panel model adapters, one per vendor.

Siblings, never a chain. A second vendor is a new file here and a different value
for `PANEL_PROVIDER` — nothing that already exists changes, which is the property
`ingestion/extraction_models/` established and this follows.
"""

from __future__ import annotations

import httpx

from app.agents.model import PanelModel
from app.agents.panel_models.gemini import GeminiPanelModel
from app.core.config import Settings


def build_panel_model(settings: Settings, http: httpx.AsyncClient) -> PanelModel | None:
    """The configured panel model, or nothing if this deployment has no key.

    The one place that decides which vendor speaks. A second adapter is a branch
    here plus a sibling module, and no caller of `PanelModel` changes.

    Absent rather than fatal, on the same grounds as the voice provider, the
    bucket and the extraction model: a deployment without a key still signs
    people in, still tracks balances, still ingests decks. It just cannot hold an
    interrogation, and refusing to boot would take everything else down with it.

    The HTTP client is injected rather than made here, so the panel shares the
    process-wide one built in the app lifespan — a model call is one POST, and a
    private connection pool per adapter would be pool-per-vendor for no reason.

    There is no `else` for an unrecognised provider, because there cannot be one:
    `panel_provider` is a `Literal`, so a typo refuses to boot.
    """
    if settings.panel_provider == "gemini":
        if not settings.gemini_api_key:
            return None
        return GeminiPanelModel(
            api_key=settings.gemini_api_key,
            http=http,
            selection_model=settings.panel_selection_model,
            composition_model=settings.panel_composition_model,
        )

    return None
