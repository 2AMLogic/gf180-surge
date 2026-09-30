#!/usr/bin/env python3
"""SXT-026 RTL-vs-model harness reporting controls (#182 #188 #194 #197 #205
#218).

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
  * a stimulus file that opens but is TRUNCATED -- fewer words than the model
    declared in `rtl/stimulus_index.json`                               (#194)

and, on the reporting path AFTER the comparison has already been computed, the
two optional TRAFFIC inputs -- `tb_traffic.txt` and `traffic.json` -- which are
existence-gated but were not parse-guarded: a truncated dump, a
stray-whitespace line, a non-integer count, a non-UTF-8 file, a declaration
missing `totals` / `totals.ext_read_words` raised out of `main()` and discarded
the otherwise-complete RTL-vs-model result together with the verdict JSON.
They are recorded in `traffic_fails` (never `sim_fails`: the simulator DID run
and the comparison DID happen, so `comparison` must not read NOT_RUN)  (#205)

and, on the same reporting path, the agreement between the recorded verdict and
the PROCESS EXIT STATUS: `verdict` was computed from `fails or traffic_fails`
but the return from `fails` alone, so a run whose only failures were traffic
ones wrote `"verdict": "FAIL"` and exited 0 -- reading as success to any caller
that tests `$?`. The ordinary return is now derived from `verdict` itself; the
two `--mutant*` returns stay comparison-only (exit 0 == the mutant was caught),
so a mutant run failing only on traffic is still refused          (#218)

plus the false-positive controls that matter more than any of them: a healthy
run whose stdout carries the testbench's own benign diagnostics (including the
five `$readmemh(...): Not enough words` WARNINGs a PASSING pinned-tree run
really does emit, transcribed from the measurement in
`reports/tooling-wt-harness-stimulus-load/artifacts/` ->
`healthy-run-warning-baseline.txt`) must still verdict PASS; a complete run
dir must still verdict PASS with
`sim_fails == []`; and a genuine comparison disagreement must still be
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

# MEASURED (#194 checkbox 1): the `$readmemh(...): Not enough words` WARNINGs
# a GENUINELY PASSING pinned-tree exactness run emits, one per $readmemh call
# site, transcribed verbatim from the artifact
# `healthy-run-warning-baseline.txt` under
# `reports/tooling-wt-harness-stimulus-load/artifacts/`
# (Icarus 13.0, kick-wtfix-kt / seq-wt-pitch-extremes-hi-v1, 4125 blocks,
# verdict PASS). ALL FIVE memories warn on a healthy run, because the
# testbench declares them far larger than any real stimulus. That measurement
# is why truncation is detected by a CONTENT check and not by a matcher on
# this text: there is no subset of these lines a healthy run does not emit.
NOT_ENOUGH_WORDS = tuple(
    "WARNING: %s/rtl/oscillators/wavetable/tb_wavetable.sv:%d: "
    "$readmemh(%s): Not enough words in the file for the requested "
    "range [0:%d].\n" % (REPO, line, path, top)
    for line, path, top in ((277, "rtl/init.hex", 63),
                            (279, "rtl/ctrl.hex", 262143),
                            (280, "rtl/wt_table.hex", 131071),
                            (281, "rtl/sinc_main.hex", 6143),
                            (288, "rtl/sinc_deriv.hex", 6143)))

# What a run whose stimulus DID load prints on stdout: those five WARNINGs
# plus the testbench's own diagnostics (DBG / WARNING / "TB done" / $finish).
# The WARNINGs are included deliberately, because they contain the `$readmemh`
# token and so pin the matcher's conjunction (`$readmem` AND `Unable to open`)
# as load-bearing. They are WARNINGs about file *length*, not open failures,
# and matching them would flip a genuinely passing exactness run to FAIL --
# the one outcome worse than the lost reason #188 exists to fix.
HEALTHY_STDOUT = (
    "".join(NOT_ENOUGH_WORDS)
    + "DBG SEL a=4250132 mip=0\n"
    "WARNING: ctrl block index 0 != 1\n"
    "DBG block 0 done @2000\n"
    "TB done: blocks 1 ext_reads 2 fill_words 0 bursts 1 stall 0 reverb 0\n"
    "%s/rtl/oscillators/wavetable/tb_wavetable.sv:424: $finish called at "
    "73500 (1ps)\n" % REPO)

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

# Word counts the fixture writes per stimulus file. Small and distinct, so a
# truncation control can shorten exactly one file and the message must name
# that file rather than "a stimulus file".
FIXTURE_WORDS = dict(zip(STIMULUS_RELPATHS, (4, 3, 8, 6, 6)))


def _write_hex(path, n_words):
    """n_words of 32-bit hex, one per line -- run_model.write_hex's format."""
    with open(path, "w") as f:
        for w in range(n_words):
            f.write("%08x\n" % w)


