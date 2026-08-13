# Who owns the conversation loop

**Decision (2026-08-13): ElevenLabs Agents runs the loop through Phase 2. We
take it back in Phase 3, as a sibling module behind the existing
`VoiceProvider` interface.**

Read this before adding STT, changing the voice provider, or wondering why
LangGraph is in the stack table but not in the code.

## The tension

`CLAUDE.md` assigns LangGraph "agent state machine, panel turn-taking, Auditor
workflow." It also names ElevenLabs Agents as the voice layer. Those are two
things that both want to be the orchestrator, and today ElevenLabs is winning:
it owns transcription, turn detection, the LLM call, and speech. LangGraph owns
nothing yet.

That was invisible while there was no code. It became visible the moment a real
conversation ran (`docs/voice-latency.md`), because the measurement showed the
provider making conversational decisions — when a speaker has finished a thought
— that belong to the product.

## Why Phase 3 rather than now

Phase 2's deliverable is *barge-in verified end-to-end from Expo*. Every piece
of that is provider-agnostic: the relay, the ticket handshake, the metering
seams, `discard_playback`, the wire protocol, and the entire mobile audio path.
None of it changes when the orchestrator changes, so none of it is wasted work,
and all of it is easier to get right against a loop that already works.

Building the owned pipeline now would mean writing streaming STT, our own
endpointing, LLM speculation and TTS cancellation **before there is any client
able to hear the result** — four new failure modes with no way to tell which one
is misbehaving.

## Why not stay on ElevenLabs Agents permanently

Three things it structurally cannot do, each of which is the product rather than
a nice-to-have:

1. **A panel is not one agent.** Flintroom needs archetypes taking turns from
   each other — a champion, a skeptic, a neutral, disagreeing (`CLAUDE.md` →
   Agent/Panel Architecture). Their multi-voice support is one model performing
   voices, which sounds similar and is not the same mechanism.
2. **The Auditor must interrupt on its own.** Targeted interruption — the
   Auditor spots a mismatch against ingested material and the archetype whose
   domain covers that metric cuts in — requires a second process watching the
   transcript and injecting a turn. That is orchestration, not a prompt.
3. **`session_costs` has columns nothing can fill.** §4.3 wants
   `llm_input_tokens`, `llm_output_tokens` and `auditor_invocations` split by
   panel, Auditor and coach. A managed agent bills an opaque per-minute rate, so
   those columns stay NULL — and every tier margin in §4.4 rests on them.

## What Phase 3 has to build, and what it costs

```
now       Expo ⇄ FastAPI ⇄ ElevenLabs Agents
                            (STT + turn + LLM + TTS)

phase 3   Expo ⇄ FastAPI ⇄ streaming STT
                         ⇄ LangGraph  (panel, Auditor, turn-taking)
                         ⇄ ElevenLabs TTS  (per-archetype voice ids)
```

The latency arithmetic is the part to go in with eyes open. Today's think/speak
figure of 0.04s is **borrowed**: `speculative_turn` runs generation *during* the
silence wait, so the answer exists before the turn is called. An owned pipeline
runs serially unless we build the same trick:

| Stage | Expected |
| --- | --- |
| Endpointing (ours) | 0.7–1.4s, depending on how semantic we make it |
| LLM first token | ~0.4s |
| TTS first byte | ~0.15s |

That is roughly parity with today's measured 1.5s, and better than it only if we
speculate. **Speculation is not an optimisation to add later — it is the reason
the current numbers look good, and leaving it out will read as a regression.**

Barge-in also becomes ours. `CLAUDE.md` names native barge-in as the reason
ElevenLabs was chosen at all, so this is the clearest thing being given up. The
client half already exists — `discard_playback` is in the wire protocol and the
relay emits it — but detecting the interruption and cancelling in-flight TTS
moves to us.

## What does not change

`relay.py`, `tickets.py`, `settlement.py`, `router.py`, `costs.py`,
`docs/voice-stream-protocol.md`, and the whole Expo client. The
`VoiceProvider` / `VoiceChannel` protocols were built so a provider is a sibling
file, and an owned pipeline satisfies them exactly as a vendor does: it yields
`ChannelReady`, `UserSpoke`, `Heartbeat`, `AgentAudio`, `Interrupted` and
accepts PCM.

This is the interface earning its keep. Keep it that way — anything that leaks
orchestration concepts above the adapter takes the option away.

## Signals that would reopen this earlier

- Turn-taking cannot be tuned to acceptable pacing without the panel talking
  over users (see the interruption count in `voice_spike.py`).
- Multi-voice markup turns out to be unable to carry distinct archetypes
  convincingly, making Phase 3's panel work start early by force.
- Provider cost per minute, once observable on a paid plan, breaks the §4.4
  margins — owning the LLM call is the main lever on that number.
