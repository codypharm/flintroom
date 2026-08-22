import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  PanelistForm,
  type DomainOffer,
  type VoiceOffer,
} from '../../components/modules/PanelistForm';
import {
  NotYourPlan,
  TitleAlreadyUsed,
  createArchetypesApi,
  type ArchetypeDraft,
  type MyArchetype,
} from '../../lib/api/archetypesApi';
import { createPanelsApi } from '../../lib/api/panelsApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { useGateway } from '../../lib/auth/gateway';
import { SignedOut } from '../../lib/auth/session';
import { color, space, type } from '../../theme/tokens';

/**
 * Writing a panelist, or editing one.
 *
 * **One route, and `new` is the sentinel.** That reads like a hack and is not:
 * a stored name is `custom:{uuid}` and the prefix is enforced by a check
 * constraint (`docs/custom-archetypes.md` §5), so the string `new` can never be
 * a panelist's name. The same guarantee that keeps rows out of the shipped
 * library's namespace keeps this path unambiguous, and two nearly identical
 * route files fetching the same catalogue would be the alternative.
 *
 * The domains and voices come from the catalogue rather than from a constant
 * here. They are the Auditor's routing key and the server refuses one it does
 * not route on, so a hardcoded list is a form offering choices the API rejects.
 */

const archetypes = createArchetypesApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const panels = createPanelsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

/** Never a stored name — the `custom:` prefix is a database constraint. */
const WRITING = 'new';

export default function PanelistRoute() {
  const { recheck } = useGateway();
  const { name } = useLocalSearchParams<{ name: string }>();
  const writing = name === WRITING;

  const [domains, setDomains] = useState<DomainOffer[] | null>(null);
  const [voices, setVoices] = useState<VoiceOffer[]>([]);
  const [existing, setExisting] = useState<MyArchetype | null>(null);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  useEffect(() => {
    let live = true;

    Promise.all([panels.catalogue(), writing ? null : archetypes.mine()])
      .then(([room, mine]) => {
        if (!live) return;
        setDomains(room.domains);
        setVoices(room.voices);
        if (mine) {
          setExisting(mine.find((one) => one.name === name) ?? null);
        }
      })
      .catch((error) => {
        if (!live) return;
        if (error instanceof SignedOut) {
          // The gate owns where a signed-out person lands, not this screen.
          recheck();
          return;
        }
        setRefusal('We could not open the panel editor. Try again in a moment.');
      });

    return () => {
      live = false;
    };
  }, [name, writing, recheck]);

  const save = async (draft: ArchetypeDraft) => {
    setBusy(true);
    setRefusal(null);

    try {
      if (writing) {
        await archetypes.write(draft);
      } else {
        // The answer's name is discarded on purpose here: this screen is
        // leaving, and the setup screen re-reads the roster on focus. What
        // matters is that the *client* never assumes the name survived, which
        // `archetypesApi` holds — a seated panelist comes back replaced.
        await archetypes.revise(name, draft);
      }
      router.back();
    } catch (error) {
      if (error instanceof TitleAlreadyUsed) {
        setRefusal('You already have a panelist with that name.');
      } else if (error instanceof NotYourPlan) {
        // Reachable only if a plan changed between opening the form and saving
        // it. Said plainly rather than as a paywall — §4.5 keeps the upsell out
        // of the way, and this is somebody mid-sentence.
        setRefusal('Writing your own panelist is part of Pro.');
      } else if (error instanceof SignedOut) {
        recheck();
      } else {
        setRefusal('That did not save. Try again in a moment.');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.screen} edges={['bottom']}>
      {/* Empty title, as on every pushed screen: the bar carries the way back
          and the form carries its own heading. */}
      <Stack.Screen
        options={{
          headerShown: true,
          headerTitle: '',
          headerBackTitle: 'Your panel',
          headerTintColor: color.onSurface,
          headerShadowVisible: false,
          headerStyle: { backgroundColor: color.card },
        }}
      />

      {domains === null ? (
        <View style={styles.centred}>
          {refusal === null ? (
            <ActivityIndicator color={color.primary} />
          ) : (
            <Text style={styles.body}>{refusal}</Text>
          )}
        </View>
      ) : (
        <PanelistForm
          domains={domains}
          voices={voices}
          existing={existing}
          busy={busy}
          refusal={refusal}
          onSave={(draft) => void save(draft)}
          onCancel={() => router.back()}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  centred: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.screen,
  },
  body: { ...type.bodyLg, color: color.onSurfaceVariant, textAlign: 'center' },
});
