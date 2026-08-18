"""What a client is told about the archetypes it may seat.

A deliberately narrow view of `agents/archetypes.py`. The library entry carries
the persona and attack strategy the model is driven with; this carries the three
fields somebody choosing a panel actually needs, and nothing that would let them
rehearse against the room in advance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.agents.difficulty import GENTLE, RELENTLESS


class ArchetypeRead(BaseModel):
    """One panelist, as offered.

    Built from an `Archetype` by field name rather than by `model_validate`, so
    that adding a field to the library does not publish it. That is the whole
    safety property of this schema: the default has to be *withheld*, because the
    field most likely to be added next is another line of prompt text.
    """

    model_config = ConfigDict(from_attributes=True)

    #: What `SessionStart.archetypes` expects back.
    name: str

    #: The role, as it appears in a picker and is spoken in the room.
    title: str

    #: One line on who they are. Never what they will attack — see
    #: `Archetype.blurb`.
    blurb: str


class ArchetypeCatalogue(BaseModel):
    """Everybody available, and how many of them this plan seats.

    The caps travel with the catalogue rather than sitting on a separate limits
    endpoint, because they are read at the same moment and by the same screen: a
    picker that knows the roster but not the seat count can only find out a
    fourth choice is refused by posting it.

    Same reasoning as `MaterialLimits` — the client refuses instantly with no
    round trip, and the server refusal stays the real wall.
    """

    archetypes: list[ArchetypeRead]

    #: How many may be in one room on the caller's plan.
    seats: int

    #: Who is in the chairs already, in seat order — the reveal.
    #:
    #: Here rather than at an endpoint of its own for the same reason `seats` is:
    #: it is read at the same moment by the same screen, and the setup screen's
    #: first-run posture *is* the "here's your room" moment `docs/onboarding.md`
    #: promised. A second call for three names would be a round trip for one
    #: field the screen needs in the same instant.
    #:
    #: Derived from the survey on every read rather than frozen at sign-up, so
    #: the reveal and the room the session builds cannot drift apart across a
    #: release. Never empty: an account that answered nothing falls through to
    #: the shipped default panel, so no client needs a branch for it.
    seated: list[str] = Field(default_factory=list)

    #: Whether this plan may write its own archetype (§4.4, Pro upward). Published
    #: even where it is false, because a picker showing a locked "write your own"
    #: is how somebody learns the capability exists.
    may_author: bool = False

    #: Seats on the rung above, or null at the top. A number rather than a verb:
    #: the client renders the prompt, and the API states the fact.
    upgrade_seats: int | None = Field(default=None)

    #: How hard the room will push, 1 to `hardest` — #55's rung.
    #:
    #: Here for the same reason `seats` is: it is read at the same moment by the
    #: same screen, and a picker that knew the roster but not the rung would need
    #: a second round trip to render one slider.
    difficulty: int = Field(default=GENTLE)

    #: The top of the ladder, so the client renders the positions that exist
    #: rather than a count of its own. A hardcoded three in the app is the same
    #: failure a hardcoded archetype library would be: two lists free to
    #: disagree, with an app release between them.
    hardest: int = Field(default=RELENTLESS)


class DifficultyChoice(BaseModel):
    """The rung a user picked for themselves.

    Validated against the ladder rather than clamped. Clamping is right where a
    *stored* number is read back — `difficulty.pressure_at` does it, so a live
    room never ends over bookkeeping — and wrong here: this is a person
    choosing, and quietly handing them level 3 when they asked for 7 is a
    control that lies about what it did.
    """

    difficulty: int = Field(ge=GENTLE, le=RELENTLESS)
