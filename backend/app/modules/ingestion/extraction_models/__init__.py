"""Concrete extraction models.

One module per vendor, mirroring `voice/providers/`. Everything vendor-shaped —
schema dialects, content layouts, authentication — lives inside its own file
here. What reading a deck *means* lives in `reading.py` and is shared, which is
what made the second adapter small rather than a copy.
"""

import httpx

from app.core.config import Settings
from app.modules.ingestion.extraction_model import ExtractionModel
from app.modules.ingestion.extraction_models.claude import ClaudeExtractionModel
from app.modules.ingestion.extraction_models.gemini import GeminiExtractionModel


def build_extraction_model(
    settings: Settings, *, http: httpx.AsyncClient | None = None
) -> ExtractionModel | None:
    """The configured model, or nothing if this deployment has no credentials.

    The one place that decides which vendor is in use. A third adapter is a
    branch here plus a sibling module, and no caller of `ExtractionModel`
    changes — the property the whole interface exists to preserve.

    Absent rather than fatal, on the same grounds as the voice provider and the
    bucket: auth, balances and the voice loop all work without extraction, and
    `docs/auditor-grounding.md` makes the deckless path first-class rather than
    degraded. A deployment without a key still runs; it just cannot ground a
    session in a document, and `main.py` logs `extraction_model_unconfigured`
    once at boot so that is a stated condition rather than a discovery.

    `http` is passed in for the Gemini adapter, which borrows the application's
    client the way the panel model does — one connection pool per process, not
    one per deck. The Claude adapter builds its own through the SDK.

    There is no `else` for an unrecognised provider, because there cannot be one
    — `Settings.extraction_provider` is a `Literal`, so a typo is a process that
    refuses to boot. That matters more here than it looks: the alternative
    failure is a deployment that starts, signs people in, accepts uploads, and
    never grounds a single session.
    """
    if settings.extraction_provider == "gemini":
        if not settings.gemini_api_key or http is None:
            return None
        return GeminiExtractionModel(
            api_key=settings.gemini_api_key,
            model=settings.extraction_model,
            concurrent_calls=settings.extraction_concurrent_calls,
            http=http,
        )

    if settings.extraction_provider == "claude":
        if not settings.anthropic_api_key:
            return None
        return ClaudeExtractionModel(
            api_key=settings.anthropic_api_key,
            model=settings.extraction_model,
            concurrent_calls=settings.extraction_concurrent_calls,
        )

    return None
