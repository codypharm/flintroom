import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Library } from '../../components/modules/Library';
import { createSessionsApi, type PastRoom } from '../../lib/api/sessionsApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { SignedOut } from '../../lib/auth/session';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * Every room already run.
 *
 * This route owns what `Library` deliberately does not: the request, and what
 * "run it again" means. The sheet is handed rooms and callbacks and has no idea
 * a network exists, which is what keeps its product rules — no grade, no
 * counter, no re-run of a room that never seated anybody — testable without a
 * server.
 *
 * **Running a room again is a start, not a resume.** It carries the same
 * seating and the same grounding into a *new* session, because a session is a
 * settled record and re-opening one would rewrite what happened. It is metered,
 * like every live interrogation, and it goes through the same setup route so
 * that the disclosure, the microphone permission and the refusals all apply
 * exactly once rather than in two places.
 */

const sessions = createSessionsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export default function LibraryRoute() {
  const [rooms, setRooms] = useState<PastRoom[] | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;

    sessions
      .list()
      .then((theirs) => {
        if (live) setRooms(theirs);
      })
      .catch((error) => {
        if (!live) return;
        if (error instanceof SignedOut) {
          router.replace('/');
          return;
        }
        // Distinct from an empty library, and the difference matters: one says
        // there is nothing here yet and the other says we could not find out.
        setRefused('I could not reach your rooms. Try that again in a moment.');
      });

    return () => {
      live = false;
    };
  }, [attempt]);

  /**
   * Run this room again — the same panel, the same material, a new session.
   *
   * Through `/setup` rather than starting one here. Everything a room needs
   * before it opens lives on that route: the recording disclosure, the
   * microphone request, and every refusal a start can return. A second path
   * that minted a room directly would be a second place for all three to be
   * forgotten, and the first thing forgotten would be the disclosure.
   */
  const runAgain = useCallback((room: PastRoom) => {
    router.push({
      pathname: '/setup',
      params: {
        archetypes: room.archetypes.join(','),
        // One id, not a list. A room can be grounded in several materials on
        // the server, but the setup screen attaches one at a time and passes
        // one to the room — so carrying more here would promise something the
        // next screen cannot honour.
        material: room.materialIds[0] ?? '',
      },
    });
  }, []);

  if (refused !== null) {
    return (
      <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
        <View style={styles.centred}>
          <Text style={styles.refusalTitle}>That did not load</Text>
          <Text style={styles.refusalBody}>{refused}</Text>
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
        </View>
      </SafeAreaView>
    );
  }

  if (rooms === null) {
    return (
      <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
        <View style={styles.centred}>
          <ActivityIndicator color={color.primary} />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <Library
        rooms={rooms}
        // Read once per render rather than held in state. Nothing here ticks —
        // "Today" does not become "Yesterday" while somebody is looking at it —
        // and a clock in state would redraw the whole list every second to say
        // the same thing.
        now={new Date()}
        onOpen={(id) => router.push(`/debrief/${id}`)}
        onRunAgain={runAgain}
        onStart={() => router.push('/setup')}
      />
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

  refusalTitle: { ...type.headlineSm, color: color.onSurface },
  refusalBody: { ...type.bodyLg, color: color.onSurfaceVariant, textAlign: 'center' },

  retry: {
    marginTop: space.snug,
    paddingVertical: space.snug,
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    backgroundColor: color.primary,
  },
  retryLabel: { ...type.labelLg, color: color.surface },
  pressed: { opacity: 0.6 },
});
