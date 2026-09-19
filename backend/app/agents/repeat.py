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

**Anchored on purpose.** A false positive replays a question over somebody
mid-argument. So a request is only a request when the *whole* utterance is
one, not when a trigger phrase appears somewhere inside an answer.

**But a miss is not free, and this file used to claim it was.** The original
wording here read "a missed request costs nothing new — the room answers it
the way it always has", and that is what justified keeping the patterns
narrow. It is false. An unrecognised request falls through to selection, and
`routing.choose` scores on domain keywords plus turns of silence — a request
carries no domain vocabulary, so the score collapses to *who has been quiet
longest*, which picks a **different panelist every time**. A near miss does
not degrade gracefully; it produces the exact failure this module was written
to prevent.

Reported again 2026-09-19 ("can you rephrase that for me"), which is the third
instance of one symptom. The patterns were widened rather than loosened: the
whole-utterance anchoring is untouched and the word cap still holds, and the
negative tables grew alongside the positive ones. What changed is that
trailing softeners come off like leading ones already did, objects are
optional where English makes them optional, and the two lists no longer
disagree with each other about what a question may be called.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.agents.context import Said, USER

#: What a request can call the thing it wants again. One fragment rather than
#: an alternation repeated per pattern, because the 2026-09-19 widening found
#: the lists had already drifted: "the question" was accepted and "that
#: question" was not, in patterns sitting four lines apart.
_THAT = r"(that|it|the question|that question|your question)"

#: The whole utterance, or nothing. Each pattern is anchored to the full
#: (normalised) text so that "I'll come again to that point" — a sentence that
#: merely contains a trigger — can never match.
_REQUESTS = tuple(
    re.compile(pattern)
    for pattern in (
        r"come again",
        # `ask` sits beside `say` and `repeat` because "can you ask that
        # again" is the same request, and the object is optional because
        # "say again" is how half of people shorten it.
        r"(please )?(say|read|repeat|ask) ((me|us) )?(" + _THAT + r" )?(again|back)",
        r"(can|could|would) you (please )?(say|repeat|ask) ((me|us) )?("
        + _THAT
        + r"( again)?|again)",
        r"(please )?repeat " + _THAT,
        r"(would|do) you mind (saying|repeating|asking) " + _THAT + r"( again)?",
        r"run " + _THAT + r" by (me|us) again",
        r"what was (that|the question)( again)?",
        r"what did you (say|ask)( again)?",
        r"pardon( me)?",
        r"sorry",
        r"what",
        r"huh",
        # `quite` is the whole reason this line changed. "I didn't quite catch
        # that" is the commonest form of all, and nothing was allowed between
        # the negation and the verb.
        r"(i )?(didn'?t|did not|couldn'?t|could not) (quite )?(catch|hear|get) (that|it|you)",
        r"((please )?(say|repeat) (that|it) )?one more time",
    )
)

#: Leading softeners stripped before matching — "sorry, come again?" is the
#: same request as "come again". Stripped only from the front: "sorry" at the
#: start softens; "sorry" mid-sentence is an apology, which is an answer.
_PREAMBLE = re.compile(r"^(sorry|sorry but|excuse me|uh|um|er|hm+|wait|oh)[,\s]+")

#: Trailing softeners, stripped for the reason the leading ones are: "could
#: you repeat that for me" is the same request as "could you repeat that".
#:
#: This is why no pattern above or below carries a `( please)?` tail any more.
#: They did, unevenly, which is how "sorry, could you repeat that for me" came
#: to miss — the front was softened and the back was not, and only some
#: patterns had thought about the back at all.
#:
#: A separator is required before the softener, so a bare "please" is left
#: alone rather than reduced to nothing.
_TRAILING = re.compile(r"[,\s]+(please|for me|for us|if you (don'?t|do not) mind)$")

