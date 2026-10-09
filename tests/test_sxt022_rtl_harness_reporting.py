"""SXT-022 `tools/compare_rtl_model.py` harness reporting controls (#193).

`compare_rtl_model.py` is one of the 10 real importers of the shared
`tools/_rtl_compile_common.compile_and_run` helper (issue #193's
re-enumeration of the #188 blind spot: a `$readmemh` target that fails to
open is reported by Icarus on the simulation's STDOUT while `vvp` still
exits 0, so `check=True` alone never sees it, and the harness's own
comparison goes on to read an empty/partial trace as though it were a
genuine RTL-vs-model disagreement).

This is the first of the 10 harnesses migrated to
`report_sim_fails=True` / `stimulus_files=...`; the remaining leaves are
tracked by a follow-up issue using this file (and
`tests/test_sxt026_wt_rtl_harness.py`, the original #188 precedent) as the
pattern to replicate.

The simulator is STUBBED here (no iverilog, no vvp, no external pinned
asset tree) -- these are reporting-path controls only, not evidence about
the RTL, the frozen model, or their agreement. The real-toolchain
measurement of tb_voice.sv's healthy stdout (the false-positive baseline
this file's controls rely on) is issue #193's own evidence, retained
alongside the PR: a healthy real run of tb_voice.sv emits ONLY Icarus's
`$readmemh(...): Not enough words...` WARNING lines, never the
`$readmem`+`Unable to open` conjunction this matcher looks for.
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
import tools.compare_rtl_model as mod  # noqa: E402

importlib.reload(mod)  # ensure a clean module object per test session

SIM_STDERR = "vvp: tb.vvp: simulated simulator failure (no rtl/sinc_deriv.hex)"

READMEMH_STDOUT = (
    "ERROR: %s/rtl/voice/tb_voice.sv:236: $readmemh: Unable to open "
    "rtl/sinc_deriv.hex for reading.\n"
    "WARNING: %s/rtl/voice/tb_voice.sv:237: $readmemh(rtl/init.hex): Not "
    "enough words in the file for the requested range [0:1152].\n"
    % (REPO, REPO))

# Measured on real Icarus 13.0 against tb_voice.sv (issue #193 evidence): a
# healthy run's stdout is two size-mismatch WARNINGs (this repo's committed
# init.hex/ctrl.hex fixtures are deliberately shorter than the testbench's
# declared memory range) plus the DONE marker and $finish -- never the
# $readmem+"Unable to open" conjunction the matcher requires.
HEALTHY_STDOUT = (
    "WARNING: %s/rtl/voice/tb_voice.sv:237: $readmemh(rtl/init.hex): Not "
    "enough words in the file for the requested range [0:1152].\n"
    "WARNING: %s/rtl/voice/tb_voice.sv:238: $readmemh(rtl/ctrl.hex): Not "
    "enough words in the file for the requested range [0:10616831].\n"
    "DONE qmuls=3653350 blocks=1 uni=1\n"
    "%s/rtl/voice/tb_voice.sv:257: $finish called at 0 (1ps)\n"
    % (REPO, REPO, REPO))

MODEL_TRACE = {
    "blocks": [{
        "b": 0,
        "mono_block": [100, -200, 300],
        "voices": [{
            "slot": 0, "key": 60, "gate": True,
            "oscout_block": [1, 2, 3],
            "after": {"aeg": {"state": 1, "phase": 4, "output": 5},
                      "feg": {"state": 1, "phase": 4, "output": 5},
                      "oscstate": 6, "osc_state": 1, "last_level": 7,
                      "pwidth": 8, "pwidth2": 9, "dc_uni": 10, "dc": 11,
                      "osc_out": 12, "osc_out2": 13, "bufpos": 0,
                      "f_r0": 14, "f_r1": 15, "f_clip": 16,
                      "C_end": [17] * 8},
        }],
    }],
}

MATCHING_TRACE = (
    "T 0 0 60 1 1 4 5 1 4 5 6 1 7 8 9 10 11 12 13 0 14 15 16 17 17 17 17 17 "
    "17 17 17 0 0\n"
    "O 0 0 1 2 3\n"
    "M 0 100\nM 0 -200\nM 0 300\n")

MISMATCHING_TRACE = MATCHING_TRACE.replace("M 0 100", "M 0 101", 1)


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
        rc, err = 0, ""
        if trace_text is not None:
            with open(os.path.join(run_dir, "tb_trace.txt"), "w") as f:
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
                        ["compare_rtl_model.py", "--run-dir", run_dir,
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
    """issue #193's failure control: delete exactly one hex file."""
    run_dir = _write_run_dir(tmp_path)
    os.remove(os.path.join(run_dir, "rtl/sinc_deriv.hex"))
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/sinc_deriv.hex" in d["sim_fails"][0]
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
    assert "rtl/sinc_deriv.hex" in d["sim_fails"][0]
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


