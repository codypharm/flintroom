import { fireEvent, render, screen } from '@testing-library/react-native';

import { TablePlan, type Plan } from './TablePlan';

/**
 * The plan somebody fills in before their first room.
 *
 * These tests are about the rules the screen has to keep, not its appearance.
 * The load-bearing one is first: a chair is a control, and the order chairs are
 * filled in survives — because the server seats them in that order and the
 * reveal shows the result back.
 */

const EMPTY: Plan = {
  situation: null,
  happensOn: null,
  role: null,
  audience: [],
  difficulty: 2,
};

function plan(over: Partial<Plan> = {}) {
  return { ...EMPTY, ...over };
}

async function show(
  over: Partial<Plan> = {},
  props: Partial<Parameters<typeof TablePlan>[0]> = {}
) {
  const onChange = jest.fn();
  await render(
    <TablePlan
      seats={3}
      hardest={3}
      plan={plan(over)}
      busy={false}
      onChange={onChange}
      onPickDate={jest.fn()}
      onContinue={jest.fn()}
      {...props}
    />
  );
  return onChange;
}

describe('TablePlan', () => {
  it('seats somebody when their chair is tapped', async () => {
    const onChange = await show();

    fireEvent.press(screen.getByText('Controls the budget'));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ audience: ['budget'] })
    );
  });
});

describe('TablePlan, continued', () => {
  it('shows the order the chairs were filled in', async () => {
    // Not decoration. The server seats archetypes in this order, so chair one
    // really does speak first — a plan that hid its own order would ask for a
    // decision and then refuse to show it back.
    await show({ audience: ['ally', 'budget'] });

    expect(screen.getByLabelText(/Already on your side, in chair 1/)).toBeTruthy();
    expect(screen.getByLabelText(/Controls the budget, in chair 2/)).toBeTruthy();
  });

  it('says a full table is full, without hiding the chairs it cannot seat', async () => {
    // Dimmed and announced, never removed. A chair that vanished would read as
    // the app losing options rather than as a plan reaching its size.
    await show({ audience: ['budget', 'technical', 'ally'] });

    expect(screen.getByLabelText(/Legal, risk or compliance\. The table is full\./)).toBeTruthy();
  });

  it('still lets a seated person be taken out of a full table', async () => {
    // The bug this guards is a cap applied to every chair rather than to empty
    // ones, which locks somebody out of editing their own answer.
    const onChange = await show({ audience: ['budget', 'technical', 'ally'] });

    fireEvent.press(screen.getByText('The technical lead'));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ audience: ['budget', 'ally'] })
    );
  });

  it('never names a room this product has not built', async () => {
    // `docs/onboarding.md`, amended 2026-08-18: a picker option is a promise.
    // Listing the v2 cases would tell every user the product does interviews
    // and then refuse them — and would make the reveal show a CFO to somebody
    // who asked for a hiring manager. "Something else" catches them instead.
    await show();

    expect(screen.queryByText(/interview|performance review|negotiation|salary/i)).toBeNull();
    expect(screen.getByText('Something else')).toBeTruthy();
  });

  it('shows no progress indicator of any kind', async () => {
    // The whole plan is one sheet, so its own length is the progress. A counter
    // here would be measuring an anxiety it had just created — and `CLAUDE.md`
    // forbids a depleting count anywhere in the product.
    await show({ audience: ['budget'] });

    expect(screen.queryByText(/\d\s*(of|\/)\s*\d/)).toBeNull();
    expect(screen.queryByText(/step|question \d|remaining|left/i)).toBeNull();
  });

  it('offers the free minutes as a gift rather than as a balance', async () => {
    await show();

    expect(screen.getByText(/15 minutes in the room, on us/)).toBeTruthy();
  });

  it('locks every control while the plan is being sent', async () => {
    // One send at a time. A second tap mid-flight would post the plan twice and
    // append a second situation row for one meeting.
    const onChange = await show({}, { busy: true });

    fireEvent.press(screen.getByText('Controls the budget'));
    fireEvent.press(screen.getByText('An investor pitch'));

    expect(onChange).not.toHaveBeenCalled();
  });

  it('treats no date as an answer rather than as something missing', async () => {
    await show();

    expect(screen.getByText('Not sure yet')).toBeTruthy();
    expect(screen.queryByText(/required|please|must/i)).toBeNull();
  });
});

it('draws the date as a statement when there is no picker to open', async () => {
  // A control that opens nothing is worse than a statement — `PanelSetup` made
  // the same call about authoring an archetype. Until the native picker lands,
  // this row says what it knows and does not pretend to be tappable.
  await show({}, { onPickDate: null });

  expect(screen.queryByLabelText(/Tap to say when/)).toBeNull();
  expect(screen.getByText('Not sure yet')).toBeTruthy();
});
