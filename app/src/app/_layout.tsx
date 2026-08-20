import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
  useColorScheme,
} from 'react-native';

import { FONTS } from '../theme/fonts';
import { Gateway, useGateway } from '../lib/auth/gateway';
import { color, radius, space, type } from '../theme/tokens';

/**
 * A stack around a tab bar.
 *
 * It was a stack alone until the Library existed, and the reasoning holds up:
 * the first slice was three screens that followed one another — sign in, home,
 * room — and none of them was a peer destination. A tab bar was also a design
 * decision, and design here goes through the `impeccable` pass against
 * `design-guide/` rather than through a scaffold default.
 *
 * What earned one is a *history*. `(tabs)` holds Home, Library and Settings —
 * three places you can be — and everything else stays on this stack, because
 * everything else is a step in a flow: setup, the room, the debrief, the prep
 * sheet, onboarding. A tab bar under a live interrogation would offer to
 * navigate away from a metered room.
 *
 * Dark Mode is wired from the start because it is a first-class appearance per
 * `CLAUDE.md`, and because the interrogation screen is committed to a dark
 * ground regardless of system setting — so the seam has to exist early rather
 * than be retrofitted around one screen that ignores it.
 */
export default function RootLayout() {
  return (
    <Gateway>
      <Shell />
    </Gateway>
  );
}

/**
 * The app, once the door has been answered.
 *
 * Split from `RootLayout` because the gate has to be *above* the thing that
 * reads it — a provider cannot be consumed by the component that renders it —
 * and because two of the four answers are not screens at all.
 */
function Shell() {
  const { who, recheck } = useGateway();
  const colorScheme = useColorScheme();
  const [fontsLoaded] = useFonts(FONTS);

  // Nothing renders until the brand face is registered. React Native does not
  // re-lay-out text when a font arrives late — the first frame measures against
  // the system sans and keeps that geometry, so a flash of the wrong font is
  // not only a flash. Holding one frame is cheaper than shipping a screen laid
  // out for a typeface it is not using.
  if (!fontsLoaded) {
    return null;
  }

  // Not a conclusion, so not a screen. Holding here rather than assuming
  // signed-out is what stops the sign-in screen flashing at every signed-in
  // launch — the whole reason `checking` is a separate state.
  if (who === 'checking') {
    return <Waiting />;
  }

  // Deliberately not the sign-in screen. A phone loses its connection
  // constantly, and treating that as a dead credential would discard a working
  // session — including a refresh token that cannot be got back.
  if (who === 'unreachable') {
    return <Unreachable onRetry={recheck} />;
  }

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      {/*
        Dark glyphs, unconditionally, and not `auto`.

        `auto` follows the system appearance; this product does not. `tokens.ts`
        holds one palette, so every screen below is `#fcf9f8` whatever the phone
        is set to, and light glyphs would be unreadable on it. The two screens
        that *do* follow the theme are the dev harnesses, and they say so
        themselves.
      */}
      <StatusBar style="dark" />
      {/*
        No headers, anywhere.

        Every screen in this app draws its own title — `Room`, `Echo spike`,
        `Before you go in`, `Who is in the room` — so a stack header is a second
        title stacked above the first. Worse, a route with no `Stack.Screen`
        entry falls back to its *filename*, which is how six screens came to be
        headed `onboarding`, `setup`, `room`, `prep-sheet` in lowercase.

        Set here rather than per route so a new screen inherits it: the failure
        this replaces was silent and opt-out, and the fix should be the default.
        Back is still available — `Stack` keeps the edge-swipe gesture with the
        header hidden, and Android has the system gesture regardless.

        The cost is that each screen owns its own top safe-area inset. That is
        `edges={['top', 'bottom']}` on every `SafeAreaView` below, and it is the
        honest trade: the header was paying that rent by occupying the space.
      */}
      {/*
        **Nothing renders until we know who is there.** Until 2026-08-20 the app
        drew itself fully for somebody with no account: Home fired `/v1/balance`
        and `/v1/progress` as nobody, took two 401s, swallowed them by design,
        and explained nothing (#86).

        `Stack.Protected` rather than a redirect in an effect. A guard is a
        statement about what may exist; a redirect is a race between a
        navigator mounting and an effect firing, and the losing frame is the one
        where a signed-out person sees somebody's rooms.
      */}
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Protected guard={who === 'signed out'}>
          <Stack.Screen name="sign-in" />
        </Stack.Protected>

        {/*
          Reachable only by an account that exists and has said nothing — the
          state the reordering made possible on purpose. It is not a first-launch
          screen any more; it is the one question the product still needs
          answered, asked whenever it is still unanswered.
        */}
        <Stack.Protected guard={who === 'undescribed'}>
          <Stack.Screen name="onboarding" />
        </Stack.Protected>

        <Stack.Protected guard={who === 'ready'}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="interrogation" />
          <Stack.Screen name="rooms/[id]" />
          <Stack.Screen name="debrief/[id]" />
          <Stack.Screen name="prep-sheet/[id]" />
          <Stack.Screen name="echo-spike" />
        </Stack.Protected>

        {/*
          A native sheet rather than a full screen. It is a one-time
          interruption before entering the room, which is the case a modal is
          actually for — protected focus on something that has to be read once.

          `fitToContents` rather than a fraction of the screen: the sheet is
          four short paragraphs, and a fixed detent would leave dead space on a
          large phone and clip the last line on a small one. The corner radius
          is the brand's 28px container radius rather than the platform default.
        */}
        <Stack.Screen
          name="disclosure"
          options={{
            presentation: 'formSheet',
            sheetAllowedDetents: 'fitToContents',
            sheetGrabberVisible: true,
            sheetCornerRadius: 28,
            headerShown: false,
          }}
        />
      </Stack>
    </ThemeProvider>
  );
}


/** The moment before anything is known. Deliberately almost nothing. */
function Waiting() {
  return (
    <View style={styles.middle}>
      <ActivityIndicator color={color.primary} />
    </View>
  );
}

/**
 * We could not find out who is there.
 *
 * Its own screen rather than the sign-in one, and that is the whole point of
 * keeping `unreachable` apart from `signed out`. Somebody on a train has a
 * perfectly good account, and offering them a sign-in button says the opposite
 * — while a second sign-in would replace the tokens they already hold.
 */
function Unreachable({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={styles.middle}>
      <Text style={styles.title}>Cannot reach Flintroom</Text>
      <Text style={styles.body}>
        You are still signed in. This is the connection, not your account.
      </Text>
      <Pressable
        accessibilityRole="button"
        onPress={onRetry}
        style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
      >
        <Text style={styles.retryLabel}>Try again</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  middle: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.screen,
    gap: space.snug,
    backgroundColor: color.surface,
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
  retryLabel: { ...type.labelLg, color: color.surface },
  pressed: { opacity: 0.6 },
});
