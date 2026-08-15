import {
  echoAboveFloorDb,
  hasEcho,
  isGatedFloor,
  median,
  rms,
  toDbfs,
} from './level';

/**
 * Signal level arithmetic for the echo spike (task #17).
 *
 * These three functions decide whether the spike reports "AEC works" or "AEC
 * does not work", so a quiet arithmetic error here would produce a confident
 * wrong answer about the single risk that gates the audio layer. Each test
 * below is a way that has actually happened to somebody.
 */
describe('rms', () => {
  it('is the root mean square, not the mean absolute value', () => {
    // The distinction only shows up on a signal that varies. For a half-scale
    // square wave the two agree, so it is tested with a sine instead: mean
    // absolute value of a sine is 2/pi (0.637), RMS is 1/sqrt(2) (0.707). An
    // implementation that averages magnitudes lands on the first and quietly
    // understates every level by about 1 dB.
    const sine = new Float32Array(1000);
    for (let i = 0; i < sine.length; i += 1) {
      sine[i] = Math.sin((2 * Math.PI * i) / 1000);
    }

    expect(rms(sine)).toBeCloseTo(Math.SQRT1_2, 3);
  });

  it('is zero for digital silence', () => {
    expect(rms(new Float32Array(256))).toBe(0);
  });

  it('is the magnitude for a constant signal, sign notwithstanding', () => {
    // Guards the squaring: a negative DC offset must not produce a negative
    // level, which would then make the dB conversion NaN.
    expect(rms(new Float32Array([-0.5, -0.5, -0.5, -0.5]))).toBeCloseTo(0.5, 6);
  });
});

describe('toDbfs', () => {
  it('puts full scale at 0 dBFS', () => {
    expect(toDbfs(1)).toBeCloseTo(0, 6);
  });

  it('puts half amplitude at about -6 dBFS', () => {
    expect(toDbfs(0.5)).toBeCloseTo(-6.02, 1);
  });

  it('floors digital silence instead of returning -Infinity', () => {
    // A recorder that hands back an all-zero buffer is normal — it happens on
    // the first callback before the stream has warmed up. `Math.log10(0)` is
    // -Infinity, which formats as "-Infinity dB" in the report and turns any
    // subsequent subtraction into NaN. The floor keeps the spike readable when
    // the very thing it measures is absence of signal.
    expect(toDbfs(0)).toBe(-120);
  });
});

describe('isGatedFloor', () => {
  it('recognises a floor that has been gated to digital silence', () => {
    // Requesting VOICE_COMMUNICATION on Android turns on noise suppression as
    // well as echo cancellation, and NS zeroes a quiet room outright. Measured
    // on an S24+: 39 buffers delivered during the silent phase, every sample
    // zero. The floor then pins at the clamp.
    expect(isGatedFloor(-120)).toBe(true);
  });

  it('treats an ordinary quiet room as not gated', () => {
    // The stock library measured -57.3 dBFS in the same room.
    expect(isGatedFloor(-57.3)).toBe(false);
  });
});

describe('hasEcho', () => {
  it('uses the ratio when there is a real floor to compare against', () => {
    // Stock library, measured: -57.3 floor, -26.6 during playback. 30.7 dB up.
    expect(hasEcho(-57.3, -26.6)).toBe(true);
  });

  it('passes a real floor that playback barely lifts', () => {
    expect(hasEcho(-57.3, -55.0)).toBe(false);
  });

  it('falls back to an absolute level when the floor is gated', () => {
    // The bug this function exists to prevent. With the floor pinned at -120,
    // "echo above floor" is ~110 dB whether the canceller works perfectly or
    // not at all, so the ratio cannot decide anything. Judge the playback level
    // on its own terms instead: -10.2 dBFS is a mic hearing a loud speaker.
    expect(hasEcho(-120, -10.2)).toBe(true);
  });

  it('passes a gated floor when playback stays genuinely quiet', () => {
    // What a working canceller looks like once NS is also in the path: the
    // room gates to silence, and playback fails to lift it appreciably.
    expect(hasEcho(-120, -70)).toBe(false);
  });
});

describe('median', () => {
  it('ignores a single loud outlier, which a mean would not', () => {
    // The reason the spike medians its per-buffer levels instead of averaging
    // them. One chair creak during the silent phase would drag a mean noise
    // floor upward, and a falsely high floor makes echo look *smaller* than it
    // is — the failure direction that produces a wrong go decision.
    const withCreak = [0.001, 0.001, 0.001, 0.001, 0.9];

    expect(median(withCreak)).toBeCloseTo(0.001, 6);
  });

  it('averages the middle pair when the count is even', () => {
    expect(median([1, 2, 3, 4])).toBeCloseTo(2.5, 6);
  });

  it('does not disturb the caller’s array', () => {
    // Sorting in place would reorder the per-buffer series the caller may still
    // want to log, and the bug would only appear in the report, not here.
    const levels = [3, 1, 2];
    median(levels);

    expect(levels).toEqual([3, 1, 2]);
  });

  it('is zero for no samples at all', () => {
    // A recorder that never fired its callback is a real outcome — it is what a
    // denied microphone permission looks like from here. Returning 0 keeps the
    // report finite so it can say "no signal" rather than "NaN".
    expect(median([])).toBe(0);
  });
});

describe('echoAboveFloorDb', () => {
  it('reports how far playback sits above the silent noise floor', () => {
    // The number the spike exists to produce. Playback ten times the amplitude
    // of the noise floor is 20 dB above it.
    expect(echoAboveFloorDb(0.001, 0.01)).toBeCloseTo(20, 1);
  });

  it('is positive when echo is present, so the sign cannot be misread', () => {
    // Sign convention is the easiest thing to invert, and inverting it turns
    // "30 dB of echo leaking in" into "30 dB of suppression" — a go decision on
    // a no-go result. Asserted as a direction, not just a magnitude.
    expect(echoAboveFloorDb(0.001, 0.1)).toBeGreaterThan(0);
  });

  it('is about zero when playback is inaudible over the floor', () => {
    // What a working AEC looks like: the mic hears no more during playback than
    // it did in silence.
    expect(echoAboveFloorDb(0.002, 0.002)).toBeCloseTo(0, 6);
  });
});
