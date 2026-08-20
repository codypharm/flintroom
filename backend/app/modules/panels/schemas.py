"""What a client is told about the archetypes it may seat.

A deliberately narrow view of `agents/archetypes.py`. The library entry carries
the persona and attack strategy the model is driven with; this carries the three
fields somebody choosing a panel actually needs, and nothing that would let them
rehearse against the room in advance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.difficulty import GENTLE, RELENTLESS
from app.agents.vocabulary import DOMAIN_TERMS
from app.agents.voices import CASTABLE
from app.modules.panels.models import PERSONA_LIMIT, TITLE_LIMIT


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


class ArchetypeDraft(BaseModel):
    """What somebody types to write a panelist.

    Four fields, and `docs/custom-archetypes.md` §0 says who supplies each.
    Everything absent from here is absent on purpose: `cadence`, `openers` and
    `nudges` are hand-written per archetype and a row carries none, the attack
    strategy is composed by us from `domains`, and the name is minted.
    """

    model_config = ConfigDict(extra="forbid")

    #: "The Board Chair". Theirs, and never an identifier — it may duplicate a
    #: shipped title without consequence.
    title: str = Field(min_length=1, max_length=TITLE_LIMIT)

    #: Who this person is, in their words. **The only text of theirs that
    #: reaches a prompt**, and it is fenced as data when it does (§2). Capped
    #: far below `Archetype.persona`'s 2000 as part of that fencing rather than
    #: for storage: a paragraph describes somebody, and a page is room to argue
    #: with the instructions underneath it.
    persona: str = Field(min_length=1, max_length=PERSONA_LIMIT)

    #: From the shipped vocabulary, never typed (§1). These are the Auditor's
    #: routing key — a panelist with none can never be the one a targeted
    #: interruption reaches, which would make it a second-class member of the
    #: room in a way nothing would report.
    domains: list[str] = Field(min_length=1, max_length=4)

    #: One of ours, or null for "pick one for me". Optional by decision rather
    #: than oversight — casting is a decision tax on the feature's main path.
    voice: str | None = None

    @field_validator("domains")
    @classmethod
    def _known(cls, domains: list[str]) -> list[str]:
        """Refused rather than dropped.

        Silently discarding an unknown domain would seat a panelist that never
        catches anything, and its author would have no way to find out why — the
        same failure `ArchetypeNotFound` exists to prevent one level up.
        """
        unknown = [one for one in domains if one not in DOMAIN_TERMS]
        if unknown:
            raise ValueError(f"not domains we route on: {', '.join(sorted(unknown))}")
        if len(set(domains)) != len(domains):
            raise ValueError("the same domain twice")
        return domains

    @field_validator("voice")
    @classmethod
    def _castable(cls, voice: str | None) -> str | None:
        if voice is not None and voice not in {one.value for one in CASTABLE}:
            raise ValueError("not a voice we cast")
        return voice

    @field_validator("title", "persona")
    @classmethod
    def _not_only_spaces(cls, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            raise ValueError("cannot be blank")
        return stripped


class AuthoredArchetypeRead(BaseModel):
    """One panelist somebody wrote, as their own device sees it.

    Their own words go back out, unlike a shipped archetype where `persona` is
    prompt text that never leaves the server. There is nothing to protect here:
    they wrote it, and the form has to be able to reopen it.
    """

    model_config = ConfigDict(from_attributes=True)

    name: str
    title: str
    persona: str
    domains: list[str]
    voice: str | None
