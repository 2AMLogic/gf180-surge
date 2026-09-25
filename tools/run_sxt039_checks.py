#!/usr/bin/env python3
"""SXT-039 re-verification runner (oracle-free).

Re-runs the leaf's committed evidence from the committed inputs:

  step 1  RTL-vs-frozen-model exactness for every fixture case (iverilog),
          plus the committed single-constant mutant control;
  step 2  model-vs-reference budgets against the COMMITTED pinned-kernel
          reference streams, and a drift check of the regenerated numbers
          against the committed budget artifacts (a changed number is a
          STALE artifact, reported as FAIL, never silently overwritten);
  step 3  the negative controls (`tools/lpmoog_negative_controls.py`).

Nothing here needs the pinned sources or the oracle host: the reference
streams are committed data.  Regenerating them (a pin bump, a new fixture)
needs `tools/render_lpmoog_reference.py` with pinned checkouts.

Usage:
  python3 tools/run_sxt039_checks.py [--steps 1,2,3] [--run-root DIR]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lpmoog"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import fixtures as fx  # noqa: E402
import run_filter_leg as rfl  # noqa: E402
import compare_rtl_model_lpmoog as crm  # noqa: E402
import compare_lpmoog_model as clm  # noqa: E402

ARTIFACTS = os.path.join(REPO, "reports", "SXT-039", "artifacts")
CASES = sorted(fx.CASES)


def have_iverilog():
    return shutil.which("iverilog") is not None and shutil.which("vvp") is not None


def step1(run_root):
    if not have_iverilog():
        print("step 1: NOT_RUN (iverilog unavailable)")
        return None
    ok = True
    for case in CASES:
        run_dir = os.path.join(run_root, f"run-{case}")
        os.makedirs(run_dir, exist_ok=True)
        trace = rfl.run_case(case)
        with open(os.path.join(run_dir, "model_trace.json"), "w", encoding="utf-8") as f:
            json.dump(trace, f)
        rfl.write_rtl_stimulus(trace, run_dir)
        tb_trace = crm.build_and_run(crm.TB, run_dir)
        checked, fails = crm.compare(trace, tb_trace)
        print(f"step 1 {case:9s} samples={checked['samples']:6d} "
              f"fields={checked['fields']:5d} -> "
              f"{'PASS' if not fails else 'FAIL (' + str(len(fails)) + ')'}")
        ok = ok and not fails
    # mutant control
    run_dir = os.path.join(run_root, f"run-{CASES[0]}")
    trace = rfl.run_case(CASES[0])
    mut_trace = crm.build_and_run(crm.MUTANT, run_dir)
    _checked, fails = crm.compare(trace, mut_trace)
    print(f"step 1 mutant control -> {'PASS (fails as required)' if fails else 'BROKEN CONTROL'}")
    return ok and bool(fails)


def step2(run_root):
    ok = True
    for case in CASES:
        ref = os.path.join(ARTIFACTS, f"ref-{case}.f32")
        if not os.path.exists(ref):
            print(f"step 2 {case:9s} NOT_RUN (committed reference missing)")
            ok = False
            continue
        run_dir = os.path.join(run_root, f"run-{case}")
        os.makedirs(run_dir, exist_ok=True)
        trace = rfl.run_case(case)
        with open(os.path.join(run_dir, "model_trace.json"), "w", encoding="utf-8") as f:
            json.dump(trace, f)
        res = clm.compare_case(run_dir, ARTIFACTS)
        committed_path = os.path.join(ARTIFACTS, f"budget-{case}.json")
        drift = "no committed artifact"
        if os.path.exists(committed_path):
            with open(committed_path, encoding="utf-8") as f:
                committed = json.load(f)
            same = (committed["L2_audio_q1021"]["max_abs_lsb"]
                    == res["L2_audio_q1021"]["max_abs_lsb"]
                    and abs(committed["L2_audio_q1021"]["rms_lsb"]
                            - res["L2_audio_q1021"]["rms_lsb"]) < 1e-6
                    and committed["verdict"] == res["verdict"])
            drift = "reproduces committed artifact" if same else "STALE (numbers moved)"
            ok = ok and same
        print(f"step 2 {case:9s} L2 max={res['L2_audio_q1021']['max_abs_lsb']:6d} "
              f"rms={res['L2_audio_q1021']['rms_lsb']:8.2f} "
              f"{res['verdicts']['L2_audio']} / {drift}")
    return ok


def step3(run_root):
    cmd = [sys.executable, os.path.join(REPO, "tools", "lpmoog_negative_controls.py"),
           "--artifact-dir", os.path.join(run_root, "nc"),
           "--ref-dir", ARTIFACTS, "--run-root", run_root]
    if not have_iverilog():
        cmd.append("--skip-rtl")
    rc = subprocess.run(cmd, check=False).returncode
    print(f"step 3 negative controls -> {'PASS (all controls failed as designed)' if rc == 0 else 'BROKEN CONTROL'}")
    return rc == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="1,2,3")
    ap.add_argument("--run-root", default=None)
    args = ap.parse_args()
    steps = {s.strip() for s in args.steps.split(",") if s.strip()}
    run_root = args.run_root or tempfile.mkdtemp(prefix="sxt039-checks-")
    os.makedirs(run_root, exist_ok=True)
    results = {}
    if "1" in steps:
        results["1"] = step1(run_root)
    if "2" in steps:
        results["2"] = step2(run_root)
    if "3" in steps:
        results["3"] = step3(run_root)
    bad = [k for k, v in results.items() if v is False]
    print(json.dumps({"steps": {k: ("PASS" if v else ("NOT_RUN" if v is None else "FAIL"))
                                for k, v in results.items()},
                      "run_root": run_root}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
