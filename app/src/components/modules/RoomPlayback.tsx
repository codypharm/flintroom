import { useRef } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { clock } from '../../lib/replay/clock';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * Hearing a room again — the transport, and nothing that makes a sound.
 *
 * **Presentation only, and the split is the whole design.** What actually plays
 * a room is `<Audio>` from `react-native-audio-api`, reached by a path the
 * package does not publish (#68) because the published one decodes an entire
 * room into memory before the first sound — a crash rather than a refusal on a
 * long readout. A private path is a thing that can move under a version bump,
 * so everything this screen *says* lives on this side of the seam, where a test
 * can reach it without mounting a native decoder.
 *
 * **The clock is not a depleting counter.** §4.6 forbids one, and it is about
 * minutes: a number counting down on something bought makes a rehearsal feel
 * expensive. This counts *up*, through a room already paid for and already
 * over, and the figure beside it is how long that room was. Nothing here is
 * spent by listening — playback plays the stored file and calls no provider.
 */

/** What the player is doing, from the point of view of somebody looking at it. */
export type Heard = 'idle' | 'opening' | 'playing' | 'paused' | 'failed';

/**
 * How far back a missed sentence is.
 *
 * Fifteen, which is the podcast convention and about two sentences of somebody
 * talking. The bar is the coarse control; this is the one for "say that again".
 */
const A_SENTENCE_OR_TWO = 15;

export interface RoomPlaybackProps {
  state: Heard;
  /** Seconds in. */
  at: number;
  /** How long the room is, or zero until the file's header has been read. */
  runs: number;
  /** What went wrong, when something did. */
  refusal: string | null;
  onPlay: () => void;
  onPause: () => void;
  /** Seconds from the start. Never called against an unmeasured bar. */
  onSeek: (seconds: number) => void;
}

export function RoomPlayback({
  state,
  at,
  runs,
  refusal,
  onPlay,
  onPause,
  onSeek,
}: RoomPlaybackProps) {
  // The bar's own width, reported by layout rather than measured with a ref.
  // Zero until the first frame has been laid out, and a tap before that is
  // dropped: dividing by it would hand `Infinity` to a native seek and throw
  // the room to its end.
  const across = useRef(0);

  const going = state === 'playing' || state === 'paused';

  if (!going) {
    return (
      <View style={styles.player}>
        {refusal !== null && (
          <Text style={styles.refusal} accessibilityRole="alert">
            {refusal}
          </Text>
        )}

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={state === 'opening' ? 'Finding it' : 'Hear this room'}
          accessibilityState={{ disabled: state === 'opening' }}
          disabled={state === 'opening'}
          onPress={onPlay}
          style={({ pressed }) => [styles.start, pressed && styles.pressed]}
        >
          {state === 'opening' ? (
            <ActivityIndicator color={color.primary} style={styles.spinner} />
          ) : (
            <View style={styles.play} />
          )}
          <Text style={styles.startLabel}>
            {state === 'opening' ? 'Finding it…' : 'Hear this room'}
          </Text>
        </Pressable>
      </View>
    );
  }

  const known = runs > 0;
  // Clamped, because position can overshoot by a frame at the very end and a
  // bar wider than its track reads as a rendering fault.
  const through = known ? Math.max(0, Math.min(1, at / runs)) : 0;

  return (
    <View style={styles.player}>
      {refusal !== null && (
        <Text style={styles.refusal} accessibilityRole="alert">
          {refusal}
        </Text>
      )}

      <Pressable
        testID="scrub"
        accessibilityRole="progressbar"
        accessibilityLabel="How far into the room"
        // Spoken rather than left to the bar's geometry. The figure is already
        // beside it for anybody who can see it; this is the same fact said.
        accessibilityValue={{
          min: 0,
          max: Math.round(runs),
          now: Math.round(at),
          text: known ? `${clock(at)} of ${clock(runs)}` : clock(at),
        }}
        onLayout={(event) => {
          across.current = event.nativeEvent.layout.width;
        }}
        onPress={(event) => {
          // Both are real first-frame states rather than defensive padding: the
          // width arrives with layout and the length arrives with the file's
          // header, and neither has happened when this is first drawn.
          if (across.current <= 0 || !known) return;

          const touched = event.nativeEvent.locationX / across.current;
          onSeek(Math.max(0, Math.min(1, touched)) * runs);
        }}
        // The track is four points tall; the target has to be a finger's.
        hitSlop={{ top: 20, bottom: 20, left: 0, right: 0 }}
        style={styles.track}
      >
        <View style={[styles.through, { width: `${through * 100}%` }]} />
      </Pressable>

      <View style={styles.readout}>
        <Text style={styles.figure}>{clock(at)}</Text>
        {/* Absent rather than zero. "4:07 of 0:00" is a room that has already
            finished, said about the one currently making noise. */}
        {known && <Text style={styles.figure}>{clock(runs)}</Text>}
      </View>

      <View style={styles.transport}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back fifteen seconds"
          onPress={() => onSeek(Math.max(0, at - A_SENTENCE_OR_TWO))}
          style={({ pressed }) => [styles.step, pressed && styles.pressed]}
        >
          <Text style={styles.stepLabel}>15s back</Text>
        </Pressable>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel={state === 'playing' ? 'Pause' : 'Play'}
          onPress={state === 'playing' ? onPause : onPlay}
          style={({ pressed }) => [styles.toggle, pressed && styles.pressed]}
        >
          {state === 'playing' ? (
            <View style={styles.pause}>
              <View style={styles.bar} />
              <View style={styles.bar} />
            </View>
          ) : (
            <View style={styles.playOn} />
          )}
        </Pressable>

        {/* The right-hand third of the row, empty, so the toggle sits on the
            centre of the card rather than on the centre of what is left after
            one control. */}
        <View style={styles.step} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  player: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    padding: space.base,
    gap: space.snug,
  },

  refusal: { ...type.bodySm, color: color.danger },

  /**
   * At rest: one control, drawn as a row rather than as a filled button.
   *
   * The primary action on this screen is the coach, and a solid burnt-orange
   * pill here would outrank it. Playing a room back is something you may want;
   * going through it is what the product is for.
   */
  start: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.snug,
    minHeight: 44,
  },
  startLabel: { ...type.labelLg, color: color.primary },
  pressed: { opacity: 0.6 },

  /** A play triangle in borders. Nine points of geometry, as `Replay` argues. */
  play: {
    width: 0,
    height: 0,
    borderTopWidth: 7,
    borderBottomWidth: 7,
    borderLeftWidth: 12,
    borderTopColor: 'transparent',
    borderBottomColor: 'transparent',
    borderLeftColor: color.primary,
  },
  // The triangle's own box, so the label does not shift when one replaces the
  // other.
  spinner: { width: 12, height: 14 },

  track: {
    height: 4,
    borderRadius: 2,
    backgroundColor: color.hairline,
    overflow: 'hidden',
  },
  through: { height: 4, backgroundColor: color.primary },

  readout: { flexDirection: 'row', justifyContent: 'space-between' },
  figure: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    // Proportional digits change width as the number climbs, and a clock that
    // twitches once a second beside a bar that moves smoothly reads as broken.
    fontVariant: ['tabular-nums'],
  },

  transport: { flexDirection: 'row', alignItems: 'center' },

  step: { flex: 1, minHeight: 44, justifyContent: 'center' },
  stepLabel: { ...type.bodySm, color: color.onSurfaceVariant },

  toggle: {
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
  },
  playOn: {
    width: 0,
    height: 0,
    borderTopWidth: 9,
    borderBottomWidth: 9,
    borderLeftWidth: 15,
    borderTopColor: 'transparent',
    borderBottomColor: 'transparent',
    borderLeftColor: color.primary,
    // The glyph's mass sits left of centre once it is a triangle; this puts the
    // shape on the button's centre rather than its bounding box.
    marginLeft: 4,
  },
  pause: { flexDirection: 'row', gap: 5 },
  bar: { width: 5, height: 18, borderRadius: 1, backgroundColor: color.primary },
});
