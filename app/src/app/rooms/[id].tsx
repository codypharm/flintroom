import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { RoomRead } from '../../components/modules/RoomRead';
import { createSessionsApi, type PastRoom, type SaidLine } from '../../lib/api/sessionsApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { SignedOut } from '../../lib/auth/session';
import { whenItRan, whoWasThere } from '../../lib/library/rooms';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * One room, read back.
 *
 * Reached from the Library. On the stack rather than under the tab bar, for the
 * reason every detail screen is: it is a place you go *into* and come back
 * from, and a bar underneath would offer to leave it sideways.
 *
 * Two requests rather than one. The room itself carries when it was and who was
 * in it; the transcript carries what was said, and `CLAUDE.md` keeps a
 * transcript out of any list response — so the Library could not have handed
 * both down. Fetching the room again also means this route survives a deep link
 * or a cold restore, which a screen fed by the previous one does not.
 */

const sessions = createSessionsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export default function RoomRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();

  const [room, setRoom] = useState<PastRoom | null>(null);
  const [lines, setLines] = useState<SaidLine[] | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;

    // Together, because the screen has nothing to draw without both and two
    // spinners resolving at different moments is one screen reflowing twice.
    Promise.all([sessions.list(), sessions.transcript(id)])
      .then(([theirs, said]) => {
        if (!live) return;
        setRoom(theirs.find((one) => one.id === id) ?? null);
        setLines(said);
      })
      .catch((error) => {
        if (!live) return;
        if (error instanceof SignedOut) {
          router.replace('/');
          return;
        }
        setRefused('I could not read that room back. Try again in a moment.');
      });

    return () => {
      live = false;
    };
  }, [id, attempt]);

  if (refused !== null) {
    return (
      <Centred>
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
      </Centred>
    );
  }

  if (lines === null) {
    return (
      <Centred>
        <ActivityIndicator color={color.primary} />
      </Centred>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <RoomRead
        // Null when the room is not in the list — a deep link to somebody
        // else's, or one deleted since. The transcript request would have
        // refused that first, so this is only ever a gap in the heading rather
        // than a screen showing content it should not.
        when={room ? whenItRan(room.startedAt, new Date()) : 'That room'}
        who={room ? whoWasThere(room.archetypes) : ''}
        lines={lines}
        onDebrief={() => router.push(`/debrief/${id}`)}
      />
    </SafeAreaView>
  );
}

function Centred({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
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
