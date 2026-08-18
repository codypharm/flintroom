import { render, screen, userEvent } from '@testing-library/react-native';

import { PanelSetup, type PanelSetupProps } from './PanelSetup';

/**
 * The last screen before somebody is attacked on purpose.
 *
 * These tests are about what the screen states and lets somebody do. The
 * composition belongs to the brief; what must not drift is the product truth
 * underneath it — that a seat is an input to the room and not a decoration,
 * that the picker never publishes what a panelist will attack, and that Start
 * refuses out loud rather than failing at the server.
 */

const LIBRARY = [
  { name: 'cfo', title: 'The CFO', blurb: 'Unhurried, unimpressed, and not interested in vision until the arithmetic holds.' },
  { name: 'champion', title: 'The Champion', blurb: 'On your side, and needs something they can carry into the room you are not in.' },
  { name: 'technical_skeptic', title: 'The Technical Skeptic', blurb: 'Has seen a demo before and wants to know what happens at ten times the load.' },
  { name: 'risk_officer', title: 'The Risk Officer', blurb: 'Reads every plan for what happens when it goes wrong.' },
];

const ROOM = {
  archetypes: LIBRARY,
  seats: 3,
  mayAuthor: false,
  upgradeSeats: 5,
  difficulty: 1,
  hardest: 3,
};

async function setup(overrides: Partial<PanelSetupProps> = {}) {
  const props: PanelSetupProps = {
    room: ROOM,
    seated: [],
    onSeatedChange: jest.fn(),
    material: null,
    onAttach: jest.fn(),
    onDifficultyChange: jest.fn(),
    onStart: jest.fn(),
    ...overrides,
  };
  await render(<PanelSetup {...props} />);
  return props;
}

it('seats somebody, and says which chair they took', async () => {
  // The seat is not a tick. `SessionStart.archetypes` carries order through
  // rather than sorting it, and `routing.choose` breaks a scoring tie on the
  // panel's own index — so the chair a user gives an archetype is a real input
  // to who speaks. Showing the position is the one structural device on this
  // screen, and it is here because it encodes something true rather than
  // because a selected row needs decorating.
  const props = await setup({ seated: ['champion'] });

  expect(screen.getByLabelText('The Champion, seated first')).toBeTruthy();

  await userEvent.press(screen.getByText('The CFO'));

  expect(props.onSeatedChange).toHaveBeenCalledWith(['champion', 'cfo']);
});

it('never says what a panelist will go after', async () => {
  // `Archetype.blurb` exists precisely so this screen can name who is in the
  // chair without publishing `attack_strategy`. A picker that printed the
  // strategy would be a rehearsal the user has already had, and the product is
  // a room that gets past what they prepared for.
  await setup();

  expect(screen.getByText(/not interested in vision until the arithmetic holds/)).toBeTruthy();
  expect(screen.queryByText(/Attack the numbers/)).toBeNull();
});

it('stops seating at the plan’s cap, and says what the next one seats', async () => {
  // `assemble` refuses an over-large panel server-side, so the screen refusing
  // first is not belt-and-braces — it is the difference between a user learning
  // the cap by being told and learning it by having Start fail.
  //
  // The upgrade is stated as a number and nothing else. The API states the
  // fact; the client renders the prompt, and on this screen the prompt is a
  // sentence rather than a button, because a paywall does not belong between
  // somebody and a rehearsal.
  const props = await setup({ seated: ['cfo', 'champion', 'technical_skeptic'] });

  expect(screen.getByText('Three of three seated. Pro seats five.')).toBeTruthy();

  await userEvent.press(screen.getByText('The Risk Officer'));
  expect(props.onSeatedChange).not.toHaveBeenCalled();

  // A seated one still lets go, or the cap becomes a trap.
  await userEvent.press(screen.getByText('The CFO'));
  expect(props.onSeatedChange).toHaveBeenCalledWith(['champion', 'technical_skeptic']);
});

it('shows that writing your own exists, even where the plan cannot', async () => {
  // `may_author` is published even when false, deliberately: a picker that hid
  // it is how somebody never learns the capability is there. Shown as a fact,
  // not as a locked door with a price on it.
  await setup();

  expect(screen.getByText('Write your own')).toBeTruthy();
  expect(screen.getByText('On Pro')).toBeTruthy();
});

it('offers three rungs and says what each one does', async () => {
  // Words, never a number. `docs/difficulty-calibration.md` decision 5: a level
  // on screen is a score, and a score is the delivery-metrics product the wedge
  // refuses. What is published instead is what the room will actually do.
  const props = await setup({ room: { ...ROOM, difficulty: 2 } });

  expect(screen.getByLabelText('Firm, selected')).toBeTruthy();

  await userEvent.press(screen.getByText('Relentless'));

  expect(props.onDifficultyChange).toHaveBeenCalledWith(3);
});

it('says out loud that the gentlest room still follows up', async () => {
  // Decision 4, made visible. The floor softens the interruptions and never
  // the press, because a room that lets an unanswered question go is not a
  // gentler version of this product — it is the delivery coach the wedge
  // exists to refuse. Somebody dragging this to the bottom should be able to
  // see they have not turned that off.
  await setup({ room: { ...ROOM, difficulty: 1 } });

  expect(screen.getByText('They follow up once. Nobody talks over you.')).toBeTruthy();
});

it('starts a room with nothing attached', async () => {
  // The deckless case is first-class, not degraded. `docs/auditor-grounding.md`
  // gives the panel plenty to attack without a deck, and somebody who does not
  // want to wait for extraction starts without one rather than being blocked.
  const props = await setup({ seated: ['cfo'] });

  await userEvent.press(screen.getByText('Start'));

  expect(props.onStart).toHaveBeenCalled();
});

it('refuses to start on a deck that is still being read, and says why', async () => {
  // `confirm_ready` refuses an unready deck server-side, so without this the
  // user learns by watching Start fail. Naming the reason is the difference
  // between a screen that waited with them and one that broke.
  const props = await setup({
    seated: ['cfo'],
    material: { id: 'm-1', filename: 'Q3 board deck.pdf', state: 'extracting' },
  });

  expect(screen.getByText('Still reading Q3 board deck.pdf.')).toBeTruthy();

  await userEvent.press(screen.getByText('Start'));

  expect(props.onStart).not.toHaveBeenCalled();
});

it('starts on a deck it has finished reading', async () => {
  const props = await setup({
    seated: ['cfo'],
    material: { id: 'm-1', filename: 'Q3 board deck.pdf', state: 'ready' },
  });

  await userEvent.press(screen.getByText('Start'));

  expect(props.onStart).toHaveBeenCalled();
});

it('will not start an empty room', async () => {
  // `assemble` seats the shipped default when no archetypes are given, so an
  // empty POST would quietly produce a room the user did not choose. Better to
  // ask than to seat somebody on their behalf and let them meet a panel they
  // never picked.
  const props = await setup({ seated: [] });

  await userEvent.press(screen.getByText('Start'));

  expect(props.onStart).not.toHaveBeenCalled();
});
