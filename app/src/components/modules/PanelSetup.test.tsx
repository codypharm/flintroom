import { fireEvent, render, screen, userEvent, within } from '@testing-library/react-native';

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
    limits: null,
    onAttach: jest.fn(),
    onRemoveMaterial: jest.fn(),
    onDifficultyChange: jest.fn(),
    onStart: jest.fn(),
    onAuthor: jest.fn(),
    rehearsalName: '',
    onRehearsalNameChange: jest.fn(),
    audience: '',
    onAudienceChange: jest.fn(),
    onReset: jest.fn(),
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

  expect(screen.getByLabelText('The Champion, in chair 1')).toBeTruthy();

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

  expect(screen.getByText('Three of three seated. Tap someone to swap them out. Pro seats five.')).toBeTruthy();

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

  expect(screen.getByText('Add your own')).toBeTruthy();
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

it('offers the way out only once the room is full', async () => {
  // A full room dims every unseated archetype, and dimmed reads as locked. The
  // swap was always allowed — `closed` is `full && !isSeated`, so a seated one
  // is still pressable — but nothing said so, and somebody on a device
  // concluded the panel could not be changed at all. Said only when it is
  // needed: on a half-empty room it would be an instruction for a problem
  // nobody has.
  await setup({ seated: ['cfo'] });
  expect(screen.queryByText(/Tap someone to swap them out/)).toBeNull();

  await setup({ seated: ['cfo', 'technical_skeptic', 'champion'] });
  expect(screen.getByText(/Tap someone to swap them out/)).toBeTruthy();
});

it('says back the room that was built, in the order it will speak', async () => {
  // Everything above this line is eight cards, a file row and three pills. The
  // screen never once said what any of it added up to, which left Start a
  // button at the bottom of a scroll rather than the door into a specific
  // room.
  //
  // Order carries information: the server seats archetypes as they arrive and
  // chair one takes the floor first, so "then" is a fact about the next twelve
  // minutes rather than a list separator.
  await setup({ seated: ['champion', 'cfo'] });

  expect(
    screen.getByText('The Champion, then the CFO. They push gentle.')
  ).toBeTruthy();
});

it('does not apologise for a room with nothing attached', async () => {
  // Material is an optional enrichment (§3.2) and pitching cold is a supported
  // way to use this. Naming the absence would turn a deliberate choice into a
  // missing step.
  await setup({ seated: ['cfo'], material: null });

  expect(screen.queryByText(/nothing attached|no deck/i)).toBeNull();
});

it('names the deck the room is grounded in, once one is ready', async () => {
  await setup({
    seated: ['cfo'],
    material: { id: 'm-1', filename: 'Q3 board deck.pdf', state: 'ready' },
  });

  expect(screen.getByText(/over Q3 board deck\.pdf/)).toBeTruthy();
});

it('shows why it cannot start instead of the room, when it cannot start', async () => {
  // The two occupy one slot on purpose. A summary of a room nobody can enter,
  // sitting above a dead button, is the screen talking past the problem.
  await setup({ seated: [] });

  expect(screen.queryByText(/They push/)).toBeNull();
});

it('says why before the button it is holding up, never after it', async () => {
  // One slot, on one side. The reason used to sit below Start while the summary
  // sat above it, so seating the first archetype added a block above the button
  // and removed one below it in the same frame — the control moved under the
  // thumb reaching for it.
  //
  // It is also the order the screen is read in. A reader landing on a dimmed
  // Start was told it could not be pressed, then had to swipe past it to find
  // out what to do about that.
  await setup({ seated: [] });

  const drawn = JSON.stringify(screen.toJSON());
  const why = drawn.indexOf('"Seat at least one of them."');

  expect(why).toBeGreaterThan(-1);
  expect(why).toBeLessThan(drawn.indexOf('"Start"'));
});

it('says how many archetypes there are, because the rail cannot', async () => {
  // The rail shows two cards and a sliver of a third, and that sliver is a
  // white card against a warm off-white margin — present on screen and
  // invisible to a person. Measured on a device: no way to tell the list
  // continued. A number is legible, and a screen reader gets it too.
  await setup();

  expect(screen.getByText('four to choose from')).toBeTruthy();
});

it('puts the deck before the panel, so extraction runs while they decide', async () => {
  // Sequence, not hierarchy. Extraction is asynchronous and `setup.tsx` polls
  // while the server reads the file, so attaching first overlaps that wait
  // with the decisions somebody is making anyway instead of leaving it
  // standing in front of Start.
  await setup();

  const order = screen
    .getAllByRole('header')
    .map((node) => node.props.children)
    .filter((child) => typeof child === 'string');

  expect(order.indexOf('What they can attack')).toBeLessThan(
    order.indexOf('Who is in the room')
  );
});


