#!/usr/bin/env python3
"""SXT-039 diagnostic: the frozen model's low-cutoff quantization dead zone.

Finding F-039-2: below a certain cutoff the per-stage increment
`round(C[1] * (prev - R))` of the frozen Q10.21 ladder registers falls under
half an LSB, so the trailing stages stop advancing and the 24 dB tap outputs
exact silence, while the pinned float kernel still produces a (very small)
residue.  This tool measures WHERE that happens for a declared drive, so the
finding carries a number instead of an adjective.

Model-only and oracle-free: it sweeps the effective cutoff with a declared
sine drive and records the model's output peak per cutoff.  The paired
model-vs-reference evidence for the same class is the `cut-lo` fixture row in
`reports/SXT-039/artifacts/budget-cut-lo.json`.

Usage:
  python3 tools/diagnose_lpmoog_deadzone.py --out reports/SXT-039/artifacts/deadzone-sweep.json
"""

import argparse
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lpmoog"))

import voice_model as vm  # noqa: E402
import filter_lpmoog_model as fp  # noqa: E402

BLOCK_OS = vm.BLOCK_SIZE_OS
DRIVE_HZ = 220.0
DRIVE_AMP = 0.5
BLOCKS = 128


def run_cutoff(cut_semi, subtype, reso=0.0):
    unit = fp.LPMoogUnit(subtype)
    cm = fp.LPMoogCoeffMaker(subtype)
    peak = 0
    phase = 0.0
    for _b in range(BLOCKS):
        cm.make_coeffs(vm.qint(cut_semi), vm.qint(reso))
        blk = []
        for _k in range(BLOCK_OS):
            phase += 2.0 * math.pi * DRIVE_HZ / 96000.0
            blk.append(vm.qint(DRIVE_AMP * math.sin(phase)))
        outs, _p, c_end = unit.process_block(blk, cm)
        cm.C = list(c_end)
        peak = max(peak, max((abs(v) for v in outs), default=0))
    return peak, cm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from-semi", type=float, default=-120.0)
    ap.add_argument("--to-semi", type=float, default=20.0)
    ap.add_argument("--step", type=float, default=2.0)
    args = ap.parse_args()

    rows = []
    cut = args.from_semi
    while cut <= args.to_semi + 1e-9:
        for subtype in (0, 3):
            peak, cm = run_cutoff(cut, subtype)
            rows.append({"cut_semi": round(cut, 3), "subtype": subtype,
                         "c1_q229": cm.C[1],
                         "c1_float": cm.C[1] / float(fp.COEF_ONE),
                         "model_peak_lsb": peak})
        cut += args.step

    def first_alive(subtype):
        for r in rows:
            if r["subtype"] == subtype and r["model_peak_lsb"] > 0:
                return r["cut_semi"]
        return None

    out = {
        "schema_version": 1,
        "issue": "SXT-039",
        "finding": "F-039-2 low-cutoff quantization dead zone (frozen Q10.21 "
                   "register word)",
        "drive": {"hz": DRIVE_HZ, "amplitude": DRIVE_AMP, "blocks": BLOCKS,
                  "resonance": 0.0},
        "first_nonzero_output_cut_semi": {"subtype_0_6dB": first_alive(0),
                                          "subtype_3_24dB": first_alive(3)},
        "engine_cutoff_param_span_semi": [-60.0, 70.0],
        "note": "cutoffA below the parameter span is reachable through the "
                "keytrack / env-mod path; the dead zone is recorded for the "
                "#12 freeze owner, never clamped away.",
        "rows": rows,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(json.dumps(out["first_nonzero_output_cut_semi"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
