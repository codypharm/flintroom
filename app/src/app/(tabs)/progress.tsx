import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Progress } from '../../components/modules/Progress';
import { createProgressApi, type Progress as Read } from '../../lib/api/progressApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { useGateway } from '../../lib/auth/gateway';
import { SignedOut } from '../../lib/auth/session';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * How you are holding up, room after room.
 *
 * A destination of its own, which is the correction. It was three sentences at
 * the head of the setup screen, and the architect's word for that was accurate:
 * the aim is to track performance *through* the app, and a caption above a
 * panel picker is not a record — it is a footnote to whatever else you came to
 * do.
 *
 * It also has the room it needs now. The run of rooms is the one thing here
 * that cannot be said in a sentence, and it was competing with a form.
 */

const progress = createProgressApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export default function ProgressRoute() {
  const { recheck } = useGateway();
  const [read, setRead] = useState<Read | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  /**
   * Re-read on every visit rather than once on mount.
   *
   * A tab is not unmounted when somebody leaves it, and the single walk that
   * changes everything on this screen is exactly the one that leaves it: build
   * a room, be interrogated, open the debrief, come back. A mount effect would
   * show the run without the room they just ran.
   */
  useFocusEffect(
    useCallback(() => {
      let live = true;

      progress
        .read()
        .then((theirs) => {
          if (live) setRead(theirs);
        })
        .catch((error) => {
          if (!live) return;
          if (error instanceof SignedOut) {
            // The gate decides where a signed-out person goes, not this screen.
          // `Stack.Protected` moves them the moment the answer changes, and a
          // `router.replace` here would be a second opinion about the same
          // thing — one that used to send them to Home, which is the screen
          // that cannot work without an account.
          recheck();
            return;
          }
          // Distinct from having no history, and the difference matters: one
          // says there is nothing to compare yet, the other says we could not
          // find out. Drawing the first for the second would tell somebody with
          // twelve rooms that they have none.
          setRefused('I could not read your rooms back. Try again in a moment.');
        });

      return () => {
        live = false;
      };
    }, [attempt])
  );

  if (refused !== null) {
    return (
      <Centred>
        <Text style={styles.title}>That did not load</Text>
        <Text style={styles.body}>{refused}</Text>
        <Pressable
          accessibilityRole="button"
          onPress={() => {
            setRefused(null);
            setAttempt((made) => made + 1);
          }}
          style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
        >
          <Text style={styles.retryLabel}>Try again</Text>
        </Pressable>
      </Centred>
    );
  }

  if (read === null) {
    return (
      <Centred>
        <ActivityIndicator color={color.primary} />
      </Centred>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={[]}>
      <Progress
        rooms={read.rooms}
        habits={read.habits}
        askers={read.askers}
        // Read at render rather than held in state. Nothing here ticks — a room
        // does not become "yesterday" while somebody is looking at it — and a
        // clock in state would redraw the whole run every second to say the
        // same thing.
        now={new Date()}
        onOpenRoom={(id) => router.push(`/rooms/${id}?from=progress`)}
      />
    </SafeAreaView>
  );
}

function Centred({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.screen} edges={[]}>
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
    padding: space.screen,
    gap: space.snug,
  },

  title: { ...type.headlineSm, color: color.onSurface },
  body: { ...type.bodyLg, color: color.onSurfaceVariant, textAlign: 'center' },

  retry: {
    marginTop: space.snug,
    paddingVertical: space.snug,
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    backgroundColor: color.primary,
  },
  // `onPrimary`, not `surface`. Text on the primary fill has always been
  // `onPrimary`'s job, and reaching for the ground colour only worked while the
  // ground happened to be near-white — which stopped being true when it was
  // darkened to make cards visible.
  retryLabel: { ...type.labelLg, color: color.onPrimary },
  pressed: { opacity: 0.6 },
});
