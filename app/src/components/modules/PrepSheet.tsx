import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { color, radius, space, type } from '../../theme/tokens';

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
 * rearranged for looks.** Two of the six weakness kinds are not the presenter's
 * doing — `dismissed` means a panelist cut across them, `not_reached` means the
 * clock ran out. Pooling those with `evasive` would tell somebody they failed
 * six times when they failed four, which is exactly the accusation #56 exists
 * to prevent, arriving through a layout instead of through a sentence.
 */

/** The six readings the debrief can return. `Weakness` in `agents/weakness.py`. */
export type WeaknessKind =
  | 'unanswered'
  | 'dismissed'
  | 'not_reached'
  | 'contradicted'
  | 'unsupported'
  | 'evasive';

export interface WeakAnswer {
  /** Where the question sits in the transcript. What sparring re-asks. */
  ordinal: number;
  question: string;
  /** An archetype key — `cfo`, `technical_skeptic`, `champion`. */
  askedBy: string;
  /** What they said, or null when they said nothing — itself a finding. */
  answer: string | null;
  weakness: WeaknessKind;
  /** The coach's sentence about what was missing. */
  why: string;
}

export interface PrepSheetProps {
  /** Worst first, as `GET /v1/sessions/{id}/debrief` returns them. */
  answers: WeakAnswer[];
  /** Re-answer the weak answer at this rank. Anchored by rank, per #59. */
  onSpar: (rank: number) => void;
  onShare: () => void;
}

/**
 * What each kind reads as when it is a habit rather than a category.
 *
 * Written as something a person did, not as a taxonomy label: "answered a
 * different question" rather than "evasive". A noun invites a score; a verb
 * invites a change.
 *
 * `blame` is the load-bearing field. It decides which heading a kind sits
 * under, and nothing else in this file is allowed to decide that.
 */
const KINDS: Record<WeaknessKind, { habit: string; blame: 'them' | 'room' }> = {
  evasive: { habit: 'Answered a different question', blame: 'them' },
  unsupported: { habit: 'Claimed it without backing it', blame: 'them' },
  contradicted: { habit: 'Gave a figure that fought another one', blame: 'them' },
  unanswered: { habit: 'Let it go by', blame: 'them' },
  dismissed: { habit: 'A panelist cut across you', blame: 'room' },
  not_reached: { habit: 'The session ran out', blame: 'room' },
};

/** Archetype keys are storage; these are what a person is called. */
const PANEL: Record<string, string> = {
  cfo: 'The CFO',
  technical_skeptic: 'The Technical Skeptic',
  champion: 'The Champion',
  growth_maximalist: 'The Growth Maximalist',
  distracted: 'The Distracted Executive',
  internal_blocker: 'The Internal Blocker',
  customer_advocate: 'The Customer Advocate',
  risk_officer: 'The Risk Officer',
};

/**
 * "Twice", not "2".
 *
 * A numeral in a slot built for a number reads as a metric, and a metric on
 * this screen is the delivery-scorer the wedge refuses (`Product.md` §1). Words
 * count without measuring, and stop counting out loud past three because by
 * then the number is not the point.
 */
function howOften(n: number): string {
  return ['', 'once', 'twice', 'three times'][n] ?? 'again and again';
}

export function PrepSheet({ answers, onSpar, onShare }: PrepSheetProps) {
  if (answers.length === 0) {
    return <CleanRoom />;
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
        <Section heading="What you did" groups={yours} onSpar={onSpar} answers={answers} />
      )}

      {theirs.length > 0 && (
        <Section
          heading="What the room did"
          note="Not yours to answer for — but you will still be asked."
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
    </ScrollView>
  );
}

/**
 * A clean room, stated as the outcome it is.
 *
 * Deliberately not a list-shaped placeholder and deliberately not a zero: both
 * read as a screen that failed rather than as a session that went well.
 */
function CleanRoom() {
  return (
    <View style={[styles.screen, styles.clean]}>
      <Text style={styles.title}>Nothing came loose</Text>
      <Text style={styles.standfirst}>
        The panel pressed and your answers held. Go again when you want a harder
        room.
      </Text>
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
        <Text style={styles.asker}>{PANEL[answer.askedBy] ?? answer.askedBy}</Text>
        <Text style={styles.questionText}>{answer.question}</Text>
      </Pressable>

      {open && (
        <View style={styles.opened}>
          <Text style={styles.saidLabel}>You said</Text>
          <Text style={styles.said}>
            {answer.answer ?? 'Nothing — the room moved on.'}
          </Text>

          <Text style={styles.why}>{answer.why}</Text>

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
