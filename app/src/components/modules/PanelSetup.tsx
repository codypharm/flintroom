import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { AttachedMaterial, MaterialLimits } from '../../lib/api/materialsApi';
import { portraitOf } from '../../lib/archetypes/portraits';
import { color, radius, space, type } from '../../theme/tokens';
import { ArchetypeCard, AuthorRow } from './ArchetypeCard';
import { DeckAttach } from './DeckAttach';

/**
 * Who is in the room, what they can attack, and how hard they push.
 *
 * THESIS: a seat is an input, not a tick. This screen refuses the panel-picker
 * every product of this kind ships — a grid of avatars with checkmarks — because
 * the order somebody seats a panel really does decide who speaks, and a
 * checkmark cannot say that. Choosing here is seating a room, in order, and the
 * screen shows the order back.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole and unextended.
 * Warm off-white ground, paper-white groups, burnt orange once, Hanken Grotesk,
 * 28px containers, hairline dividers. No value that `tokens.ts` does not carry.
 *
 * STORY: they see who they are about to face and pick a room, learn that a deck
 * makes the questions specific, decide how hard to be pushed, and start. Four
 * decisions about one thing, in the order the room is built.
 *
 * FIRST VIEWPORT: the roster. A heading that names what is about to happen, then
 * archetype rows carrying a title, one line of who they are, and — once seated —
 * the chair they took. Everything else is below the fold, which is correct: the
 * panel is the decision, the rest are adjustments to it.
 *
 * FORM: candidate 5 of 7 on the grounded list, assigned by seed `7c0db367`
 * (`--scope surface --mode operate`). The list's own top pick was a roster with
 * an accreting brief bar; the roll exists to refuse that ranking rut, and the
 * plainer structure is right for a screen somebody passes through before every
 * rehearsal.
 *
 * FINISH: unreviewed is unfinished. This build ends with the finish review and
 * the verdict — and not with a DESIGN.md, because an extension inside an
 * established world does not rewrite one.
 *
 * ---
 *
 * **The register is the differentiation, not the structure.** Four grouped
 * sections is the ordinary iOS arrangement and is meant to be: this is a screen
 * somebody crosses five times in a week. What is not ordinary is that the
 * headings state what the room will do rather than naming settings. `Product.md`
 * §9 asks the interface to make the discomfort feel deliberate and worth it —
 * never to soften it into encouragement, never to amplify it into humiliation.
 * "Configure your session" fails one way and "Ready to crush it?" fails the
 * other.
 */

/** One panelist, as the catalogue publishes them. Never their attack strategy. */
export interface ArchetypeOffered {
  name: string;
  title: string;
  /**
   * One line on who is in the chair.
   *
   * `Archetype.blurb` is deliberately not `attack_strategy`, and the reason is
   * the product rather than brevity: a picker that prints what somebody will go
   * after is a rehearsal the user has already had.
   */
  blurb: string;
}

export interface Room {
  archetypes: ArchetypeOffered[];
  /** How many this plan seats. */
  seats: number;
  /** Whether this plan may write its own archetype. */
  mayAuthor: boolean;
  /** Seats on the tier above, or null at the top. A fact, never a pitch. */
  upgradeSeats: number | null;
  difficulty: number;
  hardest: number;
}

export interface PanelSetupProps {
  room: Room;
  /** Seated archetype names, in seat order. Controlled by the route. */
  seated: string[];
  onSeatedChange: (names: string[]) => void;
  /**
   * The attached deck, or none.
   *
   * The type comes from the API module rather than being redeclared here.
   * `materialsApi` owns the lifecycle — it is the thing that collapses five
   * server states into the three a screen can draw — and a second definition
   * beside it would be free to disagree about what "extracting" means.
   *
   * One at a time even though a session may carry several: that follows what
   * the setup flow offers today, and widening it before anything attaches two
   * is a guess about a screen nobody has used.
   */
  material: AttachedMaterial | null;
  /** What this account may upload, or null while unknown. See `DeckAttach`. */
  limits: MaterialLimits | null;
  onAttach: () => void;
  onRemoveMaterial: () => void;
  onDifficultyChange: (level: number) => void;
  /**
   * Drawn above the title, inside this screen's own scroll.
   *
   * A slot rather than a second scroll view stacked on top, because two
   * scrollers on one screen is a screen where a flick sometimes moves the wrong
   * thing. What goes in it is Home's business — how the last room went, and how
   * much time is available — and this component stays ignorant of both.
   */
  header?: React.ReactNode;
  onStart: () => void;
}

