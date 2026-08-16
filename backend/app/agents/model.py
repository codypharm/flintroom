"""The seam a panel model plugs into.

Structural (`Protocol`) rather than inherited, like `voice.provider` and
`core.storage`: an adapter is a class that happens to fit rather than one that
had to import us, so a vendor SDK wrapper never acquires a dependency on our
module graph.

**One interface, two calls, one adapter per vendor.** Not two services — the two
steps are different jobs but they belong to the same conversation and the same
bill, and splitting them across components would mean two places to configure a
vendor and two places to notice it is failing.

Whether the two calls reach the *same model* is a setting inside an adapter and
not a structural question. `docs/panel-orchestration.md` starts with a cheap
model for selection and a stronger one for composition, on the grounds that
routing is a classification and interrogation is the product — but that is a
number to measure, not a shape to commit to.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.agents.archetypes import Archetype


class PanelModel(Protocol):
    """Whatever decides who speaks, and writes what they say."""

    async def select(
        self, *, candidates: Sequence[Archetype], context
    ) -> str:
        """Name the archetype that should take the floor.

        Returns a `name`, not an `Archetype`, because a model returns text and
        pretending otherwise would put the parsing somewhere less obvious. The
        caller resolves it and falls back if the model invented somebody — this
        runs inside a live metered room, where raising ends the session rather
        than degrading it.

        Sees the whole roster on purpose. Selection is the one place the room
        exists as a room: who has been quiet, whose domain was just touched,
        whose thesis the last answer contradicted. Inter-panelist disagreement is
        a property of this call, because the composer only ever sees one person.
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
