import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { WeakAnswer, WeaknessKind } from '../../lib/api/debriefApi';
import { howOften, KINDS, panelistName } from '../../lib/panel/vocabulary';
import { color, radius, space, type } from '../../theme/tokens';
import { BackTo } from '../ui/BackTo';

/**
 * The last thing somebody reads before the room that matters.
 *
 * THESIS: six weak answers are one habit, not six problems. This sheet opens
 * with the *kind* of trouble the room found and how often, and refuses the
 * ranked list every debrief screen ships — because in the last hour nobody
 * fixes six things, and everybody can hold one instruction.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole and unextended.
 * Warm off-white ground, paper-white cards, burnt orange used once, Hanken
 * Grotesk, 28px containers. No value here that `tokens.ts` does not already
 * carry.
 *
 * STORY: they see what they habitually did under pressure, then the questions
 * inside each habit, then — only when they ask — their own words and what was
 * thin about them. Then they answer it again.
 *
 * FIRST VIEWPORT: the pattern. One line naming the habit and how often, per
 * kind, under two headings that separate what they did from what the room did.
 * The questions sit beneath their kind; nothing is expanded.
 *
 * FORM: candidate 7 of 7 on the grounded list, assigned by seed `8e07280c`
 * (`--scope surface --mode operate`). The list's own top pick was a flashcard
 * deck; the roll exists to refuse that ranking rut.
 *
 * FINISH: unreviewed is unfinished. This build ends with the finish review and
 * the verdict — and *not* with a DESIGN.md, because an extension inside an
 * established world does not rewrite one. The world here is
 * `design-guide/pitchgo_design_system/DESIGN.md`, already brand truth, already
 * pinned by `tokens.test.ts`. Writing a second rulebook for one screen would
 * hand the design-system detector two authorities to disagree with.
 *
 * ---
 *
 * **The spine is fault, and it is the one thing here that must not be
 * rearranged for looks.** The headings say so bluntly — "On you" / "Not on
 * you" — chosen by the architect over two softer pairs, on the ground that this
 * is how a coach actually talks after a hard session (§9: direct and
 * unsentimental, never cruel). The bluntness is the register, not an accident;
 * softening it later is a decision somebody has to take deliberately.
 *
 * The note under the second heading is load-bearing rather than decorative.
 * "Not on you" clears the blame and says nothing about what happens next, and
 * the *only* reason these two findings are on a prep sheet is that the question
 * is still coming.
 * Two of the six weakness kinds are not the presenter's
 * doing — `dismissed` means a panelist cut across them, `not_reached` means the
 * clock ran out. Pooling those with `evasive` would tell somebody they failed
 * six times when they failed four, which is exactly the accusation #56 exists
 * to prevent, arriving through a layout instead of through a sentence.
 */

/**
 * One finding, and the vocabulary it is drawn from.
 *
 * Owned by `debriefApi`, not redeclared here. This screen and the debrief
 * render the same rows from the same response, and two hand-written copies of
 * that shape would be free to disagree — silently, because a structural type
 * matches on fields rather than on identity.
 */
export type { WeakAnswer, WeaknessKind };

export interface PrepSheetProps {
  /** Worst first, as `GET /v1/sessions/{id}/debrief` returns them. */
  answers: WeakAnswer[];
  /** Re-answer the weak answer at this rank. Anchored by rank, per #59. */
  onSpar: (rank: number) => void;
  onShare: () => void;
  /**
   * The way back, drawn at the **foot** rather than the head.
   *
   * The one screen in this app where that is not a whim. This sheet is "a
   * screen you screenshot, not a link you send" — somebody photographs the
   * findings and carries them into a real board meeting — and a chevron in the
   * top-left ends up in that photograph. Below the content it is reachable by
   * thumb and out of frame, which is the only arrangement that serves both.
   *
   * Not left to the edge-swipe gesture, which is what every screen relied on
   * until it was reported missing: a gesture is invisible and unreachable for a
   * screen-reader or switch-control user.
   */
  back: { where: string; onPress: () => void };
}