def _write_run_dir(tmp_path, stimulus_index=True, words=None):
    """A complete run dir: model trace, five hex files, the stimulus index.

    The stimulus files carry real (if short) content, and
    `rtl/stimulus_index.json` declares each file's length exactly the way
    `run_model.py --rtl` does -- that declaration is what makes a TRUNCATED
    file detectable (#194). `stimulus_index=False` reproduces a run dir from
    tooling older than #194, for which the length check must report NOT_RUN
    instead of failing closed.
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
    words = dict(FIXTURE_WORDS if words is None else words)
    for rel in STIMULUS_RELPATHS:
        _write_hex(os.path.join(run_dir, rel), words[rel])
    if stimulus_index:
        with open(os.path.join(run_dir, "rtl/stimulus_index.json"), "w") as f:
            json.dump({"format": "sxt026-wt-stimulus-index/1",
                       "files": dict(FIXTURE_WORDS)}, f)
    return run_dir


# A well-formed traffic pair, the two OPTIONAL inputs the harness reads after
# the comparison has already been computed (#205). The dump is the testbench's
# own `$fdisplay(fd_traffic, "<name> %0d", ...)` shape (two whitespace-
# separated tokens per line), transcribed from `tb_wavetable.sv`'s final block;
# the declaration is `run_model.py`'s `traffic.json`. The numbers are chosen so
# the reconciliation RECONCILES: core_reads_words + core_fill_words ==
# totals.ext_read_words.
GOOD_TB_TRAFFIC = ("core_reads_words 2\n"
                   "core_fill_words 0\n"
                   "core_bursts 1\n"
                   "core_stall_cycles 0\n"
                   "reverb_words 0\n"
                   "underrun_blocks 0\n"
                   "max_frame_bus_cost 34\n"
                   "budget_cycles_per_frame 32000\n")
GOOD_MODEL_TRAFFIC = {"format": "sxt-026-wavetable-traffic/1",
                      "totals": {"impulses": 1, "ext_read_words": 2,
                                 "frame_fills_words": 0}}

# The same dump, WELL FORMED but failing one or both of the two reconciliation
# checks against GOOD_MODEL_TRAFFIC (which declares `ext_read_words: 2`). Each
# shape isolates one reason so no single path can be the one left unguarded:
# the reconciliation mismatch alone reconciles nothing but underruns cleanly,
# and the no-underrun gate alone reconciles exactly while reporting a starved
# block. Nothing else about the run fails -- the trace still AGREES -- so these
# are the "traffic-only FAIL" runs (#218).
TRAFFIC_FAIL_TB = {
    "reconciliation mismatch alone":
        "core_reads_words 3\ncore_fill_words 0\nunderrun_blocks 0\n",
    "no-underrun gate alone":
        "core_reads_words 2\ncore_fill_words 0\nunderrun_blocks 1\n",
    "both reasons":
        "core_reads_words 3\ncore_fill_words 0\nunderrun_blocks 1\n",
}


def _write_traffic(run_dir, tb=GOOD_TB_TRAFFIC, model=GOOD_MODEL_TRAFFIC):
    """Write the two optional traffic inputs into a run dir.

    `tb` is written verbatim so a control can install a malformed dump;
    `model` is written verbatim when it is a `str`/`bytes` and as JSON
    otherwise. `None` omits that file entirely (which is what
    `_write_run_dir` leaves behind, and is NOT a failure: the reconciliation
    simply makes no claim).
    """
    if tb is not None:
        with open(os.path.join(run_dir, "tb_traffic.txt"), "w") as f:
            f.write(tb)
    if model is not None:
        path = os.path.join(run_dir, "traffic.json")
        if isinstance(model, bytes):
            with open(path, "wb") as f:
                f.write(model)
        elif isinstance(model, str):
            with open(path, "w") as f:
                f.write(model)
        else:
            with open(path, "w") as f:
                json.dump(model, f)


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
    """FALSE-POSITIVE control (the one that matters most, issues #188/#194).

    A healthy run's stdout carries the testbench's own DBG / WARNING /
    "TB done" diagnostics AND -- measured, #194 -- one Icarus
    `$readmemh(...): Not enough words` WARNING per memory. Neither may be read
    as a stimulus-load failure: reporting a run that did not fail as failed is
    worse than the lost reason this change exists to recover.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    # The stdout fed in really does carry all five measured WARNINGs.
    for warn in NOT_ENOUGH_WORDS:
        assert warn in HEALTHY_STDOUT
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


# --------------------------------------------------------------------------
# issue #194 controls: a stimulus file that OPENS but is TRUNCATED, and the
# known-good control that makes the first one trustworthy.
# --------------------------------------------------------------------------


def test_truncated_stimulus_file_is_named_and_not_a_model_disagreement(
        tmp_path, monkeypatch):
    """POSITIVE control (#194 failure control): drop half of wt_table.hex.

    Pre-fix, this run dir reached the simulator, produced whatever a
    half-loaded wavetable produces, and was reported as a MODEL
    DISAGREEMENT -- the file's name appearing nowhere in the summary. The
    stubbed simulator here still writes a *matching* trace, so only a harness
    that detects the truncation before the run can reach a FAIL at all.
    """
    mod = _load_harness()
    short = dict(FIXTURE_WORDS)
    short["rtl/wt_table.hex"] //= 2          # 8 words declared, 4 written
    run_dir = _write_run_dir(tmp_path, words=short)
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "NOT_RUN", json.dumps(d, indent=1)
    # The verdict names THAT file, and only that file.
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    msg = d["sim_fails"][0]
    assert "rtl/wt_table.hex" in msg, msg
    assert "TRUNCATED" in msg, msg
    assert "4 hex words" in msg and "declared 8" in msg, msg
    for rel in STIMULUS_RELPATHS:
        if rel != "rtl/wt_table.hex":
            assert rel not in msg, (rel, msg)
    # ... and it is NOT reported as a model/RTL disagreement.
    assert d["mismatches"] == 1, json.dumps(d, indent=1)
    assert d["checked"]["fields"] == 0, d["checked"]
    assert "model=" not in "\n".join(d["first_failures"])
    # The simulator is never invoked on stimulus known to be incomplete.
    assert calls == [], calls
    # The length report states the disagreement per file, with both counts.
    sl = d["stimulus_lengths"]
    assert sl["status"] == "FAIL", sl
    assert sl["words"]["rtl/wt_table.hex"] == {"declared": 8, "actual": 4}, sl
    assert sl["words"]["rtl/ctrl.hex"] == {"declared": 3, "actual": 3}, sl


def test_complete_stimulus_still_passes_with_no_sim_fails(tmp_path,
                                                          monkeypatch):
    """NEGATIVE (known-good) control -- the leg that makes the first one mean
    something (#194 failure control, second half).

    The SAME fixture, untouched: every stimulus file matches the length the
    model declared, so the verdict is PASS with `sim_fails == []` and the
    length check reports PASS rather than merely "nothing detected".
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT, calls=calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", json.dumps(d, indent=1)
    assert d["comparison"] == "PASS", json.dumps(d, indent=1)
    assert d["sim_fails"] == [], d["sim_fails"]
    assert d["stimulus_lengths"]["status"] == "PASS", d["stimulus_lengths"]
    for rel in STIMULUS_RELPATHS:
        entry = d["stimulus_lengths"]["words"][rel]
        assert entry["declared"] == entry["actual"] == FIXTURE_WORDS[rel]
    # The simulator DID run, and the comparison really was performed.
    assert calls == ["iverilog", "vvp"], calls
    assert d["checked"]["fields"] > 0 and d["checked"]["oscout"] > 0


def test_every_stimulus_file_is_named_when_it_is_the_truncated_one(
        tmp_path, monkeypatch):
    """The failure names whichever file is short -- not a generic message.

    A message that named a fixed file (or none) would pass the wt_table leg
    above by accident; this walks all five call sites.
    """
    mod = _load_harness()
    for target in STIMULUS_RELPATHS:
        short = dict(FIXTURE_WORDS)
        short[target] -= 1
        sub = tmp_path / target.replace("/", "_")
        sub.mkdir()
        run_dir = _write_run_dir(sub, words=short)
        _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)

        rc, d = _run_harness(mod, monkeypatch, run_dir)

        assert rc != 0, target
        assert d["verdict"] == "FAIL", (target, json.dumps(d, indent=1))
        assert len(d["sim_fails"]) == 1, (target, d["sim_fails"])
        assert target in d["sim_fails"][0], (target, d["sim_fails"])


def test_run_dir_without_a_stimulus_index_reports_not_run_not_failure(
        tmp_path, monkeypatch):
    """A run dir from tooling older than #194 must not be flipped to FAIL.

    No `rtl/stimulus_index.json` means the model declared no lengths, so no
    truncation claim can be made. That is reported as NOT_RUN in the summary
    -- visible, and never as a pass -- while the verdict itself is unchanged.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path, stimulus_index=False)
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", json.dumps(d, indent=1)
    assert d["sim_fails"] == []
    sl = d["stimulus_lengths"]
    assert sl["status"] == "NOT_RUN", sl
    assert "stimulus_index.json" in sl["reason"], sl
    assert "NOT a pass" in sl["reason"], sl
    # Coverage is still reported per file: measured, declared nothing.
    for rel in STIMULUS_RELPATHS:
        assert sl["words"][rel]["declared"] is None, sl
        assert sl["words"][rel]["actual"] == FIXTURE_WORDS[rel], sl


