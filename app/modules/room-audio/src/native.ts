import { requireOptionalNativeModule } from 'expo-modules-core';

/**
 * The native seam of the owned audio layer (#25).
 *
 * Everything the live room needs from a device, and nothing else: a 16 kHz
 * mono capture stream and a 16 kHz mono playback queue, both declared voice
 * communication *in code we own* — which is the property `app/patches/`
 * existed to graft onto a library that could not express it, and the property
 * `docs/echo-cancellation.md` measured as the difference between a room that
 * interrupts itself and one that works.
 *
 * Bytes cross the bridge as base64 PCM16, the encoding the rest of the app
 * already speaks (coach speech arrives from the server the same way).
 */
export interface RoomAudioNative {
  /**
   * Open the microphone. Frames arrive as `frame` events.
   *
   * `communication` is the profile: true opens the live room's half of the
   * AEC pair (VOICE_COMMUNICATION / voice-processed input); false is the
   * debrief's plain microphone — nothing plays while somebody answers a
   * coach, and call-tuned processing would only colour a solo recording.
   */
  startCapture(communication: boolean): Promise<void>;
  stopCapture(): void;

  /**
   * Open the output stream. Silent until something is enqueued.
   *
   * `communication` true names the far-end reference for the canceller;
   * false is media playback — the coach's voice, which outside
   * communication mode would otherwise route to the earpiece (#26).
   */
  startPlayback(communication: boolean): Promise<void>;
  stopPlayback(): void;

  /** Append one PCM16 chunk to the playback queue. */
  enqueue(base64: string): void;

  /**
   * Barge-in. Drop every queued chunk immediately — the spec is "buffered
   * audio is discarded now", and `docs/echo-cancellation.md` records the one
   * measured handset finishing its line anyway so that nobody reads this
   * module's correctness as a regression against that field note.
   */
  discard(): void;

  addListener(eventName: string, listener: (event: never) => void): { remove(): void };
}

/** One microphone frame. PCM16 mono, base64, at the rate the device delivered. */
export interface FrameEvent {
  base64: string;
  sampleRate: number;
}

/**
 * iOS stopped the engine under the room and the module started it again.
 * `error` is empty when the restart worked.
 */
export interface RestartedEvent {
  capturing: boolean;
  playing: boolean;
  error: string;
}

/** One enqueued chunk has finished playing. Emitted in queue order. */
export interface PlayedEvent {
  /** True when the queue is now empty — the loudspeaker has gone quiet. */
  drained: boolean;
}

/**
 * Optional rather than strict, following `audio-routing`: on platforms where
 * the module is absent (web, a test runner) the strict version throws at
 * import time and takes the whole bundle down. Callers check and fall back.
 */
export default requireOptionalNativeModule<RoomAudioNative>('RoomAudio');
