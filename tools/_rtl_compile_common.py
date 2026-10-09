#!/usr/bin/env python3
"""Shared iverilog compile/run step for the RTL-vs-frozen-model exactness
harnesses (`tools/compare_*rtl*.py`).

These harnesses all perform the same two-step job before their own
block-specific trace parsing and comparison begin:

  1. `iverilog -g2012 -o <vvp> <sv_file> [extra sources…]`
  2. execute the compiled image (through the `vvp` launcher, or directly)

and then read a trace file the testbench wrote into the run directory.  Ten
harnesses each carried a private `build_and_run()` copy of that step; the
copies had drifted in incidental ways (vvp file naming, whether the compile
runs with `cwd=` the run dir, which streams are suppressed, whether the image
is launched via `vvp` or exec'd directly).  This module holds the single
implementation and exposes every axis those copies actually differed on, so
each call site keeps its *exact* previous behavior.

`compile_and_run` is a build/run helper only: it parses no traces, compares no
fields and makes no verdict.  `run_leaf_comparison` (issue #303) wraps it with
the *report-assembly* skeleton five of those harnesses had copied verbatim --
load `model_trace.json`, run the simulator, decide `comparison` from
`SimResult.sim_fails`, assemble/print/write the summary JSON, return the 0/1
exit code.  It still delegates every judgement: claim (1) — "the RTL matches
the frozen fixed-point model exactly" — is decided entirely by each harness's
own `parse_tb`/`compare` callables, which this module receives and calls but
never inspects, and by the per-leaf `checked`/summary shapes it is handed
rather than normalizing.

ISSUE #193 (the #188 blind spot, shared): by default (`report_sim_fails`
unset), this function still runs both subprocess steps with `check=True` --
a failing *compile*, or a `vvp` invocation that exits non-zero, raises
CalledProcessError, same as before this issue. That default still cannot see
one specific failure shape: Icarus reports a `$readmemh` stimulus-open
failure on the simulation's STDOUT and still **exits 0** (measured on Icarus
11, 12.0 and 13.0 -- issue #188's Finding, reproduced here for `tb_voice.sv`
and `tb_control.sv` in issue #193's evidence). A caller relying on `check=True`
alone never sees that: the run "succeeds", the (empty or partial) trace file
is parsed, and the harness's own comparison reports what looks like a wall of
RTL-vs-model mismatches -- when the true failure was the stimulus never
loading at all.

`report_sim_fails=True` is the opt-in fix: instead of raising, every one of
the four mechanisms #188/#193 enumerate is caught and returned as a
`SimResult.sim_fails` string naming the reason, so the *caller* can report a
simulator-level failure (and skip its own comparison, keeping
`comparison: NOT_RUN`) instead of ever printing "the RTL disagreed with the
model" when the truth is "the stimulus never loaded". The four mechanisms:

  1. a declared input (`stimulus_files`, relative to `workdir`) missing
     before the simulator is invoked at all -- cheaper and more direct than
     pattern-matching simulator output, and it names the exact file. It does
     not *replace* mechanism 2 below -- a file can be present and still
     unreadable, and iverilog resolves the paths itself.
  2. `$readmemh: Unable to open ...` on the simulation's STDOUT while `vvp`
     exits 0 -- the mechanism above. Matched NARROWLY (both the `$readmem`
     token and `Unable to open`), never on a bare `ERROR:` prefix, so a
     testbench's own runtime diagnostics cannot trip it (issue #188's
     false-positive guardrail; a matcher that turns a genuinely passing
     exactness run into a FAIL is worse than the lost reason it recovers).
     This measurement does NOT transfer between testbenches automatically --
     every call site that turns `report_sim_fails` on must independently
     confirm its own healthy-run stdout carries no such line before relying
     on this mechanism (issue #193's per-harness evidence does this for each
     harness it touches).
  3. a non-zero `vvp` exit.
  4. `iverilog` failing to compile (CalledProcessError) or `vvp` exceeding
     `timeout` (TimeoutExpired) -- caught, so the caller can still write a
     verdict with a reason instead of dying by traceback with no verdict at
     all.

Issue #360 adds a fifth, for a non-null `trace_name` only:

  5. a clean run (none of 1-4 fired) that left no trace at the declared
     path. The helper-owned `workdir/trace_name` is removed BEFORE `vvp`
     launches, so a trace there afterward can only be this invocation's
     output; a prior invocation's trace in a reused run dir can no longer be
     parsed as if the current run produced it. Absence becomes a
     `missing current-run output: ...` entry, which the callers' existing
     `comparison: NOT_RUN` branch already handles. `trace_name=None`
     declares no trace output and is exempt; the non-reporting default path
     and explicitly supplied offline traces (`compare_sine_rtl_model.py
     --trace`, which never calls this module) are unchanged.

Original to this repository (Apache-2.0).
"""

