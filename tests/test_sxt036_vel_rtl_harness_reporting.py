"""SXT-036 `tools/compare_vel_rtl_model.py` harness reporting controls
(#188, #193, #360, #361, #631).

Issue #303 extracted the report-assembly skeleton five RTL-vs-frozen-model
leaves had copied verbatim, but left the velocity leaf on its own private
`build_and_run()` + `main()` because it "does not import
`_rtl_compile_common` at all" -- deferred for lack of analysis, not ruled to
stay separate.  Issue #631 supplied that analysis and moved it across; this
file is the reporting coverage the leaf never had.

What is pinned here is the REPORTING BOUNDARY only: that a simulator-level
failure is published as `comparison: NOT_RUN` with a named reason, never as
an RTL-vs-model disagreement, and never as a surviving stale verdict.  The
simulator is STUBBED (no iverilog, no vvp) -- nothing here is evidence about
the RTL, the frozen model, or their agreement, and
`tests/test_rtl_leaf_comparison.py` owns the shared skeleton's own contract.

Why it matters for this leaf specifically: `tools/vel_negative_controls.py`,
`tools/vel_declared_coverage.py` and `tools/vel_param_corners.py` all shell
out to this harness and read `verdict` / `mismatches` / `checked` /
`first_failures`, treating "FAIL with mismatches > 0" as a mutant firing.
Before #631 a simulator-level failure was indistinguishable from a real RTL
disagreement to those callers except through #400's ad hoc "unparseable JSON
-> ERROR" guard.

REAL-TOOLCHAIN MEASUREMENTS behind the stubs below, taken on Icarus Verilog
13.0 against a run dir built by `model/voice/run_vel_model.py --sequence
sxt036-vel-overlap-v1` (issue #631's evidence):

  * healthy run, stdout:

      WARNING: .../tb_vel.sv:108: $readmemh(rtl/vel_routes.hex): Not enough
               words in the file for the requested range [0:192].
      WARNING: .../tb_vel.sv:109: $readmemh(rtl/vel_ctrl.hex): Not enough
               words in the file for the requested range [0:2000000].
      DONE vel-qmuls=17640
      OPS passes=2940 evals=17640 mul32=17640 add64=17640 cmp64=35280 ...
      .../tb_vel.sv:121: $finish called at 0 (1ps)

    -- two size WARNINGs (this repo's hex fixtures are deliberately shorter
    than the testbench's declared ranges), never the `$readmem` + `Unable to
    open` conjunction the mechanism-2 matcher requires.  This is the
    per-harness false-positive baseline issue #193 requires before a leaf
    may rely on the stdout matcher, and `test_healthy_stdout_diagnostics_
    do_not_flip_a_pass` below is its live control.

  * `rtl/vel_ctrl.hex` removed, BEFORE #631: `subprocess.CalledProcessError`
    out of `build_and_run`, exit 1, and no verdict JSON written at all.
  * uncompilable `--tb` with `{"verdict": "PASS", "mismatches": 0}` already
    at `--out`, BEFORE #631: traceback, exit 1, stale PASS left in place.
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
import tools.compare_vel_rtl_model as mod  # noqa: E402

importlib.reload(mod)  # ensure a clean module object per test session

SIM_STDERR = "vvp: tb_vel.vvp: simulated simulator failure"

# Icarus's shape for the mechanism-2 case: the open failure is on STDOUT.
READMEMH_STDOUT = (
    "WARNING: %s/rtl/voice/tb_vel.sv:108: $readmemh(rtl/vel_routes.hex): "
    "Not enough words in the file for the requested range [0:192].\n"
    "ERROR: %s/rtl/voice/tb_vel.sv:109: $readmemh: Unable to open "
    "rtl/vel_ctrl.hex for reading.\n" % (REPO, REPO))

# Measured on real Icarus 13.0 against tb_vel.sv (see module docstring): a
# healthy run's stdout carries two size-mismatch WARNINGs, the DONE marker,
# an OPS accounting line and $finish -- never the $readmem + "Unable to
# open" conjunction.
HEALTHY_STDOUT = (
    "WARNING: %s/rtl/voice/tb_vel.sv:108: $readmemh(rtl/vel_routes.hex): "
    "Not enough words in the file for the requested range [0:192].\n"
    "WARNING: %s/rtl/voice/tb_vel.sv:109: $readmemh(rtl/vel_ctrl.hex): "
    "Not enough words in the file for the requested range [0:2000000].\n"
    "DONE vel-qmuls=17640\n"
    "OPS passes=2940 evals=17640 mul32=17640 add64=17640 cmp64=35280 "
    "add32=17640\n"
    "%s/rtl/voice/tb_vel.sv:121: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO))

MODEL_TRACE = {
    "sequence": "sxt036-vel-overlap-v1",
    "control_mode": "normal",
    "blocks": [{
        "b": 0,
        "voices": [{"slot": 0, "vel_words": [100, 200],
                    "vel_route_sums": [1, 2, 3, 4]}],
    }],
}

MATCHING_TRACE = "V 0 0 100 200\nS 0 0 1 2 3 4\n"
MISMATCHING_TRACE = "V 0 0 100 201\nS 0 0 1 2 3 4\n"


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
            with open(os.path.join(run_dir, "tb_vel_trace.txt"), "w") as f:
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


def _run_harness(monkeypatch, run_dir, out=None, extra=()):
    out = out or os.path.join(run_dir, "verdict.json")
    monkeypatch.setattr(sys, "argv",
                        ["compare_vel_rtl_model.py", "--run-dir", run_dir,
                         "--out", out] + list(extra))
    rc = mod.main()
    with open(out) as f:
        return rc, json.load(f)


# --------------------------------------------------------------------------
# The committed report shape survives the move (issue #631's first rule)
# --------------------------------------------------------------------------


def test_agreeing_trace_still_passes_with_the_committed_key_order(
        tmp_path, monkeypatch):
    """`reports/SXT-036/artifacts/exactness-vel-*.json` reports `sequence` /
    `control_mode` after `tb` and `rtl_done_line` after `first_failures`.
    The shared skeleton must not re-order or drop any of them, and the three
    keys it adds must be additive."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)
    out = os.path.join(run_dir, "verdict.json")

    rc, d = _run_harness(monkeypatch, run_dir, out=out)

    assert rc == 0
    with open(out) as f:
        order = [k for k, _ in json.loads(
            f.read(), object_pairs_hook=lambda ps: ps)]
    assert order == ["tb", "sequence", "control_mode", "verdict",
                     "comparison", "checked", "mismatches", "first_failures",
                     "rtl_done_line", "sim_fails", "sim_stdout_tail"]
    assert d["tb"] == "rtl/voice/tb_vel.sv"
    assert d["sequence"] == "sxt036-vel-overlap-v1"
    assert d["control_mode"] == "normal"
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 0
    assert d["checked"] == {"voice_block_checkpoints": 1, "source_words": 2,
                            "route_sums": 4}