it('puts writing your own outside the rail, where nothing must be swiped', async () => {
  // Reported: "people will not know it is there based on how it is now." It was
  // the ninth card in a rail of eight, which is exactly the hiding this
  // component's own note was written to prevent — `may_author` is published
  // false rather than omitted so the picker can say the capability exists.
  //
  // Asserted as "not inside the list" rather than by position, because the
  // point is reachability: a thing behind eight horizontal swipes is hidden
  // however it is ordered.
  await setup();

  const rail = within(screen.getByLabelText('Panelists to choose from'));

  expect(screen.getByText('Add your own')).toBeTruthy();
  expect(rail.queryByText('Write your own')).toBeNull();
});

it('opens the author when the plan includes it', async () => {
  // It has been drawn but inert since it was built, deliberately: "authoring
  // has no endpoint yet (#65), and a control that opens nothing is worse than a
  // statement." The endpoint exists now, so on Pro it becomes a control — and
  // on a plan without it, it stays exactly the statement it was.
  const props = await setup({ room: { ...ROOM, mayAuthor: true } });

  await userEvent.press(screen.getByLabelText('Write your own panelist'));

  expect(props.onAuthor).toHaveBeenCalled();
});

it('never puts a price on the row', async () => {
  // §4.5 keeps the upsell out of the way of a rehearsal. A fact and a plan
  // name, never a locked door with a number on it.
  await setup({ room: { ...ROOM, mayAuthor: false } });

  expect(screen.getByText('On Pro')).toBeTruthy();
  expect(screen.queryByText(/\$|month|upgrade now/i)).toBeNull();
});

it('will not start a room with nobody in it who can open it', async () => {
  // §3's floor, arriving where it was designed to: in the picker rather than as
  // a 422 on a screen somebody has already committed to. The server refuses it
  // either way — `panel_without_a_shipped_voice` — and the metering rules are
  // explicit that a room in progress is never where a constraint is discovered.
  //
  // A sentence rather than a bare disabled button, matching every other reason
  // Start holds: openers and nudges are hand-written per archetype, so a room
  // of only your own opens in silence AND reaps at ninety seconds with no
  // warning at sixty.
  const mine = { name: 'custom:0191d4c2', title: 'The Board Chair', blurb: 'Mine.' };

  await setup({
    room: { ...ROOM, archetypes: [...LIBRARY, mine] },
    seated: [mine.name],
  });

  expect(screen.getByText(/at least one of ours/i)).toBeTruthy();
});

it('starts happily once one of ours is beside them', async () => {
  const mine = { name: 'custom:0191d4c2', title: 'The Board Chair', blurb: 'Mine.' };

  await setup({
    room: { ...ROOM, archetypes: [...LIBRARY, mine] },
    seated: [mine.name, 'cfo'],
  });

  expect(screen.queryByText(/at least one of ours/i)).toBeNull();
});

it('offers to write one when there are none of yours yet', async () => {
  await setup({ room: { ...ROOM, mayAuthor: true } });

  expect(screen.getByText('Add your own')).toBeTruthy();
});

it('becomes the way into your own panel once you have written one', async () => {
  // One row, two jobs, and the second is what makes edit and retire reachable
  // at all. A first-time Pro user tapping "Write your own" and landing on an
  // empty list with another button is one tap too many; somebody with three of
  // their own needs a way back to them, and tapping a card in the rail seats it
  // rather than opening it.
  const mine = { name: 'custom:0191d4c2', title: 'The Board Chair', blurb: 'Mine.' };

  await setup({
    room: { ...ROOM, mayAuthor: true, archetypes: [...LIBRARY, mine] },
  });

  expect(screen.getByText('Your panelists')).toBeTruthy();
  expect(screen.queryByText('Add your own')).toBeNull();
});

it('shows an affordance only when the row opens something', async () => {
  // `TablePlan` decided this in the other direction: the date row "grows a
  // chevron only when there is something to open", because "a chevron on a
  // statement is a lie about what a tap does". The inverse is the same lie —
  // this row became a control and still looked like a caption, with a hairline
  // above it and nothing at all saying it could be pressed.
  await setup({ room: { ...ROOM, mayAuthor: true } });

  expect(screen.getByTestId('author-open')).toBeTruthy();
});

it('draws no affordance where the row is a statement', async () => {
  // On a plan without authoring it is a fact and a plan name, never a locked
  // door — §4.5 keeps the upsell out of the way of a rehearsal.
  await setup({ room: { ...ROOM, mayAuthor: false } });

  expect(screen.queryByTestId('author-open')).toBeNull();
  expect(screen.getByText('On Pro')).toBeTruthy();
});

it('stops saying Yours once the row itself says it', async () => {
  // "Yours" sat in the trailing slot on the one plan where the row is tappable,
  // telling somebody what the interaction already tells them — and occupying
  // the position an affordance belongs in. "On Pro" stays, because on that plan
  // it is the only thing carrying the fact.
  await setup({ room: { ...ROOM, mayAuthor: true } });

  expect(screen.queryByText('Yours')).toBeNull();
});

