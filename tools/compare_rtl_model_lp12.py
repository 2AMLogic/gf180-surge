#!/usr/bin/env python3
"""SXT-037 exactness harness: LP12 filter RTL trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every output sample ("Y" lines) against the model's out_model,
  * every block checkpoint ("T" lines): end-of-block registers r0/r1/r_clip
    and coefficient words c[0..7] against the model trace "after" state.

Also runs the committed negative control: rtl/voice/lp12_broken_mutant.sv
(the same testbench with one deliberately mutated constant) must FAIL.

Usage:
  python3 tools/compare_rtl_model_lp12.py --run-dir DIR [--tb PATH] [--out JSON]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import compile_and_run  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_lp12.sv")
MUTANT = os.path.join(REPO, "rtl", "voice", "lp12_broken_mutant.sv")


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
                t[vals[0]] = vals[1:]   # b -> subtype, r0, r1, r_clip, c0..c7
    return y, t


def compare(model_trace, tb, instance=0):
    fails = []
    checked = {"samples": 0, "checkpoints": 0, "fields": 0}
    y, t = parse_tb(tb) if isinstance(tb, str) else tb
    inst = model_trace["instances"][instance]
    if inst.get("stimulated", True) is False:
        raise SystemExit("selected instance was not the one stimulated")
    for blk in inst["trace_blocks"]:
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
        want_fields = [blk["subtype"], after["r0"], after["r1"], after["r_clip"],
                       *after["C_end"]]
        checked["checkpoints"] += 1
        for i, (w, g) in enumerate(zip(want_fields, got)):
            checked["fields"] += 1
            if w != g:
                fails.append(f"block {b} field {i}: model={w} rtl={g}")
        if len(fails) > 30:
            return checked, fails
    return checked, fails


def build_and_run(sv_file, workdir):
    """Compile + run the LP12 testbench via the shared helper.

    Kept as this module's public entry point: tools/lp12_negative_controls.py
    drives the mutant control through `crm.build_and_run(...)`.
    """
    return compile_and_run(sv_file, workdir, out_name="tb_lp12.vvp")


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
        "tb": os.path.basename(args.tb),
        "leg": model_trace.get("leg"),
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
