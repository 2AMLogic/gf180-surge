#!/usr/bin/env python3
"""SXT-033 exactness harness: RTL checkpoint trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every declared per-slot checkpoint (T lines) against the model trace's
    `after` state: the envelope state machine, the per-unison-voice impulse
    engine state (oscstate, syncstate, state, last_level, pwidth, pwidth2,
    dc_uni), the shared extraction/character stage (dc, osc_out, osc_out2,
    bufpos, hpf_prev), the lag words, and the block gain bookkeeping,
  * the 64-sample oscillator output block (O lines) at every checkpoint,
  * every 48 kHz mono output sample of every block (M lines) against the
    model's mono_block.

Usage:
  python3 tools/compare_classic_rtl_model.py --run-dir DIR \
      [--tb rtl/oscillators/classic/tb_classic.sv] [--out JSON]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _rtl_compile_common import compile_and_run  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "oscillators", "classic", "tb_classic.sv")
MUTANT = os.path.join(REPO, "rtl", "oscillators", "classic",
                      "classic_broken_mutant.sv")

MAXUNI = 16
U_FIELDS = ["oscstate", "syncstate", "state", "last_level",
            "pwidth", "pwidth2", "dc_uni"]
T_TAIL = ["l_shape", "l_pw", "l_pw2", "l_sub", "l_sync",
          "dc", "osc_out", "osc_out2", "bufpos", "hpf_prev",
          "gain_end", "outl_end"]
T_FIELDS = ["b", "slot", "key", "aeg_state", "aeg_phase", "aeg_out",
            "n_unison"] + [f"u{i}_{f}" for i in range(MAXUNI)
                           for f in U_FIELDS] + T_TAIL


def parse_tb(path):
    t = {}      # (block, slot) -> dict
    o = {}      # (block, slot) -> [64]
    m = {}      # block -> [32]
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "T":
                vals = [int(x) for x in parts[1:]]
                d = dict(zip(T_FIELDS, vals))
                t[(d["b"], d["slot"])] = d
            elif parts[0] == "O":
                o[(int(parts[1]), int(parts[2]))] = [int(x) for x in parts[3:]]
            elif parts[0] == "M":
                b = int(parts[1])
                m.setdefault(b, []).append(int(parts[2]))
    return t, o, m


def compare(model_trace, tb_trace):
    fails = []
    checked = {"checkpoints": 0, "fields": 0, "voices": 0, "oscout": 0,
               "mono": 0}
    mt, mo, mm = tb_trace

    for blk in model_trace["blocks"]:
        b = blk["b"]
        mono_model = blk["mono_block"]
        mono_rtl = mm.get(b)
        if mono_rtl is None or len(mono_rtl) != len(mono_model):
            fails.append(f"block {b}: missing/short M line")
            continue
        for k, (a, bv) in enumerate(zip(mono_model, mono_rtl)):
            checked["mono"] += 1
            if a != bv:
                fails.append(f"block {b} sample {k}: mono model={a} rtl={bv}")
                if len(fails) > 40:
                    return checked, fails
        for rec in blk["voices"]:
            if "after" not in rec:
                continue
            key = (b, rec["slot"])
            d = mt.get(key)
            if d is None:
                fails.append(f"block {b} slot {rec['slot']}: missing T line")
                continue
            a = rec["after"]
            n = model_trace["n_unison"]
            mapping = {
                "aeg_state": a["aeg"]["state"], "aeg_phase": a["aeg"]["phase"],
                "aeg_out": a["aeg"]["output"], "n_unison": n,
                "l_shape": a["l_shape"], "l_pw": a["l_pw"],
                "l_pw2": a["l_pw2"], "l_sub": a["l_sub"],
                "l_sync": a["l_sync"], "dc": a["dc"],
                "osc_out": a["osc_out"], "osc_out2": a["osc_out2"],
                "bufpos": a["bufpos"], "hpf_prev": a["hpf_prev"],
                "gain_end": a["gain_end"],
            }
            for u in range(MAXUNI):
                for fld in U_FIELDS:
                    want = a[fld][u] if u < n else 0
                    mapping[f"u{u}_{fld}"] = want
            checked["checkpoints"] += 1
            checked["voices"] += n
            for fld, want in mapping.items():
                checked["fields"] += 1
                got = d.get(fld)
                if got != want:
                    fails.append(f"block {b} slot {rec['slot']} {fld}: "
                                 f"model={want} rtl={got}")
            omodel = rec["oscout_block"]
            ortl = mo.get(key)
            if ortl is None or len(ortl) != len(omodel):
                fails.append(f"block {b} slot {rec['slot']}: missing O line")
                continue
            for k, (av, bv) in enumerate(zip(omodel, ortl)):
                checked["oscout"] += 1
                if av != bv:
                    fails.append(f"block {b} slot {rec['slot']} osout[{k}]: "
                                 f"model={av} rtl={bv}")
            if len(fails) > 40:
                return checked, fails
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

    trace_path = compile_and_run(args.tb, args.run_dir, out_name="tb.vvp",
                                 direct_exec=True, suppress_stdout=False)
    rtl_trace = parse_tb(trace_path)
    checked, fails = compare(model_trace, rtl_trace)
    summary = {
        "tb": os.path.relpath(args.tb, REPO),
        "verdict": "PASS" if not fails else "FAIL",
        "checked": checked,
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
