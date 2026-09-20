#!/usr/bin/env python3
"""SXT-022 audio comparison: frozen fixed-point model render vs pinned-engine
reference render (fixtures harness, mono int16 WAV, native levels).

Policy (contracts/fidelity-policy-DRAFT.md):
  * no normalization, no time-warping, no reference switching;
  * raw per-sample differences at native level, plus onset-aligned spectra;
  * budgets are [PROPOSED-TO-BE-FROZEN-AT-PILOT]: this tool reports ACHIEVED
    numbers against the explicitly-proposed budget values below and marks the
    verdict PENDING-FREEZE -- it never declares fidelity established.

Metrics (on int16 LSB units):
  max_abs_diff        max |ref - model| over the render
  rms_diff            RMS of (ref - model)
  rms_diff_dbfs       RMS difference relative to full scale (32767)
  best_shift          integer sample shift in [-32, 32] minimizing RMS diff
                      (the SXT-012 scheduling granularity bound); shift 0 is
                      reported separately because the model schedules events
                      identically to the render harness
  spectral_corr       correlation of log-magnitude spectra over the whole
                      render (Hann-windowed, averaged per 4096-sample frame)

Usage:
  python3 tools/compare_audio_reference.py --ref REF.wav --model MODEL.wav \
      [--json OUT.json]
"""

import argparse
import json
import sys
import wave

import numpy as np

# [PROPOSED-TO-BE-FROZEN-AT-PILOT] budget placeholders (SXT-022 proposal,
# derived from the SXT-012 free-phase escalation: raw subtraction is not
# expected to be exact across uncontrolled engine noise; these numbers are
# proposals for the pilot freeze, not frozen policy):
PROPOSED = {
    "max_abs_diff_lsb": 3500,       # ~ -19.4 dBFS equivalent
    "rms_diff_dbfs": -46.0,         # residual RMS at least this far below FS
    "spectral_corr_min": 0.98,
}


def read_wav(path):
    with wave.open(path) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, path
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return a.astype(np.float64), sr


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    ra = np.log1p(np.abs(np.fft.rfft(a[: n // frame * frame].reshape(-1, frame)
                                      * np.hanning(frame), axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b[: n // frame * frame].reshape(-1, frame)
                                      * np.hanning(frame), axis=1))).ravel()
    ra -= ra.mean(); rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--json", help="write metrics JSON here")
    args = ap.parse_args()

    ref, sr = read_wav(args.ref)
    mod, sr2 = read_wav(args.model)
    assert sr == sr2 == 48000, (sr, sr2)
    n = min(len(ref), len(mod))
    ref, mod = ref[:n], mod[:n]
    peak = float(np.abs(ref).max()) or 1.0

    def rms_at(shift):
        if shift >= 0:
            r, m = ref[shift:], mod[: n - shift]
        else:
            r, m = ref[: n + shift], mod[-shift:]
        return float(np.sqrt(((r - m) ** 2).mean()))

    shifts = {s: rms_at(s) for s in range(-32, 33)}
    best_shift = min(shifts, key=shifts.get)

    d = np.abs(ref - mod)
    metrics = {
        "frames": n,
        "ref_peak_lsb": peak,
        "model_peak_lsb": float(np.abs(mod).max()),
        "max_abs_diff_lsb": float(d.max()),
        "rms_diff_lsb": float(np.sqrt((d * d).mean())),
        "rms_diff_dbfs": float(20 * np.log10(np.sqrt((d * d).mean()) / 32767.0)),
        "rms_diff_at_shift0_lsb": shifts[0],
        "best_shift": best_shift,
        "rms_diff_at_best_shift_lsb": shifts[best_shift],
        "spectral_corr": spectral_corr(ref, mod),
    }

    proposed_results = {
        "max_abs_diff_lsb": metrics["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": metrics["rms_diff_dbfs"] >= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": metrics["spectral_corr"] >= PROPOSED["spectral_corr_min"],
    }
    metrics["proposed_budgets"] = PROPOSED
    metrics["proposed_budget_results"] = proposed_results
    metrics["verdict"] = ("PASS (PENDING-FREEZE: budgets are proposals, not "
                          "frozen policy)" if all(proposed_results.values())
                          else "FAIL against proposed budgets")
    print(json.dumps(metrics, indent=2))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(metrics, f, indent=2)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
