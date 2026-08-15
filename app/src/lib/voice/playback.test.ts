import type { AudioContext } from 'react-native-audio-api';

import { toPcm16 } from '../audio/pcm';
import { createPlayback, type PlaybackContext } from './playback';

/**
 * The fake below is only worth anything if the real context satisfies the same
 * shape, so the typechecker is asked directly. A `type` import, so nothing
 * native is loaded to run the tests — the assertion is erased entirely.
 *
 * Without this the structural interface could drift from the library it
 * describes and every test here would keep passing, which is the standard way
 * a suite of green tests ends up describing a module that no longer works.
 */
// Never called. It exists to be typechecked, and it compiles with no cast,
// which is the assertion: the real `AudioContext` is assignable as-is.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function theRealContextFits(context: AudioContext): PlaybackContext {
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

  start(): void {
    this.started += 1;
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
