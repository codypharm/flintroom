import { useTheme } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import { Button, ScrollView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView } from 'react-native-safe-area-context';
import { requestRecordingPermissionsAsync } from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';

import {
  ECHO_ABSOLUTE_DBFS,
  ECHO_OVER_FLOOR_DB,
  echoAboveFloorDb,
  isGatedFloor,
  median,
  rms,
  toDbfs,
  verdict,
} from '@/lib/audio/level';
import { PANEL_SPEECH_BASE64 } from '@/lib/audio/panelSpeech';
import { fromPcm16 } from '@/lib/audio/pcm';
import { toWav } from '@/lib/audio/wav';
import { enterHandsFree, leaveHandsFree } from '../../modules/audio-routing';
import { openCaptureStack, openPlaybackStack } from '../lib/voice/stack';

/**
 * The echo go/no-go spike (task #17), run on a real device.
 *
 * Hands-free means speakerphone: panel audio leaves the speaker, the mic is
 * open the whole time, and whatever the mic hears we stream back. If our own
 * panel comes back up the uplink, the provider's VAD reads it as a barge-in and
 * the panel interrupts itself. `docs/voice-latency.md` records that this failure
 * is indistinguishable from model latency once you are in the room, which is why
 * it gets measured rather than assumed.
 *
 * This measures the acoustic half of that question and deliberately does not
 * involve the provider. `vad_score` is bimodal — 0.00 or 1.00, nothing between
 * — so there is no gradient to learn from it; it only tells us which side of a
 * cliff we landed on, at the cost of provider minutes. The mic level tells us
 * *how far* from the cliff, on any handset, for free.
 *
 * Method: measure the room in silence, then measure it again with a loud
 * speech-band signal playing out of the speaker. A working acoustic echo
 * canceller leaves the two roughly equal. Everything else is a failure with a
 * magnitude attached.
 *
 * Since #25 there is exactly one stack to measure: `modules/room-audio`, the
 * pair the live room itself runs on. The library it replaced, and the button
 * that measured it, are gone with it — its numbers survive in
 * `docs/echo-cancellation.md`, alongside the owned pair's, taken on the same
 * phone in the same room in the same minute.
 *
 * Undesigned on purpose — this is an instrument, not a screen, and it should
 * never reach `design-guide/`.
 */

/** Per phase. Long enough to average out a passing car, short enough to repeat. */
const PHASE_SECONDS = 4;

/** Let the speaker and any AGC settle before believing what the mic reports. */
const SETTLE_SECONDS = 0.75;

// Both thresholds come from `lib/audio/level`, which is also what `verdict`
// judges by. Restating them here would let the screen print a bar the verdict
// did not actually use — which is how a reader talks themselves into the
// wrong conclusion about the one risk gating the audio layer.

const RECORD_SAMPLE_RATE = 16000;

type Phase =
  | 'idle'
  | 'silence'
  | 'playback'
  | 'done'
  | 'capturing'
  | 'captured'
  | 'error';

interface Report {
  noiseFloorDbfs: number;
  playbackDbfs: number;
  echoDb: number;
  observedSampleRate: number;
  buffersSilent: number;
  buffersPlayback: number;
}

const wait = (seconds: number) =>
  new Promise((resolve) => setTimeout(resolve, seconds * 1000));

/**
 * Four seconds of speech-band signal, as bare samples.
 *
 * Not a pure tone. Echo cancellers and voice-activity detectors are both tuned
 * for speech, and a steady sine is the one input where an AEC can look far
 * better than it is — it is trivially predictable. Stacked harmonics inside the
 * voice band, gated by a 4 Hz syllabic envelope, are a closer surrogate for a
 * panelist talking, without needing a speech asset on the device.
 *
 * Bare `Float32Array` rather than an audio-graph buffer because the owned
 * stack takes PCM through a queue: the signal is synthesised in JavaScript
 * and fed as chunks. Same formula as every measurement recorded in
 * `docs/echo-cancellation.md`, so the numbers stay comparable across stacks.
 */
function speechLikeSamples(seconds: number, sampleRate: number): Float32Array {
  const data = new Float32Array(Math.floor(sampleRate * seconds));
  for (let i = 0; i < data.length; i += 1) {
    const t = i / sampleRate;
    const syllable = 0.5 * (1 - Math.cos(2 * Math.PI * 4 * t));
    const voice =
      (Math.sin(2 * Math.PI * 220 * t) +
        Math.sin(2 * Math.PI * 440 * t) +
        Math.sin(2 * Math.PI * 880 * t) +
        Math.sin(2 * Math.PI * 1760 * t)) /
      4;
    data[i] = 0.9 * syllable * voice;
  }
  return data;
}

