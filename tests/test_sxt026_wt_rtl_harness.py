#!/usr/bin/env python3
"""SXT-026 RTL-vs-model harness reporting controls (issues #182, #188, #197).

`tools/compare_wt_rtl_model.py` must report a SIMULATOR-level failure as its
own FAIL verdict, naming the reason, instead of raising on an unbound `fails`
(#182), instead of discarding that message when the comparison's own fail list
is merged in (#182), and instead of presenting it as a wall of comparison
mismatches (#188). The five mechanisms controlled here:

  * a declared input (`model_trace.json`, `rtl/*.hex`) missing before the
    simulator is invoked at all                                        (#188)
  * a `model_trace.json` that is PRESENT but unreadable -- malformed JSON,
    mode 000, non-UTF-8 bytes -- which the existence-only pre-flight above
    cannot distinguish from a usable one                                (#197)
  * `$readmemh: Unable to open ...` on vvp's STDOUT while vvp exits 0  (#188)
  * a non-zero vvp exit                                          (#182/#190)
  * `CalledProcessError` from iverilog / `TimeoutExpired` from vvp     (#188)

plus the two false-positive controls that matter more than any of them: a
healthy run whose stdout carries the testbench's own benign diagnostics must
still verdict PASS, and a genuine comparison disagreement must still be
reported as one.

Scope of these controls: the harness's reporting path ONLY. The simulator is
stubbed (no iverilog, no vvp, no external pinned asset tree), so nothing here
is evidence about the RTL, the frozen model, or their agreement -- the
end-to-end exactness run is step 6 of `tools/run_sxt026_checks.py`, which
needs the pinned asset tree.
"""

import importlib.util
import json
import os
import subprocess
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(REPO, "tools", "compare_wt_rtl_model.py")

# Distinctive stderr text the stubbed simulator emits; the harness must carry
# it into the summary verbatim (truncated to the last 500 chars at most).
SIM_STDERR = "vvp: tb_wt.vvp: simulated simulator failure (no rtl/init.hex)"

# Verbatim shape of what Icarus prints on STDOUT when a $readmemh target is
# absent -- and it then exits 0 (measured on Icarus 11, 12.0 and 13.0; issue
# #188, whose Finding section this transcript is copied from).
READMEMH_STDOUT = "".join(
    "ERROR: %s/rtl/oscillators/wavetable/tb_wavetable.sv:%d: $readmemh: "
    "Unable to open %s for reading.\n" % (REPO, line, path)
    for line, path in ((277, "rtl/init.hex"), (279, "rtl/ctrl.hex"),
                       (280, "rtl/wt_table.hex"),
                       (281, "rtl/sinc_main.hex"),
                       (288, "rtl/sinc_deriv.hex")))

# What a run whose stimulus DID load prints on stdout: the testbench's own
# diagnostics (DBG / WARNING / "TB done" / $finish) plus Icarus's own
# `$readmemh(...): Not enough words` WARNING -- the last of these transcribed
# from a real Icarus 13.0 run and included deliberately, because it contains
# the `$readmemh` token and so pins the matcher's conjunction (`$readmem` AND
# `Unable to open`) as load-bearing. It is a WARNING about file *length*, not
# an open failure: `ctrl_mem` alone is declared [0:262143], so a real run is
# expected to emit it, and matching it would flip a genuinely passing
# exactness run to FAIL -- the one outcome worse than the lost reason #188
# exists to fix.
HEALTHY_STDOUT = (
    "DBG loading hex files\n"
    "WARNING: %s/rtl/oscillators/wavetable/tb_wavetable.sv:279: "
    "$readmemh(rtl/ctrl.hex): Not enough words in the file for the "
    "requested range [0:262143].\n"
    "WARNING: ctrl block index 0 != 1\n"
    "DBG block 0 done @2000\n"
    "TB done: blocks 1 ext_reads 2 fill_words 0 bursts 1 stall 0 reverb 0\n"
    "%s/rtl/oscillators/wavetable/tb_wavetable.sv:424: $finish called at "
    "73500 (1ps)\n" % (REPO, REPO))

