import * as DocumentPicker from 'expo-document-picker';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PanelSetup } from '../components/modules/PanelSetup';
import {
  createMaterialsApi,
  type AttachedMaterial,
  type MaterialLimits,
} from '../lib/api/materialsApi';
import { createPanelsApi, type Catalogue } from '../lib/api/panelsApi';
import { API_BASE_URL, auth } from '../lib/auth';
import { SignedOut } from '../lib/auth/session';
import { color, space, type } from '../theme/tokens';

/**
 * Panel setup, reading the real catalogue.
 *
 * **Not a first-run stub**, unlike `settings.tsx`, and the difference is what
 * this screen is made of. Settings renders facts about an account and can show
 * a plausible empty one; this renders the archetype library, and shipping a
 * hardcoded copy of that is exactly what `/v1/archetypes` exists to prevent —
 * an archetype added on the server would need an app release before anybody
 * could seat it, and the two lists would be free to disagree.
 *
 * So it fetches, and degrades honestly. With no session it says so rather than
 * pretending: sign-in has no screen yet, which is the same wall #41 hits, and
 * this state stops being reachable the moment that lands.
 */

const panels = createPanelsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const materials = createMaterialsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

/**
 * What §3.2 accepts. The native picker filters on these, so somebody never
 * chooses a file the server is about to refuse.
 */
