import { Refused } from '../api/debriefApi';
import { refusedRoom, refusedTurn } from './refusals';

/**
 * Five typed refusals, and five different next moves.
 *
 * These tests exist because the codes are cheap to collapse and expensive to
 * have collapsed. Two of them share a status; one of them is about money the
 * user is already owed.
 */

const refused = (code: string, message = 'the server said so', status = 422) =>
  new Refused(code, message, status);

describe('refusedRoom', () => {
  it('offers a fresh room when the product broke the last one', async () => {
    // The only refusal where the user is owed something. Leading with the
    // minutes is what stops the offer reading as being asked to pay twice for
    // our fault — the backend's own `RoomBroke` makes the same point about why
    // the code exists rather than just the status.
    const refusal = refusedRoom(refused('room_broke'));

    expect(refusal?.offer).toBe('fresh room');
    expect(refusal?.body).toContain('minutes are already back');
  });

  it('does not offer a restart for a room that is merely still running', async () => {
    // Restarting here would abandon a live session, which is the opposite of
    // what somebody arriving early wants.
    expect(refusedRoom(refused('session_not_settled', '', 409))?.offer).toBeNull();
  });

  it('tells a room that asked nothing apart from a room that broke', async () => {
    // Both are 422. One is "there is nothing here", the other is "we failed
    // and you have your minutes back".
    const empty = refusedRoom(refused('room_has_no_questions'));
    const broke = refusedRoom(refused('room_broke'));

    expect(empty?.title).not.toBe(broke?.title);
    expect(empty?.body).not.toContain('minutes');
  });

  it('falls back to the server’s own sentence for a code it has never seen', async () => {
    // A refusal added on the server after this build shipped still says
    // something true, rather than a shrug.
    expect(refusedRoom(refused('some_future_rule', 'You have too many rooms open.'))?.body).toBe(
      'You have too many rooms open.'
    );
  });

  it('is not a room refusal when it is not a refusal at all', async () => {
    // A `SignedOut` reaches here and must not be drawn as a debrief problem;
    // the route sends it somewhere else entirely.
    expect(refusedRoom(new Error('offline'))).toBeNull();
  });
});

describe('refusedTurn', () => {
  it('treats silence as nothing heard, not as a failure', async () => {
    // The microphone worked and the transcriber worked. Calling this an error
    // would tell somebody their recording broke when what happened is that they
    // did not speak.
    const said = refusedTurn(refused('nothing_was_said'));

    expect(said).toMatch(/say it again/i);
    expect(said).not.toMatch(/error|failed|wrong/i);
  });

  it('names the recovery for a clip past the ceiling', async () => {
    expect(refusedTurn(refused('clip_too_long', '', 413))).toMatch(/shorter/i);
  });

  it('sends somebody back to the room when their rank has gone stale', async () => {
    // Reachable by resuming onto a screen whose data has moved on. Saying "try
    // again" would loop them through the same failure.
    expect(refusedTurn(refused('no_such_weak_answer', '', 404))).toMatch(/open the room again/i);
  });

  it('says it could not reach us when the failure was not ours to name', async () => {
    expect(refusedTurn(new TypeError('Network request failed'))).toMatch(
      /could not reach the server/i
    );
  });
});
