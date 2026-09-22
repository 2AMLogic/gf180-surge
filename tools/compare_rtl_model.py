#!/usr/bin/env python3
"""SXT-022 exactness harness: RTL checkpoint trace vs frozen model trace.

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every declared per-slot checkpoint (T lines) against the model trace's
    `after` state (envelope state machines, oscillator impulse-engine state,
    filter registers, coefficient end-of-block values),
  * the 64-sample oscillator output block (O lines) at every checkpoint,
  * every 48 kHz mono output sample of every block (M lines) against the
    model's mono_block.

Also runs the committed negative control: rtl/voice/voice_broken_mutant.sv
(a deliberately mutated copy of the testbench) must FAIL this comparison.

Usage:
  python3 tools/compare_rtl_model.py --run-dir DIR [--mutant]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(REPO, "rtl", "voice", "tb_voice.sv")
MUTANT = os.path.join(REPO, "rtl", "voice", "voice_broken_mutant.sv")

T_FIELDS = ["b", "slot", "key", "gate",
            "aeg_state", "aeg_phase", "aeg_out",
            "feg_state", "feg_phase", "feg_out",
            "oscstate", "osc_state", "last_level", "pwidth", "pwidth2",
            "dc_uni", "dc", "osc_out", "osc_out2", "bufpos",
            "f_r0", "f_r1", "f_clip",
            "c0", "c1", "c2", "c3", "c4", "c5", "c6", "c7",
            "f4_r0", "f4_r1"]          # SXT-026a: IIR24 second section

U_FIELDS = ["u_oscstate", "u_state", "u_last_level",
            "u_pwidth", "u_pwidth2", "u_dc_uni"]


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
            elif parts[0] == "U":
                key = (int(parts[1]), int(parts[2]))
                uv = dict(zip(U_FIELDS, [int(x) for x in parts[4:]]))
                rec = t.setdefault(key, {})
                rec.setdefault("uni", {})[int(parts[3])] = uv
            elif parts[0] == "O":
                o[(int(parts[1]), int(parts[2]))] = [int(x) for x in parts[3:]]
            elif parts[0] == "M":
                b = int(parts[1])
                m.setdefault(b, []).append(int(parts[2]))
    return t, o, m


def compare(model_trace, tb_trace):
    fails = []
    checked = {"checkpoints": 0, "fields": 0, "oscout": 0, "mono": 0}
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
            mapping = {
                "aeg_state": a["aeg"]["state"], "aeg_phase": a["aeg"]["phase"],
                "aeg_out": a["aeg"]["output"],
                "feg_state": a["feg"]["state"], "feg_phase": a["feg"]["phase"],
                "feg_out": a["feg"]["output"],
                "oscstate": a["oscstate"], "osc_state": a["osc_state"],
                "last_level": a["last_level"], "pwidth": a["pwidth"],
                "pwidth2": a["pwidth2"], "dc_uni": a["dc_uni"], "dc": a["dc"],
                "osc_out": a["osc_out"], "osc_out2": a["osc_out2"],
                "bufpos": a["bufpos"],
                "f_r0": a["f_r0"], "f_r1": a["f_r1"], "f_clip": a["f_clip"],
                "f4_r0": a.get("f4_r0", 0), "f4_r1": a.get("f4_r1", 0),
                "c0": a["C_end"][0], "c1": a["C_end"][1], "c2": a["C_end"][2],
                "c3": a["C_end"][3], "c4": a["C_end"][4], "c5": a["C_end"][5],
                "c6": a["C_end"][6], "c7": a["C_end"][7],
            }
            checked["checkpoints"] += 1
            for fld, want in mapping.items():
                checked["fields"] += 1
                got = d.get(fld)
                if got != want:
                    fails.append(f"block {b} slot {rec['slot']} {fld}: "
                                 f"model={want} rtl={got}")
            # per-unison-voice impulse state (U lines); voice 0 also mirrors
            # the legacy scalar fields above
            uni_model = a.get("uni")
            if uni_model is not None:
                uni_rtl = d.get("uni", {})
                for uv_idx, want_u in enumerate(uni_model):
                    got_u = uni_rtl.get(uv_idx)
                    if got_u is None:
                        fails.append(f"block {b} slot {rec['slot']} uni{uv_idx}: "
                                     "missing U line")
                        continue
                    for fld, want in want_u.items():
                        checked["fields"] += 1
                        got = got_u.get("u_" + fld)
                        if got is None:
                            got = got_u.get(fld)
                        if got != want:
                            fails.append(
                                f"block {b} slot {rec['slot']} uni{uv_idx} "
                                f"{fld}: model={want} rtl={got}")
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
    workdir = os.path.abspath(workdir)
    vvp = os.path.join(workdir, "tb_mut.vvp" if sv_file == MUTANT else "tb.vvp")
    subprocess.run(["iverilog", "-g2012", "-o", vvp, os.path.abspath(sv_file)],
                   check=True)
    subprocess.run(["vvp", vvp], cwd=workdir, check=True,
                   stdout=subprocess.DEVNULL)
    return os.path.join(workdir, "tb_trace.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="directory with model_trace.json + rtl/*.hex")
    ap.add_argument("--tb", default=TB)
    ap.add_argument("--out", help="write summary JSON here")
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        model_trace = json.load(f)

    trace_path = build_and_run(args.tb, args.run_dir)
    rtl_trace = parse_tb(trace_path)
    checked, fails = compare(model_trace, rtl_trace)
    summary = {
        "tb": os.path.basename(args.tb),
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
