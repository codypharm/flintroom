"""Writing, editing and retiring a panelist you wrote.

`docs/custom-archetypes.md` §4 is the whole of this file's difficulty:
`session_panelists` stores a **name**, not a snapshot, so a row that has ever
been in a room may never change underneath it. Editing an unseated one mutates;
editing a seated one writes a new row and retires the old; and "delete" archives
rather than destroys, because rooms are kept for the life of the account and all
of them render who was there.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agents.authored import CUSTOM_PREFIX
from app.core.errors import (
    ArchetypeNotFound,
    InsufficientEntitlement,
    TitleAlreadyUsed,
)
from app.modules.billing.models import Account
from app.modules.panels.authoring import AuthoringService
from app.modules.panels.models import CustomArchetype
from app.modules.panels.schemas import ArchetypeDraft
from app.modules.sessions.models import Session, SessionPanelist


def a_draft(**over) -> ArchetypeDraft:
    return ArchetypeDraft(
        **{
            "title": "The Board Chair",
            "persona": "Unimpressed by anything that is not a number.",
            "domains": ["margin", "runway"],
            "voice": None,
            **over,
        }
    )


@pytest.fixture
async def pro(db) -> Account:
    account = Account(user_id=uuid.uuid4(), entitlement_tier="pro")
    db.add(account)
    await db.commit()
    return account


async def test_a_free_account_cannot_write_one(db, account):
    """§4.4 sells this as Pro. Checked in the service so no route can forget it."""
    with pytest.raises(InsufficientEntitlement):
        await AuthoringService(db).write(user_id=account.user_id, draft=a_draft())


async def test_writing_one_mints_a_name_nobody_supplied(db, pro):
    written = await AuthoringService(db).write(user_id=pro.user_id, draft=a_draft())

    assert written.name.startswith(CUSTOM_PREFIX)
    assert written.title == "The Board Chair"
    assert written.archived_at is None


async def test_two_live_panelists_may_not_share_a_title(db, pro):
    """The picker shows titles. Two of one word is a picker that cannot be read."""
    service = AuthoringService(db)
    await service.write(user_id=pro.user_id, draft=a_draft())

    with pytest.raises(TitleAlreadyUsed):
        await service.write(user_id=pro.user_id, draft=a_draft())


async def test_a_retired_title_is_free_again(db, pro):
    """Archiving frees the word — the retired row keeps its own for old rooms."""
    service = AuthoringService(db)
    first = await service.write(user_id=pro.user_id, draft=a_draft())
    await service.retire(user_id=pro.user_id, name=first.name)

    again = await service.write(user_id=pro.user_id, draft=a_draft())

    assert again.name != first.name


async def test_two_accounts_may_use_the_same_title(db, pro):
    """Titles are scoped to the person reading them, not to the product."""
    other = Account(user_id=uuid.uuid4(), entitlement_tier="pro")
    db.add(other)
    await db.commit()
    service = AuthoringService(db)

    await service.write(user_id=pro.user_id, draft=a_draft())
    theirs = await service.write(user_id=other.user_id, draft=a_draft())

    assert theirs.title == "The Board Chair"


async def test_editing_an_unseated_panelist_changes_it_in_place(db, pro):
    """Nothing points at it yet, so a new row would be litter."""
    service = AuthoringService(db)
    written = await service.write(user_id=pro.user_id, draft=a_draft())

    edited = await service.revise(
        user_id=pro.user_id, name=written.name, draft=a_draft(title="The Chair")
    )

    assert edited.name == written.name
    assert edited.title == "The Chair"
    assert await _rows(db, pro.user_id) == 1


async def test_a_minted_name_fits_the_column_that_records_a_seat(db, pro):
    """`session_panelists.name` is a VARCHAR(64) sized for shipped names.

    A minted one is `custom:` plus a UUID — 43 characters, comfortably inside
    it. Pinned rather than assumed, because a longer prefix or a different id
    scheme would truncate here and the failure would be a room whose transcript
    names a panelist that cannot be looked up.
    """
    written = await AuthoringService(db).write(user_id=pro.user_id, draft=a_draft())

    assert len(written.name) <= SessionPanelist.__table__.c.name.type.length


async def test_editing_a_seated_panelist_writes_a_new_row_and_retires_the_old(
    db, pro
):
    """§4 — the name in `session_panelists` must keep meaning what it meant.

    Renaming in place is the quiet hazard: "The Board Chair" becoming "Angry
    Investor" would make every past room retroactively claim a person who was
    never in it, with nothing erroring.
    """
    service = AuthoringService(db)
    written = await service.write(user_id=pro.user_id, draft=a_draft())
    await _seat(db, user_id=pro.user_id, name=written.name)

    edited = await service.revise(
        user_id=pro.user_id, name=written.name, draft=a_draft(title="Angry Investor")
    )

    assert edited.name != written.name
    assert edited.supersedes == written.name
    assert (await _row(db, written.name)).title == "The Board Chair"
    assert (await _row(db, written.name)).archived_at is not None


async def test_a_seated_panelist_may_be_edited_without_renaming_it(db, pro):
    """The ordinary edit: fix the description, keep the person.

    This is the case the replacement path makes awkward. The title index is
    partial on `archived_at IS NULL`, so the replacement collides with its own
    predecessor unless the retire has already landed — and SQLAlchemy orders
    INSERTs ahead of UPDATEs inside one flush by default. Nothing about changing
    the title exercises that, which is why this test exists beside the one that
    does.
    """
    service = AuthoringService(db)
    written = await service.write(user_id=pro.user_id, draft=a_draft())
    await _seat(db, user_id=pro.user_id, name=written.name)

    edited = await service.revise(
        user_id=pro.user_id,
        name=written.name,
        draft=a_draft(persona="Wants the number before the story."),
    )

    assert edited.name != written.name
    assert edited.title == "The Board Chair"
    assert (await _row(db, written.name)).persona.startswith("Unimpressed")


async def test_retiring_one_keeps_it_readable(db, pro):
    """"Delete" is an archive. A destroyed row leaves a dangling name in every
    transcript that seated it, and rooms outlive panelists by design.
    """
    service = AuthoringService(db)
    written = await service.write(user_id=pro.user_id, draft=a_draft())

    await service.retire(user_id=pro.user_id, name=written.name)

    assert (await _row(db, written.name)) is not None
    assert (await _row(db, written.name)).archived_at is not None


async def test_retiring_twice_is_not_an_error(db, pro):
    """A second tap on a control that already worked is not a failure."""
    service = AuthoringService(db)
    written = await service.write(user_id=pro.user_id, draft=a_draft())

    await service.retire(user_id=pro.user_id, name=written.name)
    await service.retire(user_id=pro.user_id, name=written.name)

    assert await _rows(db, pro.user_id) == 1


async def test_somebody_elses_panelist_is_not_found_rather_than_forbidden(db, pro):
    """404 rather than 403, because 403 confirms the row exists.

    An enumeration oracle on a table keyed by a guessable-shaped name is worth
    closing even when the name is a UUID.
    """
    other = Account(user_id=uuid.uuid4(), entitlement_tier="pro")
    db.add(other)
    await db.commit()
    service = AuthoringService(db)
    mine = await service.write(user_id=pro.user_id, draft=a_draft())

    with pytest.raises(ArchetypeNotFound):
        await service.retire(user_id=other.user_id, name=mine.name)


async def test_the_roster_shows_the_living_and_not_the_retired(db, pro):
    service = AuthoringService(db)
    kept = await service.write(user_id=pro.user_id, draft=a_draft())
    gone = await service.write(user_id=pro.user_id, draft=a_draft(title="The Regulator"))
    await service.retire(user_id=pro.user_id, name=gone.name)

    roster = await service.roster(user_id=pro.user_id)

    assert [one.name for one in roster] == [kept.name]


async def test_the_loader_returns_only_what_this_account_owns(db, pro):
    """What `assemble()` is handed. A row belonging to somebody else must not
    resolve, or one account seats another's panelist by knowing its name.
    """
    other = Account(user_id=uuid.uuid4(), entitlement_tier="pro")
    db.add(other)
    await db.commit()
    service = AuthoringService(db)
    mine = await service.write(user_id=pro.user_id, draft=a_draft())

    theirs = await service.seatable(user_id=other.user_id, names=[mine.name])

    assert theirs == {}


async def test_a_retired_panelist_cannot_be_seated_again(db, pro):
    """It stays readable for old rooms and leaves the picker. Seating is the
    picker, one step later.
    """
    service = AuthoringService(db)
    written = await service.write(user_id=pro.user_id, draft=a_draft())
    await service.retire(user_id=pro.user_id, name=written.name)

    assert await service.seatable(user_id=pro.user_id, names=[written.name]) == {}


async def _row(db, name: str) -> CustomArchetype | None:
    return await db.scalar(
        select(CustomArchetype).where(CustomArchetype.name == name)
    )


async def _rows(db, user_id: uuid.UUID) -> int:
    found = await db.scalars(
        select(CustomArchetype).where(CustomArchetype.user_id == user_id)
    )
    return len(found.all())


async def _seat(db, *, user_id: uuid.UUID, name: str) -> None:
    """Put this panelist in a room, so it can never be edited in place again."""
    # `active` rather than a finished state: a settled room needs a settled_at
    # and a whole lifecycle to get one, and "has ever been seated" is true of a
    # room in progress too — which is also the case where editing in place would
    # change a panel underneath a live interrogation.
    room = Session(user_id=user_id, state="active")
    db.add(room)
    await db.flush()
    db.add(SessionPanelist(session_id=room.id, name=name, seat=0))
    await db.commit()
