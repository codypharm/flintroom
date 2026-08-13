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
  return (
    <SafeAreaView style={styles.screen}>
      <View style={styles.content}>
        <Text style={styles.text}>Flintroom</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  text: { fontSize: 17 },
});
