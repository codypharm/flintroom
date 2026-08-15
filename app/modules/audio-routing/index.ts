import native from './src/native';

/**
 * Put Android's audio stack into speakerphone, and take it back out.
 *
 * This exists because `react-native-audio-api` cannot express it. Its
 * `SessionOptions` is iOS-only and its Kotlin touches `AudioManager` for focus,
 * media session and volume but never for mode or routing — so the app stays in
 * `MODE_NORMAL`, where the `Usage::VoiceCommunication` player that
 * `app/patches/` introduces routes to the *earpiece*. Working as documented,
 * and wrong for a product whose whole premise is a phone lying on a desk.
 *
 * It is deliberately not part of that patch. Which speaker the panel comes out
 * of is app policy, and it has to outlive whichever audio library sits
 * underneath — including the one task #25 replaces it with.
 *
 * iOS needs none of this: `setAudioSessionOptions({ iosCategory:
 * 'playAndRecord', iosMode: 'voiceChat', iosOptions: ['defaultToSpeaker'] })`
 * already says the same thing, and the native module is absent there.
 */
export async function enterHandsFree(): Promise<boolean> {
  // `false` when there is no native module: nothing was routed, which is the
  // truthful answer and the one a caller can act on.
  return (await native?.enterHandsFree()) ?? false;
}

/**
 * Always pair this with `enterHandsFree`, including on the error path.
 *
 * The audio mode is process-wide and outlives the screen that set it. Left in
 * communication mode, every later sound the app makes keeps call-audio routing
 * and the volume rocker goes on adjusting the wrong stream — a bug that
 * surfaces nowhere near the session that caused it.
 */
export function leaveHandsFree(): void {
  native?.leaveHandsFree();
}
