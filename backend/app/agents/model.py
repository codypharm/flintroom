"""The seam a panel model plugs into.

Structural (`Protocol`) rather than inherited, like `voice.provider` and
`core.storage`: an adapter is a class that happens to fit rather than one that
had to import us, so a vendor SDK wrapper never acquires a dependency on our
module graph.

**Two calls per turn, one adapter per vendor.** Selection was moved into code
when the spike timed it at ~0.8s against a 1.5s budget, and moved back when that
turned out to be the wrong reading of the constraint twice over.

Keyword routing measured 53% relevance against realistic speech — and, decisively,
**cannot see a custom archetype at all**, since a persona somebody typed this
morning has no entry in any vocabulary table. Pro sells custom archetypes; routing
that ignores them is not a routing system.

The 0.8s objection dissolves because routing does not have to run *after* the
user stops. We own the loop, so a partial transcript is available while they are
still speaking, and the gist is all this call needs. Routing overlaps the tail of
the utterance; composition stays the only serial hop.

Keyword routing survives as the fallback in `routing.py`, which is a better job
for it: when this call is late or fails, the room picks somebody instantly. A slow
model then costs relevance rather than silence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.agents.archetypes import Archetype


class PanelModel(Protocol):
    """Whatever decides who speaks, and writes what they say."""

    async def select(self, *, candidates: Sequence[Archetype], context) -> str:
        """Name the archetype that should take the floor.

        Returns a `name`, not an `Archetype`, because a model returns text and
        pretending otherwise would hide the parsing somewhere less obvious.

        Sees the whole roster on purpose — including any custom archetype, whose
        persona is just more text and needs nothing registered anywhere. This is
        the one place the room exists as a room: who has been quiet, whose domain
        the answer touched, whose thesis it contradicted. Inter-panelist
        disagreement is a property of this call, because the composer only ever
        sees one person.

        **May raise, and the caller must survive it.** A room is live and metered;
        a routing failure has to cost relevance, not silence.
        """
        ...

    async def compose(
        self, *, archetype: Archetype, context, finding=None
    ) -> str:
        """Write this archetype's next line.

        **One archetype, never the panel.** The signature is the enforcement: a
        prompt holding four personas averages them into one voice wearing four
        labels, and that failure is invisible from the inside — it reads
        perfectly well in a transcript and feels flat in a room, which is §3.3's
        *"synthetic within two minutes"*. A composer that cannot see the other
        three cannot blend them.

        `finding` is the Auditor's catch when there is one. It travels here as
        well as to the routing, because an archetype handed the floor for a
        contradiction and not told what the contradiction was produces a
        challenge that sounds authoritative and cites nothing.

        Returns text. Speech is the voice provider's job, and keeping that out of
        here is what lets the same adapter serve the debrief coach later, which
        is turn-based and has no room in it at all.
        """
        ...
