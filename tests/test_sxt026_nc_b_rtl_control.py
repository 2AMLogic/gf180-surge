#!/usr/bin/env python3
"""Live NC-B RTL negative control (#529).

`-DWAVETABLE_MUTANT_MIP` must FAIL the RTL-vs-model comparison on the pinned
control fixture (`kick-wtfix-kt` / `seq-wt-pitch-extremes-hi-v1`) while the
clean RTL PASSes the same stimulus. If the mutant stops failing, the committed
NC-B RTL evidence row no longer demonstrates what it claims and this test
fails. Unlike tests/test_sxt026_wt_rtl_harness.py this runs the REAL iverilog
and the real frozen model; it is SKIPPED (NOT_RUN, never a pass) when iverilog
or the pinned Surge asset tree is unavailable.

Not claimed here: that the mutant is caught on seq-wt-base-v1 or
seq-wt-pitch-extremes-v1 (it is not; see reports/sxt-026/EVIDENCE.md).
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_MODEL = os.path.join(REPO, "model", "oscillators", "wavetable",
                         "run_model.py")
HARNESS = os.path.join(REPO, "tools", "compare_wt_rtl_model.py")
INPUTS = os.path.join(REPO, "model", "oscillators", "wavetable", "inputs",
                      "kick-wtfix-kt.json")
SEQUENCE = "seq-wt-pitch-extremes-hi-v1"
_PIN = "58914e59c608ed4384ba6002e44c3465c58b2e71"


def _data_root():
    env = os.environ.get("ORACLE_SURGE_DATA")
    if env:
        return env
    base = os.environ.get("ORACLE_SURGE_DIR") or os.path.join(
        REPO, "oracle", "build", "surge")
    return os.path.join(base, "resources", "data")


def _needs():
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        return "iverilog/vvp not available"
    if not os.path.isfile(os.path.join(
            _data_root(), "wavetables", "Basic", "Triangle.wt")):
        return "pinned surge@%s asset tree not available" % _PIN[:8]
    return None


@pytest.mark.skipif(_needs() is not None, reason=_needs() or "")
def test_nc_b_rtl_mutant_fails_comparison_while_clean_passes(tmp_path):
    run_dir = str(tmp_path / "kt")
    env = dict(os.environ, ORACLE_SURGE_DATA=_data_root())
    r = subprocess.run([sys.executable, RUN_MODEL, "--inputs", INPUTS,
                        "--sequence", SEQUENCE, "--out-dir", run_dir,
                        "--rtl"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    with open(os.path.join(run_dir, "model_trace.json")) as f:
        blocks = len(json.load(f)["blocks"])

    verdicts = {}
    for tag, extra in (("clean", []), ("mutant", ["--mutant"])):
        out = os.path.join(run_dir, "v-%s.json" % tag)
        r = subprocess.run(
            [sys.executable, HARNESS, "--run-dir", run_dir, "--max-blocks",
             str(blocks), "--out", out] + extra,
            env=env, capture_output=True, text=True)
        with open(out) as f:
            verdicts[tag] = (r.returncode, json.load(f))

    rc, clean = verdicts["clean"]
    assert rc == 0 and clean["verdict"] == "PASS" and clean["mismatches"] == 0
    assert not clean["sim_fails"]

    rc, mut = verdicts["mutant"]
    # rc 0 on a --mutant run means "caught by the COMPARISON" (not traffic,
    # not a dead simulator).
    assert rc == 0, json.dumps(mut, indent=1)[:2000]
    assert not mut["sim_fails"], mut["sim_fails"]
    assert mut["verdict"] == "FAIL" and mut["mismatches"] > 0
