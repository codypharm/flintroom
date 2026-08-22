import { render, screen, userEvent, within } from '@testing-library/react-native';

import { Progress, type ProgressProps } from './Progress';

/**
 * How somebody is holding up, room after room.
 *
 * Asked for twice. The first build was three sentences about the most recent
 * room, and the architect's word for it was accurate: *"the aim of progress is
 * to track users' performance in pitching throughout the app, not some text you
 * just wrote there."* The endpoint had always returned every room with its own
 * figures and its own rung; only one of them was being drawn.
 *
 * What is still refused is a **delivery-metrics** score — `Product.md:392` —
 * and any single number standing for a run of rooms that were not equally hard.
 */

/**
 * Five rooms in two rehearsals: r-1 → r-2 → r-3 is one argument put three
 * times, and r-4 → r-5 is a second one put twice. Newest first, as the server
 * returns them.
 */
const ROOMS = [
  { sessionId: 'r-5', rehearsalId: 'r-4', rehearsalName: null, startedAt: '2026-08-20T09:12:00Z', challenged: 9, held: 8, level: 3 },
  { sessionId: 'r-4', rehearsalId: 'r-4', rehearsalName: null, startedAt: '2026-08-19T16:04:00Z', challenged: 7, held: 4, level: 3 },
  { sessionId: 'r-3', rehearsalId: 'r-1', rehearsalName: null, startedAt: '2026-08-17T11:00:00Z', challenged: 6, held: 2, level: 2 },
  { sessionId: 'r-2', rehearsalId: 'r-1', rehearsalName: null, startedAt: '2026-08-14T11:00:00Z', challenged: 5, held: 1, level: 2 },
  { sessionId: 'r-1', rehearsalId: 'r-1', rehearsalName: null, startedAt: '2026-08-11T11:00:00Z', challenged: 4, held: 0, level: 1 },
];

const NOW = new Date('2026-08-20T14:00:00Z');

async function setup(overrides: Partial<ProgressProps> = {}) {
  const props: ProgressProps = {
    rooms: ROOMS,
    habits: [
      { name: 'unanswered', rooms: 4 },
      { name: 'evasive', rooms: 2 },
    ],
    askers: [{ name: 'cfo', rooms: 4 }],
    now: NOW,
    onOpenRoom: jest.fn(),
    ...overrides,
  };

  await render(<Progress {...props} />);
  return props;
}

describe('the run of rooms', () => {
  it('shows every room, not only the last one', async () => {
    // The whole complaint. A record of performance is the series; one room is
    // a snapshot, and a snapshot cannot show somebody they are improving.
    await setup();

    for (const held of ['8 of 9', '4 of 7', '2 of 6', '1 of 5', '0 of 4']) {
      expect(screen.getByText(held)).toBeTruthy();
    }
  });

  it('runs oldest to newest, so the shape reads as time', async () => {
    // The server returns newest first, which is right for a list somebody is
    // looking through and wrong for a trend — a chart that ran backwards would
    // show an improving presenter getting worse.
    await setup();

    // Scoped to the trend, because "room by room" below it lists the same
    // rooms the other way round on purpose — newest first is right for a list
    // somebody is scanning and wrong for a shape they are reading as time.
    const trend = within(screen.getByLabelText('Every room, oldest first'));
    const bars = trend.getAllByLabelText(/held of/);

    expect(bars[0]).toHaveProp('accessibilityLabel', expect.stringContaining('0 held of 4'));
    expect(bars[bars.length - 1]).toHaveProp(
      'accessibilityLabel',
      expect.stringContaining('8 held of 9')
    );
  });

  it('names the rung on every single room', async () => {
    // The one rule that keeps the series from lying. Difficulty escalates, so
    // two bars of different heights may be two different rooms rather than two
    // different performances — and a reader comparing them needs the rung on
    // both, not in a caption underneath.
    await setup();

    expect(screen.getAllByText(/Relentless/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/Gentle/).length).toBeGreaterThanOrEqual(1);
  });

  it('leaves out a room where nobody was asked anything', async () => {
    // A room that ended before the panel spoke has no proportion. Drawing it as
    // zero would put a trough in the trend that describes a technical failure
    // rather than a performance.
    await setup({
      rooms: [
        ROOMS[0],
        { sessionId: 'r-0', rehearsalId: 'r-0', rehearsalName: null, startedAt: '2026-08-10T11:00:00Z', challenged: 0, held: 0, level: 2 },
      ],
    });

    expect(screen.queryByText('0 of 0')).toBeNull();
  });

  it('opens the room that was tapped', async () => {
    // Every point on the trend is a real afternoon, and the transcript is one
    // tap away. A chart nobody can get behind is a chart nobody trusts.
    const { onOpenRoom } = await setup();

    const trend = within(screen.getByLabelText('Every room, oldest first'));
    await userEvent.press(trend.getByLabelText(/8 held of 9/));

    expect(onOpenRoom).toHaveBeenCalledWith('r-5');
  });
});

