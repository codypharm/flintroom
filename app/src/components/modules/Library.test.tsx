import { render, screen, userEvent } from '@testing-library/react-native';

import { Library, type LibraryProps } from './Library';

/**
 * Every room already run.
 *
 * The first screen in this product that is about a history rather than about
 * one room. Two things bring somebody here: reading a room back, and running
 * one again — the architect's own definition, "a browser for all past sessions
 * in case you want to view the detail of discussion or play it and listen to
 * it".
 *
 * What it must not become is a scoreboard. The retired `design-guide/library/`
 * mockup filters by "High Scores (A)" and puts an "A-" in a circle on every
 * card, with "Pacing: Good" and "Clarity: High" beneath — the delivery-metrics
 * product §1 exists to refuse, wearing this product's colours.
 */

const ROOMS = [
  {
    id: 'room-2',
    rehearsalId: 'room-2',
    rehearsalName: null,
    audience: null,
    difficultyLevel: 2,
    state: 'settled',
    startedAt: '2026-08-20T09:12:00Z',
    endReason: 'user_ended',
    settledAt: '2026-08-20T09:23:41Z',
    archetypes: ['cfo', 'technical_skeptic'],
    materialIds: ['m-7'],
    recording: { state: 'available' as const, expiresAt: '2026-09-19T09:23:41Z' },
  },
  {
    id: 'room-1',
    rehearsalId: 'room-1',
    rehearsalName: null,
    audience: null,
    difficultyLevel: 2,
    state: 'settled',
    startedAt: '2026-08-17T16:04:00Z',
    endReason: 'idle_timeout',
    settledAt: '2026-08-17T16:09:12Z',
    archetypes: ['champion'],
    materialIds: [],
    recording: { state: 'expired' as const, expiresAt: null },
  },
];

const NOW = new Date('2026-08-20T14:00:00Z');

async function setup(overrides: Partial<LibraryProps> = {}) {
  const props: LibraryProps = {
    rooms: ROOMS,
    now: NOW,
    onOpen: jest.fn(),
    onRunAgain: jest.fn(),
    onStart: jest.fn(),
    ...overrides,
  };

  await render(<Library {...props} />);
  return props;
}

it('places each room by how long ago AND by when, not one or the other', async () => {
  // The architect's ask: "days ago or years ago or seconds ago basically diff
  // from current time along side date instead of days of the week."
  //
  // The weekday it replaces was right for the week you are living in and wrong
  // the moment a history got long enough to be worth having — "Monday" could be
  // any Monday, and past a week it fell back to a bare date that said when
  // without saying how long. Which answer you got depended on when you asked.
  // Drawn as two registers rather than one string. The headline scans — it is
  // how you find the room — and the date sits quiet underneath, because it is
  // the half you look up rather than the half you sweep past. A 20pt headline
  // holding both clipped its own date on a phone.
  await setup();

  expect(screen.getByText('4 hours ago')).toBeTruthy();
  expect(screen.getByText('20 August')).toBeTruthy();
  expect(screen.getByText('3 days ago')).toBeTruthy();
  expect(screen.getByText('17 August')).toBeTruthy();
});

it('still says the whole placement in one breath to a screen reader', async () => {
  // The split is visual. Read aloud, "4 hours ago · 20 August" is one fact
  // about when a room ran, and a reader that had to stitch it back together
  // from two nodes several lines apart would be worse off than the eye.
  await setup();

  expect(
    screen.getByLabelText('4 hours ago · 20 August, The CFO and The Technical Skeptic'),
  ).toBeTruthy();
});

it('says who was in the room, so it can be told from the others', async () => {
  // The only thing that distinguishes two rooms run on the same afternoon, and
  // the thing somebody is actually looking for: not "a rehearsal", but "the one
  // where the CFO was there".
  await setup();

  expect(screen.getByText('The CFO and The Technical Skeptic')).toBeTruthy();
});

it('opens the room that was tapped', async () => {
  const { onOpen } = await setup();

  await userEvent.press(screen.getByLabelText('4 hours ago · 20 August, The CFO and The Technical Skeptic'));

  expect(onOpen).toHaveBeenCalledWith('room-2');
});

