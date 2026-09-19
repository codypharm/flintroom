import type { NativePlaybackContext } from '../../../modules/room-audio';

import { toPcm16 } from '../audio/pcm';
import { createPlayback, type PlaybackContext } from './playback';

/**
 * The fake below is only worth anything if the real context satisfies the same
 * shape, so the typechecker is asked directly. A `type` import, so nothing
 * native is loaded to run the tests — the assertion is erased entirely.
 *
 * Without this the structural interface could drift from the module it
 * describes and every test here would keep passing, which is the standard way
 * a suite of green tests ends up describing a module that no longer works.
 * Since #25 the real context is the owned module's playback adapter.
 */
// Never called. It exists to be typechecked, and it compiles with no cast,
// which is the assertion: the real context is assignable as-is.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function theRealContextFits(context: NativePlaybackContext): PlaybackContext {
  return context;
}

/**
 * Panel audio, from the wire to the loudspeaker.
 *
 * Two things here are load-bearing and neither is obvious.
 *
 * The wire is 16 kHz (`docs/voice-stream-protocol.md`) and a device output
 * stream is whatever the hardware chose — 48 kHz on every Android phone we
 * have touched. `createBuffer` takes a sample rate and does *not* honour it on
 * playback, so handing it 16 kHz samples in a 48 kHz context plays the panel
 * three times too fast. That was a real bug, caught by a human saying "it
 * talked fast", and nothing about the API suggests it.
 *
 * And barge-in is `clearBuffers()`, which drops the buffer being played as well
 * as those queued — verified in the library's C++, where it clears the whole
 * map and resets the read index. If it only dropped the queue, an interrupted
 * panelist would keep talking for one frame after being cut off.
 */
class FakeBuffer {
  readonly channels: Float32Array[] = [];

  constructor(
    readonly numberOfChannels: number,
    readonly length: number,
    readonly sampleRate: number
  ) {
    this.channels = [new Float32Array(length)];
  }

  copyToChannel(source: Float32Array, channel: number): void {
    this.channels[channel] = source;
  }
}

class FakeQueueSource {
  readonly enqueued: FakeBuffer[] = [];
  started = 0;
  startedWith: [number | undefined, number | undefined][] = [];
  dequeued: string[] = [];
  onBufferEnded:
    | ((event: { bufferId: string; isLastBufferInQueue: boolean }) => void)
    | null
    | undefined = null;

  dequeueBuffer(bufferId: string): void {
    this.dequeued.push(bufferId);
  }

  /** What the native node does when a buffer finishes playing. */
  finish(bufferId: string): void {
    this.onBufferEnded?.({ bufferId, isLastBufferInQueue: false });
  }

  /** The same, for the last buffer there is — the room going quiet. */
  drain(bufferId: string): void {
    this.onBufferEnded?.({ bufferId, isLastBufferInQueue: true });
  }
  cleared = 0;
  connectedTo: unknown = null;

  connect(destination: unknown): void {
    this.connectedTo = destination;
  }

  enqueueBuffer(buffer: FakeBuffer): string {
    this.enqueued.push(buffer);
    return String(this.enqueued.length);
  }

  clearBuffers(): void {
    this.cleared += 1;
  }

  start(when?: number, offset?: number): void {
    this.started += 1;
    this.startedWith.push([when, offset]);
  }

  stopped = 0;

  stop(): void {
    this.stopped += 1;
  }
}

class FakeContext {
  readonly destination = { id: 'speaker' };
  readonly sources: FakeQueueSource[] = [];
  readonly buffers: FakeBuffer[] = [];

  constructor(readonly sampleRate: number) {}

  createBufferQueueSource(): FakeQueueSource {
    const source = new FakeQueueSource();
    this.sources.push(source);
    return source;
  }

  createBuffer(numberOfChannels: number, length: number, sampleRate: number): FakeBuffer {
    const buffer = new FakeBuffer(numberOfChannels, length, sampleRate);
    this.buffers.push(buffer);
    return buffer;
  }
}

