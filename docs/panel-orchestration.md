# Panel Orchestration

**Status:** decided 2026-08-16 via `grill-me`; built through 2026-08-16. Phase 3
(Weeks 5–6) per `Product.md` §7.

The panel, routing, orchestration, barge-in, synthesis, casting and transcription
all exist, and **a live socket now opens a room we run ourselves** — ElevenLabs
Agents is deleted. Every seam has an adapter, no vendor is undecided, and the
whole chain is tested from the socket down.

What is left is not code. The room has never run against a real device, and the
latency budget does not close: ~2.1s against the 1.5s threshold at which
`CLAUDE.md` says the illusion breaks. Everything below the Decisions section
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

*As of the start of Phase 3:* one ElevenLabs agent owned the whole conversation —
their speech recognition, their model, their turn-taking, one voice, one persona.
The relay forwarded the user's audio and played back whatever came out
(`voice/relay.py`). That adapter is now deleted; see the final section.

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
that happens to fit rather than one that had to import us"* — so this was a
sibling of the vendor adapter rather than a rewrite. The relay, the ticket
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

- ~~**Speech recognition is undecided**~~ — **settled: ElevenLabs Scribe v2
  Realtime.** See *Hearing the room*, below. No vendor in the chain is undecided
  now.
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

---

## Hearing the room, 2026-08-16

The last undecided vendor, settled: **ElevenLabs Scribe v2 Realtime**, in
`app/modules/voice/transcribers/elevenlabs.py`.

### Why, on numbers rather than on already holding the key

| | partial latency | price | audio in | billed on |
| --- | --- | --- | --- | --- |
| **Scribe v2 Realtime** | ~150ms | **$0.39/hr** | `pcm_16000` native | audio |
| Deepgram Nova-3 | ~300ms | $0.46/hr | linear16 16k | audio |
| AssemblyAI Universal-Streaming | — | — | PCM16 | **socket-open time** |

AssemblyAI was ruled out on billing shape, not on quality. It charges for how
long the connection stays open rather than for audio sent, and a hostile Q&A is
mostly silence — somebody working out how to defend a number is not speaking,
and we hold the socket through all of it. We would have paid for thinking time,
on the one product whose entire premise is making people think.

Scribe being both cheaper *and* faster than the low-latency standard is the part
worth not glossing over: the vendor we already had also won on the merits, so the
convenient answer and the correct one happened to agree. `pcm_16000` native
matters more than the price gap — it is byte-for-byte what the phone records and
what the panel answers in, so nothing on either leg transcodes.

**The cost of the choice, recorded before it is discovered during an outage:**
the room now rents its ears and its mouth from one company. A single ElevenLabs
incident takes transcription and speech together, and there is no partial
degradation to fall back to. The `Transcriber` and `Speaker` seams are what keep
that recoverable — Deepgram is a sibling file and a branch in
`build_transcriber`, not a rewrite — but they are insurance, not mitigation.

### `commit_strategy=vad` is the load-bearing parameter

Their default is `manual`, under which *we* decide where an utterance ends. That
would mean writing voice-activity detection in Python, over a network hop, for a
hands-free room where the user is not touching the phone and has no way to tell
us they have finished. VAD hands that back to the engine already listening to
the audio.

### The budget has a term in it that the 1.38s measurement did not include

`vad_silence_threshold_secs` is how long the user must be quiet before the
engine calls their turn over. **It sits directly inside perceived latency.** The
1.38s figure measured above starts at the final transcript; a person in the room
experiences the gap from the moment they stop talking, which is this threshold
*plus* that.

Their SDK defaults to **1.5s**, which would put the room near **2.9s** — roughly
twice the ~1.5s at which `CLAUDE.md` says the illusion breaks. The adapter ships
**0.7s** instead.

That 0.7 is a starting point, not a measurement, and it is a genuine trade rather
than a number to minimise: too low and the panel talks over somebody drawing
breath mid-answer, which is worse than a pause — a room that interrupts you
cannot be argued with. **Re-measuring the budget end to end, with this term in
it, is now part of the §4.3 spike** and needs the API key permission below.

### Both open questions, settled against live audio

