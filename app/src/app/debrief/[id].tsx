import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { AudioContext, AudioManager, AudioRecorder } from 'react-native-audio-api';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  Debrief,
  type Exchange,
  type Listening,
} from '../../components/modules/Debrief';
import { createDebriefApi, type Pressed, type WeakAnswer } from '../../lib/api/debriefApi';
import { collectClip, type Clip } from '../../lib/audio/clip';
import { API_BASE_URL, auth } from '../../lib/auth';
import { SignedOut } from '../../lib/auth/session';
import { refusedRoom, refusedTurn, type RoomRefusal } from '../../lib/debrief/refusals';
import { createCoachVoice, type CoachVoice } from '../../lib/debrief/voice';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * The debrief, on a room that has settled.
 *
 * This route owns the two things `Debrief` deliberately does not: the
 * microphone, and the requests. The sheet is handed state and callbacks and has
 * no idea a network exists, which is what makes its product rules — no verdict,
 * no meter, no re-pooled blame — testable without a server.
 *
 * **Unmetered, structurally.** Nothing in this file touches a ticket, a balance
 * or the ledger, because §4.1 meters live interrogation and nothing after it.
 * There is no code path from here to money, which is the metering boundary
 * being a property of the architecture rather than something to remember.
 *
 * Reached from the room when it ends. That is §4.1's own sequence — the panel
 * finishes, the session settles, the debrief opens — and it needs no list of
 * past rooms, which does not exist yet.
 */

const debriefs = createDebriefApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

/**
 * What the recorder is asked for. It answers with what the hardware chose, and
 * `collectClip` records whichever rate actually arrives — #18 is the whole
 * reason that is not assumed here.
 */
const CAPTURE = { sampleRate: 16_000, bufferLength: 1600, channelCount: 1 };

export default function DebriefRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();

  const [answers, setAnswers] = useState<WeakAnswer[] | null>(null);
  const [pressed, setPressed] = useState<Pressed>(null);
  const [refusal, setRefusal] = useState<RoomRefusal | null>(null);
  const [thread, setThread] = useState<Exchange[]>([]);
  const [attempts, setAttempts] = useState<Record<number, Exchange[]>>({});
  const [listening, setListening] = useState<Listening>({ state: 'idle' });
  const [turnRefusal, setTurnRefusal] = useState<string | null>(null);

  const recorder = useRef<AudioRecorder | null>(null);
  const voice = useRef<CoachVoice | null>(null);
  const speaker = useRef<AudioContext | null>(null);
  const clip = useRef<Clip | null>(null);
  const target = useRef<number | null>(null);

  /**
   * Read the room, and be callable a second time.
   *
   * A one-shot effect was enough while every refusal was permanent. It is not
   * now: `provider_unavailable` means the reading failed and the room is
   * intact, so the recovery is this exact call again — see `refusals.ts`.
   *
   * `attempt` is what re-runs the effect. A ref would not: the retry has to
   * clear the refusal and redraw, and only state does that.
   */
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;

    debriefs
      .read(id)
      .then((debrief) => {
        if (!live) return;
        setAnswers(debrief.weakAnswers);
        setPressed(debrief.pressed);
      })
      .catch((error) => {
        if (!live) return;
        if (error instanceof SignedOut) {
          router.replace('/');
          return;
        }
        setRefusal(refusedRoom(error));
      });

    return () => {
      live = false;
    };
  }, [id, attempt]);

  /**
   * Stop the hardware, whatever ended the turn.
   *
   * Called from the happy path and from every failure, because a recorder left
   * running holds the microphone open after the screen has moved on — and on
   * iOS that is a red status bar over an app that is doing nothing.
   */
  const release = useCallback(() => {
    recorder.current?.stop();
    recorder.current?.clearOnAudioReady();
    recorder.current = null;
  }, []);

  useEffect(() => release, [release]);

  /**
   * The coach, out loud — made on first use and kept for the route's life.
   *
   * Lazy rather than made on mount, because a context is a native object and
   * this screen is reachable on a room where nothing is ever said to the coach.
   * Resumed explicitly: a suspended context renders silence *without
   * complaining*, which is indistinguishable from a coach that never spoke —
   * the same trap `interrogation.tsx` records for the room.
   */
  const speak = useCallback(async (speech: string) => {
    if (!voice.current) {
      const context = new AudioContext();
      speaker.current = context;
      voice.current = createCoachVoice({ context });
    }

    if (speaker.current && speaker.current.state !== 'running') {
      await speaker.current.resume();
    }

    voice.current.play(speech);
  }, []);

  // The route is popped and the coach must not follow. `stop` rather than
  // `silence`: nothing after this screen should hear it.
  useEffect(
    () => () => {
      voice.current?.stop();
      voice.current = null;
      void speaker.current?.close();
      speaker.current = null;
    },
    []
  );

  const finish = useCallback(async () => {
    const gathering = clip.current;
    const at = target.current;
    if (!gathering) return;

    release();
    clip.current = null;
    setListening({ state: 'sending', at });

    try {
      const spoken = gathering.finish();
      const turn =
        at === null
          ? await debriefs.say(id, spoken)
          : await debriefs.spar(id, at, spoken);

      const exchange: Exchange = {
        heard: turn.heard,
        said: turn.text,
        speech: turn.speech,
      };

      if (at === null) {
        setThread((so_far) => [...so_far, exchange]);
      } else {
        setAttempts((so_far) => ({
          ...so_far,
          [at]: [...(so_far[at] ?? []), exchange],
        }));
      }

      // Spoken without being asked, which is what makes this a conversation
      // rather than a chat log — you do not tap a button to hear somebody
      // answer you. Drawn first, so the caption is on screen before the voice
      // starts and stays there for anybody who cannot hear it.
      void speak(turn.speech);
    } catch (error) {
      if (error instanceof SignedOut) {
        router.replace('/');
        return;
      }
      setTurnRefusal(refusedTurn(error));
    } finally {
      setListening({ state: 'idle' });
    }
  }, [id, release, speak]);

  const start = useCallback(
    async (at: number | null) => {
      setTurnRefusal(null);
      // Before the microphone, not after. The coach comes out of the same phone
      // that is about to record, so a reply still playing would be captured,
      // transcribed, and sent back as though the presenter had said it — the
      // coach answering itself on a screen whose whole grounding rule is that a
      // turn is about the room.
      voice.current?.silence();

      try {
        const permission = await AudioManager.requestRecordingPermissions();
        if (permission !== 'Granted') {
          setTurnRefusal('I need the microphone to hear you. Turn it on in Settings.');
          return;
        }

        AudioManager.setAudioSessionOptions({
          // `default` mode rather than the room's `voiceChat`. `voiceChat`
          // engages Apple's duplex voice processing, which exists to cancel the
          // panel out of the microphone — and here nothing is playing while the
          // user speaks, so it would only apply call-tuned processing to a
          // clip that is about to be transcribed.
          iosCategory: 'playAndRecord',
          iosMode: 'default',
          iosOptions: ['defaultToSpeaker'],
        });

        const gathering = collectClip();
        clip.current = gathering;
        target.current = at;

        const capture = new AudioRecorder();
        recorder.current = capture;

        capture.onAudioReady(CAPTURE, (event) => {
          // Trimmed to `numFrames`. The buffer is a fixed-size scratch the
          // recorder reuses, so the tail of a short final callback still holds
          // whatever was in it last — appended untrimmed, that is a repeated
          // fragment of the user's own voice on the end of every clip.
          gathering.push(
            event.buffer.getChannelData(0).subarray(0, event.numFrames),
            event.buffer.sampleRate
          );

          setListening((was) =>
            was.state === 'listening'
              ? { state: 'listening', seconds: gathering.seconds(), at }
              : was
          );

          // The ceiling reached mid-sentence is still better than the app being
          // killed. Sending what there is keeps the turn rather than discarding
          // it, and the sentence says which happened.
          if (gathering.full() && clip.current) {
            setTurnRefusal('That is as long as I can listen in one go — sending what I have.');
            void finish();
          }
        });

        await capture.start();
        setListening({ state: 'listening', seconds: 0, at });
      } catch {
        release();
        setListening({ state: 'idle' });
        setTurnRefusal('I could not start the microphone. Try that again.');
      }
    },
    [release, finish]
  );

  if (refusal) {
    return (
      <Refusal
        refusal={refusal}
        onRetry={() => {
          // The refusal has to clear as well as the attempt advancing, or the
          // screen stays on the failure while the request it triggered
          // succeeds behind it.
          setRefusal(null);
          setAttempt((made) => made + 1);
        }}
      />
    );
  }

  if (!answers) {
    return (
      <View style={styles.waiting}>
        <ActivityIndicator color={color.primary} />
        <Text style={styles.waitingLabel}>Reading the room</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.screen} edges={['top', 'bottom']}>
      <Debrief
        answers={answers}
        pressed={pressed}
        thread={thread}
        attempts={attempts}
        listening={listening}
        refusal={turnRefusal}
        onTalk={(at) => void start(at)}
        onStop={() => void finish()}
        onReplay={(speech) => void speak(speech)}
        onPrepSheet={() => router.push('/prep-sheet')}
      />
    </SafeAreaView>
  );
}

