import { Stack, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { MoreMinutes } from '../components/modules/MoreMinutes';
import { createBalanceApi } from '../lib/api/balanceApi';
import {
  createPurchaseApi,
  type Pack,
  type Plan,
  type PurchaseOptions,
} from '../lib/api/purchaseApi';
import { API_BASE_URL, auth } from '../lib/auth';
import { useGateway } from '../lib/auth/gateway';
import { SignedOut } from '../lib/auth/session';
import { revenueCatStore } from '../lib/billing/revenuecat';
import { settles } from '../lib/billing/settling';
import { unconfiguredStore, type Sellable, type Store } from '../lib/billing/store';
import { color } from '../theme/tokens';

/**
 * Buying more time in the room.
 *
 * Reached from Settings and from a room that would not open. A pushed screen
 * rather than a modal, and that is the product decision rather than a layout
 * one: §4.5 point 4 requires *"one tap to decline, always"*, and a screen you
 * can leave with the back gesture satisfies it structurally. Nothing here can
 * become dismissible-only-by-paying, because there is nothing to dismiss.
 *
 * **The store is RevenueCat when a key is present, and a shut shop when it is
 * not.** The key decides per build: production and any developer who has set
 * `EXPO_PUBLIC_REVENUECAT_ANDROID_KEY` get the real till; a build without it
 * keeps `unconfiguredStore()`, which sells nothing and refuses to buy — an
 * honest closed shop rather than a pretend open one. The key is the public
 * SDK identifier, not a secret; it ships in the bundle by design.
 */

const balance = createBalanceApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const purchases = createPurchaseApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const storeKey = process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_KEY;
const store: Store = storeKey
  ? revenueCatStore({ apiKey: storeKey, userId: () => auth.userId() })
  : unconfiguredStore();

/**
 * The bar carries the back button and nothing else — an empty `headerTitle`
 * so nothing is drawn twice, and `edges={[]}` on the screen because the
 * header owns the top inset.
 *
 * The rest is what every other pushed route pins and this one did not, which
 * left it the app's one bar with a drop shadow, an inherited tint, and a
 * background that could disagree with the screen under it. Android draws no
 * back label, so the generic word costs nothing there; when iOS arrives (#99)
 * it reads as the plain control it is — three doors lead here (Settings, the
 * time chip on every tab, a room that refused to open), so no single name
 * would be true.
 */
const BAR = {
  headerShown: true,
  headerTitle: '',
  headerBackTitle: 'Back',
  headerTintColor: color.onSurface,
  headerShadowVisible: false,
  headerStyle: { backgroundColor: color.surface },
} as const;

export default function MoreMinutesRoute() {
  const { recheck } = useGateway();

  const [holding, setHolding] = useState<number | null>(null);
  const [options, setOptions] = useState<PurchaseOptions | null>(null);
  const [sells, setSells] = useState<Sellable[] | null>(null);
  // Independent of the store, and that independence is the fix in #95: what
  // a plan *is* comes from us, so a store that never answers must not blank
  // the plans.
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [state, setState] = useState<'idle' | 'buying' | 'waiting' | 'failed'>('idle');

  const gone = useCallback(
    (thrown: unknown) => {
      if (thrown instanceof SignedOut) void recheck();
    },
    [recheck],
  );

  useFocusEffect(
    useCallback(() => {
      let live = true;

      // Three independent reads rather than one: what they hold, which control
      // leads, and what there is to sell. They fail independently too — a store
      // that will not answer must not blank the balance, and a balance that
      // will not answer must not hide the shop.
      balance
        .read()
        .then((held) => live && setHolding(held.minutes))
        .catch(gone);
      purchases
        .packs()
        .then((offered) => live && setPacks(offered))
        .catch(gone);
      purchases
        .plans()
        .then((rungs) => live && setPlans(rungs))
        .catch(gone);
      purchases
        .options()
        .then((answer) => live && setOptions(answer))
        .catch(gone);
      store
        .sells()
        .then((offered) => live && setSells(offered))
        .catch(() => live && setSells([]));

      return () => {
        live = false;
      };
    }, [gone]),
  );

  const buy = useCallback(
    async (what: Sellable) => {
      // Held before the purchase, because it is the thing `settles` compares
      // against. Read from state rather than re-fetched: a read in flight here
      // races the webhook, and a baseline that already includes the top-up
      // would never look like it moved.
      const before = holding ?? 0;

      setState('buying');
      try {
        await store.buy(what);
      } catch {
        // Covers a declined card, a cancelled sheet and a dropped connection
        // alike, and the screen says nothing about money for that reason — we
        // do not know which, and the store does.
        setState('failed');
        return;
      }

      setState('waiting');
      const moved = await settles(async () => (await balance.read()).minutes, before);
      if (moved) setHolding((await balance.read()).minutes);
      // Left in `waiting` when it did not move. The purchase is not lost — the
      // webhook may still land — and saying "that failed" about money that has
      // been taken would be worse than saying nothing new.
      setState(moved ? 'idle' : 'waiting');
    },
    [holding],
  );

  const restore = useCallback(async () => {
    setState('buying');
    try {
      await store.restore();
      setState('waiting');
    } catch {
      setState('failed');
    }
  }, []);

  if (options === null && sells === null) {
    return (
      <SafeAreaView style={styles.screen} edges={[]}>
        <Stack.Screen options={BAR} />
        <View style={styles.centred}>
          <ActivityIndicator color={color.primary} accessibilityLabel="Loading" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={[]}>
      <Stack.Screen options={BAR} />
      <MoreMinutes
        holding={holding}
        options={options}
        plans={plans}
        packs={packs}
        sells={sells}
        onBuy={(what) => void buy(what)}
        onRestore={() => void restore()}
        state={state}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  centred: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