import collections
import json
import os
import subprocess
import sys

__all__ = ["compile_and_run", "run_leaf_comparison",
           "scan_stdout_for_load_failures", "SimResult"]


# The result shape returned ONLY when `report_sim_fails=True`. Deliberately a
# single fixed shape regardless of which capture/run axis (`direct_exec`,
# `run_by_name`, `stdout_path`, `done_prefix`, ...) the call site set, so a
# caller opting into failure reporting does not also have to track which of
# `compile_and_run`'s several legacy return shapes applies to its own axes.
#
#   trace        os.path.join(workdir, trace_name), or None (trace_name is
#                None, or a simulator-level failure means nothing trustworthy
#                was produced -- including mechanism 5, the declared trace
#                was not written by this invocation)
#   value        int(...) of the last `done_prefix`-prefixed stdout line, or
#                None (no done_prefix given, or a simulator-level failure)
#   stdout       the simulation's full captured stdout ("" if it never ran)
#   sim_fails    list[str]; empty means every mechanism above was clean
#   stdout_tail  last 2000 chars of stdout, populated only when sim_fails is
#                non-empty (mirrors compare_wt_rtl_model.py's
#                `sim_stdout_tail` convention exactly)
SimResult = collections.namedtuple(
    "SimResult", ["trace", "value", "stdout", "sim_fails", "stdout_tail"])


def _as_text(stream):
    """subprocess streams: str, bytes or None (TimeoutExpired) -> str."""
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", "replace")
    return stream


def scan_stdout_for_load_failures(stdout, limit=10):
    """Stimulus-load failures Icarus reports on STDOUT while exiting 0.

    Matched NARROWLY, on both the `$readmem` token and `Unable to open`,
    deliberately NOT on a bare `ERROR:` prefix -- copied from
    `compare_wt_rtl_model.py`'s measured matcher (issue #188). Reporting a run
    that did not fail as failed would be a worse defect than the lost reason
    this matcher exists to recover, so this stays narrow rather than greedy.
    """
    hits = []
    for line in _as_text(stdout).splitlines():
        line = line.strip()
        if "$readmem" in line and "Unable to open" in line:
            hits.append(line)
            if len(hits) >= limit:
                break
    return hits