describe('what keeps happening', () => {
  it('lists the habits as things somebody did, with how often', async () => {
    await setup();

    expect(screen.getByText('Let it go by')).toBeTruthy();
    expect(screen.getByText('Answered a different question')).toBeTruthy();
    // Twice over: the habit happened in four rooms and the CFO caught them in
    // four. Both are true and both are drawn.
    expect(screen.getAllByText('four rooms').length).toBe(2);
  });

  it('lists who keeps getting past them', async () => {
    await setup();

    expect(screen.getByText('The CFO')).toBeTruthy();
  });
});

describe('what it refuses to say', () => {
  it('never reduces a run of rooms to one number', async () => {
    // Rooms at different rungs are not comparable, so there is no total, no
    // average, and no percentage — that arithmetic is the lie this screen is
    // built around avoiding.
    await setup();

    expect(screen.queryByText(/average/i)).toBeNull();
    expect(screen.queryByText(/\d+\s*%/)).toBeNull();
    expect(screen.queryByText(/overall/i)).toBeNull();
  });

  it('puts no grade anywhere', async () => {
    await setup();

    expect(screen.queryByText(/^[A-F][+-]?$/)).toBeNull();
    expect(screen.queryByText(/score/i)).toBeNull();
  });

  it('says nothing about pace, filler, or confidence', async () => {
    // The commodity layer §1 refuses, and also unmeasurable here: nothing in
    // this pipeline hears how somebody spoke, only what they said.
    await setup();

    for (const it of [/pacing/i, /filler/i, /confiden/i, /clarity/i]) {
      expect(screen.queryByText(it)).toBeNull();
    }
  });
});

describe('an account with no history', () => {
  it('says what will be here rather than drawing an empty chart', async () => {
    await setup({ rooms: [], habits: [], askers: [] });

    expect(screen.getByText('Nothing to compare yet')).toBeTruthy();
  });

  it('draws no trend from a single room', async () => {
    // One point is not a line. A chart with one bar in it implies a trajectory
    // that does not exist, which is worse than saying so.
    await setup({ rooms: [ROOMS[0]], habits: [], askers: [] });

    expect(screen.getByText(/one room so far/i)).toBeTruthy();
  });

  it('calls nothing a pattern until it has happened twice', async () => {
    await setup({
      rooms: [ROOMS[0], ROOMS[1]],
      habits: [{ name: 'evasive', rooms: 1 }],
      askers: [{ name: 'cfo', rooms: 1 }],
    });

    expect(screen.queryByText('Answered a different question')).toBeNull();
  });
});

