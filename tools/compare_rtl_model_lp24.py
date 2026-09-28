#!/usr/bin/env python3
"""SXT-038 exactness harness: LP24 filter RTL trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every output sample ("Y" lines) against the model's out_model;
  * every block checkpoint ("T" line): the end-of-block registers R[0..4]
    and the advanced coefficient words C[0..7] against the model trace.

This establishes claim (1) only — RTL matches the frozen fixed-point model.
It says NOTHING about agreement with the pinned engine (claim 2,
`tools/compare_lp24_model.py`) and nothing about musical quality (claim 3).

SIMULATOR-LEVEL FAILURES ARE NOT COMPARISON DISAGREEMENTS (issues #188,
#193).  tb_lp24.sv `$readmemh`s three files (init.hex, ctrl.hex, in.hex)
from `rtl/` under the run dir.  Measured on this leaf's own testbench with
real Icarus 13.0 (issue #209 evidence): with `rtl/in.hex` absent, Icarus
prints

  ERROR: .../rtl/voice/tb_lp24.sv:79: $readmemh: Unable to open rtl/in.hex
         for reading.

on the simulation's STDOUT and `vvp` still **exits 0**, after which the
testbench writes a complete-looking trace from a memory that was never
loaded.  `check=True` alone cannot see that.  Two consequences this harness
now handles: the run reports `comparison: NOT_RUN` with the file named,
never a wall of sample mismatches; and because a simulator-level failure
also produces `verdict: FAIL`, it must NEVER be allowed to satisfy
`--expect fail` -- a negative control whose stimulus never loaded is a
BROKEN control, not a passing one -- so a non-empty `sim_fails` forces a
non-zero exit whatever `--expect` says.

Usage:
  python3 tools/compare_rtl_model_lp24.py --run-dir DIR [--tb PATH] [--out JSON]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import compile_and_run  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_lp24.sv")
MUTANT = os.path.join(REPO, "rtl", "voice", "lp24_broken_mutant.sv")

# The hex stimulus tb_lp24.sv `$readmemh`s, relative to the run dir (issue
# #193's pre-flight check axis).  Single source of truth so the check can
# never drift from what the testbench actually reads.
STIMULUS_RELPATHS = ("rtl/init.hex", "rtl/ctrl.hex", "rtl/in.hex")


def parse_tb(path):
    y, t = {}, {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "Y":
                y[(int(parts[1]), int(parts[2]))] = int(parts[3])
            elif parts[0] == "T":
                vals = [int(v) for v in parts[1:]]
                t[vals[0]] = vals[1:]   # subtype, R[0..4], C[0..7]
    return y, t


def compare(model_trace, tb_path, max_report=30):
    fails = []
    checked = {"samples": 0, "checkpoints": 0, "fields": 0}
    y, t = parse_tb(tb_path)
    for blk in model_trace["trace_blocks"]:
        b = blk["b"]
        for k, want in enumerate(blk["out_model"]):
            checked["samples"] += 1
            got = y.get((b, k))
            if got != want:
                fails.append(f"block {b} sample {k}: model={want} rtl={got}")
                if len(fails) > max_report:
                    return checked, fails
        got = t.get(b)
        if got is None:
            fails.append(f"block {b}: missing T line")
            continue
        after = blk["after"]
        want_fields = [blk["subtype"], *after["r"], *after["C_end"]]
        checked["checkpoints"] += 1
        for i, (w, g) in enumerate(zip(want_fields, got)):
            checked["fields"] += 1
            if w != g:
                fails.append(f"block {b} field {i}: model={w} rtl={g}")
        if len(fails) > max_report:
            return checked, fails
    return checked, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json and rtl/*.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write the summary JSON here")
    ap.add_argument("--expect", choices=("pass", "fail"), default="pass",
                    help="expected verdict (negative controls use --expect fail)")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json"), encoding="utf-8") as f:
        model_trace = json.load(f)

    sim = compile_and_run(args.tb, args.run_dir,
                          out_name=os.path.basename(args.tb) + ".vvp",
                          stimulus_files=STIMULUS_RELPATHS,
                          report_sim_fails=True)

    checked = {"samples": 0, "checkpoints": 0, "fields": 0}
    fails = list(sim.sim_fails)
    comparison = "NOT_RUN"
    if not sim.sim_fails:
        checked, cmp_fails = compare(model_trace, sim.trace)
        fails += cmp_fails
        comparison = "FAIL" if cmp_fails else "PASS"

    verdict = "PASS" if not fails else "FAIL"
    summary = {
        "tb": os.path.basename(args.tb),
        "case": model_trace.get("case"),
        "leg": model_trace.get("leg"),
        "verdict": verdict,
        "comparison": comparison,
        "expected": args.expect.upper(),
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
        "sim_fails": sim.sim_fails,
        "sim_stdout_tail": sim.stdout_tail,
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    # A simulator-level failure is never an "expected" outcome, not even
    # under `--expect fail`: it means the comparison this control depends on
    # NEVER RAN (issue #193). Fail closed before consulting --expect.
    if sim.sim_fails:
        return 1
    return 0 if verdict == args.expect.upper() else 1


if __name__ == "__main__":
    sys.exit(main())
