import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { Pressed, WeakAnswer } from '../../lib/api/debriefApi';
import { panelistName } from '../../lib/panel/vocabulary';
import { color, radius, space, type } from '../../theme/tokens';
import { DebriefEntry, type Exchange } from './DebriefEntry';
import { Replay } from './Replay';
import { SparringStage } from './SparringStage';
import { TalkControl, type Listening } from './TalkControl';

/**
 * The room, worked over rather than scored.
 *
 * THESIS: a debrief sheet that fills in as you work it. Every finding has two
 * slots — what the room got, and what you say now — and the second one starts
 * empty. Nothing is ticked, graded, or marked complete. What accumulates is the
 * answer itself, twice, so the change is visible and nobody has to declare it
 * an improvement. That is #59's "no verdict" rendered as structure instead of
 * enforced by a sentence in a prompt.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole. Warm off-white
 * ground, paper-white cards, burnt orange once, Hanken Grotesk, 28px
 * containers. No value here that `tokens.ts` does not already carry.
 *
 * STORY: what came loose, worst first — then, inside each one, the question,
 * their own words, and what was thin about them. Then they say it again, and
 * the entry grows.
 *
 * FIRST VIEWPORT: the title, the one sentence about how this room compared with
 * the last, the first finding, and a control that is always ready to listen.
 *
 * FORM: candidate 6 of 7 on the grounded list, assigned by seed `5ab25451`
 * (`--scope surface --mode operate`). The list's own top pick was a coach
 * thread with findings folded into it — the chat-shaped default this roll
 * exists to refuse.
 *
 * ---
 *
 * **The risk this structure carries, named rather than hidden.** A sheet with
 * blanks can read as a form, and `CLAUDE.md` forbids reducing the coach to a
 * rigid form-filling flow: §3.5 wants follow-ups, clarifications, and a coach
 * that pushes back. The resolution is that **the conversation is free and the
 * sheet is only what it deposits.** Talking is available from the first
 * viewport and is never gated on choosing an entry; a turn that belonged to no
 * question lands at the foot rather than being refused for having no slot.
 *
 * **What the retired mockup for this screen offered and this refuses.**
 * `design-guide/coaching_debrief/` opens with a "B+" and a delivery read —
 * "strong opening hook", "pacing was optimal" — which is the scorer §1 exists
 * to refuse, wearing this product's colours. `design-guide/sparring_mode/`
 * runs a 04:12 timer over the re-try, and a clock on the one phase that is
 * deliberately unmetered reads as a meter. Both were taken for density and
 * neither for content, as `Product.md` §9 instructs.
 */

export interface DebriefProps {
  /** Worst first, as `GET /v1/sessions/{id}/debrief` ranked them. */
  answers: WeakAnswer[];
  pressed: Pressed;
  /**
   * What the coach said on arrival, before anybody said anything.
   *
   * Null on a room whose coaching started at the microphone — greeting into
   * the middle of a conversation would read as not having listened.
   */
  opening: Exchange | null;
  /** Coaching turns that belonged to no single question. */
  thread: Exchange[];
  /** Re-answers, keyed by rank — which is the index in `answers`, per #59. */
  attempts: Record<number, Exchange[]>;
  listening: Listening;
  /**
   * A turn that was refused, said plainly and without taking the sheet away.
   *
   * The route chooses the sentence from the server's code, because the
   * recoveries differ: a clip too long is said again shorter, silence is simply
   * said again, and an unreachable server is neither.
   */
  refusal: string | null;
  /** Start listening. A rank sends the clip to that question; null to the coach. */
  onTalk: (at: number | null) => void;
  onStop: () => void;
  /**
   * Say one of the coach's replies again.
   *
   * Every reply speaks itself once as it arrives. This is the way back to one
   * that was missed — see `Replay`, which carries the reasoning.
   */
  onReplay: (speech: string) => void;
  /**
   * Hear the opening again.
   *
   * Its own callback rather than `onReplay`, because the greeting's audio is
   * usually not in hand: the server speaks it once, for the arrival it belongs
   * to, and a screen that resumed has the words without the voice. The route
   * knows which case it is in; this does not.
   */
  onReplayOpening: () => void;
  /**
   * REMOVED — the stack header on `debrief/[id]` is the way back.
   *
   * It was nullable for a while, on the reasoning that a debrief reached
   * straight out of a live room has nowhere to return to. That stopped being
   * true when the interrogation route began *replacing* itself with this one:
   * the room is off the stack by the time this draws, and back is the Home
   * tab. The route now always shows the bar, and this screen never draws a
   * chevron of its own.
   */
  onPrepSheet: () => void;
}

/**
 * How this room compared with the last, in words or not at all.
 *
 * `docs/difficulty-calibration.md` decision 5. Never the level: a rung rendered
 * here turns the debrief into a score, and a score is the delivery-metrics
 * product §1 refuses. Null is silence rather than "the same" — a dial that
 * announces itself every session is a dial people play instead of a room they
 * rehearse in.
 */
function movement(pressed: Pressed): string | null {
  if (pressed === 'harder') return 'They pressed harder this time than last.';
  if (pressed === 'easier') return 'They went easier on you than last time.';
  return null;
}

