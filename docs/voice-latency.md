# Voice latency, measured

What `backend/scripts/voice_spike.py` found against a live ElevenLabs agent on
2026-08-13. Every latency claim in this repo before this document was an
assumption; these are numbers.

Read this before touching the voice pipeline, changing turn-taking, or quoting
Open Risk #3 (`Product.md`) at anyone.

## Conditions

| | |
| --- | --- |
| Agent | `flintroom-phase2-harness`, free plan |
| LLM | `gemini-2.5-flash` |
| ASR | `scribe_realtime`, quality `high` |
| Turn model | `turn_v3`, `speculative_turn: true` |
| Audio | `pcm_16000` both directions, no transcode anywhere |
| Speech | macOS `say`, three claim-with-a-number sentences |

Latency is measured from the last frame of the user's audio leaving, to the
first byte of panel audio arriving — the gap a person in the room experiences,
not a server-side stage timing.

## The headline

**The model is not the problem. Turn-taking is the entire problem.**

| Stage | Time |
| --- | --- |
| End of sentence → provider accepts the turn ended | 1.44–6.21s |
| Provider accepts → first byte of audio (LLM + TTS) | **0.03–0.06s** |

Think/speak is effectively free, and it is free for a reason: `speculative_turn`
is on, so generation runs *during* the silence wait. The answer is already built
when the timer expires. Which means turn-detection time is very nearly the whole
latency, and any work spent making the model faster would buy nothing.

## What moved the number

| Setting | Median | Endpointing | Per-turn |
| --- | --- | --- | --- |
| `turn_timeout: 7.0`, eagerness `normal` | 6.25s | 6.21s | 1.51, 6.25, 8.05 |
| `turn_timeout: 2.0`, eagerness `normal` | 4.26s | 4.23s | 1.80, 4.26, 5.52 |
| `turn_timeout: 2.0`, eagerness **`eager`** | **1.50s** | 1.44s | 1.31, 1.70 |

`eager` is the setting that matters. It lands on the 1.5s threshold and — more
useful than the median — it collapses the *variance*: 1.31–1.70s, against a
1.5–8.05s spread at `normal`. Unpredictable pacing is what reads as broken.

`turn_timeout` is not a hard cap. At 2.0s the observed endpointing was 4.23s,
because `turn_v3` is semantic: it waits until you sound like you have finished a
*thought*, not merely until you stop making noise. The one sentence that ended
cleanly endpointed in 1.73s; the two that trail off did not.

**`asr.quality` is not a knob.** The API accepts `high` and rejects everything
else, so there is no cheaper transcription to trade accuracy against latency.

## The cost of `eager`

At `normal`, one measured turn returned a *negative* latency: the panel began
answering 0.27s before the sentence had finished. It talked over the speaker.

That is the risk `eager` increases, and it is not a latency bug — it is the
product's central tension. A panel that interrupts is the point (`Product.md`
§1); a panel that interrupts a user who is thinking is the churn cause
(`Product.md` — a first session that destroys the user produces churn, not
resilience). The spike now counts interruptions separately and refuses to
average them into the median, because a reply that arrives before the question
ended is not fast.

## Settled by the same run

- **`xi-api-key` is accepted on the WebSocket handshake.** No signed URL needed.
  This closes the UNVERIFIED note in `ElevenLabsProvider.open`.
- **Channel ready in 0.63–0.80s.** Agent spin-up, during which the session sits
  in `provisioning` and bills nothing.
- **`SPEECH_THRESHOLD = 0.5` is safe.** Real `vad_score` values are bimodal —
  0.00 and 1.00, nothing in between. The threshold sits in an empty gap rather
  than on a slope, so the guess turned out not to matter.
- **A client that stops sending frames has not gone quiet, it has gone away.**
  The first spike run waited 20s for a reply that never came, because their
  endpointer decides a turn ended by *hearing* silence. See below.

## What this means for the Expo client

**The uplink must never stop.** The phone streams continuously — silence
included — between sentences. A bandwidth optimisation that suppresses silent
frames will break turn-taking, and will break it in a way that looks exactly
like model latency: the panel simply never answers. This is the single
highest-value line in this document for whoever builds the audio path.

Budget at 16 kHz mono PCM16: 32 KB/s raw on our leg, ~43 KB/s base64 on the
provider leg. Measured 1.5 MiB up for 40s of connection.

## Open

- **Cost per minute is unmeasured.** The free plan issues no invoice, so
  `Product.md` §4.3 reconciliation cannot start and the $0.12/min assumption
  behind every tier margin in §4.4 remains unverified. Blocked on a paid plan.
- **The 1.5s threshold itself.** It was written about model latency, which is
  0.04s. Whether ~1.5s *end-to-end including turn-taking* is the right bar is a
  product judgement, not something this spike can settle.
- **Multi-archetype panel.** Everything above measures one agent answering. The
  panel is several archetypes with turn-taking between them plus a background
  Auditor, which is orchestration ElevenLabs Agents does not do. See
  `docs/deferred-scale-work.md` conventions for how that decision gets recorded
  when it is made.

## Reproducing

```
uv run python -m scripts.voice_spike              # 3 turns, full report
uv run python -m scripts.voice_spike --turns 1    # cheapest useful run
uv run python -m scripts.voice_spike --sweep      # compare turn settings
```

`--sweep` edits the live agent and restores it on every path out, including
failure. Each run costs ~40s of connection against the plan.
