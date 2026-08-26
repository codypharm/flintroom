"""The stretch at the start of a room where nobody interrupts.

Every hostile room in the world opens the same way: the presenter makes their
case, uninterrupted, and only then does the questioning start. A board readout,
a demo day, an investment committee. Flintroom went straight to Q&A on turn one,
so the first panelist was asked to attack something before anything existed to
attack — and did, by inventing it.

Measured on a live room (066f32db, 2026-08-19), no deck attached, thirty words
spoken: the Technical Skeptic asked *"how many engineers maintain that
pipeline"* about a pipeline the presenter had never mentioned, and the room
spent six further turns on it. The composer guard from #45 forbids **numbers**
the presenter did not give — "NEVER STATE A NUMBER THEY DID NOT GIVE YOU" — and
an invented noun walks straight past it. That is Open Risk #2 arriving
structurally rather than through a bad prompt, and no prompt fixes it: a model
told to attack, holding nothing, will always find something to attack.

So the fix is not a better instruction. It is giving the model something true to
work from before it is asked to speak.

**Pure, and clock-injected.** Everything here is arithmetic over words and
seconds. The async machinery — arming the settle timer, cancelling it when the
presenter carries on — belongs to the listen loop, which already owns every
other task in the room. Keeping the decisions out of there is what lets them be
tested without a socket, a transcriber or a model.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from app.agents.archetypes import Archetype
from app.agents.context import Said

#: How much has to be said before the room treats it as a case worth attacking.
#:
#: Roughly twenty-five seconds of speech. Below it the presenter has cleared
#: their throat rather than made an argument, and the room owes them a question
#: instead of a challenge — see `thin`.
#:
#: **A starting point to be measured, not a number to be defended.** It decides
#: how often the orienting turn fires, and the only honest source for it is real
#: openings from real people (`Product.md` §4.3). Written here rather than in a
#: prompt for the reason `difficulty.py` gives: an integer is reproducible, and
#: `scripts/rotation.py` cannot measure a room that is not the same room twice.
SUBSTANCE_WORDS = 60

#: How long the presenter may pause before the floor is treated as handed back.
#:
#: **The whole bug, in one number.** The transcriber commits a final after
#: `SILENCE_THRESHOLD_SECS = 0.7`, and nobody delivers an opening statement
#: without pausing longer than that — so acting on the first final meant the
#: panel interrupting the first breath. This has to sit comfortably above it.
#:
#: It also has to clear a *section break*. 2.5 did not: on the first Play build
#: (Kettleworks run, 2026-08-26) a presenter reading a prepared opening paused
#: between sections and the floor closed mid-statement, so the questioning
#: began with the case half made. A rhetorical pause in a rehearsed opening
#: runs about three seconds; four clears it with margin.
#:
#: It still cannot go far above that. Every second here is a second of silence
#: in a room somebody is paying for by the minute, at the one moment they are
#: most likely to think the product has crashed — and in a real room, a beat of
#: silence after the presenter finishes reads as the panel thinking, so four
#: seconds spends believably.
SETTLE_PAUSE = 4.0

#: How long the opening may run before the panel comes in regardless.
#:
#: Without a bound, somebody who never stops talking gets a twelve-minute
#: monologue and has paid for a rehearsal nobody attended. Ninety seconds is
#: about the length of an opening worth rehearsing, and `SESSION_LIMIT` is
#: twelve minutes — so the cap costs at most an eighth of the room.
HARD_CAP = 90.0


@dataclass(frozen=True, slots=True)
class Opening:
    """What the presenter said before anybody interrupted them."""

    #: Everything they said, joined. The first turn is composed against the
    #: whole statement rather than the last fragment of it.
    text: str

    #: They did not reach `SUBSTANCE_WORDS`. The composer is told to ask for the
    #: ground rather than attack it — see `_composition_prompt`.
    thin: bool


@dataclass
class OpeningFloor:
    """Whether the floor is still the presenter's, and what they have said.

    Mutable and per room, like the dispute tally: it accumulates across turns
    and nothing else has that lifetime.
    """

    substance: int = SUBSTANCE_WORDS
    settle: float = SETTLE_PAUSE
    cap: float = HARD_CAP

    #: Still the presenter's. Goes false exactly once, in `close`.
    open: bool = True

    _said: list[str] = field(default_factory=list)

    @property
    def words(self) -> int:
        """How much has been said, across every final so far.

        Across, not per final. The transcriber commits every 0.7s of silence, so
        one thought arrives as several finals — counting each against the
        substance floor would find every fragment thin and every opening
        therefore thin.
        """
        return sum(len(one.split()) for one in self._said)

    @property
    def thin(self) -> bool:
        return self.words < self.substance

    def heard(self, text: str) -> None:
        self._said.append(text)

    def wait_for(self, *, elapsed: float) -> float:
        """How long to wait before deciding they have finished.

        Bounded by whatever is left of the cap, so a presenter in full flow is
        interrupted on time rather than one settle pause late. Zero once the cap
        is reached, which the caller reads as "close now" without a special case.
        """
        return max(0.0, min(self.settle, self.cap - elapsed))

    def close(self) -> Opening:
        """Hand the floor to the panel, and say what it was handed.

        **The substance floor decides the turn, never whether to close.** An
        earlier shape had the floor stay open until enough had been said, and it
        is wrong in the case that matters most: somebody who says nine words and
        stops would sit in silence until the ninety-second cap, watching a
        product they would reasonably assume had crashed. What "not enough" earns
        is a different question, not a longer wait.
        """
        self.open = False
        return Opening(text=" ".join(self._said), thin=self.thin)


_T = TypeVar("_T")

#: Picks one of several. Injected everywhere it is used, and defaulted here.
Chooser = Callable[[Sequence[_T]], _T]


def opener_from(
    panel: Sequence[Archetype], *, choose: Chooser = random.choice
) -> tuple[Archetype, str]:
    """Who opens the room, and what they say.

    **Random among the seated panel**, and the same draw picks the line. A fixed
    opener would ship twenty-four lines of copy and play three of them, which
    throws away the entire reason they are written per archetype.

    The first-impression worry that argues for pinning the Champion is real, and
    it is already handled upstream and better: `CLAUDE.md` has panel composition
    default to mixed — a champion, a skeptic and a neutral — so a uniformly cold
    open is managed at seating, where composition decisions belong. Enforcing it
    again here would be one rule living in two places that can disagree.

    Drawn from the **seated** panel, never the library. A voice belonging to
    somebody who is not at the table is a narrator, and this product
    deliberately has none — which is also why `compose` only ever sees one
    persona.

    `choose` is injected rather than calling `random` inline so that
    `scripts/rotation.py` and the suite can pin it. A room that cannot be
    repeated cannot be measured, which is the same property `difficulty.py`
    protects by being integers rather than an adjective in a prompt.

    An archetype with no openers is skipped rather than fatal. Custom archetypes
    are rows a user typed and carry none, and a Pro room seating one must still
    open — the same call `ElevenLabsSpeaker.speak` makes for an uncast voice.
    """
    speaking = [one for one in panel if one.openers]
    if not speaking:
        raise NoOneToOpen("no seated archetype has an opening line")

    who = choose(speaking)
    return who, choose(who.openers)


def reentry_from(
    panel: Sequence[Archetype],
    transcript: Sequence[Said],
    *,
    choose: Chooser = random.choice,
) -> tuple[Archetype, str]:
    """Who speaks when the presenter walks back in, and what they say.

    docs/reconnect.md decision 4. Two gaps, told apart by whose turn the
    transcript says it was when the line dropped:

    - The last line is a **panelist's**: their question was recorded before it
      was spoken, so the tunnel may have eaten it. The same panelist says the
      same words again — verbatim, because a paraphrase would be a model call
      about nothing and a second version of a question that already exists.
    - The last line is the **presenter's** (or there are no lines yet — the
      opener is spoken, never persisted): whoever most recently held the floor
      hands it back with one of their hand-written `reentries`. Scanning past
      seated panelists without lines covers the authored-archetype seat; the
      final fallback draws like `opener_from`, for the room that dropped
      before anyone had asked anything.

    Same seams as `opener_from`, for the same reasons: drawn from the seated
    panel only, `choose` injected so a room can be repeated, and an empty-lined
    archetype skipped rather than fatal.
    """
    seated = {one.name: one for one in panel}

    if transcript:
        last = transcript[-1]
        asked = seated.get(last.speaker)
        if asked is not None:
            return asked, last.text

    for line in reversed(transcript):
        held = seated.get(line.speaker)
        if held is not None and held.reentries:
            return held, choose(held.reentries)

    speaking = [one for one in panel if one.reentries]
    if not speaking:
        raise NoOneToReenter("no seated archetype has a re-entry line")
    who = choose(speaking)
    return who, choose(who.reentries)


class NoOneToReenter(Exception):
    """Nobody at the table can take the floor back.

    Cannot happen with a shipped panel — `test_resumed_room.py` proves every
    shipped archetype carries re-entry lines — and the room it describes
    resumes in silence rather than refusing, mirroring `NoOneToOpen`.
    """


class NoOneToOpen(Exception):
    """Nobody at the table has anything to open with.

    Cannot happen with a shipped panel — `test_openers.py` proves every
    archetype in `LIBRARY` has lines — and is reachable only by a room seated
    entirely from custom archetypes. Raised rather than returning `None` so the
    caller cannot silently open a room in silence, which is the failure mode
    this whole task exists to remove.
    """