/** A frame of panel audio on the wire: PCM16, 16 kHz, mono. */
function frame(samples: number[]): ArrayBuffer {
  return toPcm16(new Float32Array(samples));
}

function playbackAt(hardwareRate: number) {
  const context = new FakeContext(hardwareRate);
  const playback = createPlayback({ context: context as never });

  return { context, playback, source: () => context.sources[0] };
}

describe('playing panel audio', () => {
  it('resamples the wire rate up to whatever the hardware runs at', () => {
    // The whole reason this module exists rather than the socket handing
    // buffers straight to the audio graph. Four samples at 16 kHz have to
    // become twelve at 48 kHz, or the panel sounds like a chipmunk and the
    // room stops being intimidating.
    const { playback, context } = playbackAt(48000);

    playback.enqueue(frame([0, 0.5, -0.5, 0]));

    expect(context.buffers).toHaveLength(1);
    expect(context.buffers[0].sampleRate).toBe(48000);
    expect(context.buffers[0].length).toBe(12);
  });

  it('leaves the samples alone when the hardware already runs at the wire rate', () => {
    // Not hypothetical: the recorder was asked for 16 kHz and delivered it, so
    // a device output stream at 16 kHz is plausible, and a resampler with an
    // off-by-one at ratio 1.0 would corrupt every frame on exactly those
    // devices — the hardest kind of bug to reproduce, because it depends on
    // whose phone you are holding.
    const { playback, context } = playbackAt(16000);

    playback.enqueue(frame([0, 0.5, -0.5, 0]));

    expect(context.buffers[0].length).toBe(4);
    expect(context.buffers[0].sampleRate).toBe(16000);
  });

  it('runs one source for the whole room, started before any audio arrives', () => {
    // One node, started once, fed continuously — not a node per frame. An
    // empty queue renders silence and keeps the node alive (verified in
    // `runBufferProcessor`, which zeroes the output rather than ending), so
    // starting up front is safe and removes the race where the first frame of
    // the first question arrives before playback is running.
    const { playback, source, context } = playbackAt(48000);

    expect(source().started).toBe(1);
    expect(source().connectedTo).toBe(context.destination);

    playback.enqueue(frame([0.1, 0.2]));
    playback.enqueue(frame([0.3, 0.4]));

    expect(context.sources).toHaveLength(1);
    expect(source().started).toBe(1);
    expect(source().enqueued).toHaveLength(2);
  });
});

describe('barge-in', () => {
  it('drops everything queued the moment the user interrupts', () => {
    const { playback, source } = playbackAt(48000);

    playback.enqueue(frame([0.1, 0.2]));
    playback.discard();

    expect(source().cleared).toBe(1);
  });

  it('keeps playing whatever arrives after the interruption', () => {
    // The failure this guards is subtle and permanent: a discard that also
    // tore down the source would silence the panel for the rest of the
    // session. The user would interrupt once, get their answer in, and then
    // watch a room that never speaks again — which reads as the app crashing
    // rather than as a bug in barge-in.
    const { playback, source, context } = playbackAt(48000);

    playback.enqueue(frame([0.1, 0.2]));
    playback.discard();
    playback.enqueue(frame([0.3, 0.4]));

    expect(context.sources).toHaveLength(1);
    expect(source().enqueued).toHaveLength(2);
  });
});

describe('when the room ends', () => {
  it('stops the source and ignores audio that arrives afterwards', () => {
    // Frames outlive the socket — the ones already in flight when the room
    // ended. Queueing them would play a panelist's question over the top of
    // the debrief, seconds after the interrogation the user believes is over.
    const { playback, source } = playbackAt(48000);

    playback.stop();
    playback.enqueue(frame([0.1, 0.2]));

    expect(source().stopped).toBe(1);
    expect(source().enqueued).toHaveLength(0);
  });
});

