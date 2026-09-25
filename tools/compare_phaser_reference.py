#!/usr/bin/env python3
"""SXT-028g reference comparison: frozen Phaser-chain model vs the pinned
engine's wet reference (stereo float32 fixture buses, native levels).

CLAIM SCOPE: this tool addresses claim 2 of AGENTS.md ONLY (model-vs-pinned-
engine agreement, against [PROPOSED, NOT frozen] budgets). It says nothing
about RTL-vs-model exactness (tools/compare_rtl_model_phaser.py) and nothing
about musical quality.

ORACLE-GATED. It needs fixture buses rendered from the pinned engine under
SXT-012 policies (tools/render_phaser_fixtures.py). Without them it REFUSES
with NO_VERDICT / exit 2 — never a pass and never a silent skip.

One mechanism per behaviour: the metric machinery, the declared-region wet
tail gate (issue #100), the refusal semantics and the [PROPOSED] budget
family are the shared stereo effect-slice comparator from SXT-028c
(tools/compare_chorus_reference.py, which itself delegates the gate legs to
tools/compare_audio_reference.py). Only the leaf label and the default
fixture/artifact directories differ here; the budgets are NOT re-proposed
per leaf.

Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402
import compare_chorus_reference as ccr  # noqa: E402

LEAF = "SXT-028g"
PROPOSED = ccr.PROPOSED
PROPOSED_TAIL = ccr.PROPOSED_TAIL
LSB = ccr.LSB

FIXTURES = os.path.join(REPO, "reports", LEAF, "fixtures")
ARTIFACTS = os.path.join(REPO, "reports", LEAF, "artifacts")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", required=True)
    ap.add_argument("--fixtures-dir", default=FIXTURES)
    ap.add_argument("--art-dir", default=ARTIFACTS)
    ap.add_argument("--model")
    ap.add_argument("--sidecar")
    ap.add_argument("--json")
    args = ap.parse_args()

    ref_path = os.path.join(args.fixtures_dir,
                            f"{args.slug}__{args.seq}-wet.f32.wav")
    mod_path = args.model or os.path.join(
        args.art_dir, f"model__{args.slug}__{args.seq}.f32.wav")
    sidecar = args.sidecar or os.path.join(
        args.fixtures_dir, f"{args.slug}__{args.seq}.json")

    for p, what in ((ref_path, "pinned-engine wet reference"),
                    (mod_path, "frozen-model wet render")):
        if not os.path.exists(p):
            return ccr.refuse(
                f"{what} not found: {p} — no oracle fixture is available in "
                "this environment, so model-vs-reference agreement is "
                "NOT_RUN (never PASS)", args.json)
    if not os.path.exists(sidecar):
        return ccr.refuse(
            f"fixture sidecar not found: {sidecar} — the wet-path tail region "
            "cannot be declared and this tool does not guess one (issue #100)",
            args.json)
    try:
        region = car.declared_tail_region(sidecar, "wet")
    except car.TailRegionError as e:
        return ccr.refuse(str(e), args.json)

    ref, sr = ccr.read_wav_stereo_f32(ref_path)
    mod, sr2 = ccr.read_wav_stereo_f32(mod_path)
    if not (sr == sr2 == 48000):
        return ccr.refuse(f"sample-rate mismatch {sr} / {sr2}", args.json)
    why = car.validate_region_against_render(region, sr, ref.shape[1], ref_path)
    if why:
        return ccr.refuse(why, args.json)

    metrics = {
        "schema_version": 2,
        "leaf": LEAF,
        "slug": args.slug,
        "sequence": args.seq,
        "ref": os.path.relpath(ref_path, REPO),
        "model": os.path.relpath(mod_path, REPO),
        "path": "wet",
        "fixture_sidecar": os.path.relpath(sidecar, REPO),
        "comparator_provenance": "shared stereo effect-slice comparator "
                                 "(tools/compare_chorus_reference.py, "
                                 "SXT-028c) — metrics, budgets and the "
                                 "issue-#100 wet tail gate are unchanged",
    }
    chs = {n: ccr.channel_metrics(ref[i], mod[i]) for n, i in (("L", 0), ("R", 1))}
    chs["mono"] = ccr.channel_metrics(0.5 * (ref[0] + ref[1]),
                                      0.5 * (mod[0] + mod[1]))
    metrics["channels"] = chs
    worst = chs["mono"]
    results = {
        "max_abs_diff_lsb":
            worst["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"] >= PROPOSED["spectral_corr_min"],
    }
    metrics["proposed_budgets"] = PROPOSED
    metrics["proposed_budget_results"] = results
    metrics["proposed_tail_budget"] = dict(PROPOSED_TAIL)
    tc, tc_lr, tail_ok, tail_reason = car.stereo_tail_gate(
        ref, mod, dict(region, sidecar=os.path.relpath(sidecar, REPO)), LSB)
    metrics["tail_check"] = tc
    metrics["tail_check_lr"] = tc_lr
    metrics["tail_gate_ok"] = tail_ok
    budgets_ok = all(results.values())
    if budgets_ok and tail_ok:
        metrics["verdict"] = (
            "PASS (PENDING-FREEZE: the budgets and the wet-path tail-region "
            "gate are proposals, not frozen policy; freeze gated on "
            "SXT-017 #12)")
    else:
        parts = []
        if not budgets_ok:
            parts.append("budget: " + ", ".join(
                sorted(k for k, v in results.items() if not v)))
        if not tail_ok:
            parts.append("tail-region gate: " + tail_reason)
        metrics["verdict"] = ("FAIL against proposed budgets (%s)"
                              % "; ".join(parts))

    print(json.dumps({"slug": args.slug, "seq": args.seq,
                      "verdict": metrics["verdict"]}, indent=2))
    out = args.json or os.path.join(
        args.art_dir, f"compare-{args.slug}__{args.seq}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(metrics, f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