const ACCEPTS = ['application/pdf', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'];

/**
 * How often to ask whether a deck has been read.
 *
 * Extraction is a sweep with a fifteen-second pass, so anything faster is
 * asking a question that cannot have changed. Slow enough to be cheap, quick
 * enough that somebody who attached a one-pager is not left staring.
 */
const ASK_AGAIN_MS = 3000;

export default function SetupRoute() {
  const [room, setRoom] = useState<Catalogue | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [seated, setSeated] = useState<string[]>([]);

  const [material, setMaterial] = useState<AttachedMaterial | null>(null);
  const [limits, setLimits] = useState<MaterialLimits | null>(null);
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let live = true;

    panels
      .catalogue()
      .then((fetched) => {
        if (!live) return;
        setRoom(fetched);
        // **The reveal.** `seated` is the room the survey described, derived on
        // the server from the answers — so on a first run this screen opens
        // showing the people somebody placed on their plan rather than an empty
        // roster. `docs/onboarding.md` promised a "here's your room" moment;
        // this is it, and it arrives without a screen of its own because the
        // reveal and setup are one surface in two postures (2026-08-18).
        //
        // Only when nothing is seated yet. Coming back from an attach, the
        // choices already on screen are the user's and must not be overwritten
        // by what the account defaults to.
        setSeated((chosen) => (chosen.length === 0 ? fetched.seated : chosen));
      })
      .catch((error) =>
        live &&
        setRefused(
          error instanceof SignedOut
            ? 'Sign in to assemble a room.'
            : 'Could not reach the server. Try again in a moment.'
        )
      );

    // Separately, and allowed to fail. The screen states the formats it
    // accepts either way — those are a fact about the product — and only the
    // size and page numbers wait on this. A deck picker that refused to draw
    // because a limits call timed out would be worse than one missing a number.
    materials
      .limits()
      .then((read) => live && setLimits(read))
      // Quiet on purpose, and measured rather than assumed: today this fails
      // with a 502 in any deployment without object storage, because
      // `read_limits` hangs off `IngestionServiceDep` and that dependency
      // builds a store the response never touches. The screen is correct
      // either way — it states the formats and drops the numbers — but the
      // fallback is load-bearing rather than defensive, which is worth knowing
      // before somebody deletes it as dead code.
      .catch(() => undefined);

    return () => {
      live = false;
    };
  }, []);

  // Stopped on unmount as well as on settling, or a screen somebody left keeps
  // asking about a deck nobody is waiting for.
  useEffect(() => () => {
    if (polling.current !== null) clearInterval(polling.current);
  }, []);

  const watch = useCallback((id: string) => {
    if (polling.current !== null) clearInterval(polling.current);

    polling.current = setInterval(async () => {
      try {
        const state = await materials.state(id);
        if (state === 'extracting') return;

        // Terminal either way: `failed` is not retried in place, so there is
        // nothing further to wait for and the row says so.
        if (polling.current !== null) clearInterval(polling.current);
        setMaterial((current) => (current ? { ...current, state } : current));
      } catch {
        // A dropped poll is not a failed deck. The next tick asks again, and
        // clearing the row here would tell somebody their upload vanished
        // because a request timed out.
      }
    }, ASK_AGAIN_MS);
  }, []);

  const attach = useCallback(async () => {
    const picked = await DocumentPicker.getDocumentAsync({
      type: ACCEPTS,
      copyToCacheDirectory: true,
    });
    if (picked.canceled) return;

    const [file] = picked.assets;

    // Refused here rather than after the upload, which is what
    // `/v1/materials/limits` exists for: "so the app can refuse an oversized
    // file locally, before it reads a byte". The server refusal stays the real
    // wall — this only saves somebody watching a hundred megabytes climb before
    // being told it was never going to be accepted.
    if (limits !== null && (file.size ?? 0) > limits.maxUploadBytes) {
      Alert.alert(
        'That deck is too large',
        `Your plan takes up to ${Math.round(limits.maxUploadBytes / (1024 * 1024))} MB.`
      );
      return;
    }

    try {
      const attached = await materials.attach(file, async (uri) =>
        // Straight from the file to the signed URL. Nothing reads the deck into
        // JavaScript memory on the way past — a full-tier PPTX is tens of
        // megabytes and this is a phone.
        await (await fetch(uri)).blob()
      );

      setMaterial(attached);
      if (attached.state === 'extracting') watch(attached.id);
    } catch (error) {
      // Named plainly, and the deck row is left absent rather than shown in a
      // state it never reached. Which refusal it was matters to the person:
      // too large is a plan problem, unreadable is a file problem.
      Alert.alert(
        'That deck was not attached',
        String(error).includes('413')
          ? 'It is larger than your plan allows.'
          : String(error).includes('415')
            ? 'We can read PDF and PowerPoint. That looked like neither.'
            : 'We could not reach the server. Try again in a moment.'
      );
    }
  }, [watch, limits]);

  const detach = useCallback(async () => {
    if (material === null) return;

    // Cleared first. The request is the thing that must not be skipped, but the
    // row is the thing somebody is looking at — leaving a deck on screen for a
    // round trip after they asked for it gone reads as the tap not registering,
    // and the commonest next move is tapping again.
    const going = material;
    setMaterial(null);
    if (polling.current !== null) clearInterval(polling.current);

    try {
      await materials.remove(going.id);
    } catch {
      // Deliberately quiet. A 404 is already success inside `remove`, so this
      // is a network failure against a material the server still holds — which
      // costs nothing until a session is started against it, and no session can
      // be now that nothing on this screen refers to it.
    }
  }, [material]);

  const chooseDifficulty = useCallback(
    (level: number) => {
      // Optimistic, then corrected by what the server stored. The control has
      // to move under the thumb — a rung that waited on a round trip would feel
      // broken — and the server is the authority on what it actually is.
      setRoom((current) => (current ? { ...current, difficulty: level } : current));
      panels
        .chooseDifficulty(level)
        .then((stored) =>
          setRoom((current) => (current ? { ...current, difficulty: stored } : current))
        )
        .catch(() => undefined);
    },
    []
  );

  if (refused !== null) {
    return (
      <Ground>
        <Text style={styles.refused}>{refused}</Text>
      </Ground>
    );
  }

  if (room === null) {
    return (
      <Ground>
        <ActivityIndicator color={color.primary} accessibilityLabel="Loading the room" />
      </Ground>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <PanelSetup
        room={room}
        seated={seated}
        onSeatedChange={setSeated}
        material={material}
        limits={limits}
        onAttach={attach}
        onRemoveMaterial={() => void detach()}
        onDifficultyChange={chooseDifficulty}
        onStart={() => undefined}
      />
    </SafeAreaView>
  );
}

function Ground({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <View style={styles.centred}>{children}</View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },

  centred: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.screen,
  },

  refused: { ...type.bodyMd, color: color.onSurfaceVariant, textAlign: 'center' },
});
