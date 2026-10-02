#!/usr/bin/env python3
"""SXT-042 exactness harness: keytrack control-plane RTL trace vs the frozen
model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL), for every running
voice at every block boundary:

  * `kt_word`      -- the ms_keytrack word the RTL derives from the streamed
                      key (the model asserts this equals the ctor word that
                      the declared post-pass refresh reproduces),
  * `kt_route_sums`-- per-destination sums of that voice's keytrack route
                      terms (cutoff / reso / feg-mod),
  * the localcopy words after the whole md-ordered voice-route pass
    (`mod_cutoff`, `mod_reso`, `mod_envmod`, `mod_vca_db`).

Mirrors tools/compare_mw_rtl_model.py (same verdict JSON schema, same exit
codes) for rtl/voice/tb_kt.sv.

SIMULATOR-LEVEL FAILURES ARE NOT COMPARISON DISAGREEMENTS (issues #188,
#193). tb_kt.sv `$readmemh`s three files (kt_init.hex, kt_routes.hex,
kt_ctrl.hex) from `rtl/` under the run dir. Measured on this leaf's own
testbench with real Icarus 13.0 (issue #207 evidence): with `rtl/kt_ctrl.hex`
absent, Icarus prints

  ERROR: .../rtl/voice/tb_kt.sv:93: $readmemh: Unable to open
         rtl/kt_ctrl.hex for reading.

on the simulation's STDOUT (this leaf's testbench then also hits a FATAL
"ctrl stream exhausted" and exits non-zero, but the missing-input check
below fires before the simulator is ever invoked, so that does not matter).
`check=True` alone cannot see mechanism 2, so such a run could still be
reported as a wall of RTL-vs-model mismatches if it ever raced ahead of the
non-zero exit. `_rtl_compile_common`'s `report_sim_fails=True` mode names
the file and sets `comparison: NOT_RUN` instead.

Usage:
  python3 tools/compare_kt_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_kt.sv]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import run_leaf_comparison  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_kt.sv")

# The hex stimulus tb_kt.sv `$readmemh`s, relative to the run dir (issue
# #193's pre-flight check axis; single source of truth so the check can
# never drift from what the testbench actually reads).
STIMULUS_RELPATHS = ("rtl/kt_init.hex", "rtl/kt_routes.hex",
                    "rtl/kt_ctrl.hex")

FIELDS = ["kt_word", "kt_cut_sum", "kt_reso_sum", "kt_fegmod_sum",
          "mod_cutoff", "mod_reso", "mod_envmod", "mod_vca_db"]


def parse_tb(path):
    rows = {}
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p or p[0] != "V":
                continue
            rows[(int(p[1]), int(p[2]))] = [int(x) for x in p[3:11]]
    return rows


def compare(model_trace, rtl_rows):
    fails = []
    checked = {"voice_checkpoints": 0, "fields": 0}
    for blk in model_trace["blocks"]:
        b = blk["b"]
        for rec in blk["voices"]:
            key = (b, rec["slot"])
            got = rtl_rows.get(key)
            if got is None:
                fails.append(f"block {b} slot {rec['slot']}: missing V line")
                continue
            want = [rec["kt_word"], *rec["kt_route_sums"], rec["mod_cutoff"],
                    rec["mod_reso"], rec["mod_envmod"], rec["mod_vca_db"]]
            checked["voice_checkpoints"] += 1
            for name, w, g in zip(FIELDS, want, got):
                checked["fields"] += 1
                if w != g:
                    fails.append(f"block {b} slot {rec['slot']} {name}: "
                                 f"model={w} rtl={g}")
        if len(fails) > 40:
            return checked, fails
    # every RTL row must be claimed by the model (no extra voices)
    model_keys = {(blk["b"], r["slot"]) for blk in model_trace["blocks"]
                  for r in blk["voices"]}
    extra = set(rtl_rows) - model_keys
    if extra:
        fails.append(f"{len(extra)} RTL voice rows absent from the model "
                     f"trace, first {sorted(extra)[:3]}")
    return checked, fails


# This leaf reports four fields the other RTL-vs-model leaves do not, and
# reports them INTERLEAVED among the shared ones (`sequence`/`control_mode`
# after `tb`, `rtl_qmuls`/`blocks` after `checked`) rather than appended.
# SUMMARY_KEY_ORDER pins that published order so a shared report-assembly
# helper cannot silently re-order this leaf's committed evidence; it is
# checked against the actual key set on every run (ValueError on drift).
SUMMARY_KEY_ORDER = ("tb", "sequence", "control_mode", "verdict",
                     "comparison", "checked", "rtl_qmuls", "blocks",
                     "mismatches", "first_failures", "sim_fails",
                     "sim_stdout_tail")


def extra_summary_fields(model_trace, sim):
    """The four keytrack-only summary fields (see SUMMARY_KEY_ORDER)."""
    return {
        "sequence": model_trace.get("sequence"),
        "control_mode": model_trace.get("control_mode"),
        "rtl_qmuls": sim.value,
        "blocks": len(model_trace["blocks"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/*.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    return run_leaf_comparison(
        tb=args.tb, tb_label=os.path.relpath(args.tb, REPO),
        run_dir=args.run_dir, out=args.out,
        parse_tb=parse_tb, compare=compare,
        compile_kwargs=dict(
            out_name="tb_kt.vvp", absolute=True, compile_in_workdir=True,
            quiet_compile=True, done_prefix="DONE kt-qmuls=",
            trace_name="tb_kt_trace.txt",
            stimulus_files=STIMULUS_RELPATHS),
        default_checked={"voice_checkpoints": 0, "fields": 0},
        extra_summary_fields=extra_summary_fields,
        summary_key_order=SUMMARY_KEY_ORDER)


if __name__ == "__main__":
    sys.exit(main())
