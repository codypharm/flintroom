import { Stack, router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { YourPanelists } from '../../components/modules/YourPanelists';
import { createArchetypesApi, type MyArchetype } from '../../lib/api/archetypesApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { useGateway } from '../../lib/auth/gateway';
import { SignedOut } from '../../lib/auth/session';
import { color } from '../../theme/tokens';

/**
 * The panel somebody wrote.
 *
 * Reached from `AuthorRow` once there is anything behind it, because the setup
 * rail has no gesture left: tapping a card there seats that panelist.
 *
 * Re-read on focus, since editing pushes to `[name]` and comes back — a mount
 * effect would show the row exactly as it was before the edit.
 */

const archetypes = createArchetypesApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export default function YourPanelistsRoute() {
  const { recheck } = useGateway();

  const [mine, setMine] = useState<MyArchetype[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);

  const read = useCallback(() => {
    let live = true;

    archetypes
      .mine()
      .then((written) => {
        if (live) setMine(written);
      })
      .catch((error) => {
        if (!live) return;
        if (error instanceof SignedOut) {
          recheck();
          return;
        }
        setRefusal('We could not read your panel. Try again in a moment.');
        setMine([]);
      });

    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useFocusEffect(read);

  const retire = async (name: string) => {
    setBusy(name);
    setRefusal(null);

    try {
      await archetypes.retire(name);
      // Dropped locally rather than re-read. The request succeeded, and a round
      // trip to learn what we already know would leave the row on screen for a
      // beat after somebody confirmed removing it.
      setMine((held) => (held ?? []).filter((one) => one.name !== name));
    } catch (error) {
      if (error instanceof SignedOut) {
        recheck();
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
          headerBackTitle: 'Your room',
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
        <YourPanelists
          mine={mine}
          busy={busy}
          refusal={refusal}
          onEdit={(name) => router.push(`/panelists/${encodeURIComponent(name)}`)}
          onRetire={(name) => void retire(name)}
          onWrite={() => router.push('/panelists/new')}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  centred: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
