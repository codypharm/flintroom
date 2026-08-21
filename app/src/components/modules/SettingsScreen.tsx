import { MaterialIcons } from '@expo/vector-icons';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';

import { color, radius, space, type } from '../../theme/tokens';

/**
 * What Flintroom holds, and what you can do about it.
 *
 * The surface brief (`.impeccable/surfaces/app-src-app-settings-tsx.md`) opens
 * with the inventory rather than a list of preference nouns, and puts each
 * control on the thing it governs — the recording switch belongs to the rooms
 * row, not to a Privacy section that happens to contain it.
 *
 * The reason is this product specifically. Flintroom's whole promise is being
 * asked the question you would rather avoid; a settings screen that leads by
 * answering the hardest question about itself is that posture pointed inward.
 * It also turns retention from a sentence in a policy nobody reads into the
 * first thing on the screen, which is what Open Risk #5 actually needs.
 *
 * Structure differs from the platform default; affordances do not. Rows,
 * switches and destructive styling stay standard. If this starts reading as a
 * dashboard rather than a settings screen that opens with a summary, it has
 * failed.
 */

export interface Holdings {
  rooms: number;
  /** When the earliest-expiring room stops being playable. */
  oldestExpiry: Date | null;
  materials: number;
}

/**
 * Whether rooms are being recorded, and for how long they are kept.
 *
 * **Its own value rather than a field on `Holdings`, and #92 is why.** The three
 * reads behind this screen fail independently, and this one is a control while
 * the rest are counts. A 502 on `/v1/materials` used to take the recording
 * switch down with it even though `/v1/preferences/recording` had answered —
 * removing a privacy control `docs/privacy-policy.md` promises by name, over an
 * unrelated request, with its own answer sitting in memory.
 *
 * The precedent is inside `Holdings` already: `minutesRemaining` is nullable
 * separately "because it arrives separately". So is this.
 */
export interface Recording {
  recordsRooms: boolean;
  retentionDays: number;
}

export interface SettingsScreenProps {
  /**
   * What the account actually holds, or null when that is not known.
   *
   * Nullable since #85, and the null is the honest half. Every figure here was
   * a module-level literal until then, so there was no such thing as not
   * knowing yet — the screen stated `0 rooms` and `15 minutes` to everybody.
   * A zero is a claim, and the claim it makes is the reassuring one.
   */
  holdings: Holdings | null;
  /**
   * The recording preference, or null when that read is what failed.
   *
   * Null draws no switch at all. A switch rendered from nothing has to pick a
   * position, and either position is a claim about whether rooms are being
   * recorded — absent is the only honest state.
   */
  recording: Recording | null;
  /**
   * Whole minutes of interrogation available, or null when that is not known.
   *
   * **Its own prop rather than a field on `Holdings`, and it had to become one.**
   * It arrives from a different request — the app bar owns the balance read for
   * all four tabs — so it survives a failure of the counts, and while it lived
   * inside `Holdings` a 502 on `/v1/materials` hid a figure that was visible in
   * the header one row above.
   *
   * That also took away the only route to the buy screen for anybody who is not
   * out of minutes, which is the other half of #92 and was left behind when the
   * recording switch was lifted out.
   *
   * A `0` written into the gap would tell somebody they have run out.
   */
  minutesRemaining?: number | null;
  /** Whether the answer is still in flight, as opposed to having failed. */
  reading?: boolean;
  /** Offered only when the read failed and the route can make another. */
  onRetry?: () => void;
  /**
   * Whether a change to the recording preference is still in flight.
   *
   * The switch disables rather than moving, which the surface brief asks for in
   * as many words: *"controls disable rather than lie; a toggle that appears to
   * have flipped and did not is the worst failure this screen has"*. An
   * optimistic flip is precisely that shape for the length of the request, and
   * on a phone that is not a short window — so the position stays a fact about
   * the account, and the greyed control is the feedback.
   */
  writing?: boolean;
  onRecordingChange: (records: boolean) => void;
  /**
   * Open what is attached, where it can also be destroyed.
   *
   * The row counted material and stopped there, so `docs/privacy-policy.md`
   * described a control — *"Delete attached material. Any time, in Settings"* —
   * that existed nowhere in the app.
   *
   * A pushed list rather than rows here. The surface brief says this screen
   * fails the moment it reads as a dashboard, and a deck-by-deck list with a
   * destructive control on each row is one.
   */
  onOpenMaterial?: () => void;
  /**
   * Open the screen that sells more time, or undefined where it cannot be.
   *
   * Undefined rather than a disabled row, on the same reasoning `onOpenMaterial`
   * uses: a capability that exists elsewhere should not read as a locked door.
   */
  onGetMore?: () => void;
  onDeleteAccount: () => void;
  /**
   * Leave this account on this device.
   *
   * Separate from deleting, and drawn as an ordinary control rather than a
   * destructive one, because it destroys nothing — the rooms, the transcripts
   * and the minutes are all still there on the next sign-in. Putting the two
   * side by side in the same red is how somebody taps the wrong one.
   *
   * It had no control at all until 2026-08-20, which is why a signed-out state
   * was unreachable except by a token expiring on its own.
   */
  onSignOut: () => void;
}