def test_length_check_is_content_based_not_layout_based(tmp_path):
    """Unit control on the counter and the check itself.

    The count follows `$readmemh` semantics (whitespace-separated words,
    `//` comments and `@address` directives excluded), not line count, so a
    file that is complete but formatted differently is not a false positive
    -- and a partial index reports NOT_RUN for exactly the files it omits.
    """
    mod = _load_harness()
    run_dir = str(tmp_path)
    os.makedirs(os.path.join(run_dir, "rtl"))
    path = os.path.join(run_dir, "rtl/init.hex")
    with open(path, "w") as f:
        f.write("// generated\n@0000\n0000000a 0000000b\n\n0000000c\n")
    assert mod.count_hex_words(path) == 3

    for rel in STIMULUS_RELPATHS[1:]:
        _write_hex(os.path.join(run_dir, rel), FIXTURE_WORDS[rel])

    # Complete, with an index declaring init.hex's 3 content words: PASS.
    declared = dict(FIXTURE_WORDS, **{"rtl/init.hex": 3})
    with open(os.path.join(run_dir, "rtl/stimulus_index.json"), "w") as f:
        json.dump({"files": declared}, f)
    report, fails = mod.check_stimulus_lengths(run_dir)
    assert fails == [], fails
    assert report["status"] == "PASS", report

    # An index that declares only some files: NOT_RUN, naming the gap.
    with open(os.path.join(run_dir, "rtl/stimulus_index.json"), "w") as f:
        json.dump({"files": {"rtl/init.hex": 3}}, f)
    report, fails = mod.check_stimulus_lengths(run_dir)
    assert fails == [], fails
    assert report["status"] == "NOT_RUN", report
    assert "rtl/ctrl.hex" in report["reason"], report

    # A file LONGER than declared is a mismatch too (a stale file mixed into
    # the run dir), reported as such rather than as truncation.
    with open(os.path.join(run_dir, "rtl/stimulus_index.json"), "w") as f:
        json.dump({"files": dict(declared, **{"rtl/ctrl.hex": 2})}, f)
    report, fails = mod.check_stimulus_lengths(run_dir)
    assert report["status"] == "FAIL", report
    assert len(fails) == 1, fails
    assert "LONGER THAN DECLARED" in fails[0], fails
    assert "rtl/ctrl.hex" in fails[0], fails

    # An unreadable index is NOT_RUN, not a failure.
    with open(os.path.join(run_dir, "rtl/stimulus_index.json"), "w") as f:
        f.write("{not json")
    report, fails = mod.check_stimulus_lengths(run_dir)
    assert fails == [], fails
    assert report["status"] == "NOT_RUN", report
    assert "NOT a pass" in report["reason"], report