def compile_and_run(sv_file, workdir, *, out_name, extra_sources=(),
                    absolute=False, compile_in_workdir=False,
                    quiet_compile=False, direct_exec=False, run_by_name=False,
                    suppress_stdout=True, stdout_path=None,
                    capture_output=False, done_prefix=None,
                    trace_name="tb_trace.txt",
                    stimulus_files=(), report_sim_fails=False, timeout=None):
    """Compile `sv_file` with iverilog and run the result in `workdir`.

    Positional:
      sv_file       testbench (or DUT) source passed first to iverilog
      workdir       run directory: the simulation's cwd, where the trace lands

    Compile-step axes:
      out_name      basename of the compiled image inside `workdir`
      extra_sources further sources appended after `sv_file` on the command
      absolute      os.path.abspath() `workdir` and the sources first
      compile_in_workdir  run iverilog with cwd=workdir (default: inherit)
      quiet_compile       send iverilog stdout AND stderr to /dev/null

    Run-step axes:
      direct_exec   exec the compiled image directly instead of `vvp <image>`
      run_by_name   pass `out_name` rather than the full path (cwd-relative)
      suppress_stdout  send the simulation's stdout to /dev/null
      stdout_path   redirect the simulation's stdout to this file instead
      capture_output   capture the simulation's stdout as text and return it
      done_prefix   capture stdout and return int(…) of the last line starting
                    with this prefix (e.g. "DONE kt-qmuls="), or None

    Failure-reporting axes (issue #193; opt-in, ignored unless
    `report_sim_fails=True`):
      stimulus_files   paths (relative to `workdir`) the testbench
                       `$readmemh`s; checked to exist BEFORE iverilog runs
                       at all (mechanism 1)
      report_sim_fails when True, return a `SimResult` instead of raising or
                       returning one of the legacy shapes below: every
                       recognized simulator-level failure becomes a
                       `SimResult.sim_fails` entry (mechanisms 1-5 in the
                       module docstring); a non-null `trace_name` under
                       `workdir` is deleted before `vvp` runs and must be
                       re-created by it (mechanism 5)
      timeout          seconds before the vvp run is killed when
                       `report_sim_fails=True` (None = no timeout, matching
                       the unbounded default `subprocess.run` already had)

    Return, when `report_sim_fails` is NOT given (default, unchanged):
      (trace, value)  when `done_prefix` is given (value may be None)
      (trace, stdout) when `capture_output` is given
      None            when `trace_name` is None
      trace           otherwise, i.e. os.path.join(workdir, trace_name)

      `check=True` throughout: a failing compile or simulation raises
      CalledProcessError rather than producing a silently empty trace.

    Return, when `report_sim_fails=True`:
      a `SimResult` namedtuple (trace, value, stdout, sim_fails, stdout_tail).
      Never raises `CalledProcessError`/`OSError`/`TimeoutExpired` on a
      simulator-level failure; every one becomes a `sim_fails` entry instead.
    """
    if absolute:
        workdir = os.path.abspath(workdir)
        sv_file = os.path.abspath(sv_file)
        extra_sources = [os.path.abspath(s) for s in extra_sources]

    vvp = os.path.join(workdir, out_name)

    if report_sim_fails:
        return _compile_and_run_reporting(
            sv_file, workdir, vvp, extra_sources=extra_sources,
            compile_in_workdir=compile_in_workdir,
            quiet_compile=quiet_compile, direct_exec=direct_exec,
            out_name=out_name, run_by_name=run_by_name,
            stdout_path=stdout_path, done_prefix=done_prefix,
            trace_name=trace_name, stimulus_files=stimulus_files,
            timeout=timeout)

    compile_kwargs = {}
    if compile_in_workdir:
        compile_kwargs["cwd"] = workdir
    if quiet_compile:
        compile_kwargs["stdout"] = subprocess.DEVNULL
        compile_kwargs["stderr"] = subprocess.DEVNULL
    subprocess.run(["iverilog", "-g2012", "-o", vvp, sv_file,
                    *extra_sources], check=True, **compile_kwargs)

    image = out_name if run_by_name else vvp
    cmd = [image] if direct_exec else ["vvp", image]

    capture = capture_output or done_prefix is not None
    if capture:
        result = subprocess.run(cmd, cwd=workdir, check=True,
                                capture_output=True, text=True)
    elif stdout_path is not None:
        with open(stdout_path, "w") as log:
            result = subprocess.run(cmd, cwd=workdir, check=True, stdout=log)
    elif suppress_stdout:
        result = subprocess.run(cmd, cwd=workdir, check=True,
                                stdout=subprocess.DEVNULL)
    else:
        result = subprocess.run(cmd, cwd=workdir, check=True)

    trace = None if trace_name is None else os.path.join(workdir, trace_name)

    if done_prefix is not None:
        value = None
        for line in result.stdout.splitlines():
            if line.startswith(done_prefix):
                value = int(line.split("=")[1])
        return trace, value
    if capture_output:
        return trace, result.stdout
    return trace


