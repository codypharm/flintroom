"""Recording what somebody said about their meeting, and reading it back as a room.

Two writes in one transaction, because they are one answer. The durable half —
role and audience — lands on `user_preferences`; the occasion lands on
`situations`. Splitting them across two calls would allow an account whose
preferences were saved and whose meeting was not, which is a user who described
a board review and gets asked about it again on the next launch.

**This module writes a table another module declares.** `UserPreference` lives
in `sessions/models.py`, where the recording toggle put it. That is worth
naming rather than hiding: the alternative is a second preferences table owned
here, and two tables answering "what has this account chosen" is a worse problem
than one import across a module line.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.archetypes import Archetype
from app.agents.composition import compose
from app.core.logging import get_logger
from app.modules.onboarding.models import Situation
from app.modules.onboarding.schemas import Answers
from app.modules.sessions.models import UserPreference

log = get_logger(__name__, tag="onboarding")


class OnboardingService:
    """What a new account said about the room it is rehearsing for."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record(self, *, user_id: uuid.UUID, answers: Answers) -> None:
        """Store the plan, both halves, atomically.

        Upserts the preferences rather than inserting: sign-in is the only
        caller, sign-in is retryable, and a network that dropped the response
        would otherwise turn the retry into a primary-key violation reported to
        the user as a failed sign-in.

        The situation is appended and never upserted, because a second meeting
        is a second occasion rather than a correction of the first.

        **Never logged with its contents.** What somebody is preparing for, and
        when, is the most identifying thing this flow collects; the count is
        enough to answer "did onboarding run".
        """
        await self._db.execute(
            insert(UserPreference)
            .values(
                user_id=user_id,
                presenter_role=answers.role,
                audience=answers.audience,
            )
            .on_conflict_do_update(
                index_elements=[UserPreference.user_id],
                set_={
                    "presenter_role": answers.role,
                    "audience": answers.audience,
                },
            )
        )

        if answers.situation is not None:
            self._db.add(
                Situation(
                    user_id=user_id,
                    kind=answers.situation,
                    happens_on=answers.happens_on,
                )
            )

        await self._db.commit()

        log.info(
            "onboarding_recorded",
            user_id=str(user_id),
            seats_placed=len(answers.audience),
            has_situation=answers.situation is not None,
            has_date=answers.happens_on is not None,
        )

    async def room_for(
        self, *, user_id: uuid.UUID, seats: int
    ) -> tuple[Archetype, ...]:
        """The panel this account's answers describe.

        Derived on every read rather than stored at sign-up, so that a change to
        `composition`'s tables reaches accounts that already exist. A frozen
        list would mean the reveal and the room agreed only until the next
        release, which is the disagreement this whole design exists to prevent.

        An account that never answered anything still gets a room — `compose`
        falls through to the shipped default — so this never returns empty and
        callers need no special case for a user who skipped the survey.
        """
        chosen = (
            await self._db.execute(
                select(UserPreference.presenter_role, UserPreference.audience).where(
                    UserPreference.user_id == user_id
                )
            )
        ).one_or_none()

        role, audience = chosen if chosen is not None else (None, [])

        return compose(audience=audience, role=role, seats=seats)
