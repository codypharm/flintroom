import { Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { SettingsScreen, type Holdings } from '../components/modules/SettingsScreen';
import { color } from '../theme/tokens';

/**
 * Settings, on the state an account has before it has done anything.
 *
 * **Not yet reading the API**, and that is the honest position rather than a
 * shortcut. Every field below has an endpoint — `/v1/sessions`,
 * `/v1/preferences/recording`, `/v1/materials`, `/v1/balance` — and all four
 * need a bearer token the app cannot obtain, because sign-in has no screen. The
 * room screen works around that with a pasted development token; a settings
 * screen that did the same would be an instrument rather than a destination.
 *
 * So this renders the first-run state, which the surface brief calls out as the
 * one most people see first and the one most easily got wrong. When sign-in
 * lands, this file gains a fetch and loses this comment.
 */

const FIRST_RUN: Holdings = {
  rooms: 0,
  oldestExpiry: null,
  materials: 0,
  recordsRooms: true,
  // The free tier's window, which is what an account that has not upgraded has.
  // The real figure is per tier and arrives from the preference endpoint —
  // `SettingsScreen` takes it as data precisely so this file cannot decide it.
  retentionDays: 30,
  minutesRemaining: 15,
};

export default function SettingsRoute() {
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.surface }} edges={['bottom']}>
      <SettingsScreen
        holdings={FIRST_RUN}
        onRecordingChange={() => {
          // Deliberately inert until there is a token to send it with. A switch
          // that flipped locally and reached nothing would show somebody their
          // recordings were off when the next room would still be saved — the
          // one failure this screen exists to prevent.
          Alert.alert('Not yet connected', 'This needs sign-in, which has no screen yet.');
        }}
        onDeleteAccount={() => {
          // Designed here, built separately: what is destroyed versus anonymised
          // touches the ledger, sessions, materials, recordings and auth
          // identities, and `audit_events` deliberately survives deletion. That
          // is a decision, not plumbing.
          Alert.alert('Not yet built', 'Account deletion needs its own task.');
        }}
      />
    </SafeAreaView>
  );
}
