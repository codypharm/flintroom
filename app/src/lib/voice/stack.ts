import {
  openNativeCapture,
  openNativePlayback,
  type Profile,
} from '../../../modules/room-audio';
import type { PlaybackContext } from './playback';
import type { UplinkRecorder } from './uplink';

/**
 * Which audio stack a screen gets, decided in exactly one place (#25).
 *
 * Since 2026-09-02 there is one answer: `modules/room-audio`, the owned
 * pair, measured on hardware (exact digital silence on the uplink during
 * playback, a talking presenter heard through it — `docs/echo-cancellation.md`
 * → "The owned stack, measured"). The library it replaced is gone, with its
 * patch and its deep import; this file remains because *which profile* a
 * screen opens is still a decision worth owning in one place:
 *
 * - the live room opens `communication: true` — both halves of the AEC pair;
 * - the debrief opens `communication: false` — a plain microphone (nothing
 *   plays while somebody answers a coach, and call-tuned processing would
 *   only colour a solo recording) and media playback (voice-communication
 *   usage outside communication mode routes to the earpiece, #26).
 *
 * **Loud when the native module is absent.** That is a build missing its own
 * audio layer — a dev client from before the module existed, or a broken
 * autolink — and a silent fallback would be a room that opens and hears
 * nothing, the exact failure mode this file refuses to reintroduce.
 */

/** What a screen needs from a microphone. */
export interface CaptureStack {
  recorder: UplinkRecorder & { start(): unknown; stop(): void };
}

/** What a screen needs from a speaker. */
export interface PlaybackStack {
  context: PlaybackContext;
  /**
   * Kept for the call sites' shape: the owned path opens its stream on
   * `source.start` and configures its own session natively, so this resolves
   * immediately. It survives because "make the output path able to sound"
   * is a sentence the screens say once, whoever is underneath.
   */
  ready(): Promise<void>;
  close(): Promise<void>;
}

function missing(): never {
  throw new Error(
    'the room-audio native module is not in this build; rebuild the dev client'
  );
}

export function openCaptureStack(profile: Profile = { communication: true }): CaptureStack {
  const capture = openNativeCapture(profile);
  if (!capture) {
    missing();
  }
  return { recorder: capture };
}

export function openPlaybackStack(profile: Profile = { communication: true }): PlaybackStack {
  const context = openNativePlayback(profile);
  if (!context) {
    missing();
  }
  return {
    context,
    ready: async () => {},
    close: async () => context.close(),
  };
}