Once the key permission was ticked, a synthesised line was fed back through the
realtime socket at realtime pace. Both guesses above turned out to be safe, and
one measurement changed what the budget looks like.

```
threshold 0.7s  ->  committed_transcript at +0.77s after the audio stopped
threshold 0.4s  ->  complete partial      at +0.35s
                    committed_transcript  at +0.65s
```

- **Only `committed_transcript` arrives under VAD.** `final_transcript` never
  appeared. The dedupe guard is therefore insurance against a path we have not
  exercised rather than a live correction — kept, because it is four lines and
  the failure it prevents costs two metered turns, but no longer load-bearing.
- **The VAD term is real and roughly tracks the threshold**, with ~0.1–0.25s of
  engine overhead on top. It is not fixed cost that tuning cannot touch.
- **The last partial before the commit can already hold the complete utterance.**
  At 0.4s the full, correctly punctuated sentence arrived 0.30s *before* the
  commit did. That is a lever worth taking seriously: composition currently waits
  for the commit, and this says it need not always. Measured once, at one
  threshold, on synthetic speech — so it is a lead, not a result.

**What synthetic speech cannot tell us:** TTS has no natural mid-sentence pauses,
so none of this exercises the risk that actually bounds the threshold from below
— a panelist cutting off somebody drawing breath. That needs a person.

### The two questions as they stood before the key worked

- **`final_transcript` vs `committed_transcript`.** Both are documented; which
  one VAD emits is not stated anywhere. The adapter accepts **both**, because
  recognising only the wrong one produces a room that hears every word and never
  answers — a failure that looks like a broken model rather than a missed message
  type. If both arrive for one utterance the panel would interrogate the same
  sentence twice: two model calls, two syntheses, two metered turns. So
  `ElevenLabsTranscriptionStream.results` drops a final that repeats the one
  before it. Only the immediately preceding one, so a user who says "no" twice in
  separate segments is heard both times.
- **Which errors are fatal.** Fifteen error message types, and they are not the
  same kind of bad. `insufficient_audio_activity` is the dangerous one: silence
  is ordinary here, and a transcriber reporting quiet must never be able to end a
  metered session over it — that is the idle timeout's job, on a clock the
  session owns. `FATAL_ERRORS` is therefore an explicit allow-list of the seven
  that genuinely end a room, and everything else is survived.

Both are guesses made safe rather than guesses avoided, and both are cheap to
correct once a live key can confirm them.

### Open

- **The budget does not close, and this is the live risk.** ~0.7s of VAD on top
  of the 1.38s measured earlier is ~2.1s against a 1.5s threshold. Three levers
  exist and none has been tried: lower the threshold, start composition on a
  complete partial instead of the commit, or shorten the lines further. This is
  Open Risk #3 with a number against it rather than a worry.
- **The threshold has no lower bound from data.** 0.7s is chosen, not measured,
  and only a person mid-sentence can say whether it is too low.
- ~~**Nothing routes a session through `OrchestratedProvider`**~~ — **wired, and
  ElevenLabs Agents is deleted.** See *The room a socket actually opens*, below.

---

## The room a socket actually opens, 2026-08-16

Everything above was reachable only from tests. A live socket dialled ElevenLabs
Agents: their speech recognition, their model, their turn-taking, **one voice**,
and a persona configured in their dashboard rather than in `agents/archetypes.py`.
None of the seating, casting, cadence or grounding work could be heard by anyone
holding a phone.

`app/modules/voice/room.py` closes that. `build_room` assembles a session's
`OrchestratedProvider` from two halves:

| half | what | where from |
| --- | --- | --- |
| per process | transcriber, panel model, speaker | built once in the lifespan |
| per session | seated panel, grounding claims | the database, at socket time |

The per-session half is why the room cannot be a FastAPI dependency the way the
old provider was: **identity arrives with the ticket.** A WebSocket handshake has
no header to read, so redemption is the only thing that establishes who the
caller is — and the claims query is filtered by owner.

### Agents is deleted rather than kept behind a flag

The first instinct was a deployment flag with Agents as the fallback. That was
wrong, and the reason is worth writing down: **a single generic interrogator is
not a degraded Flintroom.** It is the delivery-scoring, listen-and-tell-me-how-I-
did product that `Product.md` §1 exists to refuse. Falling back to it would not
be shipping something lesser; it would be shipping the competitor.

