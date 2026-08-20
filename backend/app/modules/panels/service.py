"""The archetype catalogue, as the caller's plan sees it.

Thin, and it stays thin: the library is configuration in `agents/archetypes.py`
and nothing here decides who is in it. What this owns is the one thing a router
may not do — reading the caller's tier out of the database — and the translation
from a library entry to the narrower thing a client is allowed to see.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.archetypes import LIBRARY
from app.agents.difficulty import GENTLE, LADDER
from app.agents.difficulty import pressure_at as _pressure_at
from app.core.errors import AccountNotFound
from app.core.logging import get_logger
from app.modules.billing.models import Account
from app.modules.billing.tiers import (
    max_panel_size,
    may_author_archetypes,
    next_tier_above,
)
from app.modules.onboarding.service import OnboardingService
from app.agents.vocabulary import DOMAIN_TERMS
from app.agents.voices import CASTABLE, VOICE_BLURBS
from app.modules.panels.schemas import ArchetypeCatalogue, ArchetypeRead, VoiceRead

log = get_logger(__name__, tag="panel")


def _rung_of(level: int) -> int:
    """A stored level, brought onto the ladder.

    Expressed through `pressure_at` rather than by repeating the clamp, so
    there is one arithmetic for what a rung is. The index falls out of the
    resulting pair being the one the ladder holds.
    """
    return LADDER.index(_pressure_at(level)) + 1


class PanelCatalogueService:
    """Reads. Never writes — there is nothing here to write."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def catalogue(self, *, user_id: uuid.UUID) -> ArchetypeCatalogue:
        """Every archetype we ship, plus what this caller's plan does with them.

        **The roster is not filtered by tier**, and that is the one judgement in
        this file. Seats limit how many go in a room, never which exist — a
        catalogue that hid the archetypes a free account cannot afford would hide
        exactly what the upgrade buys, at the one moment the upsell is a fact
        rather than an interruption.
        """
        tier = await self._tier_of(user_id)
        above = next_tier_above(tier)
        seats = max_panel_size(tier)

        return ArchetypeCatalogue(
            archetypes=[
                # Field by field, not `model_validate`. A library entry gains a
                # field far more often than this schema does, and the next one is
                # likelier to be prompt text than anything a user should read.
                ArchetypeRead(
                    name=archetype.name,
                    title=archetype.title,
                    blurb=archetype.blurb,
                )
                for archetype in LIBRARY
            ],
            difficulty=await self._difficulty_of(user_id),
            seats=seats,
            seated=[
                archetype.name
                for archetype in await OnboardingService(self._db).room_for(
                    user_id=user_id, seats=seats
                )
            ],
            domains=sorted(DOMAIN_TERMS),
            voices=[
                VoiceRead(name=voice.value, sounds=VOICE_BLURBS[voice])
                for voice in sorted(CASTABLE, key=lambda one: one.value)
            ],
            may_author=may_author_archetypes(tier),
            upgrade_seats=max_panel_size(above) if above else None,
        )

    async def _tier_of(self, user_id: uuid.UUID) -> str:
        tier = await self._db.scalar(
            select(Account.entitlement_tier).where(Account.user_id == user_id)
        )
        if tier is None:
            raise AccountNotFound(user_id=str(user_id))
        return tier

    async def _difficulty_of(self, user_id: uuid.UUID) -> int:
        """The rung this account is on, clamped onto the ladder.

        Clamped on the way out even though `choose` refuses anything off it:
        the column could hold a rung a later release removed, and a picker that
        crashed on it would take the whole setup screen with it.
        """
        stored = await self._db.execute(
            select(Account.difficulty_level).where(Account.user_id == user_id)
        )
        return _rung_of(stored.scalar_one_or_none() or GENTLE)

    async def choose(self, *, user_id: uuid.UUID, difficulty: int) -> int:
        """Set the rung, because the user asked for it.

        `docs/difficulty-calibration.md` decisions 5 and 6: they may move it in
        either direction, and calibration carries on from wherever they leave
        it. Not a floor — an exec who asked for the hardest room and was
        destroyed by it must still be softened next time, which is the one
        mechanism built to prevent that churn.

        Safe downward only because of where the floor is. Level 1 still presses
        an unanswered question, so somebody who drags this to the bottom gets a
        gentler room and cannot turn the wedge off.
        """
        await self._db.execute(
            update(Account)
            .where(Account.user_id == user_id)
            .values(difficulty_level=difficulty)
        )
        await self._db.commit()
        log.info("difficulty_chosen", user_id=str(user_id), level=difficulty)
        return difficulty
