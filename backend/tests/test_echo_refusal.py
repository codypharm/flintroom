"""#78 — the matcher that tells the panel's returning voice from the presenter.

Pure text against text, no channel: the discriminant has to be right about four
different speakers — the echo, the genuine answer, the deliberate repeat, and
the fragment — before it earns a place on the live path.
"""

from app.modules.voice.echo import hears_itself

PANEL = "What specifically breaks when ten times as many customers use it tomorrow?"


def test_the_measured_echo_is_heard_as_the_room_itself():
    """The pair from room 066f32db, differing only by "ten" -> "10".

    This is the bug as it actually happened, not a construction: six of nine
    "user" lines were this shape, and every one composed a turn against words
    the presenter never said.
    """
    heard = "What specifically breaks when 10 times as many customers use it tomorrow?"
    assert hears_itself(PANEL, heard).is_echo


def test_a_verbatim_return_is_heard_as_the_room_itself():
    assert hears_itself(PANEL, PANEL).is_echo


def test_a_genuine_answer_is_not_an_echo_however_much_vocabulary_it_shares():
    heard = "At ten times the load the ingest queue breaks first, customers see stale data."
    assert not hears_itself(PANEL, heard).is_echo


def test_repeating_the_question_to_buy_time_is_kept():
    """The false positive the architect ruled on: repetition plus anything.

    "What breaks at ten times scale? Well —" is somebody thinking aloud, and
    the added words are what prove it. Only a repeat that adds nothing at all
    is swallowed.
    """
    heard = (
        "What specifically breaks when ten times as many customers use it "
        "tomorrow? Well, three things."
    )
    assert not hears_itself(PANEL, heard).is_echo


def test_a_fragment_thrown_back_is_kept():
    """"Ten times?" is a presenter asking, not a loudspeaker returning.

    A completed playback echoes whole — a fragment can only be echo when
    playback was cut, and playback is only cut when the presenter is already
    talking, which is exactly the mix the transcriber is measured to reject.
    So low coverage of the panel line means a person.
    """
    assert not hears_itself(PANEL, "Ten times?").is_echo


def test_an_unrelated_line_is_kept():
    assert not hears_itself(PANEL, "Our margin is seventy percent.").is_echo
