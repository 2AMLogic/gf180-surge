"""Lowpass-family RTL harness reporting controls (issue #209, parent #193).

Covers the three lowpass exactness harnesses migrated to
`_rtl_compile_common`'s opt-in `report_sim_fails=True` / `stimulus_files=`
mode:

  * `tools/compare_rtl_model_lp12.py`   (SXT-037, `rtl/voice/tb_lp12.sv`)
  * `tools/compare_rtl_model_lp24.py`   (SXT-038, `rtl/voice/tb_lp24.sv`)
  * `tools/compare_rtl_model_lpmoog.py` (SXT-039, `rtl/voice/tb_lpmoog.sv`)

All three `$readmemh` the SAME three files (`rtl/init.hex`, `rtl/ctrl.hex`,
`rtl/in.hex`) and share one verdict schema, so the reporting controls are
parametrized over the leaf rather than copied three times.  What differs per
leaf (module, trace shape, model-trace schema) lives in `LEAVES` below.

Two layers, deliberately separated:

1.  **Stubbed-simulator controls** (no iverilog, no vvp, no pinned asset
    tree): the reporting path itself -- a declared stimulus file missing
    before the simulator runs, a `$readmemh`-open failure Icarus reports on
    STDOUT while `vvp` exits 0, a non-zero `vvp` exit, a failed compile --
    plus regression controls that an agreeing trace still PASSes and a
    genuinely disagreeing one still FAILs with `comparison: FAIL`.

2.  **Live real-toolchain controls** (skipped, never silently passed, when
    `iverilog`/`vvp` are absent): issue #193's Stop/escalate condition
    measured rather than frozen into a string.  For each leaf, a healthy run
    of its REAL testbench must emit NO line carrying both `$readmem` and
    `Unable to open`, and the same run with exactly one stimulus file removed
    must emit exactly one such line **while `vvp` still exits 0**.  Measured
    on Icarus 13.0: every healthy run's stdout is Icarus
    `$readmemh(...): Not enough words...` WARNINGs (this fixture is smaller
    than the testbenches' declared memory ranges) plus the `DONE ...` marker
    and `$finish` -- never the matcher's conjunction.

NONE of this is evidence about the RTL, the frozen model, or their
agreement.  The model traces here are synthesized to agree (or to disagree by
exactly one sample) with whatever trace the stub or the real testbench
produced; they establish only that a simulator-level failure is reported as
one, and that a real comparison disagreement is still reported as a
disagreement.  Claim (1) is decided by the leaves' own SXT-037/038/039
exactness runs against real oracle-derived stimulus, untouched here.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import _rtl_compile_common as rcc  # noqa: E402

HAS_IVERILOG = all(shutil.which(x) for x in ("iverilog", "vvp"))

# All three testbenches read exactly these, relative to the run dir.
STIMULUS = ("rtl/init.hex", "rtl/ctrl.hex", "rtl/in.hex")

# The two-sample block every stubbed control below is built from. lp12's T
# line carries (subtype, r0, r1, r_clip, C[0..7]); lp24/lpmoog carry
# (subtype, R[0..4], C[0..7]).
SAMPLES = [42, -7]
C_END = [1, 2, 3, 4, 5, 6, 7, 8]


def _lp12_trace():
    return ("Y 0 0 42\nY 0 1 -7\n"
            "T 0 1 10 20 30 " + " ".join(str(c) for c in C_END) + "\n")


def _lp12_model():
    return {"leg": "reporting-control",
            "instances": [{"trace_blocks": [{
                "b": 0, "subtype": 1, "in": [], "out_model": list(SAMPLES),
                "after": {"r0": 10, "r1": 20, "r_clip": 30,
                          "C_end": list(C_END)}}]}]}


def _r5_trace():
    return ("Y 0 0 42\nY 0 1 -7\n"
            "T 0 2 10 20 30 40 50 " + " ".join(str(c) for c in C_END) + "\n")


def _r5_block():
    return {"b": 0, "subtype": 2, "out_model": list(SAMPLES),
            "after": {"r": [10, 20, 30, 40, 50], "C_end": list(C_END)}}


def _lp24_model():
    return {"case": "reporting-control", "leg": "reporting-control",
            "trace_blocks": [_r5_block()]}


def _lpmoog_model():
    return {"meta": {"case": "reporting-control"}, "subtypes": [2],
            "trace_blocks": [_r5_block()]}


class Leaf:
    def __init__(self, name, module, tb_relpath, tb_lineno, model, trace,
                 fields, has_legacy_build_and_run, expect_flag=False):
        self.name = name
        self.module = module
        self.tb_relpath = tb_relpath
        self.tb_lineno = tb_lineno       # the `$readmemh("rtl/in.hex", ...)`
        self.model = model
        self.trace = trace
        self.fields = fields             # checked["fields"] on a full block
        self.has_legacy_build_and_run = has_legacy_build_and_run
        self.expect_flag = expect_flag

    def __repr__(self):
        return self.name


LEAVES = [
    Leaf("lp12", "tools.compare_rtl_model_lp12",
         "rtl/voice/tb_lp12.sv", 72, _lp12_model, _lp12_trace, 12, True),
    Leaf("lp24", "tools.compare_rtl_model_lp24",
         "rtl/voice/tb_lp24.sv", 79, _lp24_model, _r5_trace, 14, False,
         expect_flag=True),
    Leaf("lpmoog", "tools.compare_rtl_model_lpmoog",
         "rtl/voice/tb_lpmoog.sv", 110, _lpmoog_model, _r5_trace, 14, True),
]

LEAF_IDS = [leaf.name for leaf in LEAVES]


@pytest.fixture(params=LEAVES, ids=LEAF_IDS)
def leaf(request):
    return request.param


def _mod(leaf):
    mod = importlib.import_module(leaf.module)
    return importlib.reload(mod)


def _healthy_stdout(leaf):
    """A healthy real run's stdout shape, as measured on Icarus 13.0.

    Kept as the stubbed false-positive control's input; the live control
    below re-measures it against the real testbench rather than trusting
    this string.
    """
    tb = os.path.join(REPO, leaf.tb_relpath)
    return (
        "WARNING: %s:%d: $readmemh(rtl/ctrl.hex): Not enough words in the "
        "file for the requested range [0:8000000].\n"
        "WARNING: %s:%d: $readmemh(rtl/in.hex): Not enough words in the file "
        "for the requested range [0:8000000].\n"
        "DONE qmuls=768 blocks=1 inputs=64\n"
        "%s:148: $finish called at 0 (1ps)\n"
        % (tb, leaf.tb_lineno - 1, tb, leaf.tb_lineno, tb))


def _readmemh_stdout(leaf):
    """The #188 mechanism's stdout, as measured on this leaf's testbench."""
    tb = os.path.join(REPO, leaf.tb_relpath)
    return (
        "ERROR: %s:%d: $readmemh: Unable to open rtl/in.hex for reading.\n"
        "DONE qmuls=768 blocks=1 inputs=64\n"
        % (tb, leaf.tb_lineno))