describe('starting the queue', () => {
  it('passes both arguments explicitly', () => {
    /**
     * A scar from the library this stack replaced (#25): it declared
     * `start(when = 0, offset = -1)` and then threw on any offset below zero
     * — its own default failed its own guard, so a bare `start()` raised on
     * every call, surfacing only on a device as a room that opened and died.
     * The owned module has no such trap, but the interface keeps both
     * arguments and the call sites keep passing them: explicit arguments are
     * what let this suite assert the call at all.
     */
    const context = new FakeContext(16_000);
    createPlayback({ context });

    expect(context.sources[0].startedWith).toEqual([[0, 0]]);
  });
});

describe('loudness', () => {
  it('recovers the headroom the synthesiser leaves unused', () => {
    /**
     * Measured against the live vendor: their PCM peaks at exactly -6 dBFS,
     * half of full scale, which is a mastering choice on their side rather
     * than a property of the speech. On a phone that is six decibels thrown
     * away before the volume slider is even consulted — and a room runs on the
     * voice-call audio path, which is quieter than media to begin with, so the
     * loss lands on top of a quieter floor.
     *
     * It was audible before it was measured: a panel at maximum volume on a
     * device that is otherwise loud enough.
     *
     * Clamped rather than trusted. The gain is right for this vendor and this
     * measurement; a future one mastering at full scale would clip, and a
     * limiter turns that into distortion on peaks instead of samples wrapping
     * to the opposite sign, which is a click.
     */
    const context = new FakeContext(16_000);
    const playback = createPlayback({ context });

    // Full-scale positive, and half-scale — the level the vendor actually sends.
    const pcm = new Int16Array([0x7fff, 0x4000, -0x4000]);
    playback.enqueue(pcm.buffer);

    const [written] = context.buffers[0].channels;
    expect(written[0]).toBeCloseTo(1, 5); // clamped, not wrapped
    expect(written[1]).toBeCloseTo(1, 2); // half scale doubled to full
    expect(written[2]).toBeCloseTo(-1, 2);
  });
});

describe('holding buffers', () => {
  it('releases each frame once it has been played', () => {
    /**
     * A panel line is around ninety frames, so three exchanges would otherwise
     * leave the source holding two hundred and seventy buffers it has already
     * finished with — the only quantity in this client that grows without
     * bound. Rooms stopped after about three replies, with the phone dropping
     * the socket, which is what that looks like from the server.
     *
     * Released on the node's own signal rather than on a timer, because only it
     * knows when playback of a frame is actually over.
     */
    const context = new FakeContext(16_000);
    const playback = createPlayback({ context });
    const source = context.sources[0];

    playback.enqueue(new Int16Array([1, 2, 3, 4]).buffer);
    // The fake hands back "1" for the first buffer, as the node hands back an id.
    source.finish('1');

    expect(source.dequeued).toEqual(['1']);
  });
});

