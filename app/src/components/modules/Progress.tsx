import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { WeaknessKind } from '../../lib/api/debriefApi';
import type { RoomHeld, Tally } from '../../lib/api/progressApi';
import { howLongAgo } from '../../lib/library/rooms';
import { atTheSameRung, ladderMoved } from '../../lib/progress/rungs';
import { KINDS, panelistName } from '../../lib/panel/vocabulary';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * How you are holding up, room after room.
 *
 * THESIS: the run, not the last one. This screen was three sentences about the
 * most recent room and the architect's word for it was accurate — the aim is to
 * track performance *through* the app, and a snapshot cannot show somebody they
 * are improving. The endpoint had always returned every room with its own
 * figures and its own rung; only one of them was being drawn.
 *
 * OWN-WORLD: the established Flintroom system, inherited whole.
 *
 * STORY: the shape of the run, then what keeps going wrong, then who keeps
 * causing it, then every room with a way into its transcript.
 *
 * FIRST VIEWPORT: the trend, which is the only thing on this screen that cannot
 * be said in a sentence.
 *
 * ---
 *
 * **The rung is on every room and never in a caption.** Difficulty escalates,
 * so two bars of different heights may be two different rooms rather than two
 * different performances. A note under a chart is read once and then forgotten
 * while the eye keeps comparing heights; a rung named on each row cannot be.
 *
 * **There is no total, no average and no percentage.** A mean across rungs is
 * an average of incomparable rooms, and a single number standing for a run is
 * exactly what somebody would start optimising instead of their argument. That
 * refusal is the reason this is a series rather than a figure — and the series
 * is *more* informative, not less.
 *
 * **The run of rooms, then the run of attempts at one argument.** Two questions
 * are being asked here and only the first had an answer: "am I getting better"
 * is the trend at the top, and "am I getting better at **this**" is the section
 * under it. The second is the one a rehearsal product exists for, and it needs
 * no new arithmetic — the same figures, scoped to a group the presenter defined
 * by tapping "Run it again".
 *
 * **No rehearsal is ever told it is going well.** Nothing computes a direction,
 * a delta or a verdict: the attempts are drawn in order with the rung each was
 * earned at, and what they add up to is the presenter's to read. A screen that
 * announced improvement would be reading a trend out of what is often three
 * points, against a room whose difficulty moved underneath them.
 *
 * **Bars, drawn from Views, of real quantities.** The craft floor's ban is on
 * sparklines and progress rings standing in *for* content; this is the content.
 * `design-guide/home/` had a bar chart too, of "Avg. Likelihood 72%", which is
 * retired both as a metric and as arithmetic.
 */

/** Below this many rooms, a recurrence is a coincidence rather than a habit. */
const A_PATTERN = 2;

/** One room is a point; a line needs two. Also what makes a rehearsal one. */
const A_TREND = 2;

/** How tall the tallest bar stands. Everything else is a share of it. */
const TALLEST = 96;

/**
 * And how tall a rehearsal's own chart stands.
 *
 * **The main trend and a rehearsal's were drawn identically**, at the same
 * height, the same bar width and the same treatment — so a screen with two
 * rehearsals on it was three interchangeable charts and the squint test found
 * no lead at all. They are not equal claims: the top one is the whole run and
 * the others are evidence inside a section, repeated per argument.
 *
 * Subordinated by size rather than by colour or opacity, because size is what
 * the eye sorts first and because the fill already carries the rung — a fourth
 * treatment on the same mark would say nothing new and hide what does.
 */
const SHORTER = 56;

export interface ProgressProps {
  /** Newest first, as the server returns them. */
  rooms: RoomHeld[];
  habits: Tally[];
  askers: Tally[];
  /** Injected, so a screen full of dates can be tested without freezing a clock. */
  now: Date;
  onOpenRoom: (sessionId: string) => void;
}

