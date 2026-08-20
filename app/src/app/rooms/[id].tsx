import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { RoomRead } from '../../components/modules/RoomRead';
import { createSessionsApi, type PastRoom, type SaidLine } from '../../lib/api/sessionsApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { useGateway } from '../../lib/auth/gateway';
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
  const { recheck } = useGateway();
  const { id, from } = useLocalSearchParams<{ id: string; from?: string }>();

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
          // The gate decides where a signed-out person goes, not this screen.
          // `Stack.Protected` moves them the moment the answer changes, and a
          // `router.replace` here would be a second opinion about the same
          // thing — one that used to send them to Home, which is the screen
          // that cannot work without an account.
          recheck();
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
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      {/*
        **The header is the way back, and it is the real one.** Two lists lead
        here — the Library and the run of rooms on Progress — and landing
        somebody on the one they did not come from is worse than no control at
        all, so `from` still names the destination. It goes on
        `headerBackTitle`, which is where iOS draws it, instead of into a
        chevron this screen drew for itself.

        An empty `headerTitle` on purpose. The bar exists for the back button;
        the date below it is this screen's title and always was. That is the
        arrangement `_layout.tsx` was reaching for when it hid every header —
        it just threw out the back button along with the duplicate title.
      */}
      <Stack.Screen
        options={{
          headerShown: true,
          headerTitle: '',
          headerBackTitle: from === 'progress' ? 'Progress' : 'Your rooms',
          headerTintColor: color.onSurface,
          headerShadowVisible: false,
          headerStyle: { backgroundColor: color.surface },
        }}
      />
      <RoomRead
        // Null when the room is not in the list — a deep link to somebody
        // else's, or one deleted since. The transcript request would have
        // refused that first, so this is only ever a gap in the heading rather
        // than a screen showing content it should not.
        when={room ? whenItRan(room.startedAt, new Date()) : 'That room'}
        who={room ? whoWasThere(room.archetypes) : ''}
        lines={lines}
        onDebrief={() => router.push(`/debrief/${id}?from=room`)}
      />
    </SafeAreaView>
  );
}

function Centred({ children }: { children: React.ReactNode }) {
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