Every part of Agents already had a replacement built and measured — Scribe hears,
Gemini writes, our own synthesis speaks in eight cast voices. What it contributed
by the end was nothing we wanted.

**What stays:** ElevenLabs itself, for both ears and mouth; and the
`VoiceProvider` Protocol, which is the seam `CLAUDE.md` keeps for Gemini Live.
`OrchestratedProvider` satisfies that same seam, which is why `relay.py`,
metering, idle detection and the client protocol are untouched by any of this.

**What went:** `voice/providers/` entirely, `ELEVENLABS_AGENT_ID`, and the agent
in their dashboard.

### Two things the wiring exposed

- **The route had no tests at all.** Tickets, relay, orchestration, panel and
  transcription were each covered; the line joining them was not — which is
  exactly where wiring fails, because a route that builds the wrong object still
  typechecks and still starts. `test_stream_route.py` now drives the socket end
  to end: the archetype a session was seated with is the one that composes, and
  its line comes back as a caption. Proven by mutation on the grounding path.
- **`Grounding.claims` was rendered by nothing.** It is documented as
  pre-rendered citable lines and was built by hand in tests only. A panel wired
  up in that state would have produced precisely the ungrounded generic questions
  Open Risk #2 names as the fastest way to lose a user. `ingestion/citations.py`
  renders the stored quote verbatim — never rebuilt from `metric`/`value`/`unit`,
  which would give "gross margin of 61.0%" instead of the sentence on the slide —
  and marks a figure read off a chart as such, so no panelist asserts that a deck
  *says* words that appear in no text layer.

### Open

- **Never run against a real device.** Every part is measured and the whole is
  tested, but no phone has yet held one of these rooms.
- **The budget still does not close** — ~2.1s against 1.5s. Unchanged by this
  work, and now the only thing between the panel and being real.

---

## Closing the budget, 2026-08-17

The first end-to-end measurement from a real phone put the room at **2.70s** —
speech stopped, panel answered — against the ~1.5s at which `CLAUDE.md` says the
illusion breaks. The terms, each measured warm rather than estimated:

| | measured |
| --- | --- |
| VAD silence threshold (0.7s) | 0.77s |
| `model.select` | 0.77s |
| `model.compose` | 0.82s |
| First speech frame (`eleven_flash_v2_5`) | 0.38s |
| | **2.74s** |

Which accounts for the 2.70s exactly. Nothing was unexplained, and the whole gap
was one hop that did not need to be there.

### The overlap this document specified was never built

The diagram above — routing against a partial transcript while the user is still
speaking, composition as the only serial hop — has been the design since the
two-call shape was adopted. `OrchestratedChannel._listen` never did it. Partials
were read for barge-in alone, and every turn paid the full selection hop after
the user went quiet.

`panel.select_speaker` is now public and the room starts it on the first partial
of each utterance, collecting it when the final arrives. Re-measured on the same
instrument, five turns:

| | Before | After |
| --- | --- | --- |
| Speech stopped → caption | 2.70s | **1.77s** |
| Speech stopped → first audio frame | ~3.08s | **~2.15s** |

**One selection per turn, not one per partial.** A partial arrives roughly every
150ms, so routing on each would be twenty calls for a sentence and would turn the
cheapest hop in the room into the most expensive thing in it. The cost is
unchanged; only its position moved.

**The room never waits for it.** An utterance shorter than the call — *"about
sixty"* — leaves the final arriving first, and waiting there would put the whole
hop back on the critical path in exactly the case with least patience for it, and
do it invisibly, since every measurement taken on a full sentence would still
look fine. A late selection is cancelled and `routing.choose` answers instantly:
the same trade `select_speaker` already makes for one that fails or names nobody
— relevance rather than silence.

### Routing on three words is not the problem it looks like

The first partial carries two or three words. That looked indefensible, and the
first live run appeared to confirm it: five turns, all to the CFO.

Measured with everything else held equal — same roster, same accumulating
transcript, same model, only the prefix varying:

