#!/usr/bin/env python3
"""SXT-038 budget verdicts: frozen LP24 model vs the pinned filter code.

Claim (2) only.  Every bound below is a **[PROPOSED]** budget: SXT-013/#12
owns the fidelity-policy freeze, so a miss here is recorded as a finding and
routed there, never widened to make a case pass (AGENTS.md).

Budgets (declared before the runs, same family as the landed SXT-037 leaf):

  L1_C_max_abs    max |C_model - C_ref|                    <=   16 LSB (Q10.21)
  L1_C_max_rel    max |dC| / max(1, |C_ref|)               <=   16 LSB
                  (the scale-relative form SXT-037 recorded as its finding)
  L2_max_abs      max |y_model - y_ref| per sample         <= 4096 LSB
  L2_rms          rms |y_model - y_ref|                    <=  256 LSB
  stability       frozen-model per-block peak monitor      ==  STABLE

  spectral_corr   log-magnitude spectral correlation       >= 0.999
                  REPORTED, NOT GATING: SXT-037 recorded this metric as
                  mis-scaled for filtered-voice spectra (sparse spectrum
                  dominates the score at error levels 80-100 dB down).  Both
                  verdicts are emitted -- `verdict` (L1+L2+stability) and
                  `verdict_including_spectral` -- so nothing is hidden.

Usage:
  python3 tools/compare_lp24_model.py --legs /tmp/run-*/leg.json \
      [--l2b /tmp/l2b-*/leg.json] --out-dir reports/SXT-038/artifacts
"""

import argparse
import glob
import json
import os
import sys

BUDGETS = {
    "L1_C_max_abs_lsb": 16,
    "L1_C_max_rel_lsb": 16,
    "L2_max_abs_lsb": 4096,
    "L2_rms_lsb": 256,
    "spectral_corr_min": 0.999,
}


def evaluate(leg, l2b=None):
    l1 = leg["l1"]
    au = leg["audio"]
    checks = {
        "L1_C_max_abs_lsb": (l1["C_max_lsb"], BUDGETS["L1_C_max_abs_lsb"],
                             l1["C_max_lsb"] <= BUDGETS["L1_C_max_abs_lsb"]),
        "L1_C_max_rel_lsb": (round(l1["C_max_rel_lsb"], 3), BUDGETS["L1_C_max_rel_lsb"],
                             l1["C_max_rel_lsb"] <= BUDGETS["L1_C_max_rel_lsb"]),
        "L2_max_abs_lsb": (au["max_abs_lsb"], BUDGETS["L2_max_abs_lsb"],
                           au["max_abs_lsb"] <= BUDGETS["L2_max_abs_lsb"]),
        "L2_rms_lsb": (round(au["rms_lsb"], 3), BUDGETS["L2_rms_lsb"],
                       au["rms_lsb"] <= BUDGETS["L2_rms_lsb"]),
        "stability": (leg["stability_verdict"], "STABLE",
                      leg["stability_verdict"] == "STABLE"),
    }
    spec_ok = leg["spectral_corr"] >= BUDGETS["spectral_corr_min"]
    gating = all(ok for _, _, ok in checks.values())
    out = {
        "case": leg["case"],
        "leg": leg["leg"],
        "subtypes": leg["subtypes"],
        "blocks": leg["blocks"],
        "samples": au["n"],
        "budgets": BUDGETS,
        "checks": {k: {"achieved": a, "budget": b, "pass": ok}
                   for k, (a, b, ok) in checks.items()},
        "spectral_corr": {"achieved": round(leg["spectral_corr"], 6),
                          "budget": BUDGETS["spectral_corr_min"],
                          "pass": spec_ok, "gating": False},
        "rms_db_rel_ref_peak": round(au["rms_db_rel_ref_peak"], 2),
        "ref_peak_lsb": au["ref_peak_lsb"],
        "model_state_peak_lsb": leg["stability_peaks_max"],
        "reg_max_abs_lsb": leg["l3_reg_max_lsb"],
        "qmul_per_sample": leg["qmul_per_sample"],
        "verdict": "PASS" if gating else "FAIL",
        "verdict_including_spectral": "PASS" if (gating and spec_ok) else "FAIL",
        "status_note": ("[PROPOSED] budgets, PENDING-FREEZE (SXT-013/#12). A FAIL "
                        "is a recorded finding, not a fidelity verdict, and is "
                        "never resolved by widening the budget."),
        "reference": leg.get("reference", {}),
    }
    if l2b:
        out["attribution_l2b"] = {
            "max_abs_lsb": l2b["audio"]["max_abs_lsb"],
            "rms_lsb": round(l2b["audio"]["rms_lsb"], 3),
            "rms_db_rel_ref_peak": round(l2b["audio"]["rms_db_rel_ref_peak"], 2),
            "note": ("model kernel driven by the PINNED coefficient plane: "
                     "isolates kernel arithmetic from coefficient construction"),
        }
    return out


def load(paths):
    out = {}
    for pat in paths:
        for p in sorted(glob.glob(pat)):
            with open(p, encoding="utf-8") as f:
                leg = json.load(f)
            out[leg["case"]] = leg
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", nargs="+", required=True)
    ap.add_argument("--l2b", nargs="*", default=[])
    ap.add_argument("--out-dir")
    args = ap.parse_args()

    legs = load(args.legs)
    l2bs = load(args.l2b) if args.l2b else {}
    if not legs:
        print("REFUSING: no leg.json inputs matched", file=sys.stderr)
        return 2

    rows = []
    for case in sorted(legs):
        row = evaluate(legs[case], l2bs.get(case))
        rows.append(row)
        if args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            with open(os.path.join(args.out_dir, f"compare-{case}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(row, f, indent=2)
                f.write("\n")

    summary = {
        "issue": "SXT-038",
        "budgets": BUDGETS,
        "cases": len(rows),
        "pass": sum(1 for r in rows if r["verdict"] == "PASS"),
        "fail": sum(1 for r in rows if r["verdict"] == "FAIL"),
        "table": [{"case": r["case"], "subtypes": r["subtypes"],
                   "L1_max": r["checks"]["L1_C_max_abs_lsb"]["achieved"],
                   "L2_max": r["checks"]["L2_max_abs_lsb"]["achieved"],
                   "L2_rms": r["checks"]["L2_rms_lsb"]["achieved"],
                   "dB": r["rms_db_rel_ref_peak"],
                   "corr": r["spectral_corr"]["achieved"],
                   "stability": r["checks"]["stability"]["achieved"],
                   "verdict": r["verdict"]} for r in rows],
    }
    print(json.dumps(summary, indent=2))
    if args.out_dir:
        with open(os.path.join(args.out_dir, "budget-summary.json"), "w",
                  encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
