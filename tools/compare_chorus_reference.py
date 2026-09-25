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
rms_diff_dbfs (clamped to a finite floor under exact agreement, issue #100),
best_shift ([-32, 32] scan), spectral_corr (Hann 4096).

Wet-path tail gate (issue #100; same legs as the shared mono comparator's
#93 gate, tools/compare_audio_reference.py)
-------------------------------------------------------------------------
The tail region is read from the fixture sidecar's DECLARED values
(`render.frames`, `render.tail_s`, `render.sample_rate`; region
[frames - tail_s*sr, frames)), never from a hard-coded window and never
inferred from silence. The sidecar defaults to
<fixtures-dir>/<slug>__<seq>.json; if it is missing, does not declare the
region, or does not describe the reference render (sample rate, frame count,
wet sha256), the tool REFUSES: verdict NO_VERDICT, exit 2, nothing graded.

The verdict is PASS only when the three proposed budgets pass AND the tail
gate passes on the mono sum and on each of L and R: declared region covered
by both renders, reference tail carries energy, model tail carries energy,
and tail residual RMS <= PROPOSED_TAIL["tail_rms_rel_db"] relative to the
reference tail RMS. A zeroed, truncated, or far-too-fast model tail FAILS.

Exit status: 0 = a graded verdict (PASS or FAIL; consumers read `verdict`,
unchanged from the pre-#100 tool); 2 = refusal (NO_VERDICT).
"""

import argparse
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402

PROPOSED_TAIL = car.PROPOSED_TAIL

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
        "rms_diff_dbfs": car.rms_dbfs(rms / LSB, float(1 << 20)),
        "rms_diff_at_shift0_lsb": shifts[0] / LSB,
        "best_shift": best_shift,
        "rms_diff_at_best_shift_lsb": shifts[best_shift] / LSB,
        "spectral_corr": spectral_corr(ref, mod),
    }


def refuse(reason, out_json=None):
    return car.refuse(reason, out_json)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", required=True)
    ap.add_argument("--fixtures-dir",
                    default=os.path.join(REPO, "reports", "SXT-028c", "fixtures"))
    ap.add_argument("--art-dir",
                    default=os.path.join(REPO, "reports", "SXT-028c", "artifacts"))
    ap.add_argument("--model",
                    help="model wet render (default: "
                         "<art-dir>/model__<slug>__<seq>.f32.wav)")
    ap.add_argument("--sidecar",
                    help="fixture sidecar declaring the tail region (default: "
                         "<fixtures-dir>/<slug>__<seq>.json)")
    ap.add_argument("--json", help="write metrics JSON here")
    args = ap.parse_args()

    ref_path = os.path.join(args.fixtures_dir,
                            f"{args.slug}__{args.seq}-wet.f32.wav")
    mod_path = args.model or os.path.join(
        args.art_dir, f"model__{args.slug}__{args.seq}.f32.wav")
    sidecar = args.sidecar or os.path.join(
        args.fixtures_dir, f"{args.slug}__{args.seq}.json")

    # The tail region must come from declared fixture metadata; refuse first.
    if not os.path.exists(sidecar):
        return refuse(
            "fixture sidecar not found: %s -- the wet-path tail region cannot "
            "be declared, and this tool does not guess one (issue #100)"
            % sidecar, args.json)
    try:
        region = car.declared_tail_region(sidecar, "wet")
    except car.TailRegionError as e:
        return refuse(str(e), args.json)

    ref, sr = read_wav_stereo_f32(ref_path)
    mod, sr2 = read_wav_stereo_f32(mod_path)
    assert sr == sr2 == 48000, (sr, sr2)
    why = car.validate_region_against_render(region, sr, ref.shape[1], ref_path)
    if why:
        return refuse(why, args.json)

    metrics = {
        "schema_version": 2,
        "leaf": "SXT-028c",
        "slug": args.slug,
        "sequence": args.seq,
        "ref": os.path.relpath(ref_path, REPO),
        "model": os.path.relpath(mod_path, REPO),
        "path": "wet",
        "fixture_sidecar": os.path.relpath(sidecar, REPO),
    }
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
    metrics["proposed_tail_budget"] = dict(PROPOSED_TAIL)
    tc, tc_lr, tail_ok, tail_reason = car.stereo_tail_gate(
        ref, mod, dict(region, sidecar=os.path.relpath(sidecar, REPO)), LSB)
    metrics["tail_check"] = tc
    metrics["tail_check_lr"] = tc_lr
    metrics["tail_gate_ok"] = tail_ok
    budgets_ok = all(proposed_results.values())
    if budgets_ok and tail_ok:
        metrics["verdict"] = (
            "PASS (PENDING-FREEZE: budgets and the wet-path tail-region gate "
            "are proposals, not frozen policy; freeze gated on SXT-017 #12 / "
            "shared delay-semantics #16)")
    else:
        parts = []
        if not budgets_ok:
            parts.append("budget: " + ", ".join(
                sorted(k for k, v in proposed_results.items() if not v)))
        if not tail_ok:
            parts.append("tail-region gate: " + tail_reason)
        metrics["verdict"] = ("FAIL against proposed budgets (%s)"
                              % "; ".join(parts))

    print(json.dumps({
        "slug": args.slug, "seq": args.seq,
        "max_abs_diff_lsb": worst["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"],
        "best_shift": worst["best_shift"],
        "tail_rms_rel_db": tc["tail_rms_rel_db"],
        "tail_gate_ok": tail_ok,
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