/**
 * The three rungs, as what the room does rather than as a level.
 *
 * `docs/difficulty-calibration.md` decision 5 keeps the number off the screen:
 * a level is a score, and a score is the delivery-metrics product §1 refuses.
 * So each rung publishes its behaviour, which is also the honest thing — these
 * are literally the two integers `agents/difficulty.py` holds.
 *
 * **The gentlest line still says they follow up**, and that is decision 4 made
 * visible. The floor softens the interruptions and never the press, because a
 * room that lets an unanswered question go is not a gentler version of this
 * product. Somebody dragging this to the bottom should be able to see they have
 * not turned that off.
 */
const RUNGS = [
  { label: 'Gentle', does: 'They follow up once. Nobody talks over you.' },
  { label: 'Firm', does: 'They follow up once, and they cut across each other.' },
  { label: 'Relentless', does: 'They press twice on an answer you dodge.' },
] as const;

/** Counted in words, never numerals — the rule `PrepSheet.howOften` follows.
 *
 * A digit on this screen reads as a score, and the one thing a room must not
 * feel like is a game with a number attached.
 */
const COUNTED = ['no', 'one', 'two', 'three', 'four', 'five'] as const;

function counted(n: number): string {
  return COUNTED[n] ?? String(n);
}


export function PanelSetup({
  room,
  seated,
  onSeatedChange,
  material,
  limits,
  onAttach,
  onRemoveMaterial,
  onDifficultyChange,
  header,
  onStart,
}: PanelSetupProps) {
  const full = seated.length >= room.seats;

  // Three numbers rather than a ref and a measure call: the rail reports all of
  // them itself, and a layout read would be a second source that can disagree
  // with what is on screen.
  const [viewport, setViewport] = useState(0);
  const [reach, setReach] = useState(0);
  const [at, setAt] = useState(0);
  // A card's width of slack, so the pointer does not flicker off one pixel
  // before the last card is actually reached.
  const more = reach - viewport - at > 24 ? 'right' : at > 24 ? 'left' : null;
  const held = holdingUpStart(seated, material);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      {header}

      <Text style={styles.title} accessibilityRole="header">
        Set the room
      </Text>

      <Text style={styles.field} accessibilityRole="header">
        What they can attack
      </Text>

      <DeckAttach
        material={material}
        limits={limits}
        onAttach={onAttach}
        onRemove={onRemoveMaterial}
      />

      {/*
        Second, and heavier than the two around it. The deck goes first because
        extraction is asynchronous and slow — `setup.tsx` polls while the server
        reads the file — so starting it before these decisions overlaps the wait
        with them instead of leaving it in front of Start. That is a sequencing
        decision and not a hierarchy one: the panel is still the thing this
        screen is for, and it keeps the only heading between the title and the
        summary.

        The count sits opposite the heading, because a rail of eight cards
        showing two and a sliver has no other way to say there is more. A white
        card peeking past a warm off-white margin is invisible; a number is not,
        and a screen reader gets it too.
      */}
      <View style={styles.fieldRow}>
        <Text style={styles.groupTitle} accessibilityRole="header">
          Who is in the room
        </Text>
        <View style={styles.count}>
          {more === 'left' && <RailEnd more="left" />}
          <Text style={styles.fieldAside}>
            {`${counted(room.archetypes.length)} to choose from`}
          </Text>
          {more === 'right' && <RailEnd more="right" />}
        </View>
      </View>

      {/*
        A horizontal rail of cards rather than a vertical list of text rows.
        The rows were measured on a device with three of three seated and read
        as *status*: the architect concluded the panel could not be changed at
        all. It always could — taking somebody out is how you make room — but a
        row of text announces nothing, while a card with a face and a badge is
        obviously a thing you pick.

        Horizontal because eight full-width cards would push the deck and the
        difficulty dial off the bottom of a screen that has to be taken in at
        once before anybody presses Start.
      */}
      <View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.rail}
        // The rail is a list of buttons; the gesture belongs to the cards.
        accessibilityRole="list"
        // Labelled as well as roled, so the rail is addressable — a test can
        // ask what is inside it, which is the only way to assert that the
        // author row is *not*.
        accessibilityLabel="Panelists to choose from"
        scrollEventThrottle={32}
        onLayout={(event) => setViewport(event.nativeEvent.layout.width)}
        onContentSizeChange={(width) => setReach(width)}
        onScroll={(event) => setAt(event.nativeEvent.contentOffset.x)}
      >
        {room.archetypes.map((archetype) => {
          const seat = seated.indexOf(archetype.name);
          const isSeated = seat >= 0;

          return (
            <ArchetypeCard
              key={archetype.name}
              title={archetype.title}
              blurb={archetype.blurb}
              seat={isSeated ? seat + 1 : null}
              // A full room closes the *unseated* cards only. Closing the
              // seated ones too would make the cap a trap with no way out but
              // starting over.
              closed={full && !isSeated}
              portrait={portraitOf(archetype.name)}
              onPress={() =>
                onSeatedChange(
                  isSeated
                    ? seated.filter((name) => name !== archetype.name)
                    : [...seated, archetype.name]
                )
              }
            />
          );
        })}
      </ScrollView>

      </View>

      {/* Belongs to the roster above it, so it sits on the same left edge
          rather than centred under a left-aligned card. */}
      <Text style={styles.groupNote}>{seatsLine(room, seated.length)}</Text>

      {/*
        Out of the rail, where it was the ninth card of eight and nobody found
        it. It is not a panelist being chosen among — it is a capability — and
        a full-width row after the horizontal scroll ends is where the eye lands
        without anything having to be swiped. See `AuthorRow`.
      */}
      <AuthorRow yours={room.mayAuthor} />

      <Text style={styles.field} accessibilityRole="header">
        How hard they push
      </Text>

      <View style={styles.group}>
        {/*
          **A departure from the platform control, declared rather than
          smuggled.** Three mutually exclusive options is a segmented control,
          and iOS guidance is right that reinventing one is the commonest native
          slop. React Native dropped it from core, so using the real thing means
          a new dependency — which `CLAUDE.md` requires justifying to a human
          rather than adding quietly.

          So these are the design system's own pill controls, which §9 names as
          brand truth, and they keep the segmented behaviour: one of three,
          always exactly one chosen, 44pt targets, the choice announced. Worth
          revisiting the moment anything else on the app needs a segmented
          control, because then the dependency pays for two screens.
        */}
        <View style={styles.rungs}>
          {RUNGS.slice(0, room.hardest).map((rung, index) => {
            const level = index + 1;
            const chosen = level === room.difficulty;

            return (
              <Pressable
                key={rung.label}
                accessibilityRole="button"
                accessibilityState={{ selected: chosen }}
                accessibilityLabel={`${rung.label}${chosen ? ', selected' : ''}`}
                onPress={() => onDifficultyChange(level)}
                style={({ pressed }) => [
                  styles.rung,
                  chosen && styles.rungChosen,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={[styles.rungLabel, chosen && styles.rungLabelChosen]}>
                  {rung.label}
                </Text>
              </Pressable>
            );
          })}
        </View>

        {/*
          The chosen rung's behaviour, stated. Not a caption for the control —
          it is the only place the difference between the three is legible, and
          it changes as they move.
        */}
        <Text style={styles.does}>
          {(RUNGS[room.difficulty - 1] ?? RUNGS[0]).does}
        </Text>
      </View>

      {/*
        The only primary action on the screen, and it refuses out loud. The
        server refuses an unready deck and an over-large panel anyway, so
        without this the user learns by watching Start fail — which is the
        difference between a screen that waited with them and one that broke.
      */}
      {/*
        What they assembled, in speaking order, immediately above the control
        that commits it. Composed from state and nothing else — no claim the
        screen cannot back.

        This is the difference between a form and an act. Everything above is
        eight cards, a file row and three pills; without this the screen never
        once says what any of it added up to, and Start is a button at the
        bottom of a scroll rather than the door into a specific room.
      */}
      {held === null && <Text style={styles.assembled}>{assembled(room, seated, material)}</Text>}

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: held !== null }}
        disabled={held !== null}
        onPress={onStart}
        style={({ pressed }) => [
          styles.start,
          pressed && styles.pressed,
          held !== null && styles.closed,
        ]}
      >
        <Text style={styles.startLabel}>Start</Text>
      </Pressable>

      {held !== null && <Text style={styles.footnote}>{held}</Text>}
    </ScrollView>
  );
}

