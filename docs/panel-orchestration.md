# Panel Orchestration

**Status:** decided 2026-08-16 via `grill-me`. Builds in Phase 3 (Weeks 5–6) per
`Product.md` §7. Nothing here is built yet.

Resolves how a panel of archetypes actually holds a conversation. `Product.md`
§3.3 specifies it in five bullets — turn-taking, inter-panelist disagreement,
grounded challenges, targeted interruption, difficulty calibration — and this is
what those turned into once the questions were asked.

> **Scope.** What the Auditor *finds* is `docs/auditor-grounding.md` and is not
> redefined here. This document is about who speaks, when, and in whose voice.

---

## Problem

Today one ElevenLabs agent owns the whole conversation: their speech recognition,
their model, their turn-taking, one voice, one persona. The relay forwards the
user's audio and plays back whatever comes out (`voice/relay.py`).

A panel of four archetypes that interrupt each other cannot come out of that. One
agent is one voice. So Phase 3 is not a feature added to the voice loop — it is a
second implementation of the seam the voice loop already has.

The stakes are Open Risk #3: above roughly 1.5 seconds the illusion breaks and
the room stops feeling real, which is the entire experience the product sells.

---

## Decisions

### We own the conversation loop

An `OrchestratedProvider` implementing the existing `VoiceChannel` protocol:
speech in, our graph decides who speaks and why, speech out in that archetype's
voice.

`voice/provider.py` is already a structural `Protocol` — *"an adapter is a class
that happens to fit rather than one that had to import us"* — so this is a
sibling of `providers/elevenlabs.py` rather than a rewrite. The relay, the ticket
flow, the metering seams and the client protocol are all unchanged.

Two alternatives were considered and rejected:

- **One agent per archetype, gated.** Four provider sockets, user audio fanned
  out, we choose whose output reaches the phone. Keeps native barge-in and
  distinct voices for free. Rejected on two unknowns that both had to go our way:
  whether four concurrent agent sessions bill as four — which would put a room at
  roughly 4× the assumed $0.12/min and break every margin in §4.4 — and whether
  agents that cannot hear each other can disagree convincingly.
- **One agent, persona swapped per turn.** Cheapest, and everything already built
  keeps working. Rejected because the whole panel then speaks in one voice, and
  `CLAUDE.md` chose ElevenLabs for *"native barge-in and distinct per-archetype
  voice identity — not TTS alone."* Taking this would mean reopening that.

**What we give up:** the vendor's native barge-in and endpointing. We build
those, and they are the reason Open Risk #3 belongs to this phase.

### A text model writes the words; ElevenLabs speaks them

The model never produces audio. It produces a sentence, and ElevenLabs renders
that sentence in the archetype's voice.

The alternative was an audio-native model — Gemini Live, GPT-realtime — which
hears and speaks directly and collapses two hops into one. That is the better
latency story by a distance, and it was rejected anyway: the voices become the
vendor's, so *"distinct per-archetype voice identity"* reduces to whatever their
voice list offers. Gemini Live remains what `CLAUDE.md` says it is — the fallback
for the *voice* role, which is a different job from writing a panelist's line.

### Two steps per turn: pick the speaker, then write in their voice alone

1. **Selection.** A cheap call scores which archetype most wants in — whose
   domain the last answer touched, who has been quiet, whose thesis was just
   contradicted.
2. **Generation.** A second call writes that line with **only that archetype's**
   persona and grounding in context.

The alternative — one call that sees every persona and returns both speaker and
line — is one hop instead of two and gets inter-panelist disagreement for free,
since the model is writing both sides. It was rejected on voice homogenisation: a
single prompt holding four personas tends to average them into one voice wearing
four labels, and that failure is invisible from the inside. It reads fine in a
transcript and feels flat in a room, which is precisely §3.3's
*"synthetic within two minutes."*

**So disagreement has to come from the routing step instead.** An archetype whose
thesis conflicts with what the last panelist just said scores high and takes the
floor. Disagreement is a property of who gets picked, not of one author writing
both parts.

**Targeted interruption is not this mechanism.** When the Auditor flags a numeric
contradiction, routing is already decided: `docs/auditor-grounding.md` has each
derivation pack declare the archetype domain that owns each figure. The selection
step is what happens when the Auditor is silent, which is most of the time —
qualitative findings wait for the debrief.

### The panel model sits behind an interface, Claude first

