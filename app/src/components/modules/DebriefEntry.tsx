import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { WeakAnswer } from '../../lib/api/debriefApi';
import { panelistName } from '../../lib/panel/vocabulary';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * One question, and everything said about it since.
 *
 * Two slots, and the second one starts empty. **In the room** is fixed — it is
 * what happened, and it does not improve. **Now** grows each time the question
 * is answered again, and it is never marked right: #59 forbids a verdict
 * outright, because telling somebody a thin answer landed sends them into the
 * real room believing it.
 *
 * The empty slot says "you have not answered this one again yet", which is a
 * statement about time rather than about quality. An unticked box, a greyed
 * card, or a progress count would all say the same thing as a score.
 */

export interface Exchange {
  /** What the transcriber made of the clip — the presenter's own words. */
  heard: string;
  /** What the coach said back. What changed, never whether it was enough. */
  said: string;
  /**
   * The same words as audio, base64 — the field the client used to drop.
   *
   * Carried on the exchange rather than played and forgotten, because a reply
   * autoplays once and the room it is about is being read on a phone that may
   * be somewhere sound is not welcome. The caption is always there; this is
   * what makes hearing it again possible without saying anything.
   */
  speech: string;
}

export interface DebriefEntryProps {
  answer: WeakAnswer;
  /** Oldest first, so the entry reads down the way the work happened. */
  attempts: Exchange[];
  /** True while any capture is running anywhere on the screen. */
  busy: boolean;
  /** Stage the question with the capture already running. */
  onAnswerAgain: () => void;
  /** Open the stage quietly — the whole exchange, nothing recording. */
  onOpen: () => void;
}

/**
 * What sits in the "In the room" slot when nothing was said.
 *
 * The distinction is #56's, and it is the one thing on this screen that must
 * not be got wrong. All three of these are silence in the transcript, and only
 * one of them is the presenter's doing — `blame` in
 * `lib/panel/vocabulary.ts` decides which, and nothing here second-guesses it.
 * Telling somebody they ducked a question a panelist took away from them reads
 * as the product not having listened.
 */
export function silence(answer: WeakAnswer): string {
  if (answer.weakness === 'dismissed') return 'A panelist cut across you.';
  if (answer.weakness === 'not_reached') return 'The session ran out before this one.';
  return 'Nothing. It went by.';
}

export function DebriefEntry({
  answer,
  attempts,
  busy,
  onAnswerAgain,
  onOpen,
}: DebriefEntryProps) {
  const asker = panelistName(answer.askedBy);

  return (
    <View style={styles.entry} accessibilityLabel={`Question from ${asker}`}>
      <Text style={styles.asker}>{asker}</Text>
      <Text style={styles.question}>{answer.question}</Text>

      <Text style={styles.slot}>In the room</Text>
      <Text style={answer.answer ? styles.said : styles.nothing}>
        {answer.answer ?? silence(answer)}
      </Text>
      {/*
        Always shown, including where the finding was not the presenter's doing.
        The coach's sentence describes what happened rather than passing
        judgement — "another panelist interrupted before you could answer" is
        the exoneration, not a softened version of an accusation — and
        withholding it on the room's own findings would leave the quietest
        entries with the least explanation.
      */}
      <Text style={styles.why}>{answer.why}</Text>

      {/*
        The half of the finding that faces forward.

        Until 2026-08-20 an entry ended at `why` — the question, what was said,
        what was thin about it, and then a button. It diagnosed and stopped, and
        the architect read six of those in silence and asked for a suggestion.
        A list that only accuses is the version of this screen that produces
        churn rather than resilience, which is Open Risk #1 as a layout.

        Written by the pass that found the weakness rather than fetched on a
        tap: that pass has read the whole transcript already, so this is one
        more field on a reply that was coming anyway, and it is on screen before
        the reader arrives. Asking the coach out loud still goes deeper — this
        is the opening, not the whole of what it can say.

        Absent rather than empty when there is none. The server drops a
        suggestion that named a figure the room never said, and a labelled blank
        would advertise the drop to somebody who has no idea one happened.
      */}
      {answer.nextTime ? (
        <View style={styles.forward}>
          <Text style={styles.slot}>Next time</Text>
          <Text style={styles.said}>{answer.nextTime}</Text>
        </View>
      ) : null}

      <View style={styles.now}>
        <Text style={styles.slot}>Now</Text>
        {attempts.length === 0 ? (
          <Text style={styles.nothing}>You have not answered this one again yet.</Text>
        ) : (
          /*
            The latest version of the words, and only that. The sheet's thesis
            is the answer itself, twice — in the room against now — and the
            back-and-forth that produced the newest one is the stage's content,
            one press away. Piling every try and reply in here made the record
            read as a transcript, and the comparison drowned in it.
          */
          <>
            <Text style={styles.said}>{attempts[attempts.length - 1].heard}</Text>
            <Pressable
              accessibilityRole="button"
              onPress={onOpen}
              style={({ pressed }) => [styles.exchange, pressed && styles.againPressed]}
            >
              <Text style={styles.exchangeLabel}>The whole exchange</Text>
            </Pressable>
          </>
        )}

        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled: busy }}
          disabled={busy}
          onPress={onAnswerAgain}
          style={({ pressed }) => [
            styles.again,
            pressed && styles.againPressed,
            // Dimmed rather than removed. A control that vanishes mid-recording
            // moves the page under somebody who is in the middle of speaking.
            busy && styles.againBusy,
          ]}
        >
          <Text style={styles.againLabel}>Answer it again</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  entry: {
    backgroundColor: color.card,
    borderRadius: radius.container,
    padding: space.loose,
    marginTop: space.base,
  },

  asker: { ...type.labelLg, color: color.primary },
  question: { ...type.bodyLg, color: color.onSurface, marginTop: space.hair },

  /**
   * The two slot names. Set small and quiet, because they are furniture: what
   * the reader is here for is the words underneath them.
   */
  slot: {
    ...type.labelLg,
    color: color.onSurfaceVariant,
    marginTop: space.loose,
  },
  said: { ...type.bodyMd, color: color.onSurface, marginTop: space.hair },
  nothing: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    marginTop: space.hair,
  },
  why: { ...type.bodyMd, color: color.onSurfaceVariant, marginTop: space.snug },

  /**
   * Set apart from `why` but inside the same slot, because it is the other half
   * of one thought rather than a third section. No rule above it — that is what
   * divides "then" from "now", and borrowing it here would read as a third
   * record and flatten the one division that carries meaning.
   */
  forward: { marginTop: space.snug },

  /**
   * The second slot is divided from the first by a rule rather than by a card.
   * Nesting a card inside a card is the lazy container, and these are two parts
   * of one record rather than two records.
   */
  now: {
    marginTop: space.loose,
    paddingTop: space.tight,
    borderTopWidth: 1,
    borderTopColor: color.hairline,
  },
  exchange: {
    minHeight: 44,
    justifyContent: 'center',
    alignSelf: 'flex-start',
  },
  exchangeLabel: { ...type.labelLg, color: color.primary },

  again: {
    minHeight: 44,
    justifyContent: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.primary,
    marginTop: space.base,
  },
  againPressed: { opacity: 0.6 },
  againBusy: { opacity: 0.4 },
  againLabel: { ...type.labelLg, color: color.primary },
});