/**
 * Which way the rail continues, beside the count of what is in it.
 *
 * Drawn from two borders on a rotated square rather than set as a character:
 * a chevron from a font is a font dependency for a shape, and it inherits
 * whatever that face does at small sizes on a device nobody tested.
 *
 * Beside the count rather than floating over the rail's edge, which is where
 * it started. Over the edge it sat on top of a card — a disc covering part of
 * a face, on a row whose entire job is comparing faces — and it had to carry
 * its own background to stay legible against whatever it happened to overlap.
 * Next to the count it occludes nothing, needs no plate, and pairs the
 * direction with the quantity it belongs to.
 *
 * Hidden from a screen reader, and that is not an omission. Swiping a rail is
 * not how anybody reaches these cards with VoiceOver on — the cards are
 * focusable and the rotor walks them regardless of what is on screen — so an
 * announced arrow would be describing a gesture that reader does not need.
 * The count beside the heading is the spoken form of the same fact.
 */
function RailEnd({ more }: { more: 'left' | 'right' }) {
  return (
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <View style={[styles.chevron, more === 'left' && styles.chevronBack]} />
    </View>
  );
}

/**
 * The room, said back in the order it will speak.
 *
 * Order is the point rather than a flourish: the server seats archetypes as
 * they arrive and chair one takes the floor first, so "The CFO, then the
 * Champion" is a fact about the next twelve minutes and not a list.
 *
 * Grounding is named only when there is some. "and nothing attached" would be
 * an apology for a deliberate choice — `Product.md` §3.2 makes material an
 * optional enrichment, and pitching cold is a supported way to use this.
 */
