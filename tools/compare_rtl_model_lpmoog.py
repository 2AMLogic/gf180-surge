#!/usr/bin/env python3
"""SXT-039 exactness harness: LP Legacy Ladder RTL trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every output sample ("Y" lines) against the model's out_model;
  * every block checkpoint ("T" line): the subtype, the end-of-block ladder
    registers R[0..4] and the eight-word coefficient plane C[0..7] against the
    model trace's "after" state.

This establishes claim (1) only -- the RTL reproduces the frozen fixed-point
model exactly.  It says nothing about model-vs-reference agreement (claim 2,
`tools/compare_lpmoog_model.py`) and nothing about how anything sounds
(claim 3, listening records only).

Usage:
  python3 tools/compare_rtl_model_lpmoog.py --run-dir DIR [--tb PATH] [--out JSON]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import compile_and_run  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_lpmoog.sv")
MUTANT = os.path.join(REPO, "rtl", "voice", "lpmoog_broken_mutant.sv")


def parse_tb(path):
    y = {}
    t = {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "Y":
                y[(int(parts[1]), int(parts[2]))] = int(parts[3])
            elif parts[0] == "T":
                vals = [int(x) for x in parts[1:]]
                t[vals[0]] = vals[1:]   # subtype, R[0..4], C[0..7]
    return y, t


def compare(model_trace, tb):
    fails = []
    checked = {"samples": 0, "checkpoints": 0, "fields": 0}
    y, t = parse_tb(tb) if isinstance(tb, str) else tb
    for blk in model_trace["trace_blocks"]:
        b = blk["b"]
        for k, want in enumerate(blk["out_model"]):
            checked["samples"] += 1
            got = y.get((b, k))
            if got != want:
                fails.append(f"block {b} sample {k}: model={want} rtl={got}")
                if len(fails) > 30:
                    return checked, fails
        after = blk["after"]
        got = t.get(b)
        if got is None:
            fails.append(f"block {b}: missing T line")
            continue
        want_fields = [blk["subtype"], *after["r"], *after["C_end"]]
        checked["checkpoints"] += 1
        for i, (w, g) in enumerate(zip(want_fields, got)):
            checked["fields"] += 1
            if w != g:
                fails.append(f"block {b} field {i}: model={w} rtl={g}")
        if len(fails) > 30:
            return checked, fails
    return checked, fails


def build_and_run(sv_file, workdir):
    """Compile + run the LP Legacy Ladder testbench via the shared helper.

    Kept as this module's public entry point: tools/run_sxt039_checks.py,
    tools/lpmoog_negative_controls.py and tests/test_sxt039_lpmoog.py all
    drive the RTL through `crm.build_and_run(...)`.
    """
    return compile_and_run(
        sv_file, workdir,
        out_name=os.path.basename(sv_file).replace(".sv", ".vvp"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json (+ rtl/*.hex in run-dir/rtl)")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        model_trace = json.load(f)

    trace_path = build_and_run(args.tb, args.run_dir)
    checked, fails = compare(model_trace, trace_path)
    summary = {
        "issue": "SXT-039",
        "tb": os.path.basename(args.tb),
        "case": model_trace["meta"]["case"],
        "subtypes": model_trace["subtypes"],
        "verdict": "PASS" if not fails else "FAIL",
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