export function Progress({ rooms, habits, askers, now, onOpenRoom }: ProgressProps) {
  // A room where nobody was asked anything has no proportion. Drawing it as
  // zero would put a trough in the trend describing a technical failure rather
  // than a performance.
  const counted = rooms.filter((room) => room.challenged > 0);

  if (counted.length === 0) {
    return (
      <Empty>
        <Text style={styles.emptyTitle}>Nothing to compare yet</Text>
        <Text style={styles.emptyBody}>
          Every room you run is measured by what the panel put to you and what
          you held. Two rooms is enough to see a direction.
        </Text>
      </Empty>
    );
  }

  const habit = habits.filter((one) => one.rooms >= A_PATTERN);
  const asker = askers.filter((one) => one.rooms >= A_PATTERN);

  // The account's own ladder, read off the rooms that opened a lineage — the
  // only ones that read the account's dial rather than inheriting a rehearsal's.
  // Null unless it has actually moved. See `ladderMoved`.
  const ladder = ladderMoved(counted);

  const rehearsals = rehearsalsIn(counted);

  // Withheld when there is exactly one rehearsal and it is the whole history:
  // that run is already the trend at the top of the screen, and a second copy
  // of it under a heading says nothing the first did not.
  const rehearsed =
    rehearsals.length > 1 || rehearsals[0]?.rooms.length !== counted.length
      ? rehearsals
      : [];

  return (
    <View style={styles.screen}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        accessibilityLabel="How you are holding up"
      >
        <Text style={styles.title}>How you are holding up</Text>

        {counted.length < A_TREND ? (
          <Text style={styles.thin}>
            One room so far. Run another and this becomes a direction rather
            than a dot.
          </Text>
        ) : (
          <Trend rooms={counted} onOpenRoom={onOpenRoom} label="Every room, oldest first" />
        )}

        {/*
          THE LADDER, AND IT IS A SENTENCE RATHER THAN A SECOND CHART.

          This screen puts the trend at the top because it "is the only thing on
          this screen that cannot be said in a sentence". The ladder can be, and
          a second chart beside the first would take the same glance while
          carrying two numbers.

          Directly under the trend because it is the caption that chart has been
          missing: the bars carry the rung in their fill precisely so nobody
          compares two heights without seeing they were different rooms, and
          this says what those different rooms add up to.

          **It describes the room. It never grades the presenter.** The rung
          moved because `calibration.py` read a room, so a climb IS the product
          saying somebody handled the last one — but saying it back as praise
          would be the single number this screen exists without, and it would be
          a verdict on a person rather than a fact about a room. Somebody who
          reads the credit into it has read it correctly; nothing here reads it
          for them.
        */}
        {ladder !== null && (
          <View style={styles.ladder}>
            <Text style={styles.moved}>
              {`Your first room was ${rung(ladder.first)}. The room you get now is ${rung(ladder.now)}.`}
            </Text>
            {/*
              Said once, and needed: without it a presenter cannot tell whether
              this was done to them, chosen by them, or earned — and the answer
              is the third, which is the only one that is not obvious.
            */}
            <Text style={styles.why}>
              The panel presses harder or eases off on its own, from how the last
              room went.
            </Text>
          </View>
        )}

        {rehearsed.length > 0 && (
          <Section heading="What you keep rehearsing">
            {rehearsed.map((run, at) => {
              // The oldest room in the run, which is where it started. Read
              // from the tail because the rooms arrive newest first.
              const oldest = run.rooms[run.rooms.length - 1];

              // The name if the presenter gave the rehearsal one, and when it
              // began if they did not. Nothing is derived from the panel or
              // the deck: a heading somebody never chose is one they have no
              // way to correct, and a date at least says only what is true.
              const called = oldest.rehearsalName ?? `Started ${howLongAgo(oldest.startedAt, now)}`;

              return (
                /*
                  A run is the largest content unit on this screen — a label, a
                  chart and its comparisons — and consecutive runs used to be
                  separated by nothing but the hairline on the next one's row.
                  Sections got 32 and the things inside them got 0, which is
                  the rhythm exactly inverted.
                */
                <View key={run.id} style={at > 0 && styles.nextRun}>
                  {/*
                    A LABEL FOR THE CHART BELOW IT, not a row in a list. It was
                    `Row`, which carries a top hairline and list padding, so a
                    rehearsal's name read as an item among the tallies further
                    down rather than as the heading of the thing under it.
                  */}
                  <View style={styles.runHead}>
                    <Text style={styles.runName} numberOfLines={1}>
                      {called}
                    </Text>
                    <Text style={styles.runCount}>{inRooms(run.rooms.length)}</Text>
                  </View>
                  <Trend
                    rooms={run.rooms}
                    onOpenRoom={onOpenRoom}
                    lesser
                    // Named after the run itself, which is what makes the two
                    // charts on this screen tellable apart by a screen reader.
                    label={
                      oldest.rehearsalName === null
                        ? `One argument, oldest first, started ${howLongAgo(oldest.startedAt, now)}`
                        : `${oldest.rehearsalName}, oldest first`
                    }
                  />

                  {/*
                    The one comparison this screen makes, and it is a statement
                    rather than a reading. Two attempts at the *same* rung hold
                    the confounder constant — the ladder only makes comparisons
                    across different rungs dishonest — so the tallies are put
                    side by side and nothing subtracts them.

                    Silent unless a rehearsal actually ran twice at one rung,
                    which is the common case early on and the point at which
                    there is genuinely nothing to say.
                  */}
                  {atTheSameRung(run.rooms).map((held) => (
                    <Text key={held.level} style={styles.against}>
                      {`${rung(held.level)}: ${held.attempts
                        .map((attempt) => `${attempt.held} of ${attempt.challenged}`)
                        .join(', then ')}`}
                    </Text>
                  ))}
                </View>
              );
            })}
          </Section>
        )}

        {habit.length > 0 && (
          <Section heading="Where it keeps going wrong">
            {habit.map((one) => (
              <Row key={one.name} left={habitOf(one.name)} right={inRooms(one.rooms)} />
            ))}
          </Section>
        )}

        {asker.length > 0 && (
          <Section heading="Who keeps getting past you">
            {asker.map((one) => (
              <Row
                key={one.name}
                left={panelistName(one.name)}
                right={inRooms(one.rooms)}
              />
            ))}
          </Section>
        )}

        <Section heading="Room by room">
          {counted.map((room) => (
            <Pressable
              key={room.sessionId}
              accessibilityRole="button"
              accessibilityLabel={`${howLongAgo(room.startedAt, now)}, ${room.held} held of ${room.challenged}`}
              onPress={() => onOpenRoom(room.sessionId)}
              style={({ pressed }) => [styles.room, pressed && styles.pressed]}
            >
              <Text style={styles.when}>{howLongAgo(room.startedAt, now)}</Text>
              <Text style={styles.tally}>
                {room.held} of {room.challenged}
              </Text>
              <Text style={styles.rung}>{rung(room.level)}</Text>
            </Pressable>
          ))}
        </Section>
      </ScrollView>
    </View>
  );
}