describe('the same argument, put more than once', () => {
  it('gathers the attempts at one argument into their own run', async () => {
    // The question the whole grouping exists for: not "am I getting better" but
    // "am I getting better at **this**". Five rooms in two rehearsals is two
    // runs, and reading them as one list of five would answer neither.
    await setup();

    const rehearsal = within(screen.getByLabelText('One argument, oldest first, started 9 days ago'));

    expect(rehearsal.getAllByLabelText(/held of/)).toHaveLength(3);
  });

  it('runs each rehearsal oldest first, like the trend above it', async () => {
    // The same instrument at a narrower scope. A second rule about which way
    // time runs is how one chart comes to disagree with the other.
    await setup();

    const rehearsal = within(screen.getByLabelText('One argument, oldest first, started 9 days ago'));
    const attempts = rehearsal.getAllByLabelText(/held of/);

    expect(attempts[0]).toHaveProp('accessibilityLabel', expect.stringContaining('0 held of 4'));
    expect(attempts[2]).toHaveProp('accessibilityLabel', expect.stringContaining('2 held of 6'));
  });

  it('says nothing about a room nobody ever repeated', async () => {
    // One attempt is not a rehearsal. Giving it a heading of its own would
    // spread the screen across every room somebody ever ran and bury the two
    // they are actually working on.
    await setup({
      rooms: [
        ROOMS[0],
        ROOMS[1],
        { sessionId: 'r-9', rehearsalId: 'r-9', rehearsalName: null, startedAt: '2026-08-18T11:00:00Z', challenged: 3, held: 3, level: 2 },
      ],
    });

    expect(screen.queryAllByLabelText(/One argument, oldest first/)).toHaveLength(1);
  });

  it('does not draw the whole history twice when it is all one argument', async () => {
    // Somebody who has only ever rehearsed one thing already has that run at
    // the top of the screen. A second copy under a heading says nothing new.
    await setup({ rooms: ROOMS.filter((room) => room.rehearsalId === 'r-1') });

    expect(screen.queryByText('What you keep rehearsing')).toBeNull();
  });

  it('states no verdict on whether a rehearsal is going well', async () => {
    // The architect's constraint, and the reason this shows a run rather than a
    // reading of one: *"we need to be careful to avoid giving user false hope
    // that they are doing well"*. Nothing here computes a direction — the
    // attempts are drawn, and what they add up to is the presenter's to judge.
    await setup();

    for (const verdict of [/improving/i, /getting better/i, /on track/i, /well done/i]) {
      expect(screen.queryByText(verdict)).toBeNull();
    }
  });
});

describe('what the rehearsal is called', () => {
  it('heads the run with its name when it has one', async () => {
    // "Started 9 days ago" is honest and nearly useless. "Am I getting better at
    // my Q3 board readout" needs the words, and this is the only screen where
    // they answer the question the presenter came with.
    await setup({
      rooms: ROOMS.map((room) =>
        room.rehearsalId === 'r-1' ? { ...room, rehearsalName: 'Q3 board readout' } : room
      ),
    });

    expect(screen.getByText('Q3 board readout')).toBeTruthy();
    expect(screen.getByLabelText('Q3 board readout, oldest first')).toBeTruthy();
  });

  it('falls back to when it started rather than inventing a heading', async () => {
    // Nothing derives a name from the panel or the deck. A label the presenter
    // never chose is one they have no way to correct, and a date at least says
    // only what is true.
    await setup();

    expect(screen.getByText('Started 9 days ago')).toBeTruthy();
  });
});

describe('the one comparison it will make', () => {
  it('states two attempts that ran at the same rung', async () => {
    // The architect asked twice to be able to tell whether they are doing well.
    // Refusing every comparison answers the false-hope constraint by abandoning
    // the question — and the ladder only makes comparisons across *different*
    // rungs dishonest. r-2 and r-3 both ran at Standard.
    await setup();

    expect(screen.getByText('Standard: 1 of 5, then 2 of 6')).toBeTruthy();
  });

  it('will not compare rooms that ran at different rungs', async () => {
    // The whole reason this screen has no total. r-1 ran at Gentle and r-3 at
    // Standard, so a room where more got past somebody may simply be a room
    // that pressed harder.
    await setup({
      rooms: [ROOMS[2], ROOMS[4]],
    });

    expect(screen.queryByText(/, then /)).toBeNull();
  });

  it('says which way it went in neither direction', async () => {
    // Tallies, not a delta, not an arrow, not a verdict. The numbers are the
    // claim the data supports; what they add up to is the presenter's to read.
    await setup();

    for (const verdict of [/better/i, /worse/i, /improv/i, /↑/, /↓/, /%/]) {
      expect(screen.queryByText(verdict)).toBeNull();
    }
  });
});

