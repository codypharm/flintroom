import { Refused } from '../api/debriefApi';
import { SignedOut } from '../auth/session';
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
    expect(refusedRoom(refused('session_not_settled', '', 409))?.offer).not.toBe(
      'fresh room'
    );
  });

  it('lets somebody who arrived early ask again', async () => {
    // **The dead end, reported 2026-09-19.** This offered nothing, on the
    // reasoning that a live room is not something to restart — true, and not
    // an argument for offering *no* way forward. The room settles seconds
    // later and the same read succeeds, so the one thing this refusal must
    // do is let them make it.
    //
    // It is reachable by two races the client cannot win from the outside:
    // the End button navigating on a fixed beat while settlement is still in
    // flight, and a dropped line whose re-mint is refused the moment the
    // session leaves `active` — which includes the whole of `finalizing`.
    const refusal = refusedRoom(refused('session_not_settled', '', 409));

    expect(refusal?.offer).toBe('try again');
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

  it('is not a room refusal when the account is the problem', async () => {
    // A `SignedOut` reaches here and must not be drawn as a debrief problem;
    // the route sends it somewhere else entirely.
    //
    // **Narrowed 2026-09-10.** This used to assert null for *any* non-refusal,
    // passing a plain `Error` to make a point about `SignedOut`, and the
    // over-broad contract it locked in is what left a failed request drawing a
    // spinner forever. Only the account case is silent now.
    expect(refusedRoom(new SignedOut('expired'))).toBeNull();
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

describe('a room that could not be read this time', () => {
  /**
   * The 502 the architect hit after a session: "That did not load. The service
   * we depend on is unavailable."
   *
   * It fell through to the default, which offers nothing — so a **transient**
   * failure was presented as a dead end. It was not: the transcript was in the
   * database the whole time, and the same three sessions returned 200 once the
   * debrief's model call stopped inheriting a five-second HTTP timeout meant
   * for OAuth. Re-reading would have worked.
   *
   * This is the one refusal where the recovery is the same action again, and
   * the offer vocabulary had no way to say so.
   */
  it('offers another go when the failure was ours and passing', () => {
    const refusal = refusedRoom(
      new Refused('provider_unavailable', 'A service we depend on is unavailable.', 502)
    );

    expect(refusal?.offer).toBe('try again');
  });

  it('does not blame them for it', () => {
    // The room happened, they said things, and none of it is gone. A refusal
    // that reads as their mistake would send somebody to start over from a
    // session that is sitting there intact.
    const refusal = refusedRoom(
      new Refused('provider_unavailable', 'A service we depend on is unavailable.', 502)
    );

    expect(refusal?.body).toMatch(/nothing is lost|still there|not lost/i);
  });

  it('still sends them to a fresh room when there is genuinely nothing to read', () => {
    // The distinction the file was written to protect. Trying again on a room
    // that asked no questions will fail identically, forever.
    expect(
      refusedRoom(new Refused('room_has_no_questions', 'x', 422))?.offer
    ).toBe('fresh room');
  });

  it('offers nothing for a refusal this build has never heard of', () => {
    // An unknown code has an unknown recovery, and guessing "try again" at one
    // would invite somebody to hammer a request that can never succeed.
    expect(refusedRoom(new Refused('something_new', 'x', 400))?.offer).toBeNull();
  });
});

describe('a coaching turn that never left the phone', () => {
  it('says the phone is offline rather than blaming the server', () => {
    expect(refusedTurn(new Error('Network request failed'), true)).toMatch(/offline/i);
  });

  it('keeps the server\'s own answer when the server answered', () => {
    expect(refusedTurn(new Refused('nothing_was_said', 'x', 422), true)).not.toMatch(
      /offline/i
    );
  });
});

describe('a debrief that never arrived', () => {
  it('says something instead of spinning forever', () => {
    // The screen renders a spinner until a refusal exists, so a null here is
    // not "no refusal" but "no exit": a transport failure left somebody
    // watching an indicator with nothing coming. Offering the same call again
    // is right, because the room and its transcript were never the problem.
    const refusal = refusedRoom(new Error('Network request failed'));

    expect(refusal).not.toBeNull();
    expect(refusal?.offer).toBe('try again');
  });

  it('names the phone when the phone is what is offline', () => {
    const refusal = refusedRoom(new Error('Network request failed'), true);

    expect(`${refusal?.title} ${refusal?.body}`).toMatch(/offline/i);
    expect(refusal?.offer).toBe('try again');
  });

  it('stays silent for a signed-out error, because the gate moves them', () => {
    // Both call sites return early on this, but the promise is this file's to
    // keep: a sentence drawn here would race the navigation that is already
    // happening, and win.
    expect(refusedRoom(new SignedOut('expired'), true)).toBeNull();
  });
});
