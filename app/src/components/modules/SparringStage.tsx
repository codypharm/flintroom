import { Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { usePreventRemove } from 'expo-router/react-navigation';

import type { WeakAnswer } from '../../lib/api/debriefApi';
import { portraitOf } from '../../lib/archetypes/portraits';
import { panelistName } from '../../lib/panel/vocabulary';
import { color, radius, space, type } from '../../theme/tokens';
import { silence, type Exchange } from './DebriefEntry';
import { Replay } from './Replay';

/**
 * One question on the table, and a discussion with the coach about it.
 *
 * THE CASTING IS THE DESIGN, and the architect confirmed it in those terms
 * before this was built. The panelist's question is the *object*: their face,
 * their words, what was said in the room and what was thin about it — fixed,
 * past tense, never speaking again. The live thread underneath is entirely
 * coach and presenter. Drawn the other way — the CFO asking again, the
 * presenter answering the CFO — this would read as a second interrogation,
 * which is the metered thing sparring deliberately is not.
 *
 * The two layers are told apart the way the debrief already tells them apart:
 * the presenter's words sit in a card, the coach's replies are speech on the
 * page's own ground, exactly as the opening is set on the sheet. No new
 * vocabulary, just the same one staged.
 *
 * FROM THE MOCKUP, AND REFUSED FROM IT. `design-guide/sparring_mode/` supplies
 * the density — one attacker held up with their question, one thing to do —
 * and this takes that whole. Its `04:12` timer does not carry over: a clock on
 * the one deliberately unmetered phase reads as a meter. Neither does its
 * token counter, nor any mark of an attempt being enough — #59 forbids a
 * verdict outright, and the way out of this screen is deciding for yourself
 * that the answer holds.
 */

export interface SparringStageProps {
  answer: WeakAnswer;
  /** Oldest first, the way the work happened. */
  attempts: Exchange[];
  onBack: () => void;
  /** Say one of the coach's replies again. */
  onReplay: (speech: string) => void;
  /** The coach is mid-sentence; replay waits its turn. */
  speaking?: boolean;
}

export function SparringStage({ answer, attempts, onBack, onReplay, speaking = false }: SparringStageProps) {
  const asker = panelistName(answer.askedBy);
  const portrait = portraitOf(answer.askedBy);

  // Back means the findings, not Home — every kind of back. This began as a
  // BackHandler subscription and went back two screens on a real phone: with
  // a native stack the hardware back pops the screen natively, so the handler
  // closed the stage while the navigator left the route in the same press,
  // and the header's own chevron was never intercepted at all. Preventing the
  // *removal* is the one seam all of those pass through. Mounted only while
  // the stage is, so the sheet's back behaviour returns the moment this goes.
  usePreventRemove(true, () => onBack());

  return (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={styles.content}
      accessibilityLabel={`Sparring on the question from ${asker}`}
    >
      <Pressable
        accessibilityRole="button"
        onPress={onBack}
        style={({ pressed }) => [styles.out, pressed && styles.outPressed]}
      >
        <Text style={styles.outLabel}>All findings</Text>
      </Pressable>

      {/*
        The exhibit. Everything in this card already happened, and nothing in
        it will happen again — which is why the portrait belongs here and
        nowhere below: the face marks whose question is on the table, not who
        is talking now.
      */}
      <View style={styles.exhibit}>
        <View style={styles.who}>
          {portrait !== null && (
            <Image source={portrait} style={styles.face} accessibilityIgnoresInvertColors />
          )}
          <Text style={styles.asker}>{asker}</Text>
        </View>
        <Text style={styles.question}>{answer.question}</Text>

        <Text style={styles.slot}>In the room</Text>
        <Text style={answer.answer ? styles.said : styles.nothing}>
          {answer.answer ?? silence(answer)}
        </Text>
        <Text style={styles.why}>{answer.why}</Text>

        {answer.nextTime ? (
          <View style={styles.forward}>
            <Text style={styles.slot}>Next time</Text>
            <Text style={styles.said}>{answer.nextTime}</Text>
          </View>
        ) : null}
      </View>

      {/*
        The discussion, on the ground rather than in the card, because it is
        the part still moving. Presenter turns are cards — their words, kept —
        and the coach is speech on the page, the same casting the sheet gives
        its opening.
      */}
      {attempts.length === 0 ? (
        <Text style={styles.unworked}>You have not answered this one again yet.</Text>
      ) : (
        attempts.map((attempt, index) => (
          <View key={index} style={styles.turn}>
            <View style={styles.yours}>
              <Text style={styles.yourWords}>{attempt.heard}</Text>
            </View>
            <View style={styles.coach}>
              <Text style={styles.coachWords}>{attempt.said}</Text>
              <Replay
                available={attempt.speech.length > 0}
                disabled={speaking}
                onReplay={() => onReplay(attempt.speech)}
              />
            </View>
          </View>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1 },
  content: { padding: space.screen, paddingBottom: space.major },

  out: {
    minHeight: 44,
    justifyContent: 'center',
    alignSelf: 'flex-start',
  },
  outPressed: { opacity: 0.6 },
  outLabel: { ...type.labelLg, color: color.primary },

  exhibit: {
    backgroundColor: color.card,
    borderRadius: radius.container,
    padding: space.loose,
    marginTop: space.snug,
  },
  who: { flexDirection: 'row', alignItems: 'center', gap: space.snug },
  face: { width: 40, height: 40, borderRadius: 20 },
  asker: { ...type.labelLg, color: color.primary },
  question: { ...type.headlineSm, color: color.onSurface, marginTop: space.base },

  slot: {
    ...type.labelLg,
    color: color.onSurfaceVariant,
    marginTop: space.loose,
  },
  said: { ...type.bodyMd, color: color.onSurface, marginTop: space.hair },
  nothing: { ...type.bodyMd, color: color.onSurfaceVariant, marginTop: space.hair },
  why: { ...type.bodyMd, color: color.onSurfaceVariant, marginTop: space.snug },
  forward: { marginTop: space.snug },

  unworked: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    marginTop: space.section,
  },

  turn: { marginTop: space.section },
  /**
   * The presenter's words, indented off the left edge the way a reply is in
   * any conversation — enough to say "the other side of the exchange" without
   * costuming the screen as a messenger.
   */
  yours: {
    backgroundColor: color.card,
    borderRadius: radius.container,
    padding: space.loose,
    marginLeft: space.section,
  },
  yourWords: { ...type.bodyMd, color: color.onSurface },
  coach: { marginTop: space.base, marginRight: space.section },
  coachWords: { ...type.bodyLg, color: color.onSurface },
});
