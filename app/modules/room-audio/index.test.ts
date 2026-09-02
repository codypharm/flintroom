/**
 * The owned audio layer's adapters (#25), tested at the bridge.
 *
 * The native halves cannot run under Jest — that is the device build's job —
 * but everything that can go wrong in *translation* lives here: base64 to
 * float and back, the frame event wearing `UplinkRecorder`'s shape, and the
 * FIFO that turns the native `played` event back into per-id `onBufferEnded`
 * calls without ever reporting a discarded chunk as heard.
 */

import type { RoomAudioNative } from './src/native';
import { openNativeCapture, openNativePlayback, roomAudioAvailable } from './index';

class FakeNative implements RoomAudioNative {
  captures = 0;
  stopped = 0;
  playbacks = 0;
  playbackStops = 0;
  enqueued: string[] = [];
  discards = 0;
  private listeners = new Map<string, Set<(event: never) => void>>();

  captureProfiles: boolean[] = [];
  playbackProfiles: boolean[] = [];
  startCapture(communication: boolean): Promise<void> {
    this.captures += 1;
    this.captureProfiles.push(communication);
    return Promise.resolve();
  }
  stopCapture(): void {
    this.stopped += 1;
  }
  startPlayback(communication: boolean): Promise<void> {
    this.playbacks += 1;
    this.playbackProfiles.push(communication);
    return Promise.resolve();
  }
  stopPlayback(): void {
    this.playbackStops += 1;
  }
  enqueue(base64: string): void {
    this.enqueued.push(base64);
  }
  discard(): void {
    this.discards += 1;
  }
  addListener(eventName: string, listener: (event: never) => void) {
    const set = this.listeners.get(eventName) ?? new Set();
    set.add(listener);
    this.listeners.set(eventName, set);
    return { remove: () => set.delete(listener) };
  }
  emit(eventName: string, event: unknown): void {
    for (const listener of this.listeners.get(eventName) ?? []) {
      (listener as (event: unknown) => void)(event);
    }
  }
}

/** PCM16 little-endian base64 for a handful of known samples. */
function base64Of(samples: number[]): string {
  const bytes = new Uint8Array(samples.length * 2);
  const view = new DataView(bytes.buffer);
  samples.forEach((sample, i) => view.setInt16(i * 2, sample, true));
  return btoa(String.fromCharCode(...bytes));
}

it('is unavailable where the native module is absent, without throwing', () => {
  expect(roomAudioAvailable(null)).toBe(false);
  expect(openNativeCapture({ communication: true }, null)).toBeNull();
  expect(openNativePlayback({ communication: true }, null)).toBeNull();
});

describe('capture', () => {
  it('wears the recorder shape: a frame arrives as float samples at the reported rate', () => {
    const native = new FakeNative();
    const capture = openNativeCapture({ communication: true }, native)!;

    const heard: { samples: Float32Array; rate: number; frames: number }[] = [];
    capture.onAudioReady({ sampleRate: 16000, bufferLength: 320, channelCount: 1 }, (event) => {
      heard.push({
        samples: event.buffer.getChannelData(0),
        rate: event.buffer.sampleRate,
        frames: event.numFrames,
      });
    });

    native.emit('frame', { base64: base64Of([0, 16384, -32768]), sampleRate: 16000 });

    expect(heard).toHaveLength(1);
    expect(heard[0]!.rate).toBe(16000);
    expect(heard[0]!.frames).toBe(3);
    expect(Array.from(heard[0]!.samples)).toEqual([0, 0.5, -1]);
  });

  it('reports the rate the device delivered, so the uplink can refuse it', () => {
    // `uplink.ts` treats a wrong rate as fatal to the room rather than
    // resampling. The adapter must carry the truth through, not paper it.
    const native = new FakeNative();
    const capture = openNativeCapture({ communication: true }, native)!;

    let reported = 0;
    capture.onAudioReady({ sampleRate: 16000, bufferLength: 320, channelCount: 1 }, (event) => {
      reported = event.buffer.sampleRate;
    });
    native.emit('frame', { base64: base64Of([1]), sampleRate: 48000 });

    expect(reported).toBe(48000);
  });

  it('a cleared callback hears nothing more', () => {
    const native = new FakeNative();
    const capture = openNativeCapture({ communication: true }, native)!;

    let frames = 0;
    capture.onAudioReady({ sampleRate: 16000, bufferLength: 320, channelCount: 1 }, () => {
      frames += 1;
    });
    capture.clearOnAudioReady();
    native.emit('frame', { base64: base64Of([1]), sampleRate: 16000 });

    expect(frames).toBe(0);
  });

  it('start and stop reach the microphone, carrying the profile', async () => {
    const native = new FakeNative();
    const capture = openNativeCapture({ communication: true }, native)!;

    await capture.start();
    capture.stop();

    expect(native.captures).toBe(1);
    expect(native.stopped).toBe(1);
    expect(native.captureProfiles).toEqual([true]);
  });

  it('the debrief profile crosses the bridge as plainly as the room one', async () => {
    // The profile is the whole difference between the AEC pair and a plain
    // microphone; an adapter that dropped it would colour every coaching
    // clip with call-tuned processing and nobody would trace it here.
    const native = new FakeNative();
    await openNativeCapture({ communication: false }, native)!.start();
    openNativePlayback({ communication: false }, native)!
      .createBufferQueueSource()
      .start(0, 0);

    expect(native.captureProfiles).toEqual([false]);
    expect(native.playbackProfiles).toEqual([false]);
  });
});