| routing sees | who spoke, across eight utterances |
| --- | --- |
| 3 words | cfo ×6, technical_skeptic ×2 |
| 6 words | cfo ×6, technical_skeptic ×2 |
| 9 words | cfo ×5, technical_skeptic ×3 |
| 12 words | cfo ×5, technical_skeptic ×3 |
| the finished sentence | cfo ×4, technical_skeptic ×3, champion ×1 |

Prefix length barely moves it. **The concentration is a bias in the selection
prompt, present at every length including the whole sentence**, and it predates
this change — `_SELECTION_INSTRUCTION` asks for "whoever has been quiet" and the
model largely ignores it, so the model path has no counterpart to
`routing.QUIET_WEIGHT`. It has its own task. A word-count threshold before
routing would have bought nothing measurable and spent the headroom the overlap
depends on.

## Giving the floor away, 2026-08-17

The bias above, fixed. Same corpus, same roster, same model, so the numbers sit
directly against the table in the previous section:

| routing sees | before | after |
| --- | --- | --- |
| 3 words | cfo ×7, skeptic ×1 | cfo ×3, skeptic ×3, champion ×2 |
| 6 words | cfo ×5, skeptic ×3 | cfo ×3-4, skeptic ×3-4, champion ×1 |
| 12 words | cfo ×5, skeptic ×3 | cfo ×3, skeptic ×3, champion ×2 |
| the finished sentence | cfo ×4, skeptic ×3, champion ×1 | cfo ×2-3, skeptic ×3, champion ×2-3 |

Three distinct archetypes at every prefix length, against one or two before.
The Champion previously spoke **once in forty selections** and never at the
lengths a live room actually routes on.

Ranges where two runs of `scripts/rotation.py` disagreed, and they are the honest
form: the exact split moves by a turn between runs and nothing here should be
read as a fixed number. What holds across every run is the shape — three voices
at every prefix length, and the CFO leading rather than monopolising.

### The data was never the missing part

Two changes, and it is worth recording that the obvious one is the weaker one.

**Annotating the roster** — each panelist marked `[has not spoken yet]`,
`[spoke last turn]` or `[silent for N turns]` by `_silence_of` — and changing
nothing else moved 5 of 8 to **6 of 8**. Slightly worse. The model was handed the
silence it had been asked to weigh and declined to weigh it.

**Ranking the criteria** is what worked. The instruction had named three
considerations joined by *or* — relevance, silence, disagreement — and left the
model to balance them. It balanced them by taking the one it can always justify.
Relevance is defensible on every single turn; "somebody else has been quiet" is
never defensible on any particular turn, only across a room. An unordered list of
criteria where one is locally justifiable and the others are only globally
justifiable collapses to the first, and that is a general shape worth remembering
rather than a fact about this prompt.

Replaced with numbered steps and one hard prohibition: a panelist who has not
spoken takes the floor unless the ground is squarely somebody else's; otherwise
relevance decides, but never the panelist marked as having just spoken.

### Both halves are needed, for different reasons

The ranked instruction alone — the model counting silence out of the transcript
itself — reaches the same spread. It does not reach the same rooms:

```
ranked instruction only   cf cf cf te te ch ch te   ← three CFO turns running
with the roster counted   cf te ch cf te cf ch te   ← never twice in a row
```

Asked to both count and decide, the model approximates the count and the hard
prohibition stops binding. Counting turns is arithmetic, code does it exactly,
and it costs about five tokens per panelist on a call already sending the roster.

The coupling this creates is real and invisible: the rules quote the exact
phrases `_silence_of` stamps. Reword either side alone and the request still goes
out, still parses, still returns a name — and the room quietly returns to one
voice. `test_the_rules_and_the_roster_use_the_same_words_for_silence` exists so
that fails loudly instead.

### Pressing a dodge, without holding the floor

The first draft of rule 2 forbade consecutive turns outright. That was wrong
twice over, and the second way is the instructive one.

