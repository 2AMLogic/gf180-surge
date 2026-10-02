#!/usr/bin/env python3
"""SXT-028e-sse (#136): frozen SSE-branch chain model vs pinned-engine wet bus.

The SXT-028c comparator (`tools/compare_chorus_reference.py`) verbatim in
policy, metric definitions and budget values — only the leaf name, the fixture
bus name and the artifact layout differ. Everything numeric is reused rather
than re-derived, so the two leaves' numbers stay comparable:

  * no normalization, no time-warping, no reference switching; raw per-sample
    differences at native level;
  * units: Q10.21 LSB (1 LSB = 2^-21); per channel (L, R) and the mono sum;
  * the [PROPOSED] SXT-023 effect-slice budgets (max <= 8,192 LSB;
    rms <= -46 dBFS; spectral corr >= 0.98) — PROPOSED, never frozen here;
    the freeze is SXT-017's (#12);
  * the wet-path tail gate reads its region from the fixture sidecar's
    DECLARED values only (issues #93/#100), and REFUSES (NO_VERDICT, exit 2)
    when the sidecar cannot declare one.

ACHIEVED NUMBERS ARE RECORDED, NOT TUNED. This tool has no threshold of its
own and no way to adjust one: the budgets are imported constants, the region
is read from committed metadata, and a FAIL is written out as a FAIL. For FX
models 4 (`DIGI_SSE2`) and 7 (`TableEval<FuzzTable<1>,1024,TANH>`) the leaf's
own finding F-028e-sse-4 already records that the sample-domain metric cannot
discriminate — a FAIL there is reported and escalated to #12, not papered
over and not used to relax anything.

Exit status: 0 = a graded verdict (PASS or FAIL); 2 = refusal (NO_VERDICT).
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

LEAF = "SXT-028e-sse"
PROPOSED = dict(ccr.PROPOSED)          # the SXT-023 effect-slice family
PROPOSED_TAIL = car.PROPOSED_TAIL
LSB = ccr.LSB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", required=True)
    ap.add_argument("--bus", default="original",
                    help="fixture sidecar bus block to compare against "
                         "(default: the unmodified `original` wet bus)")
    ap.add_argument("--fixtures-dir",
                    default=os.path.join(REPO, "reports", "SXT-028e-sse",
                                         "fixtures"))
    ap.add_argument("--art-dir",
                    default=os.path.join(REPO, "reports", "SXT-028e-sse",
                                         "artifacts"))
    ap.add_argument("--model", help="model render (default: "
                                    "<art-dir>/model__<slug>__<seq>.f32.wav)")
    ap.add_argument("--sidecar")
    ap.add_argument("--label", help="free-text label recorded in the output "
                                    "(negative controls use it)")
    ap.add_argument("--json")
    args = ap.parse_args()

    sidecar = args.sidecar or os.path.join(
        args.fixtures_dir, f"{args.slug}__{args.seq}.json")
    mod_path = args.model or os.path.join(
        args.art_dir, f"model__{args.slug}__{args.seq}.f32.wav")

    if not os.path.exists(sidecar):
        return car.refuse(
            "fixture sidecar not found: %s -- the wet-path tail region cannot "
            "be declared, and this tool does not guess one (issue #100)"
            % sidecar, args.json)
    sc = json.load(open(sidecar))
    bus = sc.get(args.bus) if isinstance(sc.get(args.bus), dict) else None
    if bus is None:
        legs = sc.get("legs") if isinstance(sc.get("legs"), dict) else {}
        bus = legs.get(args.bus)
        if isinstance(bus, dict):
            # the comparator's region reader wants a top-level bus block
            sc = dict(sc)
            sc[args.bus] = bus
            sidecar_eff = os.path.join(
                args.art_dir, f".region-{args.slug}__{args.seq}-{args.bus}.json")
            os.makedirs(args.art_dir, exist_ok=True)
            with open(sidecar_eff, "w") as f:
                json.dump(sc, f)
        else:
            return car.refuse(
                "fixture sidecar %s declares no '%s' bus block and no "
                "legs['%s'] leg" % (sidecar, args.bus, args.bus), args.json)
    else:
        sidecar_eff = sidecar
    if not bus.get("wav"):
        return car.refuse("sidecar bus '%s' declares no wav" % args.bus,
                          args.json)
    ref_path = os.path.join(REPO, bus["wav"])
    if not os.path.exists(mod_path):
        return car.refuse(
            "model render not found: %s -- NOT_RUN, and this tool grades "
            "nothing it did not read" % mod_path, args.json)

    try:
        region = car.declared_tail_region(sidecar_eff, args.bus)
    except car.TailRegionError as e:
        return car.refuse(str(e), args.json)

    ref, sr = ccr.read_wav_stereo_f32(ref_path)
    mod, sr2 = ccr.read_wav_stereo_f32(mod_path)
    if not (sr == sr2 == 48000):
        return car.refuse(f"sample-rate mismatch: ref {sr}, model {sr2}",
                          args.json)
    why = car.validate_region_against_render(region, sr, ref.shape[1], ref_path)
    if why:
        return car.refuse(why, args.json)

    metrics = {
        "schema_version": 2,
        "leaf": LEAF,
        "issue": "SXT-028e-sse reference leg (#136)",
        "slug": args.slug,
        "sequence": args.seq,
        "carrier_kind": sc.get("carrier_kind", "unknown"),
        "corpus_reach": sc.get("corpus_reach", "unknown"),
        "fx_model_index": sc.get("fx_model_index"),
        "quad_waveshaper": sc.get("quad_waveshaper"),
        "ref": os.path.relpath(ref_path, REPO),
        "ref_bus": args.bus,
        "model": os.path.relpath(mod_path, REPO),
        "path": "wet",
        "fixture_sidecar": os.path.relpath(sidecar, REPO),
    }
    if args.label:
        metrics["label"] = args.label
    chs = {}
    for name, idx in (("L", 0), ("R", 1)):
        chs[name] = ccr.channel_metrics(ref[idx], mod[idx])
    chs["mono"] = ccr.channel_metrics(0.5 * (ref[0] + ref[1]),
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

    # How the peak budget fails, when it fails: a budget missed by a handful
    # of isolated samples and one missed everywhere are different findings,
    # and "max" alone cannot tell them apart. Reported for every leg, pass or
    # fail; it is a DESCRIPTION of the achieved difference, not a second
    # budget and not a relaxation of the first.
    import numpy as np
    mono_d = np.abs(0.5 * (ref[0] + ref[1]) - 0.5 * (mod[0] + mod[1])) / LSB
    over = mono_d > PROPOSED["max_abs_diff_lsb"]
    n_over = int(over.sum())
    metrics["peak_budget_exceedance"] = {
        "threshold_lsb": PROPOSED["max_abs_diff_lsb"],
        "samples_over": n_over,
        "samples_total": int(mono_d.size),
        "fraction_over": (n_over / mono_d.size) if mono_d.size else 0.0,
        "worst_sample_index": int(np.argmax(mono_d)),
        "p99_9_abs_diff_lsb": float(np.percentile(mono_d, 99.9)),
        "median_abs_diff_lsb": float(np.median(mono_d)),
        "note": "descriptive only. The budget verdict above is unchanged by "
                "these numbers and no threshold here is a pass criterion.",
    }
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
            "are proposals, not frozen policy; freeze gated on SXT-017 #12)")
    else:
        parts = []
        if not budgets_ok:
            parts.append("budget: " + ", ".join(
                sorted(k for k, v in proposed_results.items() if not v)))
        if not tail_ok:
            parts.append("tail-region gate: " + tail_reason)
        metrics["verdict"] = ("FAIL against proposed budgets (%s)"
                              % "; ".join(parts))
    metrics["claim_scope"] = (
        "model-vs-pinned-engine agreement on a DECLARED SYNTHETIC carrier "
        "(claim 2). Not claim 1 (RTL-vs-model, separate and exact) and not "
        "claim 3 (sounds good, no listening record). No preset-support claim "
        "and no corpus reach follow from this number."
        if sc.get("carrier_kind") == "DECLARED-SYNTHETIC"
        else "model-vs-pinned-engine agreement (claim 2) only.")

    print(json.dumps({
        "slug": args.slug, "seq": args.seq, "bus": args.bus,
        "fx_model_index": metrics["fx_model_index"],
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
    if sidecar_eff != sidecar and os.path.exists(sidecar_eff):
        os.unlink(sidecar_eff)
    return 0


if __name__ == "__main__":
    sys.exit(main())
