import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { color, radius, space, type } from '../../theme/tokens';

/**
 * Tap to start, tap to stop.
 *
 * **Not push-to-talk, and the difference was decided rather than inherited.**
 * `docs/debrief-and-sparring.md` decision 5 argues for turn-based HTTP over a
 * socket, which is a claim about transport: a held socket bills for silence on
 * an unmetered phase. It then glosses that as "the phone is in the user's
 * hand", which `Product.md` §396 does not say — §396 says the screen is *fully
 * attended* in setup, debrief and sparring, and a phone propped against a
 * laptop is fully attended.
 *
 * Sparring is where the difference bites. It is the one place in the product
 * where somebody re-delivers a thirty-second answer they will give standing up,
 * and a thumb pinned to a button is not that rehearsal. Tapping costs nothing
 * and works either way; its worst case is a forgotten recording refused at the
 * server's ceiling, on a phase that charges for nothing.
 *
 * The elapsed count is here for that worst case. A recording with no visible
 * length is one somebody walks away from.
 */

export type Listening =
  | { state: 'idle' }
  | {
      state: 'listening';
      seconds: number;
      /** The rank this clip will be sent against, or null for the coach. */
      at: number | null;
    }
  | { state: 'sending'; at: number | null };

export interface TalkControlProps {
  listening: Listening;
  /** A refusal, said plainly. The screen keeps its findings either way. */
  refusal: string | null;
  /** Who asked the question being answered, when one is. */
  at: string | null;
  /**
   * What the idle button offers. Defaults to the coach, because that is what
   * an untargeted tap reaches; the sparring stage sets it to the question on
   * the table, so the label never promises one listener while the clip goes
   * to another.
   */
  prompt?: string;
  onTalk: () => void;
  onStop: () => void;
}

/** Minutes and seconds, because a bare count of seconds stops reading as time. */
function elapsed(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function TalkControl({ listening, refusal, at, prompt, onTalk, onStop }: TalkControlProps) {
  return (
    <View style={styles.dock}>
      {/*
        The refusal sits with the control rather than in the sheet, because
        every refusal this screen can show is about the last thing said — a
        clip too long, a clip with no speech in it, a server that could not be
        reached. Putting it beside the findings would make it look like one.
      */}
      {refusal && (
        <Text style={styles.refusal} accessibilityRole="alert">
          {refusal}
        </Text>
      )}

      {listening.state === 'listening' && (
        <View style={styles.live}>
          <Text style={styles.elapsed}>{elapsed(listening.seconds)}</Text>
          <Text style={styles.target}>
            {at ? `Answering ${at}` : 'Listening'}
          </Text>
        </View>
      )}

      {listening.state === 'sending' ? (
        <View style={[styles.button, styles.thinking]}>
          <ActivityIndicator color={color.onPrimary} />
          <Text style={styles.buttonLabel}>Thinking</Text>
        </View>
      ) : (
        <Pressable
          accessibilityRole="button"
          onPress={listening.state === 'listening' ? onStop : onTalk}
          style={({ pressed }) => [styles.button, pressed && styles.buttonPressed]}
        >
          <Text style={styles.buttonLabel}>
            {/*
              **Second person, because the first person inverted.** This read
              "Talk to me" — the coach's own voice inviting somebody to speak —
              and the architect read it as the coach about to speak, asking "so
              after clicking talk to me will I be the one to speak?". On the one
              control that opens a microphone, that is the exact ambiguity a
              label exists to close.

              "Talk to the coach" says who acts and who receives, and matches
              "Answer again" on each finding: both are things the user does.
            */}
            {listening.state === 'listening' ? 'Done' : (prompt ?? 'Talk to the coach')}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  /**
   * Docked rather than at the foot of the scroll. The conversation is the point
   * of this screen, and a control that has to be scrolled to is one somebody
   * with six findings never reaches.
   */
  dock: {
    paddingHorizontal: space.screen,
    paddingTop: space.base,
    paddingBottom: space.base,
    borderTopWidth: 1,
    borderTopColor: color.hairline,
    backgroundColor: color.surface,
  },

  refusal: { ...type.bodyMd, color: color.danger, marginBottom: space.snug },

  live: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: space.snug,
    marginBottom: space.snug,
  },
  /**
   * Tabular figures are not available in the loaded family, so the count is set
   * at label size where a shifting digit does not move the line beside it.
   */
  elapsed: { ...type.labelLg, color: color.onSurface },
  target: { ...type.bodySm, color: color.onSurfaceVariant },

  button: {
    minHeight: 44,
    flexDirection: 'row',
    gap: space.snug,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: color.primary,
    borderRadius: radius.pill,
  },
  buttonPressed: { opacity: 0.8 },
  thinking: { opacity: 0.8 },
  buttonLabel: { ...type.labelLg, color: color.onPrimary },
});
