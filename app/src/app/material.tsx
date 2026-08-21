import { Stack, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { YourMaterial } from '../components/modules/YourMaterial';
import { createMaterialsApi, type AttachedMaterial } from '../lib/api/materialsApi';
import { Refused } from '../lib/api/refused';
import { API_BASE_URL, auth } from '../lib/auth';
import { useGateway } from '../lib/auth/gateway';
import { SignedOut } from '../lib/auth/session';
import { color } from '../theme/tokens';

/**
 * What you have attached, and the way to destroy it.
 *
 * Reached from the Material row on Settings, which is where
 * `docs/privacy-policy.md` says this control lives. A pushed screen rather than
 * rows inside Settings: the surface brief for that screen is explicit that it
 * opens with a summary and *"if it starts reading as a dashboard rather than a
 * settings screen, it has failed"* — a list of every deck with a destructive
 * control on each row is a dashboard.
 *
 * Re-read on focus, because a deck can be attached from the setup screen and
 * this is the only place it can be removed.
 */

const materials = createMaterialsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export default function YourMaterialRoute() {
  const { recheck } = useGateway();

  const [mine, setMine] = useState<AttachedMaterial[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);

  const read = useCallback(() => {
    let live = true;

    materials
      .list()
      .then((attached) => {
        if (live) setMine(attached);
      })
      .catch((error) => {
        if (!live) return;
        if (error instanceof SignedOut) {
          recheck();
          return;
        }
        setRefusal('I could not read what you have attached. Try again in a moment.');
        // An empty list rather than a spinner that never stops. The refusal
        // above says why it is empty; a permanent spinner says nothing and
        // cannot be got out of.
        setMine([]);
      });

    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useFocusEffect(read);

  const destroy = async (id: string) => {
    setBusy(id);
    setRefusal(null);

    try {
      await materials.remove(id);
      // Dropped locally rather than re-read. The request succeeded, and a round
      // trip to learn what we already know leaves the row on screen for a beat
      // after somebody confirmed destroying it.
      setMine((held) => (held ?? []).filter((one) => one.id !== id));
    } catch (error) {
      if (error instanceof SignedOut) {
        recheck();
      } else if (error instanceof Refused) {
        // The server diagnosed it — `material_in_use` means a room is still
        // standing on this deck and the recovery is to end that room. Its
        // sentence is better than any this screen could write.
        setRefusal(error.message);
      } else {
        setRefusal('That one is still there. Try again in a moment.');
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <Stack.Screen
        options={{
          headerShown: true,
          headerTitle: '',
          headerBackTitle: 'Settings',
          headerTintColor: color.onSurface,
          headerShadowVisible: false,
          headerStyle: { backgroundColor: color.card },
        }}
      />

      {mine === null ? (
        <View style={styles.centred}>
          <ActivityIndicator color={color.primary} />
        </View>
      ) : (
        <YourMaterial
          mine={mine}
          busy={busy}
          refusal={refusal}
          onDelete={(id) => void destroy(id)}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  centred: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
