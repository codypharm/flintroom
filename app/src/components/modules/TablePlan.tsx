import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { ROLES, SEATS, SITUATIONS, labelFor, seat } from '../../lib/onboarding/plan';
import { sayWhen } from '../../lib/onboarding/when';
import { color, radius, space, type } from '../../theme/tokens';
import { Chair } from './Chair';

/**
 * The seating plan for the meeting you are about to walk into.
 *
 * THESIS: the survey is one artifact you mark up, not five questions you are
 * paged through. This refuses the first-run carousel every app of this kind
 * ships — big question, four tap targets, progress dots — because a plan you can
 * see whole reads as work to a professional, and a carousel reads as onboarding
 * theater to exactly the audience `docs/onboarding.md` says is quickest to
 * dismiss it.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole. Warm off-white
 * ground, burnt orange once, Hanken Grotesk, hairline rules, 28px containers.
 * Nothing here invents a value `tokens.ts` does not hold.
 *
 * STORY: they describe the room they are walking into, in their own words —
 * whoever controls the budget, whoever loses out if they win — and every mark
 * they make is a person who will be in the chair. Then they sign in, and the
 * same plan comes back cast.
 *
 * FIRST VIEWPORT: the table. A heading naming what is about to happen, then the
 * spine with seven chairs on it, filling as they are tapped. The situation and
 * the date sit above it as one quiet line each, because they configure the
 * least and the table configures the most.
 *
 * FORM: candidate 6 of 7 on the grounded list, assigned by seed `e15d5462`
 * (`--scope surface --mode persuade`). The list's own top pick was "seats fill
 * as you answer" — questions driving a passive picture of a room. The roll
 * refused it, and it was right to: this makes the artifact the input rather
 * than the illustration.
 *
 * FINISH: unreviewed is unfinished. This build ends with the finish review and
 * the verdict — and not with a DESIGN.md, because an extension inside an
 * established world does not rewrite one.
 *
 * ---
 *
 * **Tap to seat, never drag.** A drawn table with draggable figures is
 * unreachable by a screen reader and worse with a thumb than a tap is. So the
 * chart is geometry drawn *along* an accessible list rather than instead of
 * one — see `Chair`. At the largest Dynamic Type sizes the rows grow and the
 * table gets longer; nothing clips, because nothing was ever positioned
 * absolutely against a fixed canvas.
 *
 * **No progress indicator, anywhere.** Not dots, not "2 of 5", not a bar. The
 * whole plan is on one sheet, so its own length is the progress — and a counter
 * on a screen this short would be measuring an anxiety it had just created.
 */

export interface Plan {
  /** Q1 — what kind of room. `other` is the only escape offered. */
  situation: string | null;
  /** Q2 — ISO date, or null for "not scheduled yet", which is a real answer. */
  happensOn: string | null;
  /** Q3 — what they are when they stand up. */
  role: string | null;
  /** Q4 — the chairs they filled, in the order they filled them. */
  audience: string[];
  /** Q5 — the rung, 1 to `hardest`. */
  difficulty: number;
}

export interface TablePlanProps {
  /** How many chairs this plan draws. The free tier's three, today. */
  seats: number;
  hardest: number;
  plan: Plan;
  /** True while the plan is being sent. Locks the controls, not the scroll. */
  busy: boolean;
  onChange: (plan: Plan) => void;
  /**
   * Ask for the date, or null while no picker exists.
   *
   * The route owns the picker because it is a native host component, and this
   * screen stays testable without one — the same seam the microphone uses in
   * `debrief/[id].tsx`.
   *
   * **Null renders the row as a statement rather than a dead control.**
   * `@expo/ui` splits the picker across `DatePicker` on SwiftUI and
   * `DateTimePicker` on Compose, both inside a `Host`, and that is a
   * two-platform native integration nothing here can verify. `PanelSetup` made
   * the same call about authoring a custom archetype: *"a control that opens
   * nothing is worse than a statement"*.
   */
  onPickDate: (() => void) | null;
  onContinue: () => void;
}

/** How hard the room pushes, said as behaviour rather than as an adjective. */
const PRESSURE = [
  'Let me finish a thought',
  'Push me, but fairly',
  // "Give me nothing" was here and reads two ways: give me no quarter, or give
  // me nothing to work with. In context most people land on the first, but this
  // is the rung that decides how hard a first room hits somebody — `Product.md`
  // §8 risk 1 — and a misread there is the one that produces churn rather than
  // resilience. Same instruction, one reading.
  "Don't let up",
];

