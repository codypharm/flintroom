import { useEffect, useRef } from 'react';
import { Animated, Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { useReduceMotion } from '../../lib/a11y/reduceMotion';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * One archetype, as something you pick rather than something you read.
 *
 * This replaced a vertical list of text rows where being seated was carried by
 * the word "first" in orange. Measured on a device with three of three seated:
 * the rows read as *status*, every unseated one dimmed to 40% read as
 * permanently locked, and the conclusion was that the panel could not be
 * changed at all. It always could — a seated archetype has always been
 * pressable — but nothing about the surface said so.
 *
 * A card carries the affordance in its shape. It is an object with a border, a
 * face and a badge; picking one is obviously what it is for.
 *
 * **The badge is the seat number, not a tick.** A tick would say "chosen",
 * which is less than the truth: the server seats archetypes in the order they
 * arrive and chair one really does speak first, so the order is a decision the
 * screen would otherwise be hiding.
 */
export interface ArchetypeCardProps {
  title: string;
  blurb: string;
  /** 1-based seat, or null when nobody has put them in the room. */
  seat: number | null;
  /** The room is full and this one is not in it. */
  closed: boolean;
  /**
   * Their portrait, or null until there is artwork.
   *
   * `require`d by the caller rather than fetched: eight faces that never change
   * belong in the bundle, not behind a request on a screen somebody opens
   * before every rehearsal.
   */
  portrait: number | null;
  onPress: () => void;
}

export function ArchetypeCard({
  title,
  blurb,
  seat,
  closed,
  portrait,
  onPress,
}: ArchetypeCardProps) {
  const taken = seat !== null;
  const settled = useSeated(taken);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: taken, disabled: closed }}
      accessibilityLabel={taken ? `${title}, in chair ${seat}` : `${title}, not seated`}
      accessibilityHint={
        taken
          ? 'Tap to take them out of the room.'
          : closed
            ? 'The room is full. Take somebody out first.'
            : 'Tap to seat them.'
      }
      disabled={closed}
      onPress={onPress}
      style={({ pressed }) => [
        styles.card,
        taken && styles.taken,
        // Not lower. A full room dims every other card at once, and below about
        // this they stop reading as "waiting for a seat" and start reading as
        // "not available to you".
        closed && styles.closed,
        pressed && styles.pressed,
      ]}
    >
      <View style={styles.face}>
        {portrait === null ? (
          // Their initials, until there is a photograph. Deliberately not a
          // silhouette glyph: a generic head icon repeated eight times is
          // furniture, and tells you nothing about which card you are looking
          // at from the corner of your eye. `L` and `S` are visibly different
          // at a glance; two identical outlines are not.
          <Text style={styles.initials}>{initialsOf(title)}</Text>
        ) : (
          <Image source={portrait} style={styles.portrait} accessibilityIgnoresInvertColors />
        )}
      </View>

      {taken && (
        <Animated.View
          style={[
            styles.seat,
            { transform: [{ scale: settled }], opacity: settled },
          ]}
        >
          <Text style={styles.seatLabel}>{seat}</Text>
        </Animated.View>
      )}

      {/* Two lines always, even for "The CFO". Left to size itself, a
          one-line title and a two-line title started their blurbs at different
          heights and the rail came out ragged along the bottom — on a row of
          cards whose whole job is to be compared. */}
      <Text style={styles.title} numberOfLines={2}>
        {title}
      </Text>
      {/* Five lines, which is what the longest shipped blurb needs. Fewer cut
          the CFO mid-word — and hers is the description a presenter is most
          likely to be reading carefully, because she is the one they are
          deciding whether to sit down with.

          Kept at all, where the reference mockup drops it. Without it every card is a
          face and a job title, and choosing between eight of those is choosing
          by vibe — which is the opposite of what a panel is for. */}
      <Text style={styles.blurb} numberOfLines={5}>
        {blurb}
      </Text>
    </Pressable>
  );
}

/**
 * "The Technical Skeptic" -> "TS".
 *
 * The article is dropped because every archetype has one, and eight cards all
 * beginning T would defeat the point of showing initials at all.
 */
export function initialsOf(title: string): string {
  const words = title
    .split(/\s+/)
    .filter((word) => word.length > 0 && word.toLowerCase() !== 'the');

  if (words.length === 1) {
    const [only] = words;

    // An acronym is already the abbreviation. "The CFO" reduced to a lone "C"
    // was worse than useless — it is the one archetype a presenter is most
    // likely to be looking for, rendered as the least identifiable card.
    return only === only.toUpperCase() ? only.slice(0, 3) : only.slice(0, 2);
  }

  return words
    .map((word) => word[0].toUpperCase())
    .join('')
    .slice(0, 2);
}

/**
 * The screen's one authored moment: somebody taking a seat.
 *
 * Everything else on setup is a state flip, and it should be — a file attaches,
 * a pill selects, and dressing either up would be motion for its own sake. But
 * seating a panelist is the decision this screen exists for, and the badge
 * simply blinking into existence makes the most consequential tap on the screen
 * the least felt one.
 *
 * Overshoots slightly and settles, which is what a physical thing does when it
 * is put down. Out is a plain fade: taking somebody out is a correction, and a
 * correction that performs is a screen congratulating you for undoing
 * something.
 *
 * Honours Reduce Motion by cutting, not by slowing — a shortened bounce is
 * still a bounce, and the setting means "do not move things", not "move them
 * less".
 */
