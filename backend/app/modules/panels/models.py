"""Panelists a user wrote, stored as rows rather than shipped as config.

`docs/custom-archetypes.md` is the resolved design and this file is only its
storage. Two of its decisions live here as columns and are the reason the shape
looks the way it does.

**Immutable once seated (§4).** `session_panelists` stores a *name*, not a
snapshot — deliberately, so improving an archetype's wording does not freeze old
rooms. That holds while archetypes are ours and few, and its own docstring named
this feature as the moment to revisit it. So a row that has ever been seated is
never mutated: an edit writes a new row and retires the old, and the name in
`session_panelists` keeps pointing at the text that was actually in the room.

**Archive, never destroy (§4).** `archived_at` is what "delete" sets. The row
leaves the picker and stops being seatable, and stays readable for every room
that used it — rooms are kept for the life of the account, and the Library,
Progress, the transcript and the debrief all render who was there. Which is why
the control must read *remove from your panel* and never *delete*: a user who
archives one has not deleted their data, and `docs/privacy-policy.md` has to say
so. Account deletion is the real delete, and this table is in `PURGED`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

#: How long a user's own description of a panelist may be.
#:
#: Far shorter than `Archetype.persona`'s 2000, which is tuned prompt text we
#: write. This is the one field a user's words reach a prompt through
#: (`docs/custom-archetypes.md` §2), and the cap is part of the fencing rather
#: than a storage concern: a paragraph describes somebody, and a page is room to
#: argue with the instructions underneath it.
PERSONA_LIMIT = 400

#: What the picker, the transcript and the Library call this panelist.
TITLE_LIMIT = 64


class CustomArchetype(Base):
    """One panelist an account wrote.

    Never seated automatically. `agents/composition.py`'s `compose()` takes no
    `user_id` and no database and resolves through constants, so the reveal and
    the re-run path are structurally incapable of picking one of these. They are
    chosen by hand or not at all.
    """

    __tablename__ = "custom_archetypes"
    __table_args__ = (
        # The name is minted, so this is belt and braces — but it is the one
        # guard that survives somebody bypassing the service. A row whose name
        # does not carry the prefix would be resolvable by `by_name()` and could
        # shadow a shipped archetype, which is the failure §5 exists to make
        # impossible rather than catchable.
        CheckConstraint("name LIKE 'custom:%'", name="ck_custom_archetypes_name"),
        # No two live panelists on one account may share a title, or the picker
        # shows the same word twice and the Library cannot be read. Archived
        # rows are excluded: a title has to be reusable after its holder is
        # retired, and a retired one still has to keep its own for old rooms.
        Index(
            "uq_custom_archetypes_title",
            "user_id",
            "title",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        # The picker's query: one account's live panelists, newest last.
        Index(
            "ix_custom_archetypes_live",
            "user_id",
            "created_at",
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    #: `custom:{uuid}` — minted, never supplied. See `docs/custom-archetypes.md`
    #: §5. The primary key is the name rather than a separate id because the name
    #: is what `session_panelists` stores and what every lookup arrives with; a
    #: second identifier would be a second thing to get wrong.
    name: Mapped[str] = mapped_column(String(80), primary_key=True)

    #: Plain UUID, never a foreign key to `auth.users` — see CLAUDE.md
    #: → Database portability.
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    #: "The Board Chair". The user's own words, and the only part of a custom
    #: panelist anybody reads. May duplicate a shipped title without
    #: consequence, because it is never an identifier.
    title: Mapped[str] = mapped_column(String(TITLE_LIMIT), nullable=False)

    #: Who this person is, in the user's words. **Fenced as data at the prompt,
    #: never interpolated as instructions** — §2. We compose the attack strategy
    #: from `domains` rather than taking one from here, because the strategy is
    #: what decides what the panel *does*, and handing it over hands over the
    #: grounding rules.
    persona: Mapped[str] = mapped_column(Text, nullable=False)

    #: The claim domains this panelist owns, from the shipped vocabulary and
    #: never free text — §1. These are the Auditor's routing key: a panelist
    #: with none can never be the one a targeted interruption reaches.
    domains: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default="{}"
    )

    #: One of `agents/voices.Voice`, or null for "pick one for me".
    #:
    #: Nullable because the choice is optional by decision, not by oversight:
    #: *"most users writing a custom archetype care about the argument it makes,
    #: not its timbre, and making them cast it is a decision tax"*
    #: (`docs/panel-orchestration.md`). Null means assembly assigns the first
    #: voice unused by the seated room.
    #:
    #: A character — `measured`, `brisk` — and **never a vendor identifier**. A
    #: vendor id in a row a user owns turns a synthesis swap into a migration
    #: over customer content, and it is also the one thing that would let a
    #: persona reach for a real person's voice (§6).
    voice: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: The row this one replaced, when an edit retired a seated panelist.
    #:
    #: Self-referential and nullable: most rows have never been superseded. It
    #: exists so a past room can be traced forward to the panelist as it reads
    #: today, which is the question somebody asks when a transcript surprises
    #: them.
    supersedes: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("custom_archetypes.name", ondelete="SET NULL"),
        nullable=True,
    )

    #: When "remove from your panel" was tapped. Null while live.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