export function TablePlan({
  seats,
  hardest,
  plan,
  busy,
  onChange,
  onPickDate,
  onContinue,
}: TablePlanProps) {
  const full = plan.audience.length >= seats;

  return (
    <ScrollView
      style={styles.sheet}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.title} accessibilityRole="header">
        What are you walking into?
      </Text>

      <View style={styles.group}>
        {SITUATIONS.map((situation) => (
          <Choice
            key={situation.key}
            label={situation.label}
            chosen={plan.situation === situation.key}
            disabled={busy}
            onPress={() => onChange({ ...plan, situation: situation.key })}
          />
        ))}
      </View>

      <View style={styles.when}>
        <Pressable
          accessibilityRole={onPickDate ? 'button' : 'text'}
          accessibilityLabel={
            onPickDate
              ? plan.happensOn
                ? `It happens on ${sayWhen(plan.happensOn)}. Tap to change.`
                : 'No date set. Tap to say when it happens.'
              : `When is it? ${sayWhen(plan.happensOn)}`
          }
          disabled={busy || onPickDate === null}
          onPress={onPickDate ?? undefined}
          style={({ pressed }) => [styles.whenAsk, pressed && onPickDate && styles.pressed]}
        >
          <Text style={styles.whenLabel}>When is it?</Text>
          <Text style={styles.whenValue}>
            {/* "Not sure yet" rather than a placeholder date, and said in words
                rather than as an ISO string. A guessed date makes the countdown
                confidently wrong, which is worse than absent. */}
            {sayWhen(plan.happensOn)}
          </Text>
          {/* The affordance appears only when there is something to open. With
              no picker the row is a statement, and a chevron on a statement is
              a lie about what a tap does. */}
          {onPickDate !== null && <View style={styles.whenChevron} />}
        </Pressable>

        {/* Clearing lives on the row rather than in the picker, because neither
            native picker can do it: Compose's dialog confirms or dismisses, and
            dismissing is a cancel. "Not sure yet" is an answer, so it has to be
            reachable a second time. */}
        {plan.happensOn !== null && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Clear the date"
            accessibilityState={{ disabled: busy }}
            disabled={busy}
            onPress={() => onChange({ ...plan, happensOn: null })}
            hitSlop={space.tight}
            style={({ pressed }) => [styles.whenClear, pressed && styles.pressed]}
          >
            <Text style={styles.whenClearLabel}>Clear</Text>
          </Pressable>
        )}
      </View>

      <Text style={styles.sectionTitle} accessibilityRole="header">
        Who is in that room?
      </Text>
      <Text style={styles.aside}>
        {/* States the cap as a fact about the table rather than as a limit hit
            later. Never a count of what is left — `CLAUDE.md` forbids a
            depleting counter, and the same reasoning applies to chairs. */}
        {`Your table seats ${seats}.`}
      </Text>

      <View style={styles.table}>
        {SEATS.map((option) => {
          const at = plan.audience.indexOf(option.key);

          return (
            <Chair
              key={option.key}
              label={option.label}
              position={at === -1 ? null : at + 1}
              unavailable={busy || (full && at === -1)}
              onPress={() =>
                onChange({
                  ...plan,
                  audience: seat(plan.audience, option.key, seats),
                })
              }
            />
          );
        })}
      </View>

      <Text style={styles.sectionTitle} accessibilityRole="header">
        And what are you, in it?
      </Text>

      <View style={styles.group}>
        {ROLES.map((role) => (
          <Choice
            key={role.key}
            label={role.label}
            chosen={plan.role === role.key}
            disabled={busy}
            onPress={() => onChange({ ...plan, role: role.key })}
          />
        ))}
      </View>

      <Text style={styles.sectionTitle} accessibilityRole="header">
        How hard should they go?
      </Text>

      <View style={styles.group}>
        {Array.from({ length: hardest }, (_, rung) => (
          <Choice
            key={rung}
            label={PRESSURE[rung] ?? `Level ${rung + 1}`}
            chosen={plan.difficulty === rung + 1}
            disabled={busy}
            onPress={() => onChange({ ...plan, difficulty: rung + 1 })}
          />
        ))}
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: busy }}
        disabled={busy}
        onPress={onContinue}
        style={({ pressed }) => [styles.go, pressed && styles.pressed]}
      >
        <Text style={styles.goLabel}>Build my room</Text>
      </Pressable>

      <Text style={styles.foot}>
        {/* The one place the free grant is named, and it is named as a gift
            rather than as a balance. §4.6: show minutes plainly and generously,
            never as something draining. */}
        Signing in gives you 15 minutes in the room, on us.
      </Text>
    </ScrollView>
  );
}

