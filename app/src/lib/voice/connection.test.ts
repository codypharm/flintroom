import { openConnection, type PanelLine } from './connection';

/**
 * The client half of `docs/voice-stream-protocol.md`.
 *
 * This is the only code that decides what a frame off the wire means, so a
 * mistake here is a live interrogation that mishears the room: audio played as
 * if it were a caption, a barge-in ignored, or a ticket refusal presented to
 * the user as a crash. The backend half of this protocol is already tested
 * against the same document; these are the assertions from the other end.
 *
 * Driven through a fake socket rather than a real one. The behaviour under test
 * is the *protocol* — which frame means what, which close code means what — and
 * that is decided entirely by what arrives, not by how it travelled.
 */
class FakeSocket {
  static created: FakeSocket[] = [];

  static get last(): FakeSocket | null {
    return FakeSocket.created[FakeSocket.created.length - 1] ?? null;
  }

  binaryType = '';
  readonly sent: unknown[] = [];
  closed: { code?: number; reason?: string } | null = null;

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.created.push(this);
  }

  send(data: unknown): void {
    this.sent.push(data);
  }

  close(code?: number, reason?: string): void {
    this.closed = { code, reason };
  }

  /** What the transport is really made of: frames arriving from somewhere. */
  receive(data: unknown): void {
    this.onmessage?.({ data });
  }
}

const factory = (url: string) => new FakeSocket(url) as unknown as WebSocket;

beforeEach(() => {
  FakeSocket.created = [];
});

describe('opening a room', () => {
  it('connects to the room with the ticket, and waits for the socket to open', async () => {
    // The ticket travels in the query string because a browser cannot set
    // headers on a WebSocket handshake, and `CLAUDE.md` forbids mobile-only
    // assumptions a web client would later have to unpick. It is single-use
    // and worth exactly one room, which is what makes a logged query string
    // survivable.
    const opening = openConnection({
      url: 'wss://api.example/v1/sessions/room-1/stream',
      ticket: 'tk_abc',
      socketFactory: factory,
    });

    const socket = FakeSocket.last!;
    expect(socket.url).toBe(
      'wss://api.example/v1/sessions/room-1/stream?ticket=tk_abc'
    );

    // Resolving on construction would hand the caller a socket that cannot yet
    // carry audio: frames sent before `onopen` are dropped by the platform,
    // silently, which would show up as a room that ignores its first sentence.
    socket.onopen?.();

    await expect(opening).resolves.toBeDefined();
  });
});

/** Opens a connection and hands back the fake behind it, already open. */
async function connected(handlers: Partial<Parameters<typeof openConnection>[0]> = {}) {
  const opening = openConnection({
    url: 'wss://api.example/v1/sessions/room-1/stream',
    ticket: 'tk_abc',
    socketFactory: factory,
    ...handlers,
  });

  const socket = FakeSocket.last!;
  socket.onopen?.();

  return { connection: await opening, socket };
}

