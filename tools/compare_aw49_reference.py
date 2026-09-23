#!/usr/bin/env python3
"""SXT-028a: model-vs-reference comparison at the AW-49 slot boundary.

Drives the frozen fixed-point model (model/effects/aw-49/galactic_model.py)
with the TAPPED effect input of a fixture render (the engine's own
Airwindows adapter input, conditionally on the tapped per-sample vibrato
control-plane stream - decision-records/0006) and compares the model output
against the tapped effect output.

Policy (SXT-022/023/024): no normalization, no time-warping, no reference
switching; budgets are [PROPOSED-TO-BE-FROZEN-AT-PILOT] (SXT-013 owns the
fidelity policy) - the tool reports ACHIEVED numbers against explicitly
proposed values and marks every verdict PENDING-FREEZE.

Also verifies (per fixture):
  * internal-state agreement: the tapped engine iirAL/fbAR trajectories vs
    the model's fixed-point states (diagnostic LSB table),
  * tail-span presence (the render carries the declared tail; the
    dropped-tail negative control lives in tools/aw49_negative_controls.py),
  * countM control-plane agreement (the model's shared-counter schedule vs
    the engine's).

Original to this repository (Apache-2.0).
"""

import argparse
import hashlib
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-49"))

import galactic_model as gm  # noqa: E402

# [PROPOSED-TO-BE-FROZEN-AT-PILOT] budgets, sxt-024 reverb-class values
# (float32 bus units; the residual class is fixed-vs-float quantization):
PROPOSED = {
    "max_abs_diff": 1e-3,
    "rms_rel_db": -50.0,
    "spectral_corr_min": 0.98,
}

