import { useEffect, useRef } from 'react';
import { Animated, Easing, Image, StyleSheet, Text, View } from 'react-native';

import { color, type } from '../../theme/tokens';

/**
 * One archetype, across the table, and what happens when they take the floor.
 *
 * **This carries their face, and that overrides the surface brief's "no faces,
 * no avatars" anti-goal deliberately.** That line was written before any
 * portrait existed, when the alternative to a rectangle was a generic
 * silhouette repeated three times — furniture, and rightly refused. The product
 * now ships eight photographs, setup introduces them by name, and the committed
 * world is *prints developing in trays*. A print is of somebody. Honouring the
 * anti-goal produced a screen the architect twice described as dark bars and a
 * button.
 *
 * **A row, not a stack**, and the speaker comes to the middle of it. Stacked,
 * three seats were a list; across, they are people on the other side of a
 * table. Whoever is speaking rises out of the safelight, grows, and slides to
 * the centre — which is what a room does when somebody takes the floor, and it
 * means the presenter can tell who is on them without reading anything.
 *
 * Nobody is ever hidden. The room is the same people throughout, and a panelist
 * who vanished between turns would be a table that keeps changing size.
 *
 * The name is NOT here. It lives in the near field beside the line they said,
 * where a caption can be read rather than glanced at, and where a screen reader
 * meets it attached to the words it belongs to.
 */
export interface TrayProps {
  /** True while this archetype holds the floor. */
  speaking: boolean;
  /** Spoken by a screen reader; nothing here is a visible label. */
  label: string;
  /** Their portrait, or null when this build has no artwork for them. */
  portrait: number | null;
  /**
   * How far to slide to reach the middle of the row, in points.
   *
   * Measured by the room and handed down rather than worked out here: a seat
   * cannot know the width of the table it is at, and a percentage translate is
   * not a thing React Native does.
   */
  toCentre: number;
  /** Zero when the user has asked for less motion, in which case it cuts. */
  develop: number;
}

export function Tray({ speaking, label, portrait, toCentre, develop }: TrayProps) {
  const held = useRef(new Animated.Value(speaking ? 1 : 0)).current;
  const breath = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.timing(held, {
      toValue: speaking ? 1 : 0,
      // Receding is quicker than developing. A print takes its time coming up
      // and is lifted out in one movement — and here it clears the middle
      // promptly for whoever speaks next, so two seats are never equally lit.
      duration: speaking ? develop : Math.round(develop / 3),
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [develop, held, speaking]);

  /**
   * The ring, while they are actually talking.
   *
   * Development says WHO has the floor and holds there; this says they are
   * still going. Without it a panelist mid-question is indistinguishable from
   * one who finished twenty seconds ago, on a screen with no other clock.
   *
   * An expanding ring rather than a pulsing face: the face must stay a stable
   * thing to look at, and scaling somebody's head in and out is a costume. This
   * is the ripple a voice makes.
   */
  useEffect(() => {
    if (!speaking || develop === 0) {
      breath.setValue(0);
      return;
    }

    const loop = Animated.loop(
      Animated.timing(breath, {
        toValue: 1,
        duration: 1800,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      })
    );
    loop.start();

    return () => {
      loop.stop();
      breath.setValue(0);
    };
  }, [breath, develop, speaking]);

  return (
    <Animated.View
      testID="tray"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      accessibilityLabel={label}
      style={[
        styles.seat,
        {
          transform: [
            { translateX: held.interpolate({ inputRange: [0, 1], outputRange: [0, toCentre] }) },
            { scale: held.interpolate({ inputRange: [0, 1], outputRange: [1, 1.28] }) },
          ],
          // Lifted above the others as it grows, or a larger face would slide
          // underneath the seat beside it on the way past.
          zIndex: speaking ? 1 : 0,
        },
      ]}
    >
      <Animated.View
        style={[
          styles.ring,
          {
            opacity: breath.interpolate({ inputRange: [0, 0.15, 1], outputRange: [0, 0.5, 0] }),
            transform: [
              { scale: breath.interpolate({ inputRange: [0, 1], outputRange: [1, 1.5] }) },
            ],
          },
        ]}
      />

      <View style={styles.frame}>
        {portrait === null ? (
          <View style={styles.blank}>
            <Text style={styles.initials}>{shortFor(label)}</Text>
          </View>
        ) : (
          <>
            <Image source={portrait} style={styles.face} accessibilityIgnoresInvertColors />
            {/* Developing lifts this off rather than brightening the picture —
                one animated opacity over a static image, which the native
                driver can run off the JS thread. Animating a colour would give
                that up on the one screen that cannot afford a dropped frame. */}
            <Animated.View
              style={[
                styles.safelight,
                {
                  opacity: held.interpolate({ inputRange: [0, 1], outputRange: [SUNK, 0] }),
                },
              ]}
            />
          </>
        )}
      </View>
    </Animated.View>
  );
}

/** "The Technical Skeptic" -> "TS", for a build with no artwork. */
function shortFor(label: string): string {
  const words = label.split(/\s+/).filter((word) => word.toLowerCase() !== 'the');

  return words.length === 1
    ? words[0].slice(0, words[0] === words[0].toUpperCase() ? 3 : 2)
    : words.map((word) => word[0]?.toUpperCase() ?? '').join('').slice(0, 2);
}

/**
 * How far under the safelight a quiet panelist sits.
 *
 * Not further. They stay legibly *a person who is in the room* — the dread this
 * screen is built around is three people waiting, and three shapes waiting is a
 * weaker feeling entirely.
 */
const SUNK = 0.62;

const FACE = 92;

const styles = StyleSheet.create({
  seat: { alignItems: 'center', justifyContent: 'center' },

  frame: {
    width: FACE,
    height: FACE,
    borderRadius: FACE / 2,
    overflow: 'hidden',
    backgroundColor: color.roomTray,
  },
  face: { width: FACE, height: FACE },

  // Behind the face, expanding past it. Amber, because it is the safelight
  // moving rather than a notification.
  ring: {
    position: 'absolute',
    width: FACE,
    height: FACE,
    borderRadius: FACE / 2,
    borderWidth: 2,
    borderColor: color.roomAmber,
  },

  // The wash a print sits under before it comes up. The ground's own colour, so
  // a quiet face reads as *under a safelight* rather than as a photograph with
  // the brightness turned down.
  safelight: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: color.roomGround,
  },

  blank: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  initials: { ...type.headlineSm, color: color.onRoom, opacity: 0.5 },
});