# --------------------------------------------------------------------------
# issue #205 controls: the two TRAFFIC inputs are existence-gated but were not
# parse-guarded, and they are read AFTER the comparison has been computed -- so
# a truncated `tb_traffic.txt` or a malformed `traffic.json` raised out of
# main() and discarded an otherwise-complete RTL-vs-model result along with the
# verdict JSON. Each must instead become a named `traffic_fails` entry.
#
# `traffic_fails` (not `sim_fails`) is the correct list: the simulator DID run
# here and the comparison DID happen, so `comparison` must not be NOT_RUN.
# --------------------------------------------------------------------------


def _assert_traffic_read_failure(d, filename):
    """Shared shape for a present-but-unparseable traffic input (#205).

    The three things that were lost to the traceback are all asserted: a
    verdict JSON exists at all (the caller only gets here by reading it), the
    offending file is named, and the comparison result computed BEFORE this
    read survived into the summary.

    Deliberately NOT asserted here: the process exit status. These controls are
    about the verdict JSON getting written at all, and a control that only
    observed a non-zero exit would not discriminate -- the pre-#205 traceback
    exited non-zero too, with nothing written. The separate requirement that the
    exit status AGREE with `verdict` for a traffic-only FAIL (#218, which was
    open when #205 landed and is why this paragraph once recorded exit 0 as the
    expected value) is asserted by the `#218` controls at the end of this file,
    across all three traffic-fail shapes including this parse-failure one.
    """
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    # The simulator ran and the comparison ran: this is NOT a NOT_RUN.
    assert d["sim_fails"] == [], d["sim_fails"]
    assert d["comparison"] == "FAIL", json.dumps(d, indent=1)
    # The already-computed comparison result is still reported, and it agreed.
    assert d["checked"]["fields"] > 0 and d["checked"]["oscout"] > 0, d
    assert d["mismatches"] == 0, json.dumps(d, indent=1)
    assert d["first_failures"] == [], d["first_failures"]
    # Exactly one named reason, and it is the read -- not a derived traffic
    # mismatch computed from counts that never parsed.
    assert len(d["traffic_fails"]) == 1, d["traffic_fails"]
    msg = d["traffic_fails"][0]
    assert filename in msg, msg
    assert "ext words" not in msg, msg
    assert "underrun" not in msg, msg
    return msg


