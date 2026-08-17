"""Assembling the room one socket gets.

The join the rest of Phase 3 has been waiting on. Seating, selection,
composition, casting, transcription and barge-in each existed and were tested in
isolation; nothing put them together into something a phone could reach.

`OrchestratedProvider` is built per room rather than per process — unlike the
transcriber, the model and the speaker, which are process-wide and injected
here. That asymmetry is the whole reason this module exists: which archetypes
are seated and which deck they may attack are facts about one session, and they
live in our database rather than on a vendor's dashboard.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.model import PanelModel
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger
from app.modules.sessions.service import SessionService
from app.modules.sessions.transcript import SessionTranscript
from app.modules.voice.grounding import session_grounding
from app.agents.auditor import ClaimReader
from app.modules.voice.orchestrated import OrchestratedProvider
from app.modules.voice.speech import Speaker
from app.modules.voice.transcription import Transcriber

log = get_logger(__name__, tag="voice")


async def build_room(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    transcriber: Transcriber | None,
    model: PanelModel | None,
    speaker: Speaker | None = None,
    reader: ClaimReader | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> OrchestratedProvider:
    """The room for one session: its panel, its grounding, its vendors.

    Two of the three vendors are required and one is not, and the split is not
    arbitrary. A room that cannot hear or cannot compose is worse than one that
    refuses to open: it bills, it waits, and it never asks a question — and from
    the user's side of a phone lying face-down on a desk, that is
    indistinguishable from a slow model. Refusing here surfaces as the typed,
    unnamed failure the relay already knows how to settle and refund against,
    before a single second is metered.

    A missing claim reader degrades the same way and for the same reason: the
    Auditor is an improvement to a room that already interrogates, so without
    one the panel simply never catches a figure moving.

    A missing speaker degrades instead. Captions are a v1 requirement in their
    own right — `CLAUDE.md` sets the floor at WCAG 2.2 AA *plus live captions* —
    so a silent room still transcribes, routes, composes and captions. It is
    also what lets a deployment without an ElevenLabs key exercise the entire
    loop.
    """
    if transcriber is None:
        log.error("room_has_no_transcriber", session_id=str(session_id))
        raise ProviderUnavailable(reason="transcriber_unconfigured")

    if model is None:
        log.error("room_has_no_panel_model", session_id=str(session_id))
        raise ProviderUnavailable(reason="panel_model_unconfigured")

    sessions = SessionService(db)
    panel = await sessions.panel(session_id=session_id)
    materials = await sessions.materials(session_id=session_id)

    grounding = await session_grounding(
        db, user_id=user_id, material_ids=materials
    )

    # Counts rather than contents. CLAUDE.md forbids transcripts and ingested
    # material in logs, and a claim is ingested material quoted verbatim.
    log.info(
        "room_assembled",
        session_id=str(session_id),
        seated=len(panel),
        claims=len(grounding.claims),
        speaking=speaker is not None,
        auditing=reader is not None,
    )

    return OrchestratedProvider(
        panel=panel,
        transcriber=transcriber,
        model=model,
        speaker=speaker,
        grounding=grounding,
        reader=reader,
        # Built here because this is the only place that knows *which* session a
        # room is, and the store binds that at construction rather than taking it
        # per line — the provenance rule `CLAUDE.md` sets for `LedgerService`.
        #
        # Given the session factory rather than the room's own session, because
        # the channel writes from a task running beside the relay's loop and the
        # two would otherwise flush one `AsyncSession` concurrently. See
        # `SessionTranscript` for the second reason, which is the connection pool.
        #
        # Optional in the same way the speaker is, and it degrades the same way:
        # a room without one still interrogates and still captions. What it
        # loses is the debrief, so nothing that serves a real user may omit it.
        transcript=(
            SessionTranscript(session_factory, session_id=session_id)
            if session_factory is not None
            else None
        ),
    )
