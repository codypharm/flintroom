import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { PastRoom } from '../../lib/api/sessionsApi';
import {
  howLongAgo,
  howLongItRan,
  theDateItRan,
  whenItRan,
  whoWasThere,
} from '../../lib/library/rooms';
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
  // Spoken as one string and drawn as two. A screen reader should hear the
  // whole placement in one breath; the eye wants it in registers.
  const when = whenItRan(room.startedAt, now);
  const ago = howLongAgo(room.startedAt, now);
  const date = theDateItRan(room.startedAt, now);
  const who = whoWasThere(room.archetypes);
  const ran = howLongItRan(room.startedAt, room.settledAt);
  const named = room.rehearsalName;

  return (
    <View style={[styles.room, first && styles.firstRoom]}>
      <Pressable
        accessibilityRole="button"
        // The name if there is one, then the date, then the panel — the order
        // somebody says the room they are looking for out loud. The date stays
        // in even when there is a name, because a rehearsal run five times is
        // five rows sharing a headline and when is all that separates them.
        accessibilityLabel={named === null ? `${when}, ${who}` : `${named}, ${when}, ${who}`}
        onPress={() => onOpen(room.id)}
        style={({ pressed }) => [styles.open, pressed && styles.pressed]}
      >
        <View style={styles.headline}>
          {/*
            The name takes the headline when there is one, and the date drops to
            the line below beside the panel. What distinguishes two rooms is one
            line of text — until a rehearsal could be named, the best this screen
            had was a date and a panel, which is how you narrow down a pile
            rather than how you find a thing.
          */}
          {/*
            **`ago` rather than the full placement, and that is a fix.** This is
            20pt in a column it shares with the duration — about 170pt once the
            duration and its margin are out — and it holds one line. It used to
            carry "Monday", which fitted. It now carries what `whenItRan`
            returns, and "3 days ago · 17 August" at this size is 200pt, so an
            unnamed room clipped its own date. The date moves to the meta line
            below, where it has the whole width and is the half you look up
            rather than the half you scan by.
          */}
          <Text style={styles.when} numberOfLines={1}>
            {named ?? ago}
          </Text>
          {/*
            Only when there is one. A room that never settled has no duration,
            and "0:00" would claim it ran for no time rather than that nobody
            measured it.
          */}
          {ran !== null && <Text style={styles.ran}>{ran}</Text>}
        </View>
        {/*
          THREE REGISTERS, NOT TWO SENTENCES JOINED BY MIDDOTS.

          The panel gets its own line because it is the fact that tells two
          rooms apart — the thesis at the top of this file says so — and it was
          sharing one with the date, the relative time and, on a named room, all
          three. Four facts middot-joined at 16pt wrap to three lines and read
          as one long clause about nothing.

          The date sits under it, quiet, with the relative time repeated only
          where the headline could not carry it. An unnamed room reads
          "3 days ago" / panel / "17 August" and says each thing once.
        */}
        {/*
          **One line, cut where the row runs out.**

          Three panelists with the long titles — "The Margin-Obsessed CFO, The
          Growth Maximalist and The Technical Skeptic" — wrap to three lines at
          16pt in a column that shares the row with "Run it again", so a room
          with a full panel stood two and a half times the height of a room with
          one. A list whose rows are different heights depending on how many
          people were in them cannot be scanned, and the thesis at the top of
          this file wants a month of rehearsals in one scroll.

          Cut by width rather than by a character count, which is the same rule
          measured in the unit that actually varies: the cap is where the row
          ends on *this* phone at *this* text size, not a number picked against
          one device.

          **Nothing is lost that a reader needs.** The whole panel is in the
          `accessibilityLabel` on the Pressable above, so VoiceOver hears every
          name; the eye gets the first one and the fact that there are more,
          which is what tells two rooms apart at a glance. The room itself is
          one tap away and names all of them.
        */}
        <Text style={styles.who} numberOfLines={1}>
          {who}
        </Text>
        <Text style={styles.meta}>{named === null ? date : `${ago} · ${date}`}</Text>
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
    /**
     * Centred, not top-aligned.
     *
     * "Run it again" used to sit level with the headline, competing with the
     * one line on the row that identifies the room. It belongs beside the
     * entry, not on top of it.
     */
    alignItems: 'center',
    gap: space.base,
    /**
     * `base`, not `loose`. The entry grew a third register and a taller
     * control; 24 above and below on top of that made a list of four rooms a
     * full screen, against a thesis that wants a month of rehearsals in one
     * scroll. There is a hairline doing the separating as well.
     */
    paddingVertical: space.base,
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
  /**
   * `flexShrink` and one line, because this now holds a name somebody typed.
   * A date is four to twelve characters and a rehearsal's name may be eighty,
   * which without this would push the duration off the row.
   */
  when: { ...type.headlineSm, color: color.onSurface, flexShrink: 1 },
  /** Tabular, so a column of durations lines up on the colon. */
  ran: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    fontVariant: ['tabular-nums'],
    marginLeft: space.base,
  },

  /** The panel, on its own line — the fact that tells two rooms apart. */
  who: { ...type.bodyMd, color: color.onSurface, marginTop: space.hair },
  /** When it ran, quiet, under the thing it dates. */
  meta: { ...type.bodySm, color: color.onSurfaceVariant, marginTop: space.hair },
  gone: { ...type.bodySm, color: color.onSurfaceVariant, marginTop: space.tight },

  /**
   * A bordered control, not a word.
   *
   * **This starts a metered room.** It sat as bare 14pt text immediately beside
   * a tap area covering the rest of the row, with nothing between them but a
   * 16pt gap — two adjacent targets, no boundary, and the expensive one
   * looking like a label. The outline is what makes it read as a thing you
   * press on purpose.
   *
   * 12 + 20 + 12 is 44 exactly, so the visible target meets the floor on its
   * own and the `hitSlop` is margin rather than the whole of it.
   */
  again: {
    paddingVertical: space.snug,
    paddingHorizontal: space.base,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: color.hairline,
  },
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
  // `onPrimary`, not `surface`. Text on the primary fill has always been
  // `onPrimary`'s job, and reaching for the ground colour only worked while the
  // ground happened to be near-white — which stopped being true when it was
  // darkened to make cards visible.
  startLabel: { ...type.labelLg, color: color.onPrimary },
});
