import { Link, useTheme } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

/**
 * Undesigned on purpose.
 *
 * This is the vertical slice's home screen and it will show the remaining
 * balance and open a room. It is deliberately unstyled until the `impeccable`
 * pass runs against `design-guide/` — a scaffold's default styling is not a
 * design decision anyone made, and leaving it in place is how it becomes one.
 */
export default function HomeScreen() {
  // `ThemeProvider` in `_layout.tsx` themes navigation chrome, but React Native
  // `Text` inherits nothing from it — an uncoloured `Text` is black on every
  // appearance, which in Dark Mode is black on black. Reading the colour from
  // the same theme keeps the two in step without inventing a value, which
  // `CLAUDE.md` forbids ahead of the `impeccable` pass.
  const { colors } = useTheme();

  return (
    <SafeAreaView style={styles.screen}>
      <View style={styles.content}>
        <Text style={[styles.text, { color: colors.text }]}>Flintroom</Text>
        {/*
          Temporary, and it leaves with the spike. The echo measurement needs a
          way in while task #17 is open; it is an instrument rather than a
          destination, and nothing should come to depend on this link.
        */}
        <Link href="/echo-spike" style={[styles.link, { color: colors.primary }]}>
          Echo spike
        </Link>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  text: { fontSize: 17 },
  link: { fontSize: 15, marginTop: 24, textDecorationLine: 'underline' },
});
