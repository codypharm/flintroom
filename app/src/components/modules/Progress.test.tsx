import { render, screen } from '@testing-library/react-native';

import { Progress, type ProgressProps } from './Progress';

/**
 * Whether somebody is getting better.
 *
 * Asked for directly: *"user is meant to track their development — how would
 * they if they were not scored per session"*. What is refused is a
 * **delivery-metrics** score — `Product.md:392` — not a figure about whether an
 * argument held. These tests hold the line between the two.
 */

const ROOMS = [
  { sessionId: 'r-3', startedAt: '2026-08-20T09:12:00Z', challenged: 9, held: 8, level: 3 },
  { sessionId: 'r-2', startedAt: '2026-08-17T16:04:00Z', challenged: 7, held: 4, level: 2 },
  { sessionId: 'r-1', startedAt: '2026-08-11T11:00:00Z', challenged: 6, held: 2, level: 1 },
];

async function setup(overrides: Partial<ProgressProps> = {}) {
  const props: ProgressProps = {
    rooms: ROOMS,
    habits: [
      { name: 'evasive', rooms: 3 },
      { name: 'contradicted', rooms: 1 },
    ],
    askers: [{ name: 'cfo', rooms: 3 }],
    ...overrides,
  };

  await render(<Progress {...props} />);
  return props;
}

it('says what held in the most recent room, with the level it was earned at', async () => {
  // The two are never apart. Difficulty escalates, so eight of nine at the
  // hardest setting and eight of nine at the gentlest are different facts, and
  // a figure without its rung is the one that would tell an improving
  // presenter they are getting worse.
  await setup();

  expect(screen.getByText('8 of 9')).toBeTruthy();
  expect(screen.getByText(/most relentless/i)).toBeTruthy();
});

it('names the habit rather than counting the findings', async () => {
  // "Answered a different question, in three of your rooms" tells somebody what
  // to change. A number does not, and the habit wording is the same one the
  // debrief and the prep sheet already use.
  await setup();

  expect(screen.getByText(/Answered a different question/)).toBeTruthy();
  expect(screen.getByText(/three of your last three rooms/i)).toBeTruthy();
});

it('names who keeps getting past them', async () => {
  await setup();

  expect(screen.getByText(/The CFO/)).toBeTruthy();
});

it('never averages across rooms that were not equally hard', async () => {
  // The arithmetic that would lie. Rooms at different rungs are not
  // comparable, so there is no total, no average, and no percentage anywhere.
  await setup();

  expect(screen.queryByText(/average/i)).toBeNull();
  expect(screen.queryByText(/\d+\s*%/)).toBeNull();
});

it('puts no grade on anything', async () => {
  await setup();

  expect(screen.queryByText(/^[A-F][+-]?$/)).toBeNull();
  expect(screen.queryByText(/score/i)).toBeNull();
});

it('says nothing about pace, filler, or confidence', async () => {
  // The commodity layer, named in Product.md §1 as what this product refuses.
  // It is also literally unmeasurable here — nothing in the pipeline hears how
  // somebody spoke, only what they said.
  await setup();

  for (const delivery of [/pacing/i, /filler/i, /confiden/i, /clarity/i, /eye contact/i]) {
    expect(screen.queryByText(delivery)).toBeNull();
  }
});

describe('an account with no history', () => {
  it('says there is nothing yet rather than drawing an empty chart', async () => {
    await setup({ rooms: [], habits: [], askers: [] });

    expect(screen.getByText('Nothing to compare yet')).toBeTruthy();
  });

  it('says nothing about habits after a single room', async () => {
    // One room is not a pattern, and calling it one would tell somebody their
    // worst afternoon is who they are.
    await setup({
      rooms: [ROOMS[0]],
      habits: [{ name: 'evasive', rooms: 1 }],
      askers: [{ name: 'cfo', rooms: 1 }],
    });

    expect(screen.queryByText(/Answered a different question/)).toBeNull();
  });
});
