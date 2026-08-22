import { atTheSameRung, ladderMoved } from './rungs';

/**
 * The one comparison this product is allowed to make.
 *
 * Progress refuses totals, averages and verdicts because difficulty escalates
 * (#55) — a count of what got past somebody can rise while they improve, and a
 * figure shown without the level it was earned at would tell an improving
 * presenter they are getting worse.
 *
 * That argument forbids comparing rooms at *different* rungs. It says nothing
 * against comparing two rooms at the same one, where the confounder is held
 * constant, and the architect asked twice for somebody to be able to tell
 * whether they are doing well. Refusing that is caution rather than honesty.
 *
 * Scoped to one rehearsal by its caller. Two rooms at Standard about two
 * different arguments are not a comparison either.
 */

const AT = (sessionId: string, level: number | null, held: number, challenged: number) => ({
  sessionId,
  rehearsalId: 'r-1',
  rehearsalName: null,
  startedAt: '2026-08-20T09:00:00Z',
  challenged,
  held,
  level,
});

it('compares two attempts that ran at the same rung', () => {
  // The whole point. Same difficulty, same argument, two afternoons.
  const runs = atTheSameRung([AT('b', 2, 6, 7), AT('a', 2, 4, 7)]);

  expect(runs).toEqual([
    { level: 2, attempts: [{ held: 4, challenged: 7 }, { held: 6, challenged: 7 }] },
  ]);
});

it('reads oldest first, so the order is time', () => {
  // The rooms arrive newest first, which is right for a list and wrong for
  // anything read as a sequence. Reversed here rather than at the screen, so
  // one rule about which way time runs serves both.
  const [run] = atTheSameRung([AT('b', 2, 6, 7), AT('a', 2, 4, 7)]);

  expect(run.attempts[0]).toEqual({ held: 4, challenged: 7 });
});

it('says nothing about two rooms that ran at different rungs', () => {
  // The comparison the escalating ladder makes dishonest, and the reason this
  // module exists rather than a subtraction at the screen.
  expect(atTheSameRung([AT('b', 3, 6, 7), AT('a', 2, 4, 7)])).toEqual([]);
});

it('says nothing about a single attempt at a rung', () => {
  // One room is not a comparison. Reporting it would be the tally already on
  // the row above, wearing a heading that implies a second point.
  expect(atTheSameRung([AT('a', 2, 4, 7)])).toEqual([]);
});

it('leaves out rooms that predate the ladder', () => {
  // A null rung is a room nobody recorded a difficulty for. Treating those as
  // one shared level would compare rooms whose difficulty is unknown, which is
  // the exact mistake the whole rule exists against.
  expect(atTheSameRung([AT('b', null, 6, 7), AT('a', null, 4, 7)])).toEqual([]);
});

it('reports each rung a rehearsal has more than one attempt at', () => {
  // Somebody who ran a thing twice at Standard, moved up, and ran it twice at
  // Relentless has two comparisons, not one — and mixing them would be the
  // average across rungs that Progress refuses.
  const runs = atTheSameRung([
    AT('d', 3, 5, 9),
    AT('c', 3, 3, 9),
    AT('b', 2, 6, 7),
    AT('a', 2, 4, 7),
  ]);

  expect(runs.map((run) => run.level)).toEqual([2, 3]);
});

it('counts a room where nobody was asked anything out', () => {
  // No proportion, so no comparison. A room that ended before the panel spoke
  // is a technical failure, and pairing it with a real attempt would read as
  // somebody collapsing.
  expect(atTheSameRung([AT('b', 2, 4, 7), AT('a', 2, 0, 0)])).toEqual([]);
});

