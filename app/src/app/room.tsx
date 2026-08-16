import { useTheme } from 'expo-router';
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

type Phase = 'idle' | 'opening' | 'live' | 'over';

interface Caption {
  text: string;
  /** Milliseconds from the room opening, so a latency read needs no stopwatch. */
  at: number;
}

export default function RoomScreen() {
  const { colors } = useTheme();
  const [token, setToken] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [ending, setEnding] = useState<string | null>(null);

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

      // Started before the socket. A room is metered from the moment the
      // channel comes up, so anything slow belongs on this side of it — a
      // microphone negotiated after the room opened is billed silence.
      const started = new AudioRecorder();
      recorder.current = started;
      const playback = new AudioContext();
      context.current = playback;

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
      const socketUrl = `${API_BASE_URL.replace(/^http/, 'ws')}/v1/sessions/${session.id}/stream`;

      openedAt.current = Date.now();
      room.current = await joinRoom({
        url: socketUrl,
        ticket: session.stream_ticket,
        context: playback,
        recorder: started,
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

        {ending !== null && (
          <Text style={[styles.hint, { color: colors.text }]}>Room ended: {ending}</Text>
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
