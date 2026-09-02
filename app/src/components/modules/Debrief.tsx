import { MaterialIcons } from '@expo/vector-icons';
import { useState, type ReactNode } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { HeldAnswer, Pressed, Score, WeakAnswer } from '../../lib/api/debriefApi';
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
  /**
   * The answers that held (#118), in the room's own order.
   *
   * The other half of the reading, under the same oath: every one is pinned
   * to a quoted line, so nothing here can be flattery.
   */
  heldAnswers: HeldAnswer[];
  /**
   * (held, judged) counted server-side from verified findings, or null when
   * no score exists — a room read before strengths were judged has none, and
   * null is that fact rather than a zero pretending to be one.
   *
   * A count, not a grade. The decision of 2026-09-01 (#118): testers asked
   * for a rating, and what the product publishes is arithmetic over findings
   * that each quote the transcript — never a model's opinion of the person,
   * and never the difficulty rung, which stays unpublished below.
   */
  score: Score | null;
  /** The last scored room in this room's lineage, or null on a first attempt. */
  previousScore: Score | null;
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
  /** The coach is mid-sentence; every replay control waits its turn. */
  speaking?: boolean;
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

/**
 * The score arc: the ring fills clockwise from twelve, in primary, to the
 * percent it holds. Ruled 2026-09-02 over the static ring — the architect
 * wanted the rating readable from the fill, not only the figure.
 *
 * Plain views, no SVG dependency: a grey track circle under two clipped
 * half-ring layers. A half-ring is a bordered circle with only its top and
 * right sides coloured (a continuous 180 degrees from twelve to six); each
 * layer is rotated into place and a half-width wrapper clips away the part
 * that belongs to the other side. The 45-degree colour boundary at the arc
 * ends is the known artifact of border-drawn arcs, invisible at this stroke.
 */
function ScoreArc({ percent, children }: { percent: number; children: ReactNode }) {
  const sweep = Math.min(100, Math.max(0, percent)) * 3.6;
  const right = Math.min(sweep, 180);
  const left = Math.max(sweep - 180, 0);

  // The half-ring's coloured span runs between the 45-degree border
  // diagonals — from 10:30 to 4:30, not from twelve to six — so every
  // rotation carries a 45-degree correction. Measured on the device: the
  // first cut omitted it and 62% filled barely past a third of the ring,
  // which the architect caught by eye.
  return (
    <View style={styles.arcFrame}>
      <View style={styles.arcTrack} />
      {right > 0 && (
        <View style={styles.arcClipRight} pointerEvents="none">
          <View
            style={[styles.arcHalf, styles.arcInRight, { transform: [{ rotate: `${right - 135}deg` }] }]}
          />
        </View>
      )}
      {left > 0 && (
        <View style={styles.arcClipLeft} pointerEvents="none">
          <View style={[styles.arcHalf, { transform: [{ rotate: `${left + 45}deg` }] }]} />
        </View>
      )}
      {children}
    </View>
  );
}