def test_rtl_done_line_is_the_full_string_not_a_count(tmp_path, monkeypatch):
    """`rtl_done_line` is the whole `DONE ...` line in committed evidence.
    Routing it through `compile_and_run`'s `done_prefix` would publish
    `int(...)` instead and silently change the field's type."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    _, d = _run_harness(monkeypatch, run_dir)

    assert d["rtl_done_line"] == "DONE vel-qmuls=17640"


def test_comparison_mismatch_is_still_a_numeric_fail(tmp_path, monkeypatch):
    """The three `vel_*` callers read exactly these four keys and treat
    FAIL + mismatches > 0 as a mutant firing; that must be unchanged."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MISMATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 1
    assert "relvel_q" in d["first_failures"][0], d["first_failures"]
    assert d["checked"]["source_words"] == 2


# --------------------------------------------------------------------------
# Simulator-level failures are NOT comparison disagreements (#188/#193)
# --------------------------------------------------------------------------


def test_missing_stimulus_file_is_named_and_not_a_disagreement(
        tmp_path, monkeypatch):
    """Issue #193's mechanism-1 failure control: delete exactly one declared
    hex file.  Before #631 this raised CalledProcessError out of the private
    `build_and_run` and wrote no verdict at all."""
    run_dir = _write_run_dir(tmp_path)
    os.remove(os.path.join(run_dir, "rtl/vel_ctrl.hex"))
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/vel_ctrl.hex" in d["sim_fails"][0]
    joined = "\n".join(d["first_failures"])
    assert "missing V/S line" not in joined, joined
    assert d["checked"] == {"voice_block_checkpoints": 0, "source_words": 0,
                            "route_sums": 0}, d["checked"]
    assert calls == [], calls  # the simulator is never even invoked


