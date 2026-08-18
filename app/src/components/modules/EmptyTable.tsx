import { StyleSheet, View } from 'react-native';

import { color, radius, space } from '../../theme/tokens';

/**
 * The table, seen from above, with their side filled and yours empty.
 *
 * Third answer to the same question and the one that holds. The seated chairs
 * were drawn here first and removed — the architect read them as the panel on
 * sight, which is the confusion `plan.ts` keeps the whole seat vocabulary in
 * place to avoid, and the translation to archetypes belongs to the server
 * because it is the payoff. The app icon went there second, which claimed
 * nothing but also said nothing: a logo is about the company, and this is the
 * last screen before somebody decides the product is worth an account.
 *
 * A fourth thing was tried and thrown away, which is worth recording because it
 * looked right in source. `Chair`'s exact geometry — a vertical rail with marks
 * on it, at the content column's left edge — is literal continuity with the
 * screen they just came from, and on a device it read as a scrollbar. A rail
 * down the left margin is a list ornament, and no amount of scale turns a list
 * ornament into a drawing; it was still an ornament at 24pt, just a louder one.
 * The continuity that survives is the material, not the arrangement: hairline
 * outlines and round marks, which is what makes this recognisably the same
 * world without being the same object in the wrong job.
 *
 * **Only their side is seated.** The far edge carries the chairs, the near edge
 * is bare, and that is the one piece of meaning in the drawing: the room is
 * assembled and the presenter is not in it yet. It is also why this can sit
 * where a cast list cannot — a chair with nobody named in it claims nothing.
 *
 * Every mark is an outline. Filling one would make it a seating plan, and then
 * it is a cast list again by a slower route.
 */
export interface EmptyTableProps {
  /** How many chairs the table has. The free tier's three, today. */
  seats: number;
}

export function EmptyTable({ seats }: EmptyTableProps) {
  if (seats <= 0) return null;

  return (
    <View
      style={styles.table}
      accessible={false}
      accessibilityElementsHidden
      importantForAccessibility="no"
    >
      {Array.from({ length: seats }, (_, at) => (
        <View
          key={at}
          testID="chair-mark"
          style={[styles.chair, { left: `${place(at, seats)}%` }]}
        />
      ))}
    </View>
  );
}

/**
 * Where each chair sits along the far edge, as a percentage.
 *
 * Evenly spaced, then pushed off it. Three equal circles in a row across a
 * sign-in screen is a step indicator to everybody who has ever used a phone,
 * whatever it was drawn as — and the plan sheet refuses a progress indicator in
 * every form for reasons that do not stop applying one screen later. Uneven
 * spacing is not a decoration here; it is what stops the drawing meaning
 * something it does not mean. It is also truer: nobody sits at a table on a
 * grid.
 *
 * Deterministic rather than random, so the drawing is the same every launch and
 * a screenshot taken today matches one taken next year.
 */
const DRIFT = [-4.5, 3.5, -2, 5, -3, 2.5];

function place(at: number, seats: number): number {
  const even = ((at + 0.5) / seats) * 100;

  return even + (DRIFT[at % DRIFT.length] ?? 0);
}

const CHAIR = 22;

const styles = StyleSheet.create({
  table: {
    alignSelf: 'stretch',
    height: 156,
    borderWidth: 2,
    borderColor: color.hairline,
    // The same 28pt the cards on the previous screen use. A table drawn with a
    // radius nothing else in the product has would be a shape; drawn with this
    // one it is the same world.
    borderRadius: radius.container,
    marginTop: space.loose,
    marginBottom: space.section,
  },
  chair: {
    position: 'absolute',
    // Straddling the far edge, half in and half out, the way a chair pulled up
    // to a table overlaps it from above.
    top: -CHAIR / 2,
    // Percentages position the left edge, so half a chair of correction puts
    // the mark's centre where `place` meant it.
    marginLeft: -CHAIR / 2,
    width: CHAIR,
    height: CHAIR,
    borderRadius: CHAIR / 2,
    borderWidth: 2,
    borderColor: color.hairline,
    // Opaque, so the table edge passes behind each chair rather than through
    // it — which is what makes them sit AT the table instead of being holes
    // punched in it.
    backgroundColor: color.surface,
  },
});
