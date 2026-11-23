#!/usr/bin/env python3
"""Regenerate the T1 item-1 synthesis evidence (#537), one group at a time.

Writes signoff/t1-item1/<group>/request.json from rtl/lint_manifest.json,
runs `klt synthesize` (sequential, single-threaded), and keeps only the
commit-safe artifacts: request, report.json, netlist, synth_<top>.ys. On a
non-zero exit it also distils the Yosys log klt writes beside the executed
script into `timeout-progress.txt`, so a timeout record can state the cell
count and the passes reached instead of only the error message (#579). The
`failure.txt` error payload klt wrote is run through the same path
substitution (#714). The
raw log is not commit-safe (machine-local absolute paths, and hundreds of
thousands of suppressed debug lines), for the same reason `synth_<top>.run.ys`
is not; the excerpt keeps the load-bearing lines with paths substituted.
Synthesizability evidence only: no P&R, timing, signoff or equivalence claim.

`klt` is taken from $KLT (shlex-split, e.g. a pinned
`uvx --from "git+...@<rev>" klt`) and defaults to the host `klt`. A group in
YOSYS_TIMEOUT_S requests that Yosys budget via `yosys_timeout_s`, which only a
klt carrying 2AMLogic/klayout-tools#5412 accepts -- an older klt rejects the
unknown field rather than silently synthesizing at its fixed 300 s default.
"""
import contextlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "signoff" / "t1-item1"
PDK = "gf180mcuD"
CELL_LIBRARY = "gf180mcu_fd_sc_mcu9t5v0"
# Groups the native Yosys front end cannot read (unpacked-array ports, $fatal)
# go through klt's pinned sv2v route (operator ruling r6-q23, sv2v 0.0.13).
# The three groups that pass natively keep the native route.
NATIVE_GROUPS = {"control_top", "ext_mem_instr", "wavetable_core"}
# Per-group Yosys wall-clock budget (request `yosys_timeout_s`, klt cap 3600 s).
# Omitted groups keep klt's fixed 300 s default. galactic_core needs more:
# `synth` reaches ~272k generic cells and its generic `abc` pass alone runs
# well past 300 s (#579, decision of 2026-11-13). Why it is that expensive is
# NOT established by any run here -- see #641 for the suspected, unverified
# cause; do not restate one as fact in this file.
#
# The five #580 groups below need more than 300 s because exposing the result
# ports made their datapath observable. 1800 s is NOT known to be sufficient
# for them: all five were measured at that budget and all five were still
# killed inside the same Yosys step (see RECORD.md). The figure is kept at the
# measured one so the committed failure records are reproducible, not because
# it is a requirement. Raising it further is not the next step -- klt's cap is
# 3600 s, only 2x what already failed; see RECORD.md and #579/#641/#657 for
# why a budget argument is exhausted here.
#
# rf_ains34_core is deliberately NOT in this table: it keeps the 300 s default
# because it exits 0 there -- but only because its own inputs are not ports,
# so Yosys constant-folds its datapath away (RECORD.md "rf_ains34_core").
YOSYS_TIMEOUT_S = {
    "galactic_core": 1800,
    "logical4_core": 1800,
    "rf_bins12_core": 1800,
    "rf_global2_core": 1800,
    "rf_global34_core": 1800,
    "rf_send34_core": 1800,
}
# The klt to run; override for a pinned/throwaway environment (never install
# over the host-wide klt). NOTE: a klt without `yosys_timeout_s` support
# rejects a request that declares it, and this script then records that
# rejection in failure.txt -- overwriting a real timeout record. Re-run a
# group in YOSYS_TIMEOUT_S only under a klt that carries the field (the
# reproduce line in that group's RECORD.md names it).
KLT = shlex.split(os.environ.get("KLT", "klt"))

# The yosys-abc handshake wedge (klayout-tools#5780, measured against this
# repo in #802): Yosys drives `yosys-abc -s` over a pipe and waits for abc to
# echo its `source <script>` line; once `len(TMPDIR) + 43` reaches the 79
# column default, readline wraps that echo, the match never fires and both
# processes sit idle until the caller's budget kills them -- the last log
# line is then forever `4.22.1 Extracting gate netlist ...`. Guard every
# klt invocation: pin a wide COLUMNS and, when the ambient TMPDIR is 36
# characters or longer, substitute a private per-invocation short scratch
# directory under /tmp (mode 0700, 17 chars) so distinct Unix accounts and
# concurrent callers each get writable scratch without colliding on a shared
# fixed path. Belt-and-braces only -- the upstream fix (klayout-tools#5975,
# closing #5780) sets `COLUMNS=4096` in klt's Python launcher when it spawns
# Yosys (post-0.9.2; see RECORD.md § "#802").
TMPDIR_MAX_LEN = 35


@contextlib.contextmanager
def guarded_klt_env(base_env=None):
    """Build a child env for `klt synthesize` with the #802 wedge guard.

    Always sets COLUMNS=1000. When ambient TMPDIR is 36 characters or longer,
    creates a private per-invocation short directory under /tmp (mode 0700)
    so every caller account gets writable scratch, and removes it on exit.
    """
    env = dict(os.environ if base_env is None else base_env)
    env["COLUMNS"] = "1000"
    short_tmp = None
    if len(env.get("TMPDIR", "")) > TMPDIR_MAX_LEN:
        short_tmp = tempfile.mkdtemp(prefix="klt-", dir="/tmp")
        env["TMPDIR"] = short_tmp
    try:
        yield env
    finally:
        if short_tmp is not None:
            shutil.rmtree(short_tmp, ignore_errors=True)