function assembled(
  room: Room,
  seated: string[],
  material: AttachedMaterial | null
): string {
  const names = seated
    .map((name) => room.archetypes.find((one) => one.name === name)?.title ?? name)
    // Lowercased after the first, because this is a sentence rather than a
    // list. "The CFO, then The Technical Skeptic" reads as three proper nouns
    // stacked up; "then the Technical Skeptic" reads as somebody describing a
    // room. The catalogue keeps its capitals — the article only drops where
    // English would drop it.
    .map((title, index) => (index === 0 ? title : title.replace(/^The /, 'the ')))
    .join(', then ');

  const pressure = (RUNGS[room.difficulty - 1] ?? RUNGS[0]).label.toLowerCase();
  const ground =
    material?.state === 'ready' ? `, over ${material.filename}` : '';

  return `${names}${ground}. They push ${pressure}.`;
}

/**
 * How full the room is, and what the tier above would seat.
 *
 * One sentence rather than a counter and a badge: §4.6 forbids a depleting
 * counter, and "three of three" is a statement about a room somebody just
 * built rather than a resource draining away.
 */
function seatsLine(room: Room, taken: number): string {
  const held = `${counted(taken)} of ${counted(room.seats)} seated`.replace(
    /^./,
    (first) => first.toUpperCase()
  );

  const tier =
    room.upgradeSeats === null ? '' : ` Pro seats ${counted(room.upgradeSeats)}.`;

  // The way out, said only when it is needed. A full room dims every
  // alternative, which reads as permanently locked rather than as "free a seat
  // first" — and the swap was always allowed. Measured on a device: three of
  // three seated, and no way to tell the roster was still a control.
  const swap = taken >= room.seats ? ' Tap someone to swap them out.' : '';

  return `${held}.${swap}${tier}`;
}

/**
 * Why Start cannot be pressed yet, or null when it can.
 *
 * A sentence rather than a boolean, because a disabled button with no reason is
 * the failure this exists to prevent. Each of these is something the server
 * would refuse anyway: the screen just gets there first.
 */
