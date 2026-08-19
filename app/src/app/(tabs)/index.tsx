import * as DocumentPicker from 'expo-document-picker';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PanelSetup } from '../../components/modules/PanelSetup';
import {
  createMaterialsApi,
  type AttachedMaterial,
  type MaterialLimits,
} from '../../lib/api/materialsApi';
import { createPanelsApi, type Catalogue } from '../../lib/api/panelsApi';
import { createBalanceApi, type Held } from '../../lib/api/balanceApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { SignedOut } from '../../lib/auth/session';
import { color, space, type } from '../../theme/tokens';

/**
 * The front door, which is the room being built.
 *
 * Home and setup were two screens and the first was a landing page whose only
 * job was a button to the second. The architect called it what it was. So this
 * is one screen: how the last room went, how much time is available, and then
 * the room you are assembling — a tab you can leave and come back to with the
 * seating still on it.
 *
 * **The tab bar stays**, which is the reason this could be merged at all.
 * Library and Settings are peers reachable from here without unwinding a stack,
 * so nothing is lost by putting the product's actual work on the first tab.
 *
 * **What `design-guide/home/` has that is not here.** A "3-day streak", rejected
 * in `docs/onboarding.md`. A "120 Tokens" counter, retired for minutes, and
 * §4.6 forbids a depleting counter besides. An "Avg. Likelihood 72%" with a bar
 * chart, named in `Product.md:419` as retired. Cards for an "Investment Verdict"
 * screen that no longer exists. Strip all of that and the mockup is a heading
 * and a primary action, which is what this is — except the primary action turned
 * out to be a whole screen's worth of choices, so it is here rather than behind
 * a tap.
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

const balance = createBalanceApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

export default function HomeScreen() {
  // Set once by onboarding, and never by a link, a back gesture or a fresh
  // launch. A string because route params are strings; the comparison is
  // explicit so a truthy `'0'` cannot creep in later.
  const { reveal, archetypes: again, material: sameDeck } = useLocalSearchParams<{
    reveal?: string;
    archetypes?: string;
    material?: string;
  }>();
  const revealing = reveal === '1';
  const [room, setRoom] = useState<Catalogue | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [seated, setSeated] = useState<string[]>([]);

  const [held, setHeld] = useState<Held | null>(null);
  const [material, setMaterial] = useState<AttachedMaterial | null>(null);
  const [limits, setLimits] = useState<MaterialLimits | null>(null);
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);

  /**
   * Run this room again — seated and grounded as it was.
   *
   * From the Library, which carries a past room's archetype names and material
   * id as params. Through this screen rather than straight into a room, because
   * everything a room needs before it opens lives here: the recording
   * disclosure, the microphone request, and every refusal a start can return. A
   * second path that minted a room directly would be a second place for all
   * three to be forgotten, and the first thing forgotten would be the
   * disclosure.
   *
   * Seeded rather than locked. The panel arrives assembled and every control
   * still works — somebody re-running a room usually wants it as it was, and
   * occasionally wants it as it was plus one more voice.
   */
  useEffect(() => {
    if (again) {
      setSeated(again.split(',').filter(Boolean));
    }
  }, [again]);

  useEffect(() => {
    let live = true;

    if (!sameDeck) return;

    materials
      .read(sameDeck)
      .then((deck) => {
        if (live) setMaterial(deck);
      })
      // Silently, and this is the one place that is right. A deck deleted from
      // Settings after the room that used it is ordinary, and the recovery is
      // already on screen: attach one, or run the panel without it. A refusal
      // here would explain a failure the user has no reason to care about.
      .catch(() => undefined);

    return () => {
      live = false;
    };
  }, [sameDeck]);

  useEffect(() => {
    let live = true;

    panels
      .catalogue()
      .then((fetched) => {
        if (!live) return;
        setRoom(fetched);

        // **The reveal, and only on the path that earned it.** `seated` is the
        // room the survey described, derived on the server from the answers, so
        // arriving here straight from onboarding opens on the people somebody
        // placed on their plan — the "here's your room" moment
        // `docs/onboarding.md` promised, delivered without a screen of its own.
        //
        // Every other arrival opens EMPTY. Seating three people somebody never
        // chose does not save them work, it gives them work: measured on a
        // device, the first thing to do with a pre-filled room was unpick it.
        // A default is only a kindness when it is probably right, and outside
        // the survey there is nothing to make it probably right.
        //
        // Still guarded on `chosen.length === 0`: coming back from an attach,
        // the choices on screen are the user's and must never be overwritten.
        if (revealing) {
          setSeated((chosen) => (chosen.length === 0 ? fetched.seated : chosen));
        }
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

  /**
   * How much time is available.
   *
   * `useFocusEffect` rather than a mount effect: a tab is not unmounted when
   * somebody leaves it, and the walk that changes this number is exactly the
   * one that leaves this screen — into a room, and back.
   *
   * Failures are silent, and here that is right. This is not how somebody
   * starts a room; a refusal drawn over the panel picker would break the
   * screen's actual job over a line nobody asked for.
   */
  useFocusEffect(
    useCallback(() => {
      let live = true;

      balance
        .read()
        .then((left) => {
          if (live) setHeld(left);
        })
        .catch(() => undefined);

      return () => {
        live = false;
      };
    }, [])
  );

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
    <SafeAreaView style={styles.screen} edges={['top']}>
      <PanelSetup
        room={room}
        seated={seated}
        onSeatedChange={setSeated}
        material={material}
        limits={limits}
        onAttach={attach}
        onRemoveMaterial={() => void detach()}
        onDifficultyChange={chooseDifficulty}
        header={<Standing held={held} />}
        onStart={() => {
          // The seating and the deck travel as params rather than being read
          // back from the server, because nothing persists them: `seated` is
          // this screen's own state, so a room started from whatever was last
          // saved would seat a panel the person in front of it did not
          // assemble.
          router.push({
            pathname: '/interrogation',
            params: {
              archetypes: seated.join(','),
              material: material?.state === 'ready' ? material.id : '',
            },
          });
        }}
      />
    </SafeAreaView>
  );
}

/**
 * How much time is available, above the room about to spend it.
 *
 * One line. How the last room *went* used to be here too and has moved to its
 * own tab — a run of rooms is the one thing in this product that cannot be said
 * in a sentence, and it was being said in one, above a form.
 *
 * Silent until known. An absent line is a screen still loading; a zero is a
 * claim, and this one is a claim about somebody's money sitting directly above
 * the control that spends it.
 */
function Standing({ held }: { held: Held | null }) {
  if (!held) return null;

  return (
    <View style={styles.standing}>
      {held && (
        <Text style={styles.held}>
          {/* §4.6: framed generously, as what is there rather than what is
              left. `TablePlan` set the register — "15 minutes in the room, on
              us" — and a screen that said "remaining" would be the depleting
              counter that section forbids, one word at a time. */}
          {held.any
            ? `${held.minutes} minutes of interrogation available.`
            : 'No interrogation time available right now.'}
        </Text>
      )}
    </View>
  );
}

function Ground({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
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

  standing: { gap: space.snug, marginBottom: space.section },
  held: { ...type.bodyMd, color: color.onSurfaceVariant },
});
