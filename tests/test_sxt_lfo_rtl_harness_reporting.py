"""SXT-032 `tools/compare_lfo_rtl_model.py` harness reporting controls
(#193, #207).

`compare_lfo_rtl_model.py` is one of the "voice family" (`kt`/`mw`/`lfo`)
harnesses migrated by issue #207 to the shared
`tools/_rtl_compile_common.compile_and_run` helper's opt-in
`report_sim_fails=True` mode (issue #193's re-enumeration of the #188 blind
spot: a `$readmemh` target that fails to open is reported by Icarus on the
simulation's STDOUT while `vvp` still **exits 0**, and `check=True` alone
cannot see it, so the harness's own comparison goes on to read an
empty/partial trace as though it were a genuine RTL-vs-model disagreement).

The simulator is STUBBED here (no iverilog, no vvp) -- these are
reporting-path controls only, not evidence about the RTL, the frozen model,
or their agreement. The real-toolchain measurement of tb_lfo.sv's healthy
stdout (the false-positive baseline below) and of the missing-
`rtl/lfo_ctrl.hex` repro are issue #207's own evidence, reproduced from a
real Icarus 13.0 run against a genuine run dir built by
`model/voice/run_lfo_model.py --sequence seq-notes-repeated-v1`:

  * healthy run: `$readmemh(...): Too many/Not enough words...` WARNINGs
    (this repo's committed hex fixtures deliberately differ in size from
    the testbench's declared memory ranges), the `DONE lfo-qmuls=...`
    marker and `$finish` -- never the `$readmem`+`Unable to open`
    conjunction.
  * `rtl/lfo_ctrl.hex` removed: Icarus prints `ERROR: .../tb_lfo.sv:92:
    $readmemh: Unable to open rtl/lfo_ctrl.hex for reading.` on stdout and
    `vvp` still **exits 0**, `$finish`-ing normally -- this is the exact
    #188/#193 blind spot, genuinely reproduced on this leaf (unlike `kt`/
    `mw`, this testbench does not FATAL on the empty control memory, so
    `check=True` alone truly cannot see the failure without the pre-flight
    `stimulus_files` check or the stdout scan).
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
import tools.compare_lfo_rtl_model as mod  # noqa: E402

importlib.reload(mod)  # ensure a clean module object per test session

SIM_STDERR = ("vvp: tb_lfo.vvp: simulated simulator failure "
             "(no rtl/lfo_ctrl.hex)")

# Measured on real Icarus 13.0 against tb_lfo.sv with rtl/lfo_ctrl.hex
# removed (issue #207 evidence): rc=0, the DONE marker and $finish still
# print -- the genuine #188 blind spot.
READMEMH_STDOUT = (
    "WARNING: %s/rtl/voice/tb_lfo.sv:88: $readmemh(rtl/init.hex): Too many "
    "words in the file for the requested range [0:39].\n"
    "WARNING: %s/rtl/voice/tb_lfo.sv:90: $readmemh(rtl/lfo_routes.hex): Not "
    "enough words in the file for the requested range [0:63].\n"
    "ERROR: %s/rtl/voice/tb_lfo.sv:92: $readmemh: Unable to open "
    "rtl/lfo_ctrl.hex for reading.\n"
    "DONE lfo-qmuls=98400\n"
    "%s/rtl/voice/tb_lfo.sv:98: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO, REPO))

# Measured on real Icarus 13.0 against tb_lfo.sv (issue #207 evidence): a
# healthy run's stdout is size-mismatch WARNINGs plus the DONE marker and
# $finish -- never the $readmem+"Unable to open" conjunction the matcher
# requires.
HEALTHY_STDOUT = (
    "WARNING: %s/rtl/voice/tb_lfo.sv:88: $readmemh(rtl/init.hex): Too many "
    "words in the file for the requested range [0:39].\n"
    "WARNING: %s/rtl/voice/tb_lfo.sv:90: $readmemh(rtl/lfo_routes.hex): Not "
    "enough words in the file for the requested range [0:63].\n"
    "WARNING: %s/rtl/voice/tb_lfo.sv:92: $readmemh(rtl/lfo_ctrl.hex): Not "
    "enough words in the file for the requested range [0:4200000].\n"
    "DONE lfo-qmuls=13592\n"
    "%s/rtl/voice/tb_lfo.sv:98: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO, REPO))

MODEL_TRACE = {
    "blocks": [{
        "b": 0,
        "voices": [{
            "slot": 0,
            "lfo": [{"index": 0, "phase": 10, "env_state": 1, "env_phase": 2,
                    "env_val": 3, "output": 4}],
            "lfo_route_sums": [5, 6],
        }],
    }],
}

MATCHING_TRACE = "L 0 0 0 10 1 2 3 4\nS 0 0 5 6\n"
MISMATCHING_TRACE = "L 0 0 0 11 1 2 3 4\nS 0 0 5 6\n"


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
            with open(os.path.join(run_dir, "tb_lfo_trace.txt"), "w") as f:
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
                        ["compare_lfo_rtl_model.py", "--run-dir", run_dir,
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
    assert d["checked"]["lfo_checkpoints"] == 1
    assert d["checked"]["lfo_fields"] == 5
    assert d["checked"]["route_sums"] == 1


def test_comparison_mismatch_still_reported(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MISMATCHING_TRACE)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 1
    assert "phase" in d["first_failures"][0]


def test_missing_stimulus_file_is_named_and_not_a_comparison_disagreement(
        tmp_path, monkeypatch):
    """issue #193's failure control: delete exactly one hex file."""
    run_dir = _write_run_dir(tmp_path)
    os.remove(os.path.join(run_dir, "rtl/lfo_ctrl.hex"))
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/lfo_ctrl.hex" in d["sim_fails"][0]
    joined = "\n".join(d["first_failures"])
    assert "missing L line" not in joined, joined
    assert d["checked"]["lfo_fields"] == 0, d["checked"]
    assert calls == [], calls  # the simulator is never even invoked


def test_readmemh_open_failure_on_stdout_with_rc_zero_is_a_sim_failure(
        tmp_path, monkeypatch):
    """The genuine #188 blind spot on this leaf: rc=0 despite the missing
    file, so `check=True` alone would never have caught it."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, None, sim_stdout=READMEMH_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/lfo_ctrl.hex" in d["sim_fails"][0]
    assert "rc=0" in d["sim_fails"][0]
    assert "$readmemh" in d["sim_stdout_tail"]
    assert d["checked"]["lfo_fields"] == 0, d["checked"]


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
