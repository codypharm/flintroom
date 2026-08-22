import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { SaidLine } from '../../lib/api/sessionsApi';
import { panelistName } from '../../lib/panel/vocabulary';
import { clock } from '../../lib/replay/clock';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * One room, read back.
 *
 * THESIS: minutes, not messages. A transcript wants to be a chat — two columns,
 * bubbles, alignment carrying who spoke — and a chat is the wrong reading for
 * this. Somebody comes here to re-read a question that got past them, which
 * means scanning for a speaker and then reading a paragraph, and that is what a
 * script does: the name above the line, quiet and small, and the words at
 * reading size across the full measure.
 *
 * It is also the shape the debrief already refused for the same reason. That
 * sheet's own note records the chat-shaped default as the thing its form exists
 * to avoid.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole.
 *
 * STORY: when it was and who was in it, then the room from the top, then the
 * way through to what it found.
 *
 * FIRST VIEWPORT: the heading and the first exchange — the presenter's opening
 * and the first thing anybody asked about it.
 *
 * ---
 *
 * **Playback arrives as a slot, not as a component this file imports.** #68
 * settled the architecture: streaming a room means the `<Audio>` element from
 * `react-native-audio-api`, reached by a path the package does not publish,
 * because the published one decodes a whole room into memory before making a
 * sound — a crash rather than a refusal on any long one.
 *
 * That module cannot be imported under Jest at all; it throws "the native
 * module could not be found" at load. So a screen that pulled it in
 * transitively would need it mocked in every test it has, over a control none
 * of those tests are about. `player` keeps this file presentational and lets
 * the route compose the thing that makes noise.
 *
 * **Where it goes.** Under the coach and above the transcript. This docstring
 * used to say "directly under the heading", written before the coach moved up;
 * that placement would now put hearing a room again ahead of going through it,
 * and going through it is what the screen is for. Above the lines, though,
 * because on a forty-turn room anything below them is out of reach.
 */

/**
 * The audio of this room, and the one thing that can be done to it.
 *
 * `docs/privacy-policy.md` promises *"delete a room's recording, any room, at
 * any time"*, and until this the control existed nowhere.
 *
 * **Here rather than on the Library row**, and the placement is the design.
 * Deleting a recording is not deleting a room — `DELETE
 * /v1/sessions/{id}/recording` deliberately leaves the transcript, so a
 * "Delete" on a Library row would be followed by that row staying exactly where
 * it was, which reads as a control that failed. On this screen the thing that
 * survives is on the same page as the button.
 *
 * One prop rather than five, because these five facts are one state and a
 * caller that could set them independently could say `deleted` and `held` at
 * once.
 */
export interface RoomAudio {
  /** Whether there is anything to destroy. False once expired or never kept. */
  held: boolean;
  /** True while the request is out. */
  deleting: boolean;
  /** True once this screen destroyed it, which is the only receipt there is. */
  deleted: boolean;
  refusal: string | null;
  onDelete: () => void;
}

export interface RoomReadProps {
  /** "Today", "Monday", "4 July" — as the Library says it. */
  when: string;
  /** The panel, named as the rest of the product names them. */
  who: string;
  /** Every line, in the order it happened. Empty is a real room. */
  lines: SaidLine[];
  onDebrief: () => void;
  /**
   * The transport for hearing this room again, or null when there is nothing
   * to hear — never recorded, expired on the tier window, or just deleted.
   *
   * A node rather than a callback. See the note above: the audio layer is not
   * importable in a test environment, so the boundary has to be something this
   * file never reaches through.
   */
  player?: React.ReactNode;
  /**
   * Jump the recording to a moment, or absent where there is nothing to play.
   *
   * #69 wrote `began_at_seconds` and published it, and until this nothing read
   * it — which left the column half-built, because the ticket's own case for it
   * was that a fifteen-minute file starting at zero is barely worth playing.
   *
   * Passed by the route in exactly the cases it passes a `player`, so the two
   * cannot disagree about whether audio exists. Seconds, not a line — the
   * transport takes a position, and handing it an ordinal would make it look
   * one up.
   */
  onSeek?: (seconds: number) => void;
  /** Null when the room row was not found, which is not the same as nothing. */
  recording?: RoomAudio | null;
}

