"""SXT-021 `tools/compare_control_rtl.py` harness reporting controls (#193).

`compare_control_rtl.py` is one of the 10 real importers of the shared
`tools/_rtl_compile_common.compile_and_run` helper (issue #193's
re-enumeration of the #188 blind spot). Its testbench (`tb_control.sv`)
`$readmemh`s exactly one stimulus file, `events.hex`, which this harness
writes itself (`write_events_hex`) immediately before compiling/running --
different from the other migrated leaf (SXT-022's five `rtl/*.hex` files),
which is deliberately why this leaf was picked as the second migration: it
exercises the `run_by_name=True` / `compile_in_workdir=True` /
`stdout_path=...` / `trace_name=None` axis combination the shared helper's
own tests (`tests/test_rtl_compile_common.py`) cover individually but not
in this exact combination.

The simulator is STUBBED here (no iverilog, no vvp) -- reporting-path
controls only. The real-toolchain measurement of tb_control.sv's healthy
stdout (the false-positive baseline below) and of the missing-`events.hex`
repro (rc=0, `$readmemh: Unable to open events.hex for reading.` on stdout)
are issue #193's own evidence, reproduced from a real Icarus 13.0 run in
this environment.
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
import tools.compare_control_rtl as mod  # noqa: E402

importlib.reload(mod)

SIM_STDERR = "vvp: tb.vvp: simulated simulator failure (no events.hex)"

# Measured on real Icarus 13.0 against tb_control.sv (issue #193 evidence):
# missing events.hex -> rc=0, one ERROR line, and the testbench's own
# "BLOCKS x UNDERRUNS 0" runs to $finish anyway (undefined `x` sample count).
READMEMH_STDOUT = (
    "ERROR: %s/rtl/control/tb_control.sv:76: $readmemh: Unable to open "
    "events.hex for reading.\n"
    "BLOCKS x UNDERRUNS 0\n"
    "%s/rtl/control/tb_control.sv:127: $finish called at 17000 (1ps)\n"
    % (REPO, REPO))

# Measured on real Icarus 13.0 against tb_control.sv with real committed
# fixtures (issue #193 evidence): the testbench's own size-mismatch WARNING
# plus its BLOCKS/UNDERRUNS summary and $finish -- never the
# $readmem+"Unable to open" conjunction.
HEALTHY_STDOUT = (
    "WARNING: %s/rtl/control/tb_control.sv:76: $readmemh(events.hex): Not "
    "enough words in the file for the requested range [0:4097].\n"
    "BLOCKS 1805 UNDERRUNS 0\n"
    "%s/rtl/control/tb_control.sv:127: $finish called at 1173626000 (1ps)\n"
    % (REPO, REPO))

SEQ = {"id": "reporting-control-seq", "schema_version": 1, "events": [],
      "blocks": 1, "block_size": 32, "sample_rate": 48000, "voice_pool": 8}

# Precomputed once: the model's own trace/output for SEQ (CounterStubEngine,
# no events), so the stubbed "vvp" run below can write an rtl_trace.txt that
# genuinely AGREES with the model -- exercising the real `compare()` +
# byte-identity logic, not just a short-circuited empty comparison.
from model.control import render_sequence as _render_sequence  # noqa: E402
from model.control.engine_stub_counter import (  # noqa: E402
    CounterStubEngine as _CounterStubEngine,
)

_MODEL_TRACE, _MODEL_OUT, _ = _render_sequence(SEQ, _CounterStubEngine())


def _matching_rtl_trace_text():
    lines = []
    for rec in _MODEL_TRACE["blocks"]:
        b = rec["b"]
        snap = rec["snapshot_after"]
        t_fields = [snap["qcount"], snap["patch_id"], snap["active_count"]]
        for v in snap["voices"]:
            t_fields += [1 if v["active"] else 0, v["note"], v["seq"]]
        lines.append("T %d %s" % (b, " ".join(str(x) for x in t_fields)))
        for i in range(32):
            off = (b * 32 + i) * 4
            w = _MODEL_OUT[off:off + 4]
            l = int.from_bytes(w[0:2], "little")
            r = int.from_bytes(w[2:4], "little")
            lines.append("M %d %d %d %d" % (b, i, l, r))
    return "\n".join(lines) + "\n"


MATCHING_TRACE = _matching_rtl_trace_text()


def _stub_simulator(monkeypatch, run_dir, sim_rc, write_trace, sim_stdout="",
                    calls=None):
    def fake_run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd[0])
        if cmd[0] == "iverilog":
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        rc, err = 0, ""
        if write_trace:
            with open(os.path.join(run_dir, "rtl_trace.txt"), "w") as f:
                f.write(MATCHING_TRACE)
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


def test_agreeing_empty_sequence_still_passes(tmp_path, monkeypatch):
    run_dir = str(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, write_trace=True)

    v = mod.run_comparison(SEQ, run_dir)

    assert v["verdict"] == "PASS", v
    assert v["comparison"] == "PASS"
    assert v["sim_fails"] == []
    assert v["byte_identical_outputs"] is True


def test_comparison_mismatch_still_reported(tmp_path, monkeypatch):
    """Regression control: a genuinely disagreeing trace still FAILs the
    comparison (byte-identity), with sim_fails empty."""
    run_dir = str(tmp_path)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "iverilog":
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        mismatching = MATCHING_TRACE.replace(
            "M 0 0 %d %d" % (int.from_bytes(_MODEL_OUT[0:2], "little"),
                            int.from_bytes(_MODEL_OUT[2:4], "little")),
            "M 0 0 999 999", 1)
        assert mismatching != MATCHING_TRACE
        with open(os.path.join(run_dir, "rtl_trace.txt"), "w") as f:
            f.write(mismatching)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(rcc, "subprocess",
                        types.SimpleNamespace(
                            run=fake_run, DEVNULL=subprocess.DEVNULL,
                            CalledProcessError=subprocess.CalledProcessError,
                            TimeoutExpired=subprocess.TimeoutExpired))

    v = mod.run_comparison(SEQ, run_dir)

    assert v["verdict"] == "FAIL", v
    assert v["comparison"] == "FAIL"
    assert v["sim_fails"] == []
    assert v["byte_identical_outputs"] is False


def test_missing_events_hex_is_named_and_not_a_comparison_disagreement(
        tmp_path, monkeypatch):
    """issue #193's failure control: events.hex never gets written."""
    run_dir = str(tmp_path)
    monkeypatch.setattr(mod, "write_events_hex", lambda seq, path: 0)
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, write_trace=True, calls=calls)

    v = mod.run_comparison(SEQ, run_dir)

    assert v["verdict"] == "FAIL", v
    assert v["comparison"] == "NOT_RUN", v
    assert len(v["sim_fails"]) == 1, v["sim_fails"]
    assert "events.hex" in v["sim_fails"][0]
    joined = "\n".join(v["first_failures"])
    assert "missing/short T line" not in joined, joined
    assert v["checked"]["snapshots"] == 0, v["checked"]
    assert v["byte_identical_outputs"] is False
    assert calls == [], calls   # the simulator is never even invoked


