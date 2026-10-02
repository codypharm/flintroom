import { Refused } from '../api/refused';
import { refusalFor } from './refusals';

/**
 * Why a room would not open, and whether buying time would help.
 *
 * These lived inside `interrogation.tsx`, where routes carry no tests by
 * convention (`CLAUDE.md` → Frontend) — so the sentence somebody reads at the
 * worst moment of using this product had nothing holding it. They moved here
 * when the refusal had to grow a *decision* rather than just a sentence: with a
 * buy screen now behind it, each refusal has to say whether money is the answer,
 * and getting that wrong takes payment for something that will not help.
 */

it('offers to sell time when time is what ran out', async () => {
  const refusal = refusalFor(
    new Refused('no_minutes_remaining', 'server said so', 422),
  );

  expect(refusal.buying).toBe(true);
  expect(refusal.said).toMatch(/still here/i);
});

it('does NOT offer to sell time against the daily ceiling', async () => {
  // **The one that would be wrong to get wrong.** `DAILY_SPEND_CEILING_USD` is
  // a cost circuit breaker (#73), not a balance — it bounds what three
  // providers can charge *us* in twenty-four hours, and it lifts on its own.
  // Buying minutes does not raise it by a cent, so an offer here takes money
  // for a room that will still refuse to open.
  const refusal = refusalFor(
    new Refused('daily_ceiling_reached', 'server said so', 422),
  );

  expect(refusal.buying).toBe(false);
});

it('does not offer to sell a second room to somebody already in one', async () => {
  // Minutes are not the constraint; the one-live-session rule is. The recovery
  // is to finish the other room, and money changes nothing about it.
  const refusal = refusalFor(
    new Refused('active_session_exists', 'server said so', 422),
  );

  expect(refusal.buying).toBe(false);
});

it('tells somebody who just left a room that it clears by itself', async () => {
  // The common case is not a second device. It is a room the presenter just
  // left, held open for the 30-second reconnect window plus the sweep that
  // closes it, which took 43 to 52 seconds on the first iPhone (2026-10-02).
  // "Finish that one" sent them looking for a room they could not see.
  const refusal = refusalFor(
    new Refused('active_session_exists', 'server said so', 422),
  );

  expect(refusal.said).toMatch(/within a minute/);
  expect(refusal.said).not.toMatch(/\u2014/);
});

it('keeps the server sentence for a code this build predates', async () => {
  // A refusal added on the server after this build shipped should still say
  // something true rather than a catch-all — and must never offer to sell
  // against a cause nobody here understands.
  const refusal = refusalFor(new Refused('some_future_code', 'A real reason.', 422));

  expect(refusal.said).toBe('A real reason.');
  expect(refusal.buying).toBe(false);
});

it('says something honest about a failure nobody explained', async () => {
  const refusal = refusalFor(new Error('socket died'));

  expect(refusal.said).toBeTruthy();
  expect(refusal.buying).toBe(false);
});

describe('when the phone is the thing that is offline', () => {
  it('says so instead of the catch-all, and still says nothing was charged', () => {
    const refusal = refusalFor(new Error('Network request failed'), true);

    expect(refusal.said).toMatch(/offline/i);
    // The sentence this replaced led with "nothing was charged", and that
    // reassurance is the part that must survive: somebody who just tried to
    // spend minutes assumes they spent them.
    expect(refusal.said).toMatch(/nothing was charged/i);
    expect(refusal.buying).toBe(false);
  });

  it('never overrides a refusal the server sent, because the server answered', () => {
    // Reaching a typed refusal means a request went out and came back. If the
    // probe says offline here it is stale or wrong, and telling somebody their
    // connection is down while showing them a server's own answer is the kind
    // of contradiction that makes the whole screen untrustworthy.
    const refusal = refusalFor(
      new Refused('no_minutes_remaining', 'server said so', 422),
      true
    );

    expect(refusal.said).not.toMatch(/offline/i);
    expect(refusal.buying).toBe(true);
  });

  it('does not blame the network for the microphone', () => {
    // A denied microphone is local and stays local. Sending somebody to check
    // their wifi over a permission they have to change in Settings is a dead
    // end with a confident voice.
    expect(refusalFor(new Error('denied'), true).said).toMatch(/microphone/i);
  });
});
