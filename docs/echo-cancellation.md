# Echo cancellation, measured

What task #17 found on a real device on 2026-08-13. Read this before touching
`app/src/lib/audio/`, changing the voice provider, or assuming the microphone
path is somebody else's problem.

The question: hands-free means speakerphone, so panel audio leaves the speaker
while the mic is open. If our own panel comes back up the uplink, the provider's
VAD calls it a barge-in and the panel interrupts itself. `docs/voice-latency.md`
records that this failure is indistinguishable from model latency once you are
in the room.

## The finding

**`react-native-audio-api` 0.13.2 does no echo cancellation on Android, by
construction.** This is not a configuration mistake at our end and there is no
setting that fixes it from JavaScript.

`AndroidAudioRecorder::openAudioStream()` builds the Oboe input stream with
sharing mode, direction, format, performance mode and callbacks — and never
calls `setInputPreset()`. So it inherits Oboe's default, `AudioStreamBase.h`:

```cpp
InputPreset mInputPreset = InputPreset::VoiceRecognition;
```

Android's `VOICE_RECOGNITION` source is tuned for ASR and deliberately leaves
echo cancellation off; `VOICE_COMMUNICATION` is the source that engages AEC, AGC
and noise suppression. Two further settings on the same builder — `SharingMode::
Exclusive` and `PerformanceMode::LowLatency` — request the raw fast path, which
on most devices bypasses the pre-processing block where AEC lives.

There is no escape hatch from JS. `SessionOptions` is entirely iOS-prefixed
(`iosMode`, `iosOptions`, `iosCategory`, …) with no Android field at all, and
`AudioRecorderCallbackOptions` exposes only sample rate, buffer length and
channel count. Upstream issue #670 asking for an AEC hook has been open and
unanswered since September 2025.

iOS is the opposite: `AudioSessionManager` handles `voiceChat`, so
`setAudioSessionOptions({ iosMode: 'voiceChat' })` engages Apple's voice
processing I/O. Unmeasured — see Open below.

## Measured, stock library

Samsung Galaxy S24+ (SM-S926U1), phone flat on a desk, speaker up, room quiet.
Method in `app/src/app/echo-spike.tsx`: measure the mic in silence, then again
with a loud speech-band signal playing out of the speaker, and compare the
median per-buffer RMS of each phase.

| | |
| --- | --- |
| Noise floor, silence | −57.3 dBFS |
| During playback | −26.6 dBFS |
| **Echo above floor** | **30.8 dB** |
| Fail threshold | 6 dB |

**NO-GO.** The mic hears the speaker roughly 35× louder than the room's own
noise floor. With a panelist actually speaking, that is speech by any measure a
VAD applies.

The S24+ is the *friendly* case — a flagship with good hardware audio. A
mid-range handset is where this gets worse, and we have not measured one.

## Measured, patched

Same device, same room, same volume. Two edits to the vendored C++, each tested
separately, because the second only works given the first.

| Build | Noise floor | During playback |
| --- | --- | --- |
| Stock | −57.3 dBFS | −26.6 dBFS |
| `InputPreset::VoiceCommunication` on the recorder | −120.0 (gated) | −10.2 dBFS |
| …plus `Usage::VoiceCommunication` on the player | −120.0 (gated) | **−44.9 dBFS** |

**The input preset alone made things worse.** Playback rose 16 dB. Asking for
`VOICE_COMMUNICATION` turns on noise suppression and automatic gain control as
well as echo cancellation; NS gated the silent room to *exact digital silence*
(39 buffers, every sample zero), and AGC — hearing nothing — ramped gain up and
was caught at full gain when playback started. Cancellation itself did nothing,
because platform AEC subtracts a *reference*, and there was none: `AudioPlayer.
cpp` sets no `setUsage()`, so playback defaulted to `Usage::Media`. The system
had been told to cancel without being told what.

**Adding the output usage bought 34.7 dB.** With both streams declared voice
communication, the platform knows which signal is the far end and subtracts it.
This is the finding: on Android, echo cancellation is a property of the *pair*
of streams, not a recorder setting.

The residual −44.9 dBFS sits within 0.1 dB of the absolute threshold in
`hasEcho`, which is a judgement rather than a measurement. The method cannot
resolve further: re-running lands either side of the bar on noise alone.

## The 34.7 dB is not all cancellation

Found on 2026-08-15, by a human noticing the panel sounded quiet and saying so.
`dumpsys audio`, taken straight after a run:

```
STREAM_VOICE_CALL:  streamVolume:15 (of 15)   Devices: earpiece(1)
STREAM_MUSIC:       streamVolume:8  (of 15)   Devices: speaker(2)
```