describe('frames arriving', () => {
  it('delivers panel audio as an ArrayBuffer', async () => {
    // React Native's WebSocket hands back a Blob unless told otherwise, and a
    // Blob cannot be read synchronously — which in the playback path means
    // every frame of the panel's voice takes a trip through an async read
    // before it can be queued. Asking for `arraybuffer` up front is what keeps
    // the decode out of the latency path (Open Risk #3).
    const frames: ArrayBuffer[] = [];
    const { socket } = await connected({ onAudio: (pcm) => frames.push(pcm) });

    expect(socket.binaryType).toBe('arraybuffer');

    const panel = new ArrayBuffer(320);
    socket.receive(panel);

    expect(frames).toEqual([panel]);
  });

  it('ignores a control message it does not recognise, and keeps the room alive', async () => {
    // The mirror of the server ignoring client text frames, and for the same
    // reason: a control message added to the protocol later must not be able to
    // kill a live interrogation by arriving at a build that predates it. This
    // is what makes the wire extensible without a forced app update, and phones
    // hold old builds for a long time.
    const lines: PanelLine[] = [];
    const { socket } = await connected({ onTranscript: (line) => lines.push(line) });

    expect(() => socket.receive(JSON.stringify({ type: 'room_temperature', value: 3 }))).not.toThrow();

    socket.receive(
      JSON.stringify({ type: 'transcript', text: 'Still here.', speaker: 'cfo' })
    );
    expect(lines).toEqual([{ speaker: 'cfo', text: 'Still here.' }]);
  });

  it('survives a text frame that is not JSON at all', async () => {
    // Nothing in the protocol sends one, which is exactly why it is worth a
    // test: an unparsed frame throwing inside `onmessage` takes out the handler
    // for every frame after it, so one malformed byte would silence the panel
    // for the rest of the session rather than for one message.
    const lines: PanelLine[] = [];
    const { socket } = await connected({ onTranscript: (line) => lines.push(line) });

    expect(() => socket.receive('<html>502 Bad Gateway</html>')).not.toThrow();

    socket.receive(
      JSON.stringify({ type: 'transcript', text: 'Still here.', speaker: 'cfo' })
    );
    expect(lines).toEqual([{ speaker: 'cfo', text: 'Still here.' }]);
  });

  it('delivers a transcript as the panel line to caption, with who said it', async () => {
    // Captions are a v1 accessibility requirement, not a convenience: a
    // voice-only interrogation offers a deaf or hard-of-hearing user nothing.
    // The wire carries whole utterances, so this is a finished line, not a
    // token to append.
    //
    // The speaker comes with it because the screen draws one tray per seated
    // archetype and develops whoever holds the floor (`Product.md` §3.4) —
    // which it cannot do from text alone.
    const lines: PanelLine[] = [];
    const { socket } = await connected({ onTranscript: (line) => lines.push(line) });

    socket.receive(
      JSON.stringify({
        type: 'transcript',
        text: 'Where does that margin come from?',
        speaker: 'cfo',
      })
    );

    expect(lines).toEqual([
      { speaker: 'cfo', text: 'Where does that margin come from?' },
    ]);
  });

  it('ignores a transcript frame with no speaker on it', async () => {
    // Same reasoning as the missing text below, and the same consequence: the
    // speaker picks which tray develops, so an undefined one would either
    // develop nobody or throw inside a render while a room is live. A frame
    // that cannot say who spoke is malformed, and the room carries on without
    // it.
    const lines: PanelLine[] = [];
    const { socket } = await connected({ onTranscript: (line) => lines.push(line) });

    socket.receive(JSON.stringify({ type: 'transcript', text: 'And the margin?' }));

    expect(lines).toStrictEqual([]);
  });

  it('hands the floor back when the panel has finished its turn', async () => {
    // Carried rather than inferred. Nothing else marks where an utterance
    // ends — the caption arrives before its audio, and audio is frames that
    // stop — so a client guessing from a gap in arrivals would invite the
    // presenter to speak over the end of a question during a network stall,
    // and manufacture an accidental barge-in.
    const floor: number[] = [];
    const { socket } = await connected({ onTurnFinished: () => floor.push(1) });

    socket.receive(JSON.stringify({ type: 'turn_finished' }));

    expect(floor).toHaveLength(1);
  });

  it('ignores a transcript frame carrying no text', async () => {
    // Found by the typechecker rather than by thinking of it. The caption is
    // rendered directly, so an undefined text would put the string "undefined"
    // on screen under a panelist's face — and, being a caption, on screen for
    // precisely the user who cannot hear that it is wrong.
    const lines: PanelLine[] = [];
    const { socket } = await connected({ onTranscript: (line) => lines.push(line) });

    socket.receive(JSON.stringify({ type: 'transcript', speaker: 'cfo' }));

    // `toStrictEqual`, not `toEqual`: the latter ignores undefined entries in
    // an array, so it cannot tell "nothing was captioned" from "undefined was
    // captioned" — which is exactly the distinction under test.
    expect(lines).toStrictEqual([]);
  });

  it('raises barge-in the moment the user talks over a panelist', async () => {
    // Audio runs ahead of playback, so when the user interrupts, the device is
    // still holding frames of a sentence that will never be finished. Playing
    // them out is the room failing to be interruptible — the single feature the
    // voice provider was chosen for (`Product.md` §5.1).
    const discards: number[] = [];
    const { socket } = await connected({ onDiscardPlayback: () => discards.push(1) });

    socket.receive(JSON.stringify({ type: 'discard_playback' }));

    expect(discards).toHaveLength(1);
  });
});

describe('sending what the user says', () => {
  it('sends user audio as a binary frame, untouched', async () => {
    // The relay transcodes nothing: what goes in here is what reaches the
    // voice provider. No base64 on this leg either — their protocol requires
    // it, ours does not, and paying the 33% expansion on a phone's uplink
    // would be bandwidth spent on somebody else's requirement.
    const { connection, socket } = await connected();
    const speech = new ArrayBuffer(640);

    connection.send(speech);

    expect(socket.sent).toEqual([speech]);
  });

  it('drops audio offered after the room ended, rather than throwing', async () => {
    // The recorder does not stop the instant the socket does. Its callback is
    // already scheduled and fires once or twice more, and `send` on a closed
    // socket throws — which would surface as a crash during the hand-off to
    // the debrief, at the exact moment the user is being told things went
    // fine. The frames themselves are worthless: there is nothing left to
    // send them to.
    const { connection, socket } = await connected();
    socket.onclose?.({ code: 1000, reason: '' });

    expect(() => connection.send(new ArrayBuffer(640))).not.toThrow();
    expect(socket.sent).toEqual([]);
  });
});

