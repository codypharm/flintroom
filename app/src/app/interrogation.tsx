import * as SecureStore from 'expo-secure-store';
import { router } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import { AudioContext, AudioManager, AudioRecorder } from 'react-native-audio-api';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView } from 'react-native-safe-area-context';

import { enterHandsFree, leaveHandsFree } from '../../modules/audio-routing';
import {
  InterrogationRoom,
  type Seat,
} from '../components/modules/InterrogationRoom';
import {
  HEARD_WINDOW,
  hearing,
  loudness,
  steadied,
  type Hearing,
  type Steadied,
} from '../lib/audio/hearing';
import { ensureMicrophone } from '../lib/audio/permission';
import { refusalFor, type Refusal } from '../lib/room/refusals';
import { createAccountApi } from '../lib/api/accountApi';
import { RecordingDisclosure } from '../components/modules/RecordingDisclosure';
import { createDisclosureRecord } from '../lib/consent/disclosure';
import { enterRoom } from '../lib/consent/entry';
import { createPanelsApi } from '../lib/api/panelsApi';
import { closeRoom } from '../lib/room/closing';
import { takeIntent } from '../lib/room/intent';
import { createSessionsApi, type StartedRoom } from '../lib/api/sessionsApi';
import { API_BASE_URL, auth } from '../lib/auth';
import { joinRoom, type Room } from '../lib/voice/room';
import type { Attending, Ending, RoomTemperature , PanelLine } from '../lib/voice/connection';
import { color, radius, space, type } from '../theme/tokens';

/**
 * The live interrogation, as a route.
 *
 * Owns the three things `InterrogationRoom` cannot render: the session, the
 * socket, and the hardware. The surface above is pure props precisely so that
 * none of this leaks into it.
 *
 * **It replaced `room.tsx`,** which was an instrument with a token field, a
 * `fetch` inline in the screen and scaffold styling. Its own header said it
 * would leave when sign-in landed; sign-in landed in #19 and #70. Keeping a
 * second door into a metered room would also have meant keeping a second place
 * where `POST /v1/sessions` is called.
 */

const sessions = createSessionsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const panels = createPanelsApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

const account = createAccountApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

/** Which accounts have seen the sheet on this install. Keychain, not a new store. */
const told = createDisclosureRecord(SecureStore);

/**
 * What the sheet says when the real window cannot be read.
 *
 * The free tier's, which is the shortest — so a failed request can only ever
 * understate how long a room is kept, never overstate it. A disclosure that
 * promised less than the truth is a bug; one that promised more is a broken
 * promise nobody can prove was made.
 */
const SHORTEST_WINDOW = 30;

/** Scoped, so releasing ours cannot cancel somebody else's hold. */
const KEEP_AWAKE = 'flintroom-interrogation';

/**
 * The beat between the room ending and the debrief opening.
 *
 * Not dead time: the last thing the panel said stays on screen while the light
 * comes up, so the pause holds the question you are still chewing on. Long
 * enough to land, short enough that it does not stack badly in front of the
 * debrief's own "Reading the room".
 *
 * Deliberately **not** used to prefetch the debrief. `debrief.py` treats two
 * openers racing as "a wasted call rather than a fault", so warming it here
 * would double a reasoning-model call on every single session.
 */
const BEAT_MS = 2500;