Volume was already at maximum. It sounded quiet because declaring
`Usage::VoiceCommunication` on the player **moved playback off the loudspeaker
and onto the earpiece** — the slit at the top of the handset, pointing at the
ceiling with the phone flat on a desk.

So the two patched runs changed two things at once, and the table above credits
both to cancellation. Some of the 34.7 dB is the platform subtracting a
reference; some is simply the loud speaker no longer being used. How that splits
is not knowable from these numbers.

It also means the figure does not describe this product. Flintroom is a phone
lying on a desk talking hands-free; earpiece playback is not a quieter version
of that, it is a different thing. The residual captured this way reads
−69.7 dBFS overall with three full seconds of exact digital silence, which would
pass any VAD test and prove nothing.

**Routing is not something `react-native-audio-api` can express.** `SessionOptions`
is iOS-only, there is no output-device or audio-mode call anywhere in its API,
and its Kotlin touches `AudioManager` solely for focus, media session and
volume. The app therefore stays in `MODE_NORMAL`, where a `VOICE_COMMUNICATION`
stream routes to the earpiece by design — working as documented, and wrong for
us.

The fix is `setMode(MODE_IN_COMMUNICATION)` plus
`setCommunicationDevice(TYPE_BUILTIN_SPEAKER)`: speakerphone, which is the
configuration the product actually ships in and the one Android's AEC is most
thoroughly tuned for. It lives in a module we own rather than in `patches/`,
because which speaker the panel comes out of is app policy and has to outlive
whichever audio library is underneath it. See task #26.

Until that lands, **treat every number above as provisional.**

## On the loudspeaker, which is the configuration we ship

Task #26 landed, so the run below is the first one taken in the product's actual
acoustic configuration: `MODE_IN_COMMUNICATION`, panel audio out of the built-in
loudspeaker, phone flat on a desk. Confirmed from `dumpsys audio` during the run
— `mAudioModeOwner: mMode=MODE_IN_COMMUNICATION` and
`AUDIO_STREAM_VOICE_CALL: Devices: speaker` — and confirmed released afterwards,
owner cleared and routing back to earpiece.

**The residual is exact digital zero.** 7.70 s, every sample zero, peak
−120.0 dBFS. Not "below the threshold": nothing at all.

That number cannot be banked on its own, because **perfect cancellation and a
dead microphone are indistinguishable in it**, and one of those ships a product
where nobody can hear the user. So a second capture was taken under identical
conditions with a human deliberately talking over the panelist for the full
line:

| Capture | Peak | Overall RMS |
| --- | --- | --- |
| Silent room, panel playing | −120.0 dBFS | −120.0 dBFS |
| Talking over the panel | **−4.9 dBFS** | **−26.7 dBFS** |

The microphone is fine, and the same code path that returned silence returns
healthy near-end speech. **That is the go.**

## What that costs elsewhere, found 2026-08-21

"Perfect cancellation and a dead microphone are indistinguishable" is a sentence
about the echo spike, and it is also a sentence about the product. A quiet room
on this configuration is **exact digital zero on the uplink**, so every question
of the form "can we hear the presenter right now" has the same answer whether
the microphone is working or unplugged.

#77 was written before this connection was made. It records an emulator with its
virtual microphone switched off producing 37 seconds of digital silence and then
one empty final that a panelist answered, reads it as an emulator artefact, and
proposes two fixes: gate silence out of the uplink, and warn the presenter from
the device's own level readings. **Neither survives the measurement above.**

- Gating silence out of the uplink would gate every *pause* on Android, because
  a pause and a dead microphone are the same bytes. Trailing silence is what the
  transcriber endpoints on, so this would break the thing it was meant to
  protect. It is also the voice-activity decision `OrchestratedChannel.
  send_audio` already refuses to make, moved one hop earlier and made invisible
  to the server.
- A level-based "your microphone is dead" warning would fire at every pause.
  That is the failure `app/src/lib/audio/hearing.ts` shipped once and documents
  at length — a warning at the noise floor teaches people to ignore the warning
  that matters.

What shipped instead is `app/modules/voice/hearing.py`: a latch on whether the
room has **ever** heard anything, which the two cases do separate, surfaced as
the `unheard` value of `attending`. `docs/voice-stream-protocol.md` carries the
reasoning and the thresholds.

