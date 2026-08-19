import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';

import type { Attending, PanelLine } from '../../lib/voice/connection';
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
   * What the room says it is doing, and when it said so.
   *
   * #24. Five things look like silence to somebody in a room that has gone
   * quiet — it is thinking, it did not hear them, it is waiting for more, it
   * failed, or it is about to end. Three of those are told apart here.
   *
   * Reported by the server and never inferred: only it sees a final arrive, so
   * a timer on this side would be racing the network and would be wrong in
   * exactly the case that matters.
   */
  attending: { state: Attending; since: number };
  /**
   * How loud the presenter is right now, nothing to plainly speaking.
   *
   * Drives the bars. `audio/hearing.ts` records why this is amplitude at all:
   * it was asked for twice and the objection was overruled twice.
   */
  loudness: number;
  /**
   * `opening` while the socket is coming up, `ending` during the beat that
   * holds the last line before the debrief.
   */
  phase: 'opening' | 'live' | 'ending';
  /**
   * Seconds this room has been open, or null before it is.
   *
   * **Elapsed, never remaining, and the distinction is the rule.** §4.6 forbids
   * a depleting counter — "2 of 5 credits left" — because depletion framing
   * makes people ration and rationing users churn. A count UP is not that: it
   * says how long you have been going, which is the single most useful fact to
   * somebody rehearsing for a slot with a length. A board readout is ten
   * minutes; knowing you are at six is the point of the exercise.
   *
   * It is also the only honest warning available for the twelve-minute session
   * cap. §4.7 hands that over with a spoken line rather than cutting audio, and
   * a clock quietly approaching twelve is how somebody is not surprised by it.
   */
  elapsed: number | null;
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
  loudness,
  phase,
  elapsed,
  attending,
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
      {/*
        Small, high, and out of the way. It recedes by size and position rather
        than by being dimmed: on a dark ground, dimming text is how contrast
        fails, and this has to stay readable at a glance from a desk.
      */}
      {elapsed !== null && (
        <Text style={styles.clock} accessibilityLabel={spoken(elapsed)}>
          {onTheClock(elapsed)}
        </Text>
      )}

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

      <Floor
        floor={floor}
        hearing={hearing}
        loudness={loudness}
        phase={phase}
        attending={attending}
      />
    </View>
  );
}

/**
 * How long this room has been running, as a clock reads.
 *
 * Counting up rather than down. §4.6's ban is on DEPLETION — a number falling
 * toward zero makes people ration, and rationing users churn. Elapsed time is
 * the opposite framing of the same fact and is what a rehearsal actually needs:
 * the slot you are practising for has a length, and the useful question is how
 * far into it you are.
 */
function onTheClock(seconds: number): string {
  const minutes = Math.floor(seconds / 60);

  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

/**
 * The same thing for a screen reader, which should not be handed "4:32".
 *
 * Read aloud, a colon is a guess — VoiceOver may say "four thirty-two", "four
 * colon three two", or a time of day. Somebody relying on it during a room is
 * the last person who should have to work out which.
 */
function spoken(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);

  return `${minutes} minute${minutes === 1 ? '' : 's'} ${rest} second${rest === 1 ? '' : 's'} in the room`;
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
  loudness,
  phase,
  attending,
}: Pick<
  InterrogationRoomProps,
  'floor' | 'hearing' | 'loudness' | 'phase' | 'attending'
>) {
  const yours = floor === 'yours' && phase === 'live';

  return (
    <View style={styles.floorRow} pointerEvents="none">
      {yours && hearing === 'faint' && (
        <Text style={styles.faint} accessibilityLiveRegion="polite">
          We can barely hear you — try moving closer.
        </Text>
      )}

      {yours && hearing !== 'faint' && <Doing attending={attending} />}

      <SoundBar
        loudness={yours ? loudness : 0}
        lit={yours}
        // The one state where the bars would otherwise be dead: the floor is
        // still the presenter's, they have stopped talking, and the room owes
        // them an answer. Nothing on this screen moves, which is precisely the
        // moment they start to wonder whether it heard them.
        working={yours && attending.state === 'working'}
      />
    </View>
  );
}

/**
 * What the room is doing, in the fewest words that answer it.
 *
 * **Silent while listening**, deliberately. The sound bar directly above is
 * already moving when the presenter speaks, and words there would be a second
 * answer to a question already answered — which is the mistake that took a
 * panelist off the screen mid-sentence. It speaks only when it knows something
 * the bar does not.
 *
 * **Plain, not in character.** Chosen by the architect over an in-world
 * reading. These are the only non-diegetic lines in the room: everything else
 * heard or read there is a panelist. Somebody asking "is this thing on?" wants
 * the system to answer, not the CFO — and blurring which voice is which is
 * worst at exactly the moment they suspect it is broken.
 *
 * It yields to the faint-audio warning rather than stacking with it. Two lines
 * of machinery on a hands-free screen is a paragraph nobody glancing will read,
 * and "we can barely hear you" is the more actionable of the two.
 */
