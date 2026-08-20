import { AUTHORED_PREFIX, isAuthored, railFor } from './rail';

const SHIPPED = [
  { name: 'cfo', title: 'The CFO', blurb: 'Unimpressed.' },
  { name: 'champion', title: 'The Champion', blurb: 'Wants ammunition.' },
];

const MINE = [
  {
    name: 'custom:0191d4c2',
    title: 'The Board Chair',
    persona: 'Unimpressed by anything that is not a number.',
    domains: ['margin'],
    voice: null,
  },
];

it('leaves the shipped order exactly where it was', () => {
  // The rail is scrolled from the left every time. Putting a new panelist first
  // would move seven familiar cards to make room for one.
  const rail = railFor(SHIPPED, MINE);

  expect(rail.slice(0, 2)).toEqual(SHIPPED);
});

it('puts the ones you wrote at the end, where the row that wrote them is', () => {
  const rail = railFor(SHIPPED, MINE);

  expect(rail[2].name).toBe('custom:0191d4c2');
  expect(rail[2].title).toBe('The Board Chair');
});

it('shows their own words on the card', () => {
  // A shipped blurb exists so a picker never prints the attack strategy. That
  // reasoning is untouched — the strategy is ours and is not in this text.
  const rail = railFor(SHIPPED, MINE);

  expect(rail[2].blurb).toBe('Unimpressed by anything that is not a number.');
});

it('is just the shipped roster for an account that has written none', () => {
  expect(railFor(SHIPPED, [])).toEqual(SHIPPED);
});

it('knows a panelist somebody wrote from one we ship', () => {
  // The prefix is minted server-side and held by a check constraint, so this is
  // a reliable test rather than a heuristic. It is what the picker uses to
  // enforce the shipped-archetype floor before Start does.
  expect(isAuthored('custom:0191d4c2')).toBe(true);
  expect(isAuthored('cfo')).toBe(false);
});

it('matches the prefix the server mints', () => {
  // Duplicated across the wire, which is what a contract is. The server pins
  // its own copy in test_the_prefix_is_the_same_string_in_both_places; this is
  // the other end, so the two cannot drift silently.
  expect(AUTHORED_PREFIX).toBe('custom:');
});
