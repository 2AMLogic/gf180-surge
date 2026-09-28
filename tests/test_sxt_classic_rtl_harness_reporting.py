"""SXT-033 `tools/compare_classic_rtl_model.py` harness reporting controls
(issue #208, decomposing #201).

`compare_classic_rtl_model.py` is one of the harnesses migrated to
`_rtl_compile_common.compile_and_run`'s `report_sim_fails=True` /
`stimulus_files=...` mode (issue #193's re-enumeration of the #188 blind
spot: a `$readmemh` target that fails to open is reported by Icarus on the
simulation's STDOUT while `vvp` still exits 0, so `check=True` alone never
sees it, and the harness's own comparison goes on to read an empty/partial
trace as though it were a genuine RTL-vs-model disagreement).

The simulator is STUBBED here (no iverilog, no vvp) -- these are
reporting-path controls only, not evidence about the RTL, the frozen model,
or their agreement. The real-toolchain measurement of tb_classic.sv's
healthy stdout (the false-positive baseline below) and of the missing-
`rtl/ctrl.hex` repro (rc=0, `$readmemh: Unable to open ... for reading.` on
stdout) were both measured against this repo's Icarus 13.0 (issue #208
evidence, retained alongside the PR): a healthy run of tb_classic.sv emits
only Icarus's `$readmemh(...): Not enough words...` WARNING (this repo's
committed `ctrl.hex` fixture is deliberately shorter than the testbench's
declared memory range) plus the DONE marker and $finish -- never the
`$readmem`+`Unable to open` conjunction this matcher looks for.
"""

import importlib
import json
import os
import subprocess
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import _rtl_compile_common as rcc  # noqa: E402
import tools.compare_classic_rtl_model as mod  # noqa: E402

importlib.reload(mod)  # ensure a clean module object per test session

TB_REL = "rtl/oscillators/classic/tb_classic.sv"

SIM_STDERR = "vvp: tb.vvp: simulated simulator failure (no rtl/ctrl.hex)"

# Measured against real Icarus 13.0 with `rtl/ctrl.hex` removed from an
# otherwise-complete run dir (issue #208 evidence): rc=0, one ERROR line,
# and the testbench's own DONE/$finish sequence runs anyway.
READMEMH_STDOUT = (
    "ERROR: %s/%s:153: $readmemh: Unable to open rtl/ctrl.hex for "
    "reading.\nDONE qmuls=76800 blocks=96\n%s/%s:162: $finish called at 0 "
    "(1ps)\n" % (REPO, TB_REL, REPO, TB_REL))

# Measured against real Icarus 13.0 with the committed fixtures present
# (issue #208 evidence): the testbench's own size-mismatch WARNING (the
# committed `ctrl.hex` fixture is deliberately shorter than the testbench's
# declared memory range) plus DONE/$finish -- never the
# $readmem+"Unable to open" conjunction.
HEALTHY_STDOUT = (
    "WARNING: %s/%s:153: $readmemh(rtl/ctrl.hex): Not enough words in the "
    "file for the requested range [0:4200000].\nDONE qmuls=135110 "
    "blocks=96\n%s/%s:162: $finish called at 0 (1ps)\n"
    % (REPO, TB_REL, REPO, TB_REL))

MODEL_TRACE = {
    "n_unison": 1,
    "blocks": [{
        "b": 0,
        "mono_block": [100, -200, 300],
        "voices": [{
            "slot": 0, "oscout_block": [1, 2, 3],
            "after": {
                "aeg": {"state": 1, "phase": 4, "output": 5},
                "l_shape": 6, "l_pw": 7, "l_pw2": 8, "l_sub": 9,
                "l_sync": 10, "dc": 11, "osc_out": 12, "osc_out2": 13,
                "bufpos": 0, "hpf_prev": 14, "gain_end": 15,
                "oscstate": [16], "syncstate": [17], "state": [18],
                "last_level": [19], "pwidth": [20], "pwidth2": [21],
                "dc_uni": [22],
            },
        }],
    }],
}


def _t_line(overrides):
    """Build a `T` line in `mod.T_FIELDS` order -- shields this fixture from
    a field-order/count change in the harness (which would otherwise need a
    parallel hand-counted edit here)."""
    d = {f: 0 for f in mod.T_FIELDS}
    d.update(overrides)
    vals = [d[f] for f in mod.T_FIELDS]
    return "T " + " ".join(str(v) for v in vals)