A `PanelModel` Protocol with a `PANEL_PROVIDER` setting, exactly as
`ingestion/extraction_models/` already does for extraction.

Claude goes in first **only** because the key, the adapter shape and the
retry-and-classify handling already exist — it has not won anything. Gemini goes
in as the second implementation specifically so the two can be measured against
each other.

That comparison is not optional housekeeping. **The panel model runs on every
turn of a metered session**, so its price lands directly inside the §4.4 margins
that Open Risk #4 already says rest on an unverified $0.12/min.

Starting points, pinned rather than aliased — Google explicitly recommends
pinning stable versions, and `extraction_model: str = "claude-sonnet-5"` is
already the precedent:

| Step | Claude | Gemini |
| --- | --- | --- |
| Selection | `claude-haiku-4-5-20251001` | `gemini-3.5-flash-lite` |
| Generation | `claude-sonnet-5` | `gemini-3.7-flash` |

`claude-opus-5` is the upgrade path if Sonnet's interrogation reads flat. It is
not the starting point: it is the most expensive thing on a per-turn path inside
a room the user is paying for by the minute.

**No preview models on a metered path.** `gemini-3.1-pro-preview` is the most
capable thing Google lists and it is preview — a paid room is the wrong place for
a model that can change or be withdrawn.

---

## What is buildable without a key

Neither `ANTHROPIC_API_KEY` nor `ELEVENLABS_API_KEY` is currently configured, and
almost none of this needs them:

- The `PanelModel` interface and the Claude adapter. `test_claude_extraction.py`
  drives 55 tests through a recorded `httpx` handler without touching the
  network, and the same shape applies here — prompt assembly, response parsing
  and failure classification are all testable offline.
- Archetype configuration, which is data.
- The selection step's scoring, against a fake model.
- The orchestration graph's shape and its state transitions.

**The latency spike needs both keys** and cannot be faked. It is the one number
every remaining question is downstream of, and it is the reason task #9 existed
for the voice loop.

---

## Open

- **Speech recognition is undecided.** ElevenLabs Scribe keeps it to one vendor
  and one key; Deepgram is the low-latency standard. It is a hop in the 1.5s
  budget, so it should be decided by measurement rather than by preference.
- **Barge-in is ours now.** The vendor's native handling was the reason
  ElevenLabs was chosen, and owning the loop gives it back to us. Voice-activity
  detection, endpointing, and discarding buffered playback on interrupt are all
  unbuilt. `ClientChannel.discard_playback` already exists, which is the easy
  half.
- **Difficulty calibration across sessions** (§3.3) has no design. It needs
  something durable per user, and `docs/minutes-ledger-and-sessions.md` has no
  opinion on where that lives.
- **The two-call design does not fit the budget, measured.** This is the open
  item now, and it is load-bearing rather than a tuning question — see below.


---

## Measured, 2026-08-16

`scripts/panel_spike.py`, real Gemini, three turns against a scripted presenter
with a deck that contradicts them.

