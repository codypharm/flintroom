import { toPcm16 } from '../audio/pcm';
import { createCoachVoice } from './voice';

/**
 * The coach, out loud.
 *
 * Every coaching and sparring reply already comes back spoken —
 * `coaching.py:_voice` synthesises it and `CoachTurnRead.speech` carries it as
 * base64 PCM16 at the wire's 16 kHz. The client declared the field, fetched it
 * on every turn, and played none of it, so the debrief read as a chat log with
 * a microphone button. Reported from a device as *"why is it just texts and I
 * am the only one speaking"*.
 *
 * The text is the caption, not the reply. `CLAUDE.md` sets live captions as a
 * v1 accessibility floor **alongside** panel and coach speech, and the router's
 * own docstring says so: *"The reply carries text as well as audio."*
 */

class FakeBuffer {
  channel: Float32Array = new Float32Array(0) as Float32Array;

  constructor(readonly length: number, readonly sampleRate: number) {}

  copyToChannel(source: Float32Array): void {
    this.channel = source;
  }
}

class FakeQueueSource {
  readonly enqueued: FakeBuffer[] = [];
  cleared = 0;
  stopped = 0;
  onBufferEnded: ((event: { bufferId: string; isLastBufferInQueue: boolean }) => void) | null =
    null;

  connect(): void {}
  enqueueBuffer(buffer: FakeBuffer): string {
    this.enqueued.push(buffer);
    return String(this.enqueued.length);
  }
  dequeueBuffer(): void {}
  /** What the native node does: drops the buffer playing and the queue behind it. */
  clearBuffers(): void {
    this.cleared += 1;
    this.enqueued.length = 0;
  }
  start(): void {}
  stop(): void {
    this.stopped += 1;
  }
}

class FakeContext {
  readonly destination = { id: 'speaker' };
  readonly sources: FakeQueueSource[] = [];

  constructor(readonly sampleRate: number) {}

  createBufferQueueSource(): FakeQueueSource {
    const source = new FakeQueueSource();
    this.sources.push(source);
    return source;
  }

  createBuffer(_channels: number, length: number, sampleRate: number): FakeBuffer {
    return new FakeBuffer(length, sampleRate);
  }
}

/** What the server sends: PCM16 at 16 kHz, base64 because the reply is JSON. */
function spoken(samples: number[]): string {
  const bytes = new Uint8Array(toPcm16(new Float32Array(samples)));
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function voiceAt(hardwareRate: number) {
  const context = new FakeContext(hardwareRate);
  const voice = createCoachVoice({ context: context as never });

  return { voice, source: () => context.sources[0] };
}

it('speaks a streamed reply frame by frame, without silencing itself', () => {
  // #107 item 1: the SSE turn hands frames over as the vendor makes them, and
  // playback starts on the first — `begin` supersedes the previous reply once,
  // then every chunk queues behind the one before it.
  const { voice, source } = voiceAt(16_000);

  voice.begin();
  voice.playChunk(spoken([0.5, -0.5]));
  voice.playChunk(spoken([0.25]));

  expect(source().enqueued).toHaveLength(2);
  expect(source().enqueued[0].length).toBe(2);
  expect(source().enqueued[1].length).toBe(1);
});

it('a new streamed reply silences the one before it', () => {
  const { voice, source } = voiceAt(16_000);

  voice.playChunk(spoken([0.5, -0.5]));
  voice.begin();
  voice.playChunk(spoken([0.25]));

  expect(source().enqueued).toHaveLength(1);
  expect(source().enqueued[0].length).toBe(1);
});

it('says when it has gone quiet, so a screen can re-enable what speaking disables', () => {
  // The hear-again button must not be tappable over a coach mid-sentence —
  // pressing it would put two coach voices on one speaker. The drained signal
  // is how the screen knows the sentence ended.
  const quiet = jest.fn();
  const context = new FakeContext(16_000);
  const voice = createCoachVoice({ context: context as never, onQuiet: quiet });

  voice.play(spoken([0.5]));
  const source = context.sources[0];
  source.onBufferEnded?.({ bufferId: '1', isLastBufferInQueue: true });

  expect(quiet).toHaveBeenCalledTimes(1);
});


it('says the reply out loud instead of only writing it down', () => {
  const { voice, source } = voiceAt(16_000);

  voice.play(spoken([0.5, -0.5, 0.25]));

  expect(source().enqueued).toHaveLength(1);
  expect(source().enqueued[0].length).toBe(3);
});

it('stops the last answer before starting the next one', () => {
  // The turn that made autoplay safe to choose. Ask a follow-up while the
  // coach is still mid-sentence and two coach voices overlap on one speaker —
  // which is not a room, it is a fault. The room solves this as barge-in; here
  // it is simply that a reply supersedes the one it answers past.
  const { voice, source } = voiceAt(48_000);

  voice.play(spoken([0.5, -0.5]));
  voice.play(spoken([0.25]));

  // One buffer on the speaker, and it is the new one — asserted through the
  // queue rather than by counting calls to `clearBuffers`, so this survives
  // the module deciding to silence the old reply some other way.
  expect(source().enqueued).toHaveLength(1);
  expect(source().enqueued[0].length).toBe(3);
});

it('says nothing rather than throwing when a reply carries no audio', () => {
  // Not reachable through a healthy server — `coaching._voice` raises rather
  // than returning silence, so an empty field means something already went
  // wrong upstream. That is exactly when this must not become a second
  // failure: the text still says what the coach said, and the sheet the user
  // is working through is worth more than the voice reading it.
  //
  // `createBuffer(1, 0, rate)` is the specific hazard. A zero-length buffer is
  // a native call with nothing in it.
  const { voice, source } = voiceAt(48_000);

  expect(() => voice.play('')).not.toThrow();
  expect(source().enqueued).toHaveLength(0);
});

it('goes quiet for good when the screen is left', () => {
  // The debrief is a route, and a route is popped. Audio that outlived it
  // would carry the coach's voice into whatever screen came next.
  const { voice, source } = voiceAt(16_000);

  voice.stop();
  voice.play(spoken([0.5]));

  expect(source().stopped).toBe(1);
  expect(source().enqueued).toHaveLength(0);
});

it('stops mid-sentence when the presenter starts talking', () => {
  // The microphone opens on the same phone the coach is coming out of. A reply
  // still playing when recording starts is recorded, transcribed, and sent back
  // as though the user had said it — the coach answering itself, on a screen
  // whose whole grounding rule is that a turn is about the room.
  //
  // Not `stop`, which is for leaving the route: this one has to be able to
  // speak again the moment there is an answer.
  const { voice, source } = voiceAt(16_000);
  voice.play(spoken([0.5, -0.5]));

  voice.silence();
  voice.play(spoken([0.25]));

  expect(source().enqueued).toHaveLength(1);
});
