/**
 * The socket that carries a live interrogation.
 *
 * Implements the client half of `docs/voice-stream-protocol.md`. Everything
 * about which frame means what lives here, so the screen above it never has to
 * inspect a payload and the audio layer never has to know there is a network.
 */

/**
 * Why the room ended.
 *
 * Every one of these is an ending rather than an error. A room that broke
 * upstream is refunded in full before the socket closes, and minutes are
 * charged in arrears, so there is never anything for the client to reconcile —
 * only somewhere to go next.
 */
export type Ending =
  /** Normal close, or the connection simply dropped. Go to the debrief. */
  | 'ended'
  /** Ticket invalid, expired, spent, or for another room. Mint a new session. */
  | 'ticket_rejected'
  /** The room ended on an upstream failure, already refunded. Go to debrief. */
  | 'upstream_failure';

/**
 * A room that closed before it opened.
 *
 * Carries the `ending` so a caller can tell "mint a new session" from "the
 * provider is down" without matching on a message string.
 */
export class RoomNotOpened extends Error {
  constructor(readonly ending: Ending) {
    super(`The room closed before it opened: ${ending}`);
    this.name = 'RoomNotOpened';
  }
}

/**
 * One finished panel utterance, and who said it.
 *
 * The pair travels together because they arrive together — one utterance is
 * one caption. Splitting them would hand the screen a synchronisation problem
 * invented for nothing.
 *
 * `speaker` is the archetype's name as `POST /v1/sessions` returned it in
 * `archetypes`, so a caption can be matched to a seat without translating
 * between two vocabularies.
 */
/**
 * The three things the room may be doing, and no more.
 *
 * Deliberately silent about a panelist speaking: the caption and
 * `turn_finished` already carry that, and a second source for one fact is what
 * took a panelist off the screen mid-sentence.
 */
export type Attending = 'listening' | 'heard' | 'working';

/** Every value this build understands. Anything else is dropped, not rendered. */
const ATTENDING: readonly Attending[] = ['listening', 'heard', 'working'];

export interface PanelLine {
  speaker: string;
  text: string;
}

/** Builds the socket. Injected so tests need no network, and no fake globals. */
export type SocketFactory = (url: string) => WebSocket;

export interface ConnectionOptions {
  /** The room's stream endpoint, without the ticket. */
  url: string;
  /** Single-use, seconds-long, and worth exactly one room. */
  ticket: string;
  /** Panel audio, PCM16 16 kHz mono, to be played as received. */
  onAudio?: (pcm: ArrayBuffer) => void;
  /** A finished panel utterance, to caption. Never the user's own speech. */
  onTranscript?: (line: PanelLine) => void;
  /**
   * The panel has stopped and the floor is the presenter's.
   *
   * Carried on the wire rather than inferred here, and that is the point: the
   * caption arrives *before* its audio and audio is frames that simply stop,
   * so a client watching for a gap in arrivals would be guessing about the
   * network. A two-second stall would invite the presenter to speak over the
   * end of a question, and the room would have manufactured a barge-in nobody
   * meant.
   *
   * Not raised when barge-in cuts a turn short: `onDiscardPlayback` has
   * already said the presenter took the floor, and handing it to somebody
   * standing on it reads as a room that has lost track.
   */
  onTurnFinished?: () => void;
  /**
   * What the room is doing with the floor, while the floor is the presenter's.
   *
   * #24. Five things look like silence to somebody in a room that has gone
   * quiet — it is thinking, it did not hear them, it is waiting for more, it
   * failed, or it is about to end — and after a day of testing the middle of
   * that list was reported as the panel being broken.
   *
   * **Reported rather than inferred, because only the server can answer it.**
   * A final arriving is invisible here, so any timer on this side would be
   * racing a network and would be wrong in exactly the case that matters.
   */
  onAttending?: (state: Attending) => void;
  /** Barge-in: drop everything buffered and unplayed, immediately. */
  onDiscardPlayback?: () => void;
  /** The room is over, and why. Called once. */
  onEnding?: (ending: Ending) => void;
  socketFactory?: SocketFactory;
}

