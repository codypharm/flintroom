import { openConnection, type Ending, type SocketFactory } from './connection';
import { createPlayback, type PlaybackContext } from './playback';
import { createUplink, type UplinkRecorder } from './uplink';

/**
 * A live interrogation, in one object.
 *
 * The socket, the loudspeaker and the microphone, joined. It holds no protocol
 * knowledge of its own — each of the three enforces its own half of
 * `docs/voice-stream-protocol.md` — and exists so that the screen above deals
 * with a room rather than with three lifecycles it would have to keep in step.
 */
export interface RoomOptions {
  /** The room's stream endpoint, without the ticket. */
  url: string;
  ticket: string;
  /** Already running, and already routed to the loudspeaker on Android. */
  context: PlaybackContext;
  /**
   * Permission already granted, and **not yet started**.
   *
   * `joinRoom` registers `onAudioReady` as it builds the uplink, and capture
   * has to begin after that — a recorder started first delivers into a callback
   * nobody has registered, which fails as silence rather than as an error. The
   * caller starts it once this resolves.
   */
  recorder: UplinkRecorder;
  /** A finished panel utterance, to caption. */
  onTranscript?: (text: string) => void;
  /** The room is over, and why. Called once, after everything is torn down. */
  onEnding?: (ending: Ending) => void;
  socketFactory?: SocketFactory;
}

export interface Room {
  /** The user ending it themselves. Tears down exactly as a close does. */
  leave(): void;
}

export async function joinRoom(options: RoomOptions): Promise<Room> {
  const playback = createPlayback({ context: options.context });

  // Declared before the connection so the handlers below can close over it,
  // and assigned after, because it needs somewhere to send.
  let uplink: { stop(): void } | null = null;
  let ended = false;

  /**
   * Torn down in one order, whoever started it.
   *
   * The microphone first: a buffer captured after the socket has gone is the
   * user talking to nobody, and `Connection.send` dropping it is a guard
   * rather than the design. Playback next, so a frame already in flight cannot
   * be queued behind the ending. The screen last, when both are already true —
   * it navigates to the debrief, and should not race a teardown to get there.
   *
   * Guarded against running twice, because leaving and being closed both
   * arrive here and the user hanging up produces both.
   */
  const teardown = (ending: Ending) => {
    if (ended) {
      return;
    }
    ended = true;

    uplink?.stop();
    playback.stop();
    options.onEnding?.(ending);
  };

  const connection = await openConnection({
    url: options.url,
    ticket: options.ticket,
    socketFactory: options.socketFactory,
    onAudio: (pcm) => playback.enqueue(pcm),
    onTranscript: options.onTranscript,
    onDiscardPlayback: () => playback.discard(),
    onEnding: teardown,
  });

  uplink = createUplink({
    recorder: options.recorder,
    send: (pcm) => connection.send(pcm),
    // A device whose microphone cannot deliver the wire's rate has no usable
    // room. Closing costs the user nothing: ticks are whole 15-second units
    // charged in arrears, and this is detected on the first buffer.
    onFailure: () => connection.close(),
  });

  return {
    leave: () => {
      // Torn down first, closed second, and deliberately in that order.
      // `close()` only *begins* a closing handshake — `onclose` arrives when
      // the peer answers, or when the platform stops waiting for it. Leaving
      // teardown to that event keeps the microphone live across a network
      // round trip after the user has said stop, on a phone lying face-up on
      // a desk. The socket's own close still arrives afterwards and finds the
      // room already ended, which is what the guard in `teardown` is for.
      teardown('ended');
      connection.close();
    },
  };
}
