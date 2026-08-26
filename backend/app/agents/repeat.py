"""'Come again?' — recognising a repeat request, and choosing what to repeat.

Observed on the first Play build (Kettleworks run, 2026-08-26): the presenter
asked a panelist to say their question again, and selection — which routes any
finished utterance — handed the floor to a *different* panelist, who re-asked
their own earlier question. The room had no concept of a repeat, so an
ambiguous three-word utterance was treated as an answer to be challenged.

Deterministic on both sides, like the reentry it mirrors (`reentry_from`):
recognising the request is arithmetic over words, and honouring it is the last
panel line said again verbatim. No selection, no composer — a paraphrase would
be a model call about nothing, and a second wording of a question that already
exists.

**Conservative on purpose.** A missed request costs nothing new — the room
answers it the way it always has. A false positive replays a question over
somebody mid-argument, which is worse than either. So a request is only a
request when the *whole* utterance is one, not when a trigger phrase appears
somewhere inside an answer.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.agents.context import Said, USER

#: The whole utterance, or nothing. Each pattern is anchored to the full
#: (normalised) text so that "I'll come again to that point" — a sentence that
#: merely contains a trigger — can never match.
_REQUESTS = tuple(
    re.compile(pattern)
    for pattern in (
        r"come again",
        r"(please )?(say|read) (that|it) (again|back)( please)?",
        r"(can|could|would) you (please )?(say|repeat) (that|it|the question)( again)?( please)?",
        r"(please )?repeat (that|it|the question)( please)?",
        r"what was (that|the question)( again)?",
        r"what did you (say|ask)( again)?",
        r"pardon( me)?",
        r"sorry",
        r"what",
        r"huh",
        r"(i )?(didn'?t|did not|couldn'?t|could not) (catch|hear|get) (that|it|you)",
        r"one more time( please)?",
    )
)

#: Leading softeners stripped before matching — "sorry, come again?" is the
#: same request as "come again". Stripped only from the front: "sorry" at the
#: start softens; "sorry" mid-sentence is an apology, which is an answer.
_PREAMBLE = re.compile(r"^(sorry|sorry but|excuse me|uh|um|er|hm+|wait|oh)[,\s]+")

#: A request is short. Anything past this is somebody making a point that
#: happens to contain a trigger phrase, and the anchoring already refuses it —
#: the cap is defence in depth against a pattern growing a loose tail.
_MOST_WORDS = 8


def asked_to_repeat(text: str) -> bool:
    """Whether this utterance is a request to hear the last question again."""
    plain = re.sub(r"[^a-z' ]", " ", text.lower()).strip()
    plain = re.sub(r"\s+", " ", plain)
    for _ in range(3):
        softened = _PREAMBLE.sub("", plain)
        if softened == plain:
            break
        plain = softened

    if not plain or len(plain.split()) > _MOST_WORDS:
        return False

    return any(request.fullmatch(plain) for request in _REQUESTS)


def question_to_repeat(transcript: Sequence[Said]) -> Said | None:
    """The line to say again: the last panel line, skipping the request itself.

    By the time the room consults this, the presenter's "come again" has
    already been filed — the transcript records what was heard, requests
    included — so trailing user lines are stepped over. `None` when nobody has
    asked anything yet, which the caller reads as "handle it like any other
    utterance".
    """
    for line in reversed(transcript):
        if line.speaker != USER:
            return line
    return None