/**
 * The run, oldest on the left.
 *
 * Reversed from the server's order, which is newest-first — right for a list
 * somebody is scanning, wrong for a trend. A chart running backwards would show
 * an improving presenter getting worse, which is the exact failure every other
 * decision on this screen is arranged against.
 *
 * Horizontally scrollable, because a run of rooms has no upper bound and
 * squeezing forty into a phone's width makes each one unreadable and untappable.
 */
function Trend({
  rooms,
  onOpenRoom,
  label,
  lesser = false,
}: {
  rooms: RoomHeld[];
  onOpenRoom: (sessionId: string) => void;
  /**
   * Required rather than defaulted, because this is drawn more than once — the
   * whole history, then each rehearsal — and two charts answering to the same
   * name is a screen reader announcing the wrong one.
   */
  label: string;
  /** A rehearsal's own run, drawn as evidence under a heading rather than as
   *  the screen's lead. Height and bar width only — the rung's fill is
   *  untouched, because it means the same thing in both. */
  lesser?: boolean;
}) {
  const oldestFirst = [...rooms].reverse();
  const tallest = lesser ? SHORTER : TALLEST;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.trend}
      accessibilityLabel={label}
    >
      {oldestFirst.map((room) => {
        const share = room.held / room.challenged;

        return (
          <Pressable
            key={room.sessionId}
            accessibilityRole="button"
            accessibilityLabel={`${room.held} held of ${room.challenged}, ${rung(room.level)}`}
            onPress={() => onOpenRoom(room.sessionId)}
            style={({ pressed }) => [styles.column, pressed && styles.pressed]}
          >
            <View style={[styles.track, lesser && { height: SHORTER }]}>
              {/*
                The bar carries the rung in its fill, not only in the label
                beneath it: a harder room is drawn solid and a gentler one
                outlined, so the eye cannot compare two heights without also
                seeing that they were different rooms.
              */}
              <View
                style={[
                  styles.bar,
                  lesser && styles.barLesser,
                  { height: Math.max(2, share * tallest) },
                  room.level === 3 && styles.hardest,
                  room.level === 1 && styles.gentlest,
                ]}
              />
            </View>
            <Text style={styles.held}>{room.held}</Text>
            <Text style={styles.of}>of {room.challenged}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

/**
 * The rooms, gathered into the arguments they are attempts at.
 *
 * Grouped on `rehearsalId`, which the server answers on every room — its own id
 * unless it repeats another — so there is no null case and no chain to walk.
 *
 * Insertion order is kept and the rooms arrive newest first, so a rehearsal
 * somebody returned to yesterday sits above one they last ran in June.
 *
 * A run of one is dropped. One attempt is a room somebody ran, not a thing they
 * are working on, and a heading for each would spread the screen across every
 * room in the account and bury the two that matter.
 */
function rehearsalsIn(rooms: RoomHeld[]): { id: string; rooms: RoomHeld[] }[] {
  const runs = new Map<string, RoomHeld[]>();

  for (const room of rooms) {
    const run = runs.get(room.rehearsalId);
    if (run === undefined) {
      runs.set(room.rehearsalId, [room]);
    } else {
      run.push(room);
    }
  }

  return [...runs.entries()]
    .map(([id, its]) => ({ id, rooms: its }))
    .filter((run) => run.rooms.length >= A_TREND);
}

function Section({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.heading} accessibilityRole="header">
        {heading}
      </Text>
      {children}
    </View>
  );
}

function Row({ left, right }: { left: string; right: string }) {
  return (
    <View style={styles.line}>
      <Text style={styles.left}>{left}</Text>
      <Text style={styles.right}>{right}</Text>
    </View>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <View style={styles.screen}>
      <View style={styles.empty}>{children}</View>
    </View>
  );
}

/**
 * The rung, named rather than numbered.
 *
 * "Relentless" is a fact about the room somebody sat in. A 3 is a score, and a
 * score is what this screen exists without.
 */
function rung(level: number | null): string {
  if (level === 1) return 'Gentle';
  if (level === 2) return 'Standard';
  if (level === 3) return 'Relentless';
  return 'Unrecorded';
}

/**
 * What the habit is called, through the table the debrief and prep sheet read.
 *
 * `KINDS` writes each as a verb — "Let it go by", not "unanswered" — because a
 * noun invites a score and a verb invites a change.
 */
function habitOf(kind: string): string {
  return KINDS[kind as WeaknessKind]?.habit ?? kind;
}

/** Small counts in words: "four rooms" is a sentence, "4" is a metric. */
function inRooms(count: number): string {
  const said =
    ['no', 'one', 'two', 'three', 'four', 'five', 'six'][count] ?? String(count);

  return count === 1 ? 'one room' : `${said} rooms`;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  scroll: { flex: 1 },
  content: { padding: space.screen, paddingBottom: space.major },

  /**
   * The title states the interval below it, once, for both branches.
   *
   * It used to state none: the chart declared `paddingTop: loose` and the
   * one-room sentence declared `marginTop: base`, so the gap under the title
   * was 24 or 16 depending on how many rooms somebody had run.
   */
  title: { ...type.headlineLg, color: color.onSurface, marginBottom: space.snug },
  thin: { ...type.bodyLg, color: color.onSurfaceVariant },

  /**
   * The ladder's two ends, tight under the chart they explain.
   *
   * `space.base` rather than a section's `space.section`: this belongs to the
   * trend above it, and putting a section's worth of air between them would
   * make it a separate claim about nothing in particular.
   */
  ladder: { marginTop: space.base, gap: space.hair },
  moved: { ...type.bodyLg, color: color.onSurface },
  why: { ...type.bodySm, color: color.onSurfaceVariant },

  /**
   * No gap between columns, and that is the chart's main readability fix.
   *
   * A 22pt bar inside a 44pt column already carries 11pt of air either side;
   * the 12pt gap on top of that made the pitch 56 for a 22pt mark, so the
   * bars read as scattered dots rather than as a series, and only six fitted
   * on a phone. Adjacent columns give a 44pt pitch and eight bars, which is
   * what makes a run look like one.
   *
   * The 44pt column stays — it is the touch target, and every bar opens its
   * room.
   */
  trend: { paddingTop: space.snug, paddingBottom: space.tight },
  column: { alignItems: 'center', width: 44 },
  /** A fixed track, so every bar is measured from the same baseline. */
  track: { height: TALLEST, justifyContent: 'flex-end' },
  bar: {
    width: 26,
    borderRadius: radius.control,
    backgroundColor: color.primary,
    opacity: 0.55,
  },
  /** Narrower on a rehearsal's own chart, with its height. */
  barLesser: { width: 16 },

  /** Solid for the hardest rung, outlined for the gentlest. */
  hardest: { opacity: 1 },
  gentlest: {
    opacity: 1,
    backgroundColor: color.surface,
    borderWidth: 2,
    borderColor: color.primary,
  },
  held: {
    ...type.labelLg,
    color: color.onSurface,
    marginTop: space.tight,
    fontVariant: ['tabular-nums'],
  },
  of: { ...type.bodySm, color: color.onSurfaceVariant, fontVariant: ['tabular-nums'] },

  /**
   * Quiet, and below the bars rather than beside them. It is a footnote to the
   * run — the same numbers the chart already draws, put in an order somebody
   * can read aloud — and typographic weight here would make it the verdict this
   * screen refuses to give.
   */
  against: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    fontVariant: ['tabular-nums'],
    marginTop: space.snug,
  },

  section: { marginTop: space.section },
  /**
   * `snug` rather than `tight`: every row below a heading draws a top hairline,
   * and at 8pt that rule sat close enough to read as an underline on the
   * heading rather than as the separator between two rows.
   */
  heading: { ...type.headlineSm, color: color.onSurface, marginBottom: space.snug },

  /** One rehearsal from the next. See the comment at the call site. */
  nextRun: { marginTop: space.loose },
  runHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: space.base,
  },
  runName: { ...type.labelLg, color: color.onSurface, flexShrink: 1 },
  runCount: { ...type.bodySm, color: color.onSurfaceVariant },

  line: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    paddingVertical: space.snug,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.hairline,
  },
  left: { ...type.bodyLg, color: color.onSurface, flexShrink: 1 },
  right: { ...type.bodyMd, color: color.onSurfaceVariant, marginLeft: space.base },

  room: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: space.base,
    paddingVertical: space.snug,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: color.hairline,
  },
  when: { ...type.bodyLg, color: color.onSurface, flex: 1 },
  tally: {
    ...type.bodyLg,
    color: color.onSurface,
    fontVariant: ['tabular-nums'],
  },
  rung: { ...type.bodySm, color: color.onSurfaceVariant, width: 88, textAlign: 'right' },

  pressed: { opacity: 0.6 },

  empty: { flex: 1, justifyContent: 'center', padding: space.screen },
  emptyTitle: { ...type.headlineSm, color: color.onSurface },
  emptyBody: {
    ...type.bodyLg,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
  },
});
