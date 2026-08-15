import { toPcm16 } from '../audio/pcm';

/**
 * What the user says, on its way to the panel.
 *
 * The recorder hands over Float32; the wire takes PCM16 at 16 kHz mono
 * (`docs/voice-stream-protocol.md`) and the relay transcodes nothing. This is
 * the only step in between.
 */

/** The rate the protocol fixes, and the one the recorder is asked for. */
const WIRE_SAMPLE_RATE = 16000;

/**
 * 20 ms at the wire rate.
 *
 * Small enough that a barge-in is noticed promptly, since the provider's VAD
 * cannot react to speech it has not been sent; large enough that the socket is
 * not doing fifty sends a second for the sake of it. Nothing measured this —
 * it is the conventional frame for voice, and the latency spike is where it
 * would be revisited.
 */
const FRAME_SAMPLES = 320;

/**
 * The microphone delivered a rate the wire cannot carry.
 *
 * Deliberately fatal to the room rather than resampled. Converting 48 kHz down
 * to 16 kHz without a low-pass filter folds everything above 8 kHz back into
 * the speech band, which lands on sibilants and degrades transcription in a way
 * no one would trace to here — and the alternative, sending it unconverted, is
 * the user played back at a third speed. Failing carries the rate, so the first
 * device that does this arrives in a bug report instead of in a churn number.
 */
export class UnsupportedCaptureRate extends Error {
  constructor(readonly rate: number) {
    super(`The microphone delivered ${rate} Hz; the wire carries ${WIRE_SAMPLE_RATE} Hz`);
    this.name = 'UnsupportedCaptureRate';
  }
}

export interface RecorderBufferLike {
  getChannelData(channel: number): Float32Array;
  readonly sampleRate: number;
}

/** The slice of `AudioRecorder` this needs. Structural, so tests need no native. */
export interface UplinkRecorder {
  onAudioReady(
    options: { sampleRate: number; bufferLength: number; channelCount: number },
    callback: (event: { buffer: RecorderBufferLike; numFrames: number }) => void
  ): unknown;
  clearOnAudioReady(): void;
}

export interface UplinkOptions {
  recorder: UplinkRecorder;
  /** Where the frames go. `Connection.send`, in the assembled room. */
  send: (pcm: ArrayBuffer) => void;
  /** The uplink cannot carry this device's audio. Called at most once. */
  onFailure?: (error: UnsupportedCaptureRate) => void;
}

export interface Uplink {
  /** Stop listening to the microphone. */
  stop(): void;
}

export function createUplink({ recorder, send, onFailure }: UplinkOptions): Uplink {
  const stop = () => recorder.clearOnAudioReady();

  recorder.onAudioReady(
    // Mono, because the wire is mono and a stereo capture would put the
    // second channel's samples where the provider expects the next 20 ms.
    { sampleRate: WIRE_SAMPLE_RATE, bufferLength: FRAME_SAMPLES, channelCount: 1 },
    (event) => {
      // Checked on every buffer rather than once, because the rate is a
      // property of what arrived and not of what was requested. Unsubscribing
      // first means this reports once and not fifty times a second.
      if (event.buffer.sampleRate !== WIRE_SAMPLE_RATE) {
        stop();
        onFailure?.(new UnsupportedCaptureRate(event.buffer.sampleRate));
        return;
      }

      // Trimmed to `numFrames`, not sent whole. The recorder reports the two
      // separately because the tail of a buffer is stale audio from the
      // previous pass, and a `subarray` is a view rather than a copy — no
      // allocation in the hot path for the common case where they agree.
      const captured = event.buffer.getChannelData(0).subarray(0, event.numFrames);

      send(toPcm16(captured));
    }
  );

  return { stop };
}
