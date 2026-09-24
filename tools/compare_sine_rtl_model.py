#!/usr/bin/env python3
"""SXT-040 exactness harness: RTL checkpoint trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every declared per-slot checkpoint (T/S/G lines) against the model
    trace's `after` state: the envelope state machine, the per-unison-voice
    sine engines (legacy quadrature r/i/dr/di + playingramp; modern phase /
    lastvalue / omegaPrior), the shared lags (FB/FM), applyFilter TDF2
    registers, the character-filter state, and the block gain bookkeeping,
  * the 64-sample oscillator output block (O lines) at every checkpoint,
  * every 48 kHz mono output sample of every block (M lines) against the
    model's mono_block.

Usage:
  python3 tools/compare_sine_rtl_model.py --run-dir DIR \
      [--tb rtl/oscillators/sine/tb_sine.sv] [--out JSON]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "oscillators", "sine", "tb_sine.sv")
MUTANT = os.path.join(REPO, "rtl", "oscillators", "sine",
                      "sine_broken_mutant.sv")

MAXUNI = 16
LEGACY_U_FIELDS = ["quad_r", "quad_i", "quad_dr", "quad_di", "pramp"]
MODERN_U_FIELDS = ["phase", "lv0", "lv1", "om_prior"]


def parse_tb(path):
    t = {}      # (block, slot) -> dict
    o = {}      # (block, slot) -> [64]
    m = {}      # block -> [32]
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            tag = parts[0]
            if tag == "T":
                vals = [int(x) for x in parts[1:]]
                b, s, key, legacy, nuni, aeg_state, aeg_phase, aeg_out = vals[:8]
                rest = vals[8:]
                d = {"b": b, "slot": s, "key": key, "legacy": legacy,
                     "n_unison": nuni, "aeg_state": aeg_state,
                     "aeg_phase": aeg_phase, "aeg_out": aeg_out}
                nf = 5 if legacy else 4
                fields = LEGACY_U_FIELDS if legacy else MODERN_U_FIELDS
                for u in range(MAXUNI):
                    for fi, fld in enumerate(fields):
                        d[f"u{u}_{fld}"] = rest[u * nf + fi]
                if not legacy:
                    d["prior_valid"] = rest[MAXUNI * 4]
                t[(b, s)] = d
            elif tag == "S":
                vals = [int(x) for x in parts[1:]]
                b, s = vals[0], vals[1]
                d = t.get((b, s))
                if d is None:
                    d = t.setdefault((b, s), {})
                d.update({"fb_v": vals[2], "fm_v": vals[3],
                          "firstblock": vals[4], "hp_r0": vals[5],
                          "hp_r1": vals[6], "lp_r0": vals[7],
                          "lp_r1": vals[8], "char_py": vals[9],
                          "char_px": vals[10]})
            elif tag == "G":
                b, s, gain = int(parts[1]), int(parts[2]), int(parts[3])
                d = t.setdefault((b, s), {})
                d["gain_end"] = gain
            elif tag == "O":
                o[(int(parts[1]), int(parts[2]))] = [int(x) for x in parts[3:]]
            elif tag == "M":
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
            legacy = model_trace["legacy"]
            u_fields = LEGACY_U_FIELDS if legacy else MODERN_U_FIELDS
            mapping = {
                "aeg_state": a["aeg"]["state"],
                "aeg_phase": a["aeg"]["phase"],
                "aeg_out": a["aeg"]["output"],
                "n_unison": n,
                "legacy": 1 if legacy else 0,
                "fb_v": a["fb_v"], "fm_v": a["fm_v"],
                "firstblock": a["firstblock"],
                "hp_r0": a["hp_r0"], "hp_r1": a["hp_r1"],
                "lp_r0": a["lp_r0"], "lp_r1": a["lp_r1"],
                "char_py": a["char_py"], "char_px": a["char_px"],
                "gain_end": a["gain_end"],
            }
            if not legacy:
                mapping["prior_valid"] = a["prior_valid"]
            for u in range(MAXUNI):
                for fld in u_fields:
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


def build_and_run(sv_file, workdir):
    vvp = os.path.join(workdir, "tb.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", vvp, sv_file], check=True)
    subprocess.run([vvp], cwd=workdir, check=True)
    return os.path.join(workdir, "tb_trace.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/*.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    ap.add_argument("--trace", default=None,
                    help="reuse an existing tb_trace.txt (skip iverilog/vvp)")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        model_trace = json.load(f)

    if args.trace:
        trace_path = args.trace
    else:
        trace_path = build_and_run(args.tb, args.run_dir)
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
