import { fromPcm16, resampleLinear, toPcm16 } from './pcm';

/**
 * The conversion between what the recorder gives and what the wire takes.
 *
 * The owned capture module emits normalised Float32 (-1.0 to 1.0); the stream
 * protocol carries PCM16 little-endian. Nothing else in the client does
 * arithmetic on audio, so this is the whole of the risk — and it is worth real
 * tests because every way it can go wrong is inaudible in review and obvious in
 * a live room.
 */
describe('toPcm16', () => {
  it('writes little-endian samples, because that is what the wire expects', () => {
    // 1/4 of full scale: 0.25 * 32767 = 8191.75, rounding to 8192 = 0x2000.
    // Asserted as bytes rather than as a number, since the byte order is the
    // part that cannot be checked by reading the code back.
    const bytes = new Uint8Array(toPcm16(new Float32Array([0.25])));

    expect(Array.from(bytes)).toEqual([0x00, 0x20]);
  });

  it('clamps past full scale instead of wrapping', () => {
    // A sample above 1.0 is not hypothetical: a loud speaker close to the mic
    // clips, and any client-side gain pushes peaks over. `setInt16` takes the
    // value modulo 2^16, so 1.5 would silently land at -16385 — a peak flipped
    // to its opposite sign, which is a hard click rather than a loud sample.
    // Barge-in is driven by the provider's VAD reading this audio, so a click
    // is not merely ugly: it is a false trigger.
    const loud = new Int16Array(toPcm16(new Float32Array([1.5, -1.5])));

    expect(Array.from(loud)).toEqual([32767, -32767]);
  });
});

describe('fromPcm16', () => {
  it('reads little-endian, matching what toPcm16 wrote', () => {
    // Downlink audio arrives in the same format the uplink sends, so getting the
    // byte order wrong here produces noise rather than a panelist — and noise
    // that still has the right duration and level, which is a confusing way to
    // discover an endianness bug.
    const bytes = new Uint8Array([0x00, 0x20]).buffer;

    expect(Array.from(fromPcm16(bytes))).toEqual([expect.closeTo(0.25, 4)]);
  });

  it('round-trips through toPcm16 within quantisation error', () => {
    // The pair has to agree, and the only honest way to state that is to send a
    // signal through both. Tolerance is one 16-bit step, which is what the
    // format costs and not a bug either function can fix.
    const original = new Float32Array([0, 0.5, -0.5, 0.999, -0.999]);
    const returned = fromPcm16(toPcm16(original));

    original.forEach((sample, i) => {
      expect(returned[i]).toBeCloseTo(sample, 4);
    });
  });

  it('reaches full scale, so playback is not quietly attenuated', () => {
    // Scaling by 0x8000 on the way back would shave every sample slightly and
    // show up as the panel sounding fractionally quiet — a difference nobody
    // hears and everybody would stop looking for.
    expect(fromPcm16(new Int16Array([32767]).buffer)[0]).toBeCloseTo(1, 4);
  });
});

describe('resampleLinear', () => {
  it('stretches when the target rate is higher, so speech is not sped up', () => {
    // The bug this exists to stop. The panel asset is 16 kHz; the device output
    // runs at 48 kHz. Handing 16 kHz samples straight to a 48 kHz context plays
    // them three times too fast, which is not speech and cannot be judged by a
    // speech detector.
    const out = resampleLinear(new Float32Array([0, 1]), 16000, 48000);

    expect(out.length).toBe(6);
  });

  it('interpolates between samples rather than repeating them', () => {
    // Nearest-neighbour would give [0, 0, 1] and a staircase that adds harmonics
    // right where a VAD is listening.
    const out = resampleLinear(new Float32Array([0, 1]), 1, 2);

    expect(out[0]).toBeCloseTo(0, 4);
    expect(out[1]).toBeCloseTo(0.5, 4);
  });

  it('is a no-op when the rates already agree', () => {
    const original = new Float32Array([0.1, -0.2, 0.3]);

    expect(Array.from(resampleLinear(original, 16000, 16000))).toEqual(
      Array.from(original)
    );
  });

  it('never reads past the end of the input', () => {
    // The last output sample interpolates against a neighbour that does not
    // exist. Reading it as undefined yields NaN, which propagates through the
    // whole buffer as silence — a failure that looks like the mic not working.
    const out = resampleLinear(new Float32Array([0.5, 0.5, 0.5]), 1, 3);

    expect(Array.from(out).every(Number.isFinite)).toBe(true);
  });
});