export function PrepSheet({ answers, onSpar, onShare, back }: PrepSheetProps) {
  if (answers.length === 0) {
    return <CleanRoom back={back} />;
  }

  const yours = grouped(answers, 'them');
  const theirs = grouped(answers, 'room');

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      accessibilityLabel="Your prep sheet"
    >
      <Text style={styles.title}>Before you go in</Text>
      <Text style={styles.standfirst}>
        The room found these. They are the questions you will get again.
      </Text>

      {yours.length > 0 && (
        <Section heading="On you" groups={yours} onSpar={onSpar} answers={answers} />
      )}

      {theirs.length > 0 && (
        <Section
          heading="Not on you"
          note="You will still be asked these."
          groups={theirs}
          onSpar={onSpar}
          answers={answers}
        />
      )}

      <Pressable
        accessibilityRole="button"
        onPress={onShare}
        style={({ pressed }) => [styles.share, pressed && styles.sharePressed]}
      >
        <Text style={styles.shareLabel}>Share this sheet</Text>
      </Pressable>

      {/* Under everything, for the reason `back` gives: a screenshot of this
          sheet should carry the findings and not the furniture. */}
      <View style={styles.out}>
        <BackTo where={back.where} onPress={back.onPress} />
      </View>
    </ScrollView>
  );
}

/**
 * A clean room, stated as the outcome it is.
 *
 * Deliberately not a list-shaped placeholder and deliberately not a zero: both
 * read as a screen that failed rather than as a session that went well.
 */
function CleanRoom({ back }: { back: PrepSheetProps['back'] }) {
  return (
    <View style={[styles.screen, styles.clean]}>
      <Text style={styles.title}>Nothing came loose</Text>
      <Text style={styles.standfirst}>
        The panel pressed and your answers held. Go again when you want a harder
        room.
      </Text>
      {/* Here too. A room with nothing in it is the state somebody is most
          likely to leave immediately, and it had no way out at all. */}
      <View style={styles.out}>
        <BackTo where={back.where} onPress={back.onPress} />
      </View>
    </View>
  );
}

interface Group {
  kind: WeaknessKind;
  items: WeakAnswer[];
}

/**
 * The kinds present, each with its questions, worst first throughout.
 *
 * `answers` arrives ranked and that ranking is a model's judgement made with
 * the whole room in view (#57), so it is preserved twice over: questions keep
 * their order inside a kind, and kinds are ordered by their worst member. A
 * fixed severity table would overrule a reading made after seeing the session
 * with one written before any session existed.
 */
function grouped(answers: WeakAnswer[], blame: 'them' | 'room'): Group[] {
  const kinds: Group[] = [];

  for (const answer of answers) {
    if (KINDS[answer.weakness].blame !== blame) continue;

    const existing = kinds.find((group) => group.kind === answer.weakness);
    if (existing) {
      existing.items.push(answer);
    } else {
      kinds.push({ kind: answer.weakness, items: [answer] });
    }
  }

  return kinds;
}

function Section({
  heading,
  note,
  groups,
  answers,
  onSpar,
}: {
  heading: string;
  note?: string;
  groups: Group[];
  answers: WeakAnswer[];
  onSpar: (rank: number) => void;
}) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionHeading}>{heading}</Text>
      {note && <Text style={styles.sectionNote}>{note}</Text>}

      {groups.map((group) => (
        <View key={group.kind} style={styles.habit}>
          <Text style={styles.habitName}>{KINDS[group.kind].habit}</Text>
          <Text style={styles.habitCount}>{howOften(group.items.length)}</Text>

          {group.items.map((item) => (
            <Question
              key={item.ordinal}
              answer={item}
              onSpar={() => onSpar(answers.indexOf(item))}
            />
          ))}
        </View>
      ))}
    </View>
  );
}