/**
 * A room that cannot be debriefed, said plainly.
 *
 * Deliberately not a toast over an empty sheet. All three of these mean there
 * is nothing to work on, and drawing the furniture of a debrief around nothing
 * would read as a screen that failed to load rather than as an answer.
 */
function Refusal({
  refusal,
  onRetry,
}: {
  refusal: RoomRefusal;
  onRetry: () => void;
}) {
  return (
    <SafeAreaView style={[styles.screen, styles.refused]} edges={['top', 'bottom']}>
      <Text style={styles.title}>{refusal.title}</Text>
      <Text style={styles.body}>{refusal.body}</Text>

      {refusal.offer === 'fresh room' && (
        <Pressable
          accessibilityRole="button"
          onPress={() => router.replace('/setup')}
          style={({ pressed }) => [styles.offer, pressed && styles.offerPressed]}
        >
          <Text style={styles.offerLabel}>Start a fresh room</Text>
        </Pressable>
      )}

      {refusal.offer === 'try again' && (
        <Pressable
          accessibilityRole="button"
          onPress={onRetry}
          style={({ pressed }) => [styles.offer, pressed && styles.offerPressed]}
        >
          {/* Names the action rather than the failure. "Retry" describes what
              went wrong; this describes what happens next. */}
          <Text style={styles.offerLabel}>Read it again</Text>
        </Pressable>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  refused: { padding: space.screen, justifyContent: 'center' },

  waiting: {
    flex: 1,
    backgroundColor: color.surface,
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.base,
  },
  waitingLabel: { ...type.bodyMd, color: color.onSurfaceVariant },

  title: { ...type.headlineLg, color: color.onSurface },
  body: { ...type.bodyLg, color: color.onSurfaceVariant, marginTop: space.snug },

  offer: {
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: color.primary,
    borderRadius: radius.pill,
    marginTop: space.section,
  },
  offerPressed: { opacity: 0.8 },
  offerLabel: { ...type.labelLg, color: color.onPrimary },
});