it('stops drawing an empty seat once the seats are filled', async () => {
  // The dashed circle means "a person who is not here yet" — right above "Write
  // your own", and false above "Your panelists", where three of them exist.
  const mine = { name: 'custom:0191d4c2', title: 'The Board Chair', blurb: 'Mine.' };

  await setup({
    room: { ...ROOM, mayAuthor: true, archetypes: [...LIBRARY, mine] },
  });

  expect(screen.getByText('1')).toBeTruthy();
  expect(screen.queryByTestId('author-empty-seat')).toBeNull();
});

it('says the count once, not twice', async () => {
  const mine = { name: 'custom:0191d4c2', title: 'The Board Chair', blurb: 'Mine.' };

  await setup({
    room: { ...ROOM, mayAuthor: true, archetypes: [...LIBRARY, mine] },
  });

  expect(screen.getByText('Add another, or change one.')).toBeTruthy();
});

it('says what somebody gets rather than what we lack', async () => {
  // "Somebody this product has never met" is a fact about our library, told
  // from our side of the screen. Nobody writes a panelist to fill our gap —
  // they write one because a particular person will be in the room on Thursday
  // and none of our eight is them.
  await setup({ room: { ...ROOM, mayAuthor: true } });

  // And says what it buys rather than only what it is. A row offering a
  // capability should name the payoff — the reason to spend five minutes
  // writing somebody is that the rehearsal gets closer to the real thing.
  expect(
    screen.getByText('Make the room closer to the one that matters.')
  ).toBeTruthy();
  expect(screen.queryByText(/this product has never met/i)).toBeNull();
});

describe('naming what is being rehearsed', () => {
  it('asks what this is, and reports what was typed', async () => {
    // A run of rooms headed by a date answers "am I getting better" and not
    // "am I getting better at my Q3 board readout", which is the question. The
    // words have to come from somewhere and nothing else in the product holds
    // them.
    const props = await setup();

    fireEvent.changeText(
      screen.getByLabelText('What you are rehearsing'),
      'Q3 board readout'
    );

    expect(props.onRehearsalNameChange).toHaveBeenCalledWith('Q3 board readout');
  });

  it('shows the name a re-run arrived with', async () => {
    // "Run it again" carries the lineage's name back onto this screen, so
    // somebody re-running a rehearsal sees what it is called rather than an
    // empty field asking them to name a thing that already has a name.
    await setup({ rehearsalName: 'Series B narrative' });

    expect(screen.getByDisplayValue('Series B narrative')).toBeTruthy();
  });

  it('starts a room nobody named', async () => {
    // Optional, and it has to stay optional. The field sits above the deck and
    // the panel, and a room that would not open without it would put a text
    // input between somebody and the thing they came to do.
    const props = await setup({ seated: ['cfo'], rehearsalName: '' });

    await userEvent.press(screen.getByText('Start'));

    expect(props.onStart).toHaveBeenCalled();
  });
});

/**
 * #66 — the permitted substitute for the profile scraping `Product.md` §3.1
 * refused. The user describes the room; nothing is fetched about anybody.
 */
