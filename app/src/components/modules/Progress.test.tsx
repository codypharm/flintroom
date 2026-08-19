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

const ROOMS = [
  { sessionId: 'r-5', startedAt: '2026-08-20T09:12:00Z', challenged: 9, held: 8, level: 3 },
  { sessionId: 'r-4', startedAt: '2026-08-19T16:04:00Z', challenged: 7, held: 4, level: 3 },
  { sessionId: 'r-3', startedAt: '2026-08-17T11:00:00Z', challenged: 6, held: 2, level: 2 },
  { sessionId: 'r-2', startedAt: '2026-08-14T11:00:00Z', challenged: 5, held: 1, level: 2 },
  { sessionId: 'r-1', startedAt: '2026-08-11T11:00:00Z', challenged: 4, held: 0, level: 1 },
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
        { sessionId: 'r-0', startedAt: '2026-08-10T11:00:00Z', challenged: 0, held: 0, level: 2 },
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
