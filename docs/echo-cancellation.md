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

## The second defence, shipped 2026-08-22 — the room refuses its own line

#78's decision, made by the architect: platform AEC on one measured handset is
too thin a wall for something that corrupts the record the whole debrief is
grounded in, so the server now refuses a final that is the room's own newest
panel line returning. `app/modules/voice/echo.py` is the matcher;
`OrchestratedChannel._listen` applies it beside the empty-final guard, and a
refusal does what that guard does: nothing at all. No transcript line, no
Auditor reading, no turn — and no idle-clock reset, because on a handset with
weak AEC an abandoned room would otherwise keep itself alive past every idle
check, asking and hearing its own questions on the presenter's minutes.

The measurement above is what makes it this small. Echo mixed under a talking
presenter never reaches the transcript, so the only candidate is the **newest**
panel line, and only while nothing genuine has been said since — which is
exactly "the transcript still ends with a panel line". No clocks, no levels.

Two thresholds, both from rulings rather than tuning:

- **Coverage ≥ 0.8** of the panel line. A completed playback echoes whole; a
  fragment can only be echo when playback was cut, and playback is only cut
  when the presenter is already talking — the mix Scribe is measured to
  reject. So "Ten times?" thrown back is a person, and is kept.
- **At most one novel token.** A presenter who repeats the question *and keeps
  going* is thinking aloud, and the added words prove it — they always pass.
  The accepted cost, ruled on explicitly: a presenter who repeats the panel's
  line word for word, adds nothing, and stops is swallowed, and the room
  waits for their actual answer.

Tokens are normalised (case, punctuation, number words to digits) because the
measured echo differed from its source by exactly "ten" -> "10".

Refusals log `echo_final_refused` with the match figures and never the text.

**What this does not cover:** echo *partials* arriving while a panelist is
still speaking can cut them off — the room interrupting itself. Only devices
with no AEC at all exhibit it (the emulator; headphones remove it), no
transcript is corrupted, and widening the guard to partials would let the
matcher veto genuine barge-in, which is the feature the stack was chosen for.
Revisit only if a real handset shows it.

## The first end-to-end run, 2026-08-27 — reported, not instrumented

A live room on the Play build, Galaxy S24+, against the real provider. The
architect talked over a panelist mid-line. Two things happened, and they are
not the same thing:

- **The words survived.** The room answered what had been said. Speech spoken
  *while the panel was speaking* reached the transcriber and became a turn, so
  the residual-echo suppressor is not destroying a talking presenter on this
  handset.
- **The panelist did not stop.** It finished its line, and the interruption was
  picked up and acted on afterwards rather than cutting in. Barge-in as an
  *interrupt* was not observed; barge-in as *being heard* was.

The architect's ruling on the second point: acceptable as it feels. Recorded
here rather than left as a shrug, because **#25 reimplements `discard_playback`
against a spec that says drop buffered audio immediately** — and whoever builds
that will otherwise read this device's behaviour as a regression they caused.

**What this run does not answer.** It was at conversational volume, close to
the handset, which is the case #17 had already covered. No `vad_score` was
read. It is a field report, and it moves the end-to-end path from untested to
working; it is not the measurement the Open item below asks for.

## The owned stack, measured — 2026-09-02

The reopen condition above fired: #25 replaced the audio layer with
`modules/room-audio`, so the silent room was re-measured, through the same
spike screen's owned-stack run, on the same Galaxy S24+, phone flat on a
desk, speaker up.

| | Owned stack | Patched library (2026-08-21) |
| --- | --- | --- |
| Noise floor | −120.0 dBFS (gated) | −120.0 dBFS (gated) |
| During playback | **−120.0 dBFS** | −120.0 dBFS |
| Recorder rate | 16000 Hz, as asked | 16000 Hz |

**Exact digital silence, matching the patched pair.** The property survives
the ownership change: `VOICE_COMMUNICATION` on the recorder and
`USAGE_VOICE_COMMUNICATION` on the player, now two plain declarations in
`RoomAudioModule.kt` instead of a patch nothing in the suite protects.

The dead-microphone half was answered live rather than by a capture: a real
room on the owned stack, the architect talking over a panelist mid-line, and
the room heard and answered what was said. Same shape as the 2026-08-27 run,
on the new stack.

`unheard`'s precondition holds: the gate still returns exact zeros, so the
latch in `app/modules/voice/hearing.py` remains reachable.

