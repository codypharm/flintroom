"""What a room spends, recorded while it spends it.

`SessionCost` has carried a column per vendor since Phase 2 and nothing filled
them. That was defensible while a room was one agent on one opaque per-minute
rate: its duration was very nearly the whole story. It stopped being true the
moment the panel became ours — a single turn now bills the transcriber by the
second, the panel model by the token, and synthesis by the character.

Open Risk #4 says every margin in `Product.md` §4.4 rests on an unverified
$0.12/min, and `CLAUDE.md` refuses to let pricing ship or change without
observed cost behind it. Until these columns hold something, nothing in the
system could contradict that figure — which is the definition of an assumption
rather than a measurement.

Written per turn rather than at settlement. A session whose process dies is
settled later by the reaper, which never held the channel, so anything
accumulated in memory would be lost for exactly the rooms where cost and
revenue diverge most: the ones three providers charged for and the user was
refunded.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.billing.models import Account
from app.modules.sessions.models import Session
from app.modules.voice.costs import SessionCost

log = get_logger(__name__, tag="voice")


class SpendRecorder:
    """Adds one turn's provider consumption to a session's cost row."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record(
        self,
        *,
        session_id: uuid.UUID,
        stt_seconds: int = 0,
        llm_input_tokens: int = 0,
        llm_output_tokens: int = 0,
        tts_characters: int = 0,
    ) -> None:
        """Accumulate, never replace.

        A room is the sum of its turns. An upsert that overwrote would record
        only the last one, so every session would look like a single-question
        session — and the error would grow with precisely the rooms that went
        well and asked the most.

        Insert-or-add rather than read-modify-write: the addition happens inside
        the statement, so two writers cannot both read the same total and each
        add to it. Contention is per session and a user holds one at a time,
        which keeps this serialised against itself and never against another
        user — the property `docs/deferred-scale-work.md` requires the write
        path to preserve.

        This is telemetry, not money. It is deliberately not a `ledger_entries`
        row and never touches a balance: what the user is charged is minutes,
        decided by the meter, and nothing here may influence it.
        """
        owner = await self._owner_of(session_id)
        if owner is None:
            # A room whose session vanished mid-turn. Logged rather than raised:
            # the providers have already charged, but a live interrogation must
            # not end over a telemetry write.
            log.warning("spend_unattributable", session_id=str(session_id))
            return

        user_id, tier = owner
        totals = {
            "stt_seconds_processed": stt_seconds,
            "llm_input_tokens": llm_input_tokens,
            "llm_output_tokens": llm_output_tokens,
            "tts_characters_synthesized": tts_characters,
        }
        statement = insert(SessionCost).values(
            session_id=session_id,
            user_id=user_id,
            # Settlement rewrites this with the tier as it stood when billing
            # closed, which is the authoritative one. Supplied here only because
            # the column is not nullable and this may be the insert that creates
            # the row.
            tier=tier,
            **totals,
        )
        await self._db.execute(
            statement.on_conflict_do_update(
                index_elements=["session_id"],
                set_={
                    column: getattr(SessionCost, column) + value
                    for column, value in totals.items()
                },
            )
        )
        await self._db.commit()

    async def _owner_of(self, session_id: uuid.UUID) -> tuple[uuid.UUID, str] | None:
        """Whose room this is, and what they were on.

        Read from the session rather than passed in by the relay, which holds
        the owner only as an audit actor string. Deriving it here means a cost
        row cannot be attributed to anyone but the account that owns the
        session — the one mistake in this module that would be both silent and
        unrecoverable, since it corrupts the per-tier grouping every §4.3
        figure is computed from.
        """
        result = await self._db.execute(
            select(Session.user_id, Account.entitlement_tier)
            .join(Account, Account.user_id == Session.user_id)
            .where(Session.id == session_id)
        )
        return result.one_or_none()

    async def spent_coaching(
        self,
        *,
        session_id: uuid.UUID,
        debrief_seconds: int,
        sparring_seconds: int,
    ) -> None:
        """How long they stayed. **Set, never added** — and that is the whole
        difference from `record` above.

        A room is the sum of its turns, so token counts accumulate. A duration
        is not a sum: it is the distance between the first coaching turn and the
        last, recomputed from the turn timestamps every time one lands. Adding
        it would count the same minutes once per turn and produce a debrief
        somebody apparently spent an hour in.

        **The two overlap and must never be summed.** With turn-based transport
        there is no moment where somebody leaves the debrief and enters
        sparring — a re-try is a turn among turns — so `debrief_seconds` is the
        whole coaching engagement and `sparring_seconds` is the subset spent
        re-answering. Adding them double-counts the same minutes and inflates
        the one figure §4.3 uses to decide whether the soft cap is tight enough.

        No `_owner_of` guard, unlike `record`: this only ever runs after a
        coaching turn has already been written against a session that
        `DebriefService` resolved and found settled, so the row and the owner
        are both established by the time this is reached.
        """
        await self._db.execute(
            update(SessionCost)
            .where(SessionCost.session_id == session_id)
            .values(
                debrief_seconds=debrief_seconds, sparring_seconds=sparring_seconds
            )
        )
        await self._db.commit()
