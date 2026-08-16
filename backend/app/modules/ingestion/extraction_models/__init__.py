"""Concrete extraction models.

One module per vendor, mirroring `voice/providers/`. Everything vendor-shaped —
tool schemas, content-block layouts, authentication — lives inside its own file
here, so a second model is a sibling module rather than an edit to anything that
extracts.
"""

from app.core.config import Settings
from app.modules.ingestion.extraction_model import ExtractionModel
from app.modules.ingestion.extraction_models.claude import ClaudeExtractionModel


def build_extraction_model(settings: Settings) -> ExtractionModel | None:
    """The configured model, or nothing if this deployment has no credentials.

    The one place that decides which vendor is in use. A second adapter is a
    branch here plus a sibling module, and no caller of `ExtractionModel`
    changes — the property the whole interface exists to preserve.

    Absent rather than fatal, on the same grounds as the voice provider and the
    bucket: auth, balances and the voice loop all work without extraction, and
    `docs/auditor-grounding.md` makes the deckless path first-class rather than
    degraded. A deployment without a key still runs; it just cannot ground a
    session in a document.

    There is no `else` for an unrecognised provider, because there cannot be one
    — `Settings.extraction_provider` is a `Literal`, so a typo is a process that
    refuses to boot. That matters more here than it looks: the alternative
    failure is a deployment that starts, signs people in, accepts uploads, and
    never grounds a single session.
    """
    if settings.extraction_provider == "claude":
        if not settings.anthropic_api_key:
            return None
        return ClaudeExtractionModel(
            api_key=settings.anthropic_api_key,
            model=settings.extraction_model,
            concurrent_calls=settings.extraction_concurrent_calls,
        )

    return None
