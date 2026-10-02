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

Usage:
  python3 tools/compare_pm_rtl_model.py --run-dir DIR [--tb rtl/voice/tb_pm_mono_st_fp.sv]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_pm_mono_st_fp.sv")

FIELD_NAMES = ["active"] + [
    "gate", "uberrelease", "key",
    "aeg_state", "aeg_phase_q29", "aeg_output_q21", "aeg_scalestage_q21",
    "vel_value_q21", "vel_target_q21", "kt_word_q21",
    "portaphase_q29", "portasrc_key_q21", "pkey_q21", "priorpkey_q21",
    "porta_doretrigger",
]


def _int(x):
    try:
        return int(x)
    except ValueError:
        return None


def parse_tb(path):
    t = {}   # (block, slot) -> [active, gate, uberrelease, key, ...] (16 words)
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p or p[0] != "T":
                continue
            b, slot = int(p[1]), int(p[2])
            t[(b, slot)] = [_int(x) for x in p[3:3 + len(FIELD_NAMES)]]
    return t


def compare(model_trace, tb_trace):
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


def build_and_run(sv_file, workdir):
    workdir = os.path.abspath(workdir)
    vvp = os.path.join(workdir, "tb_pm_mono_st_fp.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", vvp, os.path.abspath(sv_file)],
                   check=True, cwd=workdir,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = subprocess.run(["vvp", vvp], cwd=workdir, check=True,
                       capture_output=True, text=True)
    done = [ln for ln in r.stdout.splitlines() if ln.startswith("DONE")]
    return os.path.join(workdir, "tb_pm_trace.txt"), (done[-1] if done else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/{init,ev}.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        model_trace = json.load(f)

    trace_path, done = build_and_run(args.tb, args.run_dir)
    checked, fails, pool = compare(model_trace, parse_tb(trace_path))
    summary = {
        "tb": os.path.relpath(os.path.abspath(args.tb), REPO),
        "carrier": model_trace.get("carrier"),
        "sequence": model_trace.get("sequence"),
        "pool": pool,
        "verdict": "PASS" if not fails else "FAIL",
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
        "rtl_done_line": done,
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