SIM_STDERR = "vvp: simulated simulator failure (no rtl/in.hex)"


def _write_run_dir(leaf, tmp_path):
    run_dir = str(tmp_path)
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(leaf.model(), f)
    os.makedirs(os.path.join(run_dir, "rtl"), exist_ok=True)
    for rel in STIMULUS:
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
        return types.SimpleNamespace(
            returncode=sim_rc, stdout=sim_stdout,
            stderr=(SIM_STDERR if sim_rc else ""))

    monkeypatch.setattr(rcc, "subprocess", types.SimpleNamespace(
        run=fake_run, DEVNULL=subprocess.DEVNULL,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired))


def _delegating_simulator(monkeypatch, substitutions, calls):
    def real_run(cmd, **kwargs):
        calls.append(cmd[0])
        return subprocess.run(substitutions.get(cmd[0], cmd), **kwargs)

    monkeypatch.setattr(rcc, "subprocess", types.SimpleNamespace(
        run=real_run, DEVNULL=subprocess.DEVNULL,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired))


def _run_harness(leaf, monkeypatch, run_dir, extra=()):
    mod = _mod(leaf)
    out = os.path.join(run_dir, "verdict.json")
    if os.path.exists(out):
        os.remove(out)
    monkeypatch.setattr(sys, "argv",
                        [leaf.module, "--run-dir", run_dir, "--out", out]
                        + list(extra))
    rc = mod.main()
    with open(out) as f:
        return rc, json.load(f)


