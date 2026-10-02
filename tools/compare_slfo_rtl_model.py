#!/usr/bin/env python3
"""SXT-041 exactness harness: SCENE-LFO RTL checkpoint trace vs frozen model
trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every declared per-instance scene-LFO checkpoint (`L` lines) against the
    model trace's per-block `slfo` records — phase, EG state, EG phase, EG
    value and routed output of ALL SIX instances at EVERY block boundary
    (not only the routed ones: "all six process every block" is part of the
    scene-scope schedule this leaf freezes);
  * the per-block scene-route sums (`S` lines) against the model's
    `slfo_route_sums` (the depth * output terms summed into cutoff /
    resonance once per block, shared by every voice);
  * the per-block one-block route latch (`O` lines) against the model's
    `slfo_route_out`. This is the field that pins the scene-route LATENCY:
    a testbench that applied `output21` directly instead of `route_out`
    disagrees here, which is how rtl/voice/slfo_nodelay_mutant.sv is caught.

Mirrors tools/compare_lfo_rtl_model.py (same verdict JSON schema, same
exit-code convention) for the SXT-041 control-plane testbench
rtl/voice/tb_slfo.sv.

SIMULATOR-LEVEL FAILURES ARE NOT COMPARISON DISAGREEMENTS (issues #188,
#193). tb_slfo.sv `$readmemh`s five files (init.hex, slfo_init.hex,
slfo_routes.hex, slfo_wssine.hex, slfo_ctrl.hex) from `rtl/` under the run
dir. Both load-failure shapes are covered and were MEASURED on Icarus 13.0
for this leaf (transcript: reports/SXT-041/artifacts/harness-failure-path.json):

  * ABSENT stimulus — `report_sim_fails=True`'s pre-flight check (mechanism
    1) names the exact file and sets `comparison: NOT_RUN`, before the
    simulator is invoked at all.
  * PRESENT-but-empty/short stimulus — opens fine, so no mechanism 1 or 2
    signal exists; `tb_slfo.sv` therefore `$fatal`s on an all-x control word
    (unlike tb_lfo.sv, whose permissive `!== 32'hxxxxxxxx` guard lets that
    shape through), which surfaces as a non-zero `vvp` exit (mechanism 3) and
    again `comparison: NOT_RUN`. Measured BEFORE that guard was added, this
    leaf reproduced the #188/#193 blind spot exactly: 74 reported
    "mismatches" from a control memory that never loaded.

The healthy-run stdout of this testbench is EMPTY (no `$readmem ... Unable to
open` line), which is the per-harness confirmation #193 requires before
mechanism 2 may be relied on.

Usage:
  python3 tools/compare_slfo_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_slfo.sv]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import compile_and_run  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_slfo.sv")

# The hex stimulus tb_slfo.sv `$readmemh`s, relative to the run dir (issue
# #193's pre-flight check axis; single source of truth so the check can never
# drift from what the testbench actually reads).
STIMULUS_RELPATHS = ("rtl/init.hex", "rtl/slfo_init.hex",
                     "rtl/slfo_routes.hex", "rtl/slfo_wssine.hex",
                     "rtl/slfo_ctrl.hex")

L_FIELDS = ["b", "index", "phase", "env_state", "env_phase", "env_val",
            "output"]
CMP_FIELDS = ("phase", "env_state", "env_phase", "env_val", "output")
MAX_REPORTED = 40


def parse_tb(path):
    lines = {}   # (block, index) -> dict
    sums = {}    # block -> [cut_sum, reso_sum]
    latch = {}   # block -> [out0..out5]
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "L":
                vals = [int(x) for x in parts[1:]]
                d = dict(zip(L_FIELDS, vals))
                lines[(d["b"], d["index"])] = d
            elif parts[0] == "S":
                sums[int(parts[1])] = [int(parts[2]), int(parts[3])]
            elif parts[0] == "O":
                latch[int(parts[1])] = [int(x) for x in parts[2:]]
    return lines, sums, latch


def compare(model_trace, tb_trace):
    fails = []
    checked = {"slfo_checkpoints": 0, "slfo_fields": 0, "route_sums": 0,
               "route_latches": 0, "blocks": 0}
    tl, ts, to = tb_trace

    for blk in model_trace["blocks"]:
        b = blk["b"]
        checked["blocks"] += 1
        for rec in blk.get("slfo", []):
            d = tl.get((b, rec["index"]))
            if d is None:
                fails.append(f"block {b} slfo {rec['index']}: missing L line")
                continue
            checked["slfo_checkpoints"] += 1
            for fld in CMP_FIELDS:
                checked["slfo_fields"] += 1
                if d[fld] != rec[fld]:
                    fails.append(f"block {b} slfo {rec['index']} {fld}: "
                                 f"model={rec[fld]} rtl={d[fld]}")
        if "slfo_route_sums" in blk:
            got = ts.get(b)
            if got is None:
                fails.append(f"block {b}: missing S line")
            else:
                checked["route_sums"] += 1
                for j, want in enumerate(blk["slfo_route_sums"]):
                    if got[j] != want:
                        fails.append(f"block {b} route_sum[{j}]: "
                                     f"model={want} rtl={got[j]}")
        if "slfo_route_out" in blk:
            got = to.get(b)
            if got is None:
                fails.append(f"block {b}: missing O line")
            else:
                checked["route_latches"] += 1
                for j, want in enumerate(blk["slfo_route_out"]):
                    if got[j] != want:
                        fails.append(f"block {b} route_out[{j}]: "
                                     f"model={want} rtl={got[j]}")
        if len(fails) > MAX_REPORTED:
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

    sim = compile_and_run(
        args.tb, args.run_dir, out_name="tb_slfo.vvp", absolute=True,
        compile_in_workdir=True, trace_name="tb_slfo_trace.txt",
        stimulus_files=STIMULUS_RELPATHS, report_sim_fails=True)

    checked = {"slfo_checkpoints": 0, "slfo_fields": 0, "route_sums": 0,
               "route_latches": 0, "blocks": 0}
    fails = list(sim.sim_fails)
    comparison = "NOT_RUN"
    if not sim.sim_fails:
        rtl_trace = parse_tb(sim.trace)
        checked, cmp_fails = compare(model_trace, rtl_trace)
        fails += cmp_fails
        comparison = "FAIL" if cmp_fails else "PASS"

    summary = {
        "tb": os.path.relpath(args.tb, REPO),
        "verdict": "PASS" if not fails else "FAIL",
        "comparison": comparison,
        "scope": "scene-LFO control plane (ms_slfo1..6): one instance set per "
                 "scene, all six checkpointed every block, plus the "
                 "once-per-block scene route sums and the one-block route "
                 "latch",
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
        "sim_fails": sim.sim_fails,
        "sim_stdout_tail": sim.stdout_tail,
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