It gave up the sharpest move a room has. *"That is not what I asked"* is the
single most useful thing a panel does — `routing.py` says so in its own
docstring, and `test_the_router_sees_the_conversation_and_not_just_the_questions`
exists precisely so the model can tell an answered question from an evaded one.
A rule forbidding the follow-up makes that signal unusable in the only case it is
collected for. It also cuts against the wedge: a CFO who asks where 61% comes
from, is told *"margin has always been a strength for us"*, and then rotates
politely away is the room `Product.md` §1 exists to refuse.

**And it did not do what it claimed.** Measured on
`scripts/followup.py` — eight scenarios, four genuine dodges and four real
answers to the same four questions — the "unless nobody else has any claim on it"
escape hatch fired constantly once the last utterance was a *reply* rather than
fresh ground: 2 of 4 dodges pressed and 2 of 4 answers pressed. No prohibition,
and no discrimination either. The rotation corpus never showed this because every
utterance in it opens new ground.

### Ask for something checkable, not for a judgement

| rule 2 says | presses a dodge | presses a real answer |
| --- | --- | --- |
| never follow up (first draft) | 2/4 | 2/4 |
| "if the presenter dodged, press" | 4/4 | **4/4** |
| "if the reply contains no figure, name, date or mechanism, press" | 4/4 | 1-2/4 |

The middle row is the finding worth keeping. Asked whether the presenter dodged,
the model says yes every time — a judgement invites the agreeable answer, and a
rule that always fires is not a rule. Asked whether the reply contains a
*specific*, it discriminates cleanly.

This is the same split `docs/auditor-grounding.md` is built on, arriving
somewhere it was not expected: let the model read, and decide against something
that cannot be talked into existence.

### The cap, and what it is buying

A follow-up rule that fires correctly still concentrates the room, because the
presenter it fires on is vague — and a vague presenter is every presenter worth
rehearsing. Same corpus, same model, only rule 2 varying:

| rule 2 | busiest archetype | consecutive repeats |
| --- | --- | --- |
| never follow up | 4.0 / 8 | 0.5 |
| press, uncapped | 5.5 / 8 | 4.0 |
| **press once, then yield** | **4.0-4.5 / 8** | **2.5-3.0** |

So the cap buys back essentially all of the rotation while keeping 3-4 of 4
dodges pressed. A panelist may press their own question; they may not press the
press. It hangs on a fourth marking, `spoke the last two turns`, counted in
`_silence_of` — and counted in *panel* turns, since a follow-up has the
presenter's reply in the middle of it and consecutive panel turns are never
consecutive transcript lines.

**Chosen by the architect on 2026-08-17**, over pressing freely and over not
pressing at all. It is panel tone, which `CLAUDE.md` reserves.

The Auditor overrules all of it regardless: a finding routes by domain in
`panel.interrogate` and never reaches this prompt, so a contradiction is put by
whoever owns it whether or not they just spoke.

`routing.py`, the keyword fallback, is untouched: it already weighs silence
against relevance numerically (`QUIET_WEIGHT` against `DOMAIN_WEIGHT`) and only
runs when the model call fails or names nobody.

### Known: a truncated reply looks like an evasion

Rule 2 asks whether the reply contains a specific, and a three-word prefix
almost never does — so routing on an early partial reads every utterance as a
dodge. It shows up consistently: across runs the 3-word and 6-word columns carry
the worst concentration (cfo ×5-6 of 8) while 12-word and full sit at 3-4.

That is the production path, so it matters. The fix is cheap and not yet
built — the room *knows* whether it is looking at a partial, and the instruction
does not say. Filed rather than bolted on, because it wants its own measurement.

### What the longer prompt cost

The instruction nearly trebled and the roster gained a marking per panelist, on a
call that sits inside a 1.5s budget. Measured twice, twelve calls each time,
alternating old and new against the same context so a slow minute lands on both:

| | input tokens | median | range |
| --- | --- | --- | --- |
| before | 265 | 0.69s / 0.73s | 0.58 – 1.07s |
| after | 473 | 0.75s / 0.66s | 0.58 – 0.88s |

**No measurable cost.** The two runs disagree on the sign, so the difference is
smaller than the noise — which is the honest reading and not the +0.06s the first
run alone appeared to show. 200 extra input tokens on a prompt this small do not
register; the output is still two tokens either way.