describe('playback', () => {
  it('runs at the wire rate, so the resample upstream is an identity', () => {
    expect(openNativePlayback({ communication: true }, new FakeNative())!.sampleRate).toBe(16000);
  });

  it('an enqueued buffer crosses the bridge as the PCM16 it holds', () => {
    const native = new FakeNative();
    const context = openNativePlayback({ communication: true }, native)!;
    const source = context.createBufferQueueSource();
    source.start(0, 0);

    const buffer = context.createBuffer(1, 3, 16000);
    buffer.copyToChannel(new Float32Array([0, 0.5, -1]), 0);
    source.enqueueBuffer(buffer);

    expect(native.enqueued).toEqual([base64Of([0, 16384, -32768])]);
  });

  it('played events come back as per-id ended calls, in queue order', () => {
    const native = new FakeNative();
    const source = openNativePlayback({ communication: true }, native)!.createBufferQueueSource();
    source.start(0, 0);

    const context = openNativePlayback({ communication: true }, native)!;
    const buffer = context.createBuffer(1, 1, 16000);
    buffer.copyToChannel(new Float32Array([0]), 0);
    const first = source.enqueueBuffer(buffer);
    const second = source.enqueueBuffer(buffer);

    const ended: { bufferId: string; isLastBufferInQueue: boolean }[] = [];
    source.onBufferEnded = (event) => ended.push(event);

    native.emit('played', { drained: false });
    native.emit('played', { drained: true });

    expect(ended).toEqual([
      { bufferId: first, isLastBufferInQueue: false },
      { bufferId: second, isLastBufferInQueue: true },
    ]);
  });

  it('a discard drops the queue and never reports the dropped chunks as heard', () => {
    // The property that matters for `onDrained`: an ended event for audio
    // nobody heard would release the panelist while the room believes the
    // loudspeaker just finished their line.
    const native = new FakeNative();
    const context = openNativePlayback({ communication: true }, native)!;
    const source = context.createBufferQueueSource();
    source.start(0, 0);

    const buffer = context.createBuffer(1, 1, 16000);
    buffer.copyToChannel(new Float32Array([0]), 0);
    source.enqueueBuffer(buffer);
    source.enqueueBuffer(buffer);

    const ended: unknown[] = [];
    source.onBufferEnded = (event) => ended.push(event);

    source.clearBuffers();
    expect(native.discards).toBe(1);

    // A chunk that finished on the device just as the discard landed.
    native.emit('played', { drained: true });
    expect(ended).toEqual([]);
  });

  it('stop unsubscribes and closes the output stream', () => {
    const native = new FakeNative();
    const source = openNativePlayback({ communication: true }, native)!.createBufferQueueSource();
    source.start(0, 0);
    source.stop(0);

    expect(native.playbackStops).toBe(1);
    native.emit('played', { drained: true }); // must not throw or call anything
  });
});
