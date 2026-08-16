"""The seam text-to-speech plugs into.

The other half of owning the loop. `ElevenLabsProvider` speaks as a side effect
of running the conversation; once we run the conversation, synthesis becomes a
thing we ask for by name — one line, one voice, one utterance at a time.

Distinct per-archetype voices are why this vendor was chosen at all (`CLAUDE.md`
→ Tech Stack), and it is not decoration. The interrogation screen is hands-free
by design: the phone is face-down on a desk, and voice is the *only* channel
carrying who is speaking. A panel that sounds like one person reading four
scripts is not a panel.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class Speaker(Protocol):
    """Turns a written line into audio. One instance per process."""

    def speak(self, *, text: str, voice: str | None) -> AsyncIterator[bytes]:
        """Speak one line, streaming PCM16 16 kHz mono as it is synthesised.

        **A stream rather than a buffer, and that is the barge-in requirement in
        the signature.** Now that the loop is ours, an interrupted panelist stops
        because the consumer stops iterating — so nothing here needs a cancel
        call, and nothing can be left half-spoken by one. A method returning
        finished bytes would have to synthesise a whole sentence before the first
        frame reached the phone, which spends the entire ~1.5s budget on a
        panelist who may be cut off two words in.

        `voice` is a character from `agents/voices.py` — "measured", "brisk" —
        never a vendor identifier. Each adapter resolves it against its own
        catalogue, so swapping synthesis is a sibling module rather than a
        migration over every custom archetype a user has written.

        Nullable, and an adapter falls back rather than refusing. A custom
        archetype may arrive uncast, and a room where two panelists sound alike
        is worse than a real room but far better than a silent one.
        """
        ...