it('runs a room again with the panel it had', async () => {
  // The whole reason this needs no new endpoint: the seating and the grounding
  // came back with the list, so running it again is a start with values already
  // in hand rather than a rebuild from an empty screen.
  const { onRunAgain } = await setup();

  await userEvent.press(screen.getAllByLabelText('Run this room again')[0]);

  expect(onRunAgain).toHaveBeenCalledWith(ROOMS[0]);
});

it('offers no re-run for a room that never seated anybody', async () => {
  // A room that failed to provision has no archetypes, so "run it again" would
  // quietly seat the default panel instead — which is a different room wearing
  // the label of the one that failed.
  await setup({
    rooms: [
      {
        id: 'room-0',
        rehearsalId: 'room-0',
        rehearsalName: null,
        audience: null,
        difficultyLevel: null,
        state: 'failed',
        startedAt: '2026-08-19T19:02:27Z',
        endReason: 'provisioning_failed',
        settledAt: null,
        archetypes: [],
        materialIds: [],
        recording: { state: 'not_recorded' as const, expiresAt: null },
      },
    ],
  });

  expect(screen.queryByLabelText('Run this room again')).toBeNull();
});

it('never marks, grades, or ranks a room', async () => {
  // `design-guide/library/` filters by "High Scores (A)" and puts an "A-" on
  // every card. Product.md:392 — delivery-metrics scoring is the commodity
  // layer and is not the product.
  await setup();

  expect(screen.queryByText(/^[A-F][+-]?$/)).toBeNull();
  expect(screen.queryByText(/score/i)).toBeNull();
  expect(screen.queryByText(/\d+\s*%/)).toBeNull();
});

it('says nothing about minutes, cost, or an upgrade', async () => {
  // A screen full of past rooms is exactly where a depleting counter would be
  // tempting to put, and §4.6 forbids one outright.
  await setup();

  for (const forbidden of [/minutes? left/i, /remaining/i, /credit/i, /upgrade/i]) {
    expect(screen.queryByText(forbidden)).toBeNull();
  }
});

describe('an account with nothing in it', () => {
  it('says so plainly, and offers the only thing there is to do', async () => {
    // Library is the tab most likely to be opened before there is anything in
    // it. An empty list with a heading over it reads as a failure to load.
    const { onStart } = await setup({ rooms: [] });

    expect(screen.getByText('No rooms yet')).toBeTruthy();

    await userEvent.press(screen.getByLabelText('Start a room'));
    expect(onStart).toHaveBeenCalled();
  });
});

describe('what the room was about', () => {
  it('leads with the name when the rehearsal has one', async () => {
    // What actually distinguishes two rooms is one line of text, and until the
    // presenter could name a rehearsal the best this screen had was a date and
    // a panel. "Q3 board readout" is what somebody is looking for; "3 days ago" is
    // how they narrow it down once they have found the right pile.
    await setup({
      rooms: [{ ...ROOMS[0], rehearsalName: 'Q3 board readout' }],
    });

    expect(screen.getByText('Q3 board readout')).toBeTruthy();
    expect(
      screen.getByLabelText('Q3 board readout, 4 hours ago · 20 August, The CFO and The Technical Skeptic')
    ).toBeTruthy();
  });

  it('still places a named room in time', async () => {
    // The date is demoted, not dropped. A rehearsal run five times is five rows
    // with the same headline, and the only thing telling them apart is when.
    await setup({
      rooms: [{ ...ROOMS[0], rehearsalName: 'Q3 board readout' }],
    });

    expect(screen.getByText(/4 hours ago/)).toBeTruthy();
  });

  it('heads an unnamed room with how long ago it ran, and invents nothing', async () => {
    // A heading derived from the panel or the deck would be a label the
    // presenter never chose and cannot correct. So the fallback is a fact:
    // when it was. The relative half takes the headline because it is what
    // somebody scans by; the date is on the line below.
    await setup();

    expect(screen.getByText('4 hours ago')).toBeTruthy();
  });
});
