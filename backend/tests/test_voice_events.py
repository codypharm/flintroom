"""The vocabulary a channel may speak in, and keeping it honest.

`VoiceEvent` is the union every consumer of a room matches against. It is
documentation about what can arrive — and documentation is what it stays unless
something checks it, which is the lesson this file was written for.

**`Spent` was missing from it for weeks.** The relay handled it, every test
passed, and nothing anywhere could notice: this project runs no type checker, so
a union is a comment that happens to be valid syntax. `Attending` would have
gone the same way a day later.

A type checker is the real answer and `uvx ty check app` is a start — it found
a second instance of exactly this (a method added to `client.py` and not to the
`ClientChannel` protocol) within a minute. But it reports sixty-eight
diagnostics against library stubs today, so it cannot gate anything yet. This
can, and it costs one file.
"""

from __future__ import annotations

import inspect
import typing

from app.modules.voice import events


def declared() -> set[str]:
    """Every event class this module defines, by name.

    Found by inspection rather than listed, because a list here would be the
    same thing the union already is: a second place to forget.
    """
    return {
        name
        for name, thing in vars(events).items()
        if inspect.isclass(thing)
        and thing.__module__ == events.__name__
        and not name.startswith("_")
        and name not in {"Attention"}  # a vocabulary, carried *by* an event
    }


def named_in_the_union() -> set[str]:
    return {member.__name__ for member in typing.get_args(events.VoiceEvent)}


def test_every_event_a_room_can_send_is_in_the_union():
    """The property `Spent` broke, and nothing else could have caught it.

    A consumer matching on `VoiceEvent` and an event that is not in it produce
    no error anywhere: the room sends it, the relay handles it by `isinstance`,
    and the union quietly stops describing reality. The failure only surfaces
    the day somebody trusts the union to be complete.
    """
    missing = declared() - named_in_the_union()

    assert missing == set(), (
        f"events a channel can send that `VoiceEvent` does not name: {sorted(missing)}"
    )


def test_the_union_names_nothing_that_is_not_an_event():
    """The other direction, which rots more quietly.

    A union naming a class that no longer exists fails loudly at import. One
    naming a class that exists but is no longer *sent* does not fail at all —
    it just makes every reader believe in a message the room stopped emitting.
    """
    invented = named_in_the_union() - declared()

    assert invented == set(), (
        f"`VoiceEvent` names things that are not events here: {sorted(invented)}"
    )
