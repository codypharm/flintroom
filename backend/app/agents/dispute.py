"""When one panelist may take issue with another's priorities.

`Product.md` §3.1 asks for a mixed room whose members "disagree with each other".
Every line before this was addressed to the presenter, so the champion and the
CFO never noticed each other existed — the room was a star, not a table.

**Code owns the occasion; the panelist owns the substance.** This module answers
one question — is this a turn where a difference of priority may be voiced — and
nothing else. It never decides what the difference is, never names a colleague's
error, never writes a line. What the panelist thinks matters more comes from its
own persona and from what was actually said, which is the part that would be
worthless if code supplied it.

Two rules from the design conversation on 2026-08-17, both here rather than in a
prompt because #43 measured what happens when a model is asked to judge whether
a rule applies. Asked whether the presenter had dodged, it said yes on 4 of 4
dodges *and* 4 of 4 genuine answers. A bound that lives in an instruction is a
bound that is not there.

**Priority only, never substance.** A panelist may say margin is not what sinks
this; it may not say the CFO's margin challenge was wrong. That distinction is
what keeps the disagreement safe: a stance about emphasis cannot be incorrect,
and it can never excuse the presenter from a question. A panel able to talk a
colleague out of a valid challenge would send somebody away having rehearsed the
wrong thing — the delivery-coach failure the wedge exists to refuse. Enforcing
it is the composer prompt's job; this module only decides when it is allowed.

**Capped per room.** Two agents free to differ whenever they like produce a room
that argues instead of interrogating, on time the user is paying for.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.archetypes import Archetype
from app.agents.context import USER, Said, TurnContext
from app.agents.difficulty import DISPUTES_PER_ROOM


def contested(
    archetype: Archetype,
    panel: Sequence[Archetype],
    context: TurnContext,
    *,
    spent: int,
) -> Said | None:
    """The line this archetype may take issue with, or `None`.

    Four checks, all against data that already exists. In order of what they
    refuse:

    1. **The cap.** Enforced first because it is the cheapest and because it is
       the one a model would not enforce itself. Read from the room's own rung
       (#55) rather than from the module constant: a first session gets zero, so
       nobody is talked over on the one room that has to sell the product.
    2. **Ground of its own.** An archetype with no `domains` has no priority to
       assert — the Distracted Executive's complaint is that you are not making
       the point clearly, which is not a subject. Nothing was added for this; it
       falls out of reading the field the Auditor already routes on.
    3. **Not itself.** A panelist may already speak twice running — #43 lets one
       press its own unanswered question, once — and on that turn the previous
       speaker is itself. A panelist disputing its own priorities is not a room
       disagreeing, it is an archetype with no thesis. The press rule and this
       one are mutually exclusive by construction rather than by a rule somebody
       has to remember.
    4. **Different ground.** Overlapping domains means the two want the same
       things, and a panelist told to find a difference anyway produces theatre.
       This is the gate against a room that argues on schedule.

    Only the immediately previous panel line is eligible. A panelist reaching
    back three turns to reopen something is not disagreement, it is a room that
    cannot move on — and a panelist disputing what *it* said earlier reads as
    having no position at all, which is the opposite of what a fixed persona and
    attack strategy are for.
    """
    if spent >= context.pressure.disputes or not archetype.domains:
        return None

    spoken = [line for line in context.grounding.transcript if line.speaker != USER]

    if not spoken or spoken[-1].speaker == archetype.name:
        return None

    last = spoken[-1]
    speaker = next((seat for seat in panel if seat.name == last.speaker), None)

    # An unknown speaker is not a dispute. A name in the transcript with no seat
    # at the table means the roster changed underneath the room, and inventing a
    # disagreement with somebody who is not there is worse than staying quiet.
    if speaker is None or not speaker.domains:
        return None

    if set(speaker.domains) & set(archetype.domains):
        return None

    return last