/**
 * The checked-in panel speech, as bare samples.
 *
 * No resample: the asset is 16 kHz (`docs/voice-stream-protocol.md` fixes the
 * wire's rate both ways) and the owned playback stream runs at exactly that
 * rate — the alignment the live downlink relies on, exercised here too.
 */
function panelSpeechSamples(): Float32Array {
  const binary = atob(PANEL_SPEECH_BASE64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return fromPcm16(bytes.buffer);
}

/** Chunked, because `String.fromCharCode(...everything)` overflows the stack. */
function base64Encode(bytes: Uint8Array): string {
  let binary = '';
  const CHUNK = 8192;
  for (let at = 0; at < bytes.length; at += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(at, at + CHUNK));
  }
  return btoa(binary);
}

export default function EchoSpikeScreen() {
  // See the note in `index.tsx`: an uncoloured `Text` is black regardless of
  // appearance, so on the dark theme it reads as an empty screen.
  const { colors } = useTheme();
  const [phase, setPhase] = useState<Phase>('idle');
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [residualPath, setResidualPath] = useState<string | null>(null);

  const levels = useRef<number[]>([]);
  const observedRate = useRef<number>(0);

  /**
   * The go/no-go measurement, through the owned stack (#25) — which since the
   * library's removal is the stack, the same pair the live room opens. What
   * this button measures is therefore exactly what a session would hear.
   */
  const run = useCallback(async () => {
    setReport(null);
    setError(null);

    try {
      const permission = await requestRecordingPermissionsAsync();
      if (!permission.granted) {
        throw new Error(`Microphone permission ${permission.status}`);
      }

      // Routing is policy and stays the app's: the owned player declares
      // voice-communication usage, which outside communication mode routes to
      // the earpiece — the #26 finding, unchanged by who owns the stream.
      await enterHandsFree();

      const { recorder } = openCaptureStack();

      recorder.onAudioReady(
        { sampleRate: RECORD_SAMPLE_RATE, bufferLength: 1600, channelCount: 1 },
        (event) => {
          observedRate.current = event.buffer.sampleRate;
          levels.current.push(rms(event.buffer.getChannelData(0)));
        }
      );

      // Phase one: the room as it is. Everything measured later is relative to
      // this, so a noisy room does not by itself fail the test.
      setPhase('silence');
      levels.current = [];
      await recorder.start();
      await wait(PHASE_SECONDS);
      const silent = [...levels.current];

      // Phase two: same room, same mic, speaker now loud. The recorder is
      // never stopped between phases — restarting it would renegotiate the
      // stream and could hand us a different input path than just measured.
      setPhase('playback');
      const sound = openPlaybackStack();
      await sound.ready();
      const source = sound.context.createBufferQueueSource();
      source.connect(sound.context.destination);
      source.start(0, 0);

      // The whole phase enqueued up front: the native queue is the loop.
      const samples = speechLikeSamples(
        SETTLE_SECONDS + PHASE_SECONDS + 1,
        sound.context.sampleRate
      );
      const CHUNK = 3200; // 200 ms — coarse is fine, nothing is latency-bound
      for (let at = 0; at < samples.length; at += CHUNK) {
        const buffer = sound.context.createBuffer(
          1,
          Math.min(CHUNK, samples.length - at),
          sound.context.sampleRate
        );
        buffer.copyToChannel(samples.subarray(at, at + CHUNK) as Float32Array, 0);
        source.enqueueBuffer(buffer);
      }

      await wait(SETTLE_SECONDS);
      levels.current = [];
      await wait(PHASE_SECONDS);
      const playing = [...levels.current];

      source.stop(0);
      await sound.close();
      recorder.stop();

      const noiseFloor = median(silent);
      const duringPlayback = median(playing);

      setReport({
        noiseFloorDbfs: toDbfs(noiseFloor),
        playbackDbfs: toDbfs(duringPlayback),
        echoDb: echoAboveFloorDb(noiseFloor, duringPlayback),
        observedSampleRate: observedRate.current,
        buffersSilent: silent.length,
        buffersPlayback: playing.length,
      });
      setPhase('done');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setPhase('error');
    } finally {
      // In `finally` because the audio mode is process-wide and outlives this
      // screen. A run that throws halfway would otherwise leave the whole app
      // in communication mode, and the symptom — the volume rocker adjusting
      // the wrong stream — shows up nowhere near the cause.
      leaveHandsFree();
    }
  }, []);

  /**
   * Capture the residual: what the mic still hears while real panel speech
   * plays, after the echo canceller has had its go.
   *
   * The acoustic run measures a level, and a level runs out of resolution at
   * the noise gate. Whether the residual reads as *speech* is not a question a
   * level can answer — only the provider's own VAD can, and `vad_score` is
   * bimodal, so the answer is unambiguous once asked.
   *
   * Written to a file rather than streamed, so one `adb pull` isolates exactly
   * one question. The WAV is assembled here from the same frames the uplink
   * would have sent — `toWav` plus the capture stream — because the owned
   * recorder deliberately has no file output: the product streams, and a
   * second sink in the native module would exist only for this screen.
   */
  const captureResidual = useCallback(async () => {
    setReport(null);
    setError(null);
    setResidualPath(null);

    try {
      const permission = await requestRecordingPermissionsAsync();
      if (!permission.granted) {
        throw new Error(`Microphone permission ${permission.status}`);
      }

      await enterHandsFree();

      const { recorder } = openCaptureStack();

      const heard: Float32Array[] = [];
      recorder.onAudioReady(
        { sampleRate: RECORD_SAMPLE_RATE, bufferLength: 1600, channelCount: 1 },
        (event) => {
          observedRate.current = event.buffer.sampleRate;
          // Copied: the adapter is free to reuse its buffer between frames.
          heard.push(new Float32Array(event.buffer.getChannelData(0)));
        }
      );

      setPhase('capturing');
      await recorder.start();

      const sound = openPlaybackStack();
      await sound.ready();
      const source = sound.context.createBufferQueueSource();
      source.connect(sound.context.destination);
      source.start(0, 0);

      const speech = panelSpeechSamples();
      const CHUNK = 3200;
      for (let at = 0; at < speech.length; at += CHUNK) {
        const buffer = sound.context.createBuffer(
          1,
          Math.min(CHUNK, speech.length - at),
          sound.context.sampleRate
        );
        buffer.copyToChannel(speech.subarray(at, at + CHUNK) as Float32Array, 0);
        source.enqueueBuffer(buffer);
      }

      // The asset's length plus a moment either side: the tail matters because
      // an echo canceller converging is exactly when it leaks most.
      await wait(speech.length / RECORD_SAMPLE_RATE + 1);

      source.stop(0);
      await sound.close();
      recorder.stop();

      if (heard.length === 0) {
        throw new Error('The capture stream delivered no frames');
      }

      const total = heard.reduce((sum, frame) => sum + frame.length, 0);
      const samples = new Float32Array(total);
      let at = 0;
      for (const frame of heard) {
        samples.set(frame, at);
        at += frame.length;
      }

      // WAV because it is the one format that needs no FFmpeg backend, and
      // this file is going straight into a Python script that would rather
      // not decode anything either.
      const wav = toWav(samples, observedRate.current || RECORD_SAMPLE_RATE);
      const path = `${FileSystem.cacheDirectory}residual.wav`;
      await FileSystem.writeAsStringAsync(path, base64Encode(new Uint8Array(wav)), {
        encoding: FileSystem.EncodingType.Base64,
      });

      setResidualPath(path);
      setPhase('captured');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setPhase('error');
    } finally {
      leaveHandsFree();
    }
  }, []);

  const running =
    phase === 'silence' || phase === 'playback' || phase === 'capturing';

  return (
    <SafeAreaView style={styles.screen}>
        {/*
          `auto`, overriding the root's `dark`. This screen is a dev harness
          that follows the system theme rather than the product's committed
          light ground, so its background flips and the glyphs have to flip
          with it.
        */}
        <StatusBar style="auto" />
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={[styles.heading, { color: colors.text }]}>Echo spike</Text>
        <Text style={[styles.body, { color: colors.text }]}>
          Put the phone flat on a desk, speaker up, and stay quiet for about ten
          seconds. It measures the room in silence, then again with a loud
          speech-band tone playing.
        </Text>

        <Button
          title={running ? 'Measuring…' : 'Run measurement'}
          onPress={run}
          disabled={running}
        />

        <Button
          title={running ? 'Working…' : 'Capture residual for vad test'}
          onPress={captureResidual}
          disabled={running}
        />

        {phase === 'capturing' && (
          <Text style={[styles.phase, { color: colors.text }]}>
            Playing panel speech and recording what comes back. Stay quiet.
          </Text>
        )}

        {residualPath && (
          <View style={styles.report}>
            <Text style={[styles.figure, { color: colors.text }]}>
              Residual captured
            </Text>
            <Text style={[styles.body, { color: colors.text }]}>
              Pull it with:
            </Text>
            <Text style={[styles.path, { color: colors.text }]}>
              adb pull {residualPath.replace('file://', '')}
            </Text>
          </View>
        )}

        {phase === 'silence' && (
          <Text style={[styles.phase, { color: colors.text }]}>Measuring the room. Stay quiet.</Text>
        )}
        {phase === 'playback' && (
          <Text style={[styles.phase, { color: colors.text }]}>Playing. Still stay quiet.</Text>
        )}

        {error && <Text style={styles.error}>{error}</Text>}

        {report &&
          (() => {
            const decision = verdict(
              report.noiseFloorDbfs,
              report.playbackDbfs,
              { silent: report.buffersSilent, playback: report.buffersPlayback }
            );

            // Reported separately rather than as a third colour on the same
            // verdict, because the levels below it are meaningless when nothing
            // was recorded and printing them next to a word like GO is how a
            // broken run gets believed.
            if (decision === 'inconclusive') {
              return (
                <View style={styles.report}>
                  <Text style={[styles.verdict, { color: colors.text }]}>
                    NO DATA
                  </Text>
                  <Text style={[styles.body, { color: colors.text }]}>
                    The recorder delivered {report.buffersSilent} buffers in
                    silence and {report.buffersPlayback} during playback, so
                    there is nothing to compare and no verdict to give.
                  </Text>
                  <Text style={[styles.body, { color: colors.text }]}>
                    Usually the input stream was disconnected by an audio
                    routing change — check logcat for
                    AAUDIO_SERVICE_EVENT_DISCONNECTED.
                  </Text>
                </View>
              );
            }

            return (
              <View style={styles.report}>
                <Text style={[styles.verdict, { color: colors.text }]}>
                  {decision === 'no-go' ? 'NO-GO' : 'GO'} (owned stack)
                </Text>
                <Text style={[styles.figure, { color: colors.text }]}>
                  During playback: {report.playbackDbfs.toFixed(1)} dBFS
                </Text>
                <Text style={[styles.body, { color: colors.text }]}>
                  Noise floor {report.noiseFloorDbfs.toFixed(1)} dBFS
                  {isGatedFloor(report.noiseFloorDbfs)
                    ? ', gated to digital silence by noise suppression, so the ratio below is not meaningful and the verdict uses the absolute level above.'
                    : `, so playback sits ${report.echoDb.toFixed(1)} dB above it.`}
                </Text>
                <Text style={[styles.body, { color: colors.text }]}>
                  Recorder returned {report.observedSampleRate} Hz (asked for{' '}
                  {RECORD_SAMPLE_RATE}). Buffers: {report.buffersSilent} silent,{' '}
                  {report.buffersPlayback} playing.
                </Text>
                <Text style={[styles.body, { color: colors.text }]}>
                  {isGatedFloor(report.noiseFloorDbfs)
                    ? `Fails above ${ECHO_ABSOLUTE_DBFS} dBFS. Noise suppression has removed the floor, so the only question left is whether what the mic still hears is loud enough to read as speech.`
                    : `Fails at ${ECHO_OVER_FLOOR_DB} dB above the floor. A working canceller leaves this near zero; tens of dB up means the mic is hearing the speaker and the panel will interrupt itself.`}
                </Text>
              </View>
            );
          })()}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { padding: 24, gap: 16 },
  heading: { fontSize: 22, fontWeight: '600' },
  body: { fontSize: 15, lineHeight: 21 },
  phase: { fontSize: 15, fontStyle: 'italic' },
  error: { fontSize: 15, color: '#b00020' },
  report: { gap: 8, marginTop: 8 },
  verdict: { fontSize: 28, fontWeight: '700' },
  figure: { fontSize: 17, fontWeight: '600' },
  path: { fontSize: 13, fontFamily: 'monospace' },
});
