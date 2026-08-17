"""Concrete weakness readers.

One module per vendor, mirroring `panel_models/` and `extraction_models/`.
Everything vendor-shaped lives inside its own file here, so a second reader is a
sibling module rather than an edit to anything that opens a debrief.

**This is the only seam in the codebase with two implementations**, and the
first evidence that the model layer really is swappable rather than merely
described that way. Both were written the same day: Claude first, because the
SDK and tool-use pattern were already here for extraction, and Gemini
immediately after, when funding the Anthropic account turned out not to be
possible. The interface cost nothing to honour and the swap took one file.
"""

import httpx

from app.agents.weakness import WeaknessReader
from app.agents.weakness_models.claude import ClaudeWeaknessReader
from app.agents.weakness_models.gemini import GeminiWeaknessReader
from app.core.config import Settings


def build_weakness_reader(
    settings: Settings, *, http: httpx.AsyncClient | None = None
) -> WeaknessReader | None:
    """The configured reader, or nothing if this deployment has no credentials.

    Absent rather than fatal, matching `build_extraction_model`: auth, balances,
    the room and the transcript all work without one. What a deployment without
    a key loses is the debrief's ranked list — worth saying out loud, because
    `Product.md` §3.5 calls that phase *"the part users will pay for"*, and a
    process that boots happily while unable to produce it is a mistake that only
    surfaces after somebody has finished a session. `docs/deployment.md` is
    where that belongs, not a boot failure.

    `http` is passed in rather than made here because the Gemini reader borrows
    the application's client, the way the panel model does — one connection pool
    per process, not one per debrief.

    No `else`: `Settings.debrief_provider` is a `Literal`, so an unrecognised
    value refuses to boot rather than producing a deployment that silently never
    debriefs.
    """
    if settings.debrief_provider == "gemini":
        if not settings.gemini_api_key or http is None:
            return None
        return GeminiWeaknessReader(
            api_key=settings.gemini_api_key, model=settings.debrief_model, http=http
        )

    if settings.debrief_provider == "claude":
        if not settings.anthropic_api_key:
            return None
        return ClaudeWeaknessReader(
            api_key=settings.anthropic_api_key, model=settings.debrief_model
        )

    return None