describe('what the room is like', () => {
  it('asks, and hands back what was typed', async () => {
    const onAudienceChange = jest.fn();
    await setup({ onAudienceChange });

    fireEvent.changeText(
      screen.getByLabelText('What this audience is like'),
      'my VP hates anything that adds headcount',
    );

    expect(onAudienceChange).toHaveBeenCalledWith(
      'my VP hates anything that adds headcount',
    );
  });

  it('does not ask again who is in the room', async () => {
    // The panel rail below already answers "who are you presenting to" — it is
    // the decision this whole screen is for. A box asking it a second time
    // reads as a second picker, and the first person to see it on a device
    // asked what the panelists were for if this existed.
    //
    // What the box is actually for is the thing an archetype *cannot* carry:
    // the eight are shipped constants shared by every user, so "The CFO" knows
    // to attack cost and cannot know that in this company headcount is the
    // third rail. So it asks for what we could not have guessed.
    await setup();

    expect(screen.queryByLabelText('Who you are presenting to')).toBeNull();
    expect(
      screen.getByLabelText('What this audience is like'),
    ).toBeOnTheScreen();
  });

  it('shows what to write, because nobody knows what goes in an empty box', async () => {
    // Product.md §3.1's own example, verbatim. Measured against nothing, but
    // the feature is worthless if people cannot tell what belongs here, and one
    // concrete line does more than a paragraph of instruction.
    await setup();

    expect(
      screen.getByText(/my VP hates anything that adds headcount/),
    ).toBeOnTheScreen();
  });

  it('says what filling it in buys, and nothing about our own machinery', async () => {
    // It used to add "It is never read out." That sentence answers a question
    // no user has: nobody typing into a text box expects it to be recited back
    // at them, so the line explains a decision rather than the product, and
    // reading it is the first time the possibility occurs to anybody.
    //
    // "Shaped, never spoken" is still true, still enforced in the composer
    // prompt, and still the architect's choice — it is simply ours to hold
    // rather than the presenter's to be reassured about. The place a user can
    // read what happens to this text is docs/privacy-policy.md, where a
    // disclosure belongs.
    await setup();

    expect(screen.getByText(/Shapes what they press on/)).toBeOnTheScreen();
    expect(screen.queryByText(/never read out/i)).toBeNull();
  });

  it('stays quiet until there is something to count', async () => {
    // An empty field is showing its placeholder and its example — the two
    // things somebody deciding whether to bother needs. "400" beside them is a
    // rule about a box they have not chosen to use yet.
    await setup({ audience: '' });

    expect(screen.queryByText('400')).toBeNull();
  });

  it('counts down from the moment somebody types', async () => {
    await setup({ audience: 'my VP hates headcount' });

    expect(screen.getByText(String(400 - 'my VP hates headcount'.length))).toBeOnTheScreen();
  });

  it('reads zero at the cap rather than going negative', async () => {
    // `maxLength` makes over-length unreachable through the keyboard, but the
    // value is a prop and a re-run prefills it from whatever the server holds.
    // A field showing "-12" would be reporting a bug it cannot have.
    await setup({ audience: 'x'.repeat(420) });

    expect(screen.getByText('0')).toBeOnTheScreen();
  });

  it('says what the number means, for somebody who cannot see it', async () => {
    await setup({ audience: 'x'.repeat(380) });

    expect(screen.getByLabelText('20 characters left')).toBeOnTheScreen();
  });

  it('stops a long paste under the thumb rather than at Start', async () => {
    await setup();

    // The server refuses past AUDIENCE_LIMIT with a 422. Bounded here as well
    // so the refusal is not a room that will not open for an invisible reason
    // — the same rule the rehearsal name already follows.
    expect(
      screen.getByLabelText('What this audience is like').props.maxLength,
    ).toBe(400);
  });
});


it('offers nothing to reset until a room has been built', async () => {
  // A control that would do nothing, beside the heading that says what the
  // screen is for. It appears when there is something to put back and goes when
  // there is not, which is why it never has to be drawn as a disabled thing.
  await setup();

  expect(screen.queryByLabelText('Clear the room')).toBeNull();
});

it('offers to reset once anything has been set, including only a name', async () => {
  // Seating is the obvious case and the least likely to be the only one. A
  // paragraph about the committee somebody is walking into is the expensive
  // thing to lose track of — it is the one field here that is prose — and a
  // reset that only appeared once somebody had seated a panel would be missing
  // from the state where it matters most.
  await setup({ rehearsalName: 'Q3 board readout' });

  expect(screen.getByLabelText('Clear the room')).toBeTruthy();
});

it('asks once before it clears anything', async () => {
  // There is no undo. The deck is destroyed on the server, and the note is
  // prose somebody wrote — the same reason End on the interrogation screen arms
  // rather than fires. The first tap teaches what the second does.
  const props = await setup({ seated: ['cfo'], audience: 'My VP hates headcount.' });

  await userEvent.press(screen.getByLabelText('Clear the room'));

  expect(props.onReset).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Tap again to clear the room')).toBeTruthy();
});

it('clears the room on the second tap', async () => {
  const props = await setup({ seated: ['cfo'] });

  await userEvent.press(screen.getByLabelText('Clear the room'));
  await userEvent.press(screen.getByLabelText('Tap again to clear the room'));

  expect(props.onReset).toHaveBeenCalledTimes(1);
});

it('does not offer to reset the rung, which belongs to the account', async () => {
  // `chooseDifficulty` stores the rung server-side the moment it is tapped, and
  // it outlives this room — so a reset that moved it would silently undo a
  // setting the next rehearsal inherits. The control says "the room", and the
  // room is who is in it, what it is called, what they are told and what they
  // are reading.
  const props = await setup({ seated: ['cfo'] });

  await userEvent.press(screen.getByLabelText('Clear the room'));
  await userEvent.press(screen.getByLabelText('Tap again to clear the room'));

  expect(props.onDifficultyChange).not.toHaveBeenCalled();
});

it('says how long a room runs, before anybody starts one', async () => {
  // The architect's room ended at twelve minutes mid-sentence, and nothing on
  // any screen had said twelve was the number. The cap is the server's
  // (SESSION_LIMIT); this is the one place it is said ahead of time, so the
  // room's clock approaching 12:00 means something.
  await setup();

  expect(screen.getByText('A room runs up to 12 minutes.')).toBeTruthy();
});
