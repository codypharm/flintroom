import { toPcm16 } from './pcm';

/**
 * The conversion between what the recorder gives and what the wire takes.
 *
 * `react-native-audio-api` emits normalised Float32 (-1.0 to 1.0); the stream
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
