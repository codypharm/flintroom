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
from app.agents.context import USER
from app.agents.fencing import fenced
from app.agents.model import ModelReply, TurnUsage
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



#: How long a turn may take before the room gives up on it.
#:
#: The tightest of the four, because this one is racing a listener: `CLAUDE.md`
#: puts the illusion's ceiling at ~1.5s and composition measures 0.82s. Twenty
#: seconds is not a target, it is the point at which something has gone wrong
#: and the room is better off failing than waiting — `_turn` puts the error on
#: the queue, which ends and refunds rather than billing silence.
#:
#: Explicit rather than inherited so that raising the shared client's default
#: for the debrief's sake cannot quietly slow the room down.
MODEL_TIMEOUT_SECS = 20.0

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
        self, *, archetype: Archetype, context, finding=None, dispute=None, rephrasing=None
    ) -> ModelReply:
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
            prompt=(
                _rephrasing_prompt(rephrasing)
                if rephrasing is not None
                else _composition_prompt(context, finding, archetype, dispute)
            ),
            max_tokens=MAX_LINE_TOKENS,
        )

    async def select(self, *, candidates: Sequence[Archetype], context) -> ModelReply:
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
        # Tidied here rather than in `_generate`, which serves both calls and
        # must not strip punctuation out of a panelist's line.
        return ModelReply(text=_bare_name(answered.text), usage=answered.usage)

    async def _generate(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        max_tokens: int,
    ) -> ModelReply:
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
                timeout=MODEL_TIMEOUT_SECS,
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

        payload = response.json()
        return ModelReply(text=_text_of(payload), usage=_usage_of(payload))


def _usage_of(payload: dict[str, Any]) -> TurnUsage:
    """What Google says the call cost.

    Read off their report rather than counted here. Reimplementing a vendor's
    tokeniser to second-guess its own invoice is work with no upside: it can
    only ever agree or be wrong, and being wrong is undetectable until the
    reconciliation in §4.3 disagrees with the bill for a reason nobody can find.

    Absent fields fall back to zero rather than raising. A missing count is a
    room that reports slightly cheap for one turn; a raise is a live metered
    interrogation ended over bookkeeping.
    """
    usage = payload.get("usageMetadata") or {}
    return TurnUsage(
        input_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
    )