/**
 * How hard the room you are handed has become — the account's own ladder.
 *
 * The architect asked whether the Progress screen had better data now, and this
 * is the strongest thing already on the wire and never drawn: `difficulty_level`
 * is on every room, the ladder moves *because* of measured performance
 * (`calibration.py` drops a rung at half its questions fumbled and raises at a
 * fifth), so climbing it IS improvement by the product's own definition. It was
 * a per-row caption on a chart the screen explicitly warns you not to compare
 * heights across, which is the weakest instrument available for it.
 *
 * **ONLY LINEAGE-OPENERS, AND THAT IS THE WHOLE SUBTLETY.** Since
 * `docs/difficulty-calibration.md` decision 8 a room's rung comes from one of
 * two places: a re-run inherits the rung its own rehearsal last ran at, and a
 * fresh argument opens at the account's. `DebriefService.pressed` refuses to
 * compare across that seam in so many words — *"two rehearsals sitting at
 * different rungs would make every debrief say 'harder', then 'easier', then
 * 'harder', while nothing about them changed"* — and a series drawn over every
 * room would be exactly that sawtooth, reporting bookkeeping as progress.
 *
 * An opener is `rehearsalId === sessionId`, because the server sends
 * `COALESCE(rehearsal_id, id)`: they are equal precisely when the column is
 * null, which is precisely when the room read the account's dial.
 */

/** A room that opened its own lineage — one that read the account's rung. */
const OPENED = (sessionId: string, level: number | null, startedAt: string) => ({
  sessionId,
  rehearsalId: sessionId,
  rehearsalName: null,
  startedAt,
  challenged: 8,
  held: 6,
  level,
});

/** A re-run, which inherited its rehearsal's rung and read no dial. */
const AGAIN = (sessionId: string, level: number | null, startedAt: string) => ({
  ...OPENED(sessionId, level, startedAt),
  rehearsalId: 'r-older',
});

it('says where the ladder started and where it stands now', () => {
  // Rooms arrive newest first, as the server sends them.
  const moved = ladderMoved([
    OPENED('c', 3, '2026-08-20T09:00:00Z'),
    OPENED('b', 2, '2026-08-14T09:00:00Z'),
    OPENED('a', 1, '2026-08-01T09:00:00Z'),
  ]);

  expect(moved).toEqual({ first: 1, now: 3 });
});

it('ignores re-runs, which inherit a rung rather than earning one', () => {
  // The sawtooth `pressed()` refuses to draw. Both re-runs sit at Relentless
  // because their lineage does; reading them as the account's ladder would
  // report a climb that never happened.
  const moved = ladderMoved([
    AGAIN('d', 3, '2026-08-20T09:00:00Z'),
    AGAIN('c', 3, '2026-08-18T09:00:00Z'),
    OPENED('b', 1, '2026-08-14T09:00:00Z'),
    OPENED('a', 1, '2026-08-01T09:00:00Z'),
  ]);

  expect(moved).toBeNull();
});

it('says nothing when the ladder has not moved', () => {
  // Nothing happened, and `pressed()` answers null in the same case for the
  // same reason: a sentence saying so is a sentence about nothing.
  const moved = ladderMoved([
    OPENED('b', 2, '2026-08-14T09:00:00Z'),
    OPENED('a', 2, '2026-08-01T09:00:00Z'),
  ]);

  expect(moved).toBeNull();
});

it('says nothing about a single room, which is a dot rather than an arc', () => {
  expect(ladderMoved([OPENED('a', 2, '2026-08-01T09:00:00Z')])).toBeNull();
});

it('skips rooms that predate the ladder rather than folding them in', () => {
  // A null rung is difficulty nobody recorded. Treating it as a level would
  // invent the very comparison the screen exists without — the same refusal
  // `atTheSameRung` makes one function above.
  const moved = ladderMoved([
    OPENED('c', 3, '2026-08-20T09:00:00Z'),
    OPENED('b', null, '2026-08-14T09:00:00Z'),
    OPENED('a', 2, '2026-08-01T09:00:00Z'),
  ]);

  expect(moved).toEqual({ first: 2, now: 3 });
});

it('reports a descent as readily as a climb', () => {
  // The ladder goes down at half a room fumbled, and that is the product
  // protecting somebody rather than grading them — #55 exists because "a first
  // session that destroys the user produces churn, not resilience".
  //
  // Hiding it would be the false-comfort mirror of the false-hope trap the
  // screen is built against, and it would make the sentence a reward rather
  // than a fact. What carries the difference is the framing at the screen: the
  // room eased off. Nothing here says anybody got worse.
  const moved = ladderMoved([
    OPENED('b', 1, '2026-08-14T09:00:00Z'),
    OPENED('a', 3, '2026-08-01T09:00:00Z'),
  ]);

  expect(moved).toEqual({ first: 3, now: 1 });
});
