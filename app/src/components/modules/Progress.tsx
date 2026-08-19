import { StyleSheet, Text, View } from 'react-native';

import type { RoomHeld, Tally } from '../../lib/api/progressApi';
import type { WeaknessKind } from '../../lib/api/debriefApi';
import { KINDS, panelistName } from '../../lib/panel/vocabulary';
import { color, space, type } from '../../theme/tokens';

/**
 * Whether you are getting better.
 *
 * THESIS: three sentences and one figure, not a dashboard. Asked for directly —
 * *"user is meant to track their development"* — and the thing that makes it
 * useful rather than motivational is that it says **what to change**, not how
 * much. "Answered a different question, in three of your last three rooms" is
 * an instruction; a percentage is a mood.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole.
 *
 * FIRST VIEWPORT: it sits at the head of Home, above the control that starts a
 * room, because it is the reason to start one.
 *
 * ---
 *
 * **The figure and its rung are one sentence and cannot be separated.**
 * Difficulty escalates, so eight of nine at the hardest setting and eight of
 * nine at the gentlest are different facts. This is the one place where a
 * layout decision is load-bearing rather than aesthetic: split them across two
 * lines and somebody scans the number alone.
 *
 * **No average, no total, no percentage, no chart.** `design-guide/home/` has a
 * bar chart of "Avg. Likelihood 72%", which is retired twice over — the metric
 * by `Product.md:419` and the shape by arithmetic, since a mean across rungs is
 * an average of incomparable rooms.
 *
 * **Nothing about how somebody spoke**, which is both the §1 refusal and a
 * statement of fact: nothing in this pipeline hears delivery. It reads what was
 * said.
 */

/** Below this many rooms, a recurrence is a coincidence rather than a habit. */
const A_PATTERN = 2;

export interface ProgressProps {
  /** Newest first, as the server returns them. */
  rooms: RoomHeld[];
  habits: Tally[];
  askers: Tally[];
}

export function Progress({ rooms, habits, askers }: ProgressProps) {
  const latest = rooms[0];

  if (!latest) {
    return (
      <View style={styles.block}>
        <Text style={styles.nothing}>Nothing to compare yet</Text>
      </View>
    );
  }

  // One room is not a pattern. Calling it one would tell somebody their worst
  // afternoon is who they are, which is the opposite of what this is for.
  const habit = habits.find((one) => one.rooms >= A_PATTERN);
  const asker = askers.find((one) => one.rooms >= A_PATTERN);

  return (
    <View style={styles.block}>
      <Text style={styles.held}>
        <Text style={styles.figure}>
          {latest.held} of {latest.challenged}
        </Text>
        <Text style={styles.qualifier}>
          {' '}
          held in your last room{rung(latest.level)}
        </Text>
      </Text>

      {habit && (
        <Text style={styles.pattern}>
          {habitOf(habit.name)}, in {inWords(habit.rooms)} of your last{' '}
          {inWords(rooms.length)} rooms.
        </Text>
      )}

      {asker && (
        <Text style={styles.pattern}>
          {panelistName(asker.name)} has got past you in {inWords(asker.rooms)} of
          them.
        </Text>
      )}
    </View>
  );
}

/**
 * The rung, as part of the sentence rather than beside it.
 *
 * Empty for a room that predates the ladder — the level is genuinely unknown
 * there, and "at an unknown setting" is worse than not saying it.
 */
function rung(level: number | null): string {
  if (level === 1) return ', at the gentler setting';
  if (level === 2) return '';
  if (level === 3) return ', with the room at its most relentless';
  return '';
}

/**
 * What the habit is called, through the table both other surfaces read.
 *
 * `KINDS` writes each as a verb — "Answered a different question", not
 * "evasive" — because a noun invites a score and a verb invites a change.
 */
function habitOf(kind: string): string {
  return KINDS[kind as WeaknessKind]?.habit ?? kind;
}

/**
 * Small counts in words.
 *
 * "three of your last three rooms" reads as a sentence somebody said; "3 of 3"
 * reads as a metric, which is the register this screen is avoiding. Digits
 * return above the point where words stop being readable.
 */
function inWords(count: number): string {
  return ['no', 'one', 'two', 'three', 'four', 'five', 'six'][count] ?? String(count);
}

const styles = StyleSheet.create({
  block: { gap: space.snug },

  /**
   * One `Text`, deliberately. The figure and its qualifier are a sentence, and
   * two elements would let a future layout put the number on its own line —
   * which is exactly how a figure starts being read without its rung.
   */
  held: { ...type.bodyLg },
  figure: { ...type.headlineMd, color: color.onSurface },
  qualifier: { ...type.bodyLg, color: color.onSurfaceVariant },

  pattern: { ...type.bodyMd, color: color.onSurfaceVariant },
  nothing: { ...type.bodyLg, color: color.onSurfaceVariant },
});
