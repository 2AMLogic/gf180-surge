#!/usr/bin/env python3
"""SXT-038 end-to-end check runner (LP 24 dB filter leaf).

Steps (in order):
  0. re-extract the case files from the committed graph corpus and verify they
     match the committed ones (--check: fail-closed);
  1. render the pinned-code reference for every case (builds the external
     harness first) and verify each bundle's sha256 against its committed
     meta.json where one exists;
  2. run the frozen model legs L2a (+ L2b attribution) per case;
  3. run RTL-vs-model exactness per case (iverilog);
  4. compute the [PROPOSED] budget verdicts;
  5. run the negative controls (all must fail their target checks).

Usage:
  python3 tools/run_sxt038_checks.py [--work /tmp/sxt038] [--steps 0,1,2,3,4,5]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(REPO, "reports", "SXT-038", "artifacts")
CASES = os.path.join(ART, "cases")
PY = sys.executable


def run(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, cwd=REPO, **kw)


def case_names():
    return sorted(os.path.splitext(f)[0] for f in os.listdir(CASES) if f.endswith(".json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/sxt038")
    ap.add_argument("--steps", default="0,1,2,3,4,5")
    args = ap.parse_args()
    steps = {int(s) for s in args.steps.split(",") if s.strip()}
    os.makedirs(args.work, exist_ok=True)
    names = case_names()
    status = {}

    if 0 in steps:
        r = run([PY, "model/voice/filter_lp24/extract_inputs.py", "--check"],
                capture_output=True, text=True)
        status["0_cases_match_corpus"] = "PASS" if r.returncode == 0 else "FAIL"
        if r.returncode:
            print(r.stdout[-2000:], r.stderr[-2000:])

    if 1 in steps:
        committed = {}
        for n in names:
            m = os.path.join(ART, f"bundle-{n}", "meta.json")
            if os.path.exists(m):
                committed[n] = json.load(open(m, encoding="utf-8")).get("sha256", {})
        r = run([PY, "tools/render_lp24_reference.py", "--cases", "all"],
                capture_output=True, text=True)
        ok = r.returncode == 0
        drift = []
        for n, shas in committed.items():
            m = os.path.join(ART, f"bundle-{n}", "meta.json")
            fresh = json.load(open(m, encoding="utf-8")).get("sha256", {})
            for k, v in shas.items():
                if k in fresh and fresh[k] != v:
                    drift.append(f"{n}/{k}")
        status["1_reference_render"] = "PASS" if ok else "FAIL"
        status["1_reference_byte_stable"] = "PASS" if (ok and not drift) else (
            "FAIL: " + ",".join(drift) if drift else "NOT_RUN")
        if not ok:
            print(r.stdout[-2000:], r.stderr[-2000:])

    if 2 in steps:
        bad = []
        for n in names:
            out = os.path.join(args.work, f"run-{n}")
            r = run([PY, "model/voice/filter_lp24/run_filter_leg.py",
                     "--bundle", os.path.join(ART, f"bundle-{n}"), "--out-dir", out],
                    capture_output=True, text=True)
            if r.returncode:
                bad.append(n)
                print(r.stderr[-800:])
            r2 = run([PY, "model/voice/filter_lp24/run_filter_leg.py",
                      "--bundle", os.path.join(ART, f"bundle-{n}"),
                      "--out-dir", os.path.join(args.work, f"l2b-{n}"),
                      "--engine-coeffs", "--no-trace"], capture_output=True, text=True)
            if r2.returncode:
                bad.append(n + "-l2b")
        status["2_model_legs"] = "PASS" if not bad else "FAIL: " + ",".join(bad)

    if 3 in steps:
        bad = []
        for n in names:
            r = run([PY, "tools/compare_rtl_model_lp24.py",
                     "--run-dir", os.path.join(args.work, f"run-{n}"),
                     "--out", os.path.join(ART, f"rtl-{n}.json")],
                    capture_output=True, text=True)
            if r.returncode:
                bad.append(n)
        status["3_rtl_exactness"] = "PASS (all cases exact)" if not bad else \
            "FAIL: " + ",".join(bad)

    if 4 in steps:
        r = run([PY, "tools/compare_lp24_model.py",
                 "--legs", os.path.join(args.work, "run-*", "leg.json"),
                 "--l2b", os.path.join(args.work, "l2b-*", "leg.json"),
                 "--out-dir", ART], capture_output=True, text=True)
        if r.returncode == 0:
            s = json.loads(r.stdout[r.stdout.index("{"):])
            status["4_budgets"] = (f"{s['pass']}/{s['cases']} cases PASS the [PROPOSED] "
                                   f"budgets ({s['fail']} recorded misses)")
        else:
            status["4_budgets"] = "FAIL (tool error)"
            print(r.stderr[-2000:])

    if 5 in steps:
        r = run([PY, "tools/lp24_negative_controls.py", "--runs", args.work],
                capture_output=True, text=True)
        status["5_negative_controls"] = ("PASS (all controls failed their target check)"
                                         if r.returncode == 0 else "FAIL (a control passed)")
        print(r.stdout[-1500:])

    print(json.dumps({"issue": "SXT-038", "status": status}, indent=2))
    hard = [k for k, v in status.items() if str(v).startswith("FAIL")]
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
