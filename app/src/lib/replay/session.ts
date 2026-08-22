import { AudioManager } from 'react-native-audio-api';

/**
 * Put the shared audio session into a shape that makes sound.
 *
 * **iOS has one audio session for the whole process**, set imperatively, and
 * nothing in this app puts it back. The interrogation sets `playAndRecord` with
 * `voiceChat` so Apple's voice processing can cancel the panel out of the
 * microphone; the debrief sets `playAndRecord` with `default` for the same
 * reason at a lower intensity. Both leave it that way. Playing a room back on a
 * category built for a two-way call keeps the microphone hot — with the orange
 * indicator to match — and attenuates output, which reads as a quiet recording
 * rather than as a wrong setting.
 *
 * **The untouched case is the worse one.** A cold launch into the Library never
 * sets a category at all, and the platform default respects the ringer switch.
 * A room played with the phone on silent makes no sound, gives no reason, and
 * looks exactly like playback that failed.
 *
 * So: `playback`, which is the category for exactly this — media the user asked
 * for, over the speaker, ignoring the silent switch. Global and unrestored, like
 * every other caller, and safe for the same reason: no screen inherits a
 * category, each sets what it needs.
 *
 * A file of its own so `RoomPlayer` can be tested. `react-native-audio-api`
 * cannot be imported under Jest at all — it throws "the native module could not
 * be found" at load — so anything reaching it has to sit behind a boundary a
 * test can replace. `element.ts` is the other one.
 */
export function forPlayingBack(): void {
  AudioManager.setAudioSessionOptions({
    iosCategory: 'playback',
    iosMode: 'default',
  });
}