MALFORMED_TB_TRAFFIC = {
    "missing token": "core_reads_words 2\ncore_fill_words\n",
    "extra token": "core_reads_words 2 3\n",
    "non-integer count": "core_reads_words 2\nunderrun_blocks none\n",
    "whitespace-only line": "core_reads_words 2\n   \nunderrun_blocks 0\n",
    "truncated last line": "core_reads_words 2\ncore_fi",
}


@pytest.mark.parametrize("shape", sorted(MALFORMED_TB_TRAFFIC))
def test_malformed_tb_traffic_is_named_without_raising(shape, tmp_path,
                                                      monkeypatch):
    """POSITIVE control 1 (#205): a present but unparseable `tb_traffic.txt`.

    Pre-fix, the `k, v = line.split()` / `int(v)` pair raised `ValueError`
    straight out of `main()` -- after the comparison had already been computed
    and agreed. No verdict JSON was written, the offending file was named
    nowhere, and the RTL-vs-model outcome for the run was lost. A control that
    only observed a non-zero exit would not discriminate: the pre-fix code
    already exited non-zero, by traceback.

    All five shapes are walked because the guard must be about the dump's
    parse, not about one token layout.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir, tb=MALFORMED_TB_TRAFFIC[shape])
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    _, d = _run_harness(mod, monkeypatch, run_dir)

    msg = _assert_traffic_read_failure(d, "tb_traffic.txt")
    assert "traffic.json" not in msg, msg
    # The simulator really was reached, so this cannot be mistaken for the
    # pre-simulator #197 path.
    assert calls == ["iverilog", "vvp"], calls
    # Partial counts are not reported as if they were the run's traffic.
    assert d["traffic_tb"] == {}, d["traffic_tb"]


def test_undecodable_tb_traffic_is_named_without_raising(tmp_path,
                                                        monkeypatch):
    """Same read, a `UnicodeDecodeError` rather than a `ValueError` from split.

    A non-UTF-8 dump raises from the decode before any line is seen.
    `UnicodeDecodeError` is a sibling `ValueError` subclass, so this pins the
    guard's `ValueError` arm the same way the #197 control does for
    `model_trace.json`.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir, tb=None)
    with open(os.path.join(run_dir, "tb_traffic.txt"), "wb") as f:
        f.write(b"core_reads_words \xff\xfe 2\n")
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)

    _, d = _run_harness(mod, monkeypatch, run_dir)

    msg = _assert_traffic_read_failure(d, "tb_traffic.txt")
    assert "UnicodeDecodeError" in msg, msg


def test_unopenable_tb_traffic_is_named_without_raising(tmp_path, monkeypatch):
    """PRESENT but unopenable (mode 000) takes the same path.

    Distinct from the malformed cases: the exception comes from `open()`
    (`PermissionError`, an `OSError`), which a guard catching only
    `ValueError` would still let escape.
    """
    if os.geteuid() == 0:
        pytest.skip("mode 000 is not enforced for root")

    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir)
    tb_path = os.path.join(run_dir, "tb_traffic.txt")
    os.chmod(tb_path, 0o000)
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)
    try:
        _, d = _run_harness(mod, monkeypatch, run_dir)
    finally:
        os.chmod(tb_path, 0o644)

    msg = _assert_traffic_read_failure(d, "tb_traffic.txt")
    assert "PermissionError" in msg, msg


MALFORMED_MODEL_TRAFFIC = {
    "not json": ("not json", "JSONDecodeError"),
    "truncated json": ('{"totals": {"ext_read_words": 2', "JSONDecodeError"),
    "not utf-8": (b"\xff\xfe\x00{", "UnicodeDecodeError"),
    "no totals key": ({"format": "sxt-026-wavetable-traffic/1"}, "KeyError"),
    "totals not an object": ({"totals": 2}, "TypeError"),
    "no ext_read_words": ({"totals": {"impulses": 1}}, "KeyError"),
    "ext_read_words not an int": ({"totals": {"ext_read_words": "2"}},
                                  "ValueError"),
}


@pytest.mark.parametrize("shape", sorted(MALFORMED_MODEL_TRAFFIC))
def test_malformed_traffic_json_is_named_without_raising(shape, tmp_path,
                                                        monkeypatch):
    """POSITIVE control 2 (#205): a present but unusable `traffic.json`.

    Pre-fix, `json.load(f)["totals"]` raised `JSONDecodeError`/`KeyError` out
    of `main()` at the same point, with the same loss. The
    `ext_read_words`-shaped cases are part of the SAME read: guarding only
    `["totals"]` would move the traceback six lines down into
    `model_traffic["ext_read_words"]` and lose the verdict just as completely,
    so both are guarded at the read and both are controlled here.
    """
    mod = _load_harness()
    doc, exc_name = MALFORMED_MODEL_TRAFFIC[shape]
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir, model=doc)
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    _, d = _run_harness(mod, monkeypatch, run_dir)

    msg = _assert_traffic_read_failure(d, "traffic.json")
    assert exc_name in msg, (shape, msg)
    assert calls == ["iverilog", "vvp"], calls
    assert d["traffic_model"] is None, d["traffic_model"]