describe('the room ending', () => {
  it('reports a normal close as the room having ended', async () => {
    // Minutes are charged in arrears, so by the time a close arrives the ledger
    // is already correct and nothing is owed back. The client never reconciles
    // anything; it goes to the debrief.
    const endings: string[] = [];
    const { socket } = await connected({ onEnding: (ending) => endings.push(ending) });

    socket.onclose?.({ code: 1000, reason: '' });

    expect(endings).toEqual(['ended']);
  });

  it('distinguishes an upstream failure, which is still an ending', async () => {
    // Worth telling apart from a normal close only because the debrief can say
    // something honest about a room that broke. It is not an error path: the
    // refund has already happened, in full, before this code arrived. And the
    // close code never names the vendor — that is an implementation detail
    // which goes stale the moment the voice provider is swapped.
    const endings: string[] = [];
    const { socket } = await connected({ onEnding: (ending) => endings.push(ending) });

    socket.onclose?.({ code: 4502, reason: '' });

    expect(endings).toEqual(['upstream_failure']);
  });

  it('tells a dropped connection apart from a room that was ended', async () => {
    // 1006 is what a phone leaving a tunnel produces. This used to map to
    // 'ended', reasoning that the ledger was already correct and the user had
    // mentally left — and then a room dropped under the architect mid-sentence
    // and the app opened the debrief as if they had finished. The room *is*
    // over (the server settles a dead line), but the screen owes the person a
    // sentence about why before it moves on, and that sentence needs the two
    // cases told apart. Reconnecting is a separate, designed feature (#100);
    // this only stops the app from pretending the ending was chosen.
    const endings: string[] = [];
    const { socket } = await connected({ onEnding: (ending) => endings.push(ending) });

    socket.onclose?.({ code: 1006, reason: '' });

    expect(endings).toEqual(['dropped']);
  });

  it('fails the open when the ticket is refused, rather than waiting forever', async () => {
    // The server redeems the ticket *before* accepting, so an unauthorised
    // caller never reaches an open socket — which means `onopen` never fires
    // and a promise waiting for it never settles. Left unhandled this is not a
    // visible bug, it is a screen that sits on a spinner until the user gives
    // up, which is the worst possible presentation of "mint a new session".
    const opening = openConnection({
      url: 'wss://api.example/v1/sessions/room-1/stream',
      ticket: 'tk_spent',
      socketFactory: factory,
    });

    FakeSocket.last!.onclose?.({ code: 4401, reason: '' });

    // 4401 is deliberately identical for expired, spent, and wrong-room. A
    // caller holding a string it should not have learns nothing by presenting
    // it — the same silence the HTTP layer keeps by answering 404 rather
    // than 403.
    await expect(opening).rejects.toMatchObject({ ending: 'ticket_rejected' });
  });

  it('does not reconnect, on any close code', async () => {
    // Reconnecting is wrong here for a reason that is not obvious: the ticket
    // is single-use and worth exactly one room, so a retry could not
    // reauthenticate even if it wanted to. Beneath that is a product argument —
    // an interrogation the user has mentally left should not resume — and
    // beneath that a billing one: the ledger is already correct, and a silent
    // reconnect would start charging again for a room nobody is in.
    const { socket } = await connected();

    socket.onclose?.({ code: 4502, reason: '' });
    await Promise.resolve();

    expect(FakeSocket.created).toHaveLength(1);
  });
});

