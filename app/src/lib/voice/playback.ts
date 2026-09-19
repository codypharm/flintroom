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
  /**
   * The utterance queued so far ends here.
   *
   * Called when `turn_finished` arrives. The wire delivers a turn's audio
   * frames before the control frame that closes it, so whatever was queued
   * last at this moment is that utterance's last buffer — which makes this an
   * exact boundary rather than an inferred one.
   */
  mark(): void;
  /** Barge-in. The source keeps running, ready for whatever is said next. */
  discard(): void;
  /** The room is over. Audio offered after this is dropped. */
  stop(): void;
}

export interface PlaybackOptions {
  context: PlaybackContext;
  /**
   * One marked utterance has finished coming out of the loudspeaker.
   *
   * **Not the same thing as the turn being over, and the difference was
   * visible on a device.** `turn_finished` says the server sent its last frame;
   * synthesis runs ahead of playback by design, which is what makes barge-in
   * possible, so the panelist was released from the screen while their voice
   * was still coming out of the phone.
   *
   * **This reported an empty queue until 2026-09-19, and an empty queue is the
   * wrong boundary.** When a presenter talks over the tail of a question the
   * server has already closed, the next panelist's frames are appended behind
   * that tail in this same queue. The loudspeaker moves from one voice to the
   * next without the queue ever emptying, so a drain signal reported once, at
   * the end of the second — and the screen had been a whole turn ahead of the
   * audio for all of it.
   *
   * Reported per mark, in order, so two utterances queued back to back are two
   * separate reports at the moment each one actually ends.
   */
  onPlayed?: () => void;
  /**
   * The queue has emptied — the loudspeaker is idle.
   *
   * A different question to `onPlayed`, and both are here because two callers
   * ask different things. The room needs to know where one utterance ends and
   * the next begins, which an empty queue cannot tell it. The debrief coach
   * has one voice and no turns to keep apart: it streams a reply in chunks and
   * never says where the reply ends, so "nothing left to play" is the only
   * signal it has, and it is the right one — it is what re-enables the
   * controls that speaking disabled.
   *
   * Do not use it to decide who is speaking. That is what it was used for, and
   * it is why the screen ran a turn ahead of the audio.
   */
  onDrained?: () => void;
}

export function createPlayback({
  context,
  onPlayed,
  onDrained,
}: PlaybackOptions): Playback {
  const source = context.createBufferQueueSource();
  source.connect(context.destination);

  // Started before a single frame has arrived. An empty queue renders silence
  // and leaves the node running, so there is no state where audio is waiting
  // on playback to be told to begin — which would cost the opening of the
  // first question, the one moment the room has to land.
  //
  // Both arguments passed explicitly — a scar from the library #25 replaced,
  // whose `start(when = 0, offset = -1)` rejected its own default and threw on
  // every bare `start()`, surfacing only on a device as a room that opened and
  // immediately died. The owned module has no such trap; the explicit call
  // stays because it is what the tests can assert.
  /**
   * Buffers handed to the node and not yet reported back.
   *
   * Needed because `mark` can arrive after the audio it describes has already
   * played — a short utterance whose frames all finished while
   * `turn_finished` was still crossing the network. Without this the mark
   * would wait on an id that is never reported again, and the floor would
   * never come back.
   */
  const outstanding = new Set<string>();
  /**
   * The buffer ids that end an utterance, oldest first.
   *
   * An array rather than a set, because two marks can name the same buffer:
   * an utterance that queued no audio at all marks whatever the previous one
   * ended on. Each end consumes one.
   */
  const boundaries: string[] = [];
  let tail: string | null = null;

  // Released as they finish, and this is not housekeeping. A panel line is
  // roughly ninety frames, so three exchanges leave two hundred and seventy
  // buffers held by a node that has already played them — the only quantity in
  // this client that counts up and never comes down. Rooms died after about
  // three replies with the phone closing the socket, which is what that looks
  // like from the far end.
  source.onBufferEnded = ({ bufferId, isLastBufferInQueue }) => {
    outstanding.delete(bufferId);
    source.dequeueBuffer(bufferId);
    // Released first, and reported second. The release is what keeps a room
    // alive past three replies; a listener that threw would otherwise take it
    // down with it.
    while (boundaries[0] === bufferId) {
      boundaries.shift();
      onPlayed?.();
    }
    if (isLastBufferInQueue) {
      onDrained?.();
    }
  };

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
      tail = source.enqueueBuffer(buffer);
      outstanding.add(tail);
    },

    mark: () => {
      // Nothing outstanding to wait for: either this utterance queued no audio
      // at all — synthesis can fail with the caption already sent — or all of
      // it played before the mark crossed the network. Both mean it is over
      // now, and waiting on a buffer that will never be reported would hold
      // the floor for the rest of the room.
      if (tail === null || !outstanding.has(tail)) {
        onPlayed?.();
        return;
      }
      boundaries.push(tail);
    },

    // `clearBuffers` and not `stop`. It drops the buffer mid-play as well as
    // those behind it — it clears the whole queue and resets the read index —
    // so the panelist is cut off inside the word, which is what being
    // interrupted sounds like. Stopping the source would do that too, and
    // would also end playback for the rest of the room.
    discard: () => {
      // The buffers these marks were waiting on will never end, so a mark left
      // behind would be inherited by whatever is queued next.
      boundaries.length = 0;
      outstanding.clear();
      tail = null;
      source.clearBuffers();
    },

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
