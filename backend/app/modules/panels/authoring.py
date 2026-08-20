"""Writing, editing and retiring a panelist somebody wrote.

`docs/custom-archetypes.md` §4 is the whole of this module's difficulty.
`session_panelists` stores a **name**, not a snapshot — deliberately, so
improving an archetype's wording does not freeze every room that used it. That
holds while archetypes are ours and few, and `sessions/models.py` named this
feature as the moment it stops holding: *"a panelist may point at a row rather
than a constant, and the question becomes what happens when its author deletes
it."*

So the rules are:

- Editing one that has **never been seated** mutates the row. Nothing points at
  it, and a second row would be litter.
- Editing one that **has** writes a new row and retires the old, so the name in
  `session_panelists` keeps pointing at the text that was actually in the room.
- **"Delete" archives.** A destroyed row leaves a dangling name in every
  transcript that seated it, and rooms outlive panelists by design.

Which is why the control must read *remove from your panel* and never *delete*:
somebody who taps it has not deleted their data. Account deletion is the real
delete, and this table is in `billing/deletion.PURGED`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.archetypes import Archetype
from app.agents.authored import mint_name, seated_as
from app.core.errors import (
    AccountNotFound,
    ArchetypeNotFound,
    InsufficientEntitlement,
    TitleAlreadyUsed,
)
from app.core.logging import get_logger
from app.modules.billing.models import Account
from app.modules.billing.tiers import may_author_archetypes
from app.modules.panels.models import CustomArchetype
from app.modules.panels.schemas import ArchetypeDraft
from app.modules.sessions.models import SessionPanelist

log = get_logger(__name__, tag="panel")


class AuthoringService:
    """One account's own panelists."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def write(
        self, *, user_id: uuid.UUID, draft: ArchetypeDraft
    ) -> CustomArchetype:
        """A new panelist, with a name nobody supplied."""
        await self._must_be_entitled(user_id)

        written = CustomArchetype(
            name=mint_name(),
            user_id=user_id,
            title=draft.title,
            persona=draft.persona,
            domains=list(draft.domains),
            voice=draft.voice,
        )
        await self._save(written)

        log.info("archetype_written", user_id=str(user_id), archetype=written.name)
        return written

    async def revise(
        self, *, user_id: uuid.UUID, name: str, draft: ArchetypeDraft
    ) -> CustomArchetype:
        """Edit it, or replace it — whichever keeps old rooms honest.

        The branch is not a preference. A row that has been in a room is
        referenced by a name that must keep meaning what it meant; one that has
        not is referenced by nothing.
        """
        await self._must_be_entitled(user_id)
        existing = await self._mine(user_id=user_id, name=name)

        if not await self._has_been_seated(name):
            existing.title = draft.title
            existing.persona = draft.persona
            existing.domains = list(draft.domains)
            existing.voice = draft.voice
            await self._save(existing)
            log.info("archetype_revised", user_id=str(user_id), archetype=name)
            return existing

        # Retired in the same transaction as the replacement is written, and
        # the ordering matters: the title index is partial on
        # `archived_at IS NULL`, so an edit that keeps the title needs the old
        # row to stop being live before the new one lands. SQLAlchemy's unit of
        # work does emit the UPDATE first here, and
        # `test_a_seated_panelist_may_be_edited_without_renaming_it` is what
        # holds that rather than a flush placed on faith — an explicit one was
        # tried and removed once the test proved it changed nothing.
        existing.archived_at = datetime.now(timezone.utc)
        replacement = CustomArchetype(
            name=mint_name(),
            user_id=user_id,
            title=draft.title,
            persona=draft.persona,
            domains=list(draft.domains),
            voice=draft.voice,
            supersedes=name,
        )
        await self._save(replacement)

        log.info(
            "archetype_superseded",
            user_id=str(user_id),
            archetype=replacement.name,
            supersedes=name,
        )
        return replacement

    async def retire(self, *, user_id: uuid.UUID, name: str) -> None:
        """Take it out of the panel, and leave every past room readable.

        Idempotent. A second tap on a control that already worked is not a
        failure, and a client that retries a request whose response was lost
        must not be told the panelist has vanished.
        """
        await self._must_be_entitled(user_id)
        existing = await self._mine(user_id=user_id, name=name)

        if existing.archived_at is None:
            existing.archived_at = datetime.now(timezone.utc)
            await self._save(existing)
            log.info("archetype_retired", user_id=str(user_id), archetype=name)

    async def roster(self, *, user_id: uuid.UUID) -> list[CustomArchetype]:
        """The live ones, oldest first — the order the picker shows them in."""
        found = await self._db.scalars(
            select(CustomArchetype)
            .where(
                CustomArchetype.user_id == user_id,
                CustomArchetype.archived_at.is_(None),
            )
            .order_by(CustomArchetype.created_at)
        )
        return list(found.all())

    async def seatable(
        self, *, user_id: uuid.UUID, names: list[str]
    ) -> dict[str, Archetype]:
        """What `assemble()` is handed, keyed by name.

        Scoped to the owner, so knowing another account's panelist name is not
        enough to seat it. Archived ones are excluded: they stay readable for
        the rooms that used them and leave the picker, and seating is the picker
        one step later.

        Silently omits anything it cannot find. `assemble()` is what turns an
        unresolvable name into `ArchetypeNotFound`, and duplicating that
        judgement here would be two places deciding what a missing panelist
        means.
        """
        if not names:
            return {}

        found = await self._db.scalars(
            select(CustomArchetype).where(
                CustomArchetype.user_id == user_id,
                CustomArchetype.name.in_(names),
                CustomArchetype.archived_at.is_(None),
            )
        )
        return {row.name: seated_as(row) for row in found.all()}

    async def _must_be_entitled(self, user_id: uuid.UUID) -> None:
        """§4.4 sells this as Pro, and the check lives here so no route forgets.

        `CLAUDE.md` puts entitlement in a dependency rather than a service, and
        the router does carry one. This is the second wall: `seatable` and
        `roster` are called from the sessions path too, and an entitlement
        enforced only at one router is one refactor from being enforced nowhere.
        """
        tier = await self._db.scalar(
            select(Account.entitlement_tier).where(Account.user_id == user_id)
        )
        if tier is None:
            raise AccountNotFound(user_id=str(user_id))
        if not may_author_archetypes(tier):
            raise InsufficientEntitlement(
                context={"user_id": str(user_id), "action": "author_archetype"}
            )

    async def _mine(self, *, user_id: uuid.UUID, name: str) -> CustomArchetype:
        """This account's panelist, or a 404.

        **404 rather than 403 for somebody else's**, and the difference matters:
        403 confirms the row exists. An enumeration oracle is worth closing even
        on a table keyed by a UUID.
        """
        found = await self._db.scalar(
            select(CustomArchetype).where(
                CustomArchetype.name == name,
                CustomArchetype.user_id == user_id,
            )
        )
        if found is None:
            raise ArchetypeNotFound(archetype=name)
        return found

    async def _has_been_seated(self, name: str) -> bool:
        """Whether any room, ever, put this panelist in a chair."""
        return bool(
            await self._db.scalar(
                select(exists().where(SessionPanelist.name == name))
            )
        )

    async def _save(self, row: CustomArchetype) -> None:
        """Commit, turning the title index's refusal into something sayable.

        The partial unique index is the authority rather than a pre-flight
        `SELECT`: two requests racing on the same title would both find it free
        and both insert. Catching the violation is the only version of this
        check that is actually true under concurrency.
        """
        self._db.add(row)
        try:
            await self._db.commit()
        except IntegrityError as clash:
            await self._db.rollback()
            if "uq_custom_archetypes_title" not in str(clash.orig):
                raise
            raise TitleAlreadyUsed(context={"title": row.title}) from clash
