import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrepSheet } from '../../components/modules/PrepSheet';
import { createDebriefApi, type WeakAnswer } from '../../lib/api/debriefApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { SignedOut } from '../../lib/auth/session';
import { refusedRoom, type RoomRefusal } from '../../lib/debrief/refusals';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * The prep sheet for one room, read from that room.
 *
 * **It used to render a sample.** A fixed set of four findings from
 * `scripts/weakness.py`, with a docstring explaining that the debrief endpoint
 * "needs a bearer token the app cannot obtain, because sign-in has no screen".
 * That was true when it was written and stopped being true when sign-in landed
 * — so the honest position had quietly become a stale one, and the screen was
 * showing everybody the same imaginary room.
 *
 * It also took no session id, which is the other half of the same problem:
 * there was no route from a *particular* debrief to that debrief's sheet.
 *
 * Reads the same idempotent call the debrief screen does. The list was computed
 * and stored the first time anybody opened the room, so this costs a query
 * rather than a second reasoning-model call — and it cannot disagree with what
 * the debrief showed, which matters when somebody is holding one to check the
 * other.
 */

const debriefs = createDebriefApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export default function PrepSheetRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();

  const [answers, setAnswers] = useState<WeakAnswer[] | null>(null);
  const [refused, setRefused] = useState<RoomRefusal | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;

    debriefs
      .read(id)
      .then((debrief) => {
        if (live) setAnswers(debrief.weakAnswers);
      })
      .catch((error) => {
        if (!live) return;
        if (error instanceof SignedOut) {
          router.replace('/');
          return;
        }
        // The debrief's own refusal vocabulary, reused rather than re-worded.
        // A room that broke, or one the panel never spoke in, means the same
        // thing here as it does there — and two screens inventing separate
        // sentences for one server code is how they come to disagree.
        setRefused(refusedRoom(error));
      });

    return () => {
      live = false;
    };
  }, [id, attempt]);

  if (refused !== null) {
    return (
      <Centred>
        <Text style={styles.title}>{refused.title}</Text>
        <Text style={styles.body}>{refused.body}</Text>
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

  if (answers === null) {
    return (
      <Centred>
        <ActivityIndicator color={color.primary} />
      </Centred>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <PrepSheet
        answers={answers}
        onSpar={() => {
          // Sparring lives on the debrief, which owns the microphone and the
          // recorder. Sending somebody there is the honest move: this sheet is
          // the thing you take into the room, not the place you rehearse.
          router.replace(`/debrief/${id}`);
        }}
        onShare={() => {
          // Rendering the view to an image and handing it to the native share
          // sheet is the whole of the export, and it drops the verbatim answers
          // on the way out. Deliberately not stubbed with a text share: the
          // point of that decision was what leaves the phone.
          Alert.alert('Not yet built', 'Sharing this sheet as an image is still to come.');
        }}
        back={{ where: 'What the room found', onPress: () => router.back() }}
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

  title: { ...type.headlineSm, color: color.onSurface, textAlign: 'center' },
  body: { ...type.bodyLg, color: color.onSurfaceVariant, textAlign: 'center' },

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
