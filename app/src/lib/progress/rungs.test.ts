import { atTheSameRung } from './rungs';

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