**#27 closed in the same session.** Two live rooms on the owned stack, same
phone: the architect talked over a panelist mid-line at conversational volume
close to the handset, and again from across the room, and both times the room
heard and answered what was said. The residual-echo suppressor does not
swallow a real interruption, near or far. What remains unanswered is iOS in
its entirety (#99).

**The library is gone — 2026-09-02.** With the owned pair measured equal to
the patched library, #25 finished: `react-native-audio-api`, `app/patches/`,
`scripts/apply-patches.sh`, the `postinstall` hook and the exact pin were all
removed. Everything above that describes the library's internals is history —
kept because it is the recorded reason the owned module declares what it
declares, and the measurement this stack was accepted against. File playback
(saved rooms, coach lines) moved to `expo-audio`; the live room and the
debrief's clips run on `modules/room-audio`, profile chosen in
`app/src/lib/voice/stack.ts`.

## iOS, measured — 2026-10-02

The first run on an iPhone, an iPhone 13, on a development build of the owned
stack, against the same Echo spike as every Android figure above. Phone flat on
a desk, volume at maximum, `voiceChat` with `defaultToSpeaker` as `stack.ts`
sets them.

| Capture | iPhone | Galaxy S24+ (owned stack) |
| --- | --- | --- |
| Quiet room, noise floor | −56.1 dBFS | — |
| Panel playing, presenter silent | **−99.9 dBFS**, GO | −120.0 dBFS |
| Talking over the panel, RMS | **−22.3 dBFS** (peak 0.0) | −26.7 dBFS (peak −4.9) |

**Both halves hold, and the second is the one that mattered.** iOS voice
processing can suppress the near end during far-end playback, and a
canceller that does that returns exactly the silence in the second row, while
also swallowing every interruption. The third row rules it out: speech spoken
straight through the panel reaches the uplink at a level comparable to the
Android handset, so the panel cannot hear itself and the presenter can still
cut in. The floor of −56.1 dBFS was not gated, so the 43.8 dB the panel sits
*below* it is a real ratio, not noise suppression flattening both readings.

The 0.0 peak is the presenter close to the microphone and loud, which is what
the capture asked for. It proves the microphone was alive; it is not a level the
room ever needs.

**What this does not answer.** One iPhone, one room, one run, read off the
phone's own screen rather than pulled and checked with `wav_level` — the cable
to hand was charge-only, which is why the screen now prints peak and RMS for
the residual. A live room on iOS against the real provider, talking over a
panelist the way the 2026-08-27 Android run did, is the field check still owed.

**The first live room on the same iPhone was silent, and the spike could not
have caught it.** The opener arrived, the seat lit, and nothing came out of the
speaker. Voice processing replaces the engine's I/O unit for both directions,
and `RoomAudioModule.swift` switched it on only in `beginCapture`. The spike
starts capture first; the live room plays the opener the moment the socket
opens and starts the microphone a beat later, so it switched voice processing
on under a running engine and the player played into nothing. Same module,
same phone, opposite order. `ensureVoiceProcessing` now switches it with the
engine stopped, from whichever side starts first, and playback enables it
before the player is attached. On the rebuilt app the room played its opener,
heard a 67-word opening and took nine turns at 0.44–1.24s. The architect talked
over a panelist mid-line and the room heard it and answered, which closes the
field check the paragraph above left owed.

**The lesson for the spike:** it measures one start order. A change to which
side of the room opens first is a change the spike will not see.

**Then the rooms went silent again, intermittently, and the cause was iOS
reconfiguring the engine under them.** Same symptom, a fresh room sometimes
working and the next one not. With no cable to the phone, a temporary probe
printed counts to the Metro terminal, and one failing room said it plainly:
iOS posted `AVAudioEngineConfigurationChange` and stopped the engine as
playback opened; the microphone delivered 549 frames and the server heard the
presenter, and of 69 chunks of a panelist's voice enqueued, none was played.
Two fixes in `RoomAudioModule.swift`: the session is only set when it differs,
since re-setting it under a running voice-processing engine is itself a
change; and the notification is observed, with recovery that rebuilds the
player's connections on the engine's current formats rather than only
restarting, because a restart alone brought the microphone back and left the
speaker playing into nothing. Three consecutive rooms on the rebuilt app, fresh
and "Run it again", all played and all heard. Each recovery logs
`[room-audio] the engine stopped under the room and was restarted` on a
development build.

Unrecovered, the bug is invisible from both ends: the server sends the opener
and logs nothing wrong, the phone lights the seat, and the room is refunded as
unheard. A metered room that plays nothing and refunds itself looks, in every
log, like a presenter who walked out.

## Open

- **One handset is not a result.** Echo behaviour is per-device on Android.

## Reproducing

`npx expo start --dev-client`, open **Echo spike** (nothing links to it; open
`flintroom://echo-spike` from the browser on the phone — Safari on iOS), put the
phone flat on a desk, turn the volume up, tap **Run measurement**, and stay
quiet for ten seconds.

Then take both residual captures, because neither means anything alone — one
says the far end is gone, the other says the microphone was alive to notice.
Tap **Capture residual for VAD test** and stay silent; tap it again and talk
straight through the panelist for the whole line, without waiting for gaps. Pull
them and measure:

```bash
adb shell "run-as com.flintroom.app cat cache/residual.wav" > capture.wav
uv run python -m scripts.wav_level capture.wav   # from backend/
```

The WAV is assembled on the phone from the same frames the uplink would have
sent — the owned recorder deliberately has no file output, so the spike writes
one itself (`toWav` plus `expo-file-system`). It lands in the app's *cache*
directory, so Android may evict it and a reinstall will clear it — pull before
rebuilding, and pull between captures, because each overwrites the last.
`adb pull` cannot read that path directly; `run-as` is what makes it readable,
and the byte count must match `ls -l` on the device or the shell has mangled
the file.