export default function InterrogationScreen() {
  const [panel, setPanel] = useState<Seat[]>([]);
  const [speaking, setSpeaking] = useState<string | null>(null);
  const [line, setLine] = useState<PanelLine | null>(null);
  const [floor, setFloor] = useState<'panel' | 'yours'>('yours');
  /**
   * What the room says it is doing, and when it said so.
   *
   * The clock is kept beside the value because `working` earns the right to
   * say how long it has been working — a hang stated as a number is a fact
   * somebody can act on, where a hang stated as nothing is the silence this
   * whole thing replaces.
   */
  // A lazy initialiser, because `Date.now()` in the argument position runs on
  // every render — `react-hooks/purity` flags it, and it is right: the value is
  // thrown away every time after the first, so the reads are pure waste on the
  // one screen that cannot drop a frame. Wrapped, it runs once.
  const [attending, setAttending] = useState<{ state: Attending; since: number }>(() => ({
    state: 'listening',
    since: Date.now(),
  }));
  /**
   * How the panel is receiving the argument — #74.
   *
   * The resting band rather than null, because there is no fourth "unknown"
   * value and there does not need to be: a panel opens unconvinced, so the
   * ground the room opens on is already true. Held flat, unlike `attending`,
   * because nothing on this screen cares how long a band has been held.
   */
  const [temperature, setTemperature] = useState<RoomTemperature>('skeptical');
  // #75. Who the room said is coming, until they arrive. Null most of the time
  // — including for every utterance the server had nothing decided early for.
  const [challenging, setChallenging] = useState<string | null>(null);
  const [heard, setHeard] = useState<Hearing>('silent');
  const [volume, setVolume] = useState(0);
  const [phase, setPhase] = useState<'opening' | 'live' | 'ending'>('opening');
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);
  /** The sheet, and the resolver that lets `enterRoom` carry on once it is read. */
  const [disclosing, setDisclosing] = useState<{
    retentionDays: number;
    continue: () => void;
  } | null>(null);

  const room = useRef<Room | null>(null);
  const context = useRef<AudioContext | null>(null);
  const recorder = useRef<AudioRecorder | null>(null);
  const session = useRef<string | null>(null);
  const levels = useRef<number[]>([]);
  /**
   * What the indicator is saying, and how hard the room is arguing with it.
   *
   * A ref rather than state because it changes fifty times a second and only
   * occasionally means anything — `steadied` is what turns that into the handful
   * of transitions worth re-rendering for. Reported from a device as the warning
   * "jerking", which is what a boundary signal looks like when every reading is
   * allowed to change the screen.
   */
  const heardSteadily = useRef<Steadied>({ shown: 'silent', agreeing: 0 });
  const opened = useRef(0);
  /** Guards the hand-off: a close and an End both arrive, and only one may navigate. */
  const leaving = useRef(false);

  const release = useCallback(async () => {
    await deactivateKeepAwake(KEEP_AWAKE).catch(() => undefined);
    recorder.current?.stop();
    recorder.current = null;
    await context.current?.close().catch(() => undefined);
    context.current = null;
    await leaveHandsFree();
  }, []);

  /**
   * The way out, however it was reached.
   *
   * `ending` first, so the beat renders with the last line still on it, and the
   * navigation after. `replace` rather than `push`: the room is settled and
   * cannot be returned to, and leaving it on the stack would put a dark screen
   * with a live microphone behind a back gesture.
   */
  const finish = useCallback(
    (why: Ending) => {
      if (leaving.current) {
        return;
      }
      leaving.current = true;

      setPhase('ending');
      if (why === 'upstream_failure') {
        // Said, because it is not their fault and the debrief they are about to
        // open will be short. The minutes were returned before the socket
        // closed; nothing here has to reconcile anything.
        setRefusal({
          said: 'The room dropped out. Those minutes are back on your account.',
          // Nothing to sell: the minutes were returned before the socket
          // closed, so they have exactly what they started with.
          buying: false,
        });
      }

      void release();

      const settled = session.current;
      setTimeout(() => {
        if (settled === null) {
          router.replace('/');
          return;
        }
        router.replace(`/debrief/${settled}`);
      }, BEAT_MS);
    },
    [release]
  );

  useEffect(() => {
    let alive = true;

    // Alongside the room rather than before it. Titles are only needed once a
    // panelist speaks, which is seconds away at best, and blocking the open on
    // a catalogue fetch would put a request on the one path where latency is
    // the product (Open Risk #3).
    panels
      .catalogue()
      .then((found) => {
        if (!alive) return;
        setPanel((seated) =>
          seated.map((seat) => ({
            ...seat,
            title:
              found.archetypes.find((one) => one.name === seat.name)?.title ?? seat.title,
          }))
        );
      })
      .catch(() => undefined);

    void open();

    async function open() {
      // A box rather than a bare `let`: the assignment happens inside a
      // callback, and TypeScript's flow analysis cannot see across one — it
      // would narrow a plain local to `null` at every use below.
      const minted: { room: StartedRoom | null } = { room: null };

      try {
        // The order here is `enterRoom`'s, and it is the reason that module
        // exists rather than these four steps living in a screen: the tap
        // before anything at all, because a sheet and a permission prompt are
        // things that should not happen to somebody who asked for nothing; the
        // sheet before the system prompt, because it is the prompt's reason;
        // the microphone before the session, because a ticket lives seconds and
        // minting first leaves somebody who tapped "don't allow" holding a dead
        // one against a live room; and the sheet remembered whatever happens
        // next, because they were told.
        const entered = await enterRoom({
          userId: await auth.userId(),
          // #76. Handed in rather than read here, so the rule that nothing
          // happens for an unasked-for room lives beside the rest of the
          // sequence in `enterRoom` — where it is tested, and where a screen
          // cannot reorder it in front of the sheet or the permission prompt.
          order: takeIntent,
          record: told,
          retentionDays: () => account.recordingWindow().catch(() => SHORTEST_WINDOW),
          disclose: (days) =>
            new Promise<void>((shown) => {
              setDisclosing({ retentionDays: days, continue: shown });
            }),
          ensureMicrophone: () => ensureMicrophone(AudioManager),
          // The real one. Handing `enterRoom` a no-op and starting the session
          // below would keep today's order by luck rather than by structure —
          // and the whole reason that module exists is that a screen is where
          // ordering goes to be accidentally rearranged.
          mint: async (order) => {
            minted.room = await sessions.start({
              archetypes: order.archetypes,
              materialIds: order.materialId === null ? [] : [order.materialId],
              // Which room this is a re-run of, when it is one. The server
              // files it under the same rehearsal, so the progress screen can
              // show a run of attempts at one argument as a run.
              repeats: order.repeats,
              rehearsalName: order.rehearsalName,
              // #66. The presenter's own words about the room they are about
              // to face. The server fences them before the composer sees
              // them, and the panel never says any of it back.
              audience: order.audience,
            });
          },
        });

        if (!alive) return;
        setDisclosing(null);

        if (entered === 'unasked') {
          // Not a refusal, so not a refusal screen. Nobody tapped anything —
          // a link on the `flintroom` scheme, a cold start onto this route, or
          // a remount after `Stack.Protected` re-evaluated its guard. The
          // answer is where rooms are started, silently: there is nothing to
          // report to somebody who has not done anything wrong.
          router.replace('/');
          return;
        }

        if (entered !== 'entered' || minted.room === null) {
          throw new Error(entered);
        }

        // Both halves of hands-free, and both load-bearing. `voiceChat` engages
        // Apple's voice processing, which is what cancels the panel out of the
        // microphone; `defaultToSpeaker` stops `playAndRecord` routing to the
        // earpiece, which would be a phone held to the ear rather than a room.
        AudioManager.setAudioSessionOptions({
          iosCategory: 'playAndRecord',
          iosMode: 'voiceChat',
          iosOptions: ['defaultToSpeaker', 'allowBluetoothHFP'],
        });
        await enterHandsFree();

        // Hands-free means nobody touches the screen for twelve minutes, so the
        // display times out, the app backgrounds and the socket dies — which the
        // server reads as hanging up. Held only while a room is open.
        await activateKeepAwakeAsync(KEEP_AWAKE);

        const capture = new AudioRecorder();
        recorder.current = capture;
        const playback = new AudioContext();
        context.current = playback;

        // A context that is not running renders nothing, and renders it
        // silently: frames enqueue without complaint and no sound arrives,
        // which is indistinguishable from a panel that never spoke.
        if (playback.state !== 'running') {
          await playback.resume();
        }

        const started = minted.room;
        session.current = started.id;
        setPanel(started.archetypes.map((name) => ({ name, title: pretty(name) })));

        room.current = await joinRoom({
          url: `${API_BASE_URL.replace(/^http/, 'ws')}/v1/sessions/${started.id}/stream`,
          ticket: started.streamTicket,
          context: playback,
          recorder: capture,
          onTranscript: (said) => {
            setLine(said);
            setSpeaking(said.speaker);
            setFloor('panel');
            // #75. They have arrived, so the announcement is spent. Cleared on
            // the caption rather than on `challenging` changing, because this
            // is the moment the thing it promised actually happened — and a
            // tray still coming up under a voice that is already speaking
            // would be the screen a beat behind the room.
            setChallenging(null);
          },
          // Both halves have happened: the room sent its last frame and the
          // phone has played it. `joinRoom` is what waits for the second —
          // acting on the first alone put the speaker down while their voice
          // was still coming out of the loudspeaker.
          // Reported, never inferred: only the server sees a final arrive, so
          // a timer here would be racing the network and would be wrong in
          // exactly the case that matters.
          onAttending: (state) =>
            setAttending((held) =>
              held.state === state ? held : { state, since: Date.now() }
            ),
          // #74. Straight into state: the server sends it on transitions and
          // repeats it on every heartbeat, so a dropped message costs one beat
          // rather than the rest of the room, and there is nothing here to
          // de-duplicate that the sender has not already.
          onTemperature: setTemperature,
          // #75. A moment rather than a state, so it is never repeated on the
          // heartbeat and is cleared by the caption that follows it. A dropped
          // frame costs one tray's development and nothing else — which is why
          // there is no timeout here forcing it back to null: the caption is
          // the only thing that can honestly end it, and a turn that never
          // produced one was a turn nobody heard either.
          onChallenging: setChallenging,
          onTurnFinished: () => {
            setSpeaking(null);
            setFloor('yours');
          },
          // Cut off mid-question. No `turn_finished` follows a barge-in, so
          // without this the interrupted panelist stays lit for the rest of
          // the room.
          onDiscardPlayback: () => {
            setSpeaking(null);
            setFloor('yours');
          },
          onLevel: (dbfs) => {
            levels.current = [...levels.current, dbfs].slice(-HEARD_WINDOW);
            // The bar tracks every buffer — it is an amplitude and lagging it
            // would make it feel disconnected from the voice. The *warning*
            // does not: it interrupts somebody mid-sentence, so it may only
            // change once the room has said the same thing for a while.
            heardSteadily.current = steadied(
              heardSteadily.current,
              hearing(levels.current)
            );
            setHeard(heardSteadily.current.shown);
            setVolume(loudness(levels.current));
          },
          onEnding: finish,
        });

        // After `joinRoom`, never before: it registers `onAudioReady` as it
        // builds the uplink, and a recorder started first delivers into a
        // callback nobody has registered — which fails as silence, not an error.
        capture.start();
        if (!alive) return;
        setPhase('live');
        // From here rather than from the tap. The clock should measure the
        // room, and everything before this — the sheet, the permission dialog,
        // minting, the socket — is not the room and is not metered either.
        opened.current = Date.now();
      } catch (thrown) {
        if (!alive) return;
        setRefusal(refusalFor(thrown));
        await release();
      }
    }

    return () => {
      alive = false;
      room.current?.leave();
      room.current = null;
      void release();
    };
    // Once, on mount. The params cannot change without a fresh route, and
    // re-running this would open a second metered room.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * The clock, once a second, and only while the room is open.
   *
   * A wall-clock difference rather than an accumulating count: a timer that
   * added one per tick drifts, and drifts most on a backgrounded app — which is
   * exactly what a phone lying on a desk for twelve minutes is closest to.
   */
  useEffect(() => {
    if (phase !== 'live') {
      return;
    }

    // Zero first, and scheduled rather than written straight into the effect
    // body. `react-hooks/set-state-in-effect` objects to the synchronous write,
    // and the fix is also the more honest one: this is the clock *starting*, so
    // it belongs on the same footing as the ticks that follow it rather than
    // being a render the room pays for before the first second exists.
    //
    // A whole second of latency would be visible here — the clock is on screen
    // — so it is a task rather than a timeout: the reset lands before the first
    // tick either way, and `elapsed` was already null until this ran.
    const start = setTimeout(() => setElapsed(0), 0);
    const tick = setInterval(
      () => setElapsed(Math.floor((Date.now() - opened.current) / 1000)),
      1000
    );

    return () => {
      clearTimeout(start);
      clearInterval(tick);
    };
  }, [phase]);

  const end = useCallback(() => {
    const settled = session.current;

    // **The intent first, then the socket — and now it actually is.** This said
    // the same thing and did not do it: `void sessions.end(...)` does not wait,
    // so the `leave()` on the next line raced a network round trip and won
    // every time. Every room in the dev database had settled as
    // `client_disconnect`, five of five (#82).
    //
    // `closeRoom` owns the order and is tested on it. The screen moves on
    // immediately either way — `finish` is not awaited, because a presenter who
    // has tapped End should not watch a spinner while we file the paperwork.
    if (settled === null) {
      room.current?.leave();
      finish('ended');
      return;
    }

    void closeRoom({
      tell: () => sessions.end(settled),
      hangUp: () => room.current?.leave(),
    });
    finish('ended');
  }, [finish]);

  const sheet = disclosing !== null && (
    <Modal
      visible
      animationType="slide"
      presentationStyle="pageSheet"
      // Nothing to dismiss to. The room has not opened, and a sheet that could
      // be swiped away would leave `enterRoom` waiting on a promise nobody is
      // going to resolve, with the microphone unasked and the screen dark.
      onRequestClose={disclosing.continue}
    >
      <RecordingDisclosure
        retentionDays={disclosing.retentionDays}
        onContinue={disclosing.continue}
      />
    </Modal>
  );

  if (refusal !== null && phase !== 'ending') {
    return (
      <SafeAreaView style={styles.dark} edges={['top', 'bottom']}>
        <StatusBar style="light" />
        {sheet}
        <View style={styles.refused}>
          <Text style={styles.refusalText} accessibilityRole="alert">
            {refusal.said}
          </Text>
          {/*
            The way out, and only where money is actually the answer.

            `CLAUDE.md` forbids interrupting a *live* session with a paywall.
            This is a room that never opened — nothing was charged, nothing was
            cut off — so the offer is a recovery rather than an interruption,
            and §4.5 keeps it out of the way of a rehearsal by never appearing
            during one.

            `refusalFor` decides, and it says false for the daily ceiling even
            though that reads like running out: no purchase lifts a cost
            circuit breaker, so an offer there charges for a room that will
            refuse again immediately.

            `replace` rather than `push`. This route is spent — its intent was
            taken on mount and the room it named was never minted — so leaving
            it on the stack gives the back gesture somewhere useless to go.
          */}
          {refusal.buying && (
            <Pressable
              onPress={() => router.replace('/minutes')}
              accessibilityRole="button"
              style={({ pressed }) => [styles.getMore, pressed && styles.fading]}
            >
              <Text style={styles.getMoreText}>Get more time</Text>
            </Pressable>
          )}
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.dark} edges={['top', 'bottom']}>
      {/* Light glyphs, overriding the root's `dark`. This is the one screen in
          the app that is not on the warm off-white. */}
      <StatusBar style="light" />
      {sheet}
      <InterrogationRoom
        panel={panel}
        speaking={speaking}
        line={line}
        floor={floor}
        hearing={heard}
        attending={attending}
        temperature={temperature}
        challenging={challenging}
        loudness={volume}
        phase={phase}
        elapsed={elapsed}
        onEnd={end}
      />
    </SafeAreaView>
  );
}


/** Route params arrive as strings; an absent one is an empty list, not `['']`. */
/**
 * A readable stand-in until the catalogue lands.
 *
 * `technical_skeptic` on screen would be the database showing through, and the
 * catalogue request is in flight — this only ever renders for the second or so
 * before it answers, and only if a panelist speaks that fast.
 */
function pretty(name: string): string {
  return name
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

const styles = StyleSheet.create({
  dark: { flex: 1, backgroundColor: color.roomGround },
  refused: { flex: 1, justifyContent: 'center', padding: space.screen },
  refusalText: { ...type.bodyLg, color: color.onRoom, textAlign: 'center' },

  // On the room's own dark ground, so it reads as a control on this screen
  // rather than a light-mode button pasted onto it.
  getMore: {
    marginTop: space.loose,
    paddingVertical: space.snug,
    paddingHorizontal: space.loose,
    borderRadius: radius.pill,
    backgroundColor: color.primary,
    minHeight: 44,
    justifyContent: 'center',
  },
  getMoreText: { ...type.labelLg, color: color.onPrimary, textAlign: 'center' },
  fading: { opacity: 0.7 },
});
