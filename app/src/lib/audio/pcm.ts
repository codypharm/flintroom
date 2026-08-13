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
