import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Dimensions,
  NativeModules,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrepSheet } from '../../components/modules/PrepSheet';
import { createDebriefApi, type WeakAnswer } from '../../lib/api/debriefApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { useGateway } from '../../lib/auth/gateway';
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
  const { recheck } = useGateway();
  const { id } = useLocalSearchParams<{ id: string }>();

  const [answers, setAnswers] = useState<WeakAnswer[] | null>(null);
  const printable = useRef<View>(null);
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
          // The gate decides where a signed-out person goes, not this screen.
          // `Stack.Protected` moves them the moment the answer changes, and a
          // `router.replace` here would be a second opinion about the same
          // thing — one that used to send them to Home, which is the screen
          // that cannot work without an account.
          recheck();
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
  }, [id, attempt, recheck]);

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
      {/*
        The sheet as it leaves the phone, drawn off-screen and captured on
        demand. `collapsable={false}` is load-bearing on Android — a view with
        no visual effect is otherwise flattened out of the native tree and
        there is nothing to capture. Rendered always rather than on tap: it is
        cheap, and mounting it during the tap would race the capture.
      */}
      <View ref={printable} collapsable={false} style={styles.print} pointerEvents="none">
        <PrepSheet answers={answers} printing onSpar={() => {}} onShare={() => {}} back={{ where: '', onPress: () => {} }} />
      </View>
      <PrepSheet
        answers={answers}
        onSpar={() => {
          // Sparring lives on the debrief, which owns the microphone and the
          // recorder. Sending somebody there is the honest move: this sheet is
          // the thing you take into the room, not the place you rehearse.
          router.replace(`/debrief/${id}`);
        }}
        onShare={async () => {
          // The whole of the export: rasterise the printing render and hand
          // the file to the native share sheet. What leaves the phone is that
          // render — findings and coaching, never the verbatim answers, which
          // is the decision #60 recorded and the reason this was never
          // stubbed with a text share.
          // Probed before imported. Both are native modules, and on a dev
          // client built before they were added, merely *evaluating* their
          // JavaScript throws — at the top of the file that took the route
          // down, and even deferred to the tap the dev overlay shouts about
          // the caught error. `requireOptionalNativeModule` answers null
          // instead of throwing, so a stale build gets a sentence about
          // rebuilding and the throwing module is never evaluated at all.
          const { requireOptionalNativeModule } = await import('expo-modules-core');
          const stale =
            requireOptionalNativeModule('ExpoSharing') === null ||
            NativeModules.RNViewShot == null;
          if (stale) {
            Alert.alert(
              'Not in this build yet',
              'Sharing needs one rebuild of the app. It will work after the next USB install.'
            );
            return;
          }

          try {
            const [{ captureRef }, { shareAsync }] = await Promise.all([
              import('react-native-view-shot'),
              import('expo-sharing'),
            ]);
            const shot = await captureRef(printable, { format: 'png', quality: 1 });
            await shareAsync(shot, { mimeType: 'image/png' });
          } catch {
            Alert.alert('That did not share', 'Try again in a moment.');
          }
        }}
        // The same destination the Library's room screen now names. `BackTo` wants
        // a place rather than a verb, and "the coach" is who is on that screen —
        // which is also what the control that opens it says.
        back={{ where: 'The coach', onPress: () => router.back() }}
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
  /**
   * Parked beyond the left edge at screen width, never display:none — a view
   * that does not lay out cannot be captured. The height is its content's.
   */
  print: {
    position: 'absolute',
    left: -Dimensions.get('window').width * 2,
    width: Dimensions.get('window').width,
  },
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
  // `onPrimary`, not `surface`. Text on the primary fill has always been
  // `onPrimary`'s job, and reaching for the ground colour only worked while the
  // ground happened to be near-white — which stopped being true when it was
  // darkened to make cards visible.
  retryLabel: { ...type.labelLg, color: color.onPrimary },
  pressed: { opacity: 0.6 },
});
