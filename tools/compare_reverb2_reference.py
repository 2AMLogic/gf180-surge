#!/usr/bin/env python3
"""SXT-028f reference comparison: the frozen Reverb 2 model vs the pinned
engine's unmodified WET bus (stereo float32 fixtures, native levels).

Policy (unchanged from SXT-022/023/028c): no normalization, no
time-warping, no reference switching, no per-patch engine switching; raw
per-sample differences at native level plus the shared log-floor spectral
correlation; budgets are [PROPOSED-TO-BE-FROZEN-AT-PILOT]. This tool
reports ACHIEVED numbers against explicitly-proposed values and marks the
verdict PENDING-FREEZE; it never declares fidelity established and it never
tunes a budget to a measurement.

CLAIM SCOPE (narrow, on purpose). The model is fed the engine's own
per-slot-bypass bus (model/effects/run_reverb2_model.py), so what is graded
here is the **fx:Reverb 2 class** -- claim (2), model vs pinned engine -- and
nothing else. It is NOT a complete-wet preset result, NOT a coverage number
and NOT a statement about how anything sounds (AGENTS.md: numeric tests
never establish musical usefulness).

Units: differences in Q10.21 LSB (1 LSB = 2^-21 ~ 4.77e-7). Metrics per
channel (L, R) and mono sum: max_abs_diff_lsb, rms_diff_lsb,
rms_diff_dbfs, best_shift ([-32, 32] scan), spectral_corr (the shared
full-scale log-floor definition of issue #110).

Wet-path tail gate (issues #93/#100): the tail region is read from the
fixture sidecar's DECLARED values (`render.frames`, `render.tail_s`,
`render.sample_rate`), never hard-coded and never inferred from silence. A
missing or non-describing sidecar is a REFUSAL (verdict NO_VERDICT, exit 2,
nothing graded).

Exit status: 0 = a graded verdict (PASS or FAIL); 2 = refusal (NO_VERDICT).
Original to this repository (Apache-2.0).
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
from compare_chorus_reference import (  # noqa: E402
    PROPOSED, PROPOSED_TAIL, channel_metrics, read_wav_stereo_f32,
)

LSB = 2.0 ** -21


def refuse(reason, out_json=None):
    return car.refuse(reason, out_json)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", required=True)
    ap.add_argument("--fixtures-dir",
                    default=os.path.join(REPO, "reports", "SXT-028f", "fixtures"))
    ap.add_argument("--art-dir",
                    default=os.path.join(REPO, "reports", "SXT-028f", "artifacts"))
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

    if not os.path.exists(sidecar):
        return refuse(
            "fixture sidecar not found: %s -- the wet-path tail region cannot "
            "be declared, and this tool does not guess one (issue #100)"
            % sidecar, args.json)
    with open(sidecar) as f:
        side = json.load(f)
    gate = side.get("determinism_gate") or {}
    if not gate.get("bit_identical"):
        return refuse(
            "fixture %s does not declare a passing 3x bit-identical "
            "determinism gate: a reference that is not reproducible cannot "
            "carry an agreement verdict" % sidecar, args.json)
    try:
        region = car.declared_tail_region(sidecar, "wet")
    except car.TailRegionError as e:
        return refuse(str(e), args.json)
    if not os.path.exists(mod_path):
        return refuse("model render not found: %s" % mod_path, args.json)

    ref, sr = read_wav_stereo_f32(ref_path)
    mod, sr2 = read_wav_stereo_f32(mod_path)
    if not (sr == sr2 == 48000):
        return refuse("sample-rate mismatch: %r vs %r" % (sr, sr2), args.json)
    why = car.validate_region_against_render(region, sr, ref.shape[1], ref_path)
    if why:
        return refuse(why, args.json)

    mman_path = os.path.join(args.art_dir,
                             f"model__{args.slug}__{args.seq}.json")
    mman = {}
    if os.path.exists(mman_path):
        with open(mman_path) as f:
            mman = json.load(f)
    if mman.get("input_boundary", {}).get("wet_sha256") not in (
            None, side["wet"]["sha256"]):
        return refuse(
            "the model render was produced against a DIFFERENT wet reference "
            "(%s) than the fixture committed here (%s)"
            % (mman["input_boundary"]["wet_sha256"][:16],
               side["wet"]["sha256"][:16]), args.json)

    metrics = {
        "schema_version": 1,
        "leaf": "SXT-028f",
        "follow_up": "F-028f-1 (#126)",
        "slug": args.slug,
        "sequence": args.seq,
        "ref": os.path.relpath(ref_path, REPO),
        "model": os.path.relpath(mod_path, REPO),
        "path": "wet",
        "claim_scope": "fx:Reverb 2 CLASS agreement (model fed the engine's "
                       "own per-slot-bypass bus); NOT a complete-wet preset, "
                       "coverage or musical-quality claim",
        "input_boundary": mman.get("input_boundary"),
        "model_revision": mman.get("model_revision"),
        "fixture_sidecar": os.path.relpath(sidecar, REPO),
        "reference_determinism_gate": {
            "repeats": gate.get("repeats"),
            "bit_identical": gate.get("bit_identical"),
            "drift_asserted": gate.get("drift_asserted"),
        },
    }
    chs = {}
    for name, idx in (("L", 0), ("R", 1)):
        chs[name] = channel_metrics(ref[idx], mod[idx])
    chs["mono"] = channel_metrics(0.5 * (ref[0] + ref[1]),
                                  0.5 * (mod[0] + mod[1]))
    metrics["channels"] = chs

    worst = chs["mono"]
    proposed_results = {
        "max_abs_diff_lsb": worst["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"] >= PROPOSED["spectral_corr_min"],
    }
    metrics["proposed_budgets"] = PROPOSED
    metrics["spectral_corr_definition"] = car.SPECTRAL_CORR_DEFINITION
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
