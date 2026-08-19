import { useEffect, useRef } from 'react';
import { Animated, StyleSheet } from 'react-native';

import { color, radius } from '../../theme/tokens';

/**
 * One archetype, as a print in a developer tray.
 *
 * The far field of the interrogation screen is the room, and this is a seat in
 * it. No face, no avatar, no name — those live in the near field beside the
 * line, where a caption can be read rather than glanced at. What this carries
 * is one fact: whether this person currently holds the floor.
 *
 * **It develops rather than switching on.** A print in a darkroom shows itself
 * over seconds, and the surface brief makes that the screen's whole motion
 * language: continuous emergence, never a typewriter tick, never a pulse. A
 * rectangle that snapped between two greys would be a status light, and a
 * throbbing one would be the thing a hands-free user cannot stop looking at.
 *
 * The *state* comes from real signals — a caption naming this archetype, and
 * the `turn_finished` frame handing the floor back. Only the rise time is
 * animation. Nothing here guesses how long an utterance will be, which is why
 * it holds at full density until the floor actually returns instead of fading
 * out on a timer that would sometimes be wrong.
 */
export interface TrayProps {
  /** True while this archetype holds the floor. */
  speaking: boolean;
  /** Spoken by a screen reader; the visual carries no text at all. */
  label: string;
  /** Zero when the user has asked for less motion, in which case it cuts. */
  develop: number;
}

export function Tray({ speaking, label, develop }: TrayProps) {
  const developed = useRef(new Animated.Value(speaking ? 1 : 0)).current;

  useEffect(() => {
    Animated.timing(developed, {
      toValue: speaking ? 1 : 0,
      // Receding is quicker than developing. A print takes its time appearing
      // and is lifted out of the tray in one movement — and on the screen it
      // means the room clears promptly for whoever speaks next, without the
      // two trays ever looking equally lit.
      duration: speaking ? develop : Math.round(develop / 3),
      // Colour cannot be driven off the UI thread, and this is one interpolated
      // background on a screen with no list and no scrolling. The alternative
      // is animating opacity over a stacked pair of views to buy a property
      // nothing here is contending for.
      useNativeDriver: false,
    }).start();
  }, [develop, developed, speaking]);

  return (
    <Animated.View
      testID="tray"
      // The room is described once, in the near field, by the line and the name
      // beside it. Three rectangles announcing themselves on every turn would
      // bury that under furniture.
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      accessibilityLabel={label}
      style={[
        styles.tray,
        {
          backgroundColor: developed.interpolate({
            inputRange: [0, 1],
            outputRange: [color.roomTray, color.roomTrayLit],
          }),
        },
      ]}
    />
  );
}

/**
 * A seat's height, fixed rather than shared out.
 *
 * `flex: 1` gave each tray a third of the far field, and on a phone that is a
 * slab the size of a card. Three of them read as empty containers rather than
 * as people across a table — the far field is meant to be glanced at, and
 * nothing that large is ever glanced at.
 */
const SEAT = 56;

const styles = StyleSheet.create({
  tray: {
    height: SEAT,
    borderRadius: radius.control,
  },
});