export function RoomRead({
  when,
  who,
  lines,
  onDebrief,
  player = null,
  onSeek,
  recording = null,
}: RoomReadProps) {
  const opened = lines.length > 0 ? new Date(lines[0].saidAt).getTime() : 0;

  return (
    <View style={styles.screen}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        accessibilityLabel="What was said in this room"
      >
        <Text style={styles.title}>{when}</Text>
        <Text style={styles.who}>{who}</Text>

        {/*
          **Above the transcript, and it used to be under all of it.** Reported
          from a phone. On a forty-turn room the one thing this screen is for
          was forty scrolls away — and somebody opening a past room either wants
          to re-read it or to work on it, of which only the second is worth a
          tap.

          The words changed with the position. "What the room found" is a noun
          phrase for a destination; it does not say that anybody is waiting, and
          since the coach got its voice back that is the whole of what happens
          next. `clarify`'s rule: a label describes what will happen.
        */}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go through it with the coach"
          onPress={onDebrief}
          style={({ pressed }) => [styles.through, pressed && styles.pressed]}
        >
          <Text style={styles.throughLabel}>Go through it with the coach</Text>
        </Pressable>

        {player !== null && <View style={styles.player}>{player}</View>}

        {lines.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>Nothing was said in this room</Text>
            <Text style={styles.emptyBody}>
              It ended before the panel got a question out. Nothing was charged
              for it.
            </Text>
          </View>
        ) : (
          lines.map((line) => (
            <Line key={line.ordinal} line={line} opened={opened} onSeek={onSeek} />
          ))
        )}

        {/*
          Last, and after the whole transcript. The foot is the wrong place for
          a primary action — this screen learned that once and moved the coach
          up — and the right place for a destructive one: nothing here should be
          reachable by a thumb that meant to scroll.
        */}
        {recording === null ? null : <Audio recording={recording} />}
      </ScrollView>
    </View>
  );
}

/**
 * The recording, and the way to destroy it.
 *
 * Confirmed in place rather than in a native alert, as `YourPanelists` and
 * `YourMaterial` both decided: the sentence worth reading is the one about what
 * survives, and an alert body is where that goes to be dismissed unread.
 */