# One declared checkpoint, one slot, one unison voice. Model-side state is
# written in the harness's own convention: per-voice and shared 32-bit fields
# are unsigned words that the harness re-signs with to_signed32().
MODEL_AFTER = {
    "oscstate": [11],
    "osc_state": [22],
    "last_level": [0xFFFFFFFD],   # -3
    "mipmap": [2],
    "tableid": 1,
    "tableipol": 0x00001000,      # 4096
    "last_tableipol": 0,
    "l_shape": 0xFFFFFF00,        # -256
    "osc_out": 0x00000040,        # 64
    "bufpos": 64,
    "hpf_prev": 0xFFFFFFFF,       # -1
}
MODEL_OSCOUT = [0, 1, 0xFFFFFFFF]  # 0, 1, -1

# The trace an agreeing simulator would have written for MODEL_AFTER.
MATCHING_TRACE = ("T 0 0 0 11 22 -3 2\n"
                  "S 0 0 1 4096 0 -256 64 64 -1\n"
                  "O 0 0 0 1 -1\n")

# Same, with one per-voice field perturbed (oscstate 11 -> 12).
MISMATCHING_TRACE = ("T 0 0 0 12 22 -3 2\n"
                     "S 0 0 1 4096 0 -256 64 64 -1\n"
                     "O 0 0 0 1 -1\n")


