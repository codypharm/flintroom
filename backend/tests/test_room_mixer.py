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

from app.modules.voice.mixing import SAMPLE_RATE, RoomMixer


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


def test_a_room_that_runs_long_stops_growing_rather_than_growing_forever():
    """The mixer bounds its own memory. It does not inherit a bound.

    A live room is ~23 MB of PCM16 today, and only because `SESSION_LIMIT`
    happens to be twelve minutes — a constant in `sessions/schemas.py` with
    nothing tying it to this module. Raising it is a plausible product change
    and an entirely reasonable one to make without thinking about audio, at
    which point a per-room memory ceiling silently becomes no ceiling, at
    ~1.92 MB per minute per concurrent room.

    Dropping the tail is the right failure. A room that refused to record past
    its limit still interrogates, still settles and still bills correctly; one
    that raised would trade a complete rehearsal for a partial recording.
    """
    mixer = RoomMixer(max_samples=4)

    mixer.heard(pcm(1, 2, 3))
    mixer.heard(pcm(4, 5, 6))

    assert mixer.mixed() == pcm(1, 2, 3, 4)
    assert mixer.truncated


def test_the_room_clock_is_where_the_users_own_stream_has_reached():
    """#69. The mix's timeline is the uplink, and the uplink is continuous.

    `app/src/lib/audio/uplink.ts` sends every frame the recorder produces with
    no voice-activity gating, so a second of samples is a second of room. That
    is what makes a sample count usable as a clock at all, and it is the same
    property the positioning above already leans on.
    """
    mixer = RoomMixer()

    mixer.heard(pcm(*([0] * SAMPLE_RATE)))

    assert mixer.elapsed() == 1.0


def test_a_panelist_speaking_does_not_move_the_room_clock():
    """The panel is positioned *against* the clock, never a source of it.

    Synthesis streams faster than real time — an eight-second answer can arrive
    inside one — so counting panel audio would make the room's clock run at
    whatever rate the vendor happened to deliver at, and every offset after the
    first turn would point somewhere the room never was.
    """
    mixer = RoomMixer()

    mixer.heard(pcm(*([0] * SAMPLE_RATE)))
    mixer.played(pcm(*([0] * (SAMPLE_RATE * 8))))

    assert mixer.elapsed() == 1.0


def test_a_room_nobody_wants_kept_still_knows_what_time_it_is():
    """#52 turns off *keeping the audio*, not knowing when things happened.

    The gate used to sit in the relay — `if self._records: self._mixer.heard()`
    — which stopped the clock along with the recording. Every line in a room
    with recording switched off would then have claimed to begin at second
    zero, and the latency reading #69 exists to make possible would have been
    a column of zeroes on exactly the accounts that never opted in.
    """
    mixer = RoomMixer(keeping=False)

    mixer.heard(pcm(*([0] * SAMPLE_RATE)))

    assert mixer.elapsed() == 1.0


def test_a_room_nobody_wants_kept_holds_none_of_it():
    """And "off" still means not gathered, which is the point of the gate.

    `router.py` reads the preference before a single frame is accumulated so a
    room the user asked not to record never holds their audio in memory at all.
    Moving the gate in here must not quietly turn that into "gathered, then
    discarded at the end".
    """
    mixer = RoomMixer(keeping=False)

    mixer.heard(pcm(1, 2, 3))
    mixer.played(pcm(4, 5))

    assert mixer.mixed() == b""


def test_a_room_nobody_wants_kept_has_no_ceiling_to_hit():
    """Nothing is stored, so there is no memory to bound and nothing to drop.

    A cap applied here would stall the clock at twenty minutes, and every line
    after that would report the same offset — a wrong answer where the honest
    one costs nothing, because the ceiling exists to bound an array this room
    never fills.
    """
    mixer = RoomMixer(keeping=False, max_samples=4)

    mixer.heard(pcm(1, 2, 3))
    mixer.heard(pcm(4, 5, 6))

    assert mixer.elapsed() == 6 / SAMPLE_RATE
    assert not mixer.truncated
