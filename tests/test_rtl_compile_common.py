"""`tools/_rtl_compile_common.py` reporting-mode tests (issue #193).

Issue #188 measured, on real Icarus (11, 12.0, 13.0), that a `$readmemh`
target that fails to open is reported on the simulation's STDOUT while `vvp`
still **exits 0** -- so `check=True` (this module's unconditional default)
never sees it, and a caller that trusts the exit code alone goes on to parse
a trace that was never produced, reporting what looks like a comparison
disagreement when the truth is "the stimulus never loaded". Issue #193
re-enumerated the shared helper's 10 real importers (`compare_wt_rtl_model.py`
is NOT one of them -- it does its own inline compile/run, by design) and
found the SAME blind spot structurally present in every one, because they
all route through this one `compile_and_run`.

This file tests the shared helper's fix directly: the opt-in
`report_sim_fails=True` / `stimulus_files=` mode added by issue #193, using
REAL `iverilog`/`vvp` (Icarus 13.0 in this environment) against tiny,
purpose-built testbenches -- not any production leaf's testbench -- so every
axis `compile_and_run` exposes (`direct_exec`, `run_by_name`, `stdout_path`,
`done_prefix`, `quiet_compile`, `compile_in_workdir`, `absolute`,
`extra_sources`) gets independent coverage of all four mechanisms plus the
false-positive control, without depending on any leaf's own fixtures.

Per-leaf false-positive controls (issue #193's Stop/escalate condition: "if
any harness's healthy run DOES emit ERROR:-prefixed stdout lines... a
matcher for that harness needs a narrower pattern") are NOT re-derived here
-- they belong to each migrated harness's own test file, because Icarus's
diagnostic wording is a simulator-level constant but each testbench's *own*
benign diagnostics (which must not collide with the matcher) are leaf-
specific and must be measured per leaf.
"""

import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import _rtl_compile_common as rcc  # noqa: E402

HAS_IVERILOG = all(shutil.which(x) for x in ("iverilog", "vvp"))
pytestmark = pytest.mark.skipif(not HAS_IVERILOG,
                                reason="iverilog/vvp not present")

# A minimal testbench that $readmemh's ONE file relative to its cwd, prints a
# DONE marker, and finishes -- deliberately as small as Icarus allows so the
# compile+run round trip stays fast across every axis combination below.
TB_SRC = """\
module tb_common_test;
  reg [7:0] mem [0:15];
  initial begin
    $readmemh("stim.hex", mem);
    $display("DONE marker=%0d", mem[0]);
    $finish;
  end
endmodule
"""

# A companion DUT-like source used only by the `extra_sources` axis control
# (an empty module is enough: iverilog just needs a second file on the
# command line to prove `extra_sources` reaches the compile step).
EXTRA_SRC = """\
module unused_extra_module;
endmodule
"""


def _write(path, text):
    with open(path, "w") as f:
        f.write(text)


def _make_tb(tmp_path):
    tb = os.path.join(str(tmp_path), "tb_common_test.sv")
    _write(tb, TB_SRC)
    return tb


def _make_stim(run_dir, value="ab"):
    os.makedirs(run_dir, exist_ok=True)
    _write(os.path.join(run_dir, "stim.hex"), value + "\n")


# --------------------------------------------------------------------------
# Real-toolchain measurement: what THIS testbench's healthy stdout contains,
# and what a missing stimulus file makes Icarus print (rc still 0).
# --------------------------------------------------------------------------


def test_measured_healthy_stdout_has_no_load_failure_line(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    vvp = os.path.join(run_dir, "tb.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", vvp, tb], check=True)
    result = subprocess.run(["vvp", vvp], cwd=run_dir, capture_output=True,
                            text=True)
    assert result.returncode == 0
    assert rcc.scan_stdout_for_load_failures(result.stdout) == [], \
        result.stdout


