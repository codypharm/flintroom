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
  /** Release a buffer that has finished playing. See `createPlayback`. */
  dequeueBuffer(bufferId: string): void;
  clearBuffers(): void;
  start(when?: number, offset?: number): void;
  stop(when?: number): void;
  onBufferEnded:
    | ((event: { bufferId: string; isLastBufferInQueue: boolean }) => void)
    | null
    | undefined;
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
  //
  // Both arguments are passed because `react-native-audio-api` cannot be called
  // without them. Its `start(when = 0, offset = -1)` then rejects any offset
  // below zero — so its own default fails its own validation, and a bare
  // `start()` throws `offset must be a finite non-negative number: -1` every
  // time. Nothing in the test suite catches it: the fake here has no such
  // guard, so this surfaced only on a device, as a room that opened and
  // immediately died. More evidence for task #25.
  // Released as they finish, and this is not housekeeping. A panel line is
  // roughly ninety frames, so three exchanges leave two hundred and seventy
  // buffers held by a node that has already played them — the only quantity in
  // this client that counts up and never comes down. Rooms died after about
  // three replies with the phone closing the socket, which is what that looks
  // like from the far end.
  source.onBufferEnded = ({ bufferId }) => source.dequeueBuffer(bufferId);

  source.start(0, 0);

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
      const samples = amplify(
        resampleLinear(fromPcm16(pcm), WIRE_SAMPLE_RATE, context.sampleRate)
      );
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


/**
 * How much of the synthesiser's unused headroom to claim back.
 *
 * **Measured, not chosen.** ElevenLabs returns PCM peaking at exactly -6 dBFS —
 * half of full scale — which is a mastering decision on their side rather than
 * anything about the speech. On a phone that is six decibels discarded before
 * the volume slider is consulted, and a room runs on the voice-call audio path
 * (`modules/audio-routing`, and `docs/echo-cancellation.md` for why), which is
 * quieter than media to begin with. The loss lands on top of a lower floor.
 *
 * It was audible before it was measured: a panel too quiet at maximum volume,
 * on a device that is otherwise loud enough.
 */
const HEADROOM_GAIN = 2;

/**
 * Louder, and never wrapped.
 *
 * Clamped rather than trusted. The gain is right for this vendor and this
 * measurement; a future synthesiser mastering at full scale would exceed it,
 * and a sample allowed past 1.0 wraps to the opposite sign further down — a
 * click, which is worse than the distortion a limiter produces and much harder
 * to attribute.
 */
function amplify(samples: Float32Array): Float32Array {
  for (let i = 0; i < samples.length; i += 1) {
    samples[i] = Math.max(-1, Math.min(1, samples[i] * HEADROOM_GAIN));
  }

  return samples;
}
