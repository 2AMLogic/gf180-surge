#!/usr/bin/env python3
"""SXT-043 exactness harness: pm_mono_st_fp articulation RTL trace vs the
frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL), at every declared
pool slot of every block: active flag, gate, uberrelease, key, the amp
envelope state machine (state/phase/output/scalestage), the SLOW_EXP
velocity smoother (value/target), the keytrack word, and the full
portamento state (phase/portasrc_key/pkey/priorpkey/doretrigger) -- the
articulation-layer checkpoint declared in
`model/voice/playmode/run_model.py`'s DECLARED MODEL / RTL BOUNDARY section.
It does NOT check the audio datapath (unchanged `tb_voice.sv`, checked
separately).

Mirrors tools/compare_vel_rtl_model.py (same verdict JSON schema, same
exit-code convention) for rtl/voice/tb_pm_mono_st_fp.sv.

SIMULATOR-LEVEL FAILURES ARE NOT COMPARISON DISAGREEMENTS (issues #188,
#193). This leaf carried a private `build_and_run()` + report skeleton
until issue #645 moved it onto `_rtl_compile_common.run_leaf_comparison`;
#631 had deferred it because its model trace carries `blocks[].slots`
(per-slot field lists) instead of the `blocks[].voices` the shared minimum
required, and relaxing that check for every leaf was #631's stop condition.
#645's shape opt-in (`model_block_shape="slots"`) leaves the six `voices`
leaves' refusal untouched and gives this leaf its own symmetric guard.
Measured before that move, on Icarus 13.0 against a run dir built by
`model/voice/playmode/run_model.py --inputs
model/voice/playmode/inputs/bass2.json --sequence seq-notes-holds-v1`:

  * `rtl/ev.hex` removed -> Icarus reports the open failure on stdout and
    still exits 0, so `check=True` saw nothing; the (near-empty) trace was
    parsed and the harness published a NUMERIC disagreement verdict --
    `"FAIL", "mismatches": 42` with `rtl_done_line: "DONE pm-qmuls=0
    voice-blocks=0"` -- on a run where nothing was compared (#188's blind
    spot). The shared path asserts the declared stimulus before the
    simulator is invoked and publishes `comparison: NOT_RUN` naming the
    file instead.
  * an uncompilable `--tb` with a `{"verdict": "PASS", "mismatches": 0}`
    already at `--out` -> CalledProcessError traceback, exit 1, and that
    stale PASS left in place byte-for-byte, with the compiler's own
    diagnostic discarded (`subprocess.DEVNULL`). The shared path
    invalidates a prior verdict at `--out` before it touches an input
    (issue #361) and records the compile failure with `comparison:
    NOT_RUN` instead.

FALSE-POSITIVE BASELINE for the stdout matcher (mechanism 2), measured for
THIS testbench on Icarus 13.0 as issue #193's per-harness rule requires: a
healthy `tb_pm_mono_st_fp.sv` run prints two `$readmemh(...): Not enough
words...` WARNINGs (this repo's hex fixtures are deliberately shorter than
the testbench's declared ranges), `DONE pm-qmuls=... voice-blocks=...` and
`$finish` -- never the `$readmem` + `Unable to open` conjunction the
matcher requires, so it cannot turn a genuinely passing exactness run into
a FAIL.

Usage:
  python3 tools/compare_pm_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_pm_mono_st_fp.sv]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import CheckpointKeys, run_leaf_comparison  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_pm_mono_st_fp.sv")

# The hex stimulus tb_pm_mono_st_fp.sv `$readmemh`s (lines 249-250),
# relative to the run dir: issue #193's mechanism-1 pre-flight axis,
# declared here so the check can never drift from what the testbench
# actually reads. Generated into the run dir by
# model/voice/playmode/run_model.py; not tracked.
STIMULUS_RELPATHS = ("rtl/init.hex", "rtl/ev.hex")

FIELD_NAMES = ["active"] + [
    "gate", "uberrelease", "key",
    "aeg_state", "aeg_phase_q29", "aeg_output_q21", "aeg_scalestage_q21",
    "vel_value_q21", "vel_target_q21", "kt_word_q21",
    "portaphase_q29", "portasrc_key_q21", "pkey_q21", "priorpkey_q21",
    "porta_doretrigger",
]


def _int(x):
    # an unresolved RTL value (x/z) can never equal a model word
    try:
        return int(x)
    except ValueError:
        return None


def parse_tb(path):
    """Parse the RTL trace.  Every T key must be unique (issues #455/#639):
    a repeated voice checkpoint -- identical or contradictory, in either
    order -- is refused with LeafInputError rather than resolved
    last-row-wins."""
    t = {}   # (block, slot) -> [active, gate, uberrelease, key, ...] (16 words)
    keys = CheckpointKeys()
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p or p[0] != "T":
                continue
            b, slot = int(p[1]), int(p[2])
            keys.put(t, "T", (b, slot),
                     [_int(x) for x in p[3:3 + len(FIELD_NAMES)]])
    keys.raise_if_duplicates(path)
    return t


def compare(model_trace, tb_trace):
    """The leaf's own judgement, unchanged by #645: returns
    `(checked, fails, pool)` and is imported directly by
    tests/test_sxt043_playmode.py."""
    fails = []
    checked = {"block_slot_checkpoints": 0, "fields": 0}
    pool = model_trace.get("pool")
    seen = set()
    for blk in model_trace["blocks"]:
        b = blk["b"]
        for slot, rec in enumerate(blk["slots"]):
            key = (b, slot)
            seen.add(key)
            got = tb_trace.get(key)
            if got is None:
                fails.append(f"block {b} slot {slot}: missing T line")
                continue
            checked["block_slot_checkpoints"] += 1
            if len(got) != len(rec):
                fails.append(f"block {b} slot {slot}: field count "
                             f"model={len(rec)} rtl={len(got)}")
                continue
            for j, want in enumerate(rec):
                checked["fields"] += 1
                if got[j] != want:
                    name = FIELD_NAMES[j] if j < len(FIELD_NAMES) else f"f{j}"
                    fails.append(f"block {b} slot {slot} {name}: "
                                 f"model={want} rtl={got[j]}")
        if len(fails) > 40:
            return checked, fails, pool
    extra = sorted(set(tb_trace) - seen)
    for key in extra[:10]:
        fails.append(f"block {key[0]} slot {key[1]}: RTL line with no model record")
    return checked, fails, pool


def _compare(model_trace, tb_trace):
    """Adapt `compare`'s `(checked, fails, pool)` to the helper's
    `(checked, fails)`; `pool` is re-reported through
    `extra_summary_fields` from the same model trace."""
    checked, fails, _pool = compare(model_trace, tb_trace)
    return checked, fails


# This leaf reports `carrier` / `sequence` / `pool` after `tb` and
# `rtl_done_line` after `first_failures`, interleaved among the shared keys
# rather than appended (reports/SXT-043/artifacts/exactness-*.json).
# SUMMARY_KEY_ORDER pins that published order so the shared report-assembly
# helper cannot silently re-order committed evidence; it is checked against
# the actual key set on every run (ValueError on drift). `comparison`,
# `sim_fails` and `sim_stdout_tail` are additive.
SUMMARY_KEY_ORDER = ("tb", "carrier", "sequence", "pool", "verdict",
                     "comparison", "checked", "mismatches", "first_failures",
                     "rtl_done_line", "sim_fails", "sim_stdout_tail")


def extra_summary_fields(model_trace, sim):
    """The four pm-only summary fields (see SUMMARY_KEY_ORDER).

    `rtl_done_line` is the full `DONE ...` string, not a count, so it is
    read off the captured stdout rather than through `compile_and_run`'s
    `done_prefix` (which returns an int and would change the field's type).
    A simulator-level failure leaves stdout empty or DONE-less, which
    reports "" exactly as the private copy did when no DONE line appeared.
    """
    done = [ln for ln in sim.stdout.splitlines() if ln.startswith("DONE")]
    return {
        "carrier": model_trace.get("carrier"),
        "sequence": model_trace.get("sequence"),
        "pool": model_trace.get("pool"),
        "rtl_done_line": done[-1] if done else "",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/{init,ev}.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    return run_leaf_comparison(
        tb=args.tb, tb_label=os.path.relpath(os.path.abspath(args.tb), REPO),
        run_dir=args.run_dir, out=args.out,
        parse_tb=parse_tb, compare=_compare,
        model_block_shape="slots",
        compile_kwargs=dict(
            out_name="tb_pm_mono_st_fp.vvp", absolute=True,
            compile_in_workdir=True, quiet_compile=True,
            trace_name="tb_pm_trace.txt", stimulus_files=STIMULUS_RELPATHS),
        default_checked={"block_slot_checkpoints": 0, "fields": 0},
        extra_summary_fields=extra_summary_fields,
        summary_key_order=SUMMARY_KEY_ORDER)


if __name__ == "__main__":
    sys.exit(main())
