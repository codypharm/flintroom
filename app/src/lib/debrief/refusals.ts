import { Refused } from '../api/debriefApi';

/**
 * What the server refused, said to the person who is holding the phone.
 *
 * The codes exist because the recoveries differ, and this is the file that has
 * to honour that. Two of them are 422s with nothing in common: one means the
 * room the product broke has already returned its minutes, and the other means
 * the room simply never asked anything. Collapsing them into "something went
 * wrong" would send somebody back to a session that will never work.
 *
 * Copy lives here rather than on the server for the reason `Product.md` §9
 * gives — the API states the fact, the client writes the sentence — and because
 * these sentences carry this product's register. The server's own message is
 * still the fallback for a code this build has never heard of, so a refusal
 * added later says something true instead of nothing.
 */

/** A refusal of the whole room: the sheet cannot be drawn at all. */
export interface RoomRefusal {
  title: string;
  body: string;
  /**
   * The way out, or null when there is only going back.
   *
   * `try again` and `fresh room` are not interchangeable, and telling them
   * apart is the entire job of this file. One says the room is fine and the
   * reading failed; the other says the room itself has nothing in it. Offering
   * the wrong one either sends somebody to start over from a session that is
   * sitting there intact, or invites them to hammer a request that can never
   * succeed.
   */
  offer: 'fresh room' | 'try again' | null;
}

const ROOM: Record<string, RoomRefusal> = {
  session_not_settled: {
    title: 'This room is still running',
    body: 'The panel finishes first, then the debrief opens. Come back when it has.',
    offer: null,
  },
  room_has_no_questions: {
    title: 'Nothing was asked',
    body: 'This room ended before the panel got a question out, so there is nothing to go over.',
    offer: 'fresh room',
  },
  provider_unavailable: {
    // The 502 a debrief returned after a real session. It fell through to the
    // default, which offers nothing — so a **transient** failure was drawn as a
    // dead end. It was not: the transcript was in the database the whole time,
    // and the same rooms read back fine once the debrief's model call stopped
    // inheriting a five-second HTTP timeout meant for OAuth key fetches.
    //
    // The body leads with what survived, because the fear this raises is that
    // the session is gone. It is the only refusal here where the right move is
    // the same action again.
    title: 'That did not come back',
    body: 'Something on our side was slow to answer. Nothing is lost. The room is still there.',
    offer: 'try again',
  },
  room_broke: {
    // The one refusal that has to lead with the money, because it is the only
    // one where the user is owed something and the offer would otherwise read
    // as being asked to pay twice for our fault.
    title: 'That room broke',
    body: 'Something on our side cut it short. Your minutes are already back. Start a fresh room.',
    offer: 'fresh room',
  },
};

/**
 * The refusal to draw instead of the sheet, or null if this is not one.
 *
 * Null for anything else, including a `SignedOut`: that is not a thing this
 * screen can explain, and the route sends it somewhere else.
 */
export function refusedRoom(error: unknown): RoomRefusal | null {
  if (!(error instanceof Refused)) return null;

  return (
    ROOM[error.code] ?? {
      title: 'That did not load',
      // The server's own sentence, because a code this build predates still
      // describes something real.
      body: error.message,
      offer: null,
    }
  );
}

/**
 * The refusal of one spoken turn, said beside the control that caused it.
 *
 * Never replaces the sheet. A clip that failed to transcribe does not
 * invalidate the room, and throwing away findings somebody is working through
 * because one recording was too long would be a worse failure than the one
 * being reported.
 */
export function refusedTurn(error: unknown): string {
  if (!(error instanceof Refused)) {
    return 'I could not reach the server. Try that again in a moment.';
  }

  switch (error.code) {
    case 'nothing_was_said':
      // Deliberately not phrased as a fault or a failure. The microphone worked
      // and the transcriber worked; there was nothing to hear.
      return 'I did not catch anything there. Say it again.';
    case 'clip_too_long':
      return 'That was longer than I can take in one go. Say it in a shorter run.';
    case 'no_such_weak_answer':
      // Reachable by resuming onto a screen whose data has moved on, so the
      // recovery is a reload rather than another attempt.
      return 'That question is not part of this room any more. Open the room again.';
    default:
      return error.message;
  }
}
