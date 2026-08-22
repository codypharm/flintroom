import * as DocumentPicker from 'expo-document-picker';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PanelSetup } from '../../components/modules/PanelSetup';
import {
  createMaterialsApi,
  type AttachedMaterial,
  type MaterialLimits,
} from '../../lib/api/materialsApi';
import { createPanelsApi, type Catalogue } from '../../lib/api/panelsApi';
import { createArchetypesApi, type MyArchetype } from '../../lib/api/archetypesApi';
import { railFor } from '../../lib/panel/rail';
import { nameFromDeck } from '../../lib/room/deckName';
import { intendRoom } from '../../lib/room/intent';
import { API_BASE_URL, auth } from '../../lib/auth';
import { useGateway } from '../../lib/auth/gateway';
import { SignedOut } from '../../lib/auth/session';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * The front door, which is the room being built.
 *
 * Home and setup were two screens and the first was a landing page whose only
 * job was a button to the second. The architect called it what it was. So this
 * is one screen: the room you are assembling, on a tab you can leave and come
 * back to with the seating still on it.
 *
 * It carried two other things for a while — how the last room went, and how
 * much time is available — and both have since found somewhere better to live:
 * Progress is a destination of its own, and the balance sits in `TopBar`, where
 * all four tabs read it from one fetch. `PanelSetup` kept an unused `header`
 * slot documenting that arrangement long after nothing filled it; it is gone.
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

