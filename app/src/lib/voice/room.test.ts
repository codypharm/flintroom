import { fromPcm16, toPcm16 } from '../audio/pcm';
import { joinRoom } from './room';

/**
 * The three pieces, wired.
 *
 * Nothing here has logic of its own — `connection`, `playback` and `uplink` are
 * each tested against their own fakes. What this file is about is *ordering*,
 * which is the only thing wiring can get wrong, and which none of those three
 * can observe alone.
 */
class FakeSocket {
  static last: FakeSocket | null = null;

  binaryType = '';
  readonly sent: ArrayBuffer[] = [];

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.last = this;
  }

  send(data: ArrayBuffer): void {
    this.sent.push(data);
  }

  /**
   * Deferred, as a real socket defers it.
   *
   * `close()` begins a closing handshake; `onclose` arrives when the peer
   * answers, or when the platform gives up waiting. Firing it synchronously
   * here would let a test pass that the network would fail — specifically, it
   * would hide how long the microphone stays live after the user leaves.
   */
  close(code = 1000): void {
    queueMicrotask(() => this.onclose?.({ code }));
  }

  /** The server closing, which does arrive as an event out of nowhere. */
  closedByServer(code: number): void {
    this.onclose?.({ code });
  }

  receive(data: unknown): void {
    this.onmessage?.({ data });
  }
}

/** Every teardown step, in the order it happened. The point of these tests. */
let order: string[] = [];

class FakeQueueSource {
  readonly enqueued: unknown[] = [];
  readonly dequeued: string[] = [];

  onBufferEnded:
    | ((event: { bufferId: string; isLastBufferInQueue: boolean }) => void)
    | null = null;

  connect(): void {}
  enqueueBuffer(buffer: unknown): string {
    this.enqueued.push(buffer);
    return '1';
  }
  dequeueBuffer(bufferId: string): void {
    this.dequeued.push(bufferId);
  }
  /** The loudspeaker actually going quiet — the last buffer played out. */
  drain(): void {
    this.onBufferEnded?.({ bufferId: '1', isLastBufferInQueue: true });
  }
  clearBuffers(): void {
    order.push('playback.discard');
  }
  start(): void {}
  stop(): void {
    order.push('playback.stop');
  }
}

class FakeContext {
  readonly destination = {};
  readonly sampleRate = 48000;
  source: FakeQueueSource | null = null;

  createBufferQueueSource(): FakeQueueSource {
    this.source = new FakeQueueSource();
    return this.source;
  }

  createBuffer(_channels: number, length: number) {
    return { length, copyToChannel: () => {} };
  }
}

class FakeRecorder {
  private callback: ((event: { buffer: unknown; numFrames: number }) => void) | null = null;

  onAudioReady(_options: unknown, callback: (event: { buffer: unknown; numFrames: number }) => void) {
    this.callback = callback;
  }

  clearOnAudioReady(): void {
    order.push('uplink.stop');
    this.callback = null;
  }

  speak(samples: number[], sampleRate = 16000): void {
    const data = new Float32Array(samples);
    this.callback?.({
      buffer: { getChannelData: () => data, sampleRate },
      numFrames: data.length,
    });
  }
}

async function joined() {
  order = [];

  const context = new FakeContext();
  const recorder = new FakeRecorder();
  const endings: string[] = [];

  const joining = joinRoom({
    url: 'wss://api.example/v1/sessions/room-1/stream',
    ticket: 'tk_abc',
    context: context as never,
    recorder: recorder as never,
    onEnding: (ending) => {
      order.push('ending');
      endings.push(ending);
    },
    socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
  });

  const socket = FakeSocket.last!;
  socket.onopen?.();

  return { room: await joining, socket, context, recorder, endings };
}

describe('a room in one piece', () => {
  it('plays what the panel says', async () => {
    const { socket, context } = await joined();

    socket.receive(toPcm16(new Float32Array([0.1, 0.2])));

    expect(context.source!.enqueued).toHaveLength(1);
  });

  it('sends what the user says', async () => {
    const { socket, recorder } = await joined();

    recorder.speak([0.25, -0.25]);

    expect(socket.sent).toHaveLength(1);
    expect(fromPcm16(socket.sent[0])).toHaveLength(2);
  });

  it('drops buffered panel audio when the user barges in', async () => {
    const { socket } = await joined();

    socket.receive(JSON.stringify({ type: 'discard_playback' }));

    expect(order).toContain('playback.discard');
  });
});

