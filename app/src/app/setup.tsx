import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PanelSetup, type AttachedMaterial } from '../components/modules/PanelSetup';
import { createPanelsApi, type Catalogue } from '../lib/api/panelsApi';
import { API_BASE_URL, auth } from '../lib/auth';
import { SignedOut } from '../lib/auth/session';
import { color, space, type } from '../theme/tokens';

/**
 * Panel setup, reading the real catalogue.
 *
 * **Not a first-run stub**, unlike `settings.tsx`, and the difference is what
 * this screen is made of. Settings renders facts about an account and can show
 * a plausible empty one; this renders the archetype library, and shipping a
 * hardcoded copy of that is exactly what `/v1/archetypes` exists to prevent —
 * an archetype added on the server would need an app release before anybody
 * could seat it, and the two lists would be free to disagree.
 *
 * So it fetches, and degrades honestly. With no session it says so rather than
 * pretending: sign-in has no screen yet, which is the same wall #41 hits, and
 * this state stops being reachable the moment that lands.
 */

const panels = createPanelsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export default function SetupRoute() {
  const [room, setRoom] = useState<Catalogue | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [seated, setSeated] = useState<string[]>([]);

  // Attachment is #64's remaining half: registering a material and driving the
  // OS file picker is its own piece of work, and the screen already renders
  // every state one produces.
  const [material] = useState<AttachedMaterial | null>(null);

  useEffect(() => {
    let live = true;

    panels
      .catalogue()
      .then((fetched) => live && setRoom(fetched))
      .catch((error) =>
        live &&
        setRefused(
          error instanceof SignedOut
            ? 'Sign in to assemble a room.'
            : 'Could not reach the server. Try again in a moment.'
        )
      );

    return () => {
      live = false;
    };
  }, []);

  const chooseDifficulty = useCallback(
    (level: number) => {
      // Optimistic, then corrected by what the server stored. The control has
      // to move under the thumb — a rung that waited on a round trip would feel
      // broken — and the server is the authority on what it actually is.
      setRoom((current) => (current ? { ...current, difficulty: level } : current));
      panels
        .chooseDifficulty(level)
        .then((stored) =>
          setRoom((current) => (current ? { ...current, difficulty: stored } : current))
        )
        .catch(() => undefined);
    },
    []
  );

  if (refused !== null) {
    return (
      <Ground>
        <Text style={styles.refused}>{refused}</Text>
      </Ground>
    );
  }

  if (room === null) {
    return (
      <Ground>
        <ActivityIndicator color={color.primary} accessibilityLabel="Loading the room" />
      </Ground>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <PanelSetup
        room={room}
        seated={seated}
        onSeatedChange={setSeated}
        material={material}
        onAttach={() => undefined}
        onDifficultyChange={chooseDifficulty}
        onStart={() => undefined}
      />
    </SafeAreaView>
  );
}

function Ground({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      <View style={styles.centred}>{children}</View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },

  centred: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.screen,
  },

  refused: { ...type.bodyMd, color: color.onSurfaceVariant, textAlign: 'center' },
});