# compare_rtl_model.py does not expose --timeout on its CLI (it does not pass
# `timeout=` through to `compile_and_run`, so the shared helper's default
# `timeout=None` -- never kill the run -- applies here). The TimeoutExpired
# mechanism itself is already covered directly against the shared helper in
# tests/test_rtl_compile_common.py::test_vvp_timeout_is_reported_not_raised;
# repeating it here would only re-test the same code path through an extra
# layer of indirection.


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


# --------------------------------------------------------------------------
# Issue #360: the public leaf refuses a trace the current run did not write.
# The stubbed vvp exits 0 with this leaf's measured healthy stdout but writes
# no trace; a prior invocation's MATCHING (i.e. passing) trace may sit at the
# expected path. Neither may be reported as a comparison.
# --------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.mark.parametrize("preseed", [None, MATCHING_TRACE],
                         ids=["empty-dir", "stale-passing-trace"])
def test_no_current_trace_is_not_run_even_with_a_passing_stale_trace(
        tmp_path, monkeypatch, preseed):
    run_dir = _write_run_dir(tmp_path)
    trace = os.path.join(run_dir, "tb_trace.txt")
    if preseed is not None:
        with open(trace, "w") as f:
            f.write(preseed)
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, None, sim_stdout=HEALTHY_STDOUT,
                    calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert calls == ["iverilog", "vvp"], calls
    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert d["sim_fails"][0].startswith(
        "missing current-run output: tb_trace.txt"), d["sim_fails"]
    assert d["mismatches"] == 1
    assert d["checked"] == {"checkpoints": 0, "fields": 0, "oscout": 0,
                            "mono": 0}, d["checked"]
    assert "DONE qmuls=" in d["sim_stdout_tail"]
    assert not os.path.exists(trace)


def test_fresh_trace_wins_over_a_stale_passing_trace(tmp_path, monkeypatch):
    """The stale MATCHING trace is replaced by the current run's
    MISMATCHING one, so the leaf reports the current FAIL, not the old
    PASS."""
    run_dir = _write_run_dir(tmp_path)
    with open(os.path.join(run_dir, "tb_trace.txt"), "w") as f:
        f.write(MATCHING_TRACE)
    _stub_simulator(monkeypatch, run_dir, 0, MISMATCHING_TRACE)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d["comparison"] == "FAIL", d
    assert d["sim_fails"] == []
    assert d["mismatches"] == 1


# --------------------------------------------------------------------------
# Issue #361: input failures through the public leaf entry point
# --------------------------------------------------------------------------
#
# Stubbed-simulator legs: vvp "succeeds" and writes a trace the leaf's
# parser cannot read. A previous PASS verdict is pre-seeded at --out.

import json  # noqa: E402

STALE_PASS = {"tb": "tb_voice.sv", "verdict": "PASS", "comparison": "PASS"}

BAD_TRACES = {
    "malformed-numeric-token": MATCHING_TRACE.replace("M 0 100", "M 0 1x0", 1),
    "truncated-O-row": "O 0\n" + MATCHING_TRACE,
    "truncated-M-row": MATCHING_TRACE + "M\n",
}


def _seed_stale(run_dir):
    out = os.path.join(run_dir, "verdict.json")
    with open(out, "w") as f:
        json.dump(STALE_PASS, f)
    return out


@pytest.mark.parametrize("name", sorted(BAD_TRACES))
def test_unparseable_rtl_trace_is_refused_not_compared(tmp_path, monkeypatch,
                                                       name):
    run_dir = _write_run_dir(tmp_path)
    _seed_stale(run_dir)
    _stub_simulator(monkeypatch, run_dir, 0, BAD_TRACES[name])

    rc, d = _run_harness(monkeypatch, run_dir)

    assert rc != 0
    assert d != STALE_PASS
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert d["checked"] == {"checkpoints": 0, "fields": 0, "oscout": 0,
                            "mono": 0}, d["checked"]
    assert d["sim_fails"] == []
    assert d["input_error"]["input"] == "rtl_trace"
    assert d["input_error"]["path"].endswith("tb_trace.txt")
    assert "model=" not in "\n".join(d["first_failures"])  # not a mismatch