function useSeated(taken: boolean): Animated.Value {
  const settled = useRef(new Animated.Value(taken ? 1 : 0)).current;
  const calm = useReduceMotion();

  useEffect(() => {
    if (!taken) {
      Animated.timing(settled, {
        toValue: 0,
        duration: calm ? 0 : 120,
        useNativeDriver: true,
      }).start();
      return;
    }

    if (calm) {
      settled.setValue(1);
      return;
    }

    Animated.spring(settled, {
      toValue: 1,
      // Low friction against a high tension: it arrives fast and overshoots
      // once. Anything softer reads as a loading state rather than as a thing
      // being set down.
      friction: 5,
      tension: 180,
      useNativeDriver: true,
    }).start();
  }, [calm, settled, taken]);

  return settled;
}

const CARD = 168;
const FACE = 72;

const styles = StyleSheet.create({
  card: {
    width: CARD,
    padding: space.base,
    borderRadius: radius.card,
    backgroundColor: color.card,
    borderWidth: 2,
    // Transparent rather than absent, so selecting one does not move it two
    // points and nudge the whole row.
    borderColor: 'transparent',
    gap: space.tight,
  },
  taken: { borderColor: color.primary },
  closed: { opacity: 0.72 },
  pressed: { opacity: 0.6 },

  face: {
    width: FACE,
    height: FACE,
    borderRadius: FACE / 2,
    backgroundColor: color.surface,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  portrait: { width: FACE, height: FACE },
  initials: { ...type.headlineSm, color: color.onSurfaceVariant },

  // Over the face's corner, where a selection mark is looked for.
  seat: {
    position: 'absolute',
    top: space.base,
    left: space.base + FACE - 24,
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: color.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  seatLabel: { ...type.labelLg, color: color.onPrimary },

  // Two lines' worth, reserved. See the comment at the call site.
  title: { ...type.labelLg, color: color.onSurface, height: 40 },
  blurb: { ...type.bodySm, color: color.onSurfaceVariant },

  // Dashed, and the only card on the rail that is not a person. It reads as a
  // slot rather than as a seat somebody is in.
  author: { borderColor: color.hairline, borderStyle: 'dashed' },
  authorFace: { backgroundColor: 'transparent', borderWidth: 2, borderColor: color.hairline, borderStyle: 'dashed' },
  aside: { ...type.labelLg, color: color.onSurfaceVariant },

  /**
   * The author row, deliberately unlike the cards above it.
   *
   * Full width, laid out horizontally, on the same left edge as the seats line
   * — everything about its shape says "a different kind of thing" rather than
   * "another one of those". A hairline above ties it to the rail it follows
   * without making it a member of it.
   */
  authorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    marginTop: space.base,
    paddingTop: space.base,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.hairline,
  },
  rowFace: {
    width: 40,
    height: 40,
    borderRadius: 20,
  },
  rowWords: { flex: 1 },
  rowTitle: { ...type.labelLg, color: color.onSurface },
  rowBlurb: { ...type.bodySm, color: color.onSurfaceVariant, marginTop: space.hair },
  rowAside: { ...type.labelLg, color: color.onSurfaceVariant },
});


/**
 * The archetype somebody would write themselves — a row, not a card in the rail.
 *
 * **It was the ninth card in a rail of eight, and nobody found it.** Reported
 * as *"people will not know it is there based on how it is now"*, which is
 * exactly what this component's own note was written to prevent: `may_author`
 * is published false rather than omitted "precisely so the picker can say the
 * capability exists — hiding it is how nobody ever learns it is there". Putting
 * it behind eight horizontal swipes hid it anyway, by a different mechanism.
 *
 * The deeper reason it did not belong there: **it is not a panelist you are
 * choosing among.** The rail is a set of mutually comparable options and this
 * is a different kind of thing — a capability, and eventually an action. Mixing
 * one into a list of choices is what let it read as "another one of those,
 * further along" rather than as something else entirely.
 *
 * So it is a full-width row under the rail, where the eye lands after the
 * horizontal scroll ends and where nothing has to be swiped to reach it.
 *
 * Still not pressable, at either plan value. Authoring has no endpoint yet
 * (#65), and a control that opens nothing is worse than a statement. A fact and
 * a plan name, never a locked door with a price on it — §4.5 keeps the upsell
 * out of the way of a rehearsal.
 */
export function AuthorRow({ yours }: { yours: boolean }) {
  return (
    <View style={styles.authorRow} accessibilityRole="summary">
      {/*
        The same blank face the rail's cards carry, at row scale: it says "a
        person who is not here yet" in the visual language already established
        two inches above.
      */}
      <View style={[styles.rowFace, styles.authorFace]} />

      <View style={styles.rowWords}>
        <Text style={styles.rowTitle}>Write your own</Text>
        <Text style={styles.rowBlurb}>
          Somebody this product has never met, described in your words.
        </Text>
      </View>

      <Text style={styles.rowAside}>{yours ? 'Yours' : 'On Pro'}</Text>
    </View>
  );
}
