"""The archetype catalogue, as the caller's plan sees it.

Thin, and it stays thin: the library is configuration in `agents/archetypes.py`
and nothing here decides who is in it. What this owns is the one thing a router
may not do — reading the caller's tier out of the database — and the translation
from a library entry to the narrower thing a client is allowed to see.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.archetypes import LIBRARY
from app.core.errors import AccountNotFound
from app.modules.billing.models import Account
from app.modules.billing.tiers import (
    max_panel_size,
    may_author_archetypes,
    next_tier_above,
)
from app.modules.panels.schemas import ArchetypeCatalogue, ArchetypeRead


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
            seats=max_panel_size(tier),
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
