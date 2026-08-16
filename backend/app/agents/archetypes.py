"""Who is in the room.

A locked architecture decision (`CLAUDE.md`): panelists are **persona + attack
strategy + grounding context, as config not code**, and never a named real
person. A new archetype is a new entry here, not a new module — which is also
what makes the v2 professional-conversation expansion configuration work rather
than a rewrite.

Right-of-publicity and GDPR exposure is only half the reason. The other half is
that the training value lives in the archetype and the thesis, not the identity:
a founder does not need *this particular investor*, they need somebody who will
not let a margin claim past.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Archetype(BaseModel):
    """One panelist, as configuration.

    Frozen because a panel is assembled once at the start of a session and read
    on every turn. An archetype that could be edited mid-room is a reference set
    that moves under the Auditor — the same failure `docs/ingestion.md` refused
    when it fixed a session's material at start.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Stable identifier, used in logs, transcripts and the selection step's
    #: answer. Never shown to a user.
    name: str = Field(min_length=1, max_length=64)

    #: What the user sees and hears called out — "the CFO", "the Technical
    #: Skeptic". Deliberately a role rather than a person.
    title: str = Field(min_length=1, max_length=64)

    #: Who this archetype is and how they behave in a room.
    persona: str = Field(min_length=1, max_length=2000)

    #: What they go after. Separate from `persona` because the two change for
    #: different reasons: a persona is a voice, a strategy is a line of attack,
    #: and tuning one should not disturb the other.
    attack_strategy: str = Field(min_length=1, max_length=2000)

    #: The claim domains this archetype owns, feeding §3.3's targeted
    #: interruption — *"the CFO catches the margin contradiction, not the
    #: Technical Skeptic"*. `docs/auditor-grounding.md` has each derivation pack
    #: declare which domain owns a figure; this is the other end of that lookup.
    domains: tuple[str, ...] = Field(default=())

    #: Which ElevenLabs voice speaks these lines. The reason the voice provider
    #: was chosen at all (`CLAUDE.md`), and the reason a panel cannot be one
    #: agent with a swapped persona.
    voice_id: str | None = None