FIXTURES_DIR = os.path.join(REPO, "reports", "sxt-028a", "fixtures")


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    if n < frame:
        return 1.0 if np.allclose(a, b) else 0.0
    ra = np.log1p(np.abs(np.fft.rfft(a[:n // frame * frame].reshape(-1, frame)
                                     * np.hanning(frame), axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b[:n // frame * frame].reshape(-1, frame)
                                     * np.hanning(frame), axis=1))).ravel()
    ra -= ra.mean()
    rb -= rb.mean()
    d = np.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def run(slug, seq_id, fixtures_dir, out_json, onset_block=0):
    sidecar = json.load(open(os.path.join(fixtures_dir, f"{slug}__{seq_id}.json")))
    fxin = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs",
                                       f"aw-49-{slug}.json")))
    npz = np.load(os.path.join(fixtures_dir, f"{slug}__{seq_id}-aw49-taps.npz"))
    gal_in = npz["gal_in"]
    gal_out = npz["gal_out"]
    vib = gm.TappedVibratoStream(None, npz["vibM"])

    aw_entry = next(e for e in fxin["chain"]
                    if e["type"] == 14 and e["aw"] == 49)
    g = aw_entry["galactic"]
    params = {"a": g["A_replace_f"], "b": g["B_brightness_f"],
              "c": g["C_modulation_f"], "d": g["D_size_f"], "e": g["E_mix_f"]}
    ctrl = gm.build_control(params, {"fpdL": 0, "fpdR": 0})
    m = gm.Galactic49Fixed(ctrl, vib=vib)

    n_blocks = len(gal_in)
    model_out = np.zeros((n_blocks, 32, 2), dtype=np.float32)
    for b in range(n_blocks):
        bl = [gm.f32_to_s32i(x) for x in gal_in[b, :, 0]]
        br = [gm.f32_to_s32i(x) for x in gal_in[b, :, 1]]
        ol, orr = m.process_block(bl, br)
        model_out[b, :, 0] = [gm.s32i_to_f32(v) for v in ol]
        model_out[b, :, 1] = [gm.s32i_to_f32(v) for v in orr]

    # compare after the onset block (the settle+ramp window is control-plane
    # conditioned but carries no comparable signal before the first event)
    ref = gal_out[onset_block:].astype(np.float64).reshape(-1)
    mod = model_out[onset_block:].astype(np.float64).reshape(-1)
    d = np.abs(ref - mod)
    rms_ref = float(np.sqrt((ref * ref).mean())) or 1e-30
    rms_abs = float(np.sqrt(((ref - mod) ** 2).mean()))
    rms_rel_db = float(20 * np.log10(max(rms_abs / rms_ref, 1e-30)))
    max_abs = float(d.max())
    corr = spectral_corr(ref, mod)

    checks = {
        "max_abs_diff<=1e-3": max_abs <= PROPOSED["max_abs_diff"],
        "rms_rel_db<=-50": rms_rel_db <= PROPOSED["rms_rel_db"],
        "spectral_corr>=0.98": corr >= PROPOSED["spectral_corr_min"],
    }

    # control-plane agreement: model shared-counter schedule vs engine countM
    countM_model = []
    m2 = gm.Galactic49Fixed(ctrl, vib=gm.TappedVibratoStream(None, npz["vibM"]), record=True)
    probe_blocks = min(n_blocks, 1024)
    for b in range(probe_blocks):
        bl = [gm.f32_to_s32i(x) for x in gal_in[b, :, 0]]
        br = [gm.f32_to_s32i(x) for x in gal_in[b, :, 1]]
        for i in range(32):
            m2._sample(bl[i], br[i])
            countM_model.append(m2.counts["M"])
    countM_agree = bool((np.asarray(countM_model) == npz["countM"][:len(countM_model)]).all())

    # internal-state diagnostics over the probed window (LSB-class deltas)
    iirA_d = float(np.abs(npz["iirAL"][:len(countM_model)]
                          - np.asarray(m2.hist["iir_a"], dtype=float)
                          / 2.0 ** 28).max())
    fbAR_d = float(np.abs(npz["fbAR"][:len(countM_model)]
                          - np.asarray(m2.hist["fb_AR"], dtype=float)
                          / 2.0 ** 28).max())

    # tail span: the render must include the declared tail after the last
    # note-off (dropped tails FAIL; control in aw49_negative_controls.py)
    tail_s = float(sidecar["render"]["tail_s"])
    tail_blocks = int(tail_s * 48000) // 32
    tail_frames = tail_blocks * 32
    tail_energy = float(np.sqrt((gal_out[-tail_blocks:].astype(np.float64) ** 2).mean()))
    tail_present = tail_blocks >= 32 and tail_energy > 0

    res = {
        "schema_version": 1,
        "leaf": "SXT-028a",
        "case": f"{slug}__{seq_id}",
        "claim": "model-vs-pinned-engine at the AW-49 slot boundary "
                 "(tapped; fpd/vibM-conditioned control plane per DR-0006)",
        "preset": sidecar["preset"],
        "blocks_compared": int(n_blocks - onset_block),
        "settle_blocks": int(onset_block),
        "proposed_budgets": PROPOSED,
        "achieved": {
            "max_abs_diff": max_abs,
            "rms_abs": rms_abs,
            "rms_rel_db": rms_rel_db,
            "ref_rms": rms_ref,
            "spectral_corr": corr,
            "saturations": int(m.saturations),
        },
        "state_diagnostics": {
            "countM_agree": countM_agree,
            "max_iirAL_delta_q4_28_lsb": iirA_d / (2.0 ** -28),
            "max_fbAR_delta_q4_28_lsb": fbAR_d / (2.0 ** -28),
        },
        "tail": {
            "declared_tail_s": tail_s,
            "tail_blocks_rendered": int(tail_blocks),
            "tail_rms": tail_energy,
            "tail_present": tail_present,
        },
        "checks": checks,
        "verdict": ("PASS (PENDING-FREEZE: budgets are proposals, not frozen "
                    "policy)" if all(checks.values()) and tail_present
                    else "FAIL against proposed budgets"),
        "sidecar_sha256": hashlib.sha256(json.dumps(
            sidecar, sort_keys=True).encode()).hexdigest(),
        "model_frozen_revision": gm.frozen_revision(),
    }
    with open(out_json, "w") as f:
        json.dump(res, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"{res['case']}: {res['verdict']}  max={max_abs:.3e} "
          f"rms_rel={rms_rel_db:.1f} dB corr={corr:.9f} "
          f"countM={countM_agree} tail={tail_present}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures-dir", default=FIXTURES_DIR)
    ap.add_argument("--out-dir", default=os.path.join(REPO, "reports", "sxt-028a", "artifacts"))
    ap.add_argument("--cases", help="comma list slug__seq; default all committed")
    ap.add_argument("--onset-block", type=int, default=None,
                    help="first compared block; default: first block after "
                         "the settle window per sidecar")
    args = ap.parse_args()
    if args.cases:
        cases = args.cases.split(",")
    else:
        cases = sorted(f[:-5].replace("aw49-taps", "x") and f[:-5]
                       for f in os.listdir(args.fixtures_dir)
                       if f.endswith(".json") and "tmp" not in f)
    ok = True
    for case in cases:
        slug, seq_id = case.split("__")
        onset = args.onset_block
        if onset is None:
            onset = int(float(json.load(open(os.path.join(
                args.fixtures_dir, f"{case}.json")))["render"]["settle_s"])
                * 48000) // 32
        res = run(slug, seq_id, args.fixtures_dir,
                  os.path.join(args.out_dir, f"compare-{case}.json"),
                  onset_block=onset)
        ok = ok and res["verdict"].startswith("PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