None of it would reach the user regardless. Selection starts on the first partial
and overlaps the tail of the utterance, and if it is outrun `_take_routing`
cancels it and `routing.choose` answers instantly.

### Still open

- **~2.15s to first audio against 1.5s.** Closer, not closed. What remains is
  VAD (0.77s), composition (0.82s) and synthesis (0.38s), and none of the three
  is free to remove.
- **The VAD threshold is a human judgement, not a measurement.** Now
  `VAD_SILENCE_THRESHOLD_SECS`, settable per deployment, because judging it
  means hearing two values back to back and a judgement costing a rebuild per
  trial is one nobody makes twice. Measured across five turns, 0.7 → 0.4 is
  worth **0.30s** — 1.77s to caption becomes 1.47s — so the whole threshold
  passes through. Nothing bounds it from below except how rude the room feels
  when somebody pauses mid-answer, and synthetic speech has no mid-sentence
  pauses, so only a real person in a real room can set it.

  **Settled on a phone, 2026-08-17: 0.4 interrupts a real person mid-answer;
  0.7 does not.** So the 0.30s is not available and the room ships at ~1.77s to
  caption, ~2.15s to first audio. 0.55 is untested and is where to look if the
  budget has to come down again.
- **Streaming composition is the one structural lever left**, and it is an
  architecture decision rather than a tuning one: synthesise the first sentence
  while the model is still writing the second. Worth roughly 0.4s, and it makes
  the turn interruptible in the middle of its own generation.

## Telling the room the sentence is not finished, 2026-08-17

Routing runs on the first partial so its ~0.77s hop overlaps the tail of the
utterance. The prompt was never told that, and rule 2 presses when the reply
contains no figure, name, date or mechanism — which a three-word prefix never
does. The hypothesis was that every early partial therefore read as an evasion,
concentrating the room on the path production actually uses.

`TurnContext.unfinished` now carries it, `_route` sets it, and rule 2 says it
does not apply while the presenter is still speaking.

### The harness was not testing the thing

`scripts/rotation.py` truncates the utterance to simulate a partial and never
set the flag. So the first before/after compared two identical prompts and read
the difference as an effect. It is set now.

### One run is not evidence, and several earlier ones were

Three runs of an unchanged prompt moved the busiest archetype by two out of
eight in a single column. That is wider than most of the differences argued over
in this document. The instrument's docstring now says to take medians of at
least three, and the earlier single-run figures here should be read as weaker
than they were written.

### Placement mattered more than wording

Written as its own paragraph between rules 1 and 2, the guidance made things
worse across every column — repeats rose from 3 to 5 at three words and from 3
to 5 at twelve. Folded into rule 2 as a condition, it behaved. That is the same
finding as *Giving the floor away*: the ranked list is load-bearing, and a
paragraph inserted into it damages the ranking rather than adding to it.

### What it actually bought, in medians of three

|          | busiest before | after | repeats before | after |
| ---      | ---            | ---   | ---            | ---   |
| 3 words  | 5/8            | 3/8   | 3              | 3     |
| 6 words  | 6/8            | 6/8   | 4              | 4     |
| 12 words | 2/8            | 2/8   | 3              | 3     |
| full     | 4/8            | 5/8   | 3              | 3     |

`scripts/followup.py` is unchanged at 4/4 dodges pressed and 2/4 answers, so
rule 2 still works on a finished sentence — the risk was disarming it entirely.

**The hypothesis was half wrong.** Repeats are identical in every column, so
rule 2 over-firing on partials was *not* what concentrated the room. The
three-word column improved and nothing else did.

The likely remainder is the corpus rather than the prompt: half of `SAID` opens
on money — "Our gross margin", "Freight is already", "Nobody has churned" — so
at three words the CFO is frequently the *correct* answer, and a share of what
this instrument reports as concentration is routing working. Separating those
two would need a corpus whose first three words are deliberately neutral, which
is a different instrument than this one.

## Letting the panel disagree, 2026-08-17

`Product.md` §3.1 asks for a mixed room whose members "disagree with each other".
Every line until now was addressed to the presenter, so the champion and the CFO
never noticed each other existed — a star, not a table.