export function Debrief({
  answers,
  heldAnswers,
  score,
  previousScore,
  pressed,
  opening,
  thread,
  attempts,
  listening,
  refusal,
  onTalk,
  onStop,
  onReplay,
  speaking = false,
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
          speaking={speaking}
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

        {/*
          The score card (#118; composition ruled 2026-09-02, taken from
          `design-guide/coaching_debrief/` at the architect's direction): the
          mockup's centred card with a ring, a verdict line, and assessment
          rows. Its *content* stays retired — no letter grade, no delivery
          read. The ring holds the counted percent, the verdict is the count,
          and the rows are the two facts this screen already carried: the
          last attempt at this argument, and how hard the room pressed.
          Absent entirely when the server sent no score, because a room read
          before scores existed is not a room where nothing held.
        */}
        {score !== null && score.judged > 0 && (
          <View style={styles.scoreCard}>
            <ScoreArc percent={(score.held / score.judged) * 100}>
              <Text style={styles.scoreValue}>
                {`${Math.round((score.held / score.judged) * 100)}%`}
              </Text>
            </ScoreArc>
            <Text style={styles.scoreVerdict}>
              {`${score.held} of ${score.judged} answers held`}
            </Text>

            {((previousScore !== null && previousScore.judged > 0) || moved) && (
              <View style={styles.scoreRows}>
                {previousScore !== null && previousScore.judged > 0 && (
                  <View style={styles.scoreRow}>
                    <MaterialIcons
                      name="history"
                      size={20}
                      color={color.onSurfaceVariant}
                    />
                    <Text style={styles.scoreRowText}>
                      {`Last time on this argument: ${previousScore.held} of ${previousScore.judged} (${Math.round(
                        (previousScore.held / previousScore.judged) * 100
                      )}%).`}
                    </Text>
                  </View>
                )}
                {moved && (
                  <View style={styles.scoreRow}>
                    <MaterialIcons
                      name={pressed === 'harder' ? 'trending-up' : 'trending-down'}
                      size={20}
                      color={color.onSurfaceVariant}
                    />
                    <Text style={styles.scoreRowText}>{moved}</Text>
                  </View>
                )}
              </View>
            )}
          </View>
        )}

        {answers.length === 0 ? (
          <Text style={styles.standfirst}>
            The panel pressed and your answers held. Ask me about any of it.
          </Text>
        ) : (
          <Text style={styles.standfirst}>
            Practice these until they hold. Practice is never scored; a fresh
            room is.
          </Text>
        )}

        {/* Standalone only when there is no card to carry it. */}
        {moved && (score === null || score.judged === 0) && (
          <Text style={styles.moved}>{moved}</Text>
        )}

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
            <Replay disabled={speaking} onReplay={onReplayOpening} />
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

        {/*
          What held, after what came loose. Second on purpose: the work is
          the findings, and the product's premise is the grill — but a sheet
          that only ever lists failure teaches nothing about what to keep
          doing, which is the half the testers asked for. Same card, same
          type, no ticks and no green: an answer that held is stated, not
          celebrated.
        */}
        {heldAnswers.length > 0 && (
          <View style={styles.thread}>
            <Text style={styles.threadHeading}>What held</Text>
            {heldAnswers.map((held) => (
              <View key={held.ordinal} style={styles.turn}>
                <Text style={styles.heard}>{held.question}</Text>
                <Text style={styles.said}>{held.why}</Text>
              </View>
            ))}
          </View>
        )}

        {thread.length > 0 && (
          <View style={styles.thread}>
            <Text style={styles.threadHeading}>What else you asked</Text>
            {thread.map((exchange, index) => (
              <View key={index} style={styles.turn}>
                <Text style={styles.heard}>{exchange.heard}</Text>
                <Text style={styles.said}>{exchange.said}</Text>
                <Replay
                  available={exchange.speech.length > 0}
                  disabled={speaking}
                  onReplay={() => onReplay(exchange.speech)}
                />
              </View>
            ))}
          </View>
        )}

        {/*
          The way out, drawn as a destination rather than a line of label
          text — field-tested 2026-08-27, the bare orange line read as dummy
          text at the foot of the scroll. A card with the app's disclosure
          chevron (the Settings rows' own affordance) says a screen is behind
          it, and the supporting line says which one.
        */}
        <Pressable
          accessibilityRole="link"
          onPress={onPrepSheet}
          style={({ pressed: down }) => [styles.out, down && styles.outPressed]}
        >
          <View style={styles.outWords}>
            <Text style={styles.outLabel}>Your prep sheet</Text>
            <Text style={styles.outDetail}>
              The questions to expect, and the answers that held.
            </Text>
          </View>
          <MaterialIcons name="chevron-right" size={24} color={color.primary} />
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
   * The score card, composed after `design-guide/coaching_debrief/`: centred
   * card, static ring with the value inside, verdict line, assessment rows.
   * The ring is a border, not a progress arc — the mockup's own is static,
   * and an arc would turn a counted fact back into a gauge. Everything on
   * incumbent tokens; the percent takes the page's one accent.
   */
  scoreCard: {
    backgroundColor: color.card,
    borderRadius: radius.container,
    padding: space.loose,
    alignItems: 'center',
    marginTop: space.loose,
  },
  arcFrame: {
    width: 116,
    height: 116,
    alignItems: 'center',
    justifyContent: 'center',
  },
  arcTrack: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    borderRadius: 58,
    borderWidth: 8,
    borderColor: color.surface,
  },
  /** Top and right coloured: a continuous half-ring from twelve to six. */
  arcHalf: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: 116,
    height: 116,
    borderRadius: 58,
    borderWidth: 8,
    borderTopColor: color.primary,
    borderRightColor: color.primary,
    borderBottomColor: 'transparent',
    borderLeftColor: 'transparent',
  },
  arcClipRight: {
    position: 'absolute',
    top: 0,
    right: 0,
    width: 58,
    height: 116,
    overflow: 'hidden',
  },
  arcInRight: { left: -58 },
  arcClipLeft: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: 58,
    height: 116,
    overflow: 'hidden',
  },
  scoreValue: { ...type.headlineLg, color: color.primary },
  scoreVerdict: { ...type.headlineSm, color: color.onSurface, marginTop: space.base },
  scoreRows: { alignSelf: 'stretch', marginTop: space.base, gap: space.snug },
  scoreRow: { flexDirection: 'row', alignItems: 'flex-start', gap: space.snug },
  scoreRowText: { ...type.bodyMd, color: color.onSurfaceVariant, flex: 1 },
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
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: color.card,
    borderRadius: radius.container,
    padding: space.loose,
    marginTop: space.section,
  },
  outPressed: { opacity: 0.6 },
  outWords: { flex: 1 },
  outLabel: { ...type.headlineSm, color: color.primary },
  outDetail: { ...type.bodyMd, color: color.onSurfaceVariant, marginTop: 2 },
});
