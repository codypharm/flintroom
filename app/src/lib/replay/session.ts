import { setAudioModeAsync } from 'expo-audio';

/**
 * Put the shared audio session into a shape that makes sound.
 *
 * **iOS has one audio session for the whole process**, set imperatively, and
 * nothing in this app puts it back. The interrogation runs it as a two-way
 * call and the debrief at a lower intensity; both leave it that way. Playing
 * a room back on a call-shaped session keeps the microphone hot — orange
 * indicator to match — and attenuates output, which reads as a quiet
 * recording rather than a wrong setting.
 *
 * **The untouched case is the worse one.** A cold launch into the Library
 * never configures anything, and the platform default respects the ringer
 * switch: a room played with the phone on silent makes no sound, gives no
 * reason, and looks exactly like playback that failed. `playsInSilentMode`
 * is that fix, said in `expo-audio`'s words (#25 moved this file off the old
 * library's `AudioManager`; the sentence it implements is unchanged).
 *
 * Fire-and-forget on purpose: the mode call resolving is not a precondition
 * for signing a link, and nothing useful could be done with its failure.
 *
 * A file of its own so `RoomPlayer` can be tested with this behind a mock,
 * which is also why it keeps its name through the library swap.
 */
export function forPlayingBack(): void {
  void setAudioModeAsync({
    playsInSilentMode: true,
    allowsRecording: false,
    // Android: never the earpiece. The panel on the loudspeaker is the
    // product's whole acoustic premise, and replay follows it.
    shouldRouteThroughEarpiece: false,
  });
}
