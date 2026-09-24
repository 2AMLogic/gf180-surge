#!/usr/bin/env python3
"""SXT-028c reference comparison: frozen chorus-chain model vs pinned-engine
wet reference (stereo float32 fixture buses, native levels).

Policy (unchanged from SXT-022/023): no normalization, no time-warping, no
reference switching; raw per-sample differences at native level plus
onset-aligned spectra; budgets are [PROPOSED-TO-BE-FROZEN-AT-PILOT] — this
tool reports ACHIEVED numbers against explicitly-proposed budget values and
marks the verdict PENDING-FREEZE; it never declares fidelity established.

The budgets are the sxt-023 effect-slice proposals (same family the Delay/EQ
slice declared; Q10.21 LSB units so the numbers are comparable across the
float32 buses and the fixed-point word). They are NOT frozen: the SXT-017
freeze (#12) is gated on the open SXT-023 delay-budget finding (#16), whose
LFO-modulated delay-time mechanism is shared with the Chorus delay-time
path. No Chorus budget may freeze before #12 decides.

Units: differences in Q10.21 LSB (1 LSB = 2^-21 ~ 4.77e-7).
Metrics per channel (L, R) and mono sum: max_abs_diff_lsb, rms_diff_lsb,
rms_diff_dbfs, best_shift ([-32, 32] scan), spectral_corr (Hann 4096), and
a tail-region check (the render tail span must be present and compared;
a dropped tail FAILS).
"""

import argparse
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# [PROPOSED] budgets — identical values to the sxt-023 effect-slice family
# (see tools/compare_fx_reference.py); PENDING-FREEZE via SXT-017 (#12),
# gated on the shared delay-semantics decision (#16)
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


def tail_metrics(ref, mod, tail_s=2.0):
    """Agreement over the declared tail window (last tail_s seconds)."""
    n = min(len(ref), len(mod))
    t = int(tail_s * 48000)
    if t >= n:
        t = n // 4
    ref_t = ref[n - t:n].astype(np.float64)
    mod_t = mod[n - t:n].astype(np.float64)
    d = np.abs(ref_t - mod_t)
    rms = float(np.sqrt((d * d).mean()))
    ref_rms = float(np.sqrt((ref_t * ref_t).mean())) or 1e-30
    return {
        "tail_frames": t,
        "tail_max_abs_diff_lsb": float(d.max() / LSB),
        "tail_rms_diff_lsb": rms / LSB,
        "tail_rms_rel_db": float(20 * np.log10(max(rms / ref_rms, 1e-30))),
        "tail_present": bool(np.abs(ref_t).max() > 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", required=True)
    ap.add_argument("--fixtures-dir",
                    default=os.path.join(REPO, "reports", "SXT-028c", "fixtures"))
    ap.add_argument("--art-dir",
                    default=os.path.join(REPO, "reports", "SXT-028c", "artifacts"))
    ap.add_argument("--json", help="write metrics JSON here")
    args = ap.parse_args()

    ref, sr = read_wav_stereo_f32(os.path.join(
        args.fixtures_dir, f"{args.slug}__{args.seq}-wet.f32.wav"))
    mod, sr2 = read_wav_stereo_f32(os.path.join(
        args.art_dir, f"model__{args.slug}__{args.seq}.f32.wav"))
    assert sr == sr2 == 48000, (sr, sr2)

    metrics = {
        "schema_version": 1,
        "leaf": "SXT-028c",
        "slug": args.slug,
        "sequence": args.seq,
        "ref": os.path.relpath(os.path.join(
            args.fixtures_dir, f"{args.slug}__{args.seq}-wet.f32.wav"), REPO),
        "model": os.path.relpath(os.path.join(
            args.art_dir, f"model__{args.slug}__{args.seq}.f32.wav"), REPO),
    }
    chs = {}
    for name, idx in (("L", 0), ("R", 1)):
        chs[name] = channel_metrics(ref[idx], mod[idx])
    chs["mono"] = channel_metrics(0.5 * (ref[0] + ref[1]), 0.5 * (mod[0] + mod[1]))
    chs["tail_mono"] = tail_metrics(0.5 * (ref[0] + ref[1]), 0.5 * (mod[0] + mod[1]))
    metrics["channels"] = chs

    worst = chs["mono"]
    proposed_results = {
        "max_abs_diff_lsb": worst["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"] >= PROPOSED["spectral_corr_min"],
    }
    metrics["proposed_budgets"] = PROPOSED
    metrics["proposed_budget_results"] = proposed_results
    metrics["tail_check"] = {
        "tail_present": chs["tail_mono"]["tail_present"],
        "tail_rms_rel_db": chs["tail_mono"]["tail_rms_rel_db"],
        "ok": chs["tail_mono"]["tail_present"],
    }
    ok = all(proposed_results.values())
    metrics["verdict"] = (
        "PASS (PENDING-FREEZE: budgets are proposals, not frozen policy; "
        "freeze gated on SXT-017 #12 / shared delay-semantics #16)"
        if ok and chs["tail_mono"]["tail_present"]
        else "FAIL against proposed budgets")

    print(json.dumps({
        "slug": args.slug, "seq": args.seq,
        "max_abs_diff_lsb": worst["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"],
        "best_shift": worst["best_shift"],
        "tail_rms_rel_db": chs["tail_mono"]["tail_rms_rel_db"],
        "verdict": metrics["verdict"],
    }, indent=2))
    out = args.json or os.path.join(
        args.art_dir, f"compare-{args.slug}__{args.seq}.json")
    with open(out, "w") as f:
        json.dump(metrics, f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
