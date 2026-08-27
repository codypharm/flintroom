"""What a room is allowed to attack, for one session.

Where seats and claims meet. `Grounding` is the panel's whole view of the world
— `CLAUDE.md` refuses to ship interrogation logic that cannot cite its source,
and Open Risk #2 is that ungrounded generic questions kill retention faster than
any UI flaw — so an empty one is not a neutral default. It is the competitor
product.

Reads ingestion's claims directly rather than through `IngestionService`, which
would drag object storage into the voice module to construct. Nothing here signs
a URL or touches a file; the claims are text, and the source document is deleted
once extraction succeeds anyway (`docs/ingestion.md`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.auditor import WrittenClaim
from app.agents.context import Grounding, Said
from app.modules.ingestion.citations import citable_row
from app.modules.ingestion.models import MaterialClaim
from app.modules.ingestion.schemas import ClaimKind, QuantitativeClaim


async def session_grounding(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    material_ids: Sequence[uuid.UUID],
    transcript: Sequence[Said] = (),
) -> Grounding:
    """Everything one room may quote, in reading order.

    `user_id` is a predicate on the query rather than an assumption inherited
    from the caller. The ids arrive from rows already bound to a session whose
    ticket was redeemed, so it should never exclude anything — it is here
    because `CLAUDE.md` says deny by default, and because the failure it
    prevents is the worst this module could have: another user's confidential
    deck read aloud by a panelist, in a live room, as an attack.

    An empty result is a legitimate room rather than an error. Material is
    optional, and `docs/auditor-grounding.md` covers the unattached case
    deliberately — without a deck the panel still has the user's own words to
    catch contradictions in. Refusing here would make attachment mandatory by
    accident.
    """
    if not material_ids:
        return Grounding(transcript=tuple(transcript))

    rows = await db.scalars(
        select(MaterialClaim)
        .where(
            MaterialClaim.material_id.in_(material_ids),
            MaterialClaim.user_id == user_id,
        )
        .order_by(MaterialClaim.page, MaterialClaim.created_at)
    )

    return Grounding(
        claims=tuple(citable_row(row) for row in rows),
        transcript=tuple(transcript),
    )


async def written_claims(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    material_ids: Sequence[uuid.UUID],
) -> tuple[WrittenClaim, ...]:
    """The deck's figures in the Auditor's own shape, page numbers attached.

    The structured half of the rows `session_grounding` renders into citable
    lines — and until 2026-08-27 the half that was dropped on the floor, which
    left the Auditor's written pool permanently empty and the deck-vs-speech
    check `docs/auditor-grounding.md` calls *exact* silently unwired. The first
    Play-build room proved it the hard way: a deck of planted contradictions,
    zero findings.

    Quantitative rows only. An assertion has no value to move, and the doc
    holds qualitative findings for the debrief rather than a live interrupt.
    Same ownership predicate as the rendering query, for the same worst-case.
    """
    if not material_ids:
        return ()

    rows = await db.scalars(
        select(MaterialClaim)
        .where(
            MaterialClaim.material_id.in_(material_ids),
            MaterialClaim.user_id == user_id,
            MaterialClaim.kind == ClaimKind.QUANTITATIVE,
        )
        .order_by(MaterialClaim.page, MaterialClaim.created_at)
    )

    return tuple(
        WrittenClaim(
            claim=QuantitativeClaim(
                quote=row.quote,
                metric=row.metric or "",
                value=float(row.value or 0),
                unit=row.unit,
                period=row.period,
            ),
            page=row.page,
        )
        for row in rows
    )