def test_readmemh_open_failure_on_stdout_is_a_sim_failure(
        tmp_path, monkeypatch):
    """Mechanism 2: the file exists for the pre-flight check but Icarus still
    cannot open it, and reports that on STDOUT."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=READMEMH_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert d["sim_fails"], d["sim_fails"]
    assert "rtl/vel_ctrl.hex" in "\n".join(d["sim_fails"])
    assert "$readmemh" in d["sim_stdout_tail"]
    assert d["checked"]["route_sums"] == 0, d["checked"]


def test_healthy_stdout_diagnostics_do_not_flip_a_pass(tmp_path, monkeypatch):
    """FALSE-POSITIVE control (issue #188's guardrail), measured for THIS
    testbench's own diagnostics -- see the module docstring.  A matcher that
    turns a genuinely passing exactness run into a FAIL is worse than the
    lost reason it recovers."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE,
                    sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""


def test_nonzero_vvp_exit_is_reported_with_its_stderr(tmp_path, monkeypatch):
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 4, MATCHING_TRACE)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["comparison"] == "NOT_RUN", d
    joined = "\n".join(d["sim_fails"])
    assert "vvp exited rc=4" in joined, joined
    assert SIM_STDERR in joined, joined


def test_compile_failure_is_recorded_instead_of_raising(tmp_path, monkeypatch):
    """Before #631 an uncompilable testbench was a CalledProcessError
    traceback with the compiler's own diagnostic discarded to DEVNULL."""
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


def test_clean_run_that_wrote_no_trace_is_not_run(tmp_path, monkeypatch):
    """Issue #360 mechanism 5, now reaching this leaf: a vvp that exits 0
    without producing the declared trace must not be compared at all."""
    run_dir = _write_run_dir(tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, None, sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["comparison"] == "NOT_RUN", d
    assert "missing current-run output" in "\n".join(d["sim_fails"])


def test_a_stale_trace_is_never_read_as_this_runs_output(
        tmp_path, monkeypatch):
    """Issue #360's ownership rule: a previous invocation's trace sitting in
    a reused run dir must be invalidated before vvp launches, so it cannot
    satisfy a run that produced nothing."""
    run_dir = _write_run_dir(tmp_path)
    with open(os.path.join(run_dir, "tb_vel_trace.txt"), "w") as f:
        f.write(MATCHING_TRACE)          # a prior run's passing trace
    _stub_simulator(monkeypatch, run_dir, 0, None, sim_stdout=HEALTHY_STDOUT)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["comparison"] == "NOT_RUN", d
    assert d["verdict"] != "PASS", d


# --------------------------------------------------------------------------
# A failing invocation never leaves a prior verdict standing (#361)
# --------------------------------------------------------------------------


def test_stale_pass_at_out_is_replaced_by_a_current_not_run(
        tmp_path, monkeypatch):
    """The second row of #631's measured table.  Before the move this left
    `{"verdict": "PASS", "mismatches": 0}` in place after a traceback."""
    run_dir = _write_run_dir(tmp_path)
    out = os.path.join(run_dir, "verdict.json")
    with open(out, "w") as f:
        json.dump({"verdict": "PASS", "mismatches": 0}, f)
    os.remove(os.path.join(run_dir, "rtl/vel_init.hex"))
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE)

    rc, d = _run_harness(monkeypatch, run_dir, out=out)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert "rtl/vel_init.hex" in "\n".join(d["sim_fails"])


def test_unusable_model_trace_is_refused_before_the_simulator_runs(
        tmp_path, monkeypatch):
    """Issue #361's input-refusal boundary, now covering this leaf: a
    malformed model trace is never reported as an RTL disagreement, and the
    leaf's extra fields are not fabricated from it."""
    run_dir = _write_run_dir(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        f.write("{not json")
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert d["input_error"]["input"] == "model"
    assert d["sequence"] is None and d["rtl_done_line"] is None, d
    assert calls == [], calls
