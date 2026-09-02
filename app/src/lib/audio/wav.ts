import { toPcm16 } from './pcm';

/**
 * PCM16 samples, wrapped as a file something else can open.
 *
 * The room streams raw samples over a socket to a relay that knows what they
 * are. A coaching turn does not: `POST /v1/sessions/{id}/debrief/turns` hands
 * the clip to a transcription vendor, and a vendor is given a file with a
 * format in it. These 44 bytes are the difference.
 *
 * **No dependency.** `expo-audio` would record straight to a container, and
 * it would also mean a second recording stack beside the owned capture module
 * (#25) for the sake of a header that is fully specified in one page of the
 * RIFF document. `toPcm16` already produces the payload; this writes what
 * sits in front of it.
 */

/** Canonical PCM: RIFF, fmt and data, with nothing optional in between. */
export const WAV_HEADER_BYTES = 44;

/** Uncompressed PCM. The only format this writes and the only one it claims. */
const FORMAT_PCM = 1;

const CHANNELS = 1;
const BITS_PER_SAMPLE = 16;
const BYTES_PER_FRAME = (CHANNELS * BITS_PER_SAMPLE) / 8;

export function toWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const payload = new Uint8Array(toPcm16(samples));
  const wav = new ArrayBuffer(WAV_HEADER_BYTES + payload.byteLength);
  const header = new DataView(wav);

  const name = (at: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) {
      header.setUint8(at + i, text.charCodeAt(i));
    }
  };

  name(0, 'RIFF');
  // Everything after this field, which is the file minus the first eight bytes
  // — not the file length. Lenient decoders accept the wrong one, which is why
  // it survives long enough to reach a strict one.
  header.setUint32(4, WAV_HEADER_BYTES - 8 + payload.byteLength, true);
  name(8, 'WAVE');

  name(12, 'fmt ');
  header.setUint32(16, 16, true);
  header.setUint16(20, FORMAT_PCM, true);
  header.setUint16(22, CHANNELS, true);
  // The rate is passed in rather than fixed at the protocol's 16 kHz, because
  // this wraps whatever the hardware gave us. #18 exists because a phone
  // returns the rate it chose, not the rate it was asked for, and a header
  // that disagrees with its payload plays the speech at the wrong speed.
  header.setUint32(24, sampleRate, true);
  header.setUint32(28, sampleRate * BYTES_PER_FRAME, true);
  header.setUint16(32, BYTES_PER_FRAME, true);
  header.setUint16(34, BITS_PER_SAMPLE, true);

  name(36, 'data');
  header.setUint32(40, payload.byteLength, true);

  new Uint8Array(wav, WAV_HEADER_BYTES).set(payload);

  return wav;
}