function Audio({ recording }: { recording: RoomAudio }) {
  const [confirming, setConfirming] = useState(false);

  if (recording.deleted) {
    // A destructive control that simply disappears has said nothing — and this
    // one destroys something nobody can check, since playback does not exist
    // yet (#68). The sentence is the only receipt there is.
    return (
      <View style={styles.audio}>
        <Text style={styles.gone}>
          The recording is gone. What was said is still here.
        </Text>
      </View>
    );
  }

  if (!recording.held) {
    return null;
  }

  return (
    <View style={styles.audio}>
      {recording.refusal !== null && (
        <Text style={styles.audioRefusal} accessibilityRole="alert">
          {recording.refusal}
        </Text>
      )}

      {confirming && (
        <Text style={styles.audioWords}>
          What was said stays. Only the audio goes, and it cannot be got back.
        </Text>
      )}

      <View style={styles.audioActions}>
        {confirming && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Keep it"
            onPress={() => setConfirming(false)}
            style={({ pressed }) => [styles.quiet, pressed && styles.pressed]}
          >
            <Text style={styles.quietLabel}>Keep it</Text>
          </Pressable>
        )}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={confirming ? 'Yes, delete it' : 'Delete the recording'}
          accessibilityState={{ disabled: recording.deleting }}
          disabled={recording.deleting}
          onPress={() => {
            if (confirming) {
              setConfirming(false);
              recording.onDelete();
            } else {
              setConfirming(true);
            }
          }}
          style={({ pressed }) => [
            styles.quiet,
            pressed && styles.pressed,
            recording.deleting && styles.dim,
          ]}
        >
          <Text style={styles.destructiveLabel}>
            {confirming ? 'Yes, delete it' : 'Delete the recording'}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

function Line({
  line,
  opened,
  onSeek,
}: {
  line: SaidLine;
  opened: number;
  onSeek?: (seconds: number) => void;
}) {
  const mine = line.speaker === 'user';

  /**
   * Where this line falls, preferring the offset the room actually recorded.
   *
   * `beganAtSeconds` is a position in the mixed file, taken from the room's own
   * clock while it ran. The derived one below is a reading aid computed from
   * when a row was *written*, and it survives only for rooms that ran before
   * #69 — where it is the best thing available and still better than nothing.
   */
  const at = line.beganAtSeconds ?? null;
  const shown = at === null ? into(line.saidAt, opened) : clock(at);

  /**
   * Tappable only where a tap would work.
   *
   * Both conditions are real and neither implies the other: a room with no
   * audio left has no `onSeek`, and a room recorded before #69 has no offset on
   * any line. An affordance on either would be the lie about what a tap does
   * that `AuthorRow` and `DeckAttach` both already refuse.
   */
  const hearable = at !== null && onSeek !== undefined;

  return (
    <View style={styles.line}>
      <View style={styles.attribution}>
        {/*
          "You" rather than the wire's `user`. Nobody re-reading their own
          rehearsal should be labelled with the string the database uses.
        */}
        <Text style={[styles.speaker, mine && styles.me]}>
          {mine ? 'You' : panelistName(line.speaker)}
        </Text>
        {hearable ? (
          <Pressable
            accessibilityRole="button"
            // Names the moment, not the mechanism. "Seek to 15.2" is what the
            // transport does; this is what the person gets.
            accessibilityLabel={`Hear this from ${shown}`}
            onPress={() => onSeek(at)}
            // The timestamp is small type by design — it is the quiet half of
            // the attribution row — so the target comes from slop rather than
            // from padding, which would push the two halves off one baseline.
            hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
            style={({ pressed }) => pressed && styles.pressed}
          >
            <Text style={[styles.at, styles.hearable]}>{shown}</Text>
          </Pressable>
        ) : (
          <Text style={styles.at}>{shown}</Text>
        )}
      </View>
      <Text style={styles.said}>{line.text}</Text>
    </View>
  );
}

/**
 * How far into the room this line fell.
 *
 * An offset rather than a clock time: "9:12" places a line in a day, and what
 * somebody re-reading a rehearsal wants is where it fell in the twelve minutes.
 *
 * Measured from the first line rather than from the session's start, because
 * the start includes provisioning — the seconds before anybody could speak —
 * and a transcript that opens at 0:08 invites a question about the eight
 * seconds that nothing on this screen can answer.
 *
 * Approximate by construction. `said_at` is when a line was *written*, so this
 * is a reading aid rather than a seek position.
 *
 * **A fallback now, not the answer.** #69 records `began_at_seconds` — a true
 * position in the mixed recording — and every room run since has one. This
 * survives for the rooms that ran before it, where it remains the best thing
 * available. Nothing seeks with it.
 */
function into(saidAt: string, opened: number): string {
  const seconds = Math.max(0, Math.round((new Date(saidAt).getTime() - opened) / 1000));

  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

const styles = StyleSheet.create({
  /** Set well below the last line, so a scroll never lands on it. */
  audio: {
    marginTop: space.major,
    paddingTop: space.loose,
    borderTopWidth: 1,
    borderTopColor: color.hairline,
    gap: space.snug,
  },
  audioWords: { ...type.bodySm, color: color.onSurfaceVariant },
  audioRefusal: { ...type.bodySm, color: color.danger },
  audioActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: space.snug },

  /**
   * A timestamp you can press, in the tint the rest of the product uses for
   * exactly that — the same `primary` on `Library`'s "Run it again".
   *
   * Colour is not the only channel: it is also the only element in the
   * attribution row with a touch target, and a screen reader gets the button
   * role and a sentence rather than a bare number.
   */
  hearable: { color: color.primary },
  gone: { ...type.bodySm, color: color.onSurfaceVariant },

  quiet: {
    minHeight: 44,
    justifyContent: 'center',
    paddingHorizontal: space.snug,
    borderRadius: radius.pill,
  },
  quietLabel: { ...type.labelLg, color: color.onSurface },
  destructiveLabel: { ...type.labelLg, color: color.danger },
  dim: { opacity: 0.4 },

  screen: { flex: 1, backgroundColor: color.surface },
  scroll: { flex: 1 },
  content: { padding: space.screen, paddingBottom: space.major },

  title: { ...type.headlineLg, color: color.onSurface, marginTop: space.base },
  who: { ...type.bodyLg, color: color.onSurfaceVariant, marginTop: space.hair },

  /**
   * Generous separation between lines and none inside one. A speaker and their
   * words are one thing; the next speaker is a different one.
   */
  line: { marginTop: space.loose },
  attribution: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  /** Burnt orange, as the panelist's name is on every finding in the debrief. */
  speaker: { ...type.labelLg, color: color.primary },
  /** The presenter is not a panelist, and the colour is what says so. */
  me: { color: color.onSurfaceVariant },
  at: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    fontVariant: ['tabular-nums'],
  },
  said: { ...type.bodyLg, color: color.onSurface, marginTop: space.hair },

  empty: { marginTop: space.section },
  emptyTitle: { ...type.headlineSm, color: color.onSurface },
  emptyBody: {
    ...type.bodyLg,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
  },

  /**
   * Between the coach and the first line.
   *
   * No top margin of its own: the coach button already carries thirty-two
   * points below it, and a second interval added to that is the commonest way
   * a screen ends up with two different gaps that were both meant to be one.
   * The player draws its own card, so this carries spacing and nothing else —
   * a background here would be a card inside a card.
   */
  player: { marginBottom: space.section },

  through: {
    // Was `marginTop: space.section` under the last line. Above the transcript
    // it needs air on both sides — it is the break between what this room WAS
    // and what to do about it.
    marginBottom: space.section,
    alignSelf: 'flex-start',
    marginTop: space.major,
    paddingVertical: space.snug,
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.primary,
  },
  throughLabel: { ...type.labelLg, color: color.primary },
  pressed: { opacity: 0.6 },
});
