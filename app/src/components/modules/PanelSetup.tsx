import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { AttachedMaterial, MaterialLimits } from '../../lib/api/materialsApi';
import { portraitOf } from '../../lib/archetypes/portraits';
import { color, radius, space, type } from '../../theme/tokens';
import { ArchetypeCard, AuthorCard } from './ArchetypeCard';
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
  onStart,
}: PanelSetupProps) {
  const full = seated.length >= room.seats;
  const held = holdingUpStart(seated, material);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.title} accessibilityRole="header">
        Who is in the room
      </Text>

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
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.rail}
        // The rail is a list of buttons; the gesture belongs to the cards.
        accessibilityRole="list"
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

        <AuthorCard yours={room.mayAuthor} />
      </ScrollView>

      {/* Belongs to the roster above it, so it sits on the same left edge
          rather than centred under a left-aligned card. */}
      <Text style={styles.groupNote}>{seatsLine(room, seated.length)}</Text>

      <Text style={styles.sectionTitle} accessibilityRole="header">
        What they can attack
      </Text>

      <DeckAttach
        material={material}
        limits={limits}
        onAttach={onAttach}
        onRemove={onRemoveMaterial}
      />

      <Text style={styles.sectionTitle} accessibilityRole="header">
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
   * Two heading sizes and two intervals, which between them are the hierarchy.
   *
   * Three headings at one size and one 32/12 interval gave the screen no
   * loudest thing — squint and it was three identical white slabs. The panel is
   * the decision and the other two are adjustments to it, so the first heading
   * is the screen's title and the rest step down. The section break goes to 48
   * against 12 inside a group, so a break is four times a gap rather than not
   * quite three.
   *
   * No top margin on the title: the content's own padding is the space above
   * it, and a margin there would double it.
   */
  title: {
    ...type.headlineLg,
    color: color.onSurface,
    marginBottom: space.base,
  },
  sectionTitle: {
    ...type.headlineSm,
    color: color.onSurface,
    marginTop: space.major,
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
    marginTop: space.major,
    minHeight: 52,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: radius.pill,
    backgroundColor: color.primary,
  },

  startLabel: { ...type.labelLg, fontSize: 16, color: color.onPrimary },

  /** A note about the group above it. Left-aligned, because the group is. */
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
