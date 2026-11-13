#!/usr/bin/env python3
"""SXT-036 exactness harness: velocity / release-velocity control-plane RTL
trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL), at every block
boundary of every voice slot that ran a control pass:
  * the per-instance source words (V lines: vel_q, relvel_q) against the
    model trace's per-voice `vel_words`,
  * the per-voice route sums (S lines: cutoff / reso / fegmod / vca sums of
    depth*source terms) against the model trace's `vel_route_sums`.
A model record with no RTL line (or vice versa) is a mismatch.

Mirrors tools/compare_mw_rtl_model.py (same verdict JSON schema, same
exit-code convention) for rtl/voice/tb_vel.sv. The audio datapath is checked
separately by tools/compare_rtl_model.py (tb_voice.sv, unchanged) against the
same run directory.

SIMULATOR-LEVEL FAILURES ARE NOT COMPARISON DISAGREEMENTS (issues #188,
#193). This leaf carried a private `build_and_run()` + report skeleton until
issue #631 moved it onto `_rtl_compile_common.run_leaf_comparison`, the
path five sibling leaves already shared; issue #303 had deferred it only for
lack of this analysis, not as a ruling that it stay separate. Measured
before that move, on Icarus 13.0 against a run dir built by
`model/voice/run_vel_model.py --sequence sxt036-vel-overlap-v1`:

  * `rtl/vel_ctrl.hex` removed -> `subprocess.CalledProcessError` traceback
    out of `build_and_run`, exit 1, and NO verdict JSON written at all.
  * an uncompilable `--tb` with a `{"verdict": "PASS", "mismatches": 0}`
    already at `--out` -> traceback, exit 1, and that stale PASS left in
    place, with the compiler's own diagnostic discarded
    (`subprocess.DEVNULL`).

Neither result says anything about RTL-vs-model agreement, yet
`tools/vel_negative_controls.py`, `tools/vel_declared_coverage.py` and
`tools/vel_param_corners.py` all shell out to this harness and read its JSON.
The shared path publishes `comparison: NOT_RUN` with a `sim_fails` entry
naming the reason instead, and invalidates a prior verdict at `--out` before
it touches an input (issue #361).

FALSE-POSITIVE BASELINE for the stdout matcher (mechanism 2), measured for
THIS testbench on Icarus 13.0 as issue #193's per-harness rule requires: a
healthy `tb_vel.sv` run prints two `$readmemh(...): Not enough words...`
WARNINGs (this repo's hex fixtures are deliberately shorter than the
testbench's declared ranges), `DONE vel-qmuls=17640`, an `OPS ...` line and
`$finish` -- never the `$readmem` + `Unable to open` conjunction the matcher
requires, so it cannot turn a genuinely passing exactness run into a FAIL.

Usage:
  python3 tools/compare_vel_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_vel.sv]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import run_leaf_comparison  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_vel.sv")

# The hex stimulus tb_vel.sv `$readmemh`s (lines 107-109), relative to the run
# dir: issue #193's mechanism-1 pre-flight axis, declared here so the check
# can never drift from what the testbench actually reads. Generated into the
# run dir by model/voice/run_vel_model.py; not tracked.
STIMULUS_RELPATHS = ("rtl/vel_init.hex", "rtl/vel_routes.hex",
                     "rtl/vel_ctrl.hex")


def _int(x):
    # an unresolved RTL value (x/z) can never equal a model word
    try:
        return int(x)
    except ValueError:
        return None


def parse_tb(path):
    s = {}   # (block, slot) -> [cut, reso, emod, vca]
    v = {}   # (block, slot) -> [vel_q, relvel_q]
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "S":
                s[(int(p[1]), int(p[2]))] = [_int(x) for x in p[3:7]]
            elif p[0] == "V":
                v[(int(p[1]), int(p[2]))] = [_int(x) for x in p[3:5]]
    return s, v


def compare(model_trace, tb_trace):
    fails = []
    checked = {"voice_block_checkpoints": 0, "source_words": 0,
               "route_sums": 0}
    ts, tv = tb_trace
    seen = set()
    for blk in model_trace["blocks"]:
        b = blk["b"]
        for rec in blk["voices"]:
            key = (b, rec["slot"])
            seen.add(key)
            got_v, got_s = tv.get(key), ts.get(key)
            if got_v is None or got_s is None:
                fails.append(f"block {b} slot {rec['slot']}: missing V/S line")
                continue
            checked["voice_block_checkpoints"] += 1
            for j, want in enumerate(rec["vel_words"]):
                checked["source_words"] += 1
                if got_v[j] != want:
                    fails.append(f"block {b} slot {rec['slot']} "
                                 f"{('vel_q', 'relvel_q')[j]}: model={want} "
                                 f"rtl={got_v[j]}")
            for j, want in enumerate(rec["vel_route_sums"]):
                checked["route_sums"] += 1
                if got_s[j] != want:
                    fails.append(f"block {b} slot {rec['slot']} "
                                 f"route_sum[{j}]: model={want} rtl={got_s[j]}")
        if len(fails) > 40:
            return checked, fails
    extra = sorted(set(ts) - seen)
    for key in extra[:10]:
        fails.append(f"block {key[0]} slot {key[1]}: RTL line with no model "
                     "record")
    return checked, fails


# This leaf reports `sequence` / `control_mode` after `tb` and `rtl_done_line`
# after `first_failures`, interleaved among the shared keys rather than
# appended (reports/SXT-036/artifacts/exactness-vel-*.json). SUMMARY_KEY_ORDER
# pins that published order so the shared report-assembly helper cannot
# silently re-order committed evidence; it is checked against the actual key
# set on every run (ValueError on drift). `comparison`, `sim_fails` and
# `sim_stdout_tail` are additive.
SUMMARY_KEY_ORDER = ("tb", "sequence", "control_mode", "verdict", "comparison",
                     "checked", "mismatches", "first_failures",
                     "rtl_done_line", "sim_fails", "sim_stdout_tail")


def extra_summary_fields(model_trace, sim):
    """The three vel-only summary fields (see SUMMARY_KEY_ORDER).

    `rtl_done_line` is the full `DONE ...` string, not a count, so it is read
    off the captured stdout rather than through `compile_and_run`'s
    `done_prefix` (which returns an int and would change the field's type).
    A simulator-level failure leaves stdout empty or DONE-less, which reports
    "" exactly as the private copy did when no DONE line appeared.
    """
    done = [ln for ln in sim.stdout.splitlines() if ln.startswith("DONE")]
    return {
        "sequence": model_trace.get("sequence"),
        "control_mode": model_trace.get("control_mode"),
        "rtl_done_line": done[-1] if done else "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/vel_*.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    return run_leaf_comparison(
        tb=args.tb, tb_label=os.path.relpath(os.path.abspath(args.tb), REPO),
        run_dir=args.run_dir, out=args.out,
        parse_tb=parse_tb, compare=compare,
        compile_kwargs=dict(
            out_name="tb_vel.vvp", absolute=True, compile_in_workdir=True,
            quiet_compile=True, trace_name="tb_vel_trace.txt",
            stimulus_files=STIMULUS_RELPATHS),
        default_checked={"voice_block_checkpoints": 0, "source_words": 0,
                         "route_sums": 0},
        extra_summary_fields=extra_summary_fields,
        summary_key_order=SUMMARY_KEY_ORDER)


if __name__ == "__main__":
    sys.exit(main())
