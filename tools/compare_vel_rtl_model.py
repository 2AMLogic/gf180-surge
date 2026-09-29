#!/usr/bin/env python3
"""SXT-036 exactness harness: velocity / release-velocity control-plane RTL
trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL), at every block
boundary of every voice slot that ran a control pass:
  * the per-instance source words (V lines: vel_q, relvel_q) against the
    model trace's per-voice `vel_words`,
  * the per-voice route sums (S lines: cutoff / reso / fegmod / vca sums of
    depth*source terms) against the model trace's `vel_route_sums`.
A model record with no RTL line (or vice versa) is a mismatch.

Mirrors tools/compare_mw_rtl_model.py (same verdict JSON schema, same
exit-code convention) for rtl/voice/tb_vel.sv. The audio datapath is checked
separately by tools/compare_rtl_model.py (tb_voice.sv, unchanged) against the
same run directory.

Usage:
  python3 tools/compare_vel_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_vel.sv]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_vel.sv")


def _int(x):
    # an unresolved RTL value (x/z) can never equal a model word
    try:
        return int(x)
    except ValueError:
        return None


def parse_tb(path):
    s = {}   # (block, slot) -> [cut, reso, emod, vca]
    v = {}   # (block, slot) -> [vel_q, relvel_q]
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "S":
                s[(int(p[1]), int(p[2]))] = [_int(x) for x in p[3:7]]
            elif p[0] == "V":
                v[(int(p[1]), int(p[2]))] = [_int(x) for x in p[3:5]]
    return s, v


def compare(model_trace, tb_trace):
    fails = []
    checked = {"voice_block_checkpoints": 0, "source_words": 0,
               "route_sums": 0}
    ts, tv = tb_trace
    seen = set()
    for blk in model_trace["blocks"]:
        b = blk["b"]
        for rec in blk["voices"]:
            key = (b, rec["slot"])
            seen.add(key)
            got_v, got_s = tv.get(key), ts.get(key)
            if got_v is None or got_s is None:
                fails.append(f"block {b} slot {rec['slot']}: missing V/S line")
                continue
            checked["voice_block_checkpoints"] += 1
            for j, want in enumerate(rec["vel_words"]):
                checked["source_words"] += 1
                if got_v[j] != want:
                    fails.append(f"block {b} slot {rec['slot']} "
                                 f"{('vel_q', 'relvel_q')[j]}: model={want} "
                                 f"rtl={got_v[j]}")
            for j, want in enumerate(rec["vel_route_sums"]):
                checked["route_sums"] += 1
                if got_s[j] != want:
                    fails.append(f"block {b} slot {rec['slot']} "
                                 f"route_sum[{j}]: model={want} rtl={got_s[j]}")
        if len(fails) > 40:
            return checked, fails
    extra = sorted(set(ts) - seen)
    for key in extra[:10]:
        fails.append(f"block {key[0]} slot {key[1]}: RTL line with no model "
                     "record")
    return checked, fails


def build_and_run(sv_file, workdir):
    workdir = os.path.abspath(workdir)
    vvp = os.path.join(workdir, "tb_vel.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", vvp, os.path.abspath(sv_file)],
                   check=True, cwd=workdir,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = subprocess.run(["vvp", vvp], cwd=workdir, check=True,
                       capture_output=True, text=True)
    done = [ln for ln in r.stdout.splitlines() if ln.startswith("DONE")]
    return os.path.join(workdir, "tb_vel_trace.txt"), (done[-1] if done else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/vel_*.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        model_trace = json.load(f)

    trace_path, done = build_and_run(args.tb, args.run_dir)
    checked, fails = compare(model_trace, parse_tb(trace_path))
    summary = {
        "tb": os.path.relpath(os.path.abspath(args.tb), REPO),
        "sequence": model_trace.get("sequence"),
        "control_mode": model_trace.get("control_mode"),
        "verdict": "PASS" if not fails else "FAIL",
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
        "rtl_done_line": done,
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