def test_measured_missing_stimulus_exits_zero_with_readmemh_error(tmp_path):
    """The exact #188/#193 mechanism, reproduced on THIS environment's
    Icarus before any of the assertions below rely on it."""
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    # deliberately do NOT write stim.hex
    vvp = os.path.join(run_dir, "tb.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", vvp, tb], check=True)
    result = subprocess.run(["vvp", vvp], cwd=run_dir, capture_output=True,
                            text=True)
    assert result.returncode == 0, \
        "if this ever fails, Icarus changed behavior and #193's whole premise " \
        "needs re-checking"
    hits = rcc.scan_stdout_for_load_failures(result.stdout)
    assert len(hits) == 1, result.stdout
    assert "stim.hex" in hits[0]


# --------------------------------------------------------------------------
# scan_stdout_for_load_failures: unit control on the matcher itself.
# --------------------------------------------------------------------------


def test_matcher_is_narrow_not_bare_error_prefix():
    healthy_but_alarming = (
        "ERROR: something unrelated happened\n"
        "WARNING: $readmemh(x): Not enough words in the file\n")
    assert rcc.scan_stdout_for_load_failures(healthy_but_alarming) == []
    assert rcc.scan_stdout_for_load_failures("") == []
    assert rcc.scan_stdout_for_load_failures(None) == []
    hit = "ERROR: tb.sv:1: $readmemh: Unable to open x.hex for reading."
    assert rcc.scan_stdout_for_load_failures(hit) == [hit]


# --------------------------------------------------------------------------
# report_sim_fails=True: mechanism 1 (pre-flight missing stimulus_files).
# --------------------------------------------------------------------------


def test_missing_declared_stimulus_is_named_before_simulator_runs(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    # stim.hex intentionally absent; declare it via stimulus_files.
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            stimulus_files=("stim.hex",),
                            report_sim_fails=True)
    assert isinstance(r, rcc.SimResult)
    assert len(r.sim_fails) == 1, r.sim_fails
    assert "stim.hex" in r.sim_fails[0]
    assert r.trace is None
    assert r.stdout == ""
    # the simulator must never have been invoked at all: no tb.vvp built.
    assert not os.path.exists(os.path.join(run_dir, "tb.vvp"))


def test_stimulus_files_pre_check_is_relative_to_workdir(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            stimulus_files=("stim.hex",),
                            report_sim_fails=True)
    assert r.sim_fails == [], r.sim_fails


# --------------------------------------------------------------------------
# report_sim_fails=True: mechanism 2 ($readmemh on stdout, rc=0).
# --------------------------------------------------------------------------


def test_readmemh_stdout_failure_with_rc_zero_is_reported_not_raised(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    # stim.hex absent, and NOT declared via stimulus_files -- so mechanism 1
    # cannot catch it; only mechanism 2 (the stdout scan) can.
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            report_sim_fails=True)
    assert len(r.sim_fails) == 1, r.sim_fails
    assert "stim.hex" in r.sim_fails[0]
    assert "rc=0" in r.sim_fails[0]
    assert "$readmemh" in r.stdout_tail


def test_healthy_stdout_does_not_flip_a_pass(tmp_path):
    """FALSE-POSITIVE control: a genuinely healthy run must report no
    sim_fails at all, on every capture axis (suppress_stdout / stdout_path /
    capture_output / done_prefix are all ignored by report_sim_fails=True,
    which always captures -- this asserts that ignoring them is harmless)."""
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            report_sim_fails=True,
                            done_prefix="DONE marker=")
    assert r.sim_fails == [], r.sim_fails
    assert r.stdout_tail == ""
    assert r.value == 0xab
    assert r.trace == os.path.join(run_dir, "tb_trace.txt")


# --------------------------------------------------------------------------
# report_sim_fails=True: mechanism 3 (non-zero vvp exit).
# --------------------------------------------------------------------------


def test_nonzero_vvp_exit_is_reported_not_raised(tmp_path):
    run_dir = str(tmp_path)
    # $finish's argument controls trailing diagnostics, NOT the process exit
    # code (Icarus always exits 0 from a plain $finish) -- $fatal is what
    # actually makes vvp exit non-zero, measured above in fataltest.
    tb_src = 'module tb_fail_test; initial $fatal(1, "boom"); endmodule\n'
    tb = os.path.join(run_dir, "tb_fail_test.sv")
    _write(tb, tb_src)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            report_sim_fails=True)
    assert len(r.sim_fails) == 1, r.sim_fails
    assert "vvp exited rc=" in r.sim_fails[0]


