"""SXT-040 `tools/compare_sine_rtl_model.py` harness reporting controls
(issue #208, decomposing #201).

`compare_sine_rtl_model.py` is one of the harnesses migrated to
`_rtl_compile_common.compile_and_run`'s `report_sim_fails=True` /
`stimulus_files=...` mode (issue #193's re-enumeration of the #188 blind
spot: a `$readmemh` target that fails to open is reported by Icarus on the
simulation's STDOUT while `vvp` still exits 0, so `check=True` alone never
sees it, and the harness's own comparison goes on to read an empty/partial
trace as though it were a genuine RTL-vs-model disagreement). This harness
also has a `--trace` reuse path that skips the simulator entirely (used to
re-run the comparison against an already-captured trace file); that path
never invokes `compile_and_run` at all, so it always reports `sim_fails: []`
and a `comparison` verdict driven purely by the comparison itself -- covered
below so the migration does not accidentally leave that branch stale.

The simulator is STUBBED here (no iverilog, no vvp) -- these are
reporting-path controls only, not evidence about the RTL, the frozen model,
or their agreement. The real-toolchain measurement of tb_sine.sv's healthy
stdout (the false-positive baseline below) and of the missing-`rtl/ctrl.hex`
repro (rc=0, `$readmemh: Unable to open ... for reading.` on stdout) were
both measured against this repo's Icarus 13.0 (issue #208 evidence, retained
alongside the PR): a healthy run of tb_sine.sv emits only Icarus's
`$readmemh(...): Not enough words...` WARNING (this repo's committed
`ctrl.hex` fixture is deliberately shorter than the testbench's declared
memory range) plus the DONE marker and $finish -- never the
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
import tools.compare_sine_rtl_model as mod  # noqa: E402

importlib.reload(mod)  # ensure a clean module object per test session

TB_REL = "rtl/oscillators/sine/tb_sine.sv"

SIM_STDERR = "vvp: tb.vvp: simulated simulator failure (no rtl/ctrl.hex)"

# Measured against real Icarus 13.0 with `rtl/ctrl.hex` removed from an
# otherwise-complete run dir (issue #208 evidence): rc=0, one ERROR line,
# and the testbench's own DONE/$finish sequence runs anyway.
READMEMH_STDOUT = (
    "ERROR: %s/%s:172: $readmemh: Unable to open rtl/ctrl.hex for "
    "reading.\nDONE qmuls=76800 blocks=2017659\n%s/%s:181: $finish called "
    "at 0 (1ps)\n" % (REPO, TB_REL, REPO, TB_REL))

# Measured against real Icarus 13.0 with the committed fixtures present
# (issue #208 evidence): the testbench's own size-mismatch WARNING (the
# committed `ctrl.hex` fixture is deliberately shorter than the testbench's
# declared memory range) plus DONE/$finish -- never the
# $readmem+"Unable to open" conjunction.
HEALTHY_STDOUT = (
    "WARNING: %s/%s:172: $readmemh(rtl/ctrl.hex): Not enough words in the "
    "file for the requested range [0:4200000].\nDONE qmuls=279570 "
    "blocks=2017659\n%s/%s:181: $finish called at 0 (1ps)\n"
    % (REPO, TB_REL, REPO, TB_REL))

MODEL_TRACE = {
    "n_unison": 1,
    "legacy": False,
    "blocks": [{
        "b": 0,
        "mono_block": [100, -200, 300],
        "voices": [{
            "slot": 0, "oscout_block": [1, 2, 3],
            "after": {
                "aeg": {"state": 1, "phase": 4, "output": 5},
                "fb_v": 6, "fm_v": 7, "firstblock": 1,
                "hp_r0": 8, "hp_r1": 9, "lp_r0": 10, "lp_r1": 11,
                "char_py": 12, "char_px": 13, "gain_end": 14,
                "prior_valid": 1,
                "phase": [15], "lv0": [16], "lv1": [17], "om_prior": [18],
            },
        }],
    }],
}


def _t_line(b, s, key, legacy, nuni, aeg_state, aeg_phase, aeg_out,
           u_values, prior_valid=None):
    """Modern (non-legacy) `T` line: b s key legacy nuni aeg_state aeg_phase
    aeg_out, then MAXUNI groups of MODERN_U_FIELDS (phase lv0 lv1 om_prior),
    then prior_valid -- mirrors `parse_tb`'s modern-branch layout exactly."""
    vals = [b, s, key, int(legacy), nuni, aeg_state, aeg_phase, aeg_out]
    for u in range(mod.MAXUNI):
        vals += list(u_values.get(u, (0, 0, 0, 0)))
    vals.append(0 if prior_valid is None else prior_valid)
    return "T " + " ".join(str(v) for v in vals)


def _s_line(b, s, fb_v, fm_v, firstblock, hp_r0, hp_r1, lp_r0, lp_r1,
           char_py, char_px):
    vals = [b, s, fb_v, fm_v, firstblock, hp_r0, hp_r1, lp_r0, lp_r1,
            char_py, char_px]
    return "S " + " ".join(str(v) for v in vals)


def _g_line(b, s, gain):
    return "G %d %d %d" % (b, s, gain)


MATCHING_TRACE = (
    _t_line(0, 0, 60, False, 1, 1, 4, 5, {0: (15, 16, 17, 18)},
           prior_valid=1) + "\n"
    + _s_line(0, 0, 6, 7, 1, 8, 9, 10, 11, 12, 13) + "\n"
    + _g_line(0, 0, 14) + "\n"
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
                        ["compare_sine_rtl_model.py", "--run-dir", run_dir,
                         "--out", out] + list(extra))
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


# --------------------------------------------------------- --trace reuse ---
# The `--trace` path skips `compile_and_run` entirely (it reuses an
# already-captured trace file), so it can never observe a simulator-level
# failure; these controls confirm the migration left that branch reporting
# `sim_fails: []` / a comparison-driven verdict, not a stale/missing field.

def test_trace_reuse_path_never_touches_the_simulator(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    trace_path = os.path.join(run_dir, "reused_trace.txt")
    with open(trace_path, "w") as f:
        f.write(MATCHING_TRACE)
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, None, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir, extra=["--trace", trace_path])

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""
    assert calls == [], calls  # never invokes iverilog/vvp


def test_trace_reuse_path_still_reports_a_mismatch(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    trace_path = os.path.join(run_dir, "reused_trace.txt")
    with open(trace_path, "w") as f:
        f.write(MISMATCHING_TRACE)
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, None, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir, extra=["--trace", trace_path])

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert calls == [], calls