MATCHING_TRACE = (
    _t_line({
        "b": 0, "slot": 0, "key": 60, "aeg_state": 1, "aeg_phase": 4,
        "aeg_out": 5, "n_unison": 1,
        "u0_oscstate": 16, "u0_syncstate": 17, "u0_state": 18,
        "u0_last_level": 19, "u0_pwidth": 20, "u0_pwidth2": 21,
        "u0_dc_uni": 22,
        "l_shape": 6, "l_pw": 7, "l_pw2": 8, "l_sub": 9, "l_sync": 10,
        "dc": 11, "osc_out": 12, "osc_out2": 13, "bufpos": 0,
        "hpf_prev": 14, "gain_end": 15,
    }) + "\n"
    "O 0 0 1 2 3\n"
    "M 0 100\nM 0 -200\nM 0 300\n")

MISMATCHING_TRACE = MATCHING_TRACE.replace("M 0 100", "M 0 101", 1)


def _write_run_dir(tmp_path):
    run_dir = str(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(MODEL_TRACE, f)
    os.makedirs(os.path.join(run_dir, "rtl"), exist_ok=True)
    for rel in mod.STIMULUS_RELPATHS:
        open(os.path.join(run_dir, rel), "w").close()
    return run_dir


def _stub_simulator(monkeypatch, run_dir, sim_rc, trace_text, sim_stdout="",
                    calls=None):
    def fake_run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd[0])
        if cmd[0] == "iverilog":
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if trace_text is not None:
            with open(os.path.join(run_dir, "tb_trace.txt"), "w") as f:
                f.write(trace_text)
        err = SIM_STDERR if sim_rc else ""
        return types.SimpleNamespace(returncode=sim_rc, stdout=sim_stdout,
                                     stderr=err)

    monkeypatch.setattr(rcc, "subprocess",
                        types.SimpleNamespace(
                            run=fake_run, DEVNULL=subprocess.DEVNULL,
                            CalledProcessError=subprocess.CalledProcessError,
                            TimeoutExpired=subprocess.TimeoutExpired))


def _delegating_simulator(monkeypatch, substitutions, calls):
    def real_run(cmd, **kwargs):
        calls.append(cmd[0])
        return subprocess.run(substitutions.get(cmd[0], cmd), **kwargs)

    monkeypatch.setattr(rcc, "subprocess",
                        types.SimpleNamespace(
                            run=real_run, DEVNULL=subprocess.DEVNULL,
                            CalledProcessError=subprocess.CalledProcessError,
                            TimeoutExpired=subprocess.TimeoutExpired))


def _run_harness(monkeypatch, run_dir, extra=()):
    out = os.path.join(run_dir, "verdict.json")
    monkeypatch.setattr(sys, "argv",
                        ["compare_classic_rtl_model.py", "--run-dir",
                         run_dir, "--out", out] + list(extra))
    rc = mod.main()
    with open(out) as f:
        return rc, json.load(f)


def test_agreeing_trace_still_passes(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 0
    assert d["checked"]["mono"] == 3 and d["checked"]["fields"] > 0


def test_comparison_mismatch_still_reported(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MISMATCHING_TRACE)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 1
    assert "sample" in d["first_failures"][0]


def test_missing_stimulus_file_is_named_and_not_a_comparison_disagreement(
        tmp_path, monkeypatch):
    """issue #208's failure control: delete exactly one declared hex file."""
    run_dir = _write_run_dir(tmp_path)
    os.remove(os.path.join(run_dir, "rtl/ctrl.hex"))
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/ctrl.hex" in d["sim_fails"][0]
    joined = "\n".join(d["first_failures"])
    assert "missing T line" not in joined, joined
    assert d["checked"]["fields"] == 0, d["checked"]
    assert calls == [], calls  # the simulator is never even invoked


def test_readmemh_open_failure_on_stdout_with_rc_zero_is_a_sim_failure(
        tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, None, sim_stdout=READMEMH_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/ctrl.hex" in d["sim_fails"][0]
    assert "rc=0" in d["sim_fails"][0]
    assert "$readmemh" in d["sim_stdout_tail"]
    assert d["checked"]["fields"] == 0, d["checked"]


def test_healthy_stdout_diagnostics_do_not_flip_a_pass(tmp_path, monkeypatch):
    """FALSE-POSITIVE control (issue #188's guardrail, re-measured for this
    leaf's own testbench diagnostics -- see module docstring)."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""


def test_simulator_failure_is_reported_with_its_stderr(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 4, MATCHING_TRACE)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    joined = "\n".join(d["sim_fails"])
    assert "vvp exited rc=4" in joined, joined
    assert SIM_STDERR in joined, joined


def test_compile_failure_is_recorded_instead_of_raising(tmp_path,
                                                         monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    calls = []
    _delegating_simulator(
        monkeypatch,
        {"iverilog": ["sh", "-c", "echo 'syntax error' >&2; exit 3"]}, calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert calls == ["iverilog"], calls
    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "iverilog compile failed rc=3" in d["sim_fails"][0]
