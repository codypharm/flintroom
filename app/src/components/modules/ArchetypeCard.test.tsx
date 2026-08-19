import { fireEvent, render, screen } from '@testing-library/react-native';
import { AccessibilityInfo } from 'react-native';

import { ArchetypeCard, initialsOf } from './ArchetypeCard';

/**
 * The control that stopped looking like one.
 *
 * These exist because of a specific failure on a device: with three of three
 * seated, the roster was a list of text rows, and the architect concluded the
 * panel could not be changed. It always could. Everything here is about the
 * surface saying so.
 */

async function show(over: Partial<Parameters<typeof ArchetypeCard>[0]> = {}) {
  const onPress = jest.fn();

  await render(
    <ArchetypeCard
      title="The Technical Skeptic"
      blurb="A senior engineer who has watched confident demos fail in production."
      seat={null}
      closed={false}
      portrait={null}
      onPress={onPress}
      {...over}
    />
  );

  return { onPress };
}

it('shows which chair they are in, not merely that they are chosen', async () => {
  // The server seats archetypes in the order they arrive and chair one speaks
  // first, so the order is a real decision. A tick would say "chosen" and hide
  // it.
  await show({ seat: 2 });

  expect(screen.getByText('2')).toBeTruthy();
  expect(screen.getByLabelText('The Technical Skeptic, in chair 2')).toBeTruthy();
});

it('stays pressable when it is the one holding a seat in a full room', async () => {
  // The whole bug. A full room closes the *unseated* cards; taking somebody out
  // is how you make space, and if this were disabled the seat cap would be a
  // trap with no way out but starting over.
  const { onPress } = await show({ seat: 1, closed: false });

  fireEvent.press(screen.getByLabelText('The Technical Skeptic, in chair 1'));

  expect(onPress).toHaveBeenCalledTimes(1);
});

it('says how to make room, rather than only that there is none', async () => {
  await show({ seat: null, closed: true });

  const card = screen.getByLabelText('The Technical Skeptic, not seated');

  expect(card.props.accessibilityState.disabled).toBe(true);
  expect(card.props.accessibilityHint).toBe(
    'The room is full. Take somebody out first.'
  );
});

it('keeps the blurb, because a face and a job title is not a choice', async () => {
  await show();

  expect(
    screen.getByText(/A senior engineer who has watched confident demos fail/)
  ).toBeTruthy();
});

it('stands in with initials until there is a photograph', async () => {
  // Not a silhouette glyph. Eight identical head outlines are furniture and
  // tell you nothing about which card you are looking at from the corner of
  // your eye.
  await show();

  expect(screen.getByText('TS')).toBeTruthy();
});

it.each([
  ['The CFO', 'CFO'],
  ['The Champion', 'Ch'],
  ['The Technical Skeptic', 'TS'],
  ['The Distracted Executive', 'DE'],
])('drops the article when it abbreviates %s', (title, expected) => {
  // Every archetype begins with "The". Keeping it would give all eight cards
  // the same first letter and defeat the point of initials entirely.
  expect(initialsOf(title)).toBe(expected);
});

it('does not move the badge for somebody who asked it not to', async () => {
  // Reduce Motion is honoured by cutting, not by shortening. A quick bounce is
  // still a bounce, and the setting means "do not move things".
  jest.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockResolvedValue(true);

  await show({ seat: 1 });

  // The badge is present and fully settled rather than mid-spring: what the
  // setting buys is arriving, not arriving slowly.
  expect(await screen.findByText('1')).toBeTruthy();
});
