import type { FrameEvent, PlayedEvent, RoomAudioNative } from './src/native';
import defaultNative from './src/native';

/**
 * The owned audio layer (#25), wearing the shapes the room already uses.
 *
 * `lib/voice/uplink.ts` and `lib/voice/playback.ts` were both written against
 * structural seams (`UplinkRecorder`, `PlaybackContext`) precisely so the
 * library underneath could be replaced by satisfying a handful of members.
 * This file is that satisfaction: adapters over the native module that let
 * the room swap audio stacks without a line of room code changing.
 *
 * Why adapters rather than moving the room onto a new interface: the seams
 * are tested, the room logic against them is tested, and a swap that
 * preserves the seam keeps every one of those tests meaningful. The seams
 * can be simplified later, once the old library is gone and there is one
 * implementation instead of two.
 */

/** The rate the wire fixes and the native streams are opened at. */
const SAMPLE_RATE = 16000;

export function roomAudioAvailable(native: RoomAudioNative | null = defaultNative): boolean {
  return native !== null;
}

/* ── Encoding ─────────────────────────────────────────────
   Local to the module rather than imported from `src/lib/audio`, so the
   module stays self-contained — it is the thing everything else depends on,
   and a dependency arrow pointing back out of it would make the eventual
   extraction to a package a rewrite. `atob`/`btoa` are on Hermes; `Buffer`
   is not (the finding `lib/debrief/voice.ts` records). */

function bytesFromBase64(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function base64FromBytes(bytes: Uint8Array): string {
  let binary = '';
  // Chunked: String.fromCharCode(...whole) overflows the argument limit on a
  // long panel line.
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  }
  return btoa(binary);
}

function floatFromPcm16(bytes: Uint8Array): Float32Array {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const samples = new Float32Array(bytes.byteLength >> 1);
  for (let i = 0; i < samples.length; i++) {
    samples[i] = view.getInt16(i * 2, true) / 32768;
  }
  return samples;
}

function pcm16FromFloat(samples: Float32Array): Uint8Array {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  for (let i = 0; i < samples.length; i++) {
    // One scale in both directions (the decoder divides by 32768), so a
    // decode/encode round trip is exact — including full-scale negative.
    const scaled = Math.round(Math.max(-1, Math.min(1, samples[i]!)) * 32768);
    view.setInt16(i * 2, Math.max(-32768, Math.min(32767, scaled)), true);
  }
  return bytes;
}

/* ── Capture ────────────────────────────────────────────── */

interface CaptureCallback {
  (event: { buffer: { getChannelData(channel: number): Float32Array; readonly sampleRate: number }; numFrames: number }): void;
}

export interface NativeCapture {
  /** `UplinkRecorder`'s member, satisfied. Options are advisory — the native
   *  stream is opened at the wire rate, and the frame reports what the device
   *  actually delivered so `uplink.ts` keeps its rate check. */
  onAudioReady(
    options: { sampleRate: number; bufferLength: number; channelCount: number },
    callback: CaptureCallback
  ): void;
  clearOnAudioReady(): void;
  start(): Promise<void>;
  stop(): void;
}

export interface Profile {
  /**
   * True is the live room: both halves of the AEC pair declared. False is
   * the debrief: a plain microphone and media playback, because call-tuned
   * processing on a solo recording and an earpiece-routed coach are the two
   * failures the profile exists to refuse.
   */
  communication: boolean;
}

export function openNativeCapture(
  { communication }: Profile,
  native: RoomAudioNative | null = defaultNative
): NativeCapture | null {
  if (!native) {
    return null;
  }

  let callback: CaptureCallback | null = null;
  let subscription: { remove(): void } | null = null;

  return {
    onAudioReady: (_options, ready) => {
      callback = ready;
      subscription?.remove();
      subscription = native.addListener('frame', (event: FrameEvent) => {
        const samples = floatFromPcm16(bytesFromBase64(event.base64));
        callback?.({
          buffer: {
            getChannelData: () => samples,
            sampleRate: event.sampleRate,
          },
          numFrames: samples.length,
        });
      });
    },
    clearOnAudioReady: () => {
      callback = null;
      subscription?.remove();
      subscription = null;
    },
    start: () => native.startCapture(communication),
    stop: () => {
      native.stopCapture();
    },
  };
}

/* ── Playback ───────────────────────────────────────────── */

interface BufferLike {
  copyToChannel(source: Float32Array, channel: number): void;
  /** What was copied in, read back out on enqueue. */
  readonly samples: () => Float32Array;
}

interface EndedListener {
  (event: { bufferId: string; isLastBufferInQueue: boolean }): void;
}

export interface NativePlaybackContext {
  readonly sampleRate: number;
  readonly destination: unknown;
  createBufferQueueSource(): {
    connect(destination: unknown): void;
    enqueueBuffer(buffer: BufferLike): string;
    dequeueBuffer(bufferId: string): void;
    clearBuffers(): void;
    start(when?: number, offset?: number): void;
    stop(when?: number): void;
    onBufferEnded: EndedListener | null | undefined;
  };
  createBuffer(
    numberOfChannels: number,
    length: number,
    sampleRate: number
  ): BufferLike;
  close(): void;
}

export function openNativePlayback(
  { communication }: Profile,
  native: RoomAudioNative | null = defaultNative
): NativePlaybackContext | null {
  if (!native) {
    return null;
  }

  return {
    // The context runs at the wire rate, which makes `playback.ts`'s
    // resample an identity copy — the native layer plays 16 kHz directly
    // rather than asking JavaScript to upsample for it.
    sampleRate: SAMPLE_RATE,
    destination: null,

    createBuffer: (_channels, length) => {
      // Typed as the generic Float32Array: the caller's array may sit on any
      // ArrayBufferLike, and this holds a reference rather than copying.
      let held: Float32Array = new Float32Array(length);
      return {
        copyToChannel: (source) => {
          held = source;
        },
        samples: () => held,
      };
    },

    createBufferQueueSource: () => {
      // The FIFO that turns the native `played` event back into the per-id
      // `onBufferEnded` contract `playback.ts` releases memory through. The
      // native side plays strictly in order, so order is identity.
      const queued: string[] = [];
      let next = 0;
      let subscription: { remove(): void } | null = null;

      const source: ReturnType<NativePlaybackContext['createBufferQueueSource']> = {
        connect: () => {},
        enqueueBuffer: (buffer) => {
          const id = String(next++);
          queued.push(id);
          native.enqueue(base64FromBytes(pcm16FromFloat(buffer.samples())));
          return id;
        },
        // Memory is native-side and freed as chunks play; there is nothing
        // held per-id in JavaScript to release.
        dequeueBuffer: () => {},
        clearBuffers: () => {
          // Barge-in: dropped chunks never report ended — `playback.ts`
          // forgets them wholesale, and an ended event for a discarded id
          // would fire `onDrained` about audio nobody heard.
          queued.length = 0;
          native.discard();
        },
        start: () => {
          subscription?.remove();
          subscription = native.addListener('played', (event: PlayedEvent) => {
            const id = queued.shift();
            if (id === undefined) {
              return; // A discard raced a chunk that had already finished.
            }
            source.onBufferEnded?.({
              bufferId: id,
              isLastBufferInQueue: event.drained && queued.length === 0,
            });
          });
          void native.startPlayback(communication);
        },
        stop: () => {
          subscription?.remove();
          subscription = null;
          native.stopPlayback();
        },
        onBufferEnded: null,
      };

      return source;
    },

    close: () => {
      native.stopPlayback();
    },
  };
}
