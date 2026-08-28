import { useEffect, useState } from 'react';
import { StyleSheet, Linking } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { SignInSheet } from '../components/modules/SignInSheet';
import { auth } from '../lib/auth';
import { createAppleProvider, isAppleAvailable } from '../lib/auth/apple';
import { useGateway } from '../lib/auth/gateway';
import { createGoogleProvider } from '../lib/auth/google';
import { CancelledByUser, type IdentityProvider } from '../lib/auth/provider';
import { refusalFor } from '../lib/auth/refusal';
import { color } from '../theme/tokens';

/**
 * The front door, for anybody the app does not recognise.
 *
 * **This is the reordering.** `docs/onboarding.md` had the survey first and the
 * sheet after, and the survey rode on the sign-in request in one call. The
 * architect reversed it on 2026-08-20 for the case that argument never covered:
 * a *signed-out* launch. A returning user — signed out, expired, or reinstalled
 * — is not the stranger the "no toll gate" reasoning was about, and under the
 * old order they had no way in at all, because this sheet was rendered in
 * exactly one place: after five questions, inside onboarding.
 *
 * No plan is posted here. Somebody arriving at this screen may have described a
 * room years ago or never; the account answers that on `/v1/me`, and the layout
 * sends them to the survey or past it. Sending an empty plan would be this
 * screen guessing at something the server already knows.
 *
 * No way back, and none to draw. This is where the app begins for anybody it
 * cannot identify, which is why `SignInSheet.onBack` became nullable.
 */

const google = createGoogleProvider();
const apple = createAppleProvider();

export default function SignInRoute() {
  const { recheck } = useGateway();

  const [appleAvailable, setAppleAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

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
      await auth.signIn(provider.id, await provider.signIn());

      // No navigation. The gate owns where somebody lands, and it has to ask
      // the server anyway to learn whether this account has described a room —
      // so this screen says "ask again" and lets the answer decide. A
      // `router.replace` here would be a second opinion about the same thing.
      recheck();
    } catch (error) {
      if (error instanceof CancelledByUser) {
        // Not a failure. Somebody deliberately made nothing happen, and saying
        // "something went wrong" straight afterwards is how an app teaches
        // people not to trust what it says.
        return;
      }
      setRefusal(refusalFor(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      {/*
        No layout here. The sheet centres its own group — the architect's call
        on 2026-08-20 — and it has to, because the back control sits outside
        that group and the scroll view sits inside it. A centring wrapper at
        this level is what was tried before and it produced the composition the
        sheet's own note argues against: a centred box still pushing its
        children to its two ends.
      */}
      <SignInSheet
        appleAvailable={appleAvailable}
        busy={busy}
        refusal={refusal}
        onApple={() => void enter(apple)}
        onGoogle={() => void enter(google)}
        onBack={null}
        onOpenLegal={(url) => void Linking.openURL(url)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
});