/**
 * The ladder, which the screen was drawing only as a caption.
 *
 * `difficulty_level` was on every room from the start and read three ways —
 * a fill on each bar, a word on each row of "Room by room", and nothing else.
 * All three describe one room. None of them answers the question the screen
 * exists for, which is what has happened across the run, and the ladder is the
 * one series in this product where the answer is not a matter of opinion:
 * `calibration.py` moves it only on measured performance.
 *
 * **It speaks about the room and never about the presenter.** That is not
 * softness, it is the same line every other decision here holds — the screen
 * refuses totals, averages and verdicts because difficulty escalates
 * underneath them. "The room you get now is Relentless" is a fact about a room
 * somebody sat in. "You have improved" is a grade, and a grade is what this
 * screen exists without.
 */
describe('how hard the room has become', () => {
  it('says where the ladder started and where it stands now', async () => {
    // The default fixture: r-1 opened its lineage at Gentle, r-4 opened a
    // second one at Relentless. Those two read the account's dial; r-2, r-3
    // and r-5 inherited a rung from the lineage they repeat.
    await setup();

    expect(
      screen.getByText(/Your first room was Gentle\. The room you get now is Relentless\./),
    ).toBeOnTheScreen();
  });

  it('explains that the panel moves on its own, so nobody reads it as a setting', async () => {
    // Without this the sentence is a mystery: a presenter who does not know
    // the ladder exists has no way to tell whether something was done to them
    // or by them, and the answer is neither.
    await setup();

    expect(screen.getByText(/presses harder or eases off on its own/i)).toBeOnTheScreen();
  });

  it('says nothing at all when the ladder has not moved', async () => {
    // Two arguments, both opened at Standard. Nothing has happened, and a
    // sentence reporting that is a sentence about nothing — the same null
    // `DebriefService.pressed` returns in the identical case.
    await setup({
      rooms: [
        { sessionId: 'b', rehearsalId: 'b', rehearsalName: null, startedAt: '2026-08-19T09:00:00Z', challenged: 6, held: 5, level: 2 },
        { sessionId: 'a', rehearsalId: 'a', rehearsalName: null, startedAt: '2026-08-11T09:00:00Z', challenged: 4, held: 3, level: 2 },
      ],
    });

    expect(screen.queryByText(/The room you get now/)).toBeNull();
  });

  it('says the room eased off without saying anybody got worse', async () => {
    // The ladder descends at half a room fumbled, and that is #55 protecting
    // somebody rather than grading them: "a first session that destroys the
    // user produces churn, not resilience."
    //
    // So the descent is shown — hiding it would make the sentence a reward
    // rather than a fact — and it is shown as something the room did.
    await setup({
      rooms: [
        { sessionId: 'b', rehearsalId: 'b', rehearsalName: null, startedAt: '2026-08-19T09:00:00Z', challenged: 6, held: 1, level: 1 },
        { sessionId: 'a', rehearsalId: 'a', rehearsalName: null, startedAt: '2026-08-11T09:00:00Z', challenged: 4, held: 3, level: 3 },
      ],
    });

    expect(
      screen.getByText(/Your first room was Relentless\. The room you get now is Gentle\./),
    ).toBeOnTheScreen();
    // Never a grade, in either direction. This is the guard on the copy: the
    // sentence has to keep describing the room if somebody edits it later.
    expect(screen.queryByText(/better|worse|improv|declin/i)).toBeNull();
  });
});
