import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { AttachedMaterial } from '../../lib/api/materialsApi';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * Everything this account has attached, and the only place it can be destroyed.
 *
 * `docs/privacy-policy.md` states *"Delete attached material. Any time, in
 * Settings"*, and until this screen that was a claim about a control nobody
 * could reach. The endpoint shipped with #30; what was missing was any way to
 * learn a material id, so the delete was reachable only by a caller still
 * holding the response that registered it. `GET /v1/materials` (#85) is what
 * made this buildable.
 *
 * **Delete, not Remove.** The opposite call to `YourPanelists`, and deliberately
 * so: a retired panelist keeps its row because past rooms have to be able to say
 * who was in them, whereas this destroys the material, its claims and both of
 * its objects. A control that said "Remove" here would understate what happens,
 * and understating a destruction is the one direction this product must not err
 * in.
 *
 * **Nothing is attached from here.** A deck is attached while setting up a room,
 * which is why this screen has an empty state where `YourPanelists` refuses one:
 * that screen carries the control that fills it and this one does not.
 */

export interface YourMaterialProps {
  mine: AttachedMaterial[];
  /** The id being destroyed, or null. Locks its row and nothing else. */
  busy: string | null;
  refusal: string | null;
  onDelete: (id: string) => void;
}

/**
 * The same three sentences the setup screen uses.
 *
 * Copied in wording rather than imported, because `DeckAttach` says them about
 * *the deck you are attaching now* and phrases the failure as an instruction —
 * "attach another, or start without it" — which is advice this screen cannot
 * give. The states are the collapsed three, not the server's five.
 */
function says(state: AttachedMaterial['state']): string {
  if (state === 'extracting') return 'Being read. This takes a moment.';
  if (state === 'failed') return 'Could not be read. Nothing was extracted from it.';
  return 'Read, and ready to be used against you.';
}

export function YourMaterial({ mine, busy, refusal, onDelete }: YourMaterialProps) {
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.title} accessibilityRole="header">
        Attached material
      </Text>
      <Text style={styles.standfirst}>
        Only the claims and a thumbnail are kept. The file itself is deleted
        once it has been read.
      </Text>

      {refusal !== null && (
        <Text style={styles.refusal} accessibilityRole="alert">
          {refusal}
        </Text>
      )}

      {mine.length === 0 ? (
        <Text style={styles.empty}>
          Nothing attached. You attach a deck when you set up a room.
        </Text>
      ) : (
        mine.map((one) => (
          <View key={one.id} style={styles.item}>
            <View style={styles.words}>
              {/* The filename is the whole identity. The source document is
                  deleted once extraction succeeds, so there is nothing else to
                  recognise a deck by — and somebody about to destroy one has to
                  be able to tell which one it is. */}
              <Text style={styles.name} numberOfLines={2}>
                {one.filename}
              </Text>
              <Text style={styles.state}>{says(one.state)}</Text>
            </View>

            {confirming === one.id ? (
              <View style={styles.confirm}>
                {/* What it does NOT do, said before it is done. The fear is
                    losing the rooms, and the real consequence is a different
                    shape: they stay, and running one of them again will no
                    longer be grounded in this. */}
                <Text style={styles.confirmWords}>
                  The rooms it was in are still here. Running one of them again
                  will not be grounded in it.
                </Text>
                <View style={styles.actions}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Keep it"
                    onPress={() => setConfirming(null)}
                    style={({ pressed }) => [styles.quiet, pressed && styles.pressed]}
                  >
                    <Text style={styles.quietLabel}>Keep it</Text>
                  </Pressable>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Yes, delete it"
                    accessibilityState={{ disabled: busy === one.id }}
                    disabled={busy === one.id}
                    onPress={() => {
                      setConfirming(null);
                      onDelete(one.id);
                    }}
                    style={({ pressed }) => [
                      styles.quiet,
                      pressed && styles.pressed,
                      busy === one.id && styles.dim,
                    ]}
                  >
                    <Text style={styles.deleteLabel}>Yes, delete it</Text>
                  </Pressable>
                </View>
              </View>
            ) : (
              <View style={styles.actions}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Delete ${one.filename}`}
                  accessibilityState={{ disabled: busy === one.id }}
                  disabled={busy === one.id}
                  onPress={() => setConfirming(one.id)}
                  style={({ pressed }) => [
                    styles.quiet,
                    pressed && styles.pressed,
                    busy === one.id && styles.dim,
                  ]}
                >
                  <Text style={styles.quietLabel}>Delete</Text>
                </Pressable>
              </View>
            )}
          </View>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  content: {
    paddingHorizontal: space.screen,
    paddingTop: space.loose,
    paddingBottom: space.major,
    gap: space.snug,
  },

  title: { ...type.headlineSm, color: color.onSurface },
  standfirst: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    marginBottom: space.snug,
  },

  refusal: {
    ...type.bodySm,
    color: color.danger,
    marginBottom: space.snug,
  },

  empty: { ...type.bodyLg, color: color.onSurfaceVariant },

  item: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    padding: space.base,
    gap: space.snug,
  },

  words: { gap: space.hair },
  name: { ...type.labelLg, color: color.onSurface },
  state: { ...type.bodySm, color: color.onSurfaceVariant },

  confirm: { gap: space.snug },
  confirmWords: { ...type.bodySm, color: color.onSurfaceVariant },

  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: space.snug },

  quiet: {
    minHeight: 44,
    justifyContent: 'center',
    paddingHorizontal: space.snug,
    borderRadius: radius.pill,
  },
  quietLabel: { ...type.labelLg, color: color.onSurface },
  deleteLabel: { ...type.labelLg, color: color.danger },
  pressed: { opacity: 0.6 },
  dim: { opacity: 0.4 },
});
