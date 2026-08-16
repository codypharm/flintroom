"""Gemini as a `PanelModel`.

Everything vendor-shaped stops here: the URL, the header, the content-block
layout, where the text hides in the response.

**Plain `httpx`, not the Google SDK**, and the reasoning differs from the one
that justified the Anthropic SDK for extraction. That decision was bought with
two things: retry-with-backoff against a provider returning 429s under load, and
the Batch API's roughly halved pricing. Neither applies here.

A panel turn is on the latency-critical path — `docs/panel-orchestration.md` puts
the whole chain under ~1.5s or the room stops feeling real — so exponential
backoff is the wrong behaviour, not a missing one. A retry that lands two seconds
later has already lost the turn. And there is no batch anything in a live
conversation.

What is left is one POST with a JSON body, which httpx already does, and a
transport that a test can substitute without a live endpoint or a funded account.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.agents.archetypes import Archetype
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger

log = get_logger(__name__, tag="panel")

PROVIDER = "gemini"

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

#: The API-key header rather than `Authorization: Bearer` or a `key=` query
#: parameter. Google documents all three; this one is unambiguous — a Gemini API
#: key is not an OAuth token — and, unlike the query parameter, it keeps the
#: credential out of URLs, which are the part of a request that ends up in access
#: logs and error trackers.
#:
#: If a live call ever returns 401 with a key that is known good, this constant
#: is the first place to look.
API_KEY_HEADER = "x-goog-api-key"

#: The line itself is the product — and **measured, the cheap model wins twice**.
#:
#: `scripts/panel_spike.py` against a real contradiction, 2026-08-16:
#:
#:   gemini-3.7-flash       2.11s   383 thinking tokens
#:     "Slide four says sixty-one percent in 2026, but you just told us seventy
#:      today—where did those nine hundred basis points come from?"
#:
#:   gemini-3.5-flash-lite  0.82s   no thinking
#:     "Slide four says sixty-one. You just said seventy.
#:      Which number is lying to me?"
#:
#: Two and a half times faster on a path with ~1.5s in total, and the better
#: line: a panelist says one short thing, and a reasoning model produces a
#: considered paragraph. The assumption going in — cheap model routes, strong
#: model speaks — was wrong in the direction that costs money, which is why
#: `docs/panel-orchestration.md` said to measure it rather than argue it.
#:
#: Stable rather than preview either way: a room somebody is paying for by the
#: minute is the wrong place for a model that can be withdrawn.
DEFAULT_COMPOSITION_MODEL = "gemini-3.5-flash-lite"

#: Selection returns a name. Anything longer is the model explaining itself, and
#: sixteen was measured sufficient — flash-lite answers `cfo` in two tokens.
MAX_SELECTION_TOKENS = 16

#: A ceiling, not a target. The prompt is what keeps a line short — measured, the
#: model stops itself at twenty-odd tokens — and this only has to be high enough
#: that nothing is ever cut mid-sentence.
#:
#: Deliberately generous, because the failure it prevents is silent and was
#: observed: a *reasoning* model spends this budget thinking before it writes, so
#: a tight ceiling returns "Slide" or an empty string with `finishReason:
#: MAX_TOKENS` and the room says nothing at all. The models configured here do no
#: thinking, but the next one somebody points this at might.
MAX_LINE_TOKENS = 512

#: Nothing here asks a model to stop reasoning, and the attempt is worth
#: recording so it is not made twice.
#:
#: `thinkingConfig: {thinkingBudget: 0}` is rejected outright by
#: `gemini-3.5-flash-lite` — 400, INVALID_ARGUMENT — and on `gemini-3.7-flash` it
#: was accepted and then ignored: the response still carried a `thoughtSignature`
#: and still spent 383 tokens thinking. Neither model can be talked out of its
#: own default.
#:
#: The answer was to choose a model that does not reason rather than to argue
#: with one that does. See `DEFAULT_COMPOSITION_MODEL`.


class GeminiPanelModel:
    """Who speaks, and what they say, from Google's text models."""

    def __init__(
        self,
        *,
        api_key: str,
        http: httpx.AsyncClient,
        composition_model: str = DEFAULT_COMPOSITION_MODEL,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._composition_model = composition_model

    async def compose(
        self, *, archetype: Archetype, context, finding=None
    ) -> str:
        """Write this archetype's next line.

        The system instruction holds one persona and one attack strategy —
        never the panel. That is the whole voice-separation decision, and the
        reason it lives in the prompt rather than in a comment is that a prompt
        assembling all four is exactly what somebody would write if they were
        optimising a call out.
        """
        return await self._generate(
            model=self._composition_model,
            system=_persona_of(archetype),
            prompt=_composition_prompt(context, finding, archetype),
            max_tokens=MAX_LINE_TOKENS,
        )

    async def select(self, *, candidates: Sequence[Archetype], context) -> str:
        """Name whoever should take the floor.

        Cheap by construction: the roster and one sentence, answered in two
        tokens. Measured warm at 0.78-0.91s across the full eight-archetype
        library, which is why it is meant to run against a partial transcript
        while the user is still speaking rather than after they stop.
        """
        answered = await self._generate(
            model=self._composition_model,
            system=_SELECTION_INSTRUCTION,
            prompt=_selection_prompt(candidates, context),
            max_tokens=MAX_SELECTION_TOKENS,
        )
        return _bare_name(answered)

    async def _generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        max_tokens: int,
    ) -> str:
        try:
            response = await self._http.post(
                f"{BASE_URL}/{model}:generateContent",
                headers={API_KEY_HEADER: self._api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "systemInstruction": {"parts": [{"text": system}]},
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "candidateCount": 1,
                    },
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # `reason` goes to the log, never to the client. `ProviderUnavailable`
            # must not name the vendor (CLAUDE.md): it tells whoever is probing
            # what our architecture is, and it goes stale the moment the provider
            # is swapped — which is the swap this interface exists to permit.
            log.warning(
                "panel_model_refused",
                provider=PROVIDER,
                model=model,
                status=exc.response.status_code,
            )
            raise ProviderUnavailable(reason="panel_model_error") from exc
        except httpx.HTTPError as exc:
            # A timeout or a dropped connection. Caught separately from a status
            # because there is nothing to read off it, and left broad within
            # httpx's own hierarchy rather than enumerated — a new transport
            # error class should surface as a 502, not as a 500.
            log.warning("panel_model_unreachable", provider=PROVIDER, model=model)
            raise ProviderUnavailable(reason="panel_model_unreachable") from exc

        return _text_of(response.json())


def _bare_name(answered: str) -> str:
    """An archetype name out of whatever the model decided to wrap it in.

    Asked for a name, a model returns `**cfo**`, `"cfo"`, `cfo.` or a name with a
    newline after it. All four are the same answer and none of them match an
    archetype, so left alone they fall through to the caller's fallback — the
    room keeps running and silently stops routing, which looks exactly like a
    panel choosing at random.

    Deliberately narrow: strip the punctuation a model decorates with, take the
    first word, and stop. Anything cleverer starts guessing at which archetype
    was meant, and a wrong guess is worse than a fallback because it is confident.
    """
    return answered.strip().strip('*"\'`.,:;!?').split()[0].lower() if answered.strip() else ""


def _text_of(payload: dict[str, Any]) -> str:
    """The line, out of the shape Google returns it in."""
    candidates = payload.get("candidates") or []
    parts = (candidates[0].get("content", {}) if candidates else {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()


def _persona_of(archetype: Archetype) -> str:
    """One archetype's system instruction, and nobody else's."""
    return (
        f"You are {archetype.title} on a panel interrogating a presenter.\n\n"
        f"Who you are: {archetype.persona}\n\n"
        f"What you go after: {archetype.attack_strategy}\n\n"
        "Speak only as yourself. Say one thing — a single question or a single "
        "challenge, in the voice described above. Never narrate, never explain "
        "that you are an AI, and never speak for anybody else in the room."
    )


_SELECTION_INSTRUCTION = (
    "You are directing a panel. Given what the presenter just said and who is in "
    "the room, name the single panelist who should speak next. Prefer whoever's "
    "expertise the answer just touched, whoever has been quiet, or whoever would "
    "disagree with what was said last. Reply with the name and nothing else."
)


def _selection_prompt(candidates: Sequence[Archetype], context) -> str:
    """The whole room, attributed.

    Who has been quiet and what ground is covered is precisely what this call is
    for. The roster is sent as written, which is what makes a custom archetype
    work with nothing registered anywhere — its persona is just more text.
    """
    roster = "\n".join(
        f"- {archetype.name}: {archetype.title}. {archetype.attack_strategy}"
        for archetype in candidates
    )
    asked = "\n".join(
        f"- {entry.archetype}: {entry.question}" for entry in context.grounding.asked
    )
    already = f"\n\nAlready asked:\n{asked}" if asked else ""
    return f"In the room:\n{roster}{already}\n\nThey just said:\n{context.said}"


def _bare_name(answered: str) -> str:
    """An archetype name out of whatever the model wrapped it in.

    Asked for a name, a model returns `**cfo**`, `"cfo"` or `cfo.` — all the same
    answer, none of which match. Left alone they reach the caller's fallback and
    the panel silently stops routing, which looks exactly like choosing at random.

    Deliberately narrow: strip the decoration, take the first word, stop. Anything
    cleverer starts guessing which archetype was meant, and a wrong guess is worse
    than a fallback because it is confident.
    """
    stripped = answered.strip().strip('*"\'`.,:;!?')
    return stripped.split()[0].lower() if stripped.split() else ""


def _composition_prompt(context, finding, archetype: Archetype) -> str:
    """What this archetype is allowed to work from.

    Claims first, because they are the thing a challenge must trace back to —
    `CLAUDE.md` refuses to ship interrogation logic that cannot cite its source.
    Then what has already been asked, so the room stops repeating itself.
    """
    parts = []

    if context.grounding.claims:
        cited = "\n".join(f"- {claim}" for claim in context.grounding.claims)
        parts.append(f"Their material says:\n{cited}")

    mine = context.grounding.asked_by(archetype.name)
    if mine:
        asked = "\n".join(f"- {question}" for question in mine)
        parts.append(f"You have already asked — do not repeat these:\n{asked}")

    if finding is not None:
        parts.append(
            "This contradicts what their material says, and it is why you are "
            f"speaking now:\n{finding.summary}\n"
            "Put it to them directly, and cite what the material says."
        )

    parts.append(f"They just said:\n{context.said}")
    return "\n\n".join(parts)