#: *I did not understand you* — a different request, wanting the opposite
#: thing (#117).
#:
#: Reported by a tester 2026-09-01: they asked the panelist to rephrase, and a
#: different panelist took the floor. Every pattern above is a variant of *I
#: did not hear you*, so the utterance matched nothing and selection routed it
#: as an ordinary answer — the failure this module was written to fix, arriving
#: through the door it did not cover.
#:
#: **The two must not overlap**, which is why they are separate tuples rather
#: than one list with a flag. A misfiled *did not hear* costs a composer call
#: and a re-wording nobody wanted. A misfiled *did not understand* returns the
#: identical words to somebody who has just said they did not follow, which
#: reads as the panel ignoring them a second time.
#:
#: Anchored to the whole utterance under the same rule, and for the same
#: reason: a false positive re-asks a question over somebody mid-argument.
_REPHRASINGS = tuple(
    re.compile(pattern)
    for pattern in (
        # The space lives *inside* the optional group. It did not, and that one
        # character is why the bare "can you rephrase" — the most natural form
        # there is — was the single phrasing this half could not recognise.
        r"(can|could|would) you (please )?rephrase( " + _THAT + r")?",
        r"(please )?rephrase( " + _THAT + r")?",
        r"what do you mean( by (that|it))?( exactly)?",
        r"(i )?(don'?t|do not|didn'?t|did not) (quite )?understand( " + _THAT + r")?",
        r"(can|could|would) you (please )?(put|say) (that|it) another way",
        r"(please )?(put|say) (that|it) another way",
        r"(in )?plain english",
        r"(i'?m )?not sure what you('?re| are) asking",
        # Object optional, because "I don't follow" on its own is how it is
        # usually said. The anchoring is what keeps "I don't follow the usual
        # playbook here" out.
        r"(i )?(don'?t|do not) (get|follow)( (that|it|you|the question))?",
    )
)

#: A request is short. Anything past this is somebody making a point that
#: happens to contain a trigger phrase, and the anchoring already refuses it —
#: the cap is defence in depth against a pattern growing a loose tail.
_MOST_WORDS = 8


def _normalised(text: str) -> str | None:
    """The utterance reduced to bare words, or `None` if it cannot be a request.

    Shared by both readings so that "sorry, what do you mean?" and "sorry, come
    again?" are softened, punctuated and length-capped identically. Two copies
    of this would drift, and the drift would show up as one request being
    recognised and the other not.
    """
    plain = re.sub(r"[^a-z' ]", " ", text.lower()).strip()
    plain = re.sub(r"\s+", " ", plain)
    for _ in range(3):
        softened = _PREAMBLE.sub("", plain)
        if softened == plain:
            break
        plain = softened

    # After the preamble and before the length check, so that "for me please"
    # comes off in both halves and a softener can never be what pushes an
    # utterance past the word cap.
    for _ in range(3):
        softened = _TRAILING.sub("", plain)
        if softened == plain:
            break
        plain = softened

    if not plain or len(plain.split()) > _MOST_WORDS:
        return None
    return plain


def asked_to_repeat(text: str) -> bool:
    """Whether this utterance is a request to hear the last question again.

    *I did not hear you.* Answered verbatim, by the same panelist — see
    `question_to_repeat`.
    """
    plain = _normalised(text)
    return plain is not None and any(one.fullmatch(plain) for one in _REQUESTS)


def asked_to_rephrase(text: str) -> bool:
    """Whether this utterance is a request to hear it put differently (#117).

    *I did not understand you*, which is not the same request and does not want
    the same answer. Repeating identical words to somebody who has just said
    they did not follow reads as the panel ignoring them twice.

    Answering this one costs a composer call, so it is deliberately the
    narrower of the two: anything ambiguous falls to `asked_to_repeat` or to
    ordinary routing, both of which are free.
    """
    plain = _normalised(text)
    return plain is not None and any(one.fullmatch(plain) for one in _REPHRASINGS)


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