/**
 * One question, closed until asked.
 *
 * Closed is the whole interaction. A question sitting beside the answer that
 * failed it is a document to read; a question sitting alone is a prompt to say
 * something out loud, which is the only thing that rebuilds an answer in the
 * hour before it is needed.
 */
function Question({ answer, onSpar }: { answer: WeakAnswer; onSpar: () => void }) {
  const [open, setOpen] = useState(false);

  return (
    <View style={styles.question}>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityHint={open ? 'Hides what you said' : 'Shows what you said'}
        onPress={() => setOpen((was) => !was)}
        style={styles.questionHit}
      >
        <Text style={styles.asker}>{panelistName(answer.askedBy)}</Text>
        <Text style={styles.questionText}>{answer.question}</Text>
      </Pressable>

      {open && (
        <View style={styles.opened}>
          <Text style={styles.saidLabel}>You said</Text>
          <Text style={styles.said}>
            {answer.answer ?? 'Nothing. The room moved on.'}
          </Text>

          <Text style={styles.why}>{answer.why}</Text>

          {/*
            The sentence worth having in the corridor. A sheet that lists what
            went wrong and stops is a record of a bad afternoon; the reason
            these six are here at all is that the questions are still coming.

            Under `why` and in the reading colour rather than the muted one:
            what was missing is context for it, and this is the part somebody
            re-reads on the way in.
          */}
          {answer.nextTime ? (
            <Text style={styles.reach}>{answer.nextTime}</Text>
          ) : null}

          <Pressable
            accessibilityRole="button"
            onPress={onSpar}
            style={({ pressed }) => [styles.again, pressed && styles.againPressed]}
          >
            <Text style={styles.againLabel}>Answer it again</Text>
          </Pressable>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  /** Below the share control, so a screenshot of the sheet does not carry it. */
  out: { marginTop: space.section, alignItems: 'center' },

  screen: { flex: 1, backgroundColor: color.surface },
  content: { padding: space.screen, paddingBottom: space.major },
  clean: { padding: space.screen, justifyContent: 'center' },

  title: { ...type.headlineLg, color: color.onSurface },
  standfirst: {
    ...type.bodyLg,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
  },

  section: { marginTop: space.major },
  sectionHeading: { ...type.headlineSm, color: color.onSurface },
  sectionNote: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    marginTop: space.hair,
  },

  habit: {
    backgroundColor: color.card,
    borderRadius: radius.container,
    padding: space.loose,
    marginTop: space.base,
  },
  habitName: { ...type.headlineMd, color: color.onSurface },
  /**
   * The count sits under the habit rather than beside it, and reads as a word.
   * A figure to the right of a label is the hero-metric arrangement, which is
   * the scorecard this screen refuses.
   */
  habitCount: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    marginTop: space.hair,
  },

  question: {
    borderTopWidth: 1,
    borderTopColor: color.hairline,
    marginTop: space.base,
    paddingTop: space.base,
  },
  /** 44pt minimum target, per the accessibility floor. */
  questionHit: { minHeight: 44, justifyContent: 'center' },
  asker: { ...type.labelLg, color: color.primary },
  questionText: {
    ...type.bodyLg,
    color: color.onSurface,
    marginTop: space.hair,
  },

  opened: { marginTop: space.base },
  saidLabel: { ...type.labelLg, color: color.onSurfaceVariant },
  said: {
    ...type.bodyMd,
    color: color.onSurface,
    marginTop: space.hair,
  },
  reach: { ...type.bodyMd, color: color.onSurface, marginTop: space.snug },
  why: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
  },

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
  againLabel: { ...type.labelLg, color: color.primary },

  share: {
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: color.primary,
    borderRadius: radius.pill,
    marginTop: space.major,
  },
  sharePressed: { opacity: 0.8 },
  shareLabel: { ...type.labelLg, color: color.onPrimary },
});
