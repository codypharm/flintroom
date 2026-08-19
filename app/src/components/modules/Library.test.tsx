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

it('places each room in time the way somebody would say it', async () => {
  await setup();

  expect(screen.getByText('Today')).toBeTruthy();
  expect(screen.getByText('Monday')).toBeTruthy();
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

  await userEvent.press(screen.getByLabelText('Today, The CFO and The Technical Skeptic'));

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
