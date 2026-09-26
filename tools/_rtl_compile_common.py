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

This is a build/run helper only.  It parses no traces, compares no fields and
makes no verdict: claim (1) — "the RTL matches the frozen fixed-point model
exactly" — is still decided entirely by each harness's own `parse_tb`/
`compare` logic, which this module does not touch.

Original to this repository (Apache-2.0).
"""

import os
import subprocess

__all__ = ["compile_and_run"]


def compile_and_run(sv_file, workdir, *, out_name, extra_sources=(),
                    absolute=False, compile_in_workdir=False,
                    quiet_compile=False, direct_exec=False, run_by_name=False,
                    suppress_stdout=True, stdout_path=None,
                    capture_output=False, done_prefix=None,
                    trace_name="tb_trace.txt"):
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

    Return:
      (trace, value)  when `done_prefix` is given (value may be None)
      (trace, stdout) when `capture_output` is given
      None            when `trace_name` is None
      trace           otherwise, i.e. os.path.join(workdir, trace_name)

    `check=True` throughout: a failing compile or simulation raises
    CalledProcessError rather than producing a silently empty trace.
    """
    if absolute:
        workdir = os.path.abspath(workdir)
        sv_file = os.path.abspath(sv_file)
        extra_sources = [os.path.abspath(s) for s in extra_sources]

    vvp = os.path.join(workdir, out_name)

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
