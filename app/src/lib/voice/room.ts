import {
  openConnection,
  type Attending,
  type Ending,
  type PanelLine,
  type RoomTemperature,
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
  /**
   * A finished panel utterance, to caption, and who said it.
   *
   * Fires the instant the frame arrives, ahead of the audio it captions, and
   * that is deliberate — captions are an accessibility requirement and a
   * caption that waited for its own audio would arrive seconds late.
   *
   * **It is not who is speaking.** Use `onSpeaking` for that.
   */
  onTranscript?: (line: PanelLine) => void;
  /**
   * Whose voice is actually coming out of the phone, or null for nobody.
   *
   * Separate from `onTranscript` because the two are true at different
   * moments, and conflating them is what put the screen a whole turn ahead of
   * the audio. A caption leads its own audio by design; a lit seat must not.
   *
   * Null is the floor being empty rather than the presenter's — that is
   * `onTurnFinished`, which follows when nobody is waiting to speak.
   */
  onSpeaking?: (archetype: string | null) => void;
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
   * How the panel is receiving the argument. Straight through, unexamined.
   *
   * #74, and there is nothing to reason about on this side even in principle:
   * the band is read from the routing reason on panel lines, which never
   * crosses the socket. The screen turns it into the ambient ground.
   */
  onTemperature?: (state: RoomTemperature) => void;
  /**
   * Who is about to take the floor — #75.
   *
   * Straight through, like the band above, and for a stronger version of the
   * same reason: the floor is decided by the Auditor's finding or the routing
   * model, and neither crosses this socket. The screen turns it into a tray
   * starting to develop.
   */
  onChallenging?: (archetype: string) => void;
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
   * Who is audible, and who is queued behind them.
   *
   * **One boundary, used for both halves of the question, because the two
   * halves used to have different answers.** Clearing a lit seat waited for
   * the server to finish *and* for the audio to play; lighting one waited for
   * nothing, so any caption could hand the seat to the next panelist while the
   * last was still speaking. Reported from a device in August as losing focus
   * "even when they are still speaking", and again on 2026-09-19 as the screen
   * running a whole turn ahead of the audio. Two reports, one defect.
   *
   * `turn_finished` says the server sent its last frame, which is not the same
   * as the phone having played it — synthesis runs ahead of playback, and that
   * is what makes barge-in possible. So it marks the last buffer of its
   * utterance instead, and the room moves on when that buffer has actually
   * played.
   *
   * Exact in both directions, and in particular still exact when the next
   * panelist's frames are queued behind the tail of the last. The queue never
   * empties there, which is why the empty-queue signal this replaces could not
   * see the boundary at all.
   */
  let audible: string | null = null;
  const waiting: string[] = [];

  const show = (who: string | null) => {
    audible = who;
    options.onSpeaking?.(who);
  };

  const playback = createPlayback({
    context: options.context,
    onPlayed: () => {
      // The floor goes back to the presenter only when nobody is queued behind
      // the voice that just stopped. Announcing it between two panel turns
      // would be the room inviting an answer to a question still being asked.
      const next = waiting.shift() ?? null;
      show(next);
      if (next === null) {
        options.onTurnFinished?.();
      }
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
    onAudio: (pcm) => playback.enqueue(pcm),
    onTranscript: (line) => {
      // The caption goes out at once, ahead of its own audio, because that is
      // what a caption is for. The *seat* does not: a caption that arrives
      // while somebody is still audible belongs to the panelist queued behind
      // them, and lighting them here is the bug this queue exists to stop.
      options.onTranscript?.(line);

      if (audible === null) {
        show(line.speaker);
        return;
      }
      waiting.push(line.speaker);
    },
    onAttending: options.onAttending,
    onTemperature: options.onTemperature,
    onChallenging: options.onChallenging,
    // Where this utterance's audio ends. Every frame of it has already been
    // enqueued — the wire delivers them before the control frame that closes
    // the turn — so the buffer queued last is this utterance's last buffer.
    onTurnFinished: () => playback.mark(),
    onDiscardPlayback: () => {
      // Barge-in. The queue is emptied without any buffer reaching its end, so
      // nothing queued will ever be reported as played — including anyone
      // waiting behind it, whose turn was thrown away with it.
      waiting.length = 0;
      playback.discard();
      // The floor is the presenter's already, by the act of interrupting, so
      // this puts the panelist down without announcing a hand-over.
      show(null);
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