def test_well_formed_traffic_still_reconciles_and_passes(tmp_path,
                                                        monkeypatch):
    """FALSE-POSITIVE control (#205), the leg that makes the two above mean
    something.

    A well-formed `tb_traffic.txt` + `traffic.json` pair must still parse,
    still reconcile, and still verdict PASS with `traffic_fails == []`. A guard
    that reported every traffic input as unparseable, or that skipped the
    reconciliation altogether, would satisfy both positive controls and be
    worse than the bug.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir)
    calls = []
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT, calls=calls)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", json.dumps(d, indent=1)
    assert d["comparison"] == "PASS", json.dumps(d, indent=1)
    assert d["sim_fails"] == [], d["sim_fails"]
    assert d["traffic_fails"] == [], d["traffic_fails"]
    # Both sides really were read (not silently treated as absent).
    assert d["traffic_tb"]["core_reads_words"] == 2, d["traffic_tb"]
    assert d["traffic_tb"]["underrun_blocks"] == 0, d["traffic_tb"]
    assert d["traffic_model"]["ext_read_words"] == 2, d["traffic_model"]
    assert calls == ["iverilog", "vvp"], calls
    assert d["checked"]["fields"] > 0 and d["checked"]["oscout"] > 0


def test_traffic_disagreement_is_still_reported_as_a_traffic_fail(tmp_path,
                                                                 monkeypatch):
    """Second false-positive control: the reconciliation itself still bites.

    Well-formed inputs that DISAGREE (the dump counts 3 ext words, the model
    declared 2) must still produce the `ext words:` entry, and an
    `underrun_blocks` count must still fail the no-underrun gate. This is what
    stops the #205 guard from being implemented as "skip the reconciliation".

    The exit status these two entries must now also produce is asserted by the
    `#218` controls at the end of this file; this test stays a statement about
    the reported reasons.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir, tb=TRAFFIC_FAIL_TB["both reasons"])
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)

    _, d = _run_harness(mod, monkeypatch, run_dir)

    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["comparison"] == "FAIL", json.dumps(d, indent=1)
    assert d["sim_fails"] == [], d["sim_fails"]
    joined = "\n".join(d["traffic_fails"])
    assert "ext words: rtl reads+fills 3+0 != model 2" in joined, joined
    assert "1 underrun block(s)" in joined, joined


