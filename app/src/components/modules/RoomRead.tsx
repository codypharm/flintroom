import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { SaidLine } from '../../lib/api/sessionsApi';
import { panelistName } from '../../lib/panel/vocabulary';
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
 * **Playback is not here, and its absence is deliberate.** #68 is an open
 * architecture decision: the public decode API loads a whole room into memory
 * before making a sound, which is a crash rather than a refusal on any long
 * one. A control that says a room can be heard, next to no way to hear it, is
 * worse than saying nothing — so this says nothing until that lands, and then
 * it belongs directly under the heading.
 */

export interface RoomReadProps {
  /** "Today", "Monday", "4 July" — as the Library says it. */
  when: string;
  /** The panel, named as the rest of the product names them. */
  who: string;
  /** Every line, in the order it happened. Empty is a real room. */
  lines: SaidLine[];
  onDebrief: () => void;
}

export function RoomRead({ when, who, lines, onDebrief }: RoomReadProps) {
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

        {lines.length === 0 ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>Nothing was said in this room</Text>
            <Text style={styles.emptyBody}>
              It ended before the panel got a question out. Nothing was charged
              for it.
            </Text>
          </View>
        ) : (
          lines.map((line) => <Line key={line.ordinal} line={line} opened={opened} />)
        )}

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="What the room found"
          onPress={onDebrief}
          style={({ pressed }) => [styles.through, pressed && styles.pressed]}
        >
          <Text style={styles.throughLabel}>What the room found</Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function Line({ line, opened }: { line: SaidLine; opened: number }) {
  const mine = line.speaker === 'user';

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
        <Text style={styles.at}>{into(line.saidAt, opened)}</Text>
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
 * is a reading aid rather than a seek position; #69 is the offset that would be
 * exact, and it does not exist yet.
 */
function into(saidAt: string, opened: number): string {
  const seconds = Math.max(0, Math.round((new Date(saidAt).getTime() - opened) / 1000));

  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  scroll: { flex: 1 },
  content: { padding: space.screen, paddingBottom: space.major },

  title: { ...type.headlineLg, color: color.onSurface },
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

  through: {
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