/**
 * "16 September", not "in 12 days".
 *
 * A date is a fact; a countdown is a clock running down on something nobody
 * asked to lose. The window elapsing is the promise being kept, so it gets no
 * urgency at all.
 */
function on(date: Date): string {
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'long' });
}

function rooms(
  { rooms, oldestExpiry }: Holdings,
  recording: Recording | null,
): string {
  // Nothing about saving when the preference is what failed to read. Both
  // "they are kept" and "not being saved" are claims, and #92's whole point is
  // that a failed read must not be answered with a guess.
  if (rooms === 0) {
    if (recording === null) return 'No rooms saved yet.';
    return recording.recordsRooms
      ? `No rooms saved yet. They are kept for ${recording.retentionDays} days.`
      : 'No rooms saved. New rooms are not being saved.';
  }

  const held = `${rooms} ${rooms === 1 ? 'room' : 'rooms'} saved`;
  const until = oldestExpiry === null ? '' : `, the oldest until ${on(oldestExpiry)}`;

  // Both facts at once when saving is off: the rooms already held stay, because
  // they were made under a disclosure the person accepted. Hiding them would
  // imply the switch had deleted them.
  if (recording === null || recording.recordsRooms) return `${held}${until}.`;
  return `${held}${until}. New rooms are not being saved.`;
}

/**
 * The switch that turns saving off, drawn wherever the preference is known.
 *
 * #92: it used to live inside the branch that required all three reads, so a
 * 502 on `/v1/materials` removed a control `docs/privacy-policy.md` promises by
 * name — "Stop rooms being recorded. A switch in Settings." — while its own
 * answer sat in memory.
 *
 * Returns nothing when the preference is unknown. A switch has to pick a
 * position, and either position is a claim about whether rooms are being
 * recorded; absent is the only honest state.
 */
function SaveRooms({
  recording,
  writing,
  onRecordingChange,
}: {
  recording: Recording | null;
  writing: boolean;
  onRecordingChange: (records: boolean) => void;
}) {
  if (recording === null) return null;

  return (
    <Switch
      accessibilityLabel="Save rooms"
      value={recording.recordsRooms}
      disabled={writing}
      onValueChange={onRecordingChange}
      trackColor={{ true: color.primary, false: color.hairline }}
    />
  );
}

