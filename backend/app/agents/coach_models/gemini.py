"""Gemini, as a `CoachModel`.

Everything vendor-shaped stops here: the parts layout, the schema dialect, the
field names usage arrives under.

**A fast model, and against the debrief's other choice.** `weakness_models`
picks a reasoning model deliberately, because reading a whole room for a fluent
wrong answer is what thinking is for. This is the opposite job: a conversation,
where the *turn* is what matters and a considered paragraph is worse than a
short sharp sentence — the same result `panel_spike.py` measured for the panel,
for the same reason.

There is a clock here too, just a gentler one. Nobody is being interrogated, but
a coach that takes four seconds to answer a follow-up stops feeling like a
conversation and starts feeling like a form being submitted, which is §3.5's
"static dashboard" arriving through latency instead of through layout.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx

from app.agents.coach import COACH, Cite, CoachReply, Grounds, Spoken
from app.agents.weakness import WeakAnswer
from app.agents.context import USER
from app.agents.model import TurnUsage
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger

log = get_logger(__name__, tag="debrief")

PROVIDER = "gemini"

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

API_KEY_HEADER = "x-goog-api-key"

DEFAULT_COACH_MODEL = "gemini-3.5-flash"

#: A coaching turn is one or two sentences. This is eight thousand of them, and
#: the gap is not caution — it is a measurement.
#:
#: Set to 1024 first, on the reasoning that the answer is short. Every grounded
#: question then came back redirected, 0 of 5, and the cause was in the reply:
#: `finishReason: MAX_TOKENS`, `candidatesTokenCount: 30`, and
#: **`thoughtsTokenCount: 979`**. `gemini-3.5-flash` thinks before it writes, so
#: the ceiling covers the thinking *and* the answer — and a budget sized for the
#: answer alone leaves thirty tokens of truncated JSON.
#:
#: `panel_models/gemini.py` records this failure in almost these words, and the
#: docstring that used to be here quoted it. Knowing the shape of a bug is not
#: the same as not writing it.
#:
#: The symptom is the reason it needs a comment this long: truncation arrives as
#: an unparseable reply, which arrives uncited, which `spoken` turns into the
#: redirect. So a ceiling set too low presents as a coach that politely tells
#: everybody to start a new room — scoped, safe, and useless, and indistinguishable
#: from the fence working correctly.
MAX_OUTPUT_TOKENS = 8192

_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "text": {
            "type": "STRING",
            "description": "What to say next. One or two sentences.",
        },
        "cites": {
            "type": "ARRAY",
            "description": (
                "Everything this turn is grounded in. A turn that cites nothing "
                "is not delivered."
            ),
            "items": {
                "type": "OBJECT",
                "properties": {
                    "kind": {"type": "STRING", "enum": ["line", "claim"]},
                    "index": {
                        "type": "INTEGER",
                        "description": (
                            "The number in brackets beside the line or claim."
                        ),
                    },
                },
                "required": ["kind", "index"],
            },
        },
    },
    "required": ["text", "cites"],
}



#: How long one coaching turn may take.
#:
#: Shorter than the debrief's and longer than the panel's, which is exactly
#: where it sits: somebody is waiting, but they are reading a screen rather
#: than holding a room open, and `docs/debrief-and-sparring.md` decision 5
#: makes this turn-based HTTP with no socket behind it.
#:
#: Explicit for the reason the debrief's is — the shared client's five seconds
#: belongs to a JWKS fetch, and inheriting it silently is how a feature becomes
#: a coin flip.
MODEL_TIMEOUT_SECS = 60.0

class GeminiCoachModel:
    """Holds the coaching conversation, one turn at a time."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_COACH_MODEL,
        http: httpx.AsyncClient,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._http = http

    async def reply(
        self, *, grounds: Grounds, exchange: Sequence[Spoken]
    ) -> CoachReply:
        payload = await self._generate(_prompt(grounds, exchange))
        reported = _reported(payload)

        return CoachReply(
            text=_text_of(reported),
            cites=_cites(reported),
            usage=_usage_of(payload),
        )

    async def spar(
        self, *, grounds: Grounds, weak: WeakAnswer, attempts: Sequence[str]
    ) -> CoachReply:
        """What changed between the first answer and the newest one."""
        payload = await self._generate(
            _retry_prompt(grounds, weak, attempts), instruction=SPARRING
        )
        reported = _reported(payload)

        return CoachReply(
            text=_text_of(reported),
            cites=_cites(reported),
            usage=_usage_of(payload),
        )

    async def _generate(
        self, prompt: str, *, instruction: str = ""
    ) -> dict[str, Any]:
        try:
            response = await self._http.post(
                f"{BASE_URL}/{self._model}:generateContent",
                headers={API_KEY_HEADER: self._api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "systemInstruction": {
                        "parts": [{"text": instruction or INSTRUCTION}]
                    },
                    "generationConfig": {
                        "maxOutputTokens": MAX_OUTPUT_TOKENS,
                        "candidateCount": 1,
                        "responseMimeType": "application/json",
                        "responseSchema": _SCHEMA,
                    },
                },
                timeout=MODEL_TIMEOUT_SECS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.warning(
                "coach_model_refused",
                provider=PROVIDER,
                model=self._model,
                status=exc.response.status_code,
            )
            raise ProviderUnavailable(reason="coach_model_error") from exc
        except httpx.HTTPError as exc:
            log.warning("coach_model_unreachable", provider=PROVIDER, model=self._model)
            raise ProviderUnavailable(reason="coach_model_unreachable") from exc

        return response.json()


def _reported(payload: dict[str, Any]) -> dict[str, Any]:
    """The object the model wrote, or nothing.

    An unparseable reply must not raise out of a phase the user was told is
    free. Nothing is the safe landing: the turn arrives uncited and `spoken`
    turns it into the redirect, so the worst case is a coach that says "start a
    room" once rather than a 500.
    """
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        log.warning("coach_reply_empty", provider=PROVIDER)
        return {}

    try:
        reported = json.loads(text)
    except json.JSONDecodeError:
        # Never the text. A coaching turn is about somebody's own material and
        # is the same class as a transcript line, which CLAUDE.md keeps out of
        # logs entirely.
        #
        # `finish_reason` is here because of how this failed the first time: a
        # truncated reply and a model answering in prose are both "unparseable",
        # and only one of them is fixed by raising a ceiling. Without it an
        # operator sees a coach that redirects everything and has nothing to go
        # on but the count.
        log.warning(
            "coach_reply_unparseable",
            provider=PROVIDER,
            finish_reason=_finish_reason(payload),
        )
        return {}

    return reported if isinstance(reported, dict) else {}


def _finish_reason(payload: dict[str, Any]) -> str | None:
    """Why the model stopped, when it stopped somewhere unhelpful."""
    try:
        return payload["candidates"][0].get("finishReason")
    except (KeyError, IndexError, TypeError):
        return None


def _text_of(reported: dict[str, Any]) -> str:
    text = reported.get("text")
    return text.strip() if isinstance(text, str) else ""


def _cites(reported: dict[str, Any]) -> tuple[Cite, ...]:
    """Typed citations, dropping anything that is not one.

    One malformed entry costs that entry rather than the turn — but not
    nothing, because dropping the only citation leaves the turn uncited and
    `spoken` redirects it. That is correct: a turn whose grounding could not be
    read is a turn nobody can check, and coercing a bad index to a default would
    invent a citation rather than lose one.
    """
    entries = reported.get("cites")
    if not isinstance(entries, list):
        return ()

    cites: list[Cite] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind, index = entry.get("kind"), entry.get("index")
        # `bool` is an `int` in Python, and `True` would index the first line.
        if kind not in ("line", "claim"):
            continue
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        cites.append(Cite(kind=kind, index=index))

    return tuple(cites)


def _usage_of(payload: dict[str, Any]) -> TurnUsage:
    """What Google says the call cost, reported even when nothing parsed."""
    usage = payload.get("usageMetadata") or {}
    return TurnUsage(
        input_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
    )


def _prompt(grounds: Grounds, exchange: Sequence[Spoken]) -> str:
    """Everything the coach is allowed to know, and the conversation so far."""
    return "\n\n".join(
        part
        for part in (
            _the_room(grounds),
            _what_went_wrong(grounds),
            _the_material(grounds),
            _so_far(exchange),
        )
        if part
    )


def _the_room(grounds: Grounds) -> str:
    """The transcript, numbered — and the numbers are the citation keys.

    Without them the model is asked to cite ordinals it was never shown, every
    citation fails the check, and every turn becomes the redirect. The product
    would look scoped and be useless, and nothing would raise.
    """
    lines = "\n".join(
        f"[{ordinal}] {'PRESENTER' if line.speaker == USER else line.speaker}: {line.text}"
        for ordinal, line in enumerate(grounds.transcript)
    )
    return f"THE SESSION\n{lines}" if lines else ""


def _what_went_wrong(grounds: Grounds) -> str:
    """The ranked list, keyed by the transcript line each is about.

    Deliberately not renumbered. A weak answer already points at a transcript
    ordinal, so citing that line cites the finding — one key, one meaning, and
    no second index for the model to confuse with the first.
    """
    if not grounds.weak_answers:
        return ""

    found = "\n".join(
        f"- line [{answer.ordinal}] ({answer.weakness.value}): {answer.why}"
        for answer in grounds.weak_answers
    )
    return f"WHAT THE ROOM FOUND, WORST FIRST\n{found}"


def _the_material(grounds: Grounds) -> str:
    if not grounds.claims:
        return ""

    claims = "\n".join(
        f"[{index}] {claim}" for index, claim in enumerate(grounds.claims)
    )
    return f"THEIR ATTACHED MATERIAL\n{claims}"


def _so_far(exchange: Sequence[Spoken]) -> str:
    """The coaching conversation, ending with what they just said."""
    turns = "\n".join(
        f"{'YOU' if turn.who == COACH else 'THEM'}: {turn.text}" for turn in exchange
    )
    return f"THE CONVERSATION SO FAR\n{turns}" if turns else ""


INSTRUCTION = """\
You are a speaking coach. Your presenter has just finished a rehearsal in which \
a panel of experts interrogated them, and you are talking it through with them \
afterwards. The session is below, numbered, along with what the room found and \
any material they attached.

Talk like a person. Answer what they actually asked, follow up, disagree with \
them when they are wrong about their own session. This is a conversation, not a \
report.

**Everything you say must be about this session.** For every turn, cite the \
numbered line or claim you are working from. Cite the line the presenter said, \
or the line the panel said, whichever your point is about.

**Not knowing an answer is not the same as being off-topic.** If they ask what \
they should have said and you do not have their real numbers, say so — and \
still cite the line you are talking about. A question about this session stays \
a question about this session even when the honest reply is "I don't know your \
figures, but the panel wanted one."

Cite nothing only when the question is about something this session does not \
contain at all: a different pitch, a new deck, how they are doing in general. \
Do not answer those from your own knowledge. Their next room is where that gets \
looked at properly.

Keep it to one or two sentences unless they asked for more.\
"""


def _retry_prompt(
    grounds: Grounds, weak: WeakAnswer, attempts: Sequence[str]
) -> str:
    """The question, the answer that failed it, and every go since."""
    tries = "\n".join(
        f"ATTEMPT {number}: {said}" for number, said in enumerate(attempts, start=1)
    )

    return "\n\n".join(
        part
        for part in (
            _the_room(grounds),
            (
                "THE QUESTION THEY ARE RE-ANSWERING\n"
                f"[{weak.ordinal}] {weak.asked_by}: {weak.question}"
            ),
            f"WHAT THEY SAID IN THE ROOM\n{weak.answer or '(they said nothing)'}",
            f"WHAT WAS THIN ABOUT IT\n{weak.why}",
            f"THEIR RE-ANSWERS, OLDEST FIRST\n{tries}",
        )
        if part
    )


#: The sparring instruction, and the one line in it that matters most is the
#: refusal to grade. `docs/debrief-and-sparring.md` decision 4: false praise
#: sends somebody into the real room believing a thin answer landed, and that is
#: worse than saying nothing at all.
SPARRING = """\
You are a speaking coach running a re-try. Your presenter fumbled a question in \
a rehearsal and is answering it again, out loud, as many times as they want.

Below is the session, the question, what they said the first time, what was thin \
about it, and every attempt they have made since.

**Say what CHANGED.** Compare their newest attempt to what they said before, and \
name the difference concretely: what is there now that was not, and what is \
still missing. "You have the number now, but you still haven't said what moved \
it."

**Do not grade it.** Never say whether it is good enough, whether it would work, \
or whether they are ready. They decide when to stop, not you. Telling somebody a \
thin answer landed sends them into the real room believing it, which is the one \
outcome this loop exists to prevent.

If the newest attempt is worse than an earlier one, say so plainly. That is a \
difference too, and it is often the most useful one you have.

Cite the numbered line your comparison rests on. One or two sentences.\
"""
