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


#: The panel a session gets when nobody has chosen one.
#:
#: **Mixed, not uniformly hostile** (`CLAUDE.md`): a champion, a skeptic and a
#: neutral. A room where every voice is against you is not a harder room, it is a
#: less informative one — there is nothing to lose and nothing to win, and Open
#: Risk #1 is already that people may not tolerate being attacked at all.
DEFAULT_PANEL: tuple[Archetype, ...] = (
    Archetype(
        name="margin_hawk",
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
            "Already persuaded, and therefore the most dangerous person in the "
            "room to disappoint. Warm, quick, and asks the questions that would "
            "let them defend this to somebody else."
        ),
        attack_strategy=(
            "Ask for the ammunition needed to argue this internally. Push for "
            "the proof point, the reference customer, the number that survives "
            "a hostile committee. Reward a strong answer by pressing further."
        ),
        domains=("market", "traction", "customers", "positioning"),
    ),
)
