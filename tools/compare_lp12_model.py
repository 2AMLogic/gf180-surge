#!/usr/bin/env python3
"""SXT-037 model-vs-reference comparison against [PROPOSED] budgets.

Reads the model traces produced by model/voice/filter_lp12/run_filter_leg.py
(leg L2a primary, L2b diagnostic) for every rendered case, applies the
[PROPOSED-TO-BE-FROZEN-AT-PILOT] budgets below, and writes one JSON verdict
artifact per case.  The budgets are proposals for the SXT-013 freeze, NOT
frozen policy: this tool records achieved numbers and marks verdicts
PENDING-FREEZE; it never declares fidelity established.

Proposed budgets (a priori, from quantization analysis of the frozen word
and the SXT-022 proposal class; not tuned against achieved numbers):

  L1 coefficients   max |dC_model - dC_engine| <= 16 LSB Q10.21
                    rms of the same                <= 4  LSB Q10.21
  L2 audio          max |y_model - y_engine|   <= 4096 LSB Q10.21 (~0.2 % FS)
                    rms                            <= 256 LSB
                    spectral correlation           >= 0.999
  stability         both legs STABLE/bounded over the whole case:
                    model leg  the frozen model's own per-block state-peak
                               monitor verdict (filter_lp12_model.
                               stability_verdict: growth detection plus the
                               1<<30 saturation floor), read from the trace
                               field `stability_verdict` emitted by
                               run_filter_leg.py -- NOT a bare threshold
                               recomputed here;
                    engine leg the ENGINE filter-output tap peak
                               (`l2a.engine_peak_lsb`, max |engine tap| in
                               Q10.21 LSB over the case) bounded by
                               ENGINE_TAP_PEAK_MAX_LSB below.

Out-of-scope runs exit 2 (refused) and are never reported as PASS.
"""

import argparse
import json
import os
import sys

PROPOSED = {
    "l1_C_max_lsb": 16,
    "l1_C_rms_lsb": 4,
    "l2_max_abs_lsb": 4096,
    "l2_rms_lsb": 256,
    "l2_spectral_corr_min": 0.999,
}
# Declared boundedness bound for the ENGINE filter-output tap peak, in Q10.21
# LSB (vm.ONE = 1 << 21, so this is 128x full scale) -- the bound the engine
# stability leg is graded against.  It is a boundedness bound, not a fidelity
# budget: a resonant LP12 tap may legitimately exceed full scale ahead of the
# downstream voice amp, so the bound is deliberately generous, while staying 8x
# below the s32 word limit so that an engine tap which actually ran away (and
# therefore saturates at quantization) fails rather than clamping silently.
# PROPOSED like the budgets above; not frozen policy.
ENGINE_TAP_PEAK_MAX_LSB = 1 << 28


def stability_legs(inst, case="?"):
    """Grade both stability legs of one instance from real trace quantities.

    Model leg: the frozen model's monitor verdict as emitted by the runner.
    A trace without it cannot be graded on this leg, so it is REFUSED rather
    than defaulted to STABLE -- the runner and this comparator ship together,
    and a missing field is a version mismatch, never a pass.

    Engine leg: the engine filter-output tap peak against
    ENGINE_TAP_PEAK_MAX_LSB.  This is engine tap data (quantized `fout` from
    the bundle's units.bin), independent of every model quantity.
    """
    name = f"{inst['key']['name']}.lane{inst['key']['lane']}"
    if "stability_verdict" not in inst:
        raise SystemExit(
            f"{case}: instance {name} carries no 'stability_verdict': this "
            "trace predates the monitor-verdict field and its model stability "
            "leg cannot be graded; re-run "
            "model/voice/filter_lp12/run_filter_leg.py on the bundle. Refusing")
    model_verdict = inst["stability_verdict"]
    if not inst["l2a"]["n"]:
        # `engine_peak_lsb` is floored at 1 LSB by _audio_metrics (it doubles
        # as an rms-dB divisor), so a silent or absent engine tap would grade
        # BOUNDED on no engine samples at all.  Refuse instead.
        raise SystemExit(
            f"{case}: instance {name} has no engine tap samples (l2a.n == 0): "
            "the engine stability leg has no engine measurement to bound. "
            "Refusing")
    engine_tap_peak = inst["l2a"]["engine_peak_lsb"]
    return {
        "stability_model": model_verdict,
        "model_state_peak_lsb": max(inst["stability_peaks"] or [0]),
        "engine_tap_peak_lsb": engine_tap_peak,
        "engine_tap_peak_max_lsb": ENGINE_TAP_PEAK_MAX_LSB,
        "stability_engine": ("BOUNDED" if engine_tap_peak < ENGINE_TAP_PEAK_MAX_LSB
                             else "UNBOUNDED"),
    }


def verdict_for(inst, legs):
    l1 = (inst["l1_C_max"] <= PROPOSED["l1_C_max_lsb"]
          and inst["l1_C_rms"] <= PROPOSED["l1_C_rms_lsb"])
    l2 = (inst["l2a"]["max_abs_lsb"] <= PROPOSED["l2_max_abs_lsb"]
          and inst["l2a"]["rms_lsb"] <= PROPOSED["l2_rms_lsb"]
          and inst["l2_spectral_corr"] >= PROPOSED["l2_spectral_corr_min"])
    stable = (legs["stability_model"] == "STABLE"
              and legs["stability_engine"] == "BOUNDED")
    return {
        "L1_coefficients": "PASS" if l1 else "FAIL",
        "L2_audio": "PASS" if l2 else "FAIL",
        "stability": "PASS" if stable else "FAIL",
        "proposed": PROPOSED,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", nargs="+", required=True,
                    help="model_trace.json paths (one per case)")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    for path in args.traces:
        with open(path, encoding="utf-8") as f:
            trace = json.load(f)
        case = trace["meta"]["case"]
        if trace["meta"].get("neutrality_violated") is True:
            raise SystemExit(f"{case}: tap neutrality violated on a deterministic "
                             "case; refusing")
        case_fail = False
        results = {}
        for inst in trace["instances"]:
            legs = stability_legs(inst, case)
            v = verdict_for(inst, legs)
            v.update(legs)
            results[f"{inst['key']['name']}.lane{inst['key']['lane']}"] = v
            if "FAIL" in (v["L1_coefficients"], v["L2_audio"], v["stability"]):
                case_fail = True
        out = {
            "schema_version": 1,
            "issue": "SXT-037",
            "case": case,
            "leg": trace.get("leg"),
            "carriers_subtypes": trace["instances"][0]["subtypes"] if trace["instances"] else [],
            "results": results,
            "verdict": "PASS (PENDING-FREEZE: budgets are proposals, not frozen policy)"
            if not case_fail else "FAIL against proposed budgets",
        }
        out_path = os.path.join(args.out_dir, f"compare-{case}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
            f.write("\n")
        print(f"{case}: {out['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