const archetypes = createArchetypesApi({
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

export default function HomeScreen() {
  const { recheck } = useGateway();
  // Set once by onboarding, and never by a link, a back gesture or a fresh
  // launch. A string because route params are strings; the comparison is
  // explicit so a truthy `'0'` cannot creep in later.
  const {
    reveal,
    archetypes: again,
    material: sameDeck,
    repeats,
    name: called,
    audience: facing,
    rung,
  } = useLocalSearchParams<{
    reveal?: string;
    archetypes?: string;
    material?: string;
    repeats?: string;
    name?: string;
    audience?: string;
    rung?: string;
  }>();
  const revealing = reveal === '1';
  const [room, setRoom] = useState<Catalogue | null>(null);
  const [mine, setMine] = useState<MyArchetype[]>([]);
  const [refused, setRefused] = useState<string | null>(null);
  // What Try again turns. Home is the one screen a failed read used to park
  // somebody on permanently: the catalogue is fetched on mount, this route
  // stays mounted behind the tab bar, and there was no control to ask again —
  // so a single timeout at launch left the product's primary screen dead until
  // the app was killed. Every other screen in the app already had the way out.
  const [attempt, setAttempt] = useState(0);
  const [seated, setSeated] = useState<string[]>([]);
  // The empty string rather than null, because it is a text input's value and
  // a `TextInput` handed null quietly becomes uncontrolled. Emptiness means
  // unnamed; this screen turns that into the null the server stores.
  const [rehearsalName, setRehearsalName] = useState('');
  // #66. The empty string rather than null for the reason the name above is:
  // it is a `TextInput` value, and one handed null quietly goes uncontrolled.
  // Emptiness means nobody described the room, and this screen is what turns
  // that into the null the server stores.
  const [audience, setAudience] = useState('');

  /**
   * The rung a re-run will actually open at, or null on a fresh argument.
   *
   * Held beside the catalogue's number rather than written into it, because the
   * two answer different questions: `room.difficulty` is the rung this
   * *account* is on, and this is the rung this *rehearsal* is on. The server
   * resolves the same thing at room build — a room that repeats another opens
   * at the pressure that rehearsal last ran at — so showing the account's
   * number here would state one rung and start another.
   *
   * Cleared the moment the user touches the control, which is what makes the
   * override honest on both sides: `choose` stamps `difficulty_chosen_at`, the
   * server then prefers the account, and the screen stops showing the pin.
   */
  const [pinned, setPinned] = useState<number | null>(null);

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

  // Seeded rather than locked, like the seating. Somebody re-running a
  // rehearsal usually wants it called what it is called, and occasionally
  // wants to correct the name — typing over it renames the whole lineage,
  // because the server reads the newest name in a group as the group's.
  useEffect(() => {
    if (called) {
      setRehearsalName(called);
    }
  }, [called]);

  // #66, and seeded on exactly the same terms — except that this one is the
  // room's rather than the rehearsal's, so it comes from the row that was
  // tapped rather than from the newest attempt in the lineage.
  //
  // Prefilled and editable, which is the whole reason the note is stored per
  // room. Somebody re-running the same argument for the same committee should
  // not retype it; somebody taking it to a different room on Friday must be
  // able to see what is in the box and change it before Start. Inheriting it
  // silently would get the second case wrong every time.
  useEffect(() => {
    if (facing) {
      setAudience(facing);
    }
  }, [facing]);

  useEffect(() => {
    // Guarded on a real number rather than on truthiness. The Library sends an
    // empty string for a rehearsal that has never run, and `Number('')` is 0 —
    // a rung off the ladder, which would draw no pill as selected at all.
    const at = Number(rung);
    if (rung && Number.isFinite(at) && at > 0) {
      setPinned(at);
    }
  }, [rung]);

  useEffect(() => {
    let live = true;

    if (!sameDeck) return;

    materials
      .read(sameDeck)
      .then((deck) => {
        if (!live) return;
        setMaterial(deck);
        // Same rule on a re-run: a rehearsal nobody ever named, carrying a
        // deck, gets the deck's name suggested. A lineage that already has one
        // arrives with it in the field, so this leaves it alone.
        setRehearsalName((named) => named || nameFromDeck(deck.filename) || '');
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

  /**
   * The panelists this account wrote, re-read every time this screen is looked
   * at.
   *
   * On focus rather than on mount, because the authoring form is *pushed from
   * here*: somebody writes one, comes back, and the card has to be in the rail.
   * A mount effect would leave them staring at a rail that does not contain the
   * thing they just made.
   *
   * Failures are silent, like the balance above. An account that cannot reach
   * this simply has the eight we ship, which is a smaller room rather than a
   * broken screen.
   */
  useFocusEffect(
    useCallback(() => {
      let live = true;

      archetypes
        .mine()
        .then((written) => {
          if (live) setMine(written);
        })
        .catch(() => undefined);

      return () => {
        live = false;
      };
    }, [])
  );

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
      .catch((error) => {
        if (!live) return;
        if (error instanceof SignedOut) {
          // The gate decides where a signed-out person goes, not this screen —
          // the same call `library.tsx` and `settings.tsx` make. Home used to
          // print "Sign in to assemble a room." and stop there, which left an
          // expired credential sitting on a sentence with no sign-in anywhere
          // near it. `Stack.Protected` moves them the moment the answer
          // changes.
          recheck();
          return;
        }
        setRefused('I could not reach the panel. Try that again in a moment.');
      });

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
    // `attempt` is what Try again turns, and `revealing` is read inside — a
    // param that only ever changes on the way in from onboarding, so listing
    // it costs nothing and stops the reveal reading a stale value. `recheck`
    // is `useCallback([])` on the gate, so it never moves and never re-fetches.
  }, [attempt, revealing, recheck]);

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
      // A name suggested from the deck, and only into an empty field.
      //
      // Optional fields get skipped, so without this most rehearsals stay
      // headed by a date — the heading the name exists to replace. What makes
      // it allowable is that it lands *here*, in an editable field before
      // Start, rather than in a heading afterwards: it is accepted, edited or
      // cleared, so nobody ends up with a label they cannot correct.
      //
      // The functional form is load-bearing. It reads what is on screen now,
      // so a name somebody already typed is never overwritten by attaching a
      // deck — which is the one way this could become the silent labelling it
      // is careful not to be.
      setRehearsalName((named) => named || nameFromDeck(attached.filename) || '');
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
      // The pin stops applying the moment somebody sets a rung themselves, and
      // the server agrees: `choose` stamps `difficulty_chosen_at`, and a choice
      // made after this rehearsal's last attempt beats the inherited pressure.
      // Without this the picker would move under the thumb and then snap back.
      setPinned(null);
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
        <Text style={styles.refusalTitle}>That did not load</Text>
        <Text style={styles.refusalBody}>{refused}</Text>
        <Pressable
          accessibilityRole="button"
          onPress={() => {
            setRefused(null);
            setAttempt((made) => made + 1);
          }}
          style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
        >
          <Text style={styles.retryLabel}>Try again</Text>
        </Pressable>
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
    <SafeAreaView style={styles.screen} edges={[]}>
      <PanelSetup
        // Merged here rather than by the API, because they are two resources
        // with different lifecycles: the catalogue is what we ship, and this is
        // what somebody wrote a minute ago. `railFor` owns the ordering and
        // says why the shipped eight never move.
        room={{
          ...room,
          archetypes: railFor(room.archetypes, mine),
          difficulty: pinned ?? room.difficulty,
        }}
        seated={seated}
        onSeatedChange={setSeated}
        rehearsalName={rehearsalName}
        audience={audience}
        onAudienceChange={setAudience}
        onRehearsalNameChange={setRehearsalName}
        material={material}
        limits={limits}
        onAttach={attach}
        onRemoveMaterial={() => void detach()}
        onDifficultyChange={chooseDifficulty}
        // Pro only, and the row states rather than refuses on any other plan
        // — `AuthorRow` draws the difference. Pushed rather than presented as
        // a modal: writing a panelist is considered work with several fields,
        // not a one-time interruption before entering a room, which is what
        // `disclosure` is and why that one is a sheet.
        onAuthor={
          room?.mayAuthor
            ? () =>
                router.push(
                  // Straight to the form when there is nothing to list. An
                  // empty list with one button in it charges a tap for nothing,
                  // and `AuthorRow` says "Write your own" in exactly that case.
                  mine.length > 0 ? '/panelists' : '/panelists/new'
                )
            : null
        }
        onStart={() => {
          // The seating and the deck are handed over in memory rather than in
          // the URL. Not persisted, for the reason they never were: `seated` is
          // this screen's own state, and a room started from whatever was last
          // saved would seat a panel the person in front of it did not
          // assemble.
          //
          // In memory rather than in params is #76. `/interrogation` mints a
          // metered room on mount, so an address that names the seating is an
          // address that starts a paid room — and `app.json` declares the
          // `flintroom` scheme, which made `flintroom://interrogation` exactly
          // that. The order now exists only here, and `takeIntent` spends it on
          // arrival.
          intendRoom({
            archetypes: seated,
            materialId: material?.state === 'ready' ? material.id : null,
            // The room the Library said to run again, carried through to the
            // start so the server files this one under the same rehearsal.
            //
            // In the address bar rather than in memory, unlike the seating, and
            // the difference is what each one can do if forged. A seating in a
            // URL opens a metered room nobody assembled (#76); a room id in a
            // URL can at worst file a rehearsal under one this account already
            // owns, and only behind a tap on Start. Wrong shelf, not a charge.
            //
            // It survives every change made on this screen after the re-run
            // seeded it, which is deliberate: "the same argument, a harder
            // panel" and "the same argument, a rewritten deck" are both still
            // that argument, and a lineage that broke whenever somebody edited
            // the room would only ever group rooms nobody improved.
            repeats: repeats ?? null,
            // Trimmed here rather than on the server's word alone, so a field
            // somebody tabbed through does not travel as a string of spaces.
            // The server strips it too — this is the same rule stated where
            // the value is produced.
            rehearsalName: rehearsalName.trim() || null,
            // Trimmed to null here rather than sent as spaces. The server
            // does the same on arrival, and agreeing about it means the box
            // somebody tabbed through never becomes a fence around nothing.
            audience: audience.trim() || null,
          });
          router.push('/interrogation');
        }}
      />
    </SafeAreaView>
  );
}

function Ground({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.screen} edges={[]}>
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
    padding: space.screen,
    gap: space.snug,
  },

  /**
   * A read that failed, and the way out of it — the shape `library.tsx`,
   * `prep-sheet/[id].tsx` and the root `Unreachable` all already draw.
   *
   * Home was the exception, and the worst screen to be one on: it is where the
   * product starts, and its catalogue is fetched on mount from a route that
   * never unmounts.
   */
  refusalTitle: { ...type.headlineSm, color: color.onSurface },
  refusalBody: { ...type.bodyLg, color: color.onSurfaceVariant, textAlign: 'center' },

  retry: {
    marginTop: space.snug,
    paddingVertical: space.snug,
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    backgroundColor: color.primary,
  },
  // `onPrimary`, not `surface`. Text on the primary fill has always been
  // `onPrimary`'s job, and reaching for the ground colour only worked while the
  // ground happened to be near-white — which stopped being true when it was
  // darkened to make cards visible.
  retryLabel: { ...type.labelLg, color: color.onPrimary },
  pressed: { opacity: 0.6 },
});