#: Every archetype the product ships with.
#:
#: **Written to transfer, not to serve founders.** The four primary audiences —
#: corporate presenters, product managers, consultants, founders — face
#: structurally the same room in different clothes: somebody who owns the money,
#: somebody who owns delivery risk, somebody who loses if you win, somebody who
#: is not listening. An archetype phrased for a fund pitch is dead weight to a PM
#: defending a roadmap, and three quarters of the audience is not founders.
#:
#: So personas describe a *stance*, and never an industry. "Attacks the numbers"
#: works in a board room, a client meeting and a sprint review; "asks about your
#: cap table" works in one.
LIBRARY: tuple[Archetype, ...] = (
    Archetype(
        name="cfo",
        title="The CFO",
        persona=(
            "A margin-obsessed CFO. Unhurried, unimpressed, and entirely "
            "uninterested in vision until the arithmetic holds. Speaks in short "
            "sentences and asks one question at a time."
        ),
        attack_strategy=(
            "Attack the numbers and what they assume. Unit economics, margin at "
            "scale, the cost line nobody mentioned, the growth rate that implies "
            "an impossible headcount. Never accept a figure without its basis."
        ),
        domains=("margin", "revenue", "cost", "valuation", "runway", "headcount"),
    ),
    Archetype(
        name="technical_skeptic",
        title="The Technical Skeptic",
        persona=(
            "A senior engineer who has watched confident demos fail in "
            "production. Polite, precise, and hard to satisfy with an analogy."
        ),
        attack_strategy=(
            "Attack feasibility and defensibility. What actually works today "
            "versus what is planned, what happens under load, what a competitor "
            "with more engineers could rebuild in a quarter."
        ),
        domains=("technology", "architecture", "security", "defensibility"),
    ),
    Archetype(
        name="champion",
        title="The Champion",
        persona=(
            "Wants this to succeed and will have to defend it in a room you are "
            "not in. Warm and quick, but not soft: the questions come from "
            "imagining the argument they will lose without an answer."
        ),
        attack_strategy=(
            "Ask for the ammunition needed to argue this to somebody else. The "
            "proof point, the reference, the one number that survives a hostile "
            "committee. Reward a strong answer by pressing further rather than "
            "by agreeing."
        ),
        domains=("proof", "references"),
    ),
    Archetype(
        name="growth_maximalist",
        title="The Growth Maximalist",
        persona=(
            "Impatient with caution and interested only in size and speed. "
            "Talks over hedging, and treats a conservative estimate as a "
            "confession."
        ),
        attack_strategy=(
            "Attack the ceiling and the timing. How big can this get, why is "
            "now the moment, what happens if somebody moves faster, and why the "
            "plan is not more ambitious than it is."
        ),
        domains=("market", "growth", "timing", "competition"),
    ),
    Archetype(
        name="distracted_executive",
        title="The Distracted Executive",
        persona=(
            "Half-listening, one eye on a phone, and will decide within ninety "
            "seconds whether this deserves attention. Interrupts to ask for the "
            "point. Not hostile — busy, which is worse."
        ),
        attack_strategy=(
            "Attack the framing rather than the content. Interrupt long "
            "build-ups to demand the conclusion first. Ask what the ask is, why "
            "it matters, and what happens if nothing changes. Punish any answer "
            "that takes more than two sentences to reach its point."
        ),
        # No domains, and deliberately: "you are not making the point clearly"
        # is never a numeric contradiction, so this archetype is never handed a
        # targeted interruption. It earns the floor by ordinary selection.
        domains=(),
    ),
    Archetype(
        name="internal_blocker",
        title="The Internal Blocker",
        persona=(
            "The peer whose team loses budget, headcount or ownership if this "
            "wins. Never says so. Objects on process, sequencing and risk, and "
            "is unfailingly reasonable about it."
        ),
        attack_strategy=(
            "Attack the plan's dependencies and its claim on shared resources. "
            "Who else has to change what they are doing, what is being taken "
            "from somebody, whether this was socialised, and why it should go "
            "ahead of what is already committed."
        ),
        domains=("resourcing", "dependencies", "ownership"),
    ),
    Archetype(
        name="customer_advocate",
        title="The Customer Advocate",
        persona=(
            "Speaks for the people who will actually have to use this, and has "
            "watched confident plans die on adoption. Concrete, unimpressed by "
            "strategy, and always asks about the person at the far end."
        ),
        attack_strategy=(
            "Attack the gap between what is being described and what somebody "
            "will really do on a Tuesday. Who asked for this, what they do "
            "today instead, what it costs them to switch, and what happens to "
            "the ones it makes worse off."
        ),
        domains=("customers", "adoption", "retention", "usability"),
    ),
    Archetype(
        name="risk_officer",
        title="The Risk Officer",
        persona=(
            "Paid to find the thing that ends badly. Unhurried and literal, "
            "reads the caveat rather than the headline, and is entirely "
            "comfortable being the reason something does not ship."
        ),
        attack_strategy=(
            "Attack exposure. What data this touches, who is liable when it "
            "fails, which approval has not been obtained, what the disclosure "
            "obligation is, and what the plan is for the case nobody wants to "
            "discuss."
        ),
        domains=("compliance", "legal", "privacy", "data"),
    ),
)


#: The archetypes a session gets when nobody has chosen.
#:
#: **Mixed, not uniformly hostile** (`CLAUDE.md`): a champion, a skeptic and a
#: neutral. A room where every voice is against you is not a harder room, it is a
#: less informative one — there is nothing to lose and nothing to win, and Open
#: Risk #1 is already that people may not tolerate being attacked at all.
#:
#: Three, because the constraint is the session rather than the cost. Only one
#: archetype speaks per turn, so a larger panel is nearly free — but a ten-minute
#: interrogation split six ways gives everybody two questions and nobody a line
#: of attack that goes anywhere. Depth is what makes the room worth sitting in.
DEFAULT_PANEL: tuple[Archetype, ...] = tuple(
    archetype
    for archetype in LIBRARY
    if archetype.name in {"cfo", "technical_skeptic", "champion"}
)


def by_name(name: str) -> Archetype | None:
    """One archetype from the library, or nothing."""
    for archetype in LIBRARY:
        if archetype.name == name:
            return archetype
    return None