def test_absent_traffic_inputs_are_not_a_failure(tmp_path, monkeypatch):
    """Third false-positive control: both files are OPTIONAL.

    The fixture's run dir carries neither traffic input (a run dir from
    tooling that did not dump them). The guard must not turn absence into a
    named failure -- the existence gate stays, and no traffic claim is made.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    assert not os.path.exists(os.path.join(run_dir, "tb_traffic.txt"))
    assert not os.path.exists(os.path.join(run_dir, "traffic.json"))
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", json.dumps(d, indent=1)
    assert d["traffic_fails"] == [], d["traffic_fails"]
    assert d["traffic_tb"] == {}, d["traffic_tb"]
    assert d["traffic_model"] is None, d["traffic_model"]


def test_traffic_read_helpers_report_rather_than_raise(tmp_path):
    """Unit control on the two helpers themselves.

    Both return `(value, fails)` and never raise: the malformed cases return
    an empty/None value with exactly one named reason, and the well-formed
    cases return the parsed value with no reason at all.
    """
    mod = _load_harness()
    tb_path = os.path.join(str(tmp_path), "tb_traffic.txt")
    model_path = os.path.join(str(tmp_path), "traffic.json")

    with open(tb_path, "w") as f:
        f.write(GOOD_TB_TRAFFIC)
    counts, fails = mod.read_tb_traffic(tb_path)
    assert fails == [], fails
    assert counts["core_reads_words"] == 2 and counts["underrun_blocks"] == 0

    with open(tb_path, "w") as f:
        f.write("core_reads_words 2\nunderrun_blocks\n")
    counts, fails = mod.read_tb_traffic(tb_path)
    assert counts == {}, counts
    assert len(fails) == 1 and "tb_traffic.txt" in fails[0], fails
    assert "line 2" in fails[0], fails

    # A file that does not exist at all still reports rather than raising,
    # even though main() reaches the helper only behind an existence gate.
    counts, fails = mod.read_tb_traffic(
        os.path.join(str(tmp_path), "nope.txt"))
    assert counts == {} and len(fails) == 1, fails

    with open(model_path, "w") as f:
        json.dump(GOOD_MODEL_TRAFFIC, f)
    totals, fails = mod.read_model_traffic(model_path)
    assert fails == [], fails
    assert totals["ext_read_words"] == 2, totals

    with open(model_path, "w") as f:
        json.dump({"totals": {"ext_read_words": True}}, f)
    totals, fails = mod.read_model_traffic(model_path)
    # A bool is not an acceptable word count even though bool is an int
    # subclass: accepting it would let `true` reconcile against 1 word.
    assert totals is None, totals
    assert len(fails) == 1 and "traffic.json" in fails[0], fails


# --------------------------------------------------------------------------
# issue #218 controls: the PROCESS EXIT STATUS must agree with the `verdict`
# field for every summary the harness writes. `main()` computed the verdict from
# `fails or traffic_fails` but the return from `fails` alone, and `traffic_fails`
# never feeds `fails` -- so a run whose only failures were traffic ones wrote
# `"verdict": "FAIL"` and exited 0. That is the mirror image of #182/#188/#197/
# #205: there the reason was lost while the exit status was honest; here the
# reason is recorded and the exit status lies, which is worse for any caller
# following the ordinary convention that exit 0 means the check passed.
#
# The `--mutant*` returns are deliberately NOT verdict-derived and are left
# alone: exit 0 there means "the mutant was caught", a statement about the
# COMPARISON. A mutant run failing only on traffic has demonstrated nothing
# about the mutant, so it must still exit non-zero.
# --------------------------------------------------------------------------


# Every well-formed-but-failing shape above, plus the present-but-unparseable
# shape from the #205 controls: all three reasons land in `traffic_fails` and
# all three used to exit 0. Parametrizing over them is what stops the fix from
# being "make the reconciliation mismatch exit non-zero" and leaving one of the
# other two paths unguarded.
TRAFFIC_ONLY_FAIL_TB = dict(
    TRAFFIC_FAIL_TB,
    **{"unparseable dump": MALFORMED_TB_TRAFFIC["missing token"]})


@pytest.mark.parametrize("shape", sorted(TRAFFIC_ONLY_FAIL_TB))
def test_traffic_only_fail_exits_non_zero(shape, tmp_path, monkeypatch):
    """FAILURE CONTROL (#218): comparison AGREES, only traffic fails => rc!=0.

    The stubbed simulator exits 0 and writes a MATCHING trace, so `sim_fails`
    and `cmp_fails` are both empty and `traffic_fails` is the run's only reason
    to fail -- exactly the summary the pre-fix code wrote as
    `"verdict": "FAIL"` while returning 0.

    The named reason must survive alongside the corrected status: a "fix" that
    merged `traffic_fails` into `fails` and so inflated `mismatches` /
    `first_failures` (turning a traffic failure into a reported RTL-vs-model
    disagreement) would be the #188 misreport again, so `mismatches == 0` and
    `first_failures == []` are asserted too.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir, tb=TRAFFIC_ONLY_FAIL_TB[shape])
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert rc != 0, (shape, rc, json.dumps(d, indent=1))
    # ... and the reason is still recorded, as a TRAFFIC failure specifically.
    assert d["traffic_fails"], json.dumps(d, indent=1)
    assert d["sim_fails"] == [], d["sim_fails"]
    assert d["comparison"] == "FAIL", json.dumps(d, indent=1)
    # The comparison itself agreed, and is not restated as a disagreement.
    assert d["mismatches"] == 0, json.dumps(d, indent=1)
    assert d["first_failures"] == [], d["first_failures"]
    assert d["checked"]["fields"] > 0 and d["checked"]["oscout"] > 0, d


def test_traffic_only_fail_names_the_reason_it_exits_non_zero_for(tmp_path,
                                                                 monkeypatch):
    """Each reconciliation reason, alone, is the one that carries the status.

    Runs the two well-formed shapes individually and asserts the exact message
    each produces, so the parametrized control above cannot be satisfied by a
    harness that reports some other traffic reason than the one installed.
    """
    mod = _load_harness()
    expected = {
        "reconciliation mismatch alone":
            ("ext words: rtl reads+fills 3+0 != model 2", "underrun"),
        "no-underrun gate alone": ("1 underrun block(s)", "ext words"),
    }
    for shape, (must, must_not) in sorted(expected.items()):
        sub = tmp_path / shape.replace(" ", "-")
        sub.mkdir()
        run_dir = _write_run_dir(sub)
        _write_traffic(run_dir, tb=TRAFFIC_FAIL_TB[shape])
        _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)

        rc, d = _run_harness(mod, monkeypatch, run_dir)

        assert rc != 0, (shape, rc)
        assert d["verdict"] == "FAIL", (shape, json.dumps(d, indent=1))
        joined = "\n".join(d["traffic_fails"])
        assert must in joined, (shape, joined)
        assert must_not not in joined, (shape, joined)


