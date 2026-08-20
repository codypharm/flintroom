import { Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';

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
  recordsRooms: boolean;
  retentionDays: number;
  minutesRemaining: number;
}

export interface SettingsScreenProps {
  holdings: Holdings;
  onRecordingChange: (records: boolean) => void;
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

function rooms({ rooms, oldestExpiry, recordsRooms, retentionDays }: Holdings): string {
  if (rooms === 0) {
    return recordsRooms
      ? `No rooms saved yet. They are kept for ${retentionDays} days.`
      : 'No rooms saved. New rooms are not being saved.';
  }

  const held = `${rooms} ${rooms === 1 ? 'room' : 'rooms'} saved`;
  const until = oldestExpiry === null ? '' : `, the oldest until ${on(oldestExpiry)}`;

  // Both facts at once when saving is off: the rooms already held stay, because
  // they were made under a disclosure the person accepted. Hiding them would
  // imply the switch had deleted them.
  return recordsRooms
    ? `${held}${until}.`
    : `${held}${until}. New rooms are not being saved.`;
}

export function SettingsScreen({
  holdings,
  onRecordingChange,
  onDeleteAccount,
  onSignOut,
}: SettingsScreenProps) {
  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.title} accessibilityRole="header">
        What we hold
      </Text>

      <View style={styles.group}>
        <View style={styles.row}>
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Rooms</Text>
            <Text style={styles.rowDetail}>{rooms(holdings)}</Text>
          </View>
          {/*
            The control sits on the thing it governs. In a Privacy section this
            would be a switch labelled "Save recordings" with the count
            somewhere else, and the person would have to hold both in their head
            to know what turning it off does.
          */}
          <Switch
            accessibilityLabel="Save rooms"
            value={holdings.recordsRooms}
            onValueChange={onRecordingChange}
            trackColor={{ true: color.primary, false: color.hairline }}
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

        <View style={styles.row}>
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Material</Text>
            <Text style={styles.rowDetail}>
              {holdings.materials === 0
                ? 'Nothing attached yet.'
                : `${holdings.materials} attached. Only the claims and a thumbnail — the file itself is deleted after it is read.`}
            </Text>
          </View>
        </View>
      </View>

      <Text style={styles.title} accessibilityRole="header">
        What you have
      </Text>

      <View style={styles.group}>
        <View style={styles.row}>
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Time under fire</Text>
            {/*
              Plain minutes, framed as what is there rather than what is left.
              §4.6 forbids a depleting counter, and the API deliberately sends
              whole minutes and a boolean so a client cannot round one into
              existence.
            */}
            <Text style={styles.rowDetail}>
              {holdings.minutesRemaining} minutes of interrogation available.
            </Text>
          </View>
        </View>
      </View>

      {/*
        Last, and separated from everything reversible above it. The gap is the
        design doing the work a confirmation dialog cannot: nothing here should
        be reachable by a thumb that meant to hit the switch.
      */}
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
    </ScrollView>
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