export function SettingsScreen({
  holdings,
  recording,
  minutesRemaining = null,
  reading = false,
  onRetry,
  writing = false,
  onRecordingChange,
  onOpenMaterial,
  onGetMore,
  onDeleteAccount,
  onSignOut,
}: SettingsScreenProps) {
  /**
   * Sign-out and deletion below stay reachable whatever the reads did.
   *
   * They need a credential, not an inventory, and an account whose reads are
   * failing is precisely the one somebody wants out of. Putting either behind a
   * successful fetch traps them — and in-app deletion is an App Store
   * requirement rather than a screen detail.
   */
  if (holdings === null) {
    return (
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
        <Text style={styles.title} accessibilityRole="header">
          What we hold
        </Text>

        <View style={styles.group}>
          <View style={styles.row}>
            {reading ? (
              <ActivityIndicator color={color.primary} />
            ) : (
              <View style={styles.rowText}>
                <Text style={styles.rowDetail}>
                  I could not read your account just now.
                </Text>
                {onRetry === undefined ? null : (
                  <Pressable
                    accessibilityRole="button"
                    onPress={onRetry}
                    style={({ pressed }) => [styles.again, pressed && styles.pressed]}
                  >
                    <Text style={styles.againLabel}>Try again</Text>
                  </Pressable>
                )}
              </View>
            )}
          </View>
        </View>

        {/*
          #92. The counts failed; this read did not, and it is a control rather
          than a count. Drawn here so an unrelated 502 on `/v1/materials` cannot
          remove a switch `docs/privacy-policy.md` promises by name — "Stop
          rooms being recorded. A switch in Settings."

          `SaveRooms` draws nothing when the preference is itself what failed,
          so this section is absent rather than guessed at in that case.
        */}
        {recording !== null && (
          <View style={styles.group}>
            <View style={styles.row}>
              <View style={styles.rowText}>
                <Text style={styles.rowTitle}>Rooms</Text>
                <Text style={styles.rowDetail}>
                  {recording.recordsRooms
                    ? `New rooms are saved, and kept for ${recording.retentionDays} days.`
                    : 'New rooms are not being saved.'}
                </Text>
              </View>
              <SaveRooms
                recording={recording}
                writing={writing}
                onRecordingChange={onRecordingChange}
              />
            </View>
          </View>
        )}

        <TimeUnderFire
          minutesRemaining={minutesRemaining}
          reading={reading}
          onGetMore={onGetMore}
        />

        <Leaving onSignOut={onSignOut} onDeleteAccount={onDeleteAccount} />
      </ScrollView>
    );
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.title} accessibilityRole="header">
        What we hold
      </Text>

      <View style={styles.group}>
        <View style={styles.row}>
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Rooms</Text>
            <Text style={styles.rowDetail}>{rooms(holdings, recording)}</Text>
          </View>
          {/*
            The control sits on the thing it governs. In a Privacy section this
            would be a switch labelled "Save recordings" with the count
            somewhere else, and the person would have to hold both in their head
            to know what turning it off does.
          */}
          <SaveRooms
            recording={recording}
            writing={writing}
            onRecordingChange={onRecordingChange}
          />
        </View>

        <View style={styles.hairline} />

        <View style={styles.row}>
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>What was said</Text>
            <Text style={styles.rowDetail}>
              Kept as text for as long as you have an account.
            </Text>
          </View>
        </View>

        <View style={styles.hairline} />

        {/*
          The one row that goes somewhere. A count is an answer to "what do you
          hold"; the policy also promises a way to destroy it, and that needs a
          list. `chevron-right` is the platform's own disclosure mark rather
          than anything of ours — `CLAUDE.md` keeps brand out of controls.
        */}
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Attached material"
          onPress={onOpenMaterial}
          disabled={onOpenMaterial === undefined}
          style={({ pressed }) => [styles.row, pressed && styles.pressed]}
        >
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Material</Text>
            <Text style={styles.rowDetail}>
              {holdings.materials === 0
                ? 'Nothing attached yet.'
                : `${holdings.materials} attached. Only the claims and a thumbnail — the file itself is deleted after it is read.`}
            </Text>
          </View>
          {onOpenMaterial === undefined ? null : (
            <MaterialIcons
              name="chevron-right"
              size={24}
              color={color.onSurfaceVariant}
            />
          )}
        </Pressable>
      </View>

      <TimeUnderFire
        minutesRemaining={minutesRemaining}
        reading={reading}
        onGetMore={onGetMore}
      />

      <Leaving onSignOut={onSignOut} onDeleteAccount={onDeleteAccount} />
    </ScrollView>
  );
}

/**
 * The two ways out, drawn once and rendered under every state of the screen.
 *
 * Last, and separated from everything reversible above it. The gap is the
 * design doing the work a confirmation dialog cannot: nothing here should be
 * reachable by a thumb that meant to hit the switch.
 */
/**
 * What is held, and the way to add to it — drawn wherever the figure is known.
 *
 * **It used to live only in the loaded branch**, which meant a 502 on
 * `/v1/materials` hid a number the app bar was displaying one row above, and
 * took the only route to the buy screen with it. Somebody who is not out of
 * minutes never sees the other entry point (an out-of-minutes refusal), so a
 * failed count left an account with no way to buy anything at all.
 *
 * **An unknown figure is stated, not dropped.** A `0` in that gap would tell
 * somebody they have run out — a claim about their money, and the one that
 * stops them starting a room — but hiding the row takes the way to buy more
 * with it. So the row stays and says it could not read the number.
 *
 * Nothing at all while the answer is still in flight: "could not read" is false
 * of a request that has not finished, and a spinner's worth of pessimism is its
 * own small lie.
 */
function TimeUnderFire({
  minutesRemaining,
  reading,
  onGetMore,
}: {
  minutesRemaining: number | null;
  reading: boolean;
  onGetMore?: () => void;
}) {
  if (reading) return null;

  return (
    <>
      <Text style={styles.title} accessibilityRole="header">
        What you have
      </Text>

      <View style={styles.group}>
        {/*
          The holding and the way to add to it, on one row.

          A row rather than a button beside a number: §4.5 keeps the upsell out
          of the way of a rehearsal, and Settings is where somebody has come to
          look at their account rather than somewhere they were interrupted.
        */}
        <Pressable
          onPress={onGetMore}
          disabled={onGetMore === undefined}
          accessibilityRole={onGetMore === undefined ? undefined : 'button'}
          style={({ pressed }) => [styles.row, pressed && styles.pressed]}
        >
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Time under fire</Text>
            {/*
              Plain minutes, framed as what is there rather than what is left.
              §4.6 forbids a depleting counter, and the API deliberately sends
              whole minutes and a boolean so a client cannot round one into
              existence.
            */}
            <Text style={styles.rowDetail}>
              {minutesRemaining === null
                ? 'I could not read this just now.'
                : `${minutesRemaining} minutes of interrogation available.`}
            </Text>
          </View>
          {onGetMore === undefined ? null : (
            <MaterialIcons
              name="chevron-right"
              size={24}
              color={color.onSurfaceVariant}
            />
          )}
        </Pressable>
      </View>
    </>
  );
}

function Leaving({
  onSignOut,
  onDeleteAccount,
}: Pick<SettingsScreenProps, 'onSignOut' | 'onDeleteAccount'>) {
  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Sign out"
        onPress={onSignOut}
        style={({ pressed }) => [styles.leave, pressed && styles.pressed]}
      >
        <Text style={styles.leaveLabel}>Sign out</Text>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        onPress={onDeleteAccount}
        style={({ pressed }) => [styles.destructive, pressed && styles.pressed]}
      >
        <Text style={styles.destructiveLabel}>Delete account</Text>
      </Pressable>

      <Text style={styles.footnote}>
        Deleting your account removes your rooms, what was said in them, and any
        material you attached.
      </Text>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },

  content: {
    paddingHorizontal: space.screen,
    paddingTop: space.loose,
    paddingBottom: space.major,
  },

  title: {
    ...type.headlineSm,
    color: color.onSurface,
    // More above than below, so a heading belongs to what follows it rather
    // than floating between two groups.
    marginTop: space.section,
    marginBottom: space.snug,
  },

  group: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    paddingHorizontal: space.base,
  },

  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    paddingVertical: space.base,
    minHeight: 44,
  },

  rowText: { flex: 1, gap: space.hair },
  rowTitle: { ...type.labelLg, color: color.onSurface },
  rowDetail: { ...type.bodySm, color: color.onSurfaceVariant },

  hairline: { height: 1, backgroundColor: color.hairline, opacity: 0.5 },

  /** Inside the group rather than centred on the screen: the failure is one
   * row's worth of the account, not the whole destination. */
  again: {
    alignSelf: 'flex-start',
    marginTop: space.snug,
    paddingVertical: space.hair,
    paddingHorizontal: space.snug,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.hairline,
  },
  againLabel: { ...type.labelLg, color: color.onSurface },

  /** An ordinary control. Nothing is destroyed and nothing should look like it. */
  leave: {
    alignSelf: 'flex-start',
    marginTop: space.section,
    paddingVertical: space.snug,
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.hairline,
  },
  leaveLabel: { ...type.labelLg, color: color.onSurface },

  destructive: {
    marginTop: space.major,
    minHeight: 52,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.danger,
  },

  pressed: { opacity: 0.7 },

  destructiveLabel: { ...type.labelLg, fontSize: 16, color: color.danger },

  footnote: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
    textAlign: 'center',
  },
});