def _load_harness():
    spec = importlib.util.spec_from_file_location(
        "sxt026_compare_wt_rtl_model", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The hex stimulus the harness declares (single source of truth: the harness's
# own STIMULUS table, which also builds vvp's command line). The run-dir
# fixture creates exactly these, so a control can delete one and require the
# harness to name it.
STIMULUS_RELPATHS = [rel for _, rel in _load_harness().STIMULUS]


def _write_run_dir(tmp_path):
    """A complete run dir: the model trace plus all five hex stimulus files.

    The stimulus files are empty on purpose -- the harness's pre-simulator
    check (#188) asserts their EXISTENCE, and the simulator that would read
    their contents is stubbed in every control here.
    """
    run_dir = str(tmp_path)
    trace = {
        "unison": 1,
        "wave_size": 1024,
        "n_tables": 2,
        "nointerp": 0,
        "legacy": 0,
        "blocks": [{"b": 0, "voices": [{"slot": 0,
                                        "after": MODEL_AFTER,
                                        "oscout_block": MODEL_OSCOUT}]}],
    }
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(trace, f)
    os.makedirs(os.path.join(run_dir, "rtl"), exist_ok=True)
    for rel in STIMULUS_RELPATHS:
        open(os.path.join(run_dir, rel), "w").close()
    return run_dir


def _stub_simulator(mod, monkeypatch, run_dir, sim_rc, trace_text,
                    sim_stdout="", calls=None):
    """Replace the harness's subprocess use with a stub iverilog + vvp.

    The stub vvp writes `trace_text` (as a real vvp run would), prints
    `sim_stdout` on stdout, and exits with `sim_rc`, emitting SIM_STDERR on
    stderr when that is non-zero. `calls` (if given) records each argv[0] so a
    control can assert the simulator was never reached.
    """
    def fake_run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd[0])
        rc, err = 0, ""
        if cmd[0] == "vvp":
            if trace_text is not None:
                with open(os.path.join(run_dir, "tb_trace.s0"), "w") as f:
                    f.write(trace_text)
            rc, err = sim_rc, (SIM_STDERR if sim_rc else "")
        return types.SimpleNamespace(returncode=rc, stdout=sim_stdout,
                                     stderr=err)

    monkeypatch.setattr(mod, "subprocess",
                        types.SimpleNamespace(
                            run=fake_run,
                            CalledProcessError=subprocess.CalledProcessError,
                            TimeoutExpired=subprocess.TimeoutExpired))


def _delegating_simulator(mod, monkeypatch, substitutions, calls):
    """Run REAL subprocesses, substituting argv per tool.

    Used by the TimeoutExpired / CalledProcessError controls so the exception
    the harness must handle is raised by the real `subprocess` machinery
    (including its quirks: `TimeoutExpired.stdout` may be None) rather than by
    a hand-rolled stub.
    """
    def real_run(cmd, **kwargs):
        calls.append(cmd[0])
        return subprocess.run(substitutions.get(cmd[0], cmd), **kwargs)

    monkeypatch.setattr(mod, "subprocess",
                        types.SimpleNamespace(
                            run=real_run,
                            CalledProcessError=subprocess.CalledProcessError,
                            TimeoutExpired=subprocess.TimeoutExpired))


def _run_harness(mod, monkeypatch, run_dir, extra=()):
    out = os.path.join(run_dir, "verdict.json")
    monkeypatch.setattr(sys, "argv",
                        ["compare_wt_rtl_model.py", "--run-dir", run_dir,
                         "--max-blocks", "1", "--out", out] + list(extra))
    rc = mod.main()
    with open(out) as f:
        return rc, json.load(f)


def test_simulator_failure_is_reported_as_fail_with_its_stderr(tmp_path,
                                                               monkeypatch):
    """rc!=0 from vvp => FAIL whose first_failures names the simulator.

    The stubbed simulator still writes a *matching* trace, so the comparison
    itself finds nothing: only a harness that keeps the simulator-level
    failure can reach a FAIL verdict here.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(mod, monkeypatch, run_dir, 4, MATCHING_TRACE)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert rc != 0
    joined = "\n".join(d["first_failures"])
    assert "vvp exited rc=4" in joined, joined
    assert SIM_STDERR in joined, joined
    assert d["mismatches"] >= 1
    # #188: the run is a simulator-level failure, so the comparison is
    # NOT_RUN -- this path must keep working exactly as #182/#190 left it.
    assert d["comparison"] == "NOT_RUN", json.dumps(d, indent=1)


def test_simulator_failure_does_not_satisfy_the_mutant_control(tmp_path,
                                                               monkeypatch):
    """--mutant expects a COMPARISON failure, not a dead simulator.

    A simulator that never ran cannot demonstrate that the committed
    mip-threshold mutant is caught, so the mutant invocation must exit
    non-zero (NOT_RUN, not a passing negative control).
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(mod, monkeypatch, run_dir, 4, MATCHING_TRACE)

    rc, d = _run_harness(mod, monkeypatch, run_dir, extra=["--mutant"])

    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert SIM_STDERR in "\n".join(d["first_failures"])


def test_agreeing_trace_still_passes(tmp_path, monkeypatch):
    """Regression control: the PASS path is unchanged by the merge."""
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", json.dumps(d, indent=1)
    assert d["comparison"] == "PASS"
    assert d["mismatches"] == 0
    assert d["first_failures"] == []
    assert d["checked"]["fields"] > 0 and d["checked"]["oscout"] > 0


def test_comparison_mismatch_still_reported(tmp_path, monkeypatch):
    """Regression control: comparison mismatches survive the merge too."""
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(mod, monkeypatch, run_dir, 0, MISMATCHING_TRACE)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 1
    assert "field 0" in d["first_failures"][0], d["first_failures"]


# --------------------------------------------------------------------------
# issue #188 controls: a stimulus that never loaded, a timeout kill, a failed
# compile -- and the false-positive control that guards all three.
# --------------------------------------------------------------------------


def test_missing_stimulus_file_is_named_and_not_a_comparison_disagreement(
        tmp_path, monkeypatch):
    """Delete exactly one hex file: the verdict must NAME that file.

    This is issue #188's failure control. The pre-fix harness reported this
    same run as `sim_fails=[] mismatches=3 first_failures[0]='block 0 slot 0
    voice 0: missing T line'` -- a comparison disagreement, which it was not.
    Merely observing FAIL does not discriminate; the assertions below do.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    os.remove(os.path.join(run_dir, "rtl/wt_table.hex"))
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "NOT_RUN", json.dumps(d, indent=1)
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/wt_table.hex" in d["sim_fails"][0], d["sim_fails"]
    # ... and NOT as a comparison disagreement:
    joined = "\n".join(d["first_failures"])
    assert "missing T line" not in joined, joined
    assert d["checked"]["fields"] == 0, d["checked"]
    # The simulator is not even invoked -- the check is the cheaper, more
    # direct one the issue asked to decide on (checkbox 3).
    assert calls == [], calls


def test_readmemh_open_failure_on_stdout_with_rc_zero_is_a_sim_failure(
        tmp_path, monkeypatch):
    """Icarus's own transcript: rc=0, five ERROR lines on STDOUT.

    The stimulus files exist (so the pre-simulator check passes) but the
    simulator reports it could not open them -- the mechanism the pre-fix
    harness could not see at all, because it discarded vvp's stdout and vvp
    exits 0.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    # No trace written: as with the real repro, nothing usable was produced.
    _stub_simulator(mod, monkeypatch, run_dir, 0, None,
                    sim_stdout=READMEMH_STDOUT)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "NOT_RUN", json.dumps(d, indent=1)
    assert len(d["sim_fails"]) == 5, d["sim_fails"]
    joined = "\n".join(d["sim_fails"])
    for rel in STIMULUS_RELPATHS:
        assert rel in joined, (rel, joined)
    assert "rc=0" in joined, joined
    # vvp's stdout is retained on failure the way its stderr already was.
    assert "$readmemh" in d["sim_stdout_tail"], d["sim_stdout_tail"]
    # ... and not a single comparison mismatch is reported.
    assert "missing T line" not in "\n".join(d["first_failures"])
    assert d["checked"]["fields"] == 0, d["checked"]


def test_healthy_stdout_diagnostics_do_not_flip_a_pass(tmp_path, monkeypatch):
    """FALSE-POSITIVE control (the one that matters most, issue #188).

    A healthy run's stdout carries the testbench's own DBG / WARNING /
    "TB done" diagnostics. The stdout matcher must not read any of them as a
    stimulus-load failure: reporting a run that did not fail as failed is
    worse than the lost reason this change exists to recover.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", json.dumps(d, indent=1)
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""
    assert d["checked"]["fields"] > 0 and d["checked"]["oscout"] > 0


def test_stdout_matcher_is_narrow():
    """Unit control on the matcher itself: what it does and does not match.

    Deliberately NOT a bare `ERROR:`-prefix match -- it requires both the
    `$readmem` token and `Unable to open`, so the testbench's own diagnostics
    cannot trip it.
    """
    mod = _load_harness()

    hits = mod.scan_stdout_for_load_failures(READMEMH_STDOUT)
    assert len(hits) == 5, hits
    for rel in STIMULUS_RELPATHS:
        assert any(rel in h for h in hits), (rel, hits)

    assert mod.scan_stdout_for_load_failures(HEALTHY_STDOUT) == []
    assert mod.scan_stdout_for_load_failures("") == []
    assert mod.scan_stdout_for_load_failures(None) == []


def test_vvp_timeout_is_recorded_instead_of_raising(tmp_path, monkeypatch):
    """A real TimeoutExpired must become a sim_fails entry + a verdict.

    Pre-fix, `subprocess.TimeoutExpired` propagated out of `main()`: traceback,
    no verdict JSON, no recorded reason. The exception here is raised by the
    real subprocess machinery (a genuinely over-running child), not simulated.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    calls = []
    _delegating_simulator(mod, monkeypatch,
                          {"iverilog": ["true"],
                           "vvp": ["sh", "-c", "echo booting; sleep 1"]},
                          calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir,
                         extra=["--timeout", "0.3"])

    assert calls == ["iverilog", "vvp"], calls
    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "NOT_RUN", json.dumps(d, indent=1)
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "timeout" in d["sim_fails"][0], d["sim_fails"]
    assert "0.3" in d["sim_fails"][0], d["sim_fails"]


def test_compile_failure_is_recorded_instead_of_raising(tmp_path, monkeypatch):
    """A real CalledProcessError from iverilog must become a sim_fails entry.

    Pre-fix, `check=True` on the compile step raised straight out of `main()`:
    traceback, no verdict JSON, no recorded reason. The simulator must also
    never be invoked on an image that was not built.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    calls = []
    _delegating_simulator(
        mod, monkeypatch,
        {"iverilog": ["sh", "-c", "echo 'syntax error' >&2; exit 3"]}, calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert calls == ["iverilog"], calls
    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "NOT_RUN", json.dumps(d, indent=1)
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "iverilog compile failed rc=3" in d["sim_fails"][0], d["sim_fails"]


def test_missing_model_trace_is_named_without_raising(tmp_path, monkeypatch):
    """The model side of the comparison is a declared input too.

    Absent `model_trace.json` used to raise FileNotFoundError before anything
    was written; it is now reported the same way a missing hex file is.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    os.remove(os.path.join(run_dir, "model_trace.json"))
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "NOT_RUN"
    assert "model_trace.json" in d["sim_fails"][0], d["sim_fails"]
    assert calls == [], calls


def _assert_unreadable_model_trace_verdict(rc, d, calls):
    """Shared shape for the present-but-unreadable `model_trace.json` cases.

    Every one of these is a SIMULATOR-level failure, never a comparison
    result: the model side of the comparison never parsed, so there is nothing
    to compare against and the simulator must not be invoked at all.
    """
    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "NOT_RUN", json.dumps(d, indent=1)
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "model_trace.json" in d["sim_fails"][0], d["sim_fails"]
    assert d["checked"]["fields"] == 0, d["checked"]
    assert calls == [], calls


def test_malformed_model_trace_is_named_without_raising(tmp_path, monkeypatch):
    """PRESENT but not valid JSON is a named failure, not a traceback (#197).

    `missing_inputs()` asserts existence only, so a `model_trace.json` that
    exists and is unparseable reached an unguarded `json.load` in `main()`:
    `json.JSONDecodeError` propagated out, the process exited by traceback,
    and no verdict JSON was written at all -- the same lost-reason failure
    #182/#188 fixed for the simulator-level paths.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        f.write("not json")
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    _assert_unreadable_model_trace_verdict(rc, d, calls)
    assert "JSONDecodeError" in d["sim_fails"][0], d["sim_fails"]


def test_unopenable_model_trace_is_named_without_raising(tmp_path, monkeypatch):
    """PRESENT but unopenable (mode 000) takes the same path (#197).

    Distinct from the malformed case: the exception is raised by `open()`
    (`PermissionError`, an `OSError`) before the JSON parser is reached, so a
    guard that caught only `json.JSONDecodeError` would still exit by
    traceback with no verdict JSON here.
    """
    if os.geteuid() == 0:
        # root bypasses the mode bits, so the control cannot demonstrate the
        # failure it targets -- report that rather than passing vacuously.
        pytest.skip("mode 000 is not enforced for root")

    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    trace_path = os.path.join(run_dir, "model_trace.json")
    os.chmod(trace_path, 0o000)
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)
    try:
        rc, d = _run_harness(mod, monkeypatch, run_dir)
    finally:
        os.chmod(trace_path, 0o644)

    _assert_unreadable_model_trace_verdict(rc, d, calls)
    assert "PermissionError" in d["sim_fails"][0], d["sim_fails"]


def test_undecodable_model_trace_is_named_without_raising(tmp_path,
                                                         monkeypatch):
    """PRESENT but not UTF-8 text takes the same path (#197).

    Third distinct exception on the same read: a truncated/binary trace raises
    `UnicodeDecodeError` from the decode, which is a sibling `ValueError`
    subclass rather than a `json.JSONDecodeError` -- so this pins the guard's
    `ValueError` arm as load-bearing.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "wb") as f:
        f.write(b"\xff\xfe\x00{")
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    _assert_unreadable_model_trace_verdict(rc, d, calls)
    assert "UnicodeDecodeError" in d["sim_fails"][0], d["sim_fails"]


def test_a_readable_model_trace_still_reaches_the_simulator(tmp_path,
                                                           monkeypatch):
    """FALSE-POSITIVE control for the #197 guard.

    The guard must not swallow a healthy run: a well-formed `model_trace.json`
    must still parse, still invoke the simulator, and still verdict PASS. A
    guard that reported every trace as unreadable would satisfy the three
    controls above and be useless.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", json.dumps(d, indent=1)
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert calls == ["iverilog", "vvp"], calls
    assert d["checked"]["fields"] > 0
