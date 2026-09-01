"""Who speaks, and what they say, from OpenAI's text models. #13.

**A measurement adapter first.** The architect approved adding OpenAI for the
panel model specifically — the redirect recorded on #13: Anthropic cannot take
this account's payment, so the comparison worth running is OpenAI against the
incumbent. This module exists so `scripts/panel_compare.py` can measure both
sides of that comparison against the same prompts; it is deliberately NOT
wired into `build_panel_model` yet, because whether the room switches vendors
is the architect's call and the numbers are what the call gets made on.

**The prompts are imported from the incumbent, never copied.** Every line the
model sees — the selection instruction, the roster annotations, the persona,
the composition prompt — is the measured text `gemini.py` sends, imported from
it directly. A paraphrase that behaved differently from the text actually sent
is exactly what a comparison must be unable to hide. If OpenAI ever becomes a
shipped provider, the prompt half of `gemini.py` moves to a `prompts.py` both
siblings import; until then the import direction records which vendor the
prompts were measured on.

**gpt-5 models reason by default, and a router must not.** The completion
budget is spent on reasoning first, so a two-token selection answer starved by
its own deliberation comes back empty. Both calls pin `reasoning_effort` to
minimal: selection because it has to answer while the presenter is still
mid-sentence, composition because a panelist's line is voice, not analysis,
and every second of thinking is a second of dead air in a live room.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.agents.archetypes import Archetype
from app.agents.model import ModelReply, TurnUsage
from app.agents.panel_models.gemini import (
    _SELECTION_INSTRUCTION,
    MODEL_TIMEOUT_SECS,
    _bare_name,
    _composition_prompt,
    _rephrasing_prompt,
    _persona_of,
    _selection_prompt,
)
from app.core.errors import ProviderUnavailable
from app.core.logging import get_logger

log = get_logger(__name__, tag="auditor")

PROVIDER = "openai"

COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

#: The latency-comparable tier. `gpt-5-mini` sits where the incumbent's
#: flash-lite does — the small fast member of the current family — and the
#: compare script can pass others.
DEFAULT_COMPOSITION_MODEL = "gpt-5-mini"

#: Generous where Gemini's caps are tight, because reasoning tokens bill into
#: the completion budget even at minimal effort, and a starved reply is an
#: empty string rather than a truncated one.
MAX_SELECTION_TOKENS = 256
MAX_LINE_TOKENS = 1024


class OpenAIPanelModel:
    """The same two calls the protocol names, against Chat Completions."""

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
        self, *, archetype: Archetype, context, finding=None, dispute=None, rephrasing=None
    ) -> ModelReply:
        return await self._generate(
            model=self._composition_model,
            system=_persona_of(archetype),
            prompt=(
                _rephrasing_prompt(rephrasing)
                if rephrasing is not None
                else _composition_prompt(context, finding, archetype, dispute)
            ),
            max_tokens=MAX_LINE_TOKENS,
        )

    async def select(self, *, candidates: Sequence[Archetype], context) -> ModelReply:
        answered = await self._generate(
            model=self._composition_model,
            system=_SELECTION_INSTRUCTION,
            prompt=_selection_prompt(candidates, context),
            max_tokens=MAX_SELECTION_TOKENS,
        )
        return ModelReply(text=_bare_name(answered.text), usage=answered.usage)

    async def _generate(
        self, *, model: str, system: str, prompt: str, max_tokens: int
    ) -> ModelReply:
        try:
            response = await self._http.post(
                COMPLETIONS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_completion_tokens": max_tokens,
                    "reasoning_effort": "minimal",
                },
                timeout=MODEL_TIMEOUT_SECS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Same discipline as the incumbent: the status goes to the log and
            # the client hears a vendorless 502 (CLAUDE.md).
            log.warning(
                "panel_model_refused",
                provider=PROVIDER,
                model=model,
                status=exc.response.status_code,
            )
            raise ProviderUnavailable(reason="panel_model_error") from exc
        except httpx.HTTPError as exc:
            log.warning("panel_model_unreachable", provider=PROVIDER, model=model)
            raise ProviderUnavailable(reason="panel_model_unreachable") from exc

        payload = response.json()
        return ModelReply(text=_text_of(payload), usage=_usage_of(payload))


def _text_of(payload: dict[str, Any]) -> str:
    """The line, out of the shape OpenAI returns it in."""
    choices = payload.get("choices") or []
    message = (choices[0].get("message", {}) if choices else {}) or {}
    return (message.get("content") or "").strip()


def _usage_of(payload: dict[str, Any]) -> TurnUsage:
    """What OpenAI says the call cost — read off their report, like Google's.

    Absent fields fall back to zero rather than raising, for the reason the
    incumbent gives: a missing count is a turn that reports slightly cheap,
    a raise is a live metered room ended over bookkeeping.
    """
    usage = payload.get("usage") or {}
    return TurnUsage(
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )
