#!/usr/bin/env python3
"""SXT-026 RTL-vs-model harness reporting controls (issue #182).

`tools/compare_wt_rtl_model.py` must report a SIMULATOR-level failure as its
own FAIL verdict, with the simulator's stderr retained in the JSON summary --
instead of raising on an unbound `fails`, and instead of discarding that
message when the comparison's own fail list is merged in.

Scope of these controls: the harness's reporting path ONLY. The simulator is
stubbed (no iverilog, no vvp, no external pinned asset tree), so nothing here
is evidence about the RTL, the frozen model, or their agreement -- the
end-to-end exactness run is step 6 of `tools/run_sxt026_checks.py`, which
needs the pinned asset tree.
"""

import importlib.util
import json
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(REPO, "tools", "compare_wt_rtl_model.py")

# Distinctive stderr text the stubbed simulator emits; the harness must carry
# it into the summary verbatim (truncated to the last 500 chars at most).
SIM_STDERR = "vvp: tb_wt.vvp: simulated simulator failure (no rtl/init.hex)"

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


def _write_run_dir(tmp_path):
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
    return run_dir


def _stub_simulator(mod, monkeypatch, run_dir, sim_rc, trace_text):
    """Replace the harness's subprocess use with a stub iverilog + vvp.

    The stub vvp writes `trace_text` (as a real vvp run would) and exits with
    `sim_rc`, emitting SIM_STDERR on stderr when that is non-zero.
    """
    def fake_run(cmd, **kwargs):
        rc, err = 0, ""
        if cmd[0] == "vvp":
            if trace_text is not None:
                with open(os.path.join(run_dir, "tb_trace.s0"), "w") as f:
                    f.write(trace_text)
            rc, err = sim_rc, (SIM_STDERR if sim_rc else "")
        return types.SimpleNamespace(returncode=rc, stdout="", stderr=err)

    monkeypatch.setattr(mod, "subprocess", types.SimpleNamespace(run=fake_run))


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
    assert d["mismatches"] == 1
    assert "field 0" in d["first_failures"][0], d["first_failures"]
