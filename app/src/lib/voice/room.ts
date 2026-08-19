import {
  openConnection,
  type Attending,
  type Ending,
  type PanelLine,
  type SocketFactory,
} from './connection';
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
  /** A finished panel utterance, to caption, and who said it. */
  onTranscript?: (line: PanelLine) => void;
  /**
   * The panel has stopped; the floor is the presenter's.
   *
   * Passed straight through rather than derived here. `joinRoom` holds the
   * playback queue and could watch it drain, which is exactly the tempting
   * wrong answer — a drained buffer means the network stalled just as often as
   * it means the utterance ended.
   */
  onTurnFinished?: () => void;
  /**
   * A panelist was cut off — the presenter took the floor by talking over them.
   *
   * Separate from `onTurnFinished`, and the room deliberately never sends both
   * for one turn: a cancelled turn does not announce the floor, because the
   * person now holding it is already speaking. But something still has to put
   * the interrupted panelist down, or they stay lit on screen having been
   * silenced — which reads as a room that has lost track of who is talking.
   */
  onDiscardPlayback?: () => void;
  /**
   * What the room is doing with the floor. Straight through, unexamined.
   *
   * `joinRoom` derives `turn_finished` from two signals because neither is
   * sufficient alone; this one is a fact the server states outright, so adding
   * any reasoning here would only be a second opinion about something already
   * answered.
   */
  onAttending?: (state: Attending) => void;
  /**
   * How loud each captured buffer was, in dBFS.
   *
   * From the uplink, which already holds it. The screen turns a window of
   * these into three states — see `audio/hearing.ts` — and is never shown the
   * number itself.
   */
  onLevel?: (dbfs: number) => void;
  /** The room is over, and why. Called once, after everything is torn down. */
  onEnding?: (ending: Ending) => void;
  socketFactory?: SocketFactory;
}

export interface Room {
  /** The user ending it themselves. Tears down exactly as a close does. */
  leave(): void;
}

export async function joinRoom(options: RoomOptions): Promise<Room> {
  /**
   * The floor comes back when **both** halves say so, and neither is enough.
   *
   * `turn_finished` means the server sent its last frame. Synthesis runs ahead
   * of playback — that is what makes barge-in possible — so acting on it alone
   * took the speaking panelist off the screen while their voice was still
   * coming out of the phone. Reported from a device as losing focus "even when
   * they are still speaking".
   *
   * An empty playback queue alone is no better, and `connection.ts` already
   * says why: it is indistinguishable from the network stalling mid-sentence,
   * which would invite the presenter to talk over the end of a question.
   *
   * Together they are exact. Nothing more is coming, and nothing is left to
   * play.
   */
  let sent = false;
  let quiet = true;

  const handOver = () => {
    if (!sent || !quiet) {
      return;
    }
    sent = false;
    options.onTurnFinished?.();
  };

  const playback = createPlayback({
    context: options.context,
    onDrained: () => {
      quiet = true;
      handOver();
    },
  });

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
    onAudio: (pcm) => {
      // A frame arriving is the room no longer being quiet. Set here rather
      // than on the caption, because a caption goes out ahead of its audio and
      // a turn whose synthesis fails would otherwise leave the floor held by
      // somebody who never spoke.
      quiet = false;
      playback.enqueue(pcm);
    },
    onTranscript: options.onTranscript,
    onAttending: options.onAttending,
    onTurnFinished: () => {
      sent = true;
      handOver();
    },
    onDiscardPlayback: () => {
      // Barge-in. The queue is emptied without any buffer reaching its end, so
      // no drain will ever be reported for what was dropped — and the floor is
      // the presenter's already, by the act of interrupting.
      quiet = true;
      sent = false;
      playback.discard();
      options.onDiscardPlayback?.();
    },
    onEnding: teardown,
  });

  uplink = createUplink({
    recorder: options.recorder,
    send: (pcm) => connection.send(pcm),
    onLevel: options.onLevel,
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