def test_readmemh_open_failure_on_stdout_with_rc_zero_is_a_sim_failure(
        tmp_path, monkeypatch):
    run_dir = str(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, write_trace=False,
                    sim_stdout=READMEMH_STDOUT)

    v = mod.run_comparison(SEQ, run_dir)

    assert v["verdict"] == "FAIL", v
    assert v["comparison"] == "NOT_RUN", v
    assert len(v["sim_fails"]) == 1, v["sim_fails"]
    assert "events.hex" in v["sim_fails"][0]
    assert "rc=0" in v["sim_fails"][0]
    assert "$readmemh" in v["sim_stdout_tail"]
    assert v["checked"]["snapshots"] == 0, v["checked"]


def test_healthy_stdout_diagnostics_do_not_flip_a_pass(tmp_path, monkeypatch):
    """FALSE-POSITIVE control (issue #188's guardrail, re-measured for this
    leaf's own testbench diagnostics -- see module docstring)."""
    run_dir = str(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, write_trace=True,
                    sim_stdout=HEALTHY_STDOUT)

    v = mod.run_comparison(SEQ, run_dir)

    assert v["verdict"] == "PASS", v
    assert v["comparison"] == "PASS"
    assert v["sim_fails"] == []
    assert v["sim_stdout_tail"] == ""


def test_simulator_failure_is_reported_with_its_stderr(tmp_path, monkeypatch):
    run_dir = str(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 4, write_trace=True)

    v = mod.run_comparison(SEQ, run_dir)

    assert v["verdict"] == "FAIL", v
    assert v["comparison"] == "NOT_RUN", v
    joined = "\n".join(v["sim_fails"])
    assert "vvp exited rc=4" in joined, joined
    assert SIM_STDERR in joined, joined


def test_compile_failure_is_recorded_instead_of_raising(tmp_path,
                                                        monkeypatch):
    run_dir = str(tmp_path)
    calls = []
    _delegating_simulator(
        monkeypatch,
        {"iverilog": ["sh", "-c", "echo 'syntax error' >&2; exit 3"]}, calls)

    v = mod.run_comparison(SEQ, run_dir)

    assert calls == ["iverilog"], calls
    assert v["verdict"] == "FAIL", v
    assert v["comparison"] == "NOT_RUN", v
    assert len(v["sim_fails"]) == 1, v["sim_fails"]
    assert "iverilog compile failed rc=3" in v["sim_fails"][0]