describe('when the room ends', () => {
  it('stops listening before it stops playing, and reports last', async () => {
    // Order, not merely occurrence. The microphone has to go first: a buffer
    // captured after the socket has gone is audio of the user talking to
    // nobody, and `Connection.send` swallowing it is a guard, not a design.
    // Playback stops next so a frame already in flight cannot be queued behind
    // the ending. The screen is told last, because by then both are true and
    // it can navigate to the debrief without racing a teardown.
    const { socket } = await joined();

    socket.closedByServer(1000);

    expect(order).toEqual(['uplink.stop', 'playback.stop', 'ending']);
  });

  it('stops the microphone the instant the user leaves, not when the network agrees', async () => {
    // `close()` starts a handshake; `onclose` arrives whenever the peer
    // answers. Waiting for it leaves the microphone live across a network
    // round trip after the user has said stop — on a phone lying face-up on a
    // desk, in an app whose whole premise is that it is listening. The
    // recording keeps running for as long as the network feels like taking.
    const { room } = await joined();

    room.leave();

    expect(order).toEqual(['uplink.stop', 'playback.stop', 'ending']);
  });

  it('leaves when the microphone cannot deliver the rate the wire needs', async () => {
    // The room is unusable — the panel would hear the user at a third speed —
    // so it ends rather than running on. It costs the user nothing: ticks are
    // whole fifteen-second units charged in arrears, and this is detected on
    // the very first buffer.
    const { recorder, endings } = await joined();

    recorder.speak([0.1], 48000);
    await Promise.resolve();

    expect(order).toContain('playback.stop');
    expect(endings).toEqual(['ended']);
  });

  it('does not tear down twice when the close it asked for comes back', async () => {
    // Leaving produces both paths: the local teardown, and then the socket's
    // own close event a moment later. The second must be silent, or the screen
    // is told the room ended after it has already navigated away from it.
    const { room } = await joined();

    room.leave();
    await Promise.resolve();

    expect(order).toEqual(['uplink.stop', 'playback.stop', 'ending']);
  });
});

describe('handing the floor back', () => {
  /**
   * Reported from a device: the speaking panelist "quickly takes the person out
   * of focus even when they are still speaking".
   *
   * Two signals arrive and neither is the answer on its own. `turn_finished`
   * says the server sent its last frame — but synthesis runs ahead of playback,
   * which is what makes barge-in possible, so seconds of the panelist's voice
   * are still queued on the phone. An empty queue says nothing is left to play
   * — but that is also what a network stall looks like mid-sentence, which
   * would invite the presenter to talk over the end of a question.
   *
   * Together they are exact, and this is the only place both can be seen.
   */
  async function speaking() {
    const floor: string[] = [];
    const context = new FakeContext();
    const recorder = new FakeRecorder();

    const joining = joinRoom({
      url: 'wss://api.example/v1/sessions/room-1/stream',
      ticket: 'tk_abc',
      context: context as never,
      recorder: recorder as never,
      onTurnFinished: () => floor.push('yours'),
      onDiscardPlayback: () => floor.push('interrupted'),
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });

    const socket = FakeSocket.last!;
    socket.onopen?.();
    const room = await joining;

    // A panelist speaks: one frame of their voice arrives and is queued.
    socket.receive(toPcm16(new Float32Array([0.1, 0.2])));

    return { room, socket, floor, source: () => context.source! };
  }

  it('waits for the audio to finish, not just for the server to stop sending', () => {
    // THE BUG. Acting here put the speaker down mid-sentence.
    return speaking().then(({ socket, floor }) => {
      socket.receive(JSON.stringify({ type: 'turn_finished' }));

      expect(floor).toEqual([]);
    });
  });

  it('hands it over once the last frame has actually played', () => {
    return speaking().then(({ socket, floor, source }) => {
      socket.receive(JSON.stringify({ type: 'turn_finished' }));
      source().drain();

      expect(floor).toEqual(['yours']);
    });
  });

  it('does not hand it over on a stall the server has not finished', () => {
    // The queue draining mid-utterance is the network, not the end of a turn.
    return speaking().then(({ socket, floor, source }) => {
      source().drain();

      expect(floor).toEqual([]);

      socket.receive(JSON.stringify({ type: 'turn_finished' }));
      expect(floor).toEqual(['yours']);
    });
  });

  it('hands it over exactly once', () => {
    // Both signals can arrive more than once — a stalled queue drains, refills
    // and drains again. The floor may only be given back for one of them.
    return speaking().then(({ socket, floor, source }) => {
      socket.receive(JSON.stringify({ type: 'turn_finished' }));
      source().drain();
      source().drain();

      expect(floor).toEqual(['yours']);
    });
  });

  it('puts an interrupted panelist down even though no turn finishes', () => {
    // A cancelled turn deliberately never announces the floor — the person
    // holding it is already talking. Without this the panelist stays lit for
    // the rest of the room.
    return speaking().then(({ socket, floor }) => {
      socket.receive(JSON.stringify({ type: 'discard_playback' }));

      expect(floor).toEqual(['interrupted']);
    });
  });
});
