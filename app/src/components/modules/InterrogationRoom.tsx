import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';

import type { PanelLine } from '../../lib/voice/connection';
import { portraitOf } from '../../lib/archetypes/portraits';
import { useReduceMotion } from '../../lib/a11y/reduceMotion';
import { color, radius, space, type } from '../../theme/tokens';
import { Tray } from './Tray';

/**
 * The live interrogation, and the only screen in this app that is not on paper.
 *
 * Everything else sits on the warm off-white. This does not, and DESIGN.md
 * carves out the exception: the phone lies flat on a desk for twelve minutes
 * while somebody argues, and a page-bright screen in that position is a lamp
 * pointed at the ceiling. You go into the dark room, and you come out.
 *
 * **Split field, mapped to physical distance.** The phone is flat, so the top
 * of the screen is further from the eye than the bottom. The far field is the
 * room — one tray per seated archetype, the speaker's developing. The near
 * field is the record: who is asking, what they asked, and the single control.
 *
 * **One touch target on the whole screen.** Nothing else here is tappable, and
 * there is deliberately no push-to-talk: the microphone is open for the length
 * of the room, and interrupting a panelist is done by talking over them, which
 * is the feature the voice provider was chosen for. A button you had to find
 * before you could cut somebody off would remove it.
 *
 * Props rather than a socket, because the route above owns the connection, the
 * microphone and the meter, and none of those can be rendered.
 */

/** One archetype in the room, named as the catalogue names them. */
export interface Seat {
  /** The slug, matching `speaking` and the wire's `speaker`. */
  name: string;
  /** What a person is called, for the caption and the screen reader. */
  title: string;
}

/**
 * What the microphone is picking up.
 *
 * Three states, not a level. The question a presenter has is *is my voice
 * reaching the room* — presence, not loudness — and a bar that moved with
 * amplitude would be the single most attention-capturing object on a screen
 * whose whole premise is that nobody looks at it. At sixty centimetres and an
 * oblique angle it could not be read as a quantity anyway.
 *
 * `faint` earns its place all the same: a presence light can say "hearing you"
 * while the transcriber gets mush, and then the room answers a garbled question
 * and the *panel* looks stupid. It is the only one of the three that speaks.
 */
export type Hearing = 'silent' | 'hearing' | 'faint';

export interface InterrogationRoomProps {
  /** Seated archetypes, in the order the server seated them. */
  panel: Seat[];
  /** Whose voice is in the room, by `Seat.name`, or null between turns. */
  speaking: string | null;
  /** The panel's current line. Null before anybody has spoken. */
  line: PanelLine | null;
  floor: 'panel' | 'yours';
  hearing: Hearing;
  /**
   * `opening` while the socket is coming up, `ending` during the beat that
   * holds the last line before the debrief.
   */
  phase: 'opening' | 'live' | 'ending';
  onEnd: () => void;
}

/** How long a print takes to develop, and the beat it is cut to under Reduce Motion. */
const DEVELOP_MS = 1400;

/** How long "Tap again to end" stands before the control forgets it was asked. */
const ARMED_MS = 4000;

export function InterrogationRoom({
  panel,
  speaking,
  line,
  floor,
  hearing,
  phase,
  onEnd,
}: InterrogationRoomProps) {
  const calm = useReduceMotion();
  const [table, setTable] = useState(0);
  const [armed, setArmed] = useState(false);
  const forget = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (forget.current !== null) {
        clearTimeout(forget.current);
      }
    },
    []
  );

  const end = useCallback(() => {
    if (armed) {
      setArmed(false);
      onEnd();
      return;
    }

    // Confirmed in place rather than in a dialog. The brief allows one touch
    // target and no modal, and the phone is lying flat under somebody's hands
    // while they gesture — a brushed thumb on the near edge would otherwise end
    // a rehearsal that cannot be resumed. The first tap teaches what the second
    // does, which a press-and-hold never could.
    setArmed(true);
    forget.current = setTimeout(() => setArmed(false), ARMED_MS);
  }, [armed, onEnd]);

  return (
    <View style={styles.room}>
      <View
        style={styles.far}
        // The row's width, so a seat can be told how far it is from the middle.
        // A seat cannot work that out for itself, and React Native has no
        // percentage translate to fake it with.
        onLayout={(event) => setTable(event.nativeEvent.layout.width)}
      >
        {panel.map((seat, index) => (
          <Tray
            key={seat.name}
            label={seat.title}
            portrait={portraitOf(seat.name)}
            speaking={seat.name === speaking}
            toCentre={centreShift(table, index, panel.length)}
            develop={calm ? 0 : DEVELOP_MS}
          />
        ))}
      </View>

      <View style={styles.near}>
        <Said line={line} panel={panel} phase={phase} />

        {phase !== 'ending' && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={armed ? 'Tap again to end the room' : 'End the room'}
            accessibilityHint={
              armed ? undefined : 'Asks once more before the room closes.'
            }
            onPress={end}
            style={({ pressed }) => [styles.end, pressed && styles.pressed]}
          >
            <Text style={styles.endLabel}>{armed ? 'Tap again to end' : 'End'}</Text>
          </Pressable>
        )}
      </View>

      <Floor floor={floor} hearing={hearing} phase={phase} />
    </View>
  );
}