function Doing({ attending }: Pick<InterrogationRoomProps, 'attending'>) {
  const held = useHeldFor(attending.since, attending.state === 'working');

  if (attending.state === 'listening') {
    return null;
  }

  return (
    <Text style={styles.doing} accessibilityLiveRegion="polite">
      {attending.state === 'heard'
        ? 'Got that.'
        : held < PATIENCE
          ? 'Working on it.'
          : `Working on it — ${held}s`}
    </Text>
  );
}

/**
 * How long the room has been in this state, in whole seconds.
 *
 * Only ticks while it is worth showing, so a listening room holds no timer at
 * all. A hang stated as a number is a fact somebody can act on; a hang stated
 * as nothing is the silence this whole thing exists to replace.
 */
function useHeldFor(since: number, ticking: boolean): number {
  const [held, setHeld] = useState(0);

  useEffect(() => {
    if (!ticking) {
      setHeld(0);
      return;
    }

    const tick = setInterval(
      () => setHeld(Math.floor((Date.now() - since) / 1000)),
      1000
    );

    return () => clearInterval(tick);
  }, [since, ticking]);

  return held;
}

/**
 * How long a turn may take before the room says how long it has taken.
 *
 * Under this it is an ordinary pause and a number would be noise — composition
 * measures 0.82s and synthesis 0.89s. Past it something is slow, and saying so
 * is the difference between somebody waiting and somebody giving up.
 */
const PATIENCE = 4;

/**
 * The presenter's own voice, as bars.
 *
 * **Asked for directly, twice.** The case against was that a bar tracking
 * volume teaches somebody to watch how loud they are rather than what they are
 * saying — the delivery-metrics reflex this product exists to refuse. It was
 * raised and overruled, and what is here is what was asked for. This note is
 * not a hedge; it is so the next person reading it knows the trade was decided
 * rather than drifted into.
 *
 * The newest reading is the middle bar and older ones spread outward, so a
 * syllable opens from the centre and travels to the edges. That is the shape a
 * voice makes rather than the shape a graph makes, and it puts the most recent
 * thing said nearest the eye.
 *
 * Bars scale from their own centre around a common line, which is how a
 * waveform reads. Growing from the base would make them a chart.
 */
function SoundBar({
  loudness,
  lit,
  working,
}: {
  loudness: number;
  lit: boolean;
  working: boolean;
}) {
  const calm = useReduceMotion();
  const bars = useRef(
    Array.from({ length: SPAN }, () => new Animated.Value(QUIET))
  ).current;
  const history = useRef<number[]>(Array.from({ length: SPAN }, () => 0)).current;
  /**
   * The room's own motion, nought to one, once per cycle.
   *
   * **Whose movement it is, is the whole signal.** The presenter's voice blooms
   * out of the middle and dies away symmetrically, because the bars either side
   * of centre show older readings. This travels — a swell crossing the row in
   * one direction — so it cannot be mistaken for somebody being heard even
   * though it uses the same thirteen bars. Nobody has to be told which is
   * which; they simply do not look alike.
   *
   * One authored moment rather than several. `heard` gets none, and that is
   * deliberate: the presenter is still talking through it, so the bars are
   * already alive with their own voice and a second animation would be fighting
   * them for the same pixels.
   */
  const swell = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!working || calm) {
      swell.setValue(0);
      return;
    }

    const crossing = Animated.loop(
      Animated.timing(swell, {
        toValue: 1,
        // Unhurried on purpose. A fast pulse reads as a spinner — a thing
        // waiting on a network — and this is a room considering an answer.
        duration: 2200,
        easing: Easing.inOut(Easing.quad),
        useNativeDriver: true,
      })
    );
    crossing.start();

    return () => {
      crossing.stop();
      swell.setValue(0);
    };
  }, [calm, swell, working]);

  useEffect(() => {
    history.unshift(loudness);
    history.length = SPAN;

    bars.forEach((bar, index) => {
      // Distance from the middle picks how old a reading this bar shows: the
      // centre is now, the edges are half a second ago.
      const height = QUIET + (history[Math.abs(index - MIDDLE)] ?? 0) * (1 - QUIET);

      Animated.timing(bar, {
        toValue: lit ? height : QUIET,
        // Short, because a reading lands every hundred milliseconds and
        // anything longer would still be catching up when the next arrives.
        duration: calm ? 0 : 110,
        useNativeDriver: true,
      }).start();
    });
  }, [bars, calm, history, lit, loudness]);

  return (
    <View
      testID="floor"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={styles.bars}
    >
      {bars.map((bar, index) => (
        <Animated.View
          key={index}
          style={[
            styles.bar,
            lit && styles.barLit,
            { transform: [{ scaleY: working && !calm ? crossing(swell, index) : bar }] },
          ]}
        />
      ))}
    </View>
  );
}

