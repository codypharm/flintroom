import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useColorScheme } from 'react-native';

import { FONTS } from '../theme/fonts';

/**
 * A stack, not a tab bar.
 *
 * The template ships tabs, but the first slice is three screens that follow one
 * another — sign in, home, room — and none of them is a peer destination. A tab
 * bar is also a design decision, and design for this product goes through the
 * `impeccable` pass against `design-guide/`, not through a scaffold default.
 *
 * Dark Mode is wired from the start because it is a first-class appearance per
 * `CLAUDE.md`, and because the interrogation screen is committed to a dark
 * ground regardless of system setting — so the seam has to exist early rather
 * than be retrofitted around one screen that ignores it.
 */
export default function RootLayout() {
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
      <Stack screenOptions={{ headerShown: false }}>
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