/**
 * How far seat `index` has to slide to reach the middle of the table.
 *
 * With seats laid out evenly, seat i of n sits at `((i + 0.5) / n) * width`,
 * and the middle is `width / 2`. The difference is the distance, and it is
 * naturally zero for the middle seat of an odd-sized room — which is right:
 * somebody already in the centre should not move to take the floor, they
 * should simply come up out of the dark.
 */
function centreShift(width: number, index: number, seats: number): number {
  if (width === 0 || seats === 0) {
    return 0;
  }

  return width / 2 - ((index + 0.5) / seats) * width;
}

/**
 * The record: who is asking, and what they asked.
 *
 * The line is shown **whole**, not word by word. The wire carries finished
 * utterances and no word timing — the caption arrives before its own audio — so
 * emergence would be the phone guessing a speech rate and drifting out of sync
 * with the voice. It would look like transcription and be theatre, on the one
 * screen that has to be trusted at a glance. It is also worst for the reader
 * the captions exist for, who would be paced by a soundtrack they cannot hear.
 *
 * The name is here rather than on the tray because caption standards want the
 * speaker identified wherever more than one person speaks, and a rectangle
 * deepening in peripheral vision tells a deaf reader nothing about who is
 * asking.
 */
function Said({
  line,
  panel,
  phase,
}: Pick<InterrogationRoomProps, 'line' | 'panel' | 'phase'>) {
  if (line === null) {
    return (
      <Text style={styles.waiting} accessibilityLiveRegion="polite">
        {/* The panel does not open the room — a turn is only composed once
            somebody has said something — and the meter is already running by
            the time this renders. A presenter left wondering whether it is
            working is being billed for the wondering. */}
        {phase === 'opening'
          ? 'Opening the room…'
          : 'The room is listening. Take it away.'}
      </Text>
    );
  }

  const said = panel.find((seat) => seat.name === line.speaker);

  return (
    <View style={styles.said}>
      <Text style={styles.who}>{said?.title ?? line.speaker}</Text>
      <Text style={styles.line} accessibilityLiveRegion="polite">
        {line.text}
      </Text>
    </View>
  );
}

/**
 * The nearest edge: your own side of the table.
 *
 * Lit when the floor is yours, brighter while you are being heard. Deliberately
 * not the ambient ground — the safelight is spoken for, and room temperature
 * will warm and cool the whole screen when it is built.
 */
function Floor({
  floor,
  hearing,
  phase,
}: Pick<InterrogationRoomProps, 'floor' | 'hearing' | 'phase'>) {
  const yours = floor === 'yours' && phase === 'live';
  const heard = yours && hearing === 'hearing';

  return (
    <View style={styles.floorRow} pointerEvents="none">
      {yours && hearing === 'faint' && (
        <Text style={styles.faint} accessibilityLiveRegion="polite">
          We can barely hear you — try moving closer.
        </Text>
      )}

      <View
        testID="floor"
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={styles.floor}
      >
        {/* Three, staggered, so the edge is never empty between them — one arc
            alone reads as a repeating blip rather than as something
            continuous. */}
        {[0, 1, 2].map((index) => (
          <Arc key={index} alive={heard} at={index} />
        ))}

        {/* Always drawn, under the arcs. The room has a near edge whether or
            not anybody is talking, and an indicator that only exists while it
            is firing cannot be found when it is not. */}
        <View style={[styles.sill, yours && styles.sillYours]} />
      </View>
    </View>
  );
}

/**
 * One ripple off the presenter's own edge of the table.
 *
 * **The same language the panel speaks, pointing the other way.** A panelist
 * with the floor emits an expanding ring; the presenter's side emits arcs off
 * the near edge. Two directions of one idea, so neither has to be learned — and
 * it puts the user in the room rather than outside it looking in.
 *
 * **Still not a level meter.** These run at a fixed rate rather than tracking
 * amplitude, and the reason is unchanged: a thing that moved with somebody's
 * volume would teach them to watch how loud they are instead of what they are
 * saying, which is precisely the delivery-metrics product this one refuses.
 * Fixed motion answers "yes, and still yes" and is a reading of nothing.
 *
 * The arc is the top of a circle far wider than the screen, most of it below
 * the bottom edge — so what shows is a shallow curve opening upward, which is
 * what a ripple looks like from inside it.
 */
