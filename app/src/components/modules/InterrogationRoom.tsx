import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Pressable, StyleSheet, Text, View } from 'react-native';

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
  const breath = useBreath(heard);

  return (
    <View style={styles.floorRow}>
      {yours && hearing === 'faint' && (
        <Text style={styles.faint} accessibilityLiveRegion="polite">
          We can barely hear you — try moving closer.
        </Text>
      )}
      <Animated.View
        testID="floor"
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={[
          styles.floor,
          yours && styles.floorYours,
          heard && styles.floorHeard,
          { transform: [{ scaleX: breath }] },
        ]}
      />
    </View>
  );
}

/**
 * The floor, alive while it is hearing you.
 *
 * A colour change alone was not enough on a device: a static bar that goes from
 * one dim tone to another says nothing at the edge of vision, which is the only
 * place this is ever seen. What reads is *movement*, and this is the one place
 * on the screen where movement is the right answer — it is the user's own side
 * of the table, and the question it answers is "is this thing on".
 *
 * **Still not a level meter.** It breathes at a fixed rate rather than tracking
 * amplitude: the presenter's question is whether their voice is reaching the
 * room, and a bar that moved WITH their volume would teach them to watch how
 * loud they are instead of what they are saying — which is the delivery-metrics
 * product this one exists to refuse. Fixed-rate motion answers "yes, and still
 * yes" without ever being a reading of anything.
 *
 * Horizontal only, from the centre out. It grows along the edge it already
 * occupies rather than getting taller, so nothing on the screen moves except a
 * line that was already a line.
 */
function useBreath(alive: boolean): Animated.Value {
  const width = useRef(new Animated.Value(alive ? 1 : REST)).current;
  const calm = useReduceMotion();
  const [table, setTable] = useState(0);

  useEffect(() => {
    if (!alive) {
      Animated.timing(width, {
        toValue: REST,
        duration: calm ? 0 : 260,
        useNativeDriver: true,
      }).start();
      return;
    }

    if (calm) {
      // Reduce Motion still gets the *state*, at full width and steady. What it
      // gives up is the loop, not the answer to "is this thing on".
      width.setValue(1);
      return;
    }

    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(width, {
          toValue: 1,
          duration: 900,
          useNativeDriver: true,
        }),
        Animated.timing(width, {
          toValue: 0.82,
          duration: 900,
          useNativeDriver: true,
        }),
      ])
    );
    loop.start();

    return () => loop.stop();
  }, [alive, calm, width]);

  return width;
}

/** How wide the floor sits when the room is not hearing anything. */
const REST = 0.35;

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

  floorRow: { gap: space.tight, paddingBottom: space.tight },
  faint: {
    ...type.bodySm,
    color: color.roomAmber,
    textAlign: 'center',
    paddingHorizontal: space.screen,
  },
  // Thicker than a hairline now that it moves: a 3pt line scaling
  // horizontally reads as a rendering artefact rather than as a thing
  // responding to you.
  floor: { height: 5, marginHorizontal: space.screen, borderRadius: radius.pill },
  floorYours: { backgroundColor: color.roomTray },
  floorHeard: { backgroundColor: color.roomAmber },
});