# ---------------------------------------------------------------- regression

def test_agreeing_trace_still_passes(leaf, tmp_path, monkeypatch):
    run_dir = _write_run_dir(leaf, tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, leaf.trace())

    rc, d = _run_harness(leaf, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""
    assert d["mismatches"] == 0
    assert d["checked"] == {"samples": 2, "checkpoints": 1,
                            "fields": leaf.fields}


def test_comparison_mismatch_still_reported(leaf, tmp_path, monkeypatch):
    """A genuine RTL-vs-model disagreement must NOT be swallowed."""
    run_dir = _write_run_dir(leaf, tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0,
                    leaf.trace().replace("Y 0 1 -7", "Y 0 1 -8", 1))

    rc, d = _run_harness(leaf, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "FAIL"
    assert d["sim_fails"] == []
    assert d["mismatches"] == 1
    assert "sample 1" in d["first_failures"][0]
    assert d["checked"]["samples"] == 2


# ----------------------------------------------------- the four mechanisms

def test_missing_stimulus_file_is_named_and_is_not_a_disagreement(
        leaf, tmp_path, monkeypatch):
    """Issue #193's failure control: remove exactly one stimulus file."""
    run_dir = _write_run_dir(leaf, tmp_path)
    os.remove(os.path.join(run_dir, "rtl/in.hex"))
    calls = []
    _stub_simulator(monkeypatch, run_dir, 0, leaf.trace(), calls=calls)

    rc, d = _run_harness(leaf, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/in.hex" in d["sim_fails"][0]
    assert d["checked"] == {"samples": 0, "checkpoints": 0, "fields": 0}
    joined = "\n".join(d["first_failures"])
    assert "sample" not in joined and "missing T line" not in joined, joined
    assert calls == [], calls  # the simulator is never even invoked


def test_readmemh_open_failure_with_rc_zero_is_a_sim_failure(
        leaf, tmp_path, monkeypatch):
    """The #188 mechanism: ERROR on STDOUT, `vvp` still exits 0."""
    run_dir = _write_run_dir(leaf, tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, None,
                    sim_stdout=_readmemh_stdout(leaf))

    rc, d = _run_harness(leaf, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "rtl/in.hex" in d["sim_fails"][0]
    assert "rc=0" in d["sim_fails"][0]
    assert "$readmemh" in d["sim_stdout_tail"]
    assert d["checked"] == {"samples": 0, "checkpoints": 0, "fields": 0}


def test_nonzero_vvp_exit_is_reported_with_its_stderr(
        leaf, tmp_path, monkeypatch):
    run_dir = _write_run_dir(leaf, tmp_path)
    _stub_simulator(monkeypatch, run_dir, 4, leaf.trace())

    rc, d = _run_harness(leaf, monkeypatch, run_dir)

    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    joined = "\n".join(d["sim_fails"])
    assert "vvp exited rc=4" in joined, joined
    assert SIM_STDERR in joined, joined


def test_compile_failure_is_recorded_instead_of_raising(
        leaf, tmp_path, monkeypatch):
    run_dir = _write_run_dir(leaf, tmp_path)
    calls = []
    _delegating_simulator(
        monkeypatch,
        {"iverilog": ["sh", "-c", "echo 'syntax error' >&2; exit 3"]}, calls)

    rc, d = _run_harness(leaf, monkeypatch, run_dir)

    assert calls == ["iverilog"], calls
    assert rc != 0
    assert d["verdict"] == "FAIL", d
    assert d["comparison"] == "NOT_RUN", d
    assert len(d["sim_fails"]) == 1, d["sim_fails"]
    assert "iverilog compile failed rc=3" in d["sim_fails"][0]


# ------------------------------------------------- false-positive guardrail

def test_healthy_stdout_diagnostics_do_not_flip_a_pass(
        leaf, tmp_path, monkeypatch):
    """Issue #188's guardrail, per leaf (#193's Stop/escalate condition).

    A matcher that turns a genuinely passing exactness run into a FAIL is
    worse than the lost reason it recovers, so the benign
    `$readmemh(...): Not enough words...` WARNINGs every one of these
    testbenches emits on a healthy run must not trip it.
    """
    run_dir = _write_run_dir(leaf, tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, leaf.trace(),
                    sim_stdout=_healthy_stdout(leaf))

    rc, d = _run_harness(leaf, monkeypatch, run_dir)

    assert rc == 0
    assert d["verdict"] == "PASS", d
    assert d["comparison"] == "PASS"
    assert d["sim_fails"] == []
    assert d["sim_stdout_tail"] == ""


# ------------------------------------------- preserved legacy contracts

def test_legacy_build_and_run_still_returns_a_trace_path(
        leaf, tmp_path, monkeypatch):
    """`build_and_run` is consumed by the leaves' negative-control tools.

    `tools/lp12_negative_controls.py`, `tools/lpmoog_negative_controls.py`,
    `tools/run_sxt039_checks.py` and `tests/test_sxt039_lpmoog.py` all call
    `crm.build_and_run(...)` and use the returned PATH. Issue #209's
    reporting mode is opt-in through a separate
    `build_and_run_reporting(...)`, so this contract must not have moved.
    """
    if not leaf.has_legacy_build_and_run:
        pytest.skip("%s has no public build_and_run()" % leaf.name)
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, leaf.trace())

    path = mod.build_and_run(os.path.join(REPO, leaf.tb_relpath), run_dir)

    assert isinstance(path, str)
    assert path == os.path.join(run_dir, "tb_trace.txt")
    # ...and the reporting variant returns the SimResult shape instead.
    sim = mod.build_and_run_reporting(
        os.path.join(REPO, leaf.tb_relpath), run_dir)
    assert isinstance(sim, rcc.SimResult)
    assert sim.sim_fails == []
    assert sim.trace == path


def test_legacy_build_and_run_still_raises_on_a_failed_run(
        leaf, tmp_path, monkeypatch):
    if not leaf.has_legacy_build_and_run:
        pytest.skip("%s has no public build_and_run()" % leaf.name)
    mod = _mod(leaf)
    run_dir = _write_run_dir(leaf, tmp_path)
    _stub_simulator(monkeypatch, run_dir, 0, leaf.trace())
    # a non-zero compile must still raise out of the LEGACY entry point
    calls = []
    _delegating_simulator(monkeypatch, {"iverilog": ["sh", "-c", "exit 3"]},
                          calls)
    with pytest.raises(subprocess.CalledProcessError):
        mod.build_and_run(os.path.join(REPO, leaf.tb_relpath), run_dir)


def test_sim_failure_never_satisfies_expect_fail(tmp_path, monkeypatch):
    """lp24 only: `--expect fail` must not accept a stimulus-load failure.

    `tools/lp24_negative_controls.py` runs the RTL mutant control through
    `compare_rtl_model_lp24.py --expect fail` and treats exit 0 / verdict
    FAIL as CONTROL-OK. A run whose stimulus never loaded ALSO produces
    verdict FAIL -- with the comparison never run -- so before this change a
    missing `rtl/init.hex` made the negative control report itself as
    passing. Measured live pre-migration (issue #209 evidence): exit 0.
    """
    leaf = LEAVES[1]
    assert leaf.name == "lp24"
    run_dir = _write_run_dir(leaf, tmp_path)
    os.remove(os.path.join(run_dir, "rtl/init.hex"))
    _stub_simulator(monkeypatch, run_dir, 0, leaf.trace())

    rc, d = _run_harness(leaf, monkeypatch, run_dir,
                         extra=("--expect", "fail"))

    assert d["verdict"] == "FAIL"
    assert d["expected"] == "FAIL"
    assert d["comparison"] == "NOT_RUN", d
    assert rc != 0, ("a simulator-level failure must never be reported as a "
                     "satisfied negative control")


def _nc_d(runs_dir):
    """Import and run `tools/lp24_negative_controls.py::nc_d` in isolation.

    Loaded by path: that module imports the LP24 leg model at import time and
    lives beside a same-named LP12 file, so a plain `import` is unsafe here.
    """
    import importlib.util
    path = os.path.join(REPO, "tools", "lp24_negative_controls.py")
    spec = importlib.util.spec_from_file_location("lp24_nc_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    lines = []
    rows = mod.nc_d(lines, runs_dir)
    return lines, rows[0]


def test_nc_d_reports_a_stimulus_load_failure_as_a_broken_control(tmp_path):
    """The live consequence of the `--expect fail` hazard, end to end.

    `nc_d` judges the RTL-mutant negative control from the harness's own
    summary. A missing `rtl/init.hex` makes tb_lp24.sv read n_blocks as x,
    write an EMPTY-but-parseable trace and exit 0, so the harness reports
    verdict FAIL with the comparison never run. `nc_d` must call that
    CONTROL-BROKEN, not CONTROL-OK. No simulator is needed: the harness's
    pre-flight check short-circuits before `iverilog` is invoked.
    """
    run_dir = os.path.join(str(tmp_path), "run-edges-toggle")
    os.makedirs(os.path.join(run_dir, "rtl"))
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump(_lp24_model(), f)
    for rel in STIMULUS:
        open(os.path.join(run_dir, rel), "w").close()
    os.remove(os.path.join(run_dir, "rtl/init.hex"))

    lines, row = _nc_d(str(tmp_path))

    assert row["control_ok"] is False, row
    assert row["verdict"] == "FAIL"          # ...but for the WRONG reason
    assert row["comparison"] == "NOT_RUN", row
    assert row["sim_fails"] and "rtl/init.hex" in row["sim_fails"][0]
    assert "CONTROL-BROKEN" in lines[0], lines
    assert "simulator-level failure" in lines[0], lines


@pytest.mark.skipif(not HAS_IVERILOG, reason="iverilog/vvp not present")
def test_nc_d_still_reports_a_caught_mutant_as_control_ok(tmp_path):
    """Known-good direction: the tightened criterion must not break nc_d.

    Real `iverilog`/`vvp`: build a complete run dir, take the CLEAN
    testbench's own trace as the model trace (so the clean RTL agrees by
    construction), then let `nc_d` run the committed rounding mutant against
    it. The mutant must still be caught -- verdict FAIL with
    `comparison: FAIL` and no simulator-level failure.
    """
    run_dir = os.path.join(str(tmp_path), "run-edges-toggle")
    os.makedirs(run_dir)
    _real_run_dir(run_dir)
    tb = os.path.join(REPO, "rtl", "voice", "tb_lp24.sv")
    image = os.path.join(run_dir, "clean.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", image, tb], check=True)
    subprocess.run(["vvp", image], cwd=run_dir, check=True,
                   capture_output=True, text=True)

    y, t = {}, {}
    with open(os.path.join(run_dir, "tb_trace.txt")) as f:
        for line in f:
            parts = line.split()
            if parts and parts[0] == "Y":
                y[(int(parts[1]), int(parts[2]))] = int(parts[3])
            elif parts and parts[0] == "T":
                vals = [int(v) for v in parts[1:]]
                t[vals[0]] = vals[1:]
    assert y and t, "the clean testbench produced no trace"
    blk = {"b": 0, "subtype": t[0][0],
           "out_model": [y[(0, k)] for k in range(64)],
           "after": {"r": t[0][1:6], "C_end": t[0][6:14]}}
    with open(os.path.join(run_dir, "model_trace.json"), "w") as f:
        json.dump({"case": "reporting-control", "leg": "reporting-control",
                   "trace_blocks": [blk]}, f)

    lines, row = _nc_d(str(tmp_path))

    assert row["sim_fails"] == [], row
    assert row["verdict"] == "FAIL", row
    assert row["comparison"] == "FAIL", row
    assert row["control_ok"] is True, row
    assert "CONTROL-OK" in lines[0], lines


# ----------------------------------------------- live real-toolchain control

FIXTURE_C = [100000, 200000, 300000, 400000, 500000, 600000, 700000, 800000]
FIXTURE_DC = [1, 2, 3, 4, 5, 6, 7, 8]


def _write_hex(path, words):
    with open(path, "w") as f:
        for x in words:
            f.write("%08x\n" % (x & 0xffffffff))


def _real_run_dir(tmp_path):
    """A minimal but fully DEFINED (non-x) stimulus these testbenches accept.

    Not oracle-derived and not an exactness fixture -- its only job is to let
    the real testbench reach `$finish` so its healthy stdout can be measured.
    """
    d = os.path.join(str(tmp_path), "rtl")
    os.makedirs(d, exist_ok=True)
    _write_hex(os.path.join(d, "init.hex"), [1])            # n_blocks = 1
    _write_hex(os.path.join(d, "ctrl.hex"),                 # active | reset
               [3, 1] + FIXTURE_C + FIXTURE_DC)
    _write_hex(os.path.join(d, "in.hex"), [i * 1000 for i in range(64)])
    return str(tmp_path)


@pytest.mark.skipif(not HAS_IVERILOG, reason="iverilog/vvp not present")
def test_live_healthy_run_does_not_trip_the_matcher(leaf, tmp_path):
    """Issue #193's Stop/escalate condition, measured not assumed.

    Real `iverilog`/`vvp` on this leaf's real testbench: a healthy run must
    emit NO line carrying both `$readmem` and `Unable to open`, and the same
    run with exactly one stimulus file removed must emit exactly one -- while
    `vvp` STILL EXITS 0, which is the whole reason `check=True` cannot see it.
    """
    run_dir = _real_run_dir(tmp_path)
    tb = os.path.join(REPO, leaf.tb_relpath)
    image = os.path.join(run_dir, "probe.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", image, tb], check=True)

    healthy = subprocess.run(["vvp", image], cwd=run_dir, check=True,
                             capture_output=True, text=True)
    assert rcc.scan_stdout_for_load_failures(healthy.stdout) == [], (
        "STOP/ESCALATE (issue #193): %s's healthy run trips the matcher; it "
        "needs a narrower pattern, not a guess" % leaf.tb_relpath)
    assert "DONE" in healthy.stdout, healthy.stdout

    away = os.path.join(run_dir, "rtl", "in.hex")
    os.rename(away, away + ".removed")
    broken = subprocess.run(["vvp", image], cwd=run_dir,
                            capture_output=True, text=True)

    assert broken.returncode == 0, (
        "the #188 mechanism requires rc=0; got %d" % broken.returncode)
    hits = rcc.scan_stdout_for_load_failures(broken.stdout)
    assert len(hits) == 1, (hits, broken.stdout)
    assert "rtl/in.hex" in hits[0]
    assert "Unable to open" in hits[0]