function Arc({ alive, at }: { alive: boolean; at: number }) {
  const out = useRef(new Animated.Value(0)).current;
  const calm = useReduceMotion();

  useEffect(() => {
    if (!alive || calm) {
      out.setValue(0);
      return;
    }

    const loop = Animated.loop(
      Animated.timing(out, {
        toValue: 1,
        duration: RIPPLE_MS,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      })
    );

    // Staggered rather than started together, or all three would be the same
    // arc drawn three times.
    const start = setTimeout(() => loop.start(), (RIPPLE_MS / 3) * at);

    return () => {
      clearTimeout(start);
      loop.stop();
      out.setValue(0);
    };
  }, [alive, at, calm, out]);

  return (
    <Animated.View
      style={[
        styles.arc,
        {
          opacity: out.interpolate({
            inputRange: [0, 0.12, 1],
            outputRange: [0, 0.45, 0],
          }),
          transform: [
            { scale: out.interpolate({ inputRange: [0, 1], outputRange: [0.7, 1.35] }) },
          ],
        },
      ]}
    />
  );
}

/** One ripple, from the edge to gone. Slow enough to read as breathing. */
const RIPPLE_MS = 2100;

/** Wider than any phone, so the visible part is a shallow curve, not a circle. */
const ARC = 520;

const styles = StyleSheet.create({
  room: { flex: 1, backgroundColor: color.roomGround },

  // 55/45, the surface brief's split, and it is about distance rather than
  // proportion: on a phone lying flat the top of the screen is further from the
  // eye, so the room goes up there and the words come down here.
  // The room sits at the top of the far field rather than filling it. Given
  // the whole 55% the trays stretched into three tall slabs — on a device they
  // read as empty cards waiting for content, which is the opposite of
  // peripheral. Seats are small and the air around them is the room.
  // A row, and centred in its half rather than pinned to the top. Stacked,
  // three seats were a list of three things; across, they are people on the
  // other side of a table — which is what the whole product is a rehearsal
  // for. `space-around` rather than `space-between` so a room of two does not
  // put one face in each corner with the table missing from the middle.
  far: {
    flex: 55,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-around',
    paddingHorizontal: space.screen,
  },
  near: {
    flex: 45,
    paddingHorizontal: space.screen,
    justifyContent: 'space-between',
    paddingBottom: space.base,
  },

  said: { gap: space.tight },
  who: { ...type.labelLg, color: color.roomAmber },
  // The screen's only real content, and sized for a glance from arm's length
  // rather than for a paragraph.
  line: { ...type.headlineMd, color: color.onRoom },
  // Full strength, not dimmed. Shipped at `roomTray` it measured 1.73:1
  // against the ground — a surface colour used as text — and it was wrong
  // twice over: before the first line arrives this sentence is not secondary
  // to anything, it is the whole screen.
  waiting: { ...type.bodyLg, color: color.onRoom },

  // The one enamel-white object, at the nearest edge, findable by position
  // without looking.
  end: {
    alignSelf: 'center',
    minHeight: 44,
    minWidth: 140,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    backgroundColor: color.onRoom,
  },
  endLabel: { ...type.labelLg, color: color.roomGround },
  pressed: { opacity: 0.6 },

  // The room's near edge, and it needs air above it. End sat eight points off
  // the ripples, which put a control inside an animation — the button looked
  // like part of the effect and the effect looked like it belonged to the
  // button.
  floorRow: { gap: space.tight, paddingBottom: space.base, marginTop: space.section },
  faint: {
    ...type.bodySm,
    color: color.roomAmber,
    textAlign: 'center',
    paddingHorizontal: space.screen,
  },
  // The band the ripples happen in. Tall enough that an arc has somewhere to
  // travel; `overflow: hidden` keeps them from climbing into the caption.
  floor: {
    height: 56,
    alignItems: 'center',
    justifyContent: 'flex-end',
    overflow: 'hidden',
  },

  /**
   * The arc, which is the top of a circle far wider than the screen with most
   * of it below the bottom edge. What shows is a shallow curve opening upward
   * — a ripple seen from inside it.
   */
  arc: {
    position: 'absolute',
    bottom: -ARC / 2,
    width: ARC,
    height: ARC,
    borderRadius: ARC / 2,
    borderWidth: 2,
    borderColor: color.roomAmber,
  },

  // Always there. A near edge that only existed while somebody was talking
  // could not be found when they were not.
  sill: {
    height: 3,
    width: 96,
    borderRadius: radius.pill,
    backgroundColor: color.roomTray,
  },
  sillYours: { backgroundColor: color.roomAmber, opacity: 0.55 },
});