@pytest.mark.parametrize("how", ["absent", "invalid-json", "bad-shape"])
def test_bad_model_is_refused_before_the_simulator_launches(
        tmp_path, monkeypatch, how):
    run_dir = _write_run_dir(tmp_path)
    _seed_stale(run_dir)
    path = os.path.join(run_dir, "model_trace.json")
    if how == "absent":
        os.remove(path)
    elif how == "invalid-json":
        with open(path, "w") as f:
            f.write("{not json")
    else:
        with open(path, "w") as f:
            json.dump({"blocks": [{"b": 0, "voices": "oops"}]}, f)
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, MATCHING_TRACE, calls=calls)

    rc, d = _run_harness(monkeypatch, run_dir)

    assert calls == [], calls
    assert rc != 0
    assert d["verdict"] == "FAIL" and d["comparison"] == "NOT_RUN", d
    assert d["checked"]["fields"] == 0
    assert d["input_error"]["input"] == "model"


# Real-simulator legs (no stubs): the model is produced by the frozen model
# runner on a committed sequence into a temporary directory; only temporary
# copies are mutated. Skipped (NOT_RUN) when iverilog/vvp are unavailable.

import shutil  # noqa: E402


def _real_toolchain():
    return shutil.which("iverilog") and shutil.which("vvp")


@pytest.fixture(scope="module")
def real_run_dir(tmp_path_factory):
    if not _real_toolchain():
        pytest.skip("NOT_RUN: iverilog/vvp not available")
    run_dir = str(tmp_path_factory.mktemp("real-voice-run"))
    subprocess.run(
        [sys.executable, os.path.join(REPO, "model", "voice", "run_model.py"),
         "--sequence", "seq-notes-repeated-v1", "--out-dir", run_dir],
        check=True, stdout=subprocess.DEVNULL)
    return run_dir


def _public(run_dir, out):
    """The real public command, as a subprocess."""
    p = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "compare_rtl_model.py"),
         "--run-dir", run_dir, "--out", out],
        capture_output=True, text=True)
    return p.returncode, p


def _copy_run(real_run_dir, tmp_path):
    dst = str(tmp_path / "run")
    shutil.copytree(real_run_dir, dst)
    return dst


def test_real_sim_healthy_run_passes_and_replaces_stale_pass(
        real_run_dir, tmp_path):
    run_dir = _copy_run(real_run_dir, tmp_path)
    out = str(tmp_path / "v.json")
    with open(out, "w") as f:
        json.dump({"verdict": "FAIL", "stale": True}, f)

    rc, _ = _public(run_dir, out)

    with open(out) as f:
        d = json.load(f)
    assert rc == 0
    assert d["verdict"] == "PASS" and d["comparison"] == "PASS"
    assert d["checked"]["mono"] > 0 and d["checked"]["fields"] > 0
    assert "input_error" not in d and "stale" not in d


def test_real_sim_numeric_mismatch_is_fail_not_an_input_refusal(
        real_run_dir, tmp_path):
    run_dir = _copy_run(real_run_dir, tmp_path)
    mpath = os.path.join(run_dir, "model_trace.json")
    with open(mpath) as f:
        model = json.load(f)
    model["blocks"][0]["mono_block"][0] += 1      # one model sample off
    with open(mpath, "w") as f:
        json.dump(model, f)
    out = str(tmp_path / "v.json")
    with open(out, "w") as f:
        json.dump(STALE_PASS, f)

    rc, _ = _public(run_dir, out)

    with open(out) as f:
        d = json.load(f)
    assert rc == 1
    assert d["comparison"] == "FAIL", d
    assert d["checked"]["mono"] > 0
    assert "input_error" not in d


@pytest.mark.parametrize("how", ["absent", "invalid-json", "bad-shape"])
def test_real_public_command_refuses_bad_model_and_replaces_stale_pass(
        real_run_dir, tmp_path, how):
    run_dir = _copy_run(real_run_dir, tmp_path)
    mpath = os.path.join(run_dir, "model_trace.json")
    if how == "absent":
        os.remove(mpath)
    elif how == "invalid-json":
        with open(mpath, "w") as f:
            f.write('{"blocks": [')
    else:
        with open(mpath, "w") as f:
            json.dump({"blocks": {"b": 0}}, f)
    out = str(tmp_path / "v.json")
    with open(out, "w") as f:
        json.dump(STALE_PASS, f)

    rc, p = _public(run_dir, out)

    with open(out) as f:
        d = json.load(f)
    assert rc == 1
    assert d != STALE_PASS
    assert d["comparison"] == "NOT_RUN" and d["verdict"] == "FAIL"
    assert d["checked"] == {"checkpoints": 0, "fields": 0, "oscout": 0,
                            "mono": 0}
    assert d["input_error"]["input"] == "model"
    assert "Traceback" not in p.stderr
