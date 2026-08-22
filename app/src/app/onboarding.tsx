import { router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { TablePlan, type Plan } from '../components/modules/TablePlan';
import { WhenPicker } from '../components/modules/WhenPicker';
import { createMeApi } from '../lib/api/meApi';
import { API_BASE_URL, auth } from '../lib/auth';
import { useGateway } from '../lib/auth/gateway';
import { color, space, type } from '../theme/tokens';

const me = createMeApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

/**
 * Describe the room, once the account exists.
 *
 * **Sign-in moved in front of this on 2026-08-20**, reversing the ordering
 * `docs/onboarding.md` settled and recording the reversal there. The old
 * argument — "identity is asked for once there is something to lose, rather
 * than a toll gate in front of a stranger" — was about a *first* launch. A
 * signed-out launch is a different case, and under survey-first it had no way
 * in at all.
 *
 * So the answers no longer ride on the sign-in request. They are posted to
 * `POST /v1/onboarding` by an account that already exists, which is the state
 * that document once refused — "a partially-created account with no
 * configuration is a state worth not having". It is reachable on purpose now,
 * and survivable because `/v1/me` publishes `onboarded`: somebody who abandons
 * here is asked again next launch rather than left half-made.
 *
 * The microphone is deliberately not asked for here. `docs/onboarding.md`:
 * a refusal on iOS is sticky and unrecoverable in-app, so the prompt belongs at
 * the moment its reason is self-evident — they have tapped to enter the room
 * and the panel is waiting.
 */

const BLANK: Plan = {
  situation: null,
  happensOn: null,
  role: null,
  audience: [],
  // The gentle rung. `docs/difficulty-calibration.md` decision 4: a first room
  // that destroys somebody produces churn rather than resilience, and this is
  // the one screen where every user is a first-timer.
  difficulty: 1,
};

export default function OnboardingRoute() {
  const { recheck } = useGateway();
  const [plan, setPlan] = useState<Plan>(BLANK);
  // The route owns the picker because it is a native host component and this
  // screen has to stay renderable without one — the same seam the microphone
  // uses in `debrief/[id].tsx`.
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const describe = async () => {
    setBusy(true);
    setRefusal(null);

    try {
      await me.describeTheRoom({
        situation: plan.situation,
        happensOn: plan.happensOn,
        role: plan.role,
        audience: plan.audience,
      });

      // `reveal` is the whole reason this parameter exists.
      // `docs/onboarding.md` promised a "here's your room" moment, and the
      // server derives a seating from these answers to deliver it — but that is
      // a reveal *earned by answering five questions*, and it is only ever
      // right on this one path. Every other way into Home opens on an empty
      // roster, because a room somebody did not choose is a room they have to
      // undo.
      router.replace({ pathname: '/', params: { reveal: '1' } });

      // And tell the gate, which is what actually decides whether this screen
      // is reachable at all. Without it the guard still reads `undescribed` and
      // would put the survey straight back in front of them.
      recheck();
    } catch {
      // One sentence, because there is one cause worth distinguishing here and
      // it is not reachable: the account already exists and the credential was
      // good a moment ago, so a failure is the network or us.
      setRefusal('That did not save. Try again in a moment.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <TablePlan
        seats={FREE_SEATS}
        hardest={RUNGS}
        plan={plan}
        busy={busy}
        onChange={setPlan}
        onPickDate={() => setPicking(true)}
        onContinue={() => void describe()}
      />

      {/* Said here rather than inside `TablePlan`, which has no slot for a
          failure and should not grow one: the only thing that can fail on this
          screen is the save, and the save belongs to this route. */}
      {refusal !== null && <Text style={styles.refusal}>{refusal}</Text>}

      {picking && (
        <WhenPicker
          value={plan.happensOn}
          onPick={(happensOn) => {
            setPlan({ ...plan, happensOn });
            setPicking(false);
          }}
          onClose={() => setPicking(false)}
        />
      )}
    </SafeAreaView>
  );
}

/**
 * The free tier's table, and the ladder's height.
 *
 * Hardcoded here and only here, because this screen runs *before* there is a
 * token to read `/v1/archetypes` with — the one place in the app that cannot
 * ask the server what a plan allows. Every screen after sign-in reads the real
 * catalogue, so a tier change reaches them without a release; this one would
 * lag, which is why it holds the value that never moves. Somebody seating more
 * than three here would be refused at session start anyway, by `panel.py`.
 */
const FREE_SEATS = 3;
const RUNGS = 3;

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  // Grows to the full height so the sheet can anchor its two ends, and scrolls
  // instead when the largest Dynamic Type sizes make it taller than the screen.
  filled: { flexGrow: 1 },
  refusal: {
    ...type.bodyMd,
    color: color.onSurfaceVariant,
    paddingHorizontal: space.screen,
    paddingBottom: space.base,
  },
});
