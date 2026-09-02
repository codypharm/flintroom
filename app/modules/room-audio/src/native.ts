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
  /** Open the microphone. Frames arrive as `frame` events. */
  startCapture(): Promise<void>;
  stopCapture(): void;

  /** Open the output stream. Silent until something is enqueued. */
  startPlayback(): Promise<void>;
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
