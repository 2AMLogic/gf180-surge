"""#145: the SXT-026a wrong-parameterization RTL control stays a live,
isolating control.

`rtl/voice/voice_wrongparam_mutant.sv` had drifted into a stale snapshot of
an older `tb_voice.sv` (commit 4a5a1a5: pre-SXT-034 cfg layout, pre-#123
halfband order, ~260 differing lines). Measured in #145: the UNMUTATED base
of that snapshot also FAILs RTL-vs-model exactness at HEAD (41 mismatches on
the smoke fixture), so the control failed whether or not its mutation was
present -- it no longer isolated the thing it targets. #145 regenerated it
as tb_voice.sv plus exactly one mutated line (and a 4-line banner). These
tests keep it that way: a control that differs from the clean testbench in
more than the targeted line would not demonstrate anything.

Nothing here is a fidelity, preset-support, or hardware claim.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_voice.sv")
MUTANT = os.path.join(REPO, "rtl", "voice", "voice_wrongparam_mutant.sv")
HAS_IVERILOG = all(shutil.which(x) for x in ("iverilog", "vvp"))

CLEAN_LINE = "    poles = 32'(cfg[41]);                     // SXT-026a: 12 or 24"
MUTANT_LINE = ("    poles = 32'sd12;                          "
               "// WRONG-PARAM MUTANT: ignores declared fu_poles")
BANNER = 4


def _lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def test_wrongparam_mutant_is_a_single_line_mutation_of_tb_voice():
    tb = _lines(TB)
    mut = _lines(MUTANT)
    assert mut[0].startswith("// SXT-026a NEGATIVE CONTROL MUTANT")
    body = mut[BANNER:]
    assert len(body) == len(tb), (
        "voice_wrongparam_mutant.sv drifted from tb_voice.sv; regenerate it "
        "as tb_voice.sv + the single fu_poles mutation")
    diff = [(a, b) for a, b in zip(tb, body) if a != b]
    assert diff == [(CLEAN_LINE, MUTANT_LINE)]


def _smoke_run(tmp_path):
    run_dir = str(tmp_path / "run")
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "model", "voice", "run_model.py"),
         "--sequence", "leaf48-smoke-bells-v1",
         "--inputs", os.path.join(REPO, "model", "voice", "bells_inputs.json"),
         "--out-dir", run_dir],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return run_dir


@pytest.mark.skipif(not HAS_IVERILOG, reason="iverilog/vvp not present")
def test_wrongparam_mutant_fails_exactness_on_the_lp24_smoke(tmp_path):
    """Live control: the Bells smoke fixture declares fu_poles = 24, so an
    RTL that ignores the declared pole count must FAIL integer equality
    against the same model trace the clean tb passes (the clean leg is
    tests/test_halfband_d2_voice.py::test_rtl_vs_model_exact_after_the_
    coordinated_fix)."""
    run_dir = _smoke_run(tmp_path)
    out = str(tmp_path / "nc.json")
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "compare_rtl_model.py"),
         "--run-dir", run_dir, "--tb", MUTANT, "--out", out],
        capture_output=True, text=True, cwd=REPO)
    with open(out, encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["verdict"] == "FAIL"
    assert summary["mismatches"] > 0
    assert r.returncode != 0
