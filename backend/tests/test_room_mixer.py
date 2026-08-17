"""The room as it sounded, not as it was sent.

`docs/session-retention.md` decides that a saved session is one mixed track, and
names the trap this module exists to avoid: panel audio runs ahead of playback
(`relay.py:250`, which is why barge-in calls `discard_playback`), so some frames
are **never heard**. Appending them as they arrive produces a recording in which
a panelist cut off at two words keeps talking for another eight seconds — every
barge-in replaying as a lie, about the one moment the product is built around.

What makes that fixable without any timestamp machinery is that the user's
uplink is continuous. `app/src/lib/audio/uplink.ts` sends every frame the
recorder produces with no voice-activity gating, so the user's stream is an
unbroken 16 kHz timeline for the life of the room — a wall clock the panel can
be positioned against.
"""

from __future__ import annotations

import array

from app.modules.voice.mixing import RoomMixer


def pcm(*samples: int) -> bytes:
    """PCM16 little-endian, the format the relay carries in both directions."""
    return array.array("h", samples).tobytes()


def test_a_room_where_only_the_user_speaks_is_what_they_said():
    """The tracer bullet: audio in, the same audio out.

    A room nobody answered is still a room, and it is the case every other
    behaviour here is a deviation from. If the mixer cannot reproduce a stream
    it never had to mix, nothing built on top of it is worth testing.
    """
    mixer = RoomMixer()

    mixer.heard(pcm(1, 2, 3))
    mixer.heard(pcm(4, 5))

    assert mixer.mixed() == pcm(1, 2, 3, 4, 5)


def test_a_panelist_is_heard_where_the_room_had_reached():
    """Panel speech is positioned, not appended to a pile.

    The naive recording concatenates whatever arrives, which happens to be right
    exactly once — the first time anybody speaks — and is wrong from then on.
    """
    mixer = RoomMixer()

    mixer.heard(pcm(1, 2))
    mixer.played(pcm(7, 8))

    assert mixer.mixed() == pcm(1, 2, 7, 8)


def test_the_user_talking_over_a_panelist_shares_the_timeline():
    """Barge-in is two people at once, and the recording has to say so.

    A room where the user waits politely for each panelist to finish is not the
    room this product sells. `Product.md` §5.1 chose the voice provider for
    barge-in specifically — so a recording that serialised the overlap would
    misrepresent the single moment a user most wants to hear again.

    Sample values add. PCM is a pressure wave and two sources in one room sum;
    laying one over the other would delete whichever was written second.
    """
    mixer = RoomMixer()

    mixer.played(pcm(10, 10, 10, 10))
    mixer.heard(pcm(1, 1))

    assert mixer.mixed() == pcm(11, 11, 10, 10)


def test_a_panelist_who_was_cut_off_does_not_finish_the_sentence():
    """The defect `docs/session-retention.md` names, and the reason to build this.

    Synthesis streams ahead of playback, so when the user cuts in there is
    already audio buffered that the phone will discard and nobody will ever
    hear. A recording that kept it would show a panelist talking over the user
    for seconds after they were silenced — turning the product's best moment
    into evidence that it does not work.

    Nothing here needs to know how much the phone had played. The user's stream
    is continuous, so their frontier *is* the current time, and panel audio
    written past it is by definition unplayed.
    """
    mixer = RoomMixer()

    mixer.heard(pcm(1, 1))
    mixer.played(pcm(9, 9, 9, 9, 9, 9))
    mixer.heard(pcm(2, 2))
    mixer.interrupted()

    assert mixer.mixed() == pcm(1, 1, 11, 11)


def test_two_loud_voices_at_once_clip_rather_than_invert():
    """A guard, not a driver — the clamp was written before this asked for it.

    Signed 16-bit arithmetic that overflows does not distort, it *inverts*: a
    loud peak becomes an equally loud peak of the opposite sign, heard as a
    click rather than as loudness. The moment both sources are loud at once is
    barge-in, so the failure would land on precisely the seconds a user replays
    to hear.
    """
    mixer = RoomMixer()

    mixer.played(pcm(30000))
    mixer.heard(pcm(30000))

    assert mixer.mixed() == pcm(32767)
