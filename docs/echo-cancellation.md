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

## Settled by the same run

**The recorder returns the sample rate it is asked for.** 16000 Hz requested,
16000 Hz delivered, across all 80 buffers of both phases. That is the rate
`docs/voice-stream-protocol.md` fixes and the relay transcodes nothing, so no
resampling step is needed in the client. Whether Oboe resamples internally from
a 48 kHz hardware rate is not visible from here and does not change our
contract. This closes task #18.

## Open

- **Whether −44.9 dBFS is quiet enough for the provider's VAD.** The acoustic
  proxy has run out of resolution, and this is the question it was standing in
  for. Answering it needs the end-to-end run task #17 originally specified:
  play panel audio, watch whether `vad_score` crosses 0.5. That test is now
  worth its cost, which it was not while the answer was 30 dB of obvious echo.
- **`MODE_IN_COMMUNICATION` is untried.** Android's platform AEC is documented
  to engage fully when `AudioManager` is in communication mode, which the
  library never sets. It is the next lever if the residual proves too loud, and
  it needs a Kotlin-side patch rather than a C++ one.
- **The test signal is harsher than a panelist.** A 0.9-amplitude harmonic stack
  under a 4 Hz envelope is a deliberately unkind input. Real speech has gaps and
  a lower crest factor, so the residual against real panel audio is likely
  quieter than measured here — which argues for the end-to-end test over more
  tuning against this surrogate.
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
