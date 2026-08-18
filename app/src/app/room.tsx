import { router, useTheme } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import { AudioContext, AudioManager, AudioRecorder } from 'react-native-audio-api';
import { SafeAreaView } from 'react-native-safe-area-context';

import { enterHandsFree, leaveHandsFree } from '../../modules/audio-routing';
import { API_BASE_URL } from '../lib/auth';
import { joinRoom, type Room } from '../lib/voice/room';

/**
 * An instrument, not a destination.
 *
 * Every part of a room has been built and tested — the socket, PCM both ways,
 * playback, the uplink, captions, the panel behind it — and none of it has ever
 * met a phone. This is the door that lets it, and it exists to answer four
 * questions no test can: does the panel arrive, how long does it take, does the
 * echo canceller survive real speech, and does talking over a panelist stop
 * them.
 *
 * Undesigned on purpose, exactly as `echo-spike.tsx` and the home screen are.
 * `CLAUDE.md` requires the `impeccable` pass and `design-guide/` before anything
 * visual, and that pass is owed to the *real* interrogation screen — a hands-free
 * surface with a room-temperature gauge and an active-speaker indicator, which
 * this is not. Reading a scaffold's default styling as a design decision is how
 * it quietly becomes one.
 *
 * It leaves when sign-in lands. Nothing should come to depend on it, and the
 * token field is the reason: the app has no native sign-in yet, so the token
 * comes from `backend/scripts/dev_token.py` on the laptop that holds the signing
 * secret. There is no path here a deployed build could use.
 */

/** What the wire carries in both directions. Not negotiable, not inferred. */
const WIRE_SAMPLE_RATE = 16_000;

/** Frames per callback. 1600 at 16 kHz is 100ms — the spike's value. */
const BUFFER_LENGTH = 1600;

/** Scoped, so releasing ours cannot cancel somebody else's hold. */
const KEEP_AWAKE = 'flintroom-room';

type Phase = 'idle' | 'opening' | 'live' | 'over';

interface Caption {
  text: string;
  /** Milliseconds from the room opening, so a latency read needs no stopwatch. */
  at: number;
}

