"""Whether the room has ever heard anything at all. #77.

**The premise the task was written on turned out to be false**, and this file
is the correction. #77 records an emulator with its virtual microphone switched
off: 37 seconds of digital silence, then one empty final that a panelist
answered. It reads as an emulator artefact, and the proposed fix was to gate
silence out of the uplink and to tell the presenter their microphone was dead.

`docs/echo-cancellation.md` had already measured why neither works. In the
configuration this product actually ships — patched `Usage::VoiceCommunication`
on both streams, `MODE_IN_COMMUNICATION`, speakerphone — a *quiet room* on a
real S24+ measures **exact digital zero**, every sample, peak -120 dBFS. The doc
says the consequence in its own words: "perfect cancellation and a dead
microphone are indistinguishable in it."

So digital silence is not evidence of a broken microphone, on the one platform
where it was measured. It is what an ordinary pause sounds like. Two things
follow:

- Gating silence out of the uplink would gate every pause on Android, which is
  the signal the transcriber endpoints on. It would also make the 37-second
  hallucination *more* likely rather than less, by removing the only audio that
  distinguishes a thinking presenter from a hung phone.
- A level-based "your microphone is dead" warning would fire at every pause. It
  is the same cry-wolf failure `app/src/lib/audio/hearing.ts` already committed
  once and documents at length.

What *is* distinguishable is a room that has **never once** heard anything. A
working microphone delivers a non-zero sample the moment somebody speaks; a dead
one never does. That is a latch rather than a classifier: it can only fire
before the first real audio, and once the room has heard a voice it is off for
good and cannot interrupt anybody.
"""

from __future__ import annotations

from app.modules.voice.hearing import UNHEARD_AFTER_SECONDS, RoomHearing

#: A whole second of PCM16 at 16 kHz mono, in the two states that matter.
SILENT_SECOND = bytes(16_000 * 2)
SPOKEN_SECOND = b"\x11\x22" * 16_000


def test_a_room_that_has_just_opened_says_nothing():
    """The first buffers are all-zero on every device — `toDbfs`'s own docstring
    records the recorder warming up that way — and a room that shouted about it
    would fire on every single session."""
    ears = RoomHearing()
    ears.heard(SILENT_SECOND)

    assert not ears.unheard


def test_nothing_but_silence_for_long_enough_is_worth_saying():
    ears = RoomHearing()
    for _ in range(UNHEARD_AFTER_SECONDS):
        ears.heard(SILENT_SECOND)

    assert ears.unheard


def test_one_word_ever_settles_it_for_the_whole_room():
    """The latch, and the reason this is safe to show at all.

    A presenter who speaks once has proven the microphone. Everything after is
    an ordinary pause — which on Android is byte-for-byte identical to a dead
    microphone — and a warning that could fire there would fire on somebody
    mid-thought, which is the failure this design exists to avoid.
    """
    ears = RoomHearing()
    ears.heard(SPOKEN_SECOND)
    for _ in range(UNHEARD_AFTER_SECONDS * 4):
        ears.heard(SILENT_SECOND)

    assert not ears.unheard


def test_a_single_non_zero_sample_counts_as_hearing_something():
    """Deliberately the weakest possible evidence.

    Being wrong in this direction costs a warning nobody sees; being wrong in
    the other tells a presenter with a working microphone that it is broken.
    Only the second one is a product failure, so the test for "we heard
    something" is as easy to pass as it can be made.
    """
    ears = RoomHearing()
    ears.heard(bytes(999) + b"\x01" + bytes(1_000))
    for _ in range(UNHEARD_AFTER_SECONDS * 2):
        ears.heard(SILENT_SECOND)

    assert not ears.unheard


def test_silence_is_measured_in_audio_and_never_in_wall_clock():
    """A phone that has stopped sending has not been heard *for* any length of
    time — it has simply gone. That is the socket's failure and the reaper's,
    and answering it here would put a second opinion on the wire."""
    ears = RoomHearing()
    for _ in range(UNHEARD_AFTER_SECONDS * 2):
        ears.heard(b"")

    assert not ears.unheard


def test_it_fires_before_the_transcriber_invents_an_utterance():
    """The measurement #77 recorded: three rooms, 36-37 seconds of digital
    silence each, then one empty final that the panel answered. Telling the
    presenter after that has already happened is telling them nothing."""
    assert UNHEARD_AFTER_SECONDS < 36


def test_it_holds_past_a_plausible_pause_before_anybody_starts():
    """The other side of the same bound. `NUDGE_AFTER_SECONDS` is 60 and its
    docstring argues that silence is still plausibly thought below that; this
    is a stronger claim than the nudge makes and is shown to somebody who may
    simply not have begun, so it must not be hair-trigger."""
    assert UNHEARD_AFTER_SECONDS >= 20


def test_a_second_of_audio_weighs_what_the_relay_says_it_does():
    """`hearing.py` restates the wire's two constants rather than importing them
    from the module that imports it. That is only safe while they agree."""
    from app.modules.voice import hearing, orchestrated

    assert hearing.SAMPLE_RATE == orchestrated.SAMPLE_RATE
    assert hearing.BYTES_PER_SAMPLE == orchestrated.BYTES_PER_SAMPLE


def test_words_settle_it_even_if_the_bytes_did_not():
    """A final carrying words is the strongest possible evidence the microphone
    works, on whatever path it arrived. It should be unreachable — words cannot
    be made from all-zero samples — and is here so that a provider which manages
    it costs one wrong line of text rather than a room whose screen contradicts
    its own transcript."""
    ears = RoomHearing()
    for _ in range(UNHEARD_AFTER_SECONDS):
        ears.heard(SILENT_SECOND)
    assert ears.unheard

    ears.spoke()

    assert not ears.unheard
