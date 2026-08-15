/**
 * Float32 from the recorder to PCM16 for the wire.
 *
 * `docs/voice-stream-protocol.md` fixes the uplink as PCM16, 16 kHz, mono, and
 * the relay transcodes nothing — what this function produces is what reaches
 * the voice provider.
 */
export function toPcm16(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);

  for (let i = 0; i < samples.length; i += 1) {
    // Clamped before scaling, because `setInt16` takes its argument modulo
    // 2^16 and would turn a clipped peak into a full-amplitude sample of the
    // opposite sign — a click, and one the provider's VAD can hear as speech.
    const clamped = Math.max(-1, Math.min(1, samples[i]));

    // Explicit little-endian rather than relying on the platform's native
    // order. Every device we ship to is little-endian, so this is not a
    // portability hedge — it is that the byte order of the wire format should
    // be stated by the code that writes it, not inferred from the hardware.
    //
    // Scaled by 0x7FFF in both directions. Int16 reaches -32768, so this gives
    // up one value at the negative extreme; the alternative is asymmetric gain
    // between the halves of the waveform, which is a worse trade for a signal
    // that exists to be transcribed.
    view.setInt16(i * 2, Math.round(clamped * 0x7fff), true);
  }

  return buffer;
}

/**
 * PCM16 from the wire back to Float32 for playback.
 *
 * The exact inverse of `toPcm16`, and scaled by the same 0x7FFF so the pair
 * agree at full scale. Dividing by 0x8000 instead would attenuate every sample
 * by a fraction of a dB — inaudible, permanent, and the kind of thing nobody
 * thinks to look for once they have stopped hearing it.
 */
export function fromPcm16(buffer: ArrayBuffer): Float32Array {
  const view = new DataView(buffer);
  const samples = new Float32Array(buffer.byteLength / 2);

  for (let i = 0; i < samples.length; i += 1) {
    // Little-endian stated explicitly, for the same reason it is stated when
    // writing: the wire format's byte order belongs in the code that reads it,
    // not inferred from whatever the device happens to be.
    samples[i] = view.getInt16(i * 2, true) / 0x7fff;
  }

  return samples;
}

/**
 * Linear resampling between two sample rates.
 *
 * The protocol fixes 16 kHz on the wire, but a device output stream runs at
 * whatever rate the hardware chose — 48 kHz on every Android phone we have
 * touched. `createBuffer` takes a rate argument and does not honour it on
 * playback, so 16 kHz samples handed to a 48 kHz context come out three times
 * too fast. That is not a cosmetic bug: sped-up speech is not speech, and the
 * echo verdict is decided by a speech detector.
 *
 * Linear rather than windowed-sinc deliberately. The imaging artefacts of
 * linear interpolation sit above 8 kHz, where a 16 kHz source has nothing to
 * begin with, and the cost is a loop the audio thread can afford. If we ever
 * resample *down* this choice has to be revisited — decimating without a
 * low-pass filter aliases, and aliasing is audible.
 */
export function resampleLinear(
  samples: Float32Array,
  fromRate: number,
  toRate: number
): Float32Array {
  // Returned as-is rather than copied: the common case on iOS, where the
  // hardware may already be at the rate we want, and an allocation per buffer
  // in the playback path is worth avoiding.
  if (fromRate === toRate || samples.length === 0) {
    return samples;
  }

  const ratio = toRate / fromRate;
  const length = Math.round(samples.length * ratio);
  const out = new Float32Array(length);

  for (let i = 0; i < length; i += 1) {
    const position = i / ratio;
    const left = Math.floor(position);
    const fraction = position - left;
    // Clamped rather than read blindly. The final output sample interpolates
    // against a neighbour past the end of the input; `samples[left + 1]` would
    // be `undefined`, the arithmetic would give NaN, and NaN in an audio buffer
    // is silence — a failure that looks like the microphone not working.
    const right = Math.min(left + 1, samples.length - 1);

    out[i] = samples[left] + (samples[right] - samples[left]) * fraction;
  }

  return out;
}
