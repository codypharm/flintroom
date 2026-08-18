import { Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { SettingsScreen, type Holdings } from '../components/modules/SettingsScreen';
import { confirmDeletion } from '../lib/account/deletion';
import { createAccountApi } from '../lib/api/accountApi';
import { API_BASE_URL, auth } from '../lib/auth';
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
 *
 * **Deletion is the exception, and is fully wired.** It is an App Store
 * requirement rather than a screen detail, and it needs no data to render — it
 * needs a credential, which `auth` supplies or refuses. With no session the
 * flow says so plainly and changes nothing, which is the true answer today and
 * stays the true answer once sign-in exists.
 */

/**
 * The confirmation, as the platform's own control.
 *
 * `Alert.alert` rather than anything of ours. Apple HIG makes a destructive
 * confirmation an alert with the destructive action styled and Cancel as the
 * default, and `CLAUDE.md` is explicit that brand expresses through tint,
 * type, motion and content — not through reinvented controls. This is the last
 * screen on which to be inventive.
 */
const ask = (title: string, body: string): Promise<boolean> =>
  new Promise((resolve) => {
    Alert.alert(title, body, [
      // Cancel first, and it is the one a stray tap lands on. iOS renders it
      // last visually and treats it as the default dismissal, which is exactly
      // the safety this needs.
      { text: 'Keep my account', style: 'cancel', onPress: () => resolve(false) },
      { text: 'Delete', style: 'destructive', onPress: () => resolve(true) },
    ]);
  });

const tell = (message: string): Promise<void> =>
  new Promise((resolve) => {
    Alert.alert('', message, [{ text: 'OK', onPress: () => resolve() }]);
  });

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
    <SafeAreaView style={{ flex: 1, backgroundColor: color.surface }} edges={['top', 'bottom']}>
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
          // Not awaited: this is a button handler, and `confirmDeletion` never
          // rejects — every outcome it has is a sentence.
          void confirmDeletion({
            ask,
            tell,
            deleteAccount: () =>
              createAccountApi({
                baseUrl: API_BASE_URL,
                accessToken: () => auth.accessToken(),
              }).deleteAccount(),
            // The server revoked every refresh token as part of the request,
            // so the pair on this device is already dead. Cleared rather than
            // signed out: presenting a revoked token to the sign-out endpoint
            // would take a 401 for something we caused on purpose.
            forgetCredentials: () => auth.signOut(),
          });
        }}
      />
    </SafeAreaView>
  );
}
