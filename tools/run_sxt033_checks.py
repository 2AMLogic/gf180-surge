#!/usr/bin/env python3
"""SXT-033 checks runner (issue #67): regenerates the committed evidence
under reports/SXT-033/artifacts/.

Steps:
  1. RTL-vs-model exactness, one canonical run per carrier variant
     (seq-notes-repeated-v1, full length) + mutant control (must FAIL)
  2. Model-vs-reference budget matrix over the committed reference renders
     (no oracle needed; renders are committed with sidecars)
  3. Submode-confusion negative control (must FAIL the budget check)
  4. Out-of-class refusal (House Of Chords; requires the external pinned
     oracle)

Working directory for the heavy runs is a scratch root (/tmp by default);
stimulus hex files are never committed. Requires iverilog/vvp for step 1
and the external pinned oracle (ORACLE_SURGE_DIR) for step 4.
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(REPO, "reports", "SXT-033", "artifacts")
CLASSIC = os.path.join(REPO, "model", "oscillators", "classic")
TB = os.path.join(REPO, "rtl", "oscillators", "classic", "tb_classic.sv")
MUTANT = os.path.join(REPO, "rtl", "oscillators", "classic",
                      "classic_broken_mutant.sv")
CARRIERS = ("edges", "horn", "tentacles", "crush")
SEQ = "seq-notes-repeated-v1"


def sh(cmd, cwd=REPO, **kw):
    print("  $ (cwd=%s)" % cwd, " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, **kw)


def run_rtl(carrier, root):
    out = os.path.join(root, "rtl-" + carrier)
    os.makedirs(out, exist_ok=True)
    r = sh([sys.executable, os.path.join(CLASSIC, "run_model.py"),
            "--inputs", os.path.join(CLASSIC, "inputs", carrier + ".json"),
            "--sequence", SEQ, "--out-dir", out, "--rtl"])
    assert r.returncode == 0, r.stderr
    assert sh(["iverilog", "-g2012", "-o", os.path.join(out, "tb.vvp"),
               TB]).returncode == 0
    assert sh([os.path.join(out, "tb.vvp")], cwd=out).returncode == 0, "vvp failed"
    return sh([sys.executable, "tools/compare_classic_rtl_model.py",
               "--run-dir", out,
               "--out", os.path.join(ART, "exact-%s.json" % carrier)])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch-root", default="/tmp/sxt033-checks")
    ap.add_argument("--steps", default="1,2,3,4")
    args = ap.parse_args()
    root = args.scratch_root
    os.makedirs(root, exist_ok=True)
    steps = {int(s) for s in args.steps.split(",")}
    ok = True

    if 1 in steps:
        print("[1] RTL-vs-model exactness per carrier + mutant control")
        for carrier in CARRIERS:
            r = run_rtl(carrier, root)
            ok &= r.returncode == 0
            print("    %s: %s" % (carrier, "PASS" if r.returncode == 0
                                  else "FAIL"))
        out = os.path.join(root, "rtl-edges")
        r = sh([sys.executable, "tools/compare_classic_rtl_model.py",
                "--run-dir", out, "--tb", MUTANT,
                "--out", os.path.join(ART, "exact-mutant-edges.json")])
        ok &= r.returncode == 1  # the mutant MUST fail
        print("    mutant: FAIL (required)")
        if r.returncode == 0:
            ok = False

    if 2 in steps:
        print("[2] model-vs-reference budget matrix (committed renders)")
        for carrier in CARRIERS:
            for seq in ("seq-notes-coverage-v1", SEQ):
                r = sh([sys.executable, "tools/compare_audio_reference.py",
                        "--ref", os.path.join(
                            ART, "%s__%s-ref.wav" % (carrier, seq)),
                        "--model", os.path.join(
                            ART, "model-%s-%s.wav" % (carrier, seq)),
                        "--json", os.path.join(
                            ART, "budget-%s-%s.json" % (carrier, seq))],
                       capture_output=True, text=True)
                ok &= r.returncode == 0

    if 3 in steps:
        print("[3] submode-confusion negative control (must FAIL)")
        env = dict(os.environ, SXT033_NC_SUBMODE_CONFUSION="1")
        for carrier in ("crush", "horn"):
            out = os.path.join(root, "nc-" + carrier)
            r = sh([sys.executable, os.path.join(CLASSIC, "run_model.py"),
                    "--inputs", os.path.join(
                        CLASSIC, "inputs", carrier + ".json"),
                    "--sequence", SEQ, "--out-dir", out, "--rtl"], env=env)
            assert r.returncode == 0, r.stderr
            r = sh([sys.executable, "tools/compare_audio_reference.py",
                    "--ref", os.path.join(
                        ART, "%s__%s-ref.wav" % (carrier, SEQ)),
                    "--model", os.path.join(out, "model.wav"),
                    "--json", os.path.join(
                        ART, "nc-submode-confusion-%s.json" % carrier)],
                   capture_output=True, text=True)
            ok &= "FAIL against proposed budgets" in r.stdout
            print("    %s: FAIL (required)" % carrier)
            if "FAIL against proposed budgets" not in r.stdout:
                ok = False

    if 4 in steps:
        print("[4] out-of-class refusal (requires the external oracle)")
        r = sh([sys.executable, os.path.join(CLASSIC, "extract_inputs.py"),
                "--carrier", "house",
                "--out", os.path.join(root, "house.json")],
               capture_output=True, text=True)
        refused = r.returncode == 2 and \
            "no Classic oscillator in scene A" in (r.stderr + r.stdout)
        print("    house: %s" % ("REFUSED (required)" if refused
                                 else "NOT REFUSED"))
        ok &= refused

    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
