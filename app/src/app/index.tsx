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
        {/*
          The same kind of thing as the echo spike, and it leaves the same way.
          The room has never met a phone; this is the door that lets it, until
          sign-in exists and the real interrogation screen replaces it.
        */}
        <Link href="/room" style={[styles.link, { color: colors.primary }]}>
          Room
        </Link>
        <Link href="/echo-spike" style={[styles.link, { color: colors.primary }]}>
          Echo spike
        </Link>
        {/*
          Also temporary, and it leaves for the same reason. `enterRoom` owns
          when this sheet actually appears — once per account, ahead of the
          microphone prompt — and that needs a signed-in user it does not have
          yet. Until then this is the only way to see it on a device.
        */}
        <Link href="/disclosure" style={[styles.link, { color: colors.primary }]}>
          Recording disclosure
        </Link>
        {/*
          Not temporary — Settings is a real destination. The link is, though:
          it belongs behind whatever the app shell turns out to be, and that is
          a top-level structural decision the settings brief names and leaves
          open (header affordance now, tab bar once Library and Debrief exist).
        */}
        <Link href="/settings" style={[styles.link, { color: colors.primary }]}>
          Settings
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