describe('reporting that an utterance has finished playing', () => {
  /**
   * Reported from a device: the speaking panelist "quickly takes the person out
   * of focus even when they are still speaking".
   *
   * `turn_finished` says the *server* has sent its last frame, not that the
   * phone has played it. Synthesis runs ahead of playback by design — that is
   * what makes barge-in possible at all — so the caption's speaker was being
   * released while their voice was still coming out of the loudspeaker.
   *
   * **This was an empty-queue signal until 2026-09-19, and an empty queue is
   * the wrong boundary.** Reported again: the screen ran a whole turn ahead of
   * the audio. When a presenter talks over the tail of a question the server
   * has already finished, the next panelist's frames are appended behind that
   * tail in the same queue — so the loudspeaker moves from one panelist to the
   * next *without the queue ever emptying*, and nothing downstream could tell
   * where one voice stopped and the other started.
   *
   * `mark` is that boundary, and it is exact rather than inferred. The wire
   * delivers a turn's audio frames before the `turn_finished` that closes it,
   * so the buffer queued last at that moment is the last buffer of that
   * utterance. The node already reports each buffer by id as it ends; this
   * module had been throwing the id away.
   */
  function markable() {
    const context = new FakeContext(16000);
    const played: number[] = [];
    const playback = createPlayback({
      context: context as never,
      onPlayed: () => played.push(1),
    });

    return { playback, played, source: () => context.sources[0] };
  }

  it('reports when the last buffer of the utterance has actually played', () => {
    const { playback, played, source } = markable();

    playback.enqueue(frame([0.1]));
    playback.enqueue(frame([0.2]));
    playback.mark();

    source().finish('1');
    expect(played).toEqual([]);

    source().finish('2');
    expect(played).toEqual([1]);
  });

  it('keeps two utterances apart when their audio runs back to back', () => {
    // THE BUG. The queue never empties between these two, so an
    // empty-queue signal reports once, at the end of the second — by which
    // time the screen has been wrong for a whole turn.
    const { playback, played, source } = markable();

    playback.enqueue(frame([0.1]));
    playback.mark();
    playback.enqueue(frame([0.2]));
    playback.mark();

    source().finish('1');
    expect(played).toEqual([1]);

    source().finish('2');
    expect(played).toEqual([1, 1]);
  });

  it('reports at once for an utterance that queued no audio', () => {
    // Synthesis can fail with the caption already sent. Nothing will ever
    // play, so waiting for a buffer would hold the floor for the rest of the
    // room.
    const { playback, played } = markable();

    playback.mark();

    expect(played).toEqual([1]);
  });

  it('reports at once when the audio finished before the mark arrived', () => {
    // A short utterance whose frames all played before `turn_finished`
    // crossed the network. The buffer is gone and its id will never be
    // reported again.
    const { playback, played, source } = markable();

    playback.enqueue(frame([0.1]));
    source().finish('1');

    playback.mark();

    expect(played).toEqual([1]);
  });

  it('forgets the marks of audio that was thrown away', () => {
    // Barge-in clears the queue, so the buffers those marks were waiting on
    // will never end. Left behind, the next utterance would inherit them.
    const { playback, played, source } = markable();

    playback.enqueue(frame([0.1]));
    playback.mark();
    playback.discard();

    source().finish('1');

    expect(played).toEqual([]);
  });

  it('still releases the buffer it reports on', () => {
    // The leak this callback sits beside: the node holds every buffer it has
    // played until told otherwise, and rooms died after about three replies.
    // Reporting must not quietly replace the release.
    const { playback, source } = markable();

    playback.enqueue(frame([0.1]));
    playback.mark();
    source().finish('1');

    expect(source().dequeued).toEqual(['1']);
  });

  it('works for a room that never asked to be told', () => {
    // `onPlayed` is optional, like every other callback on this seam.
    const context = new FakeContext(16000);
    const playback = createPlayback({ context: context as never });

    playback.enqueue(frame([0.1]));
    playback.mark();

    expect(() => context.sources[0].finish('1')).not.toThrow();
  });
});

describe('reporting that the loudspeaker is idle', () => {
  /**
   * Kept alongside `onPlayed`, and not the same question.
   *
   * The debrief coach has one voice and no turns to keep apart. It streams a
   * reply in chunks and never says where the reply ends, so "nothing left to
   * play" is the only signal available to it — and it is the right one, since
   * what it re-enables is the controls that speaking disabled.
   *
   * The room must never use it to decide who is speaking. That is what it was
   * used for, and it is why the screen ran a turn ahead of the audio.
   */
  it('says when the queue has emptied', () => {
    const context = new FakeContext(16000);
    const drained: number[] = [];
    const playback = createPlayback({
      context: context as never,
      onDrained: () => drained.push(1),
    });

    playback.enqueue(frame([0.1]));
    context.sources[0].drain('1');

    expect(drained).toEqual([1]);
  });

  it('says nothing for a buffer with more behind it', () => {
    const context = new FakeContext(16000);
    const drained: number[] = [];
    const playback = createPlayback({
      context: context as never,
      onDrained: () => drained.push(1),
    });

    playback.enqueue(frame([0.1]));
    playback.enqueue(frame([0.2]));
    context.sources[0].finish('1');

    expect(drained).toEqual([]);
  });
});
