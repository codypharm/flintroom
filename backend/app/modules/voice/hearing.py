"""Has this room ever heard anything at all? #77.

One question, asked of the bytes actually forwarded to the transcriber, and it
exists because the more obvious question cannot be answered.

**Digital silence does not mean a dead microphone.** `docs/echo-cancellation.md`
measured the configuration this product ships in — patched
`Usage::VoiceCommunication` on both streams, `MODE_IN_COMMUNICATION`, panel
audio out of the loudspeaker — and found a *quiet room* on a real S24+ reading
exact digital zero: every sample, peak -120 dBFS. Noise suppression gates the
room outright. The doc draws the conclusion itself: "perfect cancellation and a
dead microphone are indistinguishable in it."

So on Android, an ordinary pause and an unplugged microphone are byte-for-byte
the same thing, and no classifier reading levels can separate them. What can be
separated is a room that has **never once** heard anything: a working microphone
delivers a non-zero sample the moment somebody speaks, and a dead one never
does.

That makes this a latch rather than a classifier. It can only ever fire before
the first real audio, and the first voice turns it off for the rest of the room.
The failure it is built to avoid is the one `app/src/lib/audio/hearing.ts`
already committed once — a warning that fires while somebody is merely thinking
teaches people to ignore the one that matters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: What the relay carries, and therefore what a second of audio weighs.
#:
#: Stated here rather than imported from `orchestrated`, which imports this
#: — and asserted against the real constants in `test_room_hearing.py`, the
#: same trade `app/src/lib/audio/hearing.ts` makes with `BUFFER_MS` for the
#: same reason. A number this small is cheaper to restate than to entangle.
SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2

#: How much unbroken digital silence, in seconds of forwarded audio, before the
#: room says it has not heard anything.
#:
#: **Bounded on both sides by measurements rather than picked.** Above, #77 timed
#: the transcriber committing an empty final after 36-37 seconds of silence
#: across three rooms — telling the presenter after that has already happened is
#: telling them nothing, so this has to be under it. Below, `NUDGE_AFTER_SECONDS`
#: is 60 and argues that quiet is still plausibly thought beneath it; this says
#: something stronger to somebody who may simply not have started yet, so it
#: cannot be hair-trigger either.
#:
#: Twenty-five sits in that gap, past a plausible pause and comfortably ahead of
#: the hallucination. The room's escalation reads: 25s the screen says so, ~37s
#: the transcriber invents an utterance and `_listen` drops it, 60s a panelist
#: asks out loud, 90s `IDLE_LIMIT` ends it and refunds.
UNHEARD_AFTER_SECONDS = 25

#: Seconds converted to the only unit this sees. The relay carries PCM16 at
#: 16 kHz mono, so a second of audio is a fixed number of bytes.
_UNHEARD_AFTER_BYTES = UNHEARD_AFTER_SECONDS * SAMPLE_RATE * BYTES_PER_SAMPLE


@dataclass
class RoomHearing:
    """Whether a voice has ever reached this room, and how long it has not.

    Fed from `send_audio`, which is the honest place: those are the bytes the
    transcriber is actually given and actually bills for, so this cannot
    disagree with what the provider is reacting to. A phone that has stopped
    sending is not silent here — it is absent, which is the socket's problem and
    the reaper's, and answering it here would put a second opinion on the wire.
    """

    #: Latched by the first non-zero sample and never cleared. There is no
    #: `heard()`/`quiet()` pair on purpose: a microphone that has worked once
    #: has been proven, and anything that could un-prove it would fire on an
    #: ordinary pause.
    _ever: bool = field(default=False)
    #: Bytes forwarded before that happened. Stops mattering once `_ever`.
    _silent_bytes: int = field(default=0)

    def heard(self, pcm: bytes) -> None:
        """Take one buffer on its way to the transcriber.

        `strip` rather than a loop over samples, because this runs on every
        buffer of every live room and a Python-level scan of 20 ms of audio
        fifty times a second is a cost with nothing to show for it. All-zero
        bytes are all-zero samples: a sample of 1 is `b"\\x01\\x00"` and a sample
        of 256 is `b"\\x00\\x01"`, and both survive the strip.
        """
        if self._ever:
            return

        if pcm.strip(b"\x00"):
            self._ever = True
            self._silent_bytes = 0
            return

        self._silent_bytes += len(pcm)

    def spoke(self) -> None:
        """A final arrived carrying words. Settles it whatever the bytes said.

        Belt and braces, and it closes the one disagreement that would be
        visibly absurd: a screen reporting that nothing has reached the room
        while the transcript fills with what the presenter said. The two
        signals cannot contradict each other if the stronger one wins.

        It should be unreachable — a transcriber cannot make words out of
        samples that were all zero — and that is exactly why it is here rather
        than asserted. If a provider ever does, the failure is one line of
        wrong text on a screen and not a room that argues with itself.
        """
        self._ever = True
        self._silent_bytes = 0

    @property
    def unheard(self) -> bool:
        """Nothing has ever arrived, and enough of nothing to be worth saying.

        **A known blind spot, left rather than engineered around.** This tests
        for exact zero, so a device whose noise gate leaves a least-significant
        bit of dither reads as heard and never warns. That is a false negative —
        a presenter with a dead microphone on such a device learns nothing new,
        which is where they already are. Loosening it to a near-zero threshold
        would buy those devices a warning and buy every other device the
        cry-wolf failure, and only one of those is worth having.
        """
        return not self._ever and self._silent_bytes >= _UNHEARD_AFTER_BYTES
