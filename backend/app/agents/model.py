"""The seam a panel model plugs into.

Structural (`Protocol`) rather than inherited, like `voice.provider` and
`core.storage`: an adapter is a class that happens to fit rather than one that
had to import us, so a vendor SDK wrapper never acquires a dependency on our
module graph.

**One call per turn, one adapter per vendor.** There were two until the spike
timed them: a model round trip to pick the speaker cost ~0.8s of a 1.5s budget
for what is mostly a lookup, so selection moved into `routing.py` and this
interface lost a method.

What is left is the hop that cannot be done in code. Choosing who speaks is a
lookup over declared domains; writing what they say in their own voice is not.
"""

from __future__ import annotations

from typing import Protocol

from app.agents.archetypes import Archetype


class PanelModel(Protocol):
    """Whatever decides who speaks, and writes what they say."""

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
