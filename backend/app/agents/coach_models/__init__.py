"""Concrete coach models.

One module per vendor, mirroring `panel_models/` and `weakness_models/`.
"""

import httpx

from app.agents.coach import CoachModel
from app.agents.coach_models.gemini import GeminiCoachModel
from app.core.config import Settings


def build_coach_model(
    settings: Settings, *, http: httpx.AsyncClient | None = None
) -> CoachModel | None:
    """The configured coach, or nothing if this deployment has no credentials.

    Absent rather than fatal, matching every other model edge. A deployment
    without one still produces the ranked list — that is a different seam and a
    different call — so what is lost is the *conversation*, which is worth
    logging once at boot rather than discovering when somebody speaks and
    nothing answers.
    """
    if settings.debrief_provider == "gemini":
        if not settings.gemini_api_key or http is None:
            return None
        return GeminiCoachModel(
            api_key=settings.gemini_api_key, model=settings.coach_model, http=http
        )

    return None