describe('what the room says it is doing', () => {
  /**
   * #24. Five things look like silence to somebody in a room that has gone
   * quiet — it is thinking, it did not hear them, it is waiting for more, it
   * failed, or it is about to end. Only the server can tell the first two
   * apart, because only the server sees a final arrive.
   */
  it('carries the room state through', async () => {
    const said: string[] = [];
    const { socket } = await connected({ onAttending: (state) => said.push(state) });

    socket.receive(JSON.stringify({ type: 'attending', state: 'working' }));
    socket.receive(JSON.stringify({ type: 'attending', state: 'listening' }));

    expect(said).toEqual(['working', 'listening']);
  });

  it('carries the room having heard nothing at all', async () => {
    // #77. The server split "it did not hear them" in two: a final that never
    // arrived, and a microphone that has never delivered anything. Those want
    // different things from the presenter — say it again, against check the
    // phone — and `listening` was quietly claiming both.
    const said: string[] = [];
    const { socket } = await connected({ onAttending: (state) => said.push(state) });

    socket.receive(JSON.stringify({ type: 'attending', state: 'unheard' }));

    expect(said).toEqual(['unheard']);
  });

  it('ignores a state it does not recognise', async () => {
    // The server may learn a fourth value before the phone does — #24 already
    // has an idle warning queued behind it. An unknown value must leave the
    // screen on the last one it understood rather than blanking it.
    const said: string[] = [];
    const { socket } = await connected({ onAttending: (state) => said.push(state) });

    socket.receive(JSON.stringify({ type: 'attending', state: 'brooding' }));

    expect(said).toEqual([]);
  });

  it('ignores a state message with nothing in it', async () => {
    const said: string[] = [];
    const { socket } = await connected({ onAttending: (state) => said.push(state) });

    socket.receive(JSON.stringify({ type: 'attending' }));

    expect(said).toEqual([]);
  });
});

describe('how the panel is receiving it', () => {
  /**
   * #74, and the phone cannot work it out for itself.
   *
   * The band is read from the routing reason on panel lines — the Auditor
   * having caught a figure that moved — and the routing reason never goes over
   * this socket. So unlike a caption there is nothing here the device could
   * have derived, and unlike the sound bar there is no local signal to fall
   * back on.
   */
  it('carries the room temperature through', async () => {
    const read: string[] = [];
    const { socket } = await connected({ onTemperature: (state) => read.push(state) });

    socket.receive(JSON.stringify({ type: 'temperature', state: 'losing_the_room' }));
    socket.receive(JSON.stringify({ type: 'temperature', state: 'skeptical' }));

    expect(read).toEqual(['losing_the_room', 'skeptical']);
  });

  it('ignores a band it does not recognise', async () => {
    // The scale is `CLAUDE.md`'s and it is fixed, but a server ahead of a phone
    // is the ordinary case for a shipped app. An unknown band must leave the
    // ambient ground on the last one this build understood — blanking it would
    // be the screen going dark mid-room.
    const read: string[] = [];
    const { socket } = await connected({ onTemperature: (state) => read.push(state) });

    socket.receive(JSON.stringify({ type: 'temperature', state: 'investable' }));

    expect(read).toEqual([]);
  });

  it('ignores a band message with nothing in it', async () => {
    const read: string[] = [];
    const { socket } = await connected({ onTemperature: (state) => read.push(state) });

    socket.receive(JSON.stringify({ type: 'temperature' }));

    expect(read).toEqual([]);
  });
});


describe('who is about to challenge', () => {
  /**
   * #75, and `Product.md` §3.4's second half — the first was speaker identity.
   *
   * The floor is assigned from a partial while the presenter is still talking,
   * and composition plus synthesis then take a measured ~1.2s before a word is
   * audible. The name existed that whole time with nothing carrying it.
   *
   * **Nothing on this device can derive it**, like the temperature band above:
   * the decision is the Auditor's finding or the routing model's, and neither
   * crosses this socket.
   */
  it('carries who is about to take the floor', async () => {
    const read: string[] = [];
    const { socket } = await connected({ onChallenging: (name) => read.push(name) });

    socket.receive(JSON.stringify({ type: 'challenging', archetype: 'cfo' }));

    expect(read).toEqual(['cfo']);
  });

  it('ignores an announcement naming nobody', async () => {
    // Dropped rather than rendered, like a transcript missing a half. A tray
    // cannot develop for `undefined`, and the room carries on: the next thing
    // to arrive is the caption, which says who spoke either way.
    const read: string[] = [];
    const { socket } = await connected({ onChallenging: (name) => read.push(name) });

    socket.receive(JSON.stringify({ type: 'challenging' }));

    expect(read).toEqual([]);
  });

  it('passes a name this build has never heard of straight through', async () => {
    // Deliberately unlike the temperature band, which is checked against a
    // fixed vocabulary. Archetype names are not fixed — Pro users author their
    // own, and the catalogue grows without an app release — so a name the
    // screen cannot resolve to a seat is the screen's problem to ignore, not
    // the socket's to withhold.
    const read: string[] = [];
    const { socket } = await connected({ onChallenging: (name) => read.push(name) });

    socket.receive(JSON.stringify({ type: 'challenging', archetype: 'my_own_cfo' }));

    expect(read).toEqual(['my_own_cfo']);
  });
});
