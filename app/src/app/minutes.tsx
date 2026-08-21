import { Stack, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { MoreMinutes } from '../components/modules/MoreMinutes';
import { createBalanceApi } from '../lib/api/balanceApi';
import {
  createPurchaseApi,
  type Plan,
  type PurchaseOptions,
} from '../lib/api/purchaseApi';
import { API_BASE_URL, auth } from '../lib/auth';
import { useGateway } from '../lib/auth/gateway';
import { SignedOut } from '../lib/auth/session';
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
 * **The store is `unconfiguredStore()` until the console work in
 * `docs/billing-setup.md` is done.** That is not a placeholder in the usual
 * sense — it sells nothing and refuses to buy, so this screen honestly reports
 * a shop that is shut rather than pretending to be one that is open. Swapping
 * in RevenueCat is the remaining half of #90 and touches this line only.
 */

const balance = createBalanceApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const purchases = createPurchaseApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const store: Store = unconfiguredStore();

export default function MoreMinutesRoute() {
  const { recheck } = useGateway();

  const [holding, setHolding] = useState<number | null>(null);
  const [options, setOptions] = useState<PurchaseOptions | null>(null);
  const [sells, setSells] = useState<Sellable[] | null>(null);
  // Independent of the store, and that independence is the fix in #95: what
  // a plan *is* comes from us, so a store that never answers must not blank
  // the plans.
  const [plans, setPlans] = useState<Plan[] | null>(null);
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
      <SafeAreaView style={styles.screen} edges={['top']}>
        <Stack.Screen options={{ headerShown: true, headerTitle: '' }} />
        <View style={styles.centred}>
          <ActivityIndicator color={color.primary} accessibilityLabel="Loading" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={[]}>
      {/*
        The bar carries the back button and nothing else. `_layout.tsx` hides
        headers by default because every screen draws its own title, and the
        two routes that opt back in do it exactly this way — an empty
        `headerTitle` so nothing is drawn twice, and `edges={[]}` because the
        header now owns the top inset.
      */}
      <Stack.Screen options={{ headerShown: true, headerTitle: '' }} />
      <MoreMinutes
        holding={holding}
        options={options}
        plans={plans}
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
