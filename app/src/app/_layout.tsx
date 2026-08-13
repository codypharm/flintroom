import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { useColorScheme } from 'react-native';

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

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <Stack />
    </ThemeProvider>
  );
}