**The reopen condition is the same one as above.** If the audio layer is ever
replaced (#25) or its input preset changed, re-measure the silent room. A
configuration whose noise gate leaves any residual dither makes `unheard`
unreachable — a false negative, and a silent one.

**The talk-over capture also proves the silence is cancellation rather than a
mic that mutes whenever the far end plays.** The panel line is 6.61 s long and
the capture is 7.72 s, so anything before ~6.7 s has the far end active. Within
that window the recording drops to exact digital zero during the speaker's
natural pauses — 0.0–0.8 s, 2.0–2.1 s, 6.0–6.3 s — and carries voice at −16 to
−30 dBFS either side of them. Far end playing plus near end silent gives zero;
far end playing plus near end talking gives the near end. That is the behaviour
the product needs, and it is barge-in working.

**What the zeros say about the mechanism.** Exact digital silence is not what
subtraction produces; subtraction leaves a low-level residual. This is a
residual-echo suppressor gating the output hard when it detects no near-end
speech. Worth knowing because it predicts the failure mode: the risk is not echo
leaking through, it is the gate swallowing a *quiet* interruption. The tested
voice was at conversational level and passed easily. Someone interrupting the
panel timidly, or from across a room, is untested.

## Settled by the same run

**The recorder returns the sample rate it is asked for.** 16000 Hz requested,
16000 Hz delivered, across all 80 buffers of both phases. That is the rate
`docs/voice-stream-protocol.md` fixes and the relay transcodes nothing, so no
resampling step is needed in the client. Whether Oboe resamples internally from
a 48 kHz hardware rate is not visible from here and does not change our
contract. This closes task #18.

## What the transcriber does with echo — measured 2026-08-19

Prompted by `filter_background_audio`, an engine option we do not set. Three
experiments against the live account, all with `language_code=en` pinned:

| Fed to Scribe | Filter off | Filter on |
| --- | --- | --- |
| Speech under broadband noise, 10 dB and 3 dB SNR | correct | correct |
| Presenter with a panel voice mixed **underneath** at 0.5 and 0.25 gain | presenter only | presenter only |
| A panel voice **alone** | transcribed verbatim | transcribed verbatim |

**`filter_background_audio` changed nothing in any of them, so it stays off.**
A knob that cannot be shown to do anything is a knob that will later be blamed
for something it does not affect.

The second row is the finding worth keeping. **Scribe already rejects a
simultaneous second voice** — at half amplitude, unaided — so echo arriving
*while the presenter is talking* is not a problem the room has. It never
reaches the transcript.

Which makes the third row the whole of #78: echo is transcribed **only when
nobody is talking over it**. With the presenter silent, the panel's returning
voice is not background at all — it is the only voice, and therefore the
primary speaker. That is exactly what happened in room 066f32db, where six of
nine "user" lines were verbatim repeats of the panelist before them, every one
of them landing in a gap.

So a defence does not need to reason about mixed audio, levels, or ratios. It
needs to notice that a lone utterance arriving after a panelist spoke is that
panelist. The verbatim-repeat check #78 already proposes is the right shape,
and this bounds when it has to fire.

## Open

- **Whether the gate swallows a quiet interruption.** The acoustic question has
  flipped: it is no longer whether echo reaches the provider's VAD — nothing
  reaches it — but whether a *hesitant* barge-in survives the residual-echo
  suppressor. The end-to-end run answers it directly: talk over the panel
  softly and watch whether `vad_score` crosses 0.5. Note that `vad_score` is
  bimodal in practice (`docs/voice-latency.md`), so it reads as a decision, not
  a level.
- **iOS is unmeasured.** There is no iPhone on this project; the simulator
  routes audio through the host Mac and cannot answer an acoustic question. The
  code sets `voiceChat` and `defaultToSpeaker`, which *should* be sufficient,
  but "should" is what this document exists to replace. An iPhone is a
  prerequisite before shipping, not a convenience.
- **One handset is not a result.** Echo behaviour is per-device on Android.

## Reproducing

`npx expo start --dev-client`, open **Echo spike** from the home screen, put the
phone flat on a desk, turn the volume up, tap **Run measurement**, and stay
quiet for ten seconds.

Then take both residual captures, because neither means anything alone — one
says the far end is gone, the other says the microphone was alive to notice.
Tap **Capture residual for VAD test** and stay silent; tap it again and talk
straight through the panelist for the whole line, without waiting for gaps. Pull
them and measure:

```bash
adb shell "run-as com.flintroom.app cat cache/AudioAPI/<file>.wav" > capture.wav
uv run python -m scripts.wav_level capture.wav   # from backend/
```

They land in the app's *cache* directory, so Android may evict them and a
reinstall will clear them — pull before rebuilding. `adb pull` cannot read that
path directly; `run-as` is what makes it readable, and the byte count must match
`ls -l` on the device or the shell has mangled the file.
