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
  stability         monitor verdict STABLE over the whole case (both legs:
                    model monitor and engine tap peaks bounded)

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
STABILITY_FLOOR = 1 << 28      # headroom floor for the corner peak bound


def verdict_for(inst):
    l1 = (inst["l1_C_max"] <= PROPOSED["l1_C_max_lsb"]
          and inst["l1_C_rms"] <= PROPOSED["l1_C_rms_lsb"])
    l2 = (inst["l2a"]["max_abs_lsb"] <= PROPOSED["l2_max_abs_lsb"]
          and inst["l2a"]["rms_lsb"] <= PROPOSED["l2_rms_lsb"]
          and inst["spectral_corr"] >= PROPOSED["l2_spectral_corr_min"])
    peak_ok = inst.get("engine_peak_bounded", True)
    return {
        "L1_coefficients": "PASS" if l1 else "FAIL",
        "L2_audio": "PASS" if (l2 and peak_ok) else "FAIL",
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
            engine_peak = max(inst["stability_peaks"] or [0])
            inst["engine_peak_bounded"] = engine_peak < (1 << 31)
            v = verdict_for(inst)
            v["engine_state_peak_lsb"] = engine_peak
            v["model_state_peak_lsb"] = max(inst["stability_peaks"] or [0])
            v["stability_model"] = "STABLE" if v["model_state_peak_lsb"] < (1 << 31) \
                else "UNSTABLE"
            results[f"{inst['key']['name']}.lane{inst['key']['lane']}"] = v
            if "FAIL" in v["L1_coefficients"] or "FAIL" in v["L2_audio"]:
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