def test_clean_run_still_exits_zero_with_a_pass_verdict(tmp_path, monkeypatch):
    """FALSE-POSITIVE control (#218): a healthy run must not start failing.

    A complete run dir, an agreeing trace, and a well-formed reconciling
    traffic pair: `verdict` PASS, `traffic_fails` empty, rc 0. Deriving the
    status from `verdict` must not turn any PASS into a non-zero exit -- that
    would break step 6/7 of `tools/run_sxt026_checks.py`, both of which assert
    `returncode == 0` on a run they also assert verdicts PASS.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir)
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(mod, monkeypatch, run_dir)

    assert d["verdict"] == "PASS", json.dumps(d, indent=1)
    assert rc == 0, (rc, json.dumps(d, indent=1))
    assert d["traffic_fails"] == [], d["traffic_fails"]


def test_verdict_and_exit_status_agree_across_every_shape(tmp_path,
                                                          monkeypatch):
    """The general statement the parametrized controls are instances of.

    For an ORDINARY (non-mutant) run, `rc == 0` iff `verdict == "PASS"`, over
    one case per failure family the harness recognizes: clean, a simulator-level
    failure, a comparison disagreement, and a traffic-only failure. Asserting
    the biconditional rather than each status separately is what catches a
    future fail list that is added to `verdict` and forgotten in the return.
    """
    mod = _load_harness()
    cases = {
        # (sim_rc, trace, tb dump)  ->  expected verdict
        "clean": ((0, MATCHING_TRACE, GOOD_TB_TRAFFIC), "PASS"),
        "no traffic inputs": ((0, MATCHING_TRACE, None), "PASS"),
        "simulator failure": ((4, MATCHING_TRACE, GOOD_TB_TRAFFIC), "FAIL"),
        "comparison disagreement":
            ((0, MISMATCHING_TRACE, GOOD_TB_TRAFFIC), "FAIL"),
        "traffic only": ((0, MATCHING_TRACE, TRAFFIC_FAIL_TB["both reasons"]),
                         "FAIL"),
    }
    for name, ((sim_rc, trace, tb), want) in sorted(cases.items()):
        sub = tmp_path / name.replace(" ", "-")
        sub.mkdir()
        run_dir = _write_run_dir(sub)
        if tb is not None:
            _write_traffic(run_dir, tb=tb)
        _stub_simulator(mod, monkeypatch, run_dir, sim_rc, trace)

        rc, d = _run_harness(mod, monkeypatch, run_dir)

        assert d["verdict"] == want, (name, json.dumps(d, indent=1))
        assert (rc == 0) == (d["verdict"] == "PASS"), \
            (name, rc, json.dumps(d, indent=1))


def test_mutant_traffic_only_failure_is_not_a_caught_mutant(tmp_path,
                                                            monkeypatch):
    """FALSE-POSITIVE control (#218): the mutant return stays comparison-only.

    A `--mutant` run whose comparison AGREES and whose only failure is traffic
    must exit non-zero: the mutant was NOT demonstrated to be caught. Making
    the ordinary return verdict-derived must not leak into this path, where a
    traffic failure would otherwise be able to satisfy the negative control and
    credit an undetected mutant. This already held pre-fix and must keep
    holding: it is the leg the fix could most easily have broken.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir, tb=TRAFFIC_FAIL_TB["both reasons"])
    _stub_simulator(mod, monkeypatch, run_dir, 0, MATCHING_TRACE)

    rc, d = _run_harness(mod, monkeypatch, run_dir, extra=("--mutant",))

    assert rc != 0, (rc, json.dumps(d, indent=1))
    assert d["mutant"] is True, json.dumps(d, indent=1)
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    # The FAIL is a traffic one, NOT the comparison disagreement the mutant
    # control requires -- which is precisely why it may not be credited.
    assert d["traffic_fails"], d["traffic_fails"]
    assert d["sim_fails"] == [], d["sim_fails"]
    assert d["mismatches"] == 0, json.dumps(d, indent=1)


def test_mutant_caught_by_the_comparison_still_exits_zero(tmp_path,
                                                          monkeypatch):
    """The positive leg that gives the control above its meaning.

    A `--mutant` run with a genuine comparison disagreement still exits 0 --
    the mutant was caught -- even though its `verdict` reads FAIL. This
    deliberate inversion is why the fix derives only the ORDINARY return from
    `verdict`; a blanket `0 if verdict == "PASS"` would break the negative
    control that step 6 of `tools/run_sxt026_checks.py` asserts `returncode
    == 0` on.
    """
    mod = _load_harness()
    run_dir = _write_run_dir(tmp_path)
    _write_traffic(run_dir)
    _stub_simulator(mod, monkeypatch, run_dir, 0, MISMATCHING_TRACE)

    rc, d = _run_harness(mod, monkeypatch, run_dir, extra=("--mutant",))

    assert rc == 0, (rc, json.dumps(d, indent=1))
    assert d["verdict"] == "FAIL", json.dumps(d, indent=1)
    assert d["mismatches"] > 0, json.dumps(d, indent=1)
    assert d["traffic_fails"] == [], d["traffic_fails"]
