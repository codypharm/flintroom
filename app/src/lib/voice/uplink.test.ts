import type { AudioRecorder } from 'react-native-audio-api';

import { fromPcm16 } from '../audio/pcm';
import { createUplink, type UplinkRecorder } from './uplink';

/**
 * The same compile-time check `playback.test.ts` makes, and it earned its
 * keep immediately: the structural interface was first written with an option
 * named `bufferLengthInSamples`, which does not exist — the real one is
 * `bufferLength`, and `channelCount` is required alongside it. Every test in
 * this file passed against the invented shape, because a hand-written
 * interface tests only itself.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function theRealRecorderFits(recorder: AudioRecorder): UplinkRecorder {
  return recorder;
}

/**
 * What the user says, on its way to the panel.
 *
 * The relay transcodes nothing, so whatever this produces is what the voice
 * provider hears — and what the provider hears decides whether a challenge is
 * grounded in what the user actually said (Open Risk #2). A fault here does not
 * look like a fault; it looks like a panel that misquotes people.
 */
class FakeRecorderBuffer {
  constructor(private readonly samples: Float32Array, readonly sampleRate: number) {}

  getChannelData(): Float32Array {
    return this.samples;
  }
}

class FakeRecorder {
  requested: { sampleRate: number; bufferLengthInSamples: number } | null = null;
  cleared = 0;
  private callback: ((event: { buffer: FakeRecorderBuffer; numFrames: number }) => void) | null =
    null;

  onAudioReady(
    options: { sampleRate: number; bufferLengthInSamples: number },
    callback: (event: { buffer: FakeRecorderBuffer; numFrames: number }) => void
  ): void {
    this.requested = options;
    this.callback = callback;
  }

  clearOnAudioReady(): void {
    this.cleared += 1;
    this.callback = null;
  }

  /** The microphone delivering a buffer, which is all this module reacts to. */
  deliver(samples: number[], sampleRate = 16000, numFrames = samples.length): void {
    this.callback?.({
      buffer: new FakeRecorderBuffer(new Float32Array(samples), sampleRate),
      numFrames,
    });
  }
}

function uplink() {
  const recorder = new FakeRecorder();
  const sent: ArrayBuffer[] = [];
  const failures: Error[] = [];
  const link = createUplink({
    recorder: recorder as never,
    send: (pcm) => sent.push(pcm),
    onFailure: (error) => failures.push(error),
  });

  return { recorder, sent, failures, link };
}

describe('carrying the user to the panel', () => {
  it('sends what the microphone delivered, as PCM16 on the wire', () => {
    const { recorder, sent } = uplink();

    recorder.deliver([0, 0.5, -0.5]);

    expect(sent).toHaveLength(1);
    // Compared after a round trip rather than byte by byte: the assertion is
    // that the samples survive, not that a particular encoding was chosen.
    // `toPcm16` owns the encoding and has its own tests.
    expect(Array.from(fromPcm16(sent[0]))).toEqual([0, expect.closeTo(0.5, 4), expect.closeTo(-0.5, 4)]);
  });

  it('sends only the frames actually captured, not the whole buffer', () => {
    // The recorder reports `numFrames` separately from the buffer's length
    // because the last buffer of a take is usually short and the rest of it is
    // stale audio from the previous pass. Sending the whole thing appends a
    // fragment of the user's previous sentence to their current one — which
    // the provider transcribes, and the panel then quotes back at them as
    // something they said.
    const { recorder, sent } = uplink();

    recorder.deliver([0.1, 0.2, 0.9, 0.9], 16000, 2);

    expect(fromPcm16(sent[0])).toHaveLength(2);
  });
});

describe('when the microphone does not deliver the rate it was asked for', () => {
  it('fails the room instead of sending audio at the wrong speed', () => {
    // `onAudioReady` documents that the delivered rate "may differ depending on
    // hardware". Our one handset returned the 16 kHz it was asked for, and one
    // handset is not a result.
    //
    // Sent unconverted, 48 kHz audio reaches the provider as the user speaking
    // at a third speed, an octave and a half down. Transcription does not
    // degrade, it collapses — and only on some devices, and only for the user,
    // whose panel then challenges claims they never made. Refusing is louder
    // and arrives with a rate to put in a bug report.
    const { recorder, sent, failures } = uplink();

    recorder.deliver([0.1, 0.2], 48000);

    expect(sent).toHaveLength(0);
    expect(failures).toHaveLength(1);
    expect(failures[0]).toMatchObject({ rate: 48000 });
  });

  it('stops listening rather than reporting every buffer that follows', () => {
    // The recorder does not stop because we disliked one buffer; left
    // subscribed it delivers fifty a second, and the room would end fifty
    // times over.
    const { recorder, failures } = uplink();

    recorder.deliver([0.1], 48000);
    recorder.deliver([0.2], 48000);

    expect(failures).toHaveLength(1);
    expect(recorder.cleared).toBe(1);
  });
});
