"""What a rehearsal is called, resolved from the rooms in it.

There is no `rehearsals` table and deliberately so: a lineage is a group id every
room already carries, and a table would turn `rehearsal_id` into a foreign key,
a row to create on every fresh start, and something to clean up. The one thing a
group needs that a room cannot answer alone is its **name**, and that is what
this module works out.

**The newest name in a group is the group's.** Almost nobody names the first
room — they discover on the third attempt that they are working on a *thing*. If
only the root room could carry a name, that presenter could never name their
rehearsal at all, and the screen the name exists for would stay headed by a
date. So any room may be given one, and the latest one wins.

Two shapes, because the two callers ask different questions. A response about
one room asks about one lineage; a history asks about all of them, and calling
the first once per room would be fifty queries for a list.

Both are scoped by `user_id` in the `WHERE` clause rather than by a check
afterwards. A lineage is a set of rows, so there is no single id to compare —
the same reason `SessionService.recent` filters rather than asserts.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sessions.models import Session

#: The group id, with the null-means-itself rule applied. Every read of a
#: lineage goes through this expression so "which group is this room in" has one
#: answer — the same one `Session.rehearsal` gives in Python.
GROUP = func.coalesce(Session.rehearsal_id, Session.id)


def _named(user_id: uuid.UUID) -> Select:
    """Every room this account named, oldest first.

    Oldest first because both callers fold the rows into a dict and let later
    values overwrite earlier ones — which makes "the newest name wins" a
    property of the ordering rather than a comparison somebody has to write
    twice.

    Only rows with a name, which is nearly always a small fraction of them: the
    field is optional, and a run of rehearsals carries one name between them.
    """
    return (
        select(GROUP.label("rehearsal"), Session.rehearsal_name)
        .where(
            Session.user_id == user_id,
            Session.rehearsal_name.is_not(None),
        )
        .order_by(Session.started_at.asc())
    )


async def names_of(db: AsyncSession, *, user_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """Every rehearsal this account has named, by group id.

    One query for a whole history. The rows are folded oldest-to-newest, so the
    last write for a group is the newest name given to it.
    """
    return {
        row.rehearsal: row.rehearsal_name
        for row in (await db.execute(_named(user_id))).all()
    }


async def name_of(
    db: AsyncSession, *, user_id: uuid.UUID, rehearsal: uuid.UUID
) -> str | None:
    """What one lineage is called, or null if nobody named it.

    For the three responses about a single room. `LIMIT 1` off the reversed
    order rather than folding a dict, because there is nothing to fold.
    """
    return await db.scalar(
        _named(user_id)
        .where(GROUP == rehearsal)
        .order_by(None)
        .order_by(Session.started_at.desc())
        .limit(1)
        .with_only_columns(Session.rehearsal_name)
    )