def _compile_and_run_reporting(sv_file, workdir, vvp, *, extra_sources,
                               compile_in_workdir, quiet_compile,
                               direct_exec, out_name, run_by_name,
                               stdout_path, done_prefix, trace_name,
                               stimulus_files, timeout):
    """`report_sim_fails=True` path: never raises; always returns SimResult.

    Mirrors `compare_wt_rtl_model.py`'s `compile_and_run_sim` (issue #188),
    generalized to this module's compile/run axes.
    """
    sim_fails = []

    # ---- mechanism 1: declared inputs, checked BEFORE the simulator runs --
    missing = [rel for rel in stimulus_files
              if not os.path.exists(os.path.join(workdir, rel))]
    if missing:
        for rel in missing:
            sim_fails.append(
                "missing declared input: %s (absent from the run dir; the "
                "testbench $readmemh's this stimulus and Icarus reports an "
                "open failure on stdout while still exiting 0, so this is "
                "asserted before the simulator is invoked)" % rel)
        return SimResult(None, None, "", sim_fails, "")

    compile_kwargs = {}
    if compile_in_workdir:
        compile_kwargs["cwd"] = workdir
    if quiet_compile:
        compile_kwargs["stdout"] = subprocess.DEVNULL
        compile_kwargs["stderr"] = subprocess.DEVNULL
    # ---- mechanism 4a: a failed/unrunnable compile is a recorded reason,
    # not a traceback that leaves the caller with no verdict at all.
    try:
        subprocess.run(["iverilog", "-g2012", "-o", vvp, sv_file,
                        *extra_sources], check=True, **compile_kwargs)
    except subprocess.CalledProcessError as exc:
        # The compile's streams are inherited by default (visible live)
        # unless quiet_compile sent them to DEVNULL; either way exc.stderr is
        # None here (never captured), so say so rather than printing an
        # empty field that reads like "no reason given".
        detail = (_as_text(exc.stderr)[-500:]
                  or "(compiler diagnostics went to this harness's own "
                     "stdout/stderr; the compile step is not captured)")
        sim_fails.append("iverilog compile failed rc=%s: %s"
                         % (exc.returncode, detail))
        return SimResult(None, None, "", sim_fails, "")
    except OSError as exc:
        sim_fails.append("iverilog could not be executed: %s" % exc)
        return SimResult(None, None, "", sim_fails, "")

    image = out_name if run_by_name else vvp
    cmd = [image] if direct_exec else ["vvp", image]

    # ---- mechanism 5 (issue #360), part 1: invocation-owned trace. The
    # helper-owned expected trace under the run dir is invalidated BEFORE
    # the simulator launches, so the only file that can exist at that path
    # afterward is one THIS invocation wrote. A reused run dir holding a
    # previous run's trace can otherwise satisfy a testbench that exits 0
    # without writing anything. Ownership, not timestamps: an mtime
    # comparison depends on clock/filesystem resolution. Scoped to the
    # declared `trace_name` inside `workdir` only; `trace_name=None` declares
    # no trace output and is exempt, and an explicitly supplied offline trace
    # (e.g. compare_sine_rtl_model.py --trace) never reaches this function.
    trace = None
    if trace_name is not None:
        trace = os.path.join(workdir, trace_name)
        owned_root = os.path.realpath(workdir)
        if os.path.commonpath([owned_root, os.path.realpath(trace)]) \
                != owned_root:
            sim_fails.append(
                "refusing trace_name %r: it resolves outside the run dir %s, "
                "so it is not a helper-owned output this invocation may "
                "invalidate" % (trace_name, workdir))
            return SimResult(None, None, "", sim_fails, "")
        try:
            os.remove(trace)
        except FileNotFoundError:
            pass
        except OSError as exc:
            sim_fails.append(
                "could not invalidate the prior trace %s before the "
                "simulator ran (%s); a file left there could not be told "
                "apart from this invocation's output" % (trace_name, exc))
            return SimResult(None, None, "", sim_fails, "")

    # Stdout is ALWAYS captured here (regardless of suppress_stdout /
    # capture_output) so mechanism 2 can scan it; `stdout_path` is honored
    # afterward as a side-effect write, same content it would have received.
    try:
        result = subprocess.run(cmd, cwd=workdir, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout_tail = _as_text(exc.stdout)[-2000:]
        sim_fails.append(
            "vvp exceeded the %gs timeout and was killed (the simulation "
            "never completed, so no trace it left can be trusted) stdout=%s"
            % (timeout, stdout_tail[-500:]))
        return SimResult(None, None, stdout_tail, sim_fails, stdout_tail)
    except OSError as exc:
        sim_fails.append("vvp could not be executed: %s" % exc)
        return SimResult(None, None, "", sim_fails, "")

    if stdout_path is not None:
        with open(stdout_path, "w") as log:
            log.write(result.stdout)

    # ---- mechanism 3: non-zero exit ----
    if result.returncode != 0:
        sim_fails.append("vvp exited rc=%d stderr=%s"
                         % (result.returncode, _as_text(result.stderr)[-500:]))
    # ---- mechanism 2: $readmemh open failure on STDOUT, with rc=0 ----
    for line in scan_stdout_for_load_failures(result.stdout):
        sim_fails.append("vvp rc=%d but a stimulus file never loaded: %s"
                         % (result.returncode, line))
    # ---- mechanism 5 (issue #360), part 2: a clean run must have produced
    # the declared trace. Only checked when nothing above already failed, so
    # an earlier, more specific reason is not buried under this one.
    if not sim_fails and trace is not None and not os.path.isfile(trace):
        sim_fails.append(
            "missing current-run output: %s (vvp rc=%d but this invocation "
            "wrote no trace at the expected path; any prior trace there was "
            "invalidated before the simulator ran, so nothing is compared)"
            % (trace_name, result.returncode))
        trace = None

    stdout_tail = _as_text(result.stdout)[-2000:] if sim_fails else ""

    value = None
    if done_prefix is not None:
        for line in result.stdout.splitlines():
            if line.startswith(done_prefix):
                value = int(line.split("=")[1])

    return SimResult(trace, value, result.stdout, sim_fails, stdout_tail)


def run_leaf_comparison(*, tb, tb_label, run_dir, out, parse_tb, compare,
                        compile_kwargs, default_checked,
                        extra_summary_fields=None, summary_key_order=None,
                        validate_model=None):
    """The report-assembly skeleton shared by five RTL-vs-model leaves.

    Extracted by issue #303 from the byte-identical halves of
    `compare_rtl_model.py`, `compare_classic_rtl_model.py`,
    `compare_kt_rtl_model.py`, `compare_lfo_rtl_model.py` and
    `compare_mw_rtl_model.py`.  Every axis those five actually differed on is
    a parameter here, so each call site keeps its *exact* previous JSON
    (same keys, same key order, same values) and exit code.  Nothing is
    normalized: a leaf whose report shape differs keeps the difference by
    passing it in.

    Parameters:
      tb            testbench source to compile (the leaf's `--tb` value)
      tb_label      the literal string reported as `summary["tb"]`; leaves
                    disagree here on purpose (`os.path.basename(tb)` for the
                    SXT-022 voice leaf, `os.path.relpath(tb, REPO)` for the
                    other four) and this helper does not pick for them
      run_dir       run directory holding `model_trace.json`; also the
                    simulation's cwd
      out           path to write the summary JSON to, or None/"" for
                    stdout only (the leaf's `--out`)
      parse_tb      callable(trace_path) -> the leaf's own RTL trace object
      compare       callable(model_trace, rtl_trace) -> (checked, fails)
      compile_kwargs  dict of `compile_and_run` keyword arguments
                    (`out_name`, `trace_name`, `done_prefix`, `direct_exec`,
                    `stimulus_files`, ...).  `report_sim_fails=True` is
                    supplied by this helper and must NOT appear here: the
                    `comparison: NOT_RUN` branch below exists precisely
                    because a simulator-level failure is not a
                    RTL-vs-model disagreement (issues #188/#193), and that
                    branch needs a `SimResult`.
      default_checked  the leaf's zeroed `checked` dict, reported verbatim
                    when a simulator-level failure means `compare` never
                    ran (`comparison: NOT_RUN`).  Its shape and key order
                    are the leaf's, not this helper's.
      extra_summary_fields  optional callable(model_trace, sim) -> dict of
                    additional summary keys (only the keytrack leaf uses
                    this: `sequence`, `control_mode`, `rtl_qmuls`, `blocks`)
      summary_key_order  optional sequence naming the exact output key
                    order.  Required with `extra_summary_fields` whenever
                    the leaf's committed report interleaves its extra keys
                    among the base ones rather than appending them (the
                    keytrack leaf does).  Must name exactly the merged key
                    set -- a mismatch raises `ValueError` rather than
                    silently dropping or reordering a reported field.

      validate_model  optional callable(model_trace) raising `LeafInputError`
                    for leaf-specific structure beyond the shared minimum.

    Input failures (issue #361): an unreadable/malformed/mis-shaped
    `model_trace.json` is refused BEFORE the simulator launches; an absent
    or unparseable RTL trace is refused before `compare`.  Both publish
    `comparison: NOT_RUN`, the leaf's zeroed `checked`, an `input_error`
    object, and exit 1 -- never a numeric verdict.  A prior verdict at `out`
    is removed first, so it cannot outlive a failing invocation; if `out`
    cannot be invalidated/written the exit is 1 with an stderr message.

    Returns the process exit code: 0 when nothing failed, else 1.
    """
    if "report_sim_fails" in compile_kwargs:
        raise ValueError("run_leaf_comparison supplies report_sim_fails=True "
                         "itself; the NOT_RUN branch requires a SimResult")

    # ---- issue #361: input-refusal reporting boundary ----
    # A previously published verdict at the requested path must never survive
    # this invocation, so it is invalidated BEFORE any input is touched.
    publish_error = None
    if out:
        try:
            os.remove(out)
        except FileNotFoundError:
            pass
        except OSError as exc:
            publish_error = ("could not invalidate the prior verdict at %s "
                             "(%s)" % (out, exc))

    model_path = os.path.join(run_dir, "model_trace.json")
    try:
        model_trace = _load_model_trace(model_path)
        if validate_model is not None:
            validate_model(model_trace)
    except LeafInputError as exc:
        return _publish_refusal(exc, tb_label, default_checked, out,
                                publish_error, extra_summary_fields,
                                summary_key_order)

    sim = compile_and_run(tb, run_dir, report_sim_fails=True, **compile_kwargs)

    checked = dict(default_checked)
    fails = list(sim.sim_fails)
    comparison = "NOT_RUN"
    if not sim.sim_fails:
        try:
            rtl_trace = _parse_rtl_trace(parse_tb, sim.trace)
        except LeafInputError as exc:
            return _publish_refusal(exc, tb_label, default_checked, out,
                                    publish_error, extra_summary_fields,
                                    summary_key_order, model_trace, sim)
        checked, cmp_fails = compare(model_trace, rtl_trace)
        fails += cmp_fails
        comparison = "FAIL" if cmp_fails else "PASS"

    summary = {
        "tb": tb_label,
        "verdict": "PASS" if not fails else "FAIL",
        "comparison": comparison,
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
        "sim_fails": sim.sim_fails,
        "sim_stdout_tail": sim.stdout_tail,
    }
    if extra_summary_fields is not None:
        summary.update(extra_summary_fields(model_trace, sim))
    if summary_key_order is not None:
        order = list(summary_key_order)
        if sorted(order) != sorted(summary) or len(order) != len(set(order)):
            raise ValueError(
                "summary_key_order %r does not name exactly the summary keys "
                "%r" % (order, sorted(summary)))
        summary = {k: summary[k] for k in order}

    return _emit_summary(summary, out, publish_error, fails)


class LeafInputError(Exception):
    """An expected input failure (unreadable/malformed model or RTL trace).

    Carries which input failed and why.  Only raised at the explicit input
    boundaries below; programmer defects (TypeError/KeyError/AttributeError
    in a leaf's own code) are deliberately NOT converted into this.
    """

    def __init__(self, which, path, reason):
        super().__init__("%s %s: %s" % (which, path, reason))
        self.which = which
        self.path = path
        self.reason = reason


def _load_model_trace(path):
    """Read and minimally structure-check the frozen model trace.

    Structure required by all five adopted leaves: a JSON object whose
    `blocks` is a non-empty list of objects, each with an integer `b` and a
    `voices` list of objects carrying `slot`.  Anything deeper stays the
    leaf's `compare` contract; JSON syntax alone is not accepted as a model.
    """
    try:
        with open(path) as f:
            model = json.load(f)
    except OSError as exc:
        raise LeafInputError("model", path, "unreadable: %s" % exc)
    except ValueError as exc:   # JSONDecodeError and UnicodeDecodeError
        raise LeafInputError("model", path, "invalid JSON: %s" % exc)
    if not isinstance(model, dict):
        raise LeafInputError("model", path, "top level is not a JSON object")
    blocks = model.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise LeafInputError("model", path,
                             "`blocks` is missing, not a list, or empty")
    for n, blk in enumerate(blocks):
        if not isinstance(blk, dict) or isinstance(blk.get("b"), bool) \
                or not isinstance(blk.get("b"), int):
            raise LeafInputError("model", path,
                                 "blocks[%d] lacks an integer `b`" % n)
        voices = blk.get("voices")
        if not isinstance(voices, list) or not all(
                isinstance(v, dict) and "slot" in v for v in voices):
            raise LeafInputError(
                "model", path,
                "blocks[%d].voices is not a list of objects with `slot`" % n)
    return model


def _parse_rtl_trace(parse_tb, trace):
    """Run the leaf's parser; data-shaped failures become input refusals."""
    if trace is None:
        raise LeafInputError("rtl_trace", trace, "no trace path was produced")
    try:
        return parse_tb(trace)
    except FileNotFoundError:
        raise LeafInputError("rtl_trace", trace, "trace file is absent")
    except OSError as exc:
        raise LeafInputError("rtl_trace", trace, "unreadable: %s" % exc)
    except (ValueError, IndexError) as exc:
        # int()/float() token errors, undecodable bytes, truncated rows
        raise LeafInputError("rtl_trace", trace,
                             "malformed trace (%s: %s)"
                             % (type(exc).__name__, exc))


def _publish_refusal(exc, tb_label, default_checked, out, publish_error,
                     extra_summary_fields, summary_key_order,
                     model_trace=None, sim=None):
    """Current non-PASS report: comparison NOT_RUN, the leaf's zeroed
    coverage, and the offending input.  `sim_fails` stays empty -- the
    simulator did not fail, an input did."""
    reason = "input refusal: %s" % exc
    summary = {
        "tb": tb_label,
        "verdict": "FAIL",
        "comparison": "NOT_RUN",
        "checked": dict(default_checked),
        "mismatches": 1,
        "first_failures": [reason],
        "sim_fails": list(sim.sim_fails) if sim is not None else [],
        "sim_stdout_tail": sim.stdout_tail if sim is not None else "",
    }
    if summary_key_order is not None:
        # Leaf-specific extras are not derived from an unusable model or
        # trace (that would index it a second time, or fabricate values);
        # their keys are reported as null in the leaf's own order.
        for k in summary_key_order:
            summary.setdefault(k, None)
        summary = {k: summary[k] for k in summary_key_order}
    summary["input_error"] = {"input": exc.which, "path": exc.path,
                              "reason": exc.reason}
    _emit_summary(summary, out, publish_error, [reason])
    return 1


def _emit_summary(summary, out, publish_error, fails):
    print(json.dumps(summary, indent=2))
    if out and publish_error is None:
        try:
            with open(out, "w") as f:
                json.dump(summary, f, indent=2)
                f.write("\n")
        except OSError as exc:
            publish_error = "could not write the verdict to %s (%s)" % (out,
                                                                        exc)
    if publish_error is not None:
        print("ERROR: no current verdict was published: %s" % publish_error,
              file=sys.stderr)
        return 1
    return 0 if not fails else 1
