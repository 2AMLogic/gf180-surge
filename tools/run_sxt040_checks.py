#!/usr/bin/env python3
"""SXT-040 checks runner (issue #74): regenerates the committed evidence
under reports/SXT-040/artifacts/.

Steps:
  1. RTL-vs-model exactness, one canonical run per carrier
     (seq-notes-repeated-v1, full length) + mutant control (must FAIL)
  2. Model-vs-reference budget matrix over the committed reference renders
     (no oracle needed; renders are committed with sidecars)
  3. Negative controls:
     a. wrong-family substitution: the badnews fixture driven by the landed
        SXT-033 Classic arithmetic - the budget check must FAIL
     b. shape-migration confusion: the fixture rendered with the raw
        pre-migration shape value (sine_shape_remap) - must FAIL
     c. out-of-class refusals (requires the external pinned oracle):
        playmode refusals (mortsnare, arp2) and live-voice-route refusals
        (alone, mystery4) must exit 2

Working directory for the heavy runs is a scratch root (/tmp by default);
stimulus hex files are never committed. Requires iverilog/vvp for step 1
and the external pinned oracle (ORACLE_SURGE_DIR) for step 3c.
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(REPO, "reports", "SXT-040", "artifacts")
SINE = os.path.join(REPO, "model", "oscillators", "sine")
CLASSIC = os.path.join(REPO, "model", "oscillators", "classic")
TB = os.path.join(REPO, "rtl", "oscillators", "sine", "tb_sine.sv")
MUTANT = os.path.join(REPO, "rtl", "oscillators", "sine",
                      "sine_broken_mutant.sv")
CARRIERS = ("badnews", "tentacles", "popcorn2k")
SEQ = "seq-notes-repeated-v1"
REFUSALS = ("mortsnare", "arp2", "alone", "mystery4")


def sh(cmd, cwd=REPO, **kw):
    print("  $ (cwd=%s)" % cwd, " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, **kw)


def run_rtl(carrier, root):
    out = os.path.join(root, "rtl-" + carrier)
    os.makedirs(out, exist_ok=True)
    r = sh([sys.executable, os.path.join(SINE, "run_model.py"),
            "--inputs", os.path.join(SINE, "inputs", carrier + ".json"),
            "--sequence", SEQ, "--out-dir", out, "--rtl"])
    assert r.returncode == 0, r.stderr
    assert sh(["iverilog", "-g2012", "-o", os.path.join(out, "tb.vvp"),
               TB]).returncode == 0
    assert sh([os.path.join(out, "tb.vvp")], cwd=out).returncode == 0, "vvp failed"
    return sh([sys.executable, "tools/compare_sine_rtl_model.py",
               "--run-dir", out,
               "--out", os.path.join(ART, "exact-%s.json" % carrier)])


def classic_substitution_inputs(out_path):
    """The badnews fixture's slot parameters re-expressed as landed
    SXT-033 Classic-model inputs (same gain staging, same AEG, same
    unison/pitch parameters; Classic impulse-machine arithmetic instead of
    the Sine family). Wrong-family substitution for the negative control."""
    with open(os.path.join(SINE, "inputs", "badnews.json")) as f:
        d = json.load(f)
    c = dict(d)
    c.update({
        "issue": "SXT-033-negative-control-of-SXT-040",
        "shape": 0,          # classic shape 0 (the sine slot's shape is 0)
        "pw": 0.5, "pw2": 0.5,
        "submix": 0.0, "sync": 0.0,
        "unison": d["unison"], "unison_detune": d["unison_detune"],
        "extend_detune": d["extend_detune"],
        "absolute_detune": d["absolute_detune"],
    })
    with open(out_path, "w") as f:
        json.dump(c, f, indent=2, sort_keys=True)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch-root", default="/tmp/sxt040-checks")
    ap.add_argument("--steps", default="1,2,3")
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
        out = os.path.join(root, "rtl-badnews")
        r = sh([sys.executable, "tools/compare_sine_rtl_model.py",
                "--run-dir", out, "--tb", MUTANT,
                "--out", os.path.join(ART, "exact-mutant-badnews.json")])
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
        print("[3a] wrong-family substitution (Classic arithmetic) - must "
              "FAIL the budget check")
        sub = os.path.join(root, "badnews-classic-sub.json")
        classic_substitution_inputs(sub)
        out = os.path.join(root, "nc-classic-sub")
        r = sh([sys.executable, os.path.join(CLASSIC, "run_model.py"),
                "--inputs", sub, "--sequence", SEQ, "--out-dir", out,
                "--max-blocks", "6150"], capture_output=True, text=True)
        if r.returncode != 0:
            # full render too heavy for CI; a capped render still shows it
            r = sh([sys.executable, os.path.join(CLASSIC, "run_model.py"),
                    "--inputs", sub, "--sequence", SEQ, "--out-dir", out,
                    "--max-blocks", "512"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = sh([sys.executable, "tools/compare_audio_reference.py",
                "--ref", os.path.join(ART, "badnews__%s-ref.wav" % SEQ),
                "--model", os.path.join(out, "model.wav"),
                "--json", os.path.join(ART, "nc-classic-substitution.json")],
               capture_output=True, text=True)
        failed = "FAIL against proposed budgets" in r.stdout
        print("    classic-substitution: %s (FAIL required)" %
              ("FAIL" if failed else "NOT-FAILED"))
        ok &= failed

        print("[3b] shape-migration confusion (raw pre-migration shape) - "
              "must FAIL the budget check")
        out = os.path.join(root, "nc-shape-raw")
        r = sh([sys.executable, os.path.join(SINE, "run_model.py"),
                "--inputs", os.path.join(SINE, "inputs", "tentacles.json"),
                "--sequence", "seq-notes-coverage-v1", "--out-dir", out,
                "--max-blocks", "512"],
               env=dict(os.environ, SXT040_NC_SHAPE_RAWVALUE="1"),
               capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = sh([sys.executable, "tools/compare_audio_reference.py",
                "--ref", os.path.join(ART,
                                      "tentacles__seq-notes-coverage-v1-ref.wav"),
                "--model", os.path.join(out, "model.wav"),
                "--json", os.path.join(ART, "nc-shape-migration.json")],
               capture_output=True, text=True)
        failed = "FAIL against proposed budgets" in r.stdout
        print("    shape-rawvalue: %s (FAIL required)" %
              ("FAIL" if failed else "NOT-FAILED"))
        ok &= failed

        print("[3c] out-of-class refusals (requires the external oracle)")
        for carrier in REFUSALS:
            r = sh([sys.executable, os.path.join(SINE, "extract_inputs.py"),
                    "--carrier", carrier,
                    "--out", os.path.join(root, carrier + ".json")],
                   capture_output=True, text=True)
            refused = r.returncode == 2 and \
                "REFUSING" in (r.stderr + r.stdout)
            print("    %s: %s" % (carrier, "REFUSED (required)" if refused
                                  else "NOT REFUSED"))
            ok &= refused

    print("OVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