export interface Connection {
  /** User audio, PCM16 16 kHz mono. Ignored once the room has ended. */
  send(pcm: ArrayBuffer): void;
  close(): void;
}

/**
 * A close code, as an ending.
 *
 * Anything unrecognised — 1006 from a phone leaving a tunnel, or a code added
 * to the protocol after this build shipped — is `ended`. That is the safe
 * default in both directions: it sends the user to the debrief with whatever
 * was said, and the ledger needs nothing, because minutes are charged in
 * arrears and an upstream failure is refunded before the socket closes.
 */
function endingFor(code: number): Ending {
  if (code === 4401) {
    return 'ticket_rejected';
  }
  if (code === 4502) {
    return 'upstream_failure';
  }

  return 'ended';
}

export function openConnection(options: ConnectionOptions): Promise<Connection> {
  const create = options.socketFactory ?? ((url: string) => new WebSocket(url));

  // Encoded even though it is currently a no-op: the server mints tickets with
  // `secrets.token_urlsafe`, whose alphabet is URL-safe by construction. That
  // is a property of the *server's* choice of generator, though, and this end
  // would fail silently and unauthenticatedly if it ever changed.
  const socket = create(`${options.url}?ticket=${encodeURIComponent(options.ticket)}`);

  // Before anything can arrive. React Native defaults to `blob`, which cannot
  // be read synchronously, so every frame of panel audio would take an async
  // hop before reaching the speaker.
  socket.binaryType = 'arraybuffer';

  socket.onmessage = (event: { data: unknown }) => {
    if (event.data instanceof ArrayBuffer) {
      options.onAudio?.(event.data);
      return;
    }

    let control: {
      type?: string;
      text?: string;
      speaker?: string;
      state?: string;
    };
    try {
      control = JSON.parse(event.data as string);
    } catch {
      // Deliberately without the payload. A control frame carries panel
      // transcript text, and `CLAUDE.md` forbids that in logs — unlike a
      // credential it cannot be caught by key-name redaction, so the only
      // thing keeping it out is nobody passing it. That a frame was
      // unparsable is the whole diagnostic; its contents are not ours to
      // print.
      console.warn('voice: discarded an unparsable control frame');
      return;
    }

    if (control.type === 'transcript') {
      // A transcript missing either half is not a caption, it is a malformed
      // frame, and it is dropped for the same reason an unknown type is: the
      // room carries on. Both halves are required because both are rendered —
      // the text as the line, the speaker as the tray that develops — and a
      // missing one would either print "undefined" to the person who cannot
      // hear that it is wrong, or develop nobody.
      if (control.text !== undefined && control.speaker !== undefined) {
        options.onTranscript?.({ speaker: control.speaker, text: control.text });
      }
    } else if (control.type === 'attending') {
      // Checked against what this build knows rather than passed through. The
      // server may learn a fourth value first — #24 has an idle warning queued
      // behind this — and an unrecognised one must leave the screen showing the
      // last state it understood rather than blanking it.
      if (ATTENDING.includes(control.state as Attending)) {
        options.onAttending?.(control.state as Attending);
      }
    } else if (control.type === 'turn_finished') {
      options.onTurnFinished?.();
    } else if (control.type === 'discard_playback') {
      options.onDiscardPlayback?.();
    }
  };

  return new Promise((resolve, reject) => {
    let open = false;

    socket.onopen = () => {
      open = true;

      resolve({
        // Guarded rather than trusted. The recorder's callback is already
        // scheduled when the socket goes, so a frame or two always arrives
        // after the end; `send` on a closed socket throws.
        send: (pcm) => {
          if (open) {
            socket.send(pcm);
          }
        },
        close: () => socket.close(),
      });
    };

    // One report per room, and which one depends on whether the caller ever
    // got a connection to hold. Before `onopen` the promise is the only thing
    // listening, and a pending promise is a screen stuck on a spinner; after
    // it, the promise is long settled and `onEnding` is the only way back.
    socket.onclose = (event: { code: number }) => {
      const ending = endingFor(event.code);
      const wasOpen = open;
      open = false;

      if (wasOpen) {
        options.onEnding?.(ending);
      } else {
        reject(new RoomNotOpened(ending));
      }
    };
  });
}