#: Lines kept by :func:`distil_log`: every numbered Yosys step header (so the
#: last step reached is visible, including a sub-step like "Extracting gate
#: netlist ... to input.blif" that a timeout dies inside) and every line that
#: quantifies the design (cell/wire counts, dedup and cleanup totals) or
#: reports a structural obstacle (unsortable cells, ABC loop breaking).
KEEP_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.\s+\S"
    r"|Computing hashes of \d+ cells\b"
    r"|Removed (?:a total of )?\d+ (?:unused )?cells\b"
    r"|Replacing \d+ occurrences\b"
    r"|Breaking loop using new signal\b"
    r"|Couldn't topologically sort cells\b"
    r"|<suppressed [~\d]+ debug messages>"
    r"|\[std(?:out|err)\]$)"
)


def neutral_paths(text):
    """Machine-neutral form of a payload: ROOT -> <repo>, then home -> <home>.

    ROOT is substituted first: it sits under home, so the home replacement
    only fires on a path elsewhere under home. One shared helper for the
    distil_log() excerpt and the failure.txt payload (#714), so a re-run
    from any worktree reproduces both committed records byte for byte.
    """
    return text.replace(str(ROOT), "<repo>").replace(str(pathlib.Path.home()), "<home>")


def distil_log(text):
    """Commit-safe excerpt of a Yosys log: kept lines, paths substituted.

    Deterministic (same log -> same excerpt), so re-running regen.py
    reproduces the committed artifact byte for byte.
    """
    out_lines, dropped = [], 0
    for line in text.splitlines():
        if KEEP_RE.match(line):
            if dropped:
                out_lines.append(f"[... {dropped} line(s) omitted ...]")
                dropped = 0
            out_lines.append(neutral_paths(line))
        else:
            dropped += 1
    if dropped:
        out_lines.append(f"[... {dropped} line(s) omitted ...]")
    return (
        "# Excerpt of the Yosys log klt wrote beside the executed script\n"
        "# (<repo>/signoff/t1-item1/<group>/out/synth_<top>.run.log, removed with\n"
        "# the scratch directory). Produced by signoff/t1-item1/regen.py's\n"
        "# distil_log(): Yosys pass headers plus every line that quantifies the\n"
        "# design or names a structural obstacle; absolute paths substituted\n"
        "# (<repo>, <home>) so the artifact is commit-safe and machine-neutral.\n"
        "# Progress evidence for a non-zero exit -- NOT a verdict.\n\n"
        + "\n".join(out_lines)
        + "\n"
    )


def main(only):
    manifest = json.loads((ROOT / "rtl" / "lint_manifest.json").read_text())
    with guarded_klt_env() as env:
        for g in manifest["groups"]:
            if only and g["id"] not in only:
                continue
            d = BASE / g["id"]
            d.mkdir(parents=True, exist_ok=True)
            out = d / "out"
            shutil.rmtree(out, ignore_errors=True)
            rel = "../../../" + g["source"]
            req = {
                "schema": "klt.synthesize.request/1",
                "engine": "yosys",
                "sources": [rel],
                "hdl_toplevel": g["top"],
                "pdk": {"cell_library": CELL_LIBRARY},
                "constraints": {"clock_period_ns": None},
                "outputs": {"dir": "out"},
            }
            if g["id"] not in NATIVE_GROUPS:
                req["sv_frontend"] = "sv2v"
                # sv2v does not define SYNTHESIS itself; the RTL guards its
                # simulation-only $fatal/string ROM init with `ifndef SYNTHESIS (#572).
                req["defines"] = {"SYNTHESIS": None}
            if g["id"] in YOSYS_TIMEOUT_S:
                req["yosys_timeout_s"] = YOSYS_TIMEOUT_S[g["id"]]
            (d / "request.json").write_text(json.dumps(req, indent=2) + "\n")
            p = subprocess.run(
                KLT + ["synthesize", str(d / "request.json"), "--pdk", PDK,
                       "--format", "json"],
                check=False, capture_output=True, text=True, cwd=ROOT, env=env)
            (d / "exit_status.txt").write_text(f"{p.returncode}\n")
            if p.returncode == 0:
                (d / "report.json").write_text(p.stdout)
                top = g["top"]
                shutil.copy(out / f"{top}_synth.v", d / f"{top}_synth.v")
                shutil.copy(out / f"synth_{top}.ys", d / f"synth_{top}.ys")
                # A success retires any excerpt an earlier timeout left here;
                # leaving it would present stale progress evidence beside a
                # verdict it does not belong to.
                (d / "timeout-progress.txt").unlink(missing_ok=True)
            else:
                (d / "failure.txt").write_text(neutral_paths(p.stdout + "\n" + p.stderr))
                # klt writes <script>.log beside the executed script even on a
                # timeout; distil it so the record can quote the progress reached.
                log = out / f"synth_{g['top']}.run.log"
                if log.is_file():
                    (d / "timeout-progress.txt").write_text(
                        distil_log(log.read_text(errors="replace")))
            shutil.rmtree(out, ignore_errors=True)
            print(g["id"], p.returncode, flush=True)


if __name__ == "__main__":
    main(set(sys.argv[1:]))
