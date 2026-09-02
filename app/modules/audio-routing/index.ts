import native from './src/native';

/**
 * Put Android's audio stack into speakerphone, and take it back out.
 *
 * This exists because routing is app policy, not a property of a stream. In
 * `MODE_NORMAL` a `USAGE_VOICE_COMMUNICATION` player routes to the
 * *earpiece* — working as documented, and wrong for a product whose whole
 * premise is a phone lying on a desk (#26).
 *
 * It is deliberately separate from `modules/room-audio` (#25): which preset a
 * stream opens with is a property of the stream and lives there; which
 * speaker the panel comes out of is decided per screen, here, and has to
 * outlive whichever audio layer sits underneath.
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