/** How many bars. Odd, so there is a middle for the newest reading to sit in. */
const SPAN = 13;
const MIDDLE = (SPAN - 1) / 2;

/**
 * The height a bar rests at with nothing arriving.
 *
 * Never zero. A row that collapsed to nothing between words would flicker out
 * of existence several times a sentence, and an indicator nobody can find while
 * it is quiet cannot reassure them the room is still listening.
 */
const QUIET = 0.12;

/** The row's full height. Bars scale within it rather than resizing it. */
const BAR_H = 44;

/**
 * How far the room's own swell lifts a bar.
 *
 * Small, and the smallness is load-bearing. It has to read in peripheral vision
 * on a phone lying flat, and it must never be mistaken for a voice — somebody
 * speaking normally fills far more of the bar than this, so the two never
 * occupy the same range and the eye can tell them apart without being told.
 */
const SWELL = 0.28;

/**
 * One bar's part in a swell crossing the row.
 *
 * Each peaks a little after the one before it, so the movement reads as
 * *travelling* rather than as thirteen bars breathing in unison — which would
 * look like a heartbeat, and a heartbeat on a screen means something is wrong.
 *
 * That direction is the entire signal. The presenter's own voice blooms out of
 * the middle and decays symmetrically, because the bars either side of centre
 * show older readings. The room's does not. Same thirteen bars, two motions
 * nobody could confuse.
 *
 * The phase sits inside the cycle rather than at its ends, so the first and
 * last bars get a whole rise and fall instead of a clipped one.
 */
function crossing(
  swell: Animated.Value,
  index: number
): Animated.AnimatedInterpolation<number> {
  const peak = EDGE + (index / (SPAN - 1)) * (1 - EDGE * 2);

  return swell.interpolate({
    inputRange: [0, peak - RAMP, peak, peak + RAMP, 1],
    outputRange: [QUIET, QUIET, QUIET + SWELL, QUIET, QUIET],
    extrapolate: 'clamp',
  });
}

/**
 * How far into the cycle the first bar peaks, and how far from the end the last
 * one does.
 *
 * The margin exists so the outermost bars get a whole rise and fall rather than
 * a clipped one — and it bounds `RAMP`, because a ramp wider than this margin
 * puts a negative number in the input range and React Native refuses it
 * outright ("inputRange must be monotonically non-decreasing").
 */
const EDGE = 0.15;

/** How much of the cycle one bar spends rising and falling. Under `EDGE`. */
const RAMP = 0.12;

const styles = StyleSheet.create({
  room: { flex: 1, backgroundColor: color.roomGround },

  clock: {
    ...type.bodySm,
    color: color.onRoom,
    fontVariant: ['tabular-nums'],
    textAlign: 'center',
    paddingTop: space.snug,
    // Half strength by *placement*, not by colour. It is the smallest thing on
    // the screen and the furthest from the eye, which is enough.
    opacity: 0.55,
  },

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
  // Same size and place as the faint warning it stands in for, so the two never
  // shift the bar beneath them. Dimmer, because this is the ordinary case and
  // that one is a problem.
  doing: {
    ...type.bodySm,
    color: color.onRoom,
    opacity: 0.6,
    textAlign: 'center',
    paddingHorizontal: space.screen,
  },

  faint: {
    ...type.bodySm,
    color: color.roomAmber,
    textAlign: 'center',
    paddingHorizontal: space.screen,
  },
  /**
   * The bar row, on the near edge.
   *
   * A fixed height with bars SCALED rather than resized, so every frame runs on
   * the native driver — this updates ten times a second for twelve minutes and
   * must not touch the JS thread to do it.
   */
  bars: {
    height: BAR_H,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.hair,
  },
  bar: {
    width: 4,
    height: BAR_H,
    borderRadius: radius.pill,
    backgroundColor: color.roomTray,
  },
  barLit: { backgroundColor: color.roomAmber },

});
