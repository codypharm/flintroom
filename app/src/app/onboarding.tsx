import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { SignInSheet } from '../components/modules/SignInSheet';
import { TablePlan, type Plan } from '../components/modules/TablePlan';
import { WhenPicker } from '../components/modules/WhenPicker';
import { createAppleProvider, isAppleAvailable } from '../lib/auth/apple';
import { createGoogleProvider } from '../lib/auth/google';
import { refusalFor } from '../lib/auth/refusal';
import { auth } from '../lib/auth';
import { CancelledByUser, type IdentityProvider } from '../lib/auth/provider';
import { color } from '../theme/tokens';

/**
 * First launch: describe the room, then keep it.
 *
 * `docs/onboarding.md`, with the ordering amended on 2026-08-18 — the plan is
 * filled in, then identity is asked for, then the reveal arrives on the setup
 * screen as the room the answers built. The doc's diagram put the reveal before
 * sign-in; its argument only ever established that the *survey* comes first,
 * and moving the reveal after removed a preview that could disagree with the
 * room a session actually builds.
 *
 * **The answers are held here and posted once, with sign-up.** Nothing about
 * this plan exists on the server until there is a user to attach it to, which
 * is what keeps `CLAUDE.md`'s rule that a `user_id` exists only for a real
 * person: no anonymous account rows, no orphan per bounced install, no merge
 * path. The cost is accepted and stated in the doc — no per-question drop-off
 * analytics for somebody who leaves before signing in.
 *
 * The microphone is deliberately not asked for here. `docs/onboarding.md`:
 * a refusal on iOS is sticky and unrecoverable in-app, so the prompt belongs at
 * the moment its reason is self-evident — they have tapped to enter the room
 * and the panel is waiting.
 */

/**
 * Built once, at module load, because `GoogleSignin.configure` is process-wide
 * and re-running it per render would reconfigure the SDK under an open sheet.
 */
const google: IdentityProvider = createGoogleProvider();
const apple: IdentityProvider = createAppleProvider();

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
  const [plan, setPlan] = useState<Plan>(BLANK);
  const [asking, setAsking] = useState(false);
  // The route owns the picker because it is a native host component and this
  // screen has to stay renderable without one — the same seam the microphone
  // uses in `debrief/[id].tsx`.
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [appleAvailable, setAppleAvailable] = useState(false);

  useEffect(() => {
    let live = true;
    void isAppleAvailable().then((can) => live && setAppleAvailable(can));
    return () => {
      live = false;
    };
  }, []);

  const enter = async (provider: IdentityProvider) => {
    setBusy(true);
    setRefusal(null);

    try {
      await auth.signIn(provider.id, await provider.signIn(), {
        // Posted with sign-up rather than after it: an account that exists and
        // has been asked nothing is a user who described a board review and
        // gets asked about it again on their next launch.
        situation: plan.situation,
        happensOn: plan.happensOn,
        role: plan.role,
        audience: plan.audience,
      });

      // `replace`, not `push`. Onboarding runs once and there is nothing behind
      // it worth a back gesture — returning here would offer to build a plan
      // for an account that already has one.
      router.replace('/setup');
    } catch (error) {
      if (error instanceof CancelledByUser) {
        // Not a failure. Somebody deliberately made nothing happen, and saying
        // "something went wrong" immediately afterwards is how an app teaches
        // people not to trust what it says.
        return;
      }

      // One sentence per cause, decided in `refusal.ts` and tested there. The
      // string this replaced was said to every failure alike, which sent
      // somebody whose account had been refused off to check their signal.
      setRefusal(refusalFor(error));
    } finally {
      setBusy(false);
    }
  };

  if (!asking) {
    return (
      <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
        <TablePlan
          seats={FREE_SEATS}
          hardest={RUNGS}
          plan={plan}
          busy={busy}
          onChange={setPlan}
          onPickDate={() => setPicking(true)}
          onContinue={() => setAsking(true)}
        />

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

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <ScrollView contentContainerStyle={styles.filled}>
        <SignInSheet
          appleAvailable={appleAvailable}
          busy={busy}
          refusal={refusal}
          onApple={() => void enter(apple)}
          onGoogle={() => void enter(google)}
          // Their own answers, shown back. Not the panel — the archetypes are
          // the server's translation of these and stay unseen until setup.
          seated={plan.audience}
          // Back to the plan with every answer still in it, because the plan
          // lives in this component's state and has been posted nowhere. The
          // sheet refuses this itself while a sign-in is in flight.
          onBack={() => setAsking(false)}
        />
      </ScrollView>
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
});
