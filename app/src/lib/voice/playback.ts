import { fromPcm16, resampleLinear } from '../audio/pcm';

/**
 * Panel audio, from the wire to the loudspeaker.
 *
 * Owns the one thing the socket must not know about — that a device output
 * stream does not run at the rate the protocol does — and the one thing the
 * screen must not have to think about: what barge-in means to a buffer queue.
 */

/** The rate `docs/voice-stream-protocol.md` fixes. The relay transcodes nothing. */
const WIRE_SAMPLE_RATE = 16000;

/**
 * The slice of `AudioContext` this needs.
 *
 * Structural rather than the concrete class, so a test can supply a context
 * without a native module behind it — and so replacing the audio library
 * (task #25) is a matter of satisfying four members.
 */
export interface PlaybackContext {
  readonly sampleRate: number;
  readonly destination: unknown;
  createBufferQueueSource(): QueueSource;
  createBuffer(numberOfChannels: number, length: number, sampleRate: number): AudioBufferLike;
}

export interface AudioBufferLike {
  copyToChannel(source: Float32Array, channel: number): void;
}

export interface QueueSource {
  connect(destination: unknown): void;
  enqueueBuffer(buffer: AudioBufferLike): string;
  clearBuffers(): void;
  start(when?: number): void;
  stop(when?: number): void;
}

export interface Playback {
  /** One frame of panel audio, PCM16 at the wire rate. */
  enqueue(pcm: ArrayBuffer): void;
  /** Barge-in. The source keeps running, ready for whatever is said next. */
  discard(): void;
  /** The room is over. Audio offered after this is dropped. */
  stop(): void;
}

export function createPlayback({ context }: { context: PlaybackContext }): Playback {
  const source = context.createBufferQueueSource();
  source.connect(context.destination);

  // Started before a single frame has arrived. An empty queue renders silence
  // and leaves the node running, so there is no state where audio is waiting
  // on playback to be told to begin — which would cost the opening of the
  // first question, the one moment the room has to land.
  source.start();

  let playing = true;

  return {
    enqueue: (pcm) => {
      // Frames outlive the socket: the ones already in flight when the room
      // ended. Played, they would put a panelist's question over the top of
      // the debrief.
      if (!playing) {
        return;
      }

      // Resampled *before* the buffer is made, and the buffer declared at the
      // context's rate. `createBuffer` carries a sample rate but does not act
      // on it during playback, so a 16 kHz buffer in a 48 kHz context is
      // played as though it were 48 kHz — three times too fast.
      const samples = resampleLinear(fromPcm16(pcm), WIRE_SAMPLE_RATE, context.sampleRate);
      const buffer = context.createBuffer(1, samples.length, context.sampleRate);

      buffer.copyToChannel(samples, 0);
      source.enqueueBuffer(buffer);
    },

    // `clearBuffers` and not `stop`. It drops the buffer mid-play as well as
    // those behind it — it clears the whole queue and resets the read index —
    // so the panelist is cut off inside the word, which is what being
    // interrupted sounds like. Stopping the source would do that too, and
    // would also end playback for the rest of the room.
    discard: () => source.clearBuffers(),

    stop: () => {
      playing = false;
      source.stop();
    },
  };
}
