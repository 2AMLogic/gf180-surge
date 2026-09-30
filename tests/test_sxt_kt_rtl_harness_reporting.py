"""SXT-042 `tools/compare_kt_rtl_model.py` harness reporting controls
(#193, #207).

`compare_kt_rtl_model.py` is one of the "voice family" (`kt`/`mw`/`lfo`)
harnesses migrated by issue #207 to the shared
`tools/_rtl_compile_common.compile_and_run` helper's opt-in
`report_sim_fails=True` mode (issue #193's re-enumeration of the #188 blind
spot: a `$readmemh` target that fails to open is reported by Icarus on the
simulation's STDOUT, and `check=True` alone cannot see it, so the harness's
own comparison could go on to read an empty/partial trace as though it were
a genuine RTL-vs-model disagreement).

The simulator is STUBBED here (no iverilog, no vvp) -- these are
reporting-path controls only, not evidence about the RTL, the frozen model,
or their agreement. The real-toolchain measurement of tb_kt.sv's healthy
stdout (the false-positive baseline below) and of the missing-
`rtl/kt_ctrl.hex` repro are issue #207's own evidence, reproduced from a
real Icarus 13.0 run against a genuine run dir built by
`model/voice/run_kt_model.py --sequence sxt025-accept-v1`:

  * healthy run: two `$readmemh(...): Not enough words...` WARNINGs (this
    repo's committed hex fixtures are deliberately shorter than the
    testbench's declared memory ranges), the `DONE kt-qmuls=...` marker and
    `$finish` -- never the `$readmem`+`Unable to open` conjunction.
  * `rtl/kt_ctrl.hex` removed: Icarus prints
    `ERROR: .../tb_kt.sv:93: $readmemh: Unable to open rtl/kt_ctrl.hex for
    reading.` on stdout, then this leaf's testbench also FATALs on the
    exhausted ctrl stream and `vvp` exits 1 (unlike the `lfo` leaf, this one
    does not race ahead with rc=0 -- but the missing-input pre-flight check
    (mechanism 1) fires before the simulator is ever invoked either way, so
    that distinction does not matter to the harness).
"""

import importlib
import os
import subprocess
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import _rtl_compile_common as rcc  # noqa: E402
import tools.compare_kt_rtl_model as mod  # noqa: E402

importlib.reload(mod)  # ensure a clean module object per test session

SIM_STDERR = "vvp: tb_kt.vvp: simulated simulator failure (no rtl/kt_ctrl.hex)"

READMEMH_STDOUT = (
    "WARNING: %s/rtl/voice/tb_kt.sv:92: $readmemh(rtl/kt_routes.hex): Not "
    "enough words in the file for the requested range [0:191].\n"
    "ERROR: %s/rtl/voice/tb_kt.sv:93: $readmemh: Unable to open "
    "rtl/kt_ctrl.hex for reading.\n"
    "FATAL: %s/rtl/voice/tb_kt.sv:119: kt ctrl stream exhausted at block 0\n"
    "       Time: 0  Scope: tb_kt.run\n" % (REPO, REPO, REPO))

# Measured on real Icarus 13.0 against tb_kt.sv (issue #207 evidence): a
# healthy run's stdout is two size-mismatch WARNINGs plus the DONE marker
# and $finish -- never the $readmem+"Unable to open" conjunction the
# matcher requires.
HEALTHY_STDOUT = (
    "WARNING: %s/rtl/voice/tb_kt.sv:92: $readmemh(rtl/kt_routes.hex): Not "
    "enough words in the file for the requested range [0:191].\n"
    "WARNING: %s/rtl/voice/tb_kt.sv:93: $readmemh(rtl/kt_ctrl.hex): Not "
    "enough words in the file for the requested range [0:1999999].\n"
    "DONE kt-qmuls=180126\n"
    "%s/rtl/voice/tb_kt.sv:112: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO))

MODEL_TRACE = {
    "sequence": "test-seq",
    "control_mode": "normal",
    "blocks": [{
        "b": 0,
        "voices": [{
            "slot": 0,
            "kt_word": 100,
            "kt_route_sums": [10, 20, 30],
            "mod_cutoff": 1, "mod_reso": 2, "mod_envmod": 3, "mod_vca_db": 4,
        }],
    }],
}

MATCHING_TRACE = "V 0 0 100 10 20 30 1 2 3 4\n"
MISMATCHING_TRACE = "V 0 0 101 10 20 30 1 2 3 4\n"


def _write_run_dir(tmp_path):
    run_dir = str(tmp_path)
    import json
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
            with open(os.path.join(run_dir, "tb_kt_trace.txt"), "w") as f:
                f.write(trace_text)
        rc, err = sim_rc, (SIM_STDERR if sim_rc else "")
        return types.SimpleNamespace(returncode=rc, stdout=sim_stdout,
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
    import json
    out = os.path.join(run_dir, "verdict.json")
    monkeypatch.setattr(sys, "argv",
                        ["compare_kt_rtl_model.py", "--run-dir", run_dir,
                         "--out", out] + list(extra))
    rc = mod.main()
    with open(out) as f:
        return rc, json.load(f)


def test_agreeing_trace_still_passes(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 0
    assert d["rtl_qmuls"] == 180126
    assert d["checked"]["voice_checkpoints"] == 1
    assert d["checked"]["fields"] == 8


def test_comparison_mismatch_still_reported(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MISMATCHING_TRACE)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 1
    assert "kt_word" in d["first_failures"][0]


def test_missing_stimulus_file_is_named_and_not_a_comparison_disagreement(
        tmp_path, monkeypatch):
    """issue #193's failure control: delete exactly one hex file."""
    run_dir = _write_run_dir(tmp_path)
    os.remove(os.path.join(run_dir, "rtl/kt_ctrl.hex"))
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/kt_ctrl.hex" in d["sim_fails"][0]
    joined = "\n".join(d["first_failures"])
    assert "missing V line" not in joined, joined
    assert d["checked"]["fields"] == 0, d["checked"]
    assert d["rtl_qmuls"] is None, d
    assert calls == [], calls  # the simulator is never even invoked


def test_readmemh_open_failure_on_stdout_is_a_sim_failure(
        tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 1, None, sim_stdout=READMEMH_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert d["sim_fails"], d["sim_fails"]
    joined = "\n".join(d["sim_fails"])
    assert "rtl/kt_ctrl.hex" in joined
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


def test_compile_failure_is_recorded_instead_of_raising(tmp_path, monkeypatch):
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