# --------------------------------------------------------------------------
# report_sim_fails=True: mechanism 4 (compile failure / timeout).
# --------------------------------------------------------------------------


def test_compile_failure_is_reported_not_raised(tmp_path):
    run_dir = str(tmp_path)
    tb = os.path.join(run_dir, "broken.sv")
    _write(tb, "this is not valid verilog {{{\n")
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            report_sim_fails=True)
    assert len(r.sim_fails) == 1, r.sim_fails
    assert "iverilog compile failed" in r.sim_fails[0]
    assert not os.path.exists(os.path.join(run_dir, "tb.vvp"))


def test_vvp_timeout_is_reported_not_raised(tmp_path):
    run_dir = str(tmp_path)
    tb_src = ("module tb_spin_test;\n"
             "  initial begin\n"
             "    #1 $display(\"booting\");\n"
             "    forever #1 ;\n"
             "  end\n"
             "endmodule\n")
    tb = os.path.join(run_dir, "tb_spin_test.sv")
    _write(tb, tb_src)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            report_sim_fails=True, timeout=0.5)
    assert len(r.sim_fails) == 1, r.sim_fails
    assert "timeout" in r.sim_fails[0]
    assert "0.5" in r.sim_fails[0]


# --------------------------------------------------------------------------
# Axis coverage: report_sim_fails=True must behave the same way regardless
# of which of the legacy run-step axes is also set.
# --------------------------------------------------------------------------


def test_direct_exec_axis_with_reporting(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            direct_exec=True, report_sim_fails=True)
    assert r.sim_fails == [], r.sim_fails


def test_run_by_name_axis_with_reporting(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            compile_in_workdir=True, run_by_name=True,
                            report_sim_fails=True)
    assert r.sim_fails == [], r.sim_fails


def test_stdout_path_axis_with_reporting_still_writes_the_log(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    log = os.path.join(run_dir, "sim.log")
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            stdout_path=log, report_sim_fails=True)
    assert r.sim_fails == [], r.sim_fails
    with open(log) as f:
        logged = f.read()
    assert "DONE marker" in logged
    assert logged == r.stdout


def test_quiet_compile_axis_with_reporting(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            quiet_compile=True, report_sim_fails=True)
    assert r.sim_fails == [], r.sim_fails


def test_extra_sources_and_absolute_axes_with_reporting(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    extra = os.path.join(run_dir, "extra.sv")
    _write(extra, EXTRA_SRC)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            extra_sources=(extra,), absolute=True,
                            report_sim_fails=True)
    assert r.sim_fails == [], r.sim_fails


def test_trace_name_none_axis_with_reporting(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    r = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                            trace_name=None, report_sim_fails=True)
    assert r.sim_fails == [], r.sim_fails
    assert r.trace is None


# --------------------------------------------------------------------------
# Non-reporting default path is UNCHANGED (regression control): the
# report_sim_fails=True mode is purely additive.
# --------------------------------------------------------------------------


def test_default_mode_still_raises_on_compile_failure(tmp_path):
    run_dir = str(tmp_path)
    tb = os.path.join(run_dir, "broken.sv")
    _write(tb, "this is not valid verilog {{{\n")
    with pytest.raises(subprocess.CalledProcessError):
        rcc.compile_and_run(tb, run_dir, out_name="tb.vvp")


def test_default_mode_still_returns_trace_path(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    trace = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp")
    assert trace == os.path.join(run_dir, "tb_trace.txt")


def test_default_mode_still_returns_done_prefix_value(tmp_path):
    run_dir = str(tmp_path)
    tb = _make_tb(tmp_path)
    _make_stim(run_dir)
    trace, value = rcc.compile_and_run(tb, run_dir, out_name="tb.vvp",
                                       done_prefix="DONE marker=")
    assert value == 0xab
