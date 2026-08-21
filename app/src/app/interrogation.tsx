import * as SecureStore from 'expo-secure-store';
import { router } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, StyleSheet, Text, View } from 'react-native';
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
import { Refused } from '../lib/api/refused';
import type { Attending, Ending } from '../lib/voice/connection';
import type { PanelLine } from '../lib/voice/connection';
import { color, space, type } from '../theme/tokens';

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
  const [attending, setAttending] = useState<{ state: Attending; since: number }>({
    state: 'listening',
    since: Date.now(),
  });
  const [heard, setHeard] = useState<Hearing>('silent');
  const [volume, setVolume] = useState(0);
  const [phase, setPhase] = useState<'opening' | 'live' | 'ending'>('opening');
  const [refusal, setRefusal] = useState<string | null>(null);
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
        setRefusal('The room dropped out. Those minutes are back on your account.');
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

    const tick = setInterval(
      () => setElapsed(Math.floor((Date.now() - opened.current) / 1000)),
      1000
    );
    setElapsed(0);

    return () => clearInterval(tick);
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
            {refusal}
          </Text>
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
        loudness={volume}
        phase={phase}
        elapsed={elapsed}
        onEnd={end}
      />
    </SafeAreaView>
  );
}

/**
 * Why the room did not open, in the presenter's terms.
 *
 * Split by whose problem it is. A denied microphone is theirs to fix and
 * Settings is where; `unavailable` is ours, and sending them to a Settings page
 * to grant a permission they never refused would waste their time and their
 * trust. Anything else is a room that never started, which means nothing was
 * billed — worth saying, because somebody who just tried to spend minutes will
 * assume otherwise.
 */
function refusalFor(thrown: unknown): string {
  // The server's own diagnosis first, because it is the only one that knows
  // WHY. A device reported "the room would not open, nothing was charged" while
  // the API was saying `no_minutes_remaining` — the catch-all below, standing in
  // for an answer somebody could have acted on.
  if (thrown instanceof Refused) {
    return REFUSED[thrown.code] ?? thrown.message;
  }

  const why = thrown instanceof Error ? thrown.message : '';

  if (why === 'denied') {
    return 'Flintroom needs the microphone to hold a room. Turn it on in Settings, then try again.';
  }

  if (why === 'unavailable') {
    return 'We could not reach the microphone. Try again in a moment.';
  }

  return 'The room would not open. Nothing was charged.';
}

/**
 * Why the server would not open a room, in the presenter's terms.
 *
 * Copy here rather than on the server, the rule `Product.md` §9 sets: the API
 * states the fact, the client writes the sentence. The server's own message is
 * still the fallback for a code this build predates, so a refusal added later
 * says something true rather than nothing — the same shape `debrief/refusals.ts`
 * already uses.
 */
const REFUSED: Record<string, string> = {
  // **§4.6 governs this sentence.** Never a depleting counter, and framed
  // generously — so it says what is true (the minutes are spent) and what is
  // still theirs (everything already recorded), and it does not scold. The room
  // costs money to hold; running out is the product working, not a failure.
  //
  // It cannot yet offer a way to buy more: RevenueCat is unwired (#32). Saying
  // so plainly beats a button that does nothing, and beats implying they did
  // something wrong.
  no_minutes_remaining:
    'You have used your interrogation minutes. Your rooms and debriefs are all still here.',
  // One live room at a time, which is a real constraint rather than a fault —
  // and the recovery is to finish or leave the other one.
  active_session_exists:
    'A room is already open on this account. Finish that one, then start another.',
};

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
});