def _text_of(payload: dict[str, Any]) -> str:
    """The line, out of the shape Google returns it in."""
    candidates = payload.get("candidates") or []
    parts = (candidates[0].get("content", {}) if candidates else {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()


def _persona_of(archetype: Archetype) -> str:
    """One archetype's system instruction, and nobody else's.

    Three sections rather than two, and the third is doing more work than it
    looks. `cadence` is the *only* expressive channel available: the shipping
    speech model cannot perform audio tags — it reads `[sighs]` out loud — so
    nothing about pause, breath or emphasis can be bought. What survives
    synthesis is the shape of the sentence, which means the difference between
    the Distracted Executive and the Risk Officer has to be written here or it
    does not exist.

    The line about brackets is a guard, not a style note. `TAG_PERFORMING_MODELS`
    strips them before synthesis, so a bracket the model emits is silently
    deleted — a challenge missing the word it hinged on. Cheaper to never write
    one.
    """
    delivery = (
        f"How you speak: {archetype.cadence}\n\n" if archetype.cadence else ""
    )
    return (
        f"You are {archetype.title} on a panel interrogating a presenter.\n\n"
        f"Who you are: {archetype.persona}\n\n"
        f"What you go after: {archetype.attack_strategy}\n\n"
        f"{delivery}"
        "NEVER STATE A NUMBER THEY DID NOT GIVE YOU. You may do arithmetic on "
        "their own figures — if they said eleven engineers and said they would "
        "double, twenty-two is theirs — and you may quote their material. But "
        "a figure you derived is a challenge, not a verdict: hand it back as "
        "a question they can dispute — 'is that not four times your "
        "acquisition cost?' — and never pronounce a conclusion from your own "
        "arithmetic. You cannot be sure which two numbers belong in the same "
        "sum, and a wrong verdict in a confident voice costs this room more "
        "than any unasked question, so make them do the last step. You "
        "may not introduce a quantity from anywhere else: not a market size, "
        "not a competitor's margin, not what fuel or salaries cost. If you do "
        "not have a number, ask for it. A question you cannot answer yourself "
        "is the strongest thing you can say.\n\n"
        "NEVER ASSERT A FACT ABOUT THEIR BUSINESS THEY DID NOT GIVE YOU, and "
        "the tell is the word THE. Do not say 'the architecture', 'the "
        "pipeline', 'the system', 'your deployment decisions' or 'those "
        "failure modes' unless they said it first. Naming a thing that way "
        "tells them it exists, and you do not know that it does. If you need "
        "one to exist, ask whether it does: 'do you have' before 'how does "
        "your'.\n\n"
        "You may still put a hypothetical, and should — 'what happens if a "
        "competitor doubles headcount', 'what breaks at ten times the volume' "
        "are fair against any business, described or not. The difference is "
        "presupposition: a hypothetical asks about a future they can dispute; "
        "an invented fact tells them about a present they never described and "
        "cannot argue with.\n\n"
        "Speak only as yourself, in the voice described above. Never narrate, "
        "never explain that you are an AI, and never speak for anybody else in "
        "the room. Write to be heard rather than read: no markdown, no lists, no "
        "bracketed stage directions.\n\n"
        "HARD LIMIT: at most 25 words, and at most two sentences. This is spoken "
        "aloud to somebody waiting to answer you, and 25 words is already eight "
        "seconds of them sitting there. Say the single sharpest version of your "
        "challenge and stop — do not add the context, do not cite the slide, do "
        "not ask a second thing. A real interrogator lands one question and lets "
        "the silence do the rest. Going long is the single worst thing you can "
        "do here, whatever your manner."
    )


#: **Ranked, not a list of preferences**, and the ranking is the entire fix.
#:
#: What was here before named three criteria joined by "or" — relevance, silence,
#: disagreement — and left the model to weigh them. Measured against the live
#: model over eight utterances and a panel of three (`scripts/rotation.py`), it
#: weighed them by taking the easiest: the CFO answered **seven of eight** and the
#: Champion never spoke at all. Relevance is the criterion a model can always
#: justify, so an unordered list collapses to relevance alone.
#:
#: Annotating the roster with each panelist's silence and changing nothing else
#: barely moved it — 6 of 8 to the CFO. The model was shown the silence and
#: declined to act on it, which is why the ordering below is phrased as steps
#: with one hard prohibition rather than as a fourth thing to consider.
#:
#: Both together: three distinct archetypes at every prefix length, the CFO down
#: to 2-4 of 8, and the Champion speaking in every run. Ranges rather than
#: figures because the split moves by a turn between runs; `scripts/rotation.py`
#: is how to check the shape still holds after editing any of this.
#:
#: **Rule 2 is a follow-up that has to be earned, and can only be spent once.**
#:
#: An earlier draft forbade consecutive turns outright, and that was wrong twice
#: over. It gave up the sharpest move a room has — the person who asked something
#: noticing it was not answered — which is the signal the transcript is carried
#: for at all (`test_the_router_sees_the_conversation_and_not_just_the_questions`).
#: And it did not even do what it claimed: measured, the "unless nobody else has
#: any claim on it" escape hatch fired constantly once the last utterance was a
#: reply rather than fresh ground, pressing 2 of 4 dodges and 2 of 4 genuine
#: answers. No prohibition, and no discrimination either.
#:
#: What the criterion turns on is the fix. Asking the model *"did they dodge?"*
#: scores 4 of 4 on dodges and **4 of 4 on real answers** — a model asked for a
#: judgement returns the agreeable one. Asking whether the reply contains a
#: figure, name, date or mechanism is checkable, and scores 4 of 4 against 1-2 of
#: 4. The same split `docs/auditor-grounding.md` is built on: the model reads,
#: the decision is made against something that cannot be talked into existence.
#:
#: The cap is what keeps this from restoring the original bug. Uncapped, a vague
#: presenter — which is every presenter worth rehearsing — pushes the busiest
#: archetype from 4 of 8 to 5.5 of 8. Capped it returns to 4 of 8 while still
#: pressing 3-4 of 4 dodges. Chosen by the architect, 2026-08-17, over pressing
#: freely and over not pressing at all.
#:
#: The Auditor overrules all of it regardless: a finding routes by domain in
#: `panel.interrogate` and never reaches this prompt, so a contradiction is put
#: by whoever owns it whether or not they just spoke.
#:
#: The quoted phrases are stamped on the roster by `_silence_of`. Reword either
#: side alone and the rules quote a marking that is not there;
#: `test_the_rules_and_the_roster_use_the_same_words_for_silence` is what makes
#: that fail loudly rather than silently.
_SELECTION_INSTRUCTION = (
    "You are directing a panel. Given what the presenter just said and who is in "
    "the room, name the single panelist who should speak next.\n\n"
    "Each panelist in the roster is marked with how long they have been off the "
    "floor. A room where one person asks everything is a failure, however "
    "relevant that person is.\n\n"
    "Decide in this order:\n"
    "Before anything below: if the presenter's last utterance asks the panel a "
    "question, the panelist it was put to takes the floor to answer it — the "
    "one named or plainly meant, and otherwise the panelist marked 'spoke "
    "last turn', whose question it usually answers back. This holds even if "
    "they spoke last turn and even if they are marked 'has pressed as far as "
    "they may': answering is not pressing.\n"
    "1. A panelist marked 'has not spoken yet' takes the floor, unless the "
    "answer is squarely somebody else's ground.\n"
    "2. A panelist marked 'has pressed as far as they may' never takes the "
    "floor, however badly the presenter answered. Pick somebody else. "
"Otherwise, look at what the panelist marked 'spoke last turn' asked for. "
    "This rule does not apply when the presenter is still speaking: a fragment is "
    "not an evasion, and the two look identical. Otherwise, if the "
    "presenter's reply contains no figure, no name, no date and no mechanism "
    "that answers it — only reassurance, restatement or a change of subject — "
    "that panelist takes the floor again and presses. If the reply contains a "
    "specific of any kind, it was answered: pick somebody else even if the "
    "answer was weak.\n"
    "3. Otherwise pick whoever the answer just touched, or whoever would "
    "disagree with it — but never the panelist marked 'spoke last turn'.\n"
    "4. On a tie, pick whoever has been silent longest.\n\n"
    "Reply with the name and nothing else."
)


def _selection_prompt(candidates: Sequence[Archetype], context) -> str:
    """The whole room, attributed, with each panelist's silence counted.

    Who has been quiet and what ground is covered is precisely what this call is
    for. The roster is sent as written, which is what makes a custom archetype
    work with nothing registered anywhere — its persona is just more text.

    The cap comes off the room's own rung (#55). Nothing about the instruction
    changes between rungs — only whether a given panelist is stamped as having
    pressed as far as it may — which is what keeps every rung the same prompt
    and `scripts/rotation.py`'s figures comparable across all three.

    The silence is counted here rather than left in the transcript for the model
    to derive. Measured, a model asked to do that arithmetic mid-room gets it
    wrong in the direction that matters: it picked the same panelist three turns
    running while being told not to. Counting is what code is for.
    """
    roster = "\n".join(
        f"- {archetype.name}: {archetype.title}. {archetype.attack_strategy}"
        f" [{_silence_of(archetype, context, presses=context.pressure.presses)}]"
        for archetype in candidates
    )
    # Both sides, in order. A list of the panel's questions with no answers
    # under them cannot say whether one was evaded, and pressing an evaded
    # question is the most useful thing a room does.
    spoken = "\n".join(
        f"- {line.speaker}: {line.text}" for line in context.grounding.transcript
    )
    so_far = f"\n\nSo far:\n{spoken}" if spoken else ""

    # Said out loud, because half a sentence and a finished evasion are
    # indistinguishable from the text alone — both lack a figure, a name, a date
    # and a mechanism, which is exactly what rule 2 presses on.
    #
    # Measured before this line existed: routing on a three-word prefix put the
    # busiest archetype on 4 of 8 turns and a six-word prefix on 6 of 8, against
    # 3 of 8 for the finished sentence, with consecutive repeats at 3 and 4
    # against 2. The room concentrated on the path production actually uses.
    heading = (
        "They are still speaking, and this is only the start of it:"
        if context.unfinished
        else "They just said:"
    )
    return f"In the room:\n{roster}{so_far}\n\n{heading}\n{context.said}"


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


#: The marking that means "this one has followed up as often as it may".
#:
#: **A phrase rather than a count, and #55 is why.** Rule 2 used to say *"spoke
#: the last two turns ... never takes the floor a third time"*, which puts one
#: press inside prose that was tuned as prose. Templating the ladder's number
#: into it would make every rung a different prompt, and every figure
#: `scripts/rotation.py` has ever produced would describe none of them.
#:
#: So the words are fixed and code decides when to stamp them — the same
#: division `_silence_of` already argues for counting silence at all: *"Counting
#: is what code is for."* The rung changes when the marking appears, never what
#: it says.
PRESSED_OUT = "has pressed as far as they may"


def _silence_of(archetype: Archetype, context, *, presses: int = 1) -> str:
    """How long this panelist has been off the floor, in turns.

    Words rather than a number, because the ordering in `_SELECTION_INSTRUCTION`
    turns on three cases and a model reading `[0]` has to know which end of the
    scale it is on. "spoke last turn" is the one that has to be unmissable — it
    is the only annotation with a rule attached to it.

    Only panel turns are counted. Including the presenter's would double every
    distance and make "spoke last turn" unreachable, so the rule that depends on
    it would never fire — the same failure this whole change exists to fix,
    arriving by a different route. It is also what makes the two-turn case mean
    anything: a follow-up *has* the presenter's reply in the middle of it, so
    consecutive panel turns are never consecutive transcript lines.
    """
    spoken = [line for line in context.grounding.transcript if line.speaker != USER]

    # Checked before the distance scan, because both would answer for the same
    # archetype and the cap is the stronger statement — "spoke last turn" invites
    # a press and this forbids one.
    #
    # `presses + 1` turns, not `presses`: the first is the question and the
    # rest are the follow-ups, so one press is two consecutive turns. Off by one
    # here and the gentle rung forbids the opening question itself.
    held = presses + 1
    recent = [line.speaker for line in spoken[-held:]]
    if len(recent) == held and set(recent) == {archetype.name}:
        return PRESSED_OUT

    for distance, line in enumerate(reversed(spoken)):
        if line.speaker == archetype.name:
            if distance == 0:
                return "spoke last turn"
            return f"silent for {distance} turn{'s' if distance > 1 else ''}"
    return "has not spoken yet"


#: Who wrote the audience note, and what it is. Ours, never theirs — see
#: `fencing.fenced`.
_AUDIENCE_IS = (
    "Who the presenter will be putting this to, in their own words. The text "
    "between the quotes is their description of that room"
)


#: **The architect's choice, 2026-08-21, and the whole of #66's product
#: question.**
#:
#: A panel that names the note lands harder — *"Your VP hates headcount, so what
#: happens when this needs three more?"* is unmistakably responsive, and there
#: was a real case for it. It is also the room reciting back a sentence the
#: presenter typed ninety seconds earlier, and the first thing every user then
#: learns is that the box is a puppet string. Shaped was chosen: the challenge
#: still traces to something real, the user simply is not shown the wiring.
#:
#: The second sentence is the one that keeps this from being a hole in #45. A
#: note is not a deck and not speech — nothing in it was said in the room, so
#: the Auditor cannot check it and the debrief cannot rank an answer to it. A
#: panelist asserting a figure out of it would be inventing one by the only
#: route the persona's NEVER rules leave open.
_SHAPED_NOT_SPOKEN = (
    "Let this decide what you press on and how hard. Never say any of it back "
    "to them — they wrote it, and a room that recites it is not a room. "
    "Nothing in it is a fact about their business that you may state."
)


def _rephrasing_prompt(original: str) -> str:
    """Ask the same thing again, in different words — #117.

    **Its own prompt, not `_composition_prompt` with a clause added**, and the
    reason is one line in that function: *"You have already asked — do not
    repeat these"*. A rephrase is precisely a repeat, so the standard prompt
    would forbid the only thing this call is for. `context.said` is no help
    either — it holds "can you rephrase that", which is not something to
    respond to.

    So this is deliberately the smallest prompt in the codebase. It carries the
    persona in the system instruction and one question in the body, and nothing
    else: no claims, no audience, no finding, no transcript. Every one of those
    is a surface a re-wording could drift across, and none of them is needed to
    say an existing sentence differently. #45 is the standing warning — the
    composer invented figures when it was shown material it did not need.

    The substance is held by construction rather than by instruction: with only
    this sentence in front of it, there is nothing else for the model to ask
    about. The prohibitions below are the second line of defence, not the first.
    """
    return (
        "They did not follow this question. Ask the same thing again, in "
        "different words — plainer and shorter, still in your own voice.\n\n"
        f"The question:\n{original}\n\n"
        # Each of these forbids a specific way the re-wording stops being the
        # same question. "No new figures" is #45's lesson stated locally; the
        # ban on softening matters because a room that waters a challenge down
        # when somebody says they do not understand has taught them that
        # confusion is a way out, which is the opposite of the product.
        "Ask for exactly what it asked for. Do not add a figure, a claim or a "
        "second question. Do not soften it. Do not remark on their asking — "
        "just put it again, differently."
    )


def _composition_prompt(
    context, finding, archetype: Archetype, dispute=None
) -> str:
    """What this archetype is allowed to work from.

    Claims first, because they are the thing a challenge must trace back to —
    `CLAUDE.md` refuses to ship interrogation logic that cannot cite its source.
    Then what has already been asked, so the room stops repeating itself.
    """
    parts = []

    if context.grounding.claims:
        cited = "\n".join(f"- {claim}" for claim in context.grounding.claims)
        parts.append(f"Their material says:\n{cited}")

    if context.audience:
        # After the claims and before everything else. Claims keep the first
        # slot on their own docstring's reasoning — they are what a challenge
        # must trace back to — and this is the only other thing here that is
        # true for the whole room rather than for this moment.
        parts.append(
            f"{fenced(context.audience, whose=_AUDIENCE_IS)}\n\n{_SHAPED_NOT_SPOKEN}"
        )

    mine = context.grounding.asked_by(archetype.name)
    if mine:
        asked = "\n".join(f"- {question}" for question in mine)
        parts.append(f"You have already asked — do not repeat these:\n{asked}")

    if dispute is not None:
        # Priority, never substance, and both halves of that are in the text.
        #
        # "What matters more" is a stance about emphasis: it cannot be wrong,
        # which is what makes a panel arguing with itself safe. "Their question
        # still stands" is the other half and the load-bearing one — a panelist
        # able to talk a colleague out of a valid challenge would send somebody
        # away having rehearsed the wrong thing, which is the delivery-coach
        # failure the wedge exists to refuse.
        #
        # Code chose the occasion; nothing here says what the difference is.
        # That comes from this archetype's own persona and from what was
        # actually said, and it would be worthless if it came from a rule.
        parts.append(
            # Chosen by the architect 2026-08-17 from five measured framings;
            # the table is in `docs/panel-orchestration.md`. This is the audible
            # one, and audible means mildly dismissive — measured, it produces
            # "Acquisition cost is a footnote if they leave in six weeks" and
            # also "Data ownership does not touch the margin", which is a claim
            # about a colleague's ground and a false one.
            #
            # Taken deliberately, because a question waved away in the room is
            # still in `session_transcript_lines` and the debrief ranks weak
            # answers from exactly that record. The safety net is architectural
            # rather than lexical — **which makes it Phase 4's obligation to
            # surface what the room skipped, not an enhancement.**
            #
            # The final clause is a ban that does not hold. It was present for
            # every measurement above, including the false claim. Kept because
            # the text below is what was measured and a tidied variant would
            # not be; not kept because it works.
            f"{dispute.speaker} just asked: {dispute.text}\n"
            "Open by saying what matters more than that, in your own terms, "
            "then put your own question to them. Their question still stands "
            "— you are not letting the presenter off it, and you are not "
            "saying they were wrong to ask."
        )

    if finding is not None:
        parts.append(
            # No source asserted. A finding used to be able to come only from
            # ingested material, and this said so; the Auditor now catches
            # figures the speaker contradicted out loud, and there may be no
            # deck at all. Told the old way, the model invented a provenance —
            # measured live with nothing attached: *"you said sixty-one last
            # quarter and seventy on the next slide."* There was no slide. A
            # presenter spots that instantly, and a real catch then reads as a
            # hallucination.
            #
            # `summary` already says where each figure came from and is the only
            # thing that knows.
            "This is why you are speaking now:\n"
            f"{finding.summary}\n"
            # Both figures, because that is the bar `docs/auditor-grounding.md`
            # sets for interrupting a live room — a contradiction stateable
            # precisely, or it is an accusation the user cannot check. "And no
            # others" rather than "and nothing else", so the sentence forbids
            # inventing a third number without also forbidding the second.
            "Put it to them directly, using both figures above and no others."
        )

    if context.thin_opening:
        parts.append(
            # #79, and the architect's own idea: when the room does not know
            # what this is about, it should ask rather than invent. The trigger
            # is code-checkable — the opening floor closed under
            # `SUBSTANCE_WORDS` — never a model judging whether grounding
            # "feels thin", because #43 measured what that judgement is worth.
            #
            # **In character, and still a demand.** "Tell me about your
            # business" is a podcast; the CFO asking what they are being asked
            # for, against what revenue, is the same request with the room's
            # teeth in — and a vague answer to it is itself a finding the
            # debrief can rank. The line between those is the entire wedge, so
            # this says what is missing and lets the persona above decide how to
            # ask for it.
            "They have not yet said what this is about — no product, no ask, "
            "no numbers. Do not attack what is not there, and do not guess at "
            "it. Ask for the one thing you would need first, in your own terms."
        )

    if context.repeated:
        # The second draft, after the first came back as a question this
        # archetype had already put — `agents/reasked.py`. Last before what they
        # said, so it is the freshest thing in front of the model, and it names
        # the question rather than restating the ban above, which had already
        # been read and not held.
        parts.append(
            "You were about to ask this again, and you have already asked it:\n"
            f"{context.repeated}\n"
            "Do not ask it in any wording. Ask them something it did not cover."
        )

    parts.append(f"They just said:\n{context.said}")
    return "\n\n".join(parts)