| | |
| --- | --- |
| Selection (`gemini-3.5-flash-lite`) | ~0.8s |
| Composition (`gemini-3.5-flash-lite`) | ~0.8s |
| **Both, per turn** | **1.49s – 2.37s, mean 1.90s** |
| Budget (Open Risk #3) | 1.5s **for the whole chain** |

Transcription and speech are not in that number. They are unbuilt and unchosen,
so the real chain is this plus two hops.

### Three things the spike found that argument had not

**The cheap model wins twice.** The design said a cheap model routes and a
stronger one writes, on the reasoning that interrogation is the product. Measured,
`gemini-3.7-flash` took 2.11s and spent 383 tokens thinking; `gemini-3.5-flash-lite`
took 0.82s and wrote the better line:

> *"Slide four says sixty-one. You just said seventy. Which one is lying to me?"*

against

> *"Slide four says sixty-one percent in 2026, but you just told us seventy
> today—where did those nine hundred basis points come from?"*

A panelist says one short thing. A reasoning model produces a considered
paragraph, which is worse as well as slower. Both calls now use the fast model.

**A reasoning model cannot be talked out of reasoning.**
`thinkingConfig: {thinkingBudget: 0}` is a 400 on flash-lite and is accepted then
ignored on 3.7-flash — the response still carried a `thoughtSignature` and still
spent the tokens. Worse, those tokens come out of `maxOutputTokens`, so a tight
ceiling returns `"Slide"` or an empty string with `finishReason: MAX_TOKENS` and
the room says nothing. The answer was to choose a model that does not reason.

**Streaming does not rescue the number.** A panelist's line is ~25 tokens, so the
first streamed chunk and the last arrive together (1.09s / 1.09s). There is no
time-to-first-audio advantage to hide the second call behind.

### Corrected: a fast model routes, keywords are the fallback

Moving selection into code was right about the number and wrong about the
constraint, twice.

**Keyword routing cannot see a custom archetype.** A persona a Pro user writes
this morning has no entry in any vocabulary table, so it could never be chosen
for relevance — only by having been quiet. §4.4 sells custom archetypes; routing
that ignores them is not routing.

**And it barely works for the shipped ones.** Measured against fifteen sentences
of the kind a presenter actually says, matching canonical domain names routed
**7%**. A hand-written synonym table lifted that to 53% on the default panel and
80% on the full library — real, and still a table somebody has to maintain,
against a model that measured warm at **0.78–0.91s** and routed every case
correctly including the two the table misses.

**The 0.8s objection dissolves.** It only bit because routing was assumed to run
*after* the user stops speaking. It does not have to: we own the loop, so a
partial transcript is available while they are still talking, and routing needs
the gist rather than the final word.

```
user still speaking ──────────────┐
   partial transcript ──► ROUTE ──┘   ~0.8s, hidden
user stops ──► final transcript ──► COMPOSE ──► speech
```

Composition stays the only serial hop, at ~0.85s warm.

**Keyword routing survives as the fallback**, which is a better job for it. When
selection is late, fails, or names nobody, the room picks somebody instantly. A
slow model then costs relevance rather than silence — and in a live metered room
a pause with nobody in it is the failure a user notices first.

That also takes the vocabulary table off the critical path: an incomplete entry
is a slightly worse fallback rather than a broken feature.

### The measurement that prompted all of it, 2026-08-16

Option 1 taken. `agents/routing.py` picks the speaker from two signals already in
the data — how many of an archetype's declared domains the answer used, and how
long since they last spoke — and the model call for selection is gone.

Re-measured, same script:

| | Before | After |
| --- | --- | --- |
| Mean per turn | 1.90s | **1.48s** |
| Warm turns | — | **0.85s – 1.23s** |
| First turn | — | 2.36s (TLS and DNS on a cold client, paid once per process) |

The rotation works. Turn two went to the Technical Skeptic because the CFO had
just spoken; turn three came back to the CFO on the margin contradiction. No
model was asked.

**What was given up** is comprehension. A model would route an answer that is
entirely about margin without ever using the word; this will not. The weights are
guesses encoding an ordering rather than a measurement — relevance beats
rotation, but three turns of silence outweigh one glancing keyword. They are the
thing to tune when a transcript reads wrong.

**Still open on latency:** transcription and speech are unbuilt, so ~0.85s warm
is a floor and not the answer. And one line came back as a rambling paragraph
despite the prompt asking for one thing, which is a prompt problem rather than a
latency one.

### The original argument, kept because it is why the shape changed

Grounding works — the room caught a contradiction with no Auditor involved, from
the deck alone. What does not work is two serial model calls inside 1.5s.

Four ways out, none free:

1. **Deterministic selection.** Route in code — domain match against the last
   answer, who has been quiet, whose thesis was contradicted — and spend zero on
   the hop that buys the least. Saves the whole 0.8s and leaves composition at
   ~0.8s. Costs comprehension: keyword-shaped routing where a model understood
   the answer. `_owner` already routes findings this way, so it is a widening of
   something that exists rather than a new idea.
2. **One call plays the whole room**, the alternative rejected above. ~0.8s and
   inter-panelist disagreement comes free. Costs the voice separation the two-step
   design exists for, which was rejected on a risk that is real but unmeasured —
   and is now the cheaper of two evils rather than the more expensive.
3. **Speculative composition.** Start writing for the most likely archetype while
   selection runs, discard when wrong. Hides the latency, pays roughly double on
   the turns it guesses wrong, and doubles the complexity of the loop.
4. **Move the threshold.** 1.5s is `Product.md`'s number and it is itself an
   assumption. Worth saying out loud rather than treating as physics — but it is
   the one number in this area with a product argument behind it, and moving it
   because the implementation is slow is the wrong direction of travel.

This is an architecture decision and it is not the agent's to make.
