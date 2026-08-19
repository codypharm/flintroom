import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PastRoom } from '../../lib/api/sessionsApi';
import { howLongItRan, whenItRan, whoWasThere } from '../../lib/library/rooms';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * Every room already run.
 *
 * THESIS: an archive, not a gallery. Two things bring somebody here — reading a
 * room back, and running one again — and both start with *finding the right
 * one*, which on this screen means a date and a panel rather than a picture.
 * So the rooms are entries down a page, separated by hairlines, dense enough
 * that a month of rehearsals is one scroll.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole. Warm off-white
 * ground, burnt orange once, Hanken Grotesk. No value here that `tokens.ts`
 * does not already carry.
 *
 * STORY: when it ran, who was in it, how long it lasted, and whether it can
 * still be heard. Newest first, because the room you want is nearly always the
 * one you just left.
 *
 * FIRST VIEWPORT: the title and three or four rooms, with the most recent
 * carrying everything you need to decide whether to open it or run it again.
 *
 * ---
 *
 * **Cards were the obvious form and are refused.** `design-guide/library/`
 * draws each session as a card with a deck thumbnail, which cannot be built —
 * `docs/ingestion.md` deletes the source document once extraction succeeds, so
 * there is no image to show and a placeholder rectangle would be decoration
 * standing in for content. Identical cards are also the lazy page structure,
 * and what actually distinguishes two rooms is one line of text.
 *
 * **What else that mockup has, and why none of it is here.** It filters by
 * "High Scores (A)", puts an "A-" in a circle on every card, and tags each with
 * "Pacing: Good" and "Clarity: High". `Product.md:392` — *"Delivery-metrics
 * scoring is the commodity layer and is not the product."* There is no field on
 * this screen that could carry a mark, and a test asserts none renders.
 */

export interface LibraryProps {
  /** Newest first, as the server returns them. */
  rooms: PastRoom[];
  /**
   * Injected rather than read from the clock.
   *
   * Half of every row is a statement about the present — "Today", "Monday" —
   * and a screen that consulted a global clock could only be tested by freezing
   * one.
   */
  now: Date;
  onOpen: (roomId: string) => void;
  /** Run this room again, with the panel and the material it had. */
  onRunAgain: (room: PastRoom) => void;
  /** The only thing to do when there is nothing here yet. */
  onStart: () => void;
}

export function Library({ rooms, now, onOpen, onRunAgain, onStart }: LibraryProps) {
  return (
    <View style={styles.screen}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        accessibilityLabel="Every room you have run"
      >
        <Text style={styles.title}>Every room</Text>

        {rooms.length === 0 ? (
          <Empty onStart={onStart} />
        ) : (
          rooms.map((room, index) => (
            <Room
              key={room.id}
              room={room}
              now={now}
              first={index === 0}
              onOpen={onOpen}
              onRunAgain={onRunAgain}
            />
          ))
        )}
      </ScrollView>
    </View>
  );
}

function Room({
  room,
  now,
  first,
  onOpen,
  onRunAgain,
}: {
  room: PastRoom;
  now: Date;
  first: boolean;
  onOpen: (roomId: string) => void;
  onRunAgain: (room: PastRoom) => void;
}) {
  const when = whenItRan(room.startedAt, now);
  const who = whoWasThere(room.archetypes);
  const ran = howLongItRan(room.startedAt, room.settledAt);

  return (
    <View style={[styles.room, first && styles.firstRoom]}>
      <Pressable
        accessibilityRole="button"
        // The date and the panel together, because that is how somebody names
        // the room they are looking for out loud.
        accessibilityLabel={`${when}, ${who}`}
        onPress={() => onOpen(room.id)}
        style={({ pressed }) => [styles.open, pressed && styles.pressed]}
      >
        <View style={styles.headline}>
          <Text style={styles.when}>{when}</Text>
          {/*
            Only when there is one. A room that never settled has no duration,
            and "0:00" would claim it ran for no time rather than that nobody
            measured it.
          */}
          {ran !== null && <Text style={styles.ran}>{ran}</Text>}
        </View>
        <Text style={styles.who}>{who}</Text>
        <Hearing recording={room.recording} />
      </Pressable>

      {/*
        Offered only where there was a panel. A room that failed before seating
        has no archetypes, so running it again would quietly seat the default
        panel instead — a different room wearing the label of the one that
        failed.
      */}
      {room.archetypes.length > 0 && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Run this room again"
          onPress={() => onRunAgain(room)}
          hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
          style={({ pressed }) => [styles.again, pressed && styles.pressed]}
        >
          <Text style={styles.againLabel}>Run it again</Text>
        </Pressable>
      )}
    </View>
  );
}

/**
 * Whether this room can still be heard.
 *
 * Silent when it was never recorded, which is the state saying nothing is
 * correct for: the user turned saving off, they know, and a line reporting the
 * absence of a thing they declined is a screen nagging them about a setting.
 *
 * `expired` says something and `available` says nothing, which is the way round
 * it needs to be — a window closing is news, and a room being playable is what
 * tapping it will show anyway.
 */
function Hearing({ recording }: { recording: PastRoom['recording'] }) {
  if (recording.state !== 'expired') return null;

  return <Text style={styles.gone}>The recording has passed its window</Text>;
}

function Empty({ onStart }: { onStart: () => void }) {
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyTitle}>No rooms yet</Text>
      <Text style={styles.emptyBody}>
        Every room you run is kept here — what was asked, what you said, and the
        recording while its window lasts.
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Start a room"
        onPress={onStart}
        style={({ pressed }) => [styles.start, pressed && styles.pressed]}
      >
        <Text style={styles.startLabel}>Start a room</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  scroll: { flex: 1 },
  content: { padding: space.screen, paddingBottom: space.major },

  title: { ...type.headlineLg, color: color.onSurface },

  /**
   * A hairline above rather than below, so the last room does not sit over a
   * rule with nothing under it — and none above the first, because a line
   * directly beneath a title is a second underline.
   */
  room: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.base,
    paddingVertical: space.loose,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.hairline,
  },
  firstRoom: { borderTopWidth: 0 },

  open: { flex: 1 },
  pressed: { opacity: 0.6 },

  headline: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  when: { ...type.headlineSm, color: color.onSurface },
  /** Tabular, so a column of durations lines up on the colon. */
  ran: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    fontVariant: ['tabular-nums'],
  },

  who: { ...type.bodyMd, color: color.onSurfaceVariant, marginTop: space.hair },
  gone: { ...type.bodySm, color: color.onSurfaceVariant, marginTop: space.tight },

  again: { paddingTop: space.hair },
  againLabel: { ...type.labelLg, color: color.primary },

  empty: { paddingTop: space.section },
  emptyTitle: { ...type.headlineSm, color: color.onSurface },
  emptyBody: {
    ...type.bodyLg,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
  },
  start: {
    alignSelf: 'flex-start',
    marginTop: space.loose,
    paddingVertical: space.snug,
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    backgroundColor: color.primary,
  },
  startLabel: { ...type.labelLg, color: color.surface },
});
