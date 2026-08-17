"""Claim reader adapters, one per vendor.

Siblings, never a chain — the property `panel_models/` and
`ingestion/extraction_models/` already establish. A second vendor is a new file
here and a different setting, and nothing that already exists changes.
"""

from __future__ import annotations

import httpx

from app.agents.auditor import ClaimReader
from app.agents.claim_readers.gemini import GeminiClaimReader
from app.core.config import Settings


def build_claim_reader(
    settings: Settings, http: httpx.AsyncClient
) -> ClaimReader | None:
    """The configured claim reader, or nothing if this deployment has no key.

    Absent rather than fatal, and the trade is milder here than for any other
    model in the product: a room without one still transcribes, routes,
    composes, speaks and captions. What it loses is the Auditor catching a
    figure moving — a kind of question, not a session.

    Shares the process-wide HTTP client. A reading is one POST, and a private
    connection pool per adapter would be pool-per-vendor for no reason.

    Keyed off `panel_provider` rather than a setting of its own. Both are text
    models reached through the same account, and a second knob would be a second
    thing to get wrong for a choice nobody is going to make differently — when
    somebody does, it becomes its own setting and this comment is the record of
    why it was not one.
    """
    if settings.panel_provider == "gemini":
        if not settings.gemini_api_key:
            return None
        return GeminiClaimReader(api_key=settings.gemini_api_key, http=http)

    return None