export function Debrief({
  answers,
  pressed,
  opening,
  thread,
  attempts,
  listening,
  refusal,
  onTalk,
  onStop,
  onReplay,
  onReplayOpening,
  onPrepSheet,
}: DebriefProps) {
  // One capture at a time. Two would race, and the loser's clip would arrive
  // against whichever request finished last — a re-answer landing on somebody
  // else's question.
  const busy = listening.state !== 'idle';
  const moved = movement(pressed);

  /**
   * The question on the table, by rank, or null while the sheet is up.
   *
   * Component state rather than the route's, because staging changes what is
   * *shown*, never what is known — every word on the stage is already in the
   * props, and a background-and-restore that loses it costs one tap, not a
   * conversation. What must survive restores — the thread, the attempts —
   * already lives above this component.
   */
  const [staged, setStaged] = useState<number | null>(null);
  const tabled = staged !== null ? answers[staged] : undefined;

  return (
    <View style={styles.screen}>
      {tabled !== undefined && staged !== null ? (
        <SparringStage
          answer={tabled}
          attempts={attempts[staged] ?? []}
          onBack={() => setStaged(null)}
          onReplay={onReplay}
        />
      ) : (
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        accessibilityLabel="Your debrief"
      >
        <Text style={styles.title}>
          {answers.length === 0 ? 'Nothing came loose' : 'Where it came loose'}
        </Text>

        {answers.length === 0 ? (
          <Text style={styles.standfirst}>
            The panel pressed and your answers held. Ask me about any of it.
          </Text>
        ) : (
          <Text style={styles.standfirst}>
            Say these again until they hold. Nothing here is being marked.
          </Text>
        )}

        {moved && <Text style={styles.moved}>{moved}</Text>}

        {/*
          The coach, before the list.

          It speaks itself on arrival, which is the whole point: somebody
          walking out of a room is greeted rather than handed a form. This is
          the caption, which `CLAUDE.md` requires alongside the voice rather
          than instead of it.

          Above the findings because it is what orders them — it says where the
          room got past you and which one to start with, and reading that after
          the list would be reading the index after the book.

          There is no grade here and nowhere to put one. The retired mockup for
          this screen opens with a letter in a circle over a delivery read, and
          neither this component nor the field it renders can carry one.
        */}
        {opening && (
          <View style={styles.opening}>
            <Text style={styles.openingSaid}>{opening.said}</Text>
            <Replay onReplay={onReplayOpening} />
          </View>
        )}

        {answers.map((answer, rank) => (
          <DebriefEntry
            key={answer.ordinal}
            answer={answer}
            attempts={attempts[rank] ?? []}
            // Disabled rather than hidden while a capture runs: a control that
            // disappears mid-recording moves everything under the reading
            // position of somebody who is in the middle of talking.
            busy={busy}
            // Staging never records. This started the capture in the same tap,
            // and the architect questioned it: the tap navigates, the eyes need
            // a beat on the question and the suggestion, and a microphone that
            // opens itself on a navigation is the wrong reflex for this app.
            // The docked control on the stage is the one explicit way to speak.
            onAnswerAgain={() => setStaged(rank)}
            onOpen={() => setStaged(rank)}
          />
        ))}

        {thread.length > 0 && (
          <View style={styles.thread}>
            <Text style={styles.threadHeading}>What else you asked</Text>
            {thread.map((exchange, index) => (
              <View key={index} style={styles.turn}>
                <Text style={styles.heard}>{exchange.heard}</Text>
                <Text style={styles.said}>{exchange.said}</Text>
                <Replay
                  available={exchange.speech.length > 0}
                  onReplay={() => onReplay(exchange.speech)}
                />
              </View>
            ))}
          </View>
        )}

        <Pressable
          accessibilityRole="link"
          onPress={onPrepSheet}
          style={({ pressed: down }) => [styles.out, down && styles.outPressed]}
        >
          <Text style={styles.outLabel}>Your prep sheet</Text>
        </Pressable>
      </ScrollView>
      )}

      <TalkControl
        listening={listening}
        refusal={refusal}
        // The question being worked is named on the control itself, so somebody
        // who scrolled away while recording can still see where their words are
        // going.
        at={
          listening.state !== 'idle' && listening.at !== null
            ? panelistName(answers[listening.at]?.askedBy ?? '')
            : null
        }
        prompt={tabled !== undefined ? 'Answer it again' : undefined}
        // Aimed at whatever is on the table; null reaches the coach, and
        // `staged` is null exactly when the sheet is up.
        onTalk={() => onTalk(staged)}
        onStop={onStop}
      />
    </View>
  );
}

/** Re-exported so a route needs one import for the screen and its shapes. */
export type { Exchange, Listening };

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  scroll: { flex: 1 },
  content: { padding: space.screen, paddingBottom: space.major },

  title: { ...type.headlineLg, color: color.onSurface },

  /**
   * The coach's opening, set as speech rather than as a card.
   *
   * No container, no border, no avatar. A card here would make it a summary
   * panel — which is exactly the retired mockup's B+ block wearing different
   * clothes — and this is somebody talking. It reads at body size on the page's
   * own ground, above the first finding, and the only furniture is the control
   * to hear it again.
   */
  opening: { marginTop: space.loose },
  openingSaid: { ...type.bodyLg, color: color.onSurface },
  standfirst: {
    ...type.bodyLg,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
  },
  /**
   * The one sentence about difficulty, set apart from the standfirst and from
   * the findings. It is about the room rather than about any answer, and
   * folding it into either would make it read as a finding of its own.
   */
  moved: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    marginTop: space.base,
    paddingTop: space.base,
    borderTopWidth: 1,
    borderTopColor: color.hairline,
  },

  thread: { marginTop: space.section },
  threadHeading: { ...type.headlineSm, color: color.onSurface },
  turn: {
    backgroundColor: color.card,
    borderRadius: radius.container,
    padding: space.loose,
    marginTop: space.base,
  },
  heard: { ...type.bodyMd, color: color.onSurfaceVariant },
  said: { ...type.bodyLg, color: color.onSurface, marginTop: space.snug },

  out: {
    minHeight: 44,
    justifyContent: 'center',
    alignSelf: 'flex-start',
    marginTop: space.section,
  },
  outPressed: { opacity: 0.6 },
  outLabel: { ...type.labelLg, color: color.primary },
});