/** One answer in a pick-one list. Deliberately not a card. */
function Choice({
  label,
  chosen,
  disabled,
  onPress,
}: {
  label: string;
  chosen: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected: chosen, disabled }}
      accessibilityLabel={label}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.choice, pressed && styles.pressed]}
    >
      <Text style={[styles.choiceLabel, chosen && styles.choiceChosen]}>{label}</Text>
      {chosen && <View style={styles.chosenMark} />}
    </Pressable>
  );
}

export { labelFor };

const styles = StyleSheet.create({
  sheet: { flex: 1, backgroundColor: color.surface },
  content: {
    paddingHorizontal: space.screen,
    paddingTop: space.section,
    paddingBottom: space.major,
  },

  /**
   * Two intervals and two heading sizes, which between them are the whole
   * hierarchy of this sheet.
   *
   * Every question used to be `headlineMd` at 32 above and 12 below, four times
   * over, and a screen where four things are the loudest thing has no loudest
   * thing — squint at it and you see four identical white slabs in a row. The
   * first question is the sheet's own title now and carries `headlineLg`; the
   * three after it step down to `headlineSm` and are separated by `major`
   * rather than `section`, so a section break (48) is four times the interval
   * inside a group (12) instead of not quite three.
   *
   * `title` has no top margin because it opens the sheet — the content's own
   * top padding is the space above it, and a margin there would double it.
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
  // Tight to the heading it belongs to, because it is part of that sentence
  // rather than a paragraph under it.
  aside: { ...type.bodyMd, color: color.onSurfaceVariant, marginBottom: space.tight },

  group: {
    backgroundColor: color.card,
    borderRadius: radius.container,
    paddingHorizontal: space.base,
  },
  choice: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: space.snug,
  },
  choiceLabel: { ...type.bodyLg, color: color.onSurfaceVariant, flex: 1 },
  // Brand colour, not merely darker. The only feedback this sheet gives was a
  // 10pt dot at the far right of a 390pt row and a shift from warm brown to
  // near-black in the label — at arm's length on a warm ground, an answered
  // question and an unanswered one looked the same. Colouring the label is what
  // makes a mark readable across the whole sheet without adding a counter the
  // thesis refuses. It also matches the seated chair, whose marker and position
  // number are already `primary`, so one colour means "chosen" throughout.
  choiceChosen: { color: color.primary },
  chosenMark: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: color.primary,
    marginLeft: space.base,
  },

  /**
   * A line, not a card.
   *
   * It had the same 28px container, the same white, and the same left inset as
   * the six-option question above it — which said the two configure the room
   * equally, when one picks the archetypes and the other is a date that is
   * currently not even askable. Stacked label over value in a card is the shape
   * of a form field; label left and value right on one line is the shape of a
   * fact, which is what this is until #71 lands.
   *
   * Half the height it was, and the plan gets its emphasis back.
   */
  when: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: space.loose,
    minHeight: 44,
  },
  // The question takes the width and the clear sits after it, so the value
  // stays on the right edge the rest of the sheet aligns to until there is
  // something to clear.
  whenAsk: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    minHeight: 44,
  },
  whenClear: {
    minHeight: 44,
    justifyContent: 'center',
    paddingLeft: space.base,
  },
  whenClearLabel: { ...type.labelLg, color: color.primary },
  whenLabel: { ...type.labelLg, color: color.onSurfaceVariant, flex: 1 },
  whenValue: { ...type.bodyLg, color: color.onSurface },
  whenChevron: {
    width: 9,
    height: 9,
    borderRightWidth: 2,
    borderTopWidth: 2,
    borderColor: color.onSurfaceVariant,
    transform: [{ rotate: '45deg' }],
  },

  // No card around the table. The spine is the container, and a card would put
  // a box around a drawing whose whole job is to read as one continuous edge.
  //
  // Flush left, where it used to sit 4pt in. A rule that stands for the edge of
  // a table has to be aligned to something, and the only vertical line on this
  // sheet worth aligning to is the column the headings start on. The chair
  // labels then land inset from it, which is the ordinary leading-accessory
  // inset every list with a marker has — deliberate, unlike the 4.
  table: { paddingLeft: 0 },

  go: {
    minHeight: 44,
    // A section break, like the headings — the action closes the last question
    // rather than belonging to it.
    marginTop: space.major,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: color.primary,
    borderRadius: radius.pill,
    paddingVertical: space.snug,
  },
  goLabel: { ...type.labelLg, color: color.onPrimary },
  pressed: { opacity: 0.6 },

  foot: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    marginTop: space.base,
    textAlign: 'center',
  },
});
