#!/usr/bin/env python3
"""SXT-032 exactness harness: LFO RTL checkpoint trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every declared per-instance LFO checkpoint (L lines) against the model
    trace's per-voice `lfo` records (phase, EG state, EG phase, EG value,
    routed output at every block boundary),
  * every per-voice routed-modulation sum (S lines) against the model's
    `lfo_route_sums` (the depth * output terms added into cutoff/reso).

Mirrors tools/compare_rtl_model.py (same verdict JSON schema, same exit-code
convention) for the SXT-032 control-plane testbench rtl/voice/tb_lfo.sv.

Usage:
  python3 tools/compare_lfo_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_lfo.sv]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import compile_and_run  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_lfo.sv")

L_FIELDS = ["b", "slot", "index", "phase", "env_state", "env_phase",
            "env_val", "output"]


def parse_tb(path):
    l = {}   # (block, slot, index) -> dict
    s = {}   # (block, slot) -> [cut_sum, reso_sum]
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "L":
                vals = [int(x) for x in parts[1:]]
                d = dict(zip(L_FIELDS, vals))
                l[(d["b"], d["slot"], d["index"])] = d
            elif parts[0] == "S":
                s[(int(parts[1]), int(parts[2]))] = [int(parts[3]),
                                                     int(parts[4])]
    return l, s


def compare(model_trace, tb_trace):
    fails = []
    checked = {"lfo_checkpoints": 0, "lfo_fields": 0, "route_sums": 0}
    tl, ts = tb_trace

    for blk in model_trace["blocks"]:
        b = blk["b"]
        for rec in blk["voices"]:
            key = (b, rec["slot"])
            for lr in rec.get("lfo", []):
                d = tl.get((b, rec["slot"], lr["index"]))
                if d is None:
                    fails.append(f"block {b} slot {rec['slot']} lfo "
                                 f"{lr['index']}: missing L line")
                    continue
                checked["lfo_checkpoints"] += 1
                for fld in ("phase", "env_state", "env_phase", "env_val",
                            "output"):
                    checked["lfo_fields"] += 1
                    if d[fld] != lr[fld]:
                        fails.append(
                            f"block {b} slot {rec['slot']} lfo {lr['index']} "
                            f"{fld}: model={lr[fld]} rtl={d[fld]}")
            if "lfo_route_sums" in rec:
                got = ts.get(key)
                if got is None:
                    fails.append(f"block {b} slot {rec['slot']}: missing "
                                 "S line")
                    continue
                checked["route_sums"] += 1
                for j, want in enumerate(rec["lfo_route_sums"]):
                    if got[j] != want:
                        fails.append(f"block {b} slot {rec['slot']} route_"
                                     f"sum[{j}]: model={want} rtl={got[j]}")
            if len(fails) > 40:
                return checked, fails
    return checked, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/*.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        model_trace = json.load(f)

    trace_path = compile_and_run(
        args.tb, args.run_dir, out_name="tb_lfo.vvp", absolute=True,
        compile_in_workdir=True, trace_name="tb_lfo_trace.txt")
    rtl_trace = parse_tb(trace_path)
    checked, fails = compare(model_trace, rtl_trace)
    summary = {
        "tb": os.path.relpath(args.tb, REPO),
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
