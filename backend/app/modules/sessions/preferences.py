"""What an account has chosen about its own rooms.

One preference so far, and it is the one `docs/session-retention.md` promised
would exist: the disclosure at first session says saving can be turned off in
Settings, and a disclosure pointing at a control that does nothing is worse than
no disclosure at all.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.billing.models import Account
from app.modules.billing.tiers import FREE_TIER, RECORDING_RETENTION_DAYS
from app.modules.sessions.models import UserPreference

log = get_logger(__name__, tag="sessions")


class PreferenceService:
    """Reads and writes one account's choices."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def records_rooms(self, *, user_id: uuid.UUID) -> bool:
        """Whether this account's interrogations should be recorded.

        **The absence of a row means yes.** Nothing writes a preference at
        signup — that would be a row per account holding a value every account
        shares — so a missing row is the default rather than an unknown, and
        reading it as "off" would silently disable the feature for everybody who
        has never opened Settings.
        """
        preference = await self._db.get(UserPreference, user_id)
        return True if preference is None else preference.records_rooms

    async def retention_days(self, *, user_id: uuid.UUID) -> int:
        """How long this account's rooms stay playable.

        Published here rather than on `/v1/me` because it belongs to the same
        question the toggle answers — whether we record you, and for how long we
        keep it — and a client that could read one without the other could
        disclose "your rooms are saved" with nothing truthful after it.

        Read from the tier *now*, matching the sweep and the playback expiry
        exactly. Three places apply this rule and all three read it live, so an
        upgrade or downgrade needs nothing rewritten anywhere.
        """
        tier = await self._db.scalar(
            select(Account.entitlement_tier).where(Account.user_id == user_id)
        )
        return RECORDING_RETENTION_DAYS.get(
            tier or FREE_TIER, RECORDING_RETENTION_DAYS[FREE_TIER]
        )

    async def set_records_rooms(self, *, user_id: uuid.UUID, enabled: bool) -> None:
        """Turn recording on or off for future rooms.

        Upsert rather than insert, because a toggle is flipped more than once
        and the second write would otherwise be a primary key violation — a 500
        raised by the Settings control that exists to reassure somebody about
        their privacy.

        Affects rooms started *after* this. Existing recordings are left alone
        on purpose: they were made under a disclosure the user accepted, and
        destroying them as a side effect of a switch would be a surprise in the
        one direction that cannot be undone. Deleting a room is its own action.

        Logged as a money movement is not — nothing here touches a balance — but
        logged all the same, because "when did this account turn recording off"
        is a question a privacy complaint asks and only this line answers.
        """
        await self._db.execute(
            insert(UserPreference)
            .values(user_id=user_id, records_rooms=enabled)
            .on_conflict_do_update(
                index_elements=[UserPreference.user_id],
                set_={"records_rooms": enabled},
            )
        )
        await self._db.commit()
        log.info(
            "recording_preference_set", user_id=str(user_id), records_rooms=enabled
        )
