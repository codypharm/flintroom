// Scoped here rather than added to `tsconfig`'s `types`, which would put Node's
// globals in scope for app code too — in a React Native bundle that turns a
// runtime crash into something the compiler happily accepts.
/// <reference types="node" />
import { readFileSync } from 'fs';
import { join } from 'path';

/**
 * The guard on `app/patches/`.
 *
 * The echo fix lives in six lines of vendored C++, which means nothing in this
 * repo fails when it disappears — and it *has* disappeared, twice, silently:
 * once to an install and once to a bug in `scripts/apply-patches.sh` that
 * reversed the very hunks it was meant to protect. The symptom is not a crash.
 * It is the panel interrupting itself, which `docs/voice-latency.md` records as
 * indistinguishable from model latency once you are in the room.
 *
 * So this asserts on the vendored source. Reading `node_modules` in a test is
 * ordinarily a smell; here it is the only seam that sees the failure, because
 * the thing being protected is not our code. See `docs/echo-cancellation.md`.
 *
 * Android AEC is a property of the stream *pair*. Both files have to be right
 * or neither matters — the recorder says "cancel", the player says "cancel
 * against this" — so they are asserted together.
 */
const VENDORED = join(
  __dirname,
  '../../../node_modules/react-native-audio-api/android/src/main/cpp/audioapi/android'
);

function source(file: string): string {
  return readFileSync(join(VENDORED, 'core', file), 'utf8');
}

describe('the recorder stream', () => {
  const recorder = () => source('AndroidAudioRecorder.cpp');

  it('asks for the input preset that engages echo cancellation', () => {
    // Oboe's default is `VoiceRecognition`, which is tuned for ASR and
    // deliberately leaves AEC off. Absent this line there is no cancellation at
    // all, whatever the player does.
    expect(recorder()).toContain('setInputPreset(oboe::InputPreset::VoiceCommunication)');
  });

  it('does not request the raw fast path, which bypasses pre-processing', () => {
    // `Exclusive` + `LowLatency` hand back a stream that skips the block where
    // AEC, AGC and NS live. Faster, and silently useless to us.
    expect(recorder()).toContain('setSharingMode(oboe::SharingMode::Shared)');
    expect(recorder()).toContain('setPerformanceMode(oboe::PerformanceMode::None)');
  });
});

describe('the player stream', () => {
  const player = () => source('AudioPlayer.cpp');

  it('declares itself voice communication, so AEC has a reference to subtract', () => {
    // The finding that bought 34.7 dB. Without a declared usage the platform
    // has been told to cancel without being told what — the recorder preset
    // alone measured *worse* than stock.
    expect(player()).toContain('setUsage(Usage::VoiceCommunication)');
    expect(player()).toContain('setContentType(ContentType::Speech)');
  });

  it('does not request the raw fast path either', () => {
    expect(player()).toContain('setSharingMode(SharingMode::Shared)');
    expect(player()).toContain('setPerformanceMode(PerformanceMode::None)');
  });
});
