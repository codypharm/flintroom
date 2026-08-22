"""Where a room's words go once the room is over.

> **Naming.** *Transcription* (`transcription.py`) is the live speech-to-text
> stream — a vendor seam, alive only while the socket is. *Transcript* is the
> record of what was said, both sides, and outlives the room. They are one
> letter apart and genuinely different things; Python will even suggest one when
> you mistype the other. Read the suffix, not the stem.

`docs/session-retention.md` decides that the transcript survives the room on
every tier, including Free, and for the life of the account. That is not a
feature — it is the precondition for Phase 4. `Product.md` §405 grounds the
coach in the session's transcript, weak answers, Auditor findings and material,
and `CLAUDE.md` requires that scope be *structural* rather than a system prompt,
because a prompt saying "don't do general pitch review" is one jailbreak from
handing every user unlimited free pitch review. A coach that cannot read the
transcript has no grounding to be constrained to.

**Why this is a `Protocol` and not a service call.** `OrchestratedChannel` is the
only object that holds both sides of the room — `UserSpoke` carries no text and
`AgentTranscript` is deliberately only the panel — so the write has to happen
there. But the channel drives agents and knows nothing about databases, sessions
or entitlements, and it should stay that way: every other collaborator it takes
is a seam (`TranscriptionStream`, `PanelModel`, `Speaker`, `Auditor`), and a
`AsyncSession` in that constructor would be the one exception.

**Lines are written as they are said, not gathered at the end.** Same reasoning
as `spend.py`: a room whose process dies is settled later by the reaper, which
never held the channel, so anything accumulated in memory is lost for exactly
the rooms that ended badly — which are the ones a debrief has most to say about.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.context import Said


#: Checkable at runtime for the reason `TranscriptionStream` is: there is no base
#: class to inherit and no type checker in the suite, so a renamed method here
#: would stay green everywhere and fail only in a live room.
@runtime_checkable
class TranscriptStore(Protocol):
    """One room's record, for the length of one room."""

    async def record(self, line: Said, *, at: float | None = None) -> None:
        """Keep one line, whoever said it, and how far into the room it began.

        Takes a whole `Said` rather than a speaker and a string, so the caller
        cannot attribute a line to the wrong side by argument order — and so the
        panel's lines and the user's travel the same path. `Said.speaker` is
        `USER` or an archetype's name, exactly as the room's own memory records
        it.

        **Which session this belongs to is bound when the store is built**, not
        passed per call, following the provenance rule `CLAUDE.md` sets for
        `LedgerService`: a caller that cannot name the session cannot file half a
        room under the wrong one. It is also what keeps the channel free of
        session identity, which it otherwise has no use for.

        Never logged. `CLAUDE.md` forbids transcript text in logs and, unlike a
        secret, it cannot be caught by key-name redaction — it is indistinguishable
        from any other string. It must not be passed to a log call at all.

        **`at` is passed rather than read, and #69 is why.** The two sides of a
        room are stamped from different moments and only the caller knows which:
        a panel line is composed at the moment it belongs to, while a user's
        line is written when their final arrives — the end of what they said
        rather than the start. A store that read a clock here would file a
        ninety-second answer at the moment it finished.

        `None` when the room has no clock, which is not zero. Zero is a line at
        the very top of a room; `None` is a room that was never keeping time,
        and a reader that confused them would seek to the wrong place.
        """
        ...
