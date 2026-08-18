import { toPcm16 } from './pcm';
import { toWav, WAV_HEADER_BYTES } from './wav';

/**
 * The container a coaching turn arrives in.
 *
 * `POST /v1/sessions/{id}/debrief/turns` proxies the clip to a transcriber, and
 * a transcriber is handed a file rather than a stream of samples. This is the
 * 44 bytes that turn what the recorder already produces into one.
 *
 * Written rather than depended on. `toPcm16` already emits exactly the payload
 * a PCM WAV carries, so the alternative was `expo-audio` for a header — a
 * dependency `CLAUDE.md` would want justified, on a library #25 is already
 * scheduled to replace.
 *
 * These assertions are byte offsets because that is what a decoder reads. A
 * header that is *nearly* right does not fail loudly: it produces a file that
 * plays at the wrong speed, or one the vendor rejects with a message about the
 * audio being unintelligible, which reads as a transcription problem.
 */

/** Little-endian, as every field in a RIFF header is. */
function u32(wav: ArrayBuffer, at: number): number {
  return new DataView(wav).getUint32(at, true);
}

function u16(wav: ArrayBuffer, at: number): number {
  return new DataView(wav).getUint16(at, true);
}

function ascii(wav: ArrayBuffer, at: number, length: number): string {
  return String.fromCharCode(...new Uint8Array(wav, at, length));
}

/** A quarter second of tone, so a wrong sample rate is arithmetically visible. */
function tone(samples: number): Float32Array {
  const wave = new Float32Array(samples);
  for (let i = 0; i < samples; i += 1) {
    wave[i] = Math.sin((2 * Math.PI * 440 * i) / 16_000);
  }
  return wave;
}

describe('toWav', () => {
  it('opens with the three chunk names a decoder looks for', () => {
    const wav = toWav(tone(64), 16_000);

    expect(ascii(wav, 0, 4)).toBe('RIFF');
    expect(ascii(wav, 8, 4)).toBe('WAVE');
    expect(ascii(wav, 12, 4)).toBe('fmt ');
    // The trailing space in `fmt ` is not a typo and is the single most common
    // way this header is written wrong. A three-character chunk name shifts
    // every field after it by one byte.
    expect(ascii(wav, 36, 4)).toBe('data');
  });

  it('declares mono 16-bit PCM', () => {
    const wav = toWav(tone(64), 16_000);

    expect(u32(wav, 16)).toBe(16); // fmt chunk length, fixed for PCM
    expect(u16(wav, 20)).toBe(1); // format 1 is uncompressed PCM
    expect(u16(wav, 22)).toBe(1); // one channel
    expect(u16(wav, 34)).toBe(16); // bits per sample
  });

  it('carries the rate it was recorded at, not an assumed one', () => {
    // The recorder's rate is a property of the hardware — #18 exists because
    // Android hands back 48 kHz whatever is asked for. A header hardcoded to
    // 16 kHz would make a 48 kHz clip play at a third speed, and speech slowed
    // to a third is not speech a transcriber can hear.
    const wav = toWav(tone(64), 48_000);

    expect(u32(wav, 24)).toBe(48_000);
    // Byte rate and block align are derived, and a decoder that trusts them
    // over the sample rate exists. Mono 16-bit: two bytes a frame.
    expect(u32(wav, 28)).toBe(48_000 * 2);
    expect(u16(wav, 32)).toBe(2);
  });

  it('states both lengths in the two places a header states them', () => {
    const samples = tone(1600);
    const wav = toWav(samples, 16_000);

    // RIFF's length excludes the first eight bytes — the name and the field
    // itself. Writing the whole file length here is the second classic error,
    // and ffmpeg forgives it while stricter decoders do not.
    expect(u32(wav, 4)).toBe(WAV_HEADER_BYTES - 8 + samples.length * 2);
    expect(u32(wav, 40)).toBe(samples.length * 2);
    expect(wav.byteLength).toBe(WAV_HEADER_BYTES + samples.length * 2);
  });

  it('carries exactly the bytes toPcm16 would have produced', () => {
    // The header is the whole of this function's job. If the payload were
    // re-derived here rather than delegated, the two encoders could drift and
    // the room's uplink and the coach's clip would disagree about what a
    // clipped peak sounds like.
    const samples = tone(256);
    const wav = toWav(samples, 16_000);

    expect(new Uint8Array(wav, WAV_HEADER_BYTES)).toEqual(
      new Uint8Array(toPcm16(samples))
    );
  });

  it('writes a valid header for a clip with no samples in it', () => {
    // Reachable: somebody taps record and taps stop. The server answers that
    // with `nothing_was_said`, which is a sentence a person can act on — but
    // only if what it received parsed as audio at all. A malformed file gets a
    // vendor error instead, and the user is told the recording failed when
    // what actually happened is that they did not speak.
    const wav = toWav(new Float32Array(0), 16_000);

    expect(wav.byteLength).toBe(WAV_HEADER_BYTES);
    expect(u32(wav, 40)).toBe(0);
    expect(ascii(wav, 0, 4)).toBe('RIFF');
  });
});
