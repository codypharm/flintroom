import { collectClip, CLIP_CEILING_SECONDS } from './clip';
import { WAV_HEADER_BYTES } from './wav';

/**
 * One spoken turn, accumulated from the recorder's callbacks.
 *
 * The recorder hands back a buffer every few tens of milliseconds and a turn is
 * seconds long, so something has to hold the middle. That something also has to
 * stop: an unbounded accumulator on a phone is a crash, and the way to reach it
 * is to tap Talk and put the phone down.
 */

/** A tenth of a second at 16 kHz, which is what the recorder actually delivers. */
function frames(count = 1600): Float32Array {
  return new Float32Array(count).fill(0.25);
}

describe('collectClip', () => {
  it('joins what the recorder handed over, in order', async () => {
    const clip = collectClip();
    clip.push(new Float32Array([1, 0, -1]), 16_000);
    clip.push(new Float32Array([0.5]), 16_000);

    const wav = await clip.finish().arrayBuffer();

    expect(wav.byteLength).toBe(WAV_HEADER_BYTES + 4 * 2);
    expect(new DataView(wav).getInt16(WAV_HEADER_BYTES, true)).toBe(0x7fff);
  });

  it('writes the rate the hardware chose, not the one that was asked for', async () => {
    // #18's finding: a phone returns the rate it wanted. The recorder is asked
    // for 16 kHz and Android hands back 48. A clip that recorded the request
    // rather than the reality plays at a third speed, which is not speech.
    const clip = collectClip();
    clip.push(frames(), 48_000);

    const wav = await clip.finish().arrayBuffer();

    expect(new DataView(wav).getUint32(24, true)).toBe(48_000);
  });

  it('counts elapsed time from the samples, not from a clock', async () => {
    // A wall clock would keep counting while the microphone was stalled, which
    // is the reading that would tell somebody they had said five seconds of
    // nothing. Samples are what the server will be billed for hearing.
    const clip = collectClip();
    for (let i = 0; i < 25; i += 1) clip.push(frames(), 16_000);

    expect(clip.seconds()).toBe(2);
  });

  it('is a valid empty recording before anything is said', async () => {
    // Reachable by tapping Talk and then Done. The server answers that with
    // `nothing_was_said`, which is a sentence somebody can act on — but only if
    // the file parsed as audio. A zero-length body gets a vendor error instead,
    // and the user is told the recording broke when in fact they said nothing.
    const wav = await collectClip().finish().arrayBuffer();

    expect(wav.byteLength).toBe(WAV_HEADER_BYTES);
  });

  it('stops accepting audio at the ceiling instead of growing without bound', async () => {
    // The way to reach this is to tap Talk and put the phone down. Held as
    // Float32 and again as PCM, an hour of 16 kHz audio is hundreds of
    // megabytes — the app is killed, and from the user's side the debrief
    // simply vanished.
    const clip = collectClip();
    const second = new Float32Array(16_000);

    for (let i = 0; i < CLIP_CEILING_SECONDS + 30; i += 1) {
      clip.push(second, 16_000);
    }

    expect(clip.full()).toBe(true);
    expect(clip.seconds()).toBe(CLIP_CEILING_SECONDS);
  });

  it('keeps a ceiling under what the server will accept', async () => {
    // The server refuses past 10 MB. Filling to exactly that would trade a
    // sentence the app can say — "that is as long as I can listen in one go" —
    // for a 413 that arrives after the upload, having spent the bytes.
    expect(CLIP_CEILING_SECONDS * 16_000 * 2 + WAV_HEADER_BYTES).toBeLessThan(
      10 * 1024 * 1024
    );
  });
});