Shape settled with the architect, and the division is the design: **code owns the
occasion, the panelist owns the substance.** `app/agents/dispute.py` answers only
whether this is a turn where a difference of priority may be voiced. It never
decides what the difference is.

### What the architect refused, and why it was right

The first proposal was a declared-opposition field on `Archetype` — the Champion
argues with the CFO. Rejected on the grounds that a hardcoded rivalry fires on
schedule whether or not the colleague said anything worth disputing.

Pulling that thread found something worse than a stilted room. A panelist able to
dismiss a colleague's challenge can send the presenter away without answering a
question a real board would have pressed — the panel working against the product's
own purpose. So the scope narrowed to **priority only, never substance**: a
panelist may say margin is not what sinks this, and may not say the CFO was wrong
to ask.

### The gate

Four checks, all against data that already existed. Cap unspent; the archetype
has `domains` of its own; the previous panel line is not its own; that speaker's
domains do not overlap its own.

Two properties fall out rather than being written. A panelist pressing its own
unanswered question (#43) cannot also dispute, because the previous speaker is
itself. And the Distracted Executive never disputes, because it deliberately has
no domains — its complaint is that you are not making the point clearly, which
is not a subject.

The cap is in code. #43 measured what a model does when asked to judge whether a
rule applies: asked whether the presenter had dodged, it said yes on 4 of 4
dodges *and* 4 of 4 genuine answers.

### Three framings, three failures

`scripts/dispute.py` runs eight pairs and counts two checkable things: does the
line still put a question to the presenter, and is the colleague referenced at
all. The third question — is their question left standing — needs a person.

| Instruction | asked | named | What went wrong |
| --- | --- | --- | --- |
| "say what matters more than that" | 8/8 | 0/8 | Best lines by a distance, and dismissive. Produced substantive claims about a colleague's ground, one of them false: *"Data ownership does not touch the margin."* |
| "you want something answered first" | 7/8 | — | Safe and invisible. *"Onboarding moved everything. What did it move to our gross margin?"* signals no disagreement at all |
| "name their subject, say yours comes first" | 8/8 | 3/8 | Audible and stilted — it narrates the mechanic: *"Technical skeptic asked about data ownership. I want mine answered first."* In one case the skeptic asked the CFO's question instead of its own |

The first framing carried an explicit ban — *"you are not saying they were wrong
to ask"* — and violated it anyway. A prohibition in the instruction is not a
prohibition, which is the same finding as #43 and as the partial-routing work
earlier the same day.

### Shipped, and honestly weaker than intended

The second framing is in place: the only one that cannot harm the presenter. Its
cost is that the disagreement is frequently inaudible, so the feature currently
underdelivers rather than misbehaves.

### Both remaining ideas were tried, and the pattern closed

| Instruction | asked | named | What went wrong |
| --- | --- | --- | --- |
| In the **persona** rather than the turn prompt | 8/8 | 3/8 | Audible and *rude*. "Never mind what the CFO just asked about." "Let technical_skeptic wait" — leaking an internal name. "Ignore him." The worst of the five on the one axis that matters |
| **One clause**, one sentence | 7/8 | 0/8 | Safe and invisible again, plus one turn where the Technical Skeptic asked the CFO's burn question instead of its own |

Five framings, and they sort into two columns with nothing in between:

|            | audible | safe |
| ---        | ---     | ---  |
| matters more | yes   | no   |
| answered first | no  | yes  |
| name their subject | yes | no |
| in the persona | yes | no |
| one clause | no      | yes  |

**Audible implies dismissive; safe implies invisible.** That is not a prompting
failure to be solved with a sixth attempt. In English, voicing a difference of
priority *is* a mild dismissal — "I want mine answered first" cannot be said
without implying theirs is less urgent. The brief asked for audible and never
dismissive, and those two may not both be available.

### What that changes about the decision

The harm was that a dismissed question goes unanswered. That argument is weaker
than it was this morning, because the transcript now persists both sides of the
room for the life of the account and the debrief is grounded in it. A question
waved away in the room is still in the record, and Phase 4 ranks weak answers
from exactly that record.

So the choice is no longer "dismissive or safe" but "dismissive in the room and
recovered in the debrief, or absent from both". That is a product-tone decision
and belongs to the architect.
