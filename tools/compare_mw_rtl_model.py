#!/usr/bin/env python3
"""SXT-035 exactness harness: modwheel control-plane RTL trace vs frozen model
trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every declared per-voice route-sum checkpoint (S lines: cutoff / reso /
    vca sums of depth*value terms) against the model trace's per-voice
    `mw_route_sums` at every block boundary of every running voice,
  * the smoothed modwheel value (M lines, post-step) against the model's
    per-block `mw_value`.

Mirrors tools/compare_lfo_rtl_model.py (same verdict JSON schema, same
exit-code convention) for the SXT-035 control-plane testbench
rtl/voice/tb_mw.sv.

Usage:
  python3 tools/compare_mw_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_mw.sv]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import compile_and_run  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_mw.sv")


def parse_tb(path):
    s = {}   # (block, slot) -> [cut_sum, reso_sum, vca_sum]
    m = {}   # block -> value
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "S":
                s[(int(parts[1]), int(parts[2]))] = [int(parts[3]),
                                                     int(parts[4]),
                                                     int(parts[5])]
            elif parts[0] == "M":
                m[int(parts[1])] = int(parts[2])
    return s, m


def compare(model_trace, tb_trace):
    fails = []
    checked = {"mw_values": 0, "route_sum_checkpoints": 0, "route_sums": 0}
    ts, tm = tb_trace

    for blk in model_trace["blocks"]:
        b = blk["b"]
        want_v = blk["mw_value"]
        got_v = tm.get(b)
        if got_v is None:
            fails.append(f"block {b}: missing M line")
        else:
            checked["mw_values"] += 1
            if got_v != want_v:
                fails.append(f"block {b} mw_value: model={want_v} "
                             f"rtl={got_v}")
        for rec in blk["voices"]:
            key = (b, rec["slot"])
            got = ts.get(key)
            if got is None:
                fails.append(f"block {b} slot {rec['slot']}: missing S line")
                continue
            checked["route_sum_checkpoints"] += 1
            for j, want in enumerate(rec["mw_route_sums"]):
                checked["route_sums"] += 1
                if got[j] != want:
                    fails.append(f"block {b} slot {rec['slot']} route_sum[{j}]"
                                 f": model={want} rtl={got[j]}")
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
        args.tb, args.run_dir, out_name="tb_mw.vvp", absolute=True,
        compile_in_workdir=True, quiet_compile=True,
        trace_name="tb_mw_trace.txt")
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
