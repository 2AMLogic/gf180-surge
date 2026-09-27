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

Usage:
  python3 tools/compare_kt_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_kt.sv]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import compile_and_run  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_kt.sv")

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/*.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        model_trace = json.load(f)

    trace_path, qmuls = compile_and_run(
        args.tb, args.run_dir, out_name="tb_kt.vvp", absolute=True,
        compile_in_workdir=True, quiet_compile=True,
        done_prefix="DONE kt-qmuls=", trace_name="tb_kt_trace.txt")
    checked, fails = compare(model_trace, parse_tb(trace_path))
    summary = {
        "tb": os.path.relpath(args.tb, REPO),
        "sequence": model_trace.get("sequence"),
        "control_mode": model_trace.get("control_mode"),
        "verdict": "PASS" if not fails else "FAIL",
        "checked": checked,
        "rtl_qmuls": qmuls,
        "blocks": len(model_trace["blocks"]),
        "mismatches": len(fails),
        "first_failures": fails[:10],
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
