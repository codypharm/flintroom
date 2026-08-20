import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { MyArchetype } from '../../lib/api/archetypesApi';
import { color, radius, space, type } from '../../theme/tokens';
import { initialsOf } from './ArchetypeCard';

/**
 * The panel somebody wrote, and the only place it can be changed.
 *
 * **It exists because the rail has no gesture left.** Tapping a card there
 * seats that panelist, which is right, so opening one had nowhere to live —
 * `revise` and `retire` had endpoints, service rules and a form route for two
 * commits with nothing able to reach them. This is the door, and `AuthorRow`
 * becomes it once there is anything behind it.
 *
 * **Remove, never delete** (`docs/custom-archetypes.md` §4). The row survives
 * so every past room can still say who was in it — rooms outlive panelists by
 * design — and account deletion is the real delete. A control saying "delete"
 * would be the product claiming something `docs/privacy-policy.md` cannot.
 *
 * Confirmed in place rather than in an alert. The thing worth saying is what
 * removing does *not* do, and a native alert's body is where that sentence goes
 * to be dismissed unread.
 */

export interface YourPanelistsProps {
  mine: MyArchetype[];
  /** The one being removed, or null. Locks its row and nothing else. */
  busy: string | null;
  refusal: string | null;
  onEdit: (name: string) => void;
  onRetire: (name: string) => void;
  onWrite: () => void;
}

export function YourPanelists({
  mine,
  busy,
  refusal,
  onEdit,
  onRetire,
  onWrite,
}: YourPanelistsProps) {
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.title} accessibilityRole="header">
        Your panelists
      </Text>
      {/* Theirs, said from their side. This read "people this product has
          never met, described in your words", which is a fact about our
          library — nobody writes a panelist to fill our gap. See `AuthorRow`,
          where the same line was rewritten for the same reason. */}
      <Text style={styles.standfirst}>
        The people you are actually preparing for. They sit beside ours in any
        room.
      </Text>

      {refusal !== null && (
        <Text style={styles.refusal} accessibilityRole="alert">
          {refusal}
        </Text>
      )}

      {mine.map((one) => (
        <View key={one.name} style={styles.person}>
          <View style={styles.head}>
            {/* The same initials the rail draws, for the same reason: a
                panelist somebody wrote has no portrait, and `initialsOf`
                already knows how to make "The Board Chair" legible at a
                glance. */}
            <View style={styles.face}>
              <Text style={styles.initials}>{initialsOf(one.title)}</Text>
            </View>
            <View style={styles.words}>
              <Text style={styles.name}>{one.title}</Text>
              <Text style={styles.persona} numberOfLines={2}>
                {one.persona}
              </Text>
            </View>
          </View>

          {confirming === one.name ? (
            <View style={styles.confirm}>
              {/* What it does NOT do, said before it is done. Somebody removing
                  a panelist is usually afraid of losing the rooms it was in. */}
              <Text style={styles.confirmWords}>
                They leave your panel. Your rooms with them in are still here.
              </Text>
              <View style={styles.confirmActions}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Keep them"
                  onPress={() => setConfirming(null)}
                  style={({ pressed }) => [styles.quiet, pressed && styles.pressed]}
                >
                  <Text style={styles.quietLabel}>Keep them</Text>
                </Pressable>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Yes, remove them"
                  accessibilityState={{ disabled: busy === one.name }}
                  disabled={busy === one.name}
                  onPress={() => {
                    setConfirming(null);
                    onRetire(one.name);
                  }}
                  style={({ pressed }) => [
                    styles.quiet,
                    pressed && styles.pressed,
                    busy === one.name && styles.dim,
                  ]}
                >
                  <Text style={styles.removeLabel}>Yes, remove them</Text>
                </Pressable>
              </View>
            </View>
          ) : (
            <View style={styles.actions}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Edit ${one.title}`}
                onPress={() => onEdit(one.name)}
                style={({ pressed }) => [styles.quiet, pressed && styles.pressed]}
              >
                <Text style={styles.quietLabel}>Edit</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Remove ${one.title} from your panel`}
                accessibilityState={{ disabled: busy === one.name }}
                disabled={busy === one.name}
                onPress={() => setConfirming(one.name)}
                style={({ pressed }) => [
                  styles.quiet,
                  pressed && styles.pressed,
                  busy === one.name && styles.dim,
                ]}
              >
                <Text style={styles.quietLabel}>Remove</Text>
              </Pressable>
            </View>
          )}
        </View>
      ))}

      {/*
        No empty state, and that is the decision. An account with none of these
        is at a beginning rather than at a failure, and "you have no panelists"
        is a sentence that names an absence somebody already knows about. The
        heading and the standfirst say what these are; the button says what to
        do. Same call `PrepSheet` made about a room that found nothing.
      */}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Write another panelist"
        onPress={onWrite}
        style={({ pressed }) => [styles.write, pressed && styles.pressed]}
      >
        <Text style={styles.writeLabel}>
          {mine.length > 0 ? 'Write another' : 'Write your first'}
        </Text>
      </Pressable>
    </ScrollView>
  );
}

const FACE = 44;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  content: {
    paddingHorizontal: space.screen,
    paddingTop: space.section,
    paddingBottom: space.major,
  },

  title: { ...type.headlineLg, color: color.onSurface },
  standfirst: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    marginTop: space.tight,
    marginBottom: space.loose,
  },

  person: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    padding: space.base,
    marginBottom: space.snug,
  },
  head: { flexDirection: 'row', alignItems: 'center' },
  face: {
    width: FACE,
    height: FACE,
    borderRadius: FACE / 2,
    borderWidth: 1,
    borderColor: color.hairline,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: space.snug,
  },
  initials: { ...type.labelLg, color: color.onSurfaceVariant },
  words: { flex: 1 },
  name: { ...type.headlineSm, color: color.onSurface },
  persona: { ...type.bodySm, color: color.onSurfaceVariant, marginTop: space.hair },

  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: space.snug },
  confirm: { marginTop: space.snug },
  confirmWords: { ...type.bodySm, color: color.onSurfaceVariant },
  confirmActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: space.snug,
  },

  quiet: {
    minHeight: 44,
    justifyContent: 'center',
    paddingHorizontal: space.snug,
  },
  quietLabel: { ...type.labelLg, color: color.onSurfaceVariant },
  removeLabel: { ...type.labelLg, color: color.danger },

  write: {
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: space.base,
    paddingVertical: space.snug,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.onSurface,
  },
  writeLabel: { ...type.labelLg, color: color.onSurface },

  refusal: { ...type.bodyMd, color: color.danger, marginBottom: space.snug },

  pressed: { opacity: 0.6 },
  dim: { opacity: 0.4 },
});
