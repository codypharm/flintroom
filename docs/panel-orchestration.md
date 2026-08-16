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
- **The latency budget is unmeasured.** Every decision above assumes the chain
  fits in ~1.5s and none of them has been tested against a clock.
