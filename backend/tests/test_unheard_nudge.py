"""What the room asks when it has never heard anything. #77.

**The bug this fixes is live.** #24 gave every archetype a nudge for the quiet
at sixty seconds, and every one of those lines asks the presenter to *speak* —
"Take your time, but say something", "Come on, talk to me", "Don't leave us
hanging". Nothing consulted whether the room had ever heard anything before
choosing one.

So a presenter whose microphone is dead, who has been talking for a full minute,
was told at sixty seconds to do the exact thing they had been doing. That is
worse than saying nothing: it reads as a room that is not listening, which is
the failure this whole area keeps arriving back at.

The remedy is the question, not the channel. #24's argument for speaking holds
here and holds harder — the phone is flat on a desk and a presenter rehearsing
hands-free is looking at their notes, not at it. What has to change is *which*
question a room that has heard nothing asks, so it sends them to the handset
rather than back to the microphone.
"""

from __future__ import annotations

from app.agents.archetypes import DEFAULT_PANEL, LIBRARY
from app.agents.silence import nudge_from


def test_every_shipped_archetype_can_say_it_is_getting_nothing():
    """The same guarantee `nudges` relies on, and it relies on it for the same
    reason: `docs/custom-archetypes.md` seats at least one shipped archetype in
    every room precisely because these lines are hand-written, so a room of
    entirely custom panelists would go quiet at the moment it must not."""
    for archetype in LIBRARY:
        assert archetype.unheard, f"{archetype.name} cannot say it hears nothing"


def test_a_room_that_has_heard_nothing_asks_a_different_question():
    who, line = nudge_from(DEFAULT_PANEL, choose=lambda options: options[0], heard=False)

    assert line in who.unheard
    assert line not in who.nudges


def test_a_room_that_has_heard_them_asks_the_ordinary_one():
    """The default, and it must stay the default. Somebody thinking hard about a
    hostile question has a working microphone and wants "still there?", not to
    be sent to check a handset that is fine."""
    who, line = nudge_from(DEFAULT_PANEL, choose=lambda options: options[0])

    assert line in who.nudges


def test_it_never_tells_a_silent_presenter_to_say_something():
    """The bug, stated as the thing that must not happen.

    Every one of these is heard by somebody whose words are not arriving. A line
    asking them to speak, repeat, or go on is the room telling them to keep
    doing what has already failed.
    """
    asking_them_to_talk = (
        "say",
        "talk",
        "speak",
        "go on",
        "hear you",
        "anything?",
    )

    for archetype in LIBRARY:
        for line in archetype.unheard:
            spoken = line.lower()
            for phrase in asking_them_to_talk:
                assert phrase not in spoken, f"{archetype.name}: {line!r}"


def test_it_says_the_failure_is_at_our_end():
    """Never "your microphone is broken", which the room cannot know — a
    presenter who simply has not started yet produces identical bytes. Stating
    our own side is true in both readings and actionable in both, and it is the
    same discipline the screen's wording follows."""
    for archetype in LIBRARY:
        for line in archetype.unheard:
            assert any(
                ours in line.lower()
                for ours in ("we", "us", "our", "this end", "nothing")
            ), f"{archetype.name}: {line!r}"


def test_nobody_says_it_in_words_a_model_wrote():
    """Hand-written for the reason the nudges are, and more so: this is spoken
    into a room that is already failing, and a composed line would be a model
    call made about nothing at all."""
    for archetype in LIBRARY:
        for line in archetype.unheard:
            assert len(line.split()) <= 10, f"{archetype.name}: {line!r}"
            assert "[" not in line and "]" not in line


def test_two_archetypes_never_say_it_the_same_way():
    """§3.3's "synthetic within two minutes" failure. A shared line is the panel
    audibly being one voice in eight costumes, and it would land hardest here —
    heard by somebody already wondering whether the room is real."""
    seen: dict[str, str] = {}

    for archetype in LIBRARY:
        for line in archetype.unheard:
            assert line not in seen, f"{archetype.name} and {seen[line]} share {line!r}"
            seen[line] = archetype.name


def test_no_line_is_shared_with_the_ordinary_nudge():
    """They answer different questions. One reused across both would make the
    distinction this task exists to draw invisible in the room."""
    for archetype in LIBRARY:
        assert not set(archetype.unheard) & set(archetype.nudges), archetype.name
