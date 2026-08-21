import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { SettingsScreen, type Holdings } from '../../components/modules/SettingsScreen';
import { confirmDeletion } from '../../lib/account/deletion';
import { saved } from '../../lib/account/holdings';
import { createAccountApi } from '../../lib/api/accountApi';
import { createMaterialsApi } from '../../lib/api/materialsApi';
import { createPreferencesApi, type Recording } from '../../lib/api/preferencesApi';
import { createSessionsApi } from '../../lib/api/sessionsApi';
import { useHeld } from '../../lib/balance/held';
import { useGateway } from '../../lib/auth/gateway';
import { SignedOut } from '../../lib/auth/session';
import { API_BASE_URL, auth } from '../../lib/auth';
import { color } from '../../theme/tokens';

/**
 * Settings, on the account rather than on a constant.
 *
 * Until #85 this route rendered a module-level `FIRST_RUN` — so it told
 * everybody they had 15 minutes, no saved rooms, nothing attached and a 30-day
 * window, and the recording switch raised an Alert saying "Not yet connected".
 * The docstring here was honest about that and named sign-in as the blocker.
 * Sign-in landed in #19, which made the docstring stale rather than honest.
 *
 * **Four reads, three of them here.** Rooms and their expiry come out of
 * `/v1/sessions`, the window and the switch out of `/v1/preferences/recording`,
 * and the attached count out of `/v1/materials` — an endpoint that did not
 * exist until this task, which is why the count was the last literal to go.
 * The fourth, the balance, is the app bar's: it reads it for all four tabs, and
 * the bar and the "Time under fire" row are the same number on the same screen.
 * Two fetches for it is two chances to disagree in front of somebody.
 *
 * **On focus rather than on mount.** A room ends and lands back here through
 * the debrief; a count still showing the pre-room figure is worse than one
 * showing none.
 *
 * **Deletion and sign-out never wait on any of it.** They need a credential,
 * not an inventory, and the account somebody most wants out of is the one whose
 * reads are failing.
 */

const sessions = createSessionsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const materials = createMaterialsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const preferences = createPreferencesApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

/** Everything this screen reads for itself — the balance is the app bar's. */
type Inventory = Holdings;

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

export default function SettingsRoute() {
  const { recheck } = useGateway();
  const held = useHeld();

  const [inventory, setInventory] = useState<Inventory | null>(null);
  // Beside the counts rather than inside them — #92. It arrives from its own
  // request and fails on its own, and it is a control rather than a figure.
  const [saving, setSaving] = useState<Recording | null>(null);
  const [reading, setReading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [writing, setWriting] = useState(false);

  useFocusEffect(
    useCallback(() => {
      // Read only so that Try again re-runs this effect. The body does not
      // otherwise depend on the count, and without the reference the exhaustive
      // -deps rule would have the dependency removed and the retry silently
      // stop working.
      void attempt;

      let live = true;
      setReading(true);

      // The gate decides where a signed-out person goes. A `replace` here
      // would be a second opinion about the same thing.
      const gone = (error: unknown) => {
        if (error instanceof SignedOut) recheck();
      };

      // **Two reads, not one gathered promise — #92.** These fail
      // independently and `Promise.all` rejects on the first rejection, so a
      // 502 on `/v1/materials` used to discard a `/v1/preferences/recording`
      // that had answered 200. What that removed was the switch which turns
      // saving off, a control `docs/privacy-policy.md` promises by name.
      //
      // The counts stay all-or-nothing, and that half of the old reasoning is
      // kept: this screen's job is to state what is held, and a number smaller
      // than the truth is the worst way to be wrong here. What changed is that
      // an unrelated failure no longer takes a *control* down with the counts.
      Promise.all([sessions.list(), materials.list()])
        .then(([rooms, attached]) => {
          if (!live) return;
          setInventory({ ...saved(rooms), materials: attached.length });
        })
        .catch((error) => {
          if (!live) return;
          gone(error);
          // Stated by the screen rather than drawn as an empty account. Partial
          // counts are still not shown: rendering three of four rows and
          // quietly dropping the fourth would understate what we hold.
          setInventory(null);
        })
        .finally(() => {
          if (live) setReading(false);
        });

      preferences
        .read()
        .then((now) => live && setSaving(now))
        .catch((error) => {
          if (!live) return;
          gone(error);
          // Null draws no switch. A switch has to pick a position and either
          // position is a claim about whether rooms are being recorded.
          setSaving(null);
        });

      return () => {
        live = false;
      };
    }, [attempt, recheck])
  );

  /**
   * The switch, and the one control here that is a promise rather than a
   * preference — `docs/privacy-policy.md` states that a person can turn saving
   * off, and until this task the control raised an Alert instead.
   *
   * **It does not move until the server has agreed.** No optimistic flip: the
   * surface brief calls a toggle that appears to have flipped and did not the
   * worst failure this screen has, and it is right, because the direction it
   * fails in is showing "off" while the next room is still being saved. So the
   * switch disables, the write goes out, and the position is set from the
   * response.
   */
  const setRecording = useCallback(
    (records: boolean) => {
      setWriting(true);

      void preferences
        .setRecordsRooms(records)
        // Straight onto the preference. It used to have to reach inside the
        // inventory, which meant a successful write was silently dropped
        // whenever the counts had failed to read — the switch would move on
        // the server and not on the screen.
        .then((now: Recording) => setSaving(now))
        .catch((error) => {
          if (error instanceof SignedOut) {
            recheck();
            return;
          }
          // The switch never moved, so this says what is still true rather than
          // apologising for a state it put on the screen.
          void tell(
            records
              ? 'I could not turn saving on. Your rooms are still not being saved.'
              : 'I could not turn saving off. Your rooms are still being saved.'
          );
        })
        .finally(() => setWriting(false));
    },
    [recheck]
  );

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.surface }} edges={[]}>
      <SettingsScreen
        holdings={
          inventory === null
            ? null
            : // The balance is nullable on its own: the app bar swallows its
              // failures, so it can be unknown while the inventory is fine.
              inventory
        }
        reading={reading}
        writing={writing}
        onRetry={() => setAttempt((made) => made + 1)}
        recording={saving}
        // From the app bar's own read, so it survives a failed count — and with
        // it the only route to the buy screen for anybody who has minutes left.
        minutesRemaining={held?.minutes ?? null}
        onRecordingChange={setRecording}
        onOpenMaterial={() => router.push('/material')}
        onGetMore={() => router.push('/minutes')}
        onSignOut={() => {
          void (async () => {
            // Ends the session here and, if reachable, everywhere — and never
            // rejects, so there is nothing to catch. A sign-out that could fail
            // would leave somebody looking at a signed-in screen having asked
            // to leave.
            await auth.signOut();
            recheck();
          })();
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
