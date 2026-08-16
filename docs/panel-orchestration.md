# Panel Orchestration

**Status:** decided 2026-08-16 via `grill-me`; built through 2026-08-16, except
speech recognition. Phase 3 (Weeks 5–6) per `Product.md` §7.

The panel, routing, orchestration, barge-in, synthesis and casting all exist and
are measured against live providers. **A transcriber is the one remaining vendor
and the one remaining seam** — see *Open*. Everything below the Decisions section
records what building it changed, and several decisions were revised by
measurement rather than held.

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

- **Speech recognition is undecided**, and is now the *only* undecided vendor in
  the chain. ElevenLabs Scribe keeps it to one vendor and one key; Deepgram is the
  low-latency standard. Decide it by measurement rather than preference — and
  weigh one requirement above latency: **it must emit interim results.** The whole
  plan for holding 1.5s is running the ~0.8s selection hop against a partial
  transcript while the user is still speaking. A transcriber that speaks only at
  the end of an utterance makes that overlap impossible, and the room is over
  budget by construction however fast the vendor itself is.
- **Barge-in is ours now, and built** — see *Owning the loop*, below. What is
  still outstanding is endpointing, which belongs to whichever transcriber is
  chosen rather than to us.
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

---

## Owning the loop, 2026-08-16

`OrchestratedProvider` and `OrchestratedChannel` satisfy the same `VoiceChannel`
contract as the vendor adapter while running the conversation themselves —
transcribe, select, compose, speak. Nothing in `relay.py` changed, so metering,
idle detection and settlement all work unmodified against it.

Two properties are worth stating because both were arrived at by being wrong
first.

**The channel listens while it speaks.** The first version read a transcription
result, answered it, then read the next — a room that cannot be interrupted,
because while a panelist speaks nothing is listening. A listener task now reads
transcription continuously and a turn runs beside it. Cancelling the turn is what
stops a panelist mid-word, which is why `Speaker.speak` is an iterator rather
than a method returning bytes: dropping the iteration drops the utterance, and
nothing needs a cancel call that could leave an adapter half-spoken. A **partial**
takes the floor away, not a final — waiting for the final means waiting for the
user to finish their sentence before conceding it.

**The user's words are recorded outside the cancellable part.** A second finished
utterance abandons the turn in flight, correctly: the room should answer the
latest thing said rather than queue a challenge to a sentence the user has moved
on from. But recording their line *inside* that task meant our choice not to
reply erased what they said, and the next selection judged the conversation
missing an answer it had been given.

### Speech, measured against the live account

| | |
| --- | --- |
| First frame, warm (`eleven_flash_v2_5`) | **0.38s**, steady across six of eight |
| First frame, cold connection | 2.59s, 1.13s |
| First frame (`eleven_v3`) | 0.76s |
| Format | `pcm_16000` — S16LE 16 kHz mono, no transcode anywhere |

Which closes the budget arithmetic that had been an estimate since the spike:

| | Interrogate | Speech | Overlap | First audio |
| --- | --- | --- | --- | --- |
| Flash v2.5 | 1.80s | 0.38s | −0.80s | **1.38s** ✓ |
| v3 | 1.80s | 0.76s | −0.80s | 1.76s ✗ |

The selection overlap is no longer a hypothesis with one end measured. Both ends
are now measured, and it works out — which also makes the transcriber's interim
results a hard requirement rather than a preference.

### Deferred: v3 for genuine expressiveness

**Decided, not merely unbuilt.** The human wants the room expressive; the cost is
not payable yet. Recorded here as well as in the task list because a task list is
not a repository.

Audio tags — `[sighs]`, `[laughs]`, `[sarcastic]` — are the difference between a
panel that reads and a panel that performs. Flash v2.5 does not support them, and
does **not** ignore them either: measured, it speaks them aloud. A tagged take ran
5.7s against 3.6s for identical words, and the extra two seconds is the model
saying "sighs" out loud. Documentation would not have caught this — the prompting
guide calls tags "an Eleven v3 feature", the model page names v3 *Conversational*
as the only model supporting them, and neither says what Flash does on receiving
one. Only listening found it.

`speakers/elevenlabs.TAG_PERFORMING_MODELS` strips tags for any model not known
to perform them, and the composer prompt forbids brackets outright, since a
stripped tag leaves a challenge missing the word it hinged on.

**What we do instead, and it is most of the way there.** `Archetype.cadence`
describes how a panelist's words land — sentence length, where the full stops
fall, whether they open with a beat. It is the only expressive channel synthesis
leaves us, and it is free. Measured on one utterance against live Gemini, the
same four archetypes produced four structurally identical compound questions
without it, and with it:

> **Distracted Executive** — *"Replatform? Six months? What is the ask, and what
> happens if we do nothing?"*
>
> **CFO** — *"Replatforming takes four quarters minimum. Where is the downtime
> budget in your model?"*

It also overshot, which is worth recording: with cadence and no ceiling the
Internal Blocker produced 85 words — **27.9 seconds** of measured speech. A
monologue in a room whose premise is that the user answers back, costing three
ways at once: they wait half a minute for a turn, it consumes a third of the
90-second idle window that only *user* speech resets, and synthesis bills per
character. The prompt now bounds a turn at thirty words and two sentences
however unhurried the manner, which took that line to 10.7s with the archetype
still unmistakably itself.

**Reopen when any of:**

1. The ElevenLabs plan is upgraded and `eleven_v3_conversational` — built for
   real time at ~280ms, currently `model_access_denied` — measures near spec. It
   is the only option that takes both sides of the trade.
2. Real users report the room feels flat or synthetic *despite* the cadence work.
   Open Risk #1 is whether people tolerate being attacked at all, and a flat
   reading is less confronting than a performed one.
3. §4.3 cost instrumentation shows margin headroom for a pricier synthesis tier.
   v3 costs more per character, and every tier margin still rests on an
   unverified $0.12/min assumption.

**When reopened:** add the model to `TAG_PERFORMING_MODELS` — the strip guard is
already model-aware — and teach the composer prompt to emit tags, which it is
currently instructed never to do.

### Casting

Eight voices, four and four by gender, three accents. Stored as characters in
`agents/voices.py` — `measured`, `brisk` — never vendor identifiers.
`ELEVENLABS_VOICES` in the adapter is the only place in the codebase that knows
an ElevenLabs voice id.

That indirection exists for the feature that does not exist yet. Shipped
archetypes are config in one file, so a vendor swap there is a find-and-replace;
a Pro user's custom archetype is a row **they** own, and a vendor id in one turns
that swap into a migration over customer content. The cheap moment to avoid it
was before any row existed.

Custom archetypes get a voice **auto-assigned** — first unused in the seated room
— with an optional override from the same eight. Decided rather than defaulted:
most users writing a custom archetype care about the argument it makes, not its
timbre, and making them cast it is a decision tax on the feature's main path. The
uniqueness constraint is **per-room, not per-library**: two custom archetypes may
share a voice safely if never seated together, so the check belongs in
`assemble()` beside the tier cap.
