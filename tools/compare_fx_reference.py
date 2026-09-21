#!/usr/bin/env python3
"""SXT-023 audio comparison: fixed-point effect-chain model vs pinned-engine
wet reference (stereo float32 fixture buses, native levels).

Policy (unchanged from SXT-022): no normalization, no time-warping, no
reference switching; raw per-sample differences at native level plus
onset-aligned spectra; budgets are [PROPOSED-TO-BE-FROZEN-AT-PILOT] — this
tool reports ACHIEVED numbers against explicitly-proposed budget values and
marks the verdict PENDING-FREEZE; it never declares fidelity established.

Units: differences are expressed in Q10.21 LSB (1 LSB = 2^-21 ≈ 4.77e-7) so
the budgets are comparable across the float32 buses and the fixed-point word.

Metrics per channel (L, R) and mono sum:
  max_abs_diff_lsb, rms_diff_lsb, rms_diff_dbfs (re 2^-21 full scale),
  best_shift ([-32, 32] scan; scheduling granularity is 32 samples),
  spectral_corr (Hann 4096 log-magnitude correlation).
"""

import argparse
import json
import sys

import numpy as np

# [PROPOSED-TO-BE-FROZEN-AT-PILOT] budgets for the SXT-023 effect slice
# (declared with the model; the delay line re-quantizes to Q10.21 and the
# engine computes the same structure in float32, so the residual is the
# fixed-vs-float quantization class; values are proposals, not frozen policy):
PROPOSED = {
    "max_abs_diff_lsb": 8192,       # ~ -18 dBFS equivalent
    "rms_diff_dbfs": -46.0,         # residual RMS at least this far below FS
    "spectral_corr_min": 0.98,
}

LSB = 2.0 ** -21


def read_wav_stereo_f32(path):
    import struct

    with open(path, "rb") as f:
        data = f.read()
    pos = 12
    fmt = None
    raw = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        sz = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + sz]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            raw = body
        pos += 8 + sz + (sz & 1)
    audio_fmt, nch, sr, _b, _a, bits = fmt
    if audio_fmt != 3 or bits != 32 or nch != 2:
        raise ValueError(f"expected stereo float32: {path}")
    a = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    return a.T.copy(), sr


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    if n < frame:
        return 1.0 if np.allclose(a, b) else 0.0
    ra = np.log1p(np.abs(np.fft.rfft(a[: n // frame * frame].reshape(-1, frame)
                                     * np.hanning(frame), axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b[: n // frame * frame].reshape(-1, frame)
                                     * np.hanning(frame), axis=1))).ravel()
    ra -= ra.mean()
    rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def channel_metrics(ref, mod):
    n = min(len(ref), len(mod))
    ref, mod = ref[:n].astype(np.float64), mod[:n].astype(np.float64)

    def rms_at(shift):
        if shift >= 0:
            r, m = ref[shift:], mod[: n - shift]
        else:
            r, m = ref[: n + shift], mod[-shift:]
        return float(np.sqrt(((r - m) ** 2).mean()))

    shifts = {s: rms_at(s) for s in range(-32, 33)}
    best_shift = min(shifts, key=shifts.get)
    d = np.abs(ref - mod)
    rms = float(np.sqrt((d * d).mean()))
    return {
        "frames": n,
        "ref_peak_lsb": float(np.abs(ref).max() / LSB),
        "model_peak_lsb": float(np.abs(mod).max() / LSB),
        "max_abs_diff_lsb": float(d.max() / LSB),
        "rms_diff_lsb": rms / LSB,
        "rms_diff_dbfs": float(20 * np.log10(rms / LSB / (1 << 20))),
        "rms_diff_at_shift0_lsb": shifts[0] / LSB,
        "best_shift": best_shift,
        "rms_diff_at_best_shift_lsb": shifts[best_shift] / LSB,
        "spectral_corr": spectral_corr(ref, mod),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True, help="engine wet stereo f32 WAV")
    ap.add_argument("--model", required=True, help="model wet stereo f32 WAV")
    ap.add_argument("--preset")
    ap.add_argument("--json", help="write metrics JSON here")
    args = ap.parse_args()

    ref, sr = read_wav_stereo_f32(args.ref)
    mod, sr2 = read_wav_stereo_f32(args.model)
    assert sr == sr2 == 48000, (sr, sr2)

    metrics = {"ref": args.ref, "model": args.model}
    if args.preset:
        metrics["preset"] = args.preset
    chs = {}
    for name, idx in (("L", 0), ("R", 1)):
        chs[name] = channel_metrics(ref[idx], mod[idx])
    chs["mono"] = channel_metrics(0.5 * (ref[0] + ref[1]), 0.5 * (mod[0] + mod[1]))
    metrics["channels"] = chs

    worst = chs["mono"]
    proposed_results = {
        "max_abs_diff_lsb": worst["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"] >= PROPOSED["spectral_corr_min"],
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