export default function RoomScreen() {
  const { colors } = useTheme();
  // Prefilled from `app/.env.local`, which `scripts/dev_token.py` writes. Two
  // hundred characters is not something anyone should type into a handset, and
  // a measurement abandoned because pasting was annoying is a measurement not
  // taken.
  //
  // `__DEV__` guards it rather than trusting the file to be absent. Expo inlines
  // `EXPO_PUBLIC_*` into the bundle in plain text, so a release build made on a
  // machine that happened to have the file would otherwise ship a working token
  // for somebody's account. The variable is read statically because Expo only
  // substitutes dot notation — `process.env['...']` is not replaced.
  const [token, setToken] = useState(
    __DEV__ ? (process.env.EXPO_PUBLIC_DEV_TOKEN ?? '') : ''
  );
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [ending, setEnding] = useState<string | null>(null);
  // On screen rather than in a log, because the phone is the only place this is
  // observable and reading logcat is a second thing to get right while holding
  // a handset.
  const [audio, setAudio] = useState<string | null>(null);

  // Kept so the room can hand off when it ends. §4.1's own sequence — the
  // panel finishes, the session settles, the debrief opens — and the id is the
  // only thing the next screen needs.
  const [settled, setSettled] = useState<string | null>(null);
  const room = useRef<Room | null>(null);
  const context = useRef<AudioContext | null>(null);
  const recorder = useRef<AudioRecorder | null>(null);
  const openedAt = useRef(0);

  /**
   * Torn down in one place, whatever ended the room.
   *
   * The recorder and the audio session outlive `joinRoom` — it owns the socket
   * and the uplink, not the hardware it was handed — so leaving without this
   * holds the microphone open and leaves the phone in a call-audio mode after
   * the room is gone.
   */
  const release = useCallback(async () => {
    await deactivateKeepAwake(KEEP_AWAKE);
    recorder.current?.stop();
    recorder.current = null;
    await context.current?.close();
    context.current = null;
    await leaveHandsFree();
  }, []);

  const enter = useCallback(async () => {
    setError(null);
    setEnding(null);
    setCaptions([]);
    setPhase('opening');

    try {
      const permission = await AudioManager.requestRecordingPermissions();
      if (permission !== 'Granted') {
        throw new Error(`Microphone permission ${permission}`);
      }

      // Both halves of hands-free, and both are load-bearing. `voiceChat`
      // engages Apple's voice processing, which is what cancels the panel out
      // of the microphone; `defaultToSpeaker` stops `playAndRecord` routing to
      // the earpiece, which would be a phone held to the ear rather than the
      // product. `enterHandsFree` is the Android side of the same sentence.
      AudioManager.setAudioSessionOptions({
        iosCategory: 'playAndRecord',
        iosMode: 'voiceChat',
        iosOptions: ['defaultToSpeaker', 'allowBluetoothHFP'],
      });
      await enterHandsFree();

      // A room is hands-free by design — `CLAUDE.md` puts the phone face-down
      // on a desk and forbids UI that assumes anyone is holding it. Nobody
      // touches the screen for the length of an interrogation, so Android's
      // display timeout fires, the app goes to the background and the socket
      // dies. The server reads that as the user hanging up and settles the
      // room, which is why every session ended in `client_disconnect` at
      // roughly the same number of seconds, whatever was said in it.
      //
      // Held only while a room is open. Keeping the display on for the whole
      // app would be a battery cost paid by every screen that does not need it.
      await activateKeepAwakeAsync(KEEP_AWAKE);

      const capture = new AudioRecorder();
      recorder.current = capture;
      const playback = new AudioContext();
      context.current = playback;

      // A context that is not running renders nothing, and renders it silently:
      // frames enqueue without complaint and no sound arrives. That is
      // indistinguishable from a panel that never spoke, which is exactly how
      // the first room with a working microphone read — captions on screen,
      // nothing audible.
      if (playback.state !== 'running') {
        await playback.resume();
      }
      setAudio(`${playback.state} @ ${playback.sampleRate}Hz`);

      const response = await fetch(`${API_BASE_URL}/v1/sessions`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          authorization: `Bearer ${token.trim()}`,
        },
        // No archetypes and no material: the server seats the panel we ship,
        // which is what a first-time user gets and therefore what is worth
        // measuring first.
        body: JSON.stringify({}),
      });

      if (!response.ok) {
        throw new Error(`Starting the session: ${response.status} ${await response.text()}`);
      }

      const session = await response.json();
      setSettled(session.id);
      const socketUrl = `${API_BASE_URL.replace(/^http/, 'ws')}/v1/sessions/${session.id}/stream`;

      openedAt.current = Date.now();
      room.current = await joinRoom({
        url: socketUrl,
        ticket: session.stream_ticket,
        context: playback,
        recorder: capture,
        onTranscript: (text) =>
          setCaptions((so_far) => [
            ...so_far,
            { text, at: Date.now() - openedAt.current },
          ]),
        onEnding: (why) => {
          setEnding(why);
          setPhase('over');
          void release();
        },
      });

      // Started here, after `joinRoom` and not before it. `joinRoom` builds the
      // uplink, which is what registers `onAudioReady` — and the echo spike
      // established on a real device that the callback goes on before capture
      // begins. Starting first left the recorder running with nowhere to
      // deliver, which is exactly what the first room on a phone did: fifty-six
      // seconds open, zero seconds of audio at the far end, and no error
      // anywhere because nothing was wrong, only silent.
      await capture.start();

      setPhase('live');
    } catch (thrown) {
      setError(thrown instanceof Error ? thrown.message : String(thrown));
      setPhase('idle');
      await release();
    }
  }, [release, token]);

  const leave = useCallback(() => {
    room.current?.leave();
    room.current = null;
  }, []);

  return (
    <SafeAreaView style={styles.screen}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={[styles.heading, { color: colors.text }]}>Room</Text>

        {phase === 'idle' && (
          <>
            <Text style={[styles.hint, { color: colors.text }]}>
              From `backend/`: uv run python -m scripts.dev_token
            </Text>
            <TextInput
              value={token}
              onChangeText={setToken}
              placeholder="Paste the dev token"
              placeholderTextColor={colors.border}
              autoCapitalize="none"
              autoCorrect={false}
              multiline
              style={[styles.input, { color: colors.text, borderColor: colors.border }]}
            />
            <Pressable
              onPress={enter}
              disabled={token.trim().length === 0}
              style={[styles.button, { borderColor: colors.primary }]}
            >
              <Text style={[styles.buttonText, { color: colors.primary }]}>
                Enter the room
              </Text>
            </Pressable>
          </>
        )}

        {phase === 'opening' && <ActivityIndicator />}

        {phase === 'live' && (
          <Pressable onPress={leave} style={[styles.button, { borderColor: colors.notification }]}>
            <Text style={[styles.buttonText, { color: colors.notification }]}>Leave</Text>
          </Pressable>
        )}

        {audio !== null && (
          <Text style={[styles.hint, { color: colors.text }]}>audio: {audio}</Text>
        )}

        {ending !== null && (
          <Text style={[styles.hint, { color: colors.text }]}>Room ended: {ending}</Text>
        )}

        {/*
          The hand-off §4.1 describes, and the only route into the debrief that
          exists: there is no list of past rooms yet. Offered rather than
          automatic, because this screen is still an instrument and a
          measurement run that navigated itself away would lose the numbers on
          it.
        */}
        {phase === 'over' && settled !== null && (
          <Pressable
            onPress={() => router.push(`/debrief/${settled}`)}
            style={[styles.button, { borderColor: colors.primary }]}
          >
            <Text style={[styles.buttonText, { color: colors.primary }]}>Open the debrief</Text>
          </Pressable>
        )}

        {error !== null && (
          <Text style={[styles.error, { color: colors.notification }]}>{error}</Text>
        )}

        {/*
          Timed from the room opening rather than from the last thing the user
          said, because nothing on this side knows when that was — the server
          decides where an utterance ended. The gap between two consecutive
          numbers is the figure Open Risk #3 is about.
        */}
        {captions.map((caption, index) => (
          <View key={index} style={styles.caption}>
            <Text style={[styles.at, { color: colors.border }]}>
              {(caption.at / 1000).toFixed(1)}s
            </Text>
            <Text style={[styles.line, { color: colors.text }]}>{caption.text}</Text>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { padding: 24, gap: 16 },
  heading: { fontSize: 28, fontWeight: '600' },
  hint: { fontSize: 13, opacity: 0.7 },
  input: { borderWidth: 1, borderRadius: 6, padding: 12, minHeight: 88, fontSize: 12 },
  button: { borderWidth: 1, borderRadius: 6, padding: 14, alignItems: 'center' },
  buttonText: { fontSize: 16, fontWeight: '600' },
  error: { fontSize: 14 },
  caption: { gap: 2 },
  at: { fontSize: 11, fontVariant: ['tabular-nums'] },
  line: { fontSize: 16, lineHeight: 22 },
});
