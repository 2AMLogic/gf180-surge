#!/usr/bin/env python3
"""SXT-043 valid-reference gate (issue #329).  Pure numpy; no oracle.

A reference render may only anchor a model-vs-reference budget comparison if
it is demonstrably the declared fixture configuration's sound: a Sine slot
playing the probe key.  #311 showed two ways a "reference" can be invalid
while still being produced without error:

  * SILENCE -- the Sine oscillator's integer Shape selector is corrupted by a
    surviving float modulation route, the oscillator never writes its
    buffer, and a fresh engine renders all-zero;
  * STALE / NON-PITCHED -- the same, after a prior note: the untouched
    buffer replays leftover non-Sine data (observed dominant ~1.46 kHz at
    key 60), which is nonzero but not the probe key's fundamental.

Peak alone therefore cannot validate a reference.  This gate requires all of
the following on a HELD segment (outside the onset, the velocity smoother
settle and any portamento; the probe is a single fresh note, which
pm_mono_st_fp anchors at its own pitch, so no glide occurs):

  1. peak over the segment >= PEAK_MIN;
  2. dominant frequency within PITCH_TOL_CENTS of the expected fundamental
     f0 = 440 * 2 ** ((key + 12 * (scene_octave + osc_octave) + pitch - 69)
     / 12)  (standard 12-TET tuning, A4 = 440 Hz -- the declared tuning of
     this leaf; microtuning is refused upstream);
  3. at least PURITY_MIN of the segment's spectral power lies within
     +-PURITY_BAND_CENTS of f0 (a Sine slice is spectrally pure; a stale
     buffer or broadband junk is not).

Every threshold is DECLARED HERE, before any measurement, and is not tuned
to a result.  The gate's verdict is PASS (valid reference) or FAIL (NOT A
VALID COMPARISON) with the failed legs listed.  It establishes only that the
render is a pitched, nonzero rendering of the probe key; it says nothing
about model-vs-reference agreement or sound quality.
"""

import math

import numpy as np

SR = 48000

# ---- declared probe (single fresh note) ---------------------------------
PROBE_KEY = 60
PROBE_VELOCITY = 100
PROBE_SETTLE_S = 0.25        # pre-roll discarded, as the fixture harness
PROBE_HOLD_S = 1.0           # note-on .. note-off
PROBE_TAIL_S = 0.25
# held analysis segment, measured from note-on
SEGMENT_START_S = 0.30
SEGMENT_END_S = 0.80

# ---- declared thresholds ------------------------------------------------
PEAK_MIN = 1.0e-3            # float full scale (~33 int16 LSB)
PITCH_TOL_CENTS = 25.0
PURITY_BAND_CENTS = 100.0
PURITY_MIN = 0.5
SEARCH_HZ = (20.0, 20000.0)
ZERO_PAD = 8

DECLARED = {
    "probe": {"key": PROBE_KEY, "velocity": PROBE_VELOCITY,
              "settle_s": PROBE_SETTLE_S, "hold_s": PROBE_HOLD_S,
              "tail_s": PROBE_TAIL_S},
    "segment_from_note_on_s": [SEGMENT_START_S, SEGMENT_END_S],
    "peak_min": PEAK_MIN,
    "pitch_tol_cents": PITCH_TOL_CENTS,
    "purity_band_cents": PURITY_BAND_CENTS,
    "purity_min": PURITY_MIN,
    "tuning": "standard 12-TET, A4 (key 69) = 440 Hz",
    "estimator": "Hann window, %dx zero-pad rfft, parabolic interpolation "
                 "on log magnitude, search %g-%g Hz" % ((ZERO_PAD,)
                                                       + SEARCH_HZ),
}


def expected_f0(key, scene_octave, osc_octave=0, pitch=0.0):
    """Sine fundamental for `key` under standard tuning (keytrack on)."""
    semis = key + 12 * (scene_octave + osc_octave) + pitch - 69
    return 440.0 * 2.0 ** (semis / 12.0)


def cents(f, ref):
    if f <= 0 or ref <= 0:
        return math.inf
    return 1200.0 * math.log2(f / ref)


def dominant_frequency(x, sr=SR):
    """(f_hz, power_spectrum, freqs) of a segment; f_hz None if silent."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n < 16:
        raise ValueError("segment too short: %d samples" % n)
    w = np.hanning(n)
    nfft = 1 << int(math.ceil(math.log2(n * ZERO_PAD)))
    spec = np.abs(np.fft.rfft(x * w, nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
    band = (freqs >= SEARCH_HZ[0]) & (freqs <= SEARCH_HZ[1])
    if not np.any(spec[band] > 0):
        return None, spec, freqs
    idx = np.flatnonzero(band)
    i = int(idx[np.argmax(spec[band])])
    f = freqs[i]
    if 0 < i < len(spec) - 1:
        a, b, c = (math.log(max(v, 1e-300)) for v in spec[i - 1:i + 2])
        den = a - 2 * b + c
        if den != 0:
            f = freqs[i] + 0.5 * (a - c) / den * (freqs[1] - freqs[0])
    return float(f), spec, freqs


def held_segment(mono, note_on_sample, sr=SR):
    a = note_on_sample + int(round(SEGMENT_START_S * sr))
    b = note_on_sample + int(round(SEGMENT_END_S * sr))
    if b > len(mono):
        raise ValueError("render shorter than the declared held segment")
    return np.asarray(mono[a:b], dtype=np.float64)


def check(mono, note_on_sample, f0, sr=SR):
    """Apply the declared gate.  Returns a JSON-serializable record."""
    seg = held_segment(mono, note_on_sample, sr)
    peak = float(np.max(np.abs(seg))) if len(seg) else 0.0
    rec = {"declared": DECLARED, "expected_f0_hz": f0,
           "segment_samples": [note_on_sample + int(round(SEGMENT_START_S * sr)),
                               note_on_sample + int(round(SEGMENT_END_S * sr))],
           "peak_abs": peak, "peak_abs_full_render":
               float(np.max(np.abs(mono))) if len(mono) else 0.0}
    fails = []
    if not (peak >= PEAK_MIN):
        fails.append("silent: held-segment peak %.3g < %.3g" % (peak, PEAK_MIN))
    f, spec, freqs = dominant_frequency(seg, sr)
    rec["dominant_hz"] = f
    if f is None:
        rec["pitch_error_cents"] = None
        rec["purity"] = 0.0
        if "silent" not in " ".join(fails):
            fails.append("no spectral content in the search band")
    else:
        err = cents(f, f0)
        rec["pitch_error_cents"] = err
        if not abs(err) <= PITCH_TOL_CENTS:
            fails.append("dominant %.2f Hz is %.1f cents from expected "
                         "%.2f Hz (tol %.0f)" % (f, err, f0, PITCH_TOL_CENTS))
        lo = f0 * 2.0 ** (-PURITY_BAND_CENTS / 1200.0)
        hi = f0 * 2.0 ** (PURITY_BAND_CENTS / 1200.0)
        total = float(np.sum(spec))
        near = float(np.sum(spec[(freqs >= lo) & (freqs <= hi)]))
        purity = near / total if total > 0 else 0.0
        rec["purity"] = purity
        if not purity >= PURITY_MIN:
            fails.append("purity %.3f < %.2f within +-%.0f cents of f0"
                         % (purity, PURITY_MIN, PURITY_BAND_CENTS))
    rec["fails"] = fails
    rec["verdict"] = "PASS" if not fails else "FAIL"
    rec["meaning"] = ("valid reference: nonzero, pitched at the probe key"
                      if not fails else "NOT A VALID COMPARISON")
    return rec
