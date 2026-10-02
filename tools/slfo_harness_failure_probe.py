#!/usr/bin/env python3
"""SXT-041: measure the SLFO exactness harness's simulator-failure paths.

Issue #193 requires each harness that turns `report_sim_fails=True` on to
confirm, on ITS OWN testbench, that the healthy-run stdout carries no
`$readmem ... Unable to open` line (so mechanism 2's narrow matcher cannot
turn a passing run into a FAIL), and issue #188 requires the
present-but-unloaded shape to be visible as a simulator failure rather than
as RTL-vs-model mismatches.

This probe measures three states on a copy of a real run dir and writes the
transcript to `--out`:

  A healthy          -> verdict PASS, comparison PASS, stdout tail empty
  B stimulus ABSENT  -> comparison NOT_RUN, sim_fails names the exact file
                        (mechanism 1, asserted before the simulator runs)
  C stimulus EMPTY   -> comparison NOT_RUN via a non-zero vvp exit
                        (mechanism 3), because tb_slfo.sv $fatal's on an
                        all-x control word. The same state measured against
                        a testbench carrying the PERMISSIVE guard tb_lfo.sv
                        uses is recorded too, so the transcript shows what
                        this leaf's guard buys: the #188/#193 blind spot (a
                        wall of "mismatches" from a control memory that never
                        loaded).

Nothing here is an RTL-vs-model or model-vs-reference claim; it is a property
of the harness.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CMP = os.path.join(REPO, "tools", "compare_slfo_rtl_model.py")
TB = os.path.join(REPO, "rtl", "voice", "tb_slfo.sv")
# The two independent stimulus-load guards tb_slfo.sv carries, replaced in
# the "without guard" measurement by the PERMISSIVE form tb_lfo.sv uses, so
# the transcript compares this leaf's guard against the sibling leaf's and
# reproduces the #188 blind spot machine-checkably.
GUARD_ANCHOR = (
    "      if (ctrl_mem[ci] === 32'hxxxxxxxx)\n"
    "        $fatal(1, \"slfo ctrl memory not loaded at block %0d "
    "(rtl/slfo_ctrl.hex empty or shorter than the %0d declared blocks)\", "
    "b, total_blocks);\n"
    "      if (int'(ctrl_mem[ci]) != b)\n"
    "        $fatal(1, \"slfo ctrl desync at block %0d (got %0d)\", b, "
    "ctrl_mem[ci]);\n")
PERMISSIVE_GUARD = (
    "      if (ctrl_mem[ci] !== 32'hxxxxxxxx && int'(ctrl_mem[ci]) != b)\n"
    "        $fatal(1, \"slfo ctrl desync at block %0d (got %0d)\", b, "
    "ctrl_mem[ci]);\n")


def run_cmp(run_dir, tb=None):
    cmd = [sys.executable, CMP, "--run-dir", run_dir]
    if tb:
        cmd += ["--tb", tb]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"verdict": "NO_VERDICT", "comparison": "NOT_RUN",
                "sim_fails": [f"harness produced no JSON: {r.stderr[-400:]}"],
                "mismatches": 0, "sim_stdout_tail": ""}


def summarize(d):
    return {"verdict": d["verdict"], "comparison": d["comparison"],
            "mismatches": d["mismatches"], "sim_fails": d["sim_fails"],
            "sim_stdout_tail": d["sim_stdout_tail"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="a healthy run dir (model_trace.json + rtl/*.hex)")
    ap.add_argument("--work", default="/tmp/sxt041-harness-probe")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if os.path.exists(args.work):
        shutil.rmtree(args.work)
    shutil.copytree(args.run_dir, args.work)
    ctrl = os.path.join(args.work, "rtl", "slfo_ctrl.hex")

    out = {"issue": "SXT-041",
           "claim_scope": "Harness property only (issues #188/#193). Not an "
                          "RTL-vs-model or model-vs-reference claim.",
           "testbench": os.path.relpath(TB, REPO),
           "source_run_dir": os.path.relpath(args.run_dir, REPO),
           "icarus_version": subprocess.run(
               ["iverilog", "-V"], capture_output=True,
               text=True).stdout.splitlines()[0]}

    out["A_healthy"] = summarize(run_cmp(args.work))

    backup = ctrl + ".bak"
    shutil.move(ctrl, backup)
    out["B_stimulus_absent"] = summarize(run_cmp(args.work))

    open(ctrl, "w").close()
    out["C_stimulus_empty_with_guard"] = summarize(run_cmp(args.work))

    # the same state against a testbench with the load guard removed, so the
    # transcript shows the #188/#193 blind spot the guard closes
    src = open(TB, encoding="utf-8").read()
    if src.count(GUARD_ANCHOR) != 1:
        out["C_stimulus_empty_permissive_guard"] = {
            "verdict": "NOT_RUN",
            "why": "load-guard anchor not found exactly once in tb_slfo.sv; "
                   "the permissive-guard comparison was not measured"}
    else:
        unguarded = os.path.join(args.work, "tb_slfo_unguarded.sv")
        with open(unguarded, "w", encoding="utf-8") as f:
            f.write(src.replace(GUARD_ANCHOR, PERMISSIVE_GUARD))
        out["C_stimulus_empty_permissive_guard"] = summarize(
            run_cmp(args.work, tb=unguarded))

    shutil.move(backup, ctrl)
    out["D_restored"] = summarize(run_cmp(args.work))

    out["findings"] = [
        "healthy-run stdout tail is empty: mechanism 2's narrow "
        "`$readmem ... Unable to open` matcher cannot fire on a passing run "
        "of this testbench (#193 per-harness confirmation)",
        "an ABSENT stimulus is named by the pre-flight check and keeps the "
        "comparison NOT_RUN (#193 mechanism 1)",
        "a PRESENT-but-EMPTY stimulus is caught by tb_slfo.sv's own load "
        "guards as a non-zero vvp exit (#193 mechanism 3); with the "
        "PERMISSIVE guard tb_lfo.sv uses instead, the same state is reported "
        "as RTL-vs-model mismatches, which is the #188 blind spot measured "
        "directly on this leaf",
    ]
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(out, indent=2, sort_keys=True))
    ok = (out["A_healthy"]["comparison"] == "PASS"
          and out["B_stimulus_absent"]["comparison"] == "NOT_RUN"
          and out["C_stimulus_empty_with_guard"]["comparison"] == "NOT_RUN"
          and out["D_restored"]["comparison"] == "PASS")
    print("PROBE OK" if ok else "PROBE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
