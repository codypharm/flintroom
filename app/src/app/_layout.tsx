import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
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
      <Stack>
        <Stack.Screen name="index" options={{ headerShown: false }} />
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