function holdingUpStart(
  seated: string[],
  material: AttachedMaterial | null
): string | null {
  if (seated.length === 0) {
    // `assemble` seats the shipped default on an empty list, so starting here
    // would quietly produce a room nobody chose. Asking is better than seating
    // somebody on their behalf.
    return 'Seat at least one of them.';
  }
  if (material?.state === 'extracting') {
    return `Still reading ${material.filename}.`;
  }
  return null;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },

  content: {
    paddingHorizontal: space.screen,
    paddingTop: space.section,
    paddingBottom: space.major,
  },

  /**
   * The screen's one question, and the only thing at display size.
   *
   * No top margin: `content` already carries the inset, and a heading that
   * adds its own to a container's is the commonest way a screen ends up with
   * two different top edges depending on which one you measure.
   */
  title: {
    ...type.headlineLg,
    color: color.onSurface,
    marginBottom: space.base,
  },

  /**
   * The panel's heading and its count, on one baseline.
   *
   * `flex-end` rather than centre: the two are different sizes, and aligning
   * their boxes would leave the small one floating above the heading's
   * baseline instead of sitting on it.
   */
  fieldRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    marginTop: space.section,
    marginBottom: space.snug,
  },

  /**
   * The one heading between the title and the summary.
   *
   * The deck and the dial are labels; this is not. Sequence puts the deck
   * first because extraction is slow, and nothing about that makes attaching a
   * file the point of the screen.
   */
  groupTitle: { ...type.headlineSm, color: color.onSurface },

  /**
   * How many there are to pick from.
   *
   * The rail shows two cards and a sliver, and the sliver is a white card
   * against a warm off-white margin — present, and invisible. This is the
   * only thing on the screen that says the list continues.
   */
  fieldAside: { ...type.bodySm, color: color.onSurfaceVariant },

  field: {
    ...type.labelLg,
    color: color.onSurfaceVariant,
    marginTop: space.section,
    marginBottom: space.snug,
  },

  group: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    paddingHorizontal: space.base,
  },

  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    paddingVertical: space.base,
    minHeight: 44,
  },

  pressed: { opacity: 0.7 },

  rowText: { flex: 1, gap: space.hair },
  rowTitle: { ...type.labelLg, color: color.onSurface },
  rowDetail: { ...type.bodySm, color: color.onSurfaceVariant },

  seat: { ...type.labelLg, color: color.primary },

  /** A stated fact beside a row — never an action. */
  aside: { ...type.bodySm, color: color.onSurfaceVariant },

  /**
   * A row the room has no seat for, and the Start it is holding up.
   *
   * Light enough to stay legible: WCAG exempts inactive controls from the
   * contrast floor, but somebody has to be able to read *which* archetype they
   * cannot seat, or the cap reads as the list being broken.
   */
  // Not lower. A full room dims five rows at once, and at the depth this was
  // they read as permanently unavailable rather than as waiting for a seat —
  // which is how somebody concludes the panel cannot be changed at all.
  closed: { opacity: 0.72 },

  // Breaks the screen margin on purpose: a rail that stopped at the gutter
  // reads as a finished row, and nothing about it invites a swipe. Running the
  // last card off the edge is what says there is more.
  rail: {
    gap: space.snug,
    paddingHorizontal: space.screen,
    paddingBottom: space.hair,
  },

  /** The count and its direction, on one line. */
  count: { flexDirection: 'row', alignItems: 'center', gap: space.tight },

  chevron: {
    width: 8,
    height: 8,
    borderRightWidth: 2,
    borderTopWidth: 2,
    borderColor: color.onSurfaceVariant,
    transform: [{ rotate: '45deg' }],
    // The glyph's mass sits left of centre once rotated; this puts the point
    // on the disc's centre rather than the bounding box.
    marginRight: 3,
  },
  chevronBack: { transform: [{ rotate: '225deg' }], marginRight: 0, marginLeft: 3 },

  rungs: {
    flexDirection: 'row',
    gap: space.tight,
    paddingTop: space.base,
  },

  rung: {
    flex: 1,
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.hairline,
  },

  // Filled rather than outlined, because three outlined pills with one tinted
  // border is a difference somebody has to hunt for.
  rungChosen: { backgroundColor: color.primary, borderColor: color.primary },

  rungLabel: { ...type.labelLg, color: color.onSurfaceVariant },
  rungLabelChosen: { color: color.onPrimary },

  does: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    paddingTop: space.snug,
    paddingBottom: space.base,
  },

  start: {
    marginTop: space.hair,
    minHeight: 52,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: radius.pill,
    backgroundColor: color.primary,
  },

  startLabel: { ...type.labelLg, fontSize: 16, color: color.onPrimary },

  /**
   * The assembled room, directly above Start.
   *
   * Centred, unlike every other note on this screen, and deliberately: it
   * belongs to the button rather than to the group above it, and it is the one
   * line here that is a summary rather than a caption.
   */
  assembled: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    textAlign: 'center',
    marginTop: space.major,
    marginBottom: space.snug,
  },

  groupNote: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
  },

  /** A note about the button above it, which is centred, so this is too. */
  footnote: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
    textAlign: 'center',
  },

  hairline: { height: 1, backgroundColor: color.hairline, opacity: 0.5 },
});
