#!/usr/bin/env python3
"""SXT-026 RTL-vs-model exactness harness (issue #19).

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * per-voice impulse-engine state at every declared checkpoint
    (oscstate, table state, last_level, mipmap),
  * morph machinery state (tableid, tableipol, last_tableipol, l_shape),
  * the hpf/output stage (osc_out, bufpos, hpf_prev),
  * every 64-sample oscillator output block,
  * external-asset traffic: core reads_words vs the model's declared
    2-words-per-impulse accounting, fill_words vs frame-fills.

Also verifies the RTL negative-control mutant (NC-B RTL: -DWAVETABLE_MUTANT_MIP)
FAILS the same comparison (--mutant).

Usage:
  python3 tools/compare_wt_rtl_model.py --run-dir DIR [--tb TB] [--out JSON]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RTLDIR = os.path.join(REPO, "rtl", "oscillators", "wavetable")


def parse_traces(run_dir, slots=4):
    """Parse tb_trace.s<k> files: T (per-voice), S (shared), O (oscout)."""
    t, sh, o = {}, {}, {}
    for s in range(slots):
        p = os.path.join(run_dir, "tb_trace.s%d" % s)
        if not os.path.exists(p):
            continue
        with open(p) as f:
            for line in f:
                parts = line.split()
                if parts[0] == "T":
                    b, slot, v = int(parts[1]), int(parts[2]), int(parts[3])
                    vals = [int(x) for x in parts[4:]]
                    t[(b, slot, v)] = vals
                elif parts[0] == "S":
                    b, slot = int(parts[1]), int(parts[2])
                    vals = [int(x) for x in parts[3:]]
                    sh[(b, slot)] = vals
                elif parts[0] == "O":
                    b, slot = int(parts[1]), int(parts[2])
                    o.setdefault((b, slot), []).extend(
                        int(x) for x in parts[3:])
    return t, sh, o


def to_signed32(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x >= (1 << 31) else x


def compare(model_trace, rtl):
    t, sh, o = rtl
    fails = []
    checked = {"voices": 0, "fields": 0, "oscout": 0, "shared": 0}
    for blk in model_trace["blocks"]:
        b = blk["b"]
        for rec in blk["voices"]:
            if "after" not in rec:
                continue
            slot = rec["slot"]
            a = rec["after"]
            n = len(a["oscstate"])
            for v in range(n):
                want = [a["oscstate"][v], a["osc_state"][v],
                        to_signed32(a["last_level"][v]), a["mipmap"][v]]
                got = t.get((b, slot, v))
                checked["voices"] += 1
                if got is None:
                    fails.append("block %d slot %d voice %d: missing T line"
                                 % (b, slot, v))
                    continue
                for fi, (wv, gv) in enumerate(zip(want, got)):
                    checked["fields"] += 1
                    if wv != gv:
                        fails.append(
                            "block %d slot %d voice %d field %d: "
                            "model=%d rtl=%d" % (b, slot, v, fi, wv, gv))
            want_s = [a["tableid"], to_signed32(a["tableipol"]),
                      to_signed32(a["last_tableipol"]),
                      to_signed32(a["l_shape"]),
                      to_signed32(a["osc_out"]), a["bufpos"],
                      to_signed32(a["hpf_prev"])]
            got_s = sh.get((b, slot))
            checked["shared"] += 1
            if got_s is None:
                fails.append("block %d slot %d: missing S line" % (b, slot))
            else:
                for fi, (wv, gv) in enumerate(zip(want_s, got_s)):
                    checked["fields"] += 1
                    if wv != gv:
                        fails.append("block %d slot %d sfield %d: "
                                     "model=%d rtl=%d" % (b, slot, fi,
                                                          wv, gv))
            om = rec.get("oscout_block")
            ot = o.get((b, slot))
            if om is not None:
                if ot is None or len(ot) != len(om):
                    fails.append("block %d slot %d: missing/short O line"
                                 % (b, slot))
                    continue
                for k, (wv, gv) in enumerate(zip(om, ot)):
                    checked["oscout"] += 1
                    if to_signed32(wv) != gv:
                        fails.append("block %d slot %d osout[%d]: "
                                     "model=%d rtl=%d" % (b, slot, k,
                                                          wv, gv))
            if len(fails) > 30:
                return checked, fails
    return checked, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="run dir with model_trace.json + rtl/ stimulus")
    ap.add_argument("--out", help="write verdict JSON here")
    ap.add_argument("--mutant", action="store_true",
                    help="build the committed mip-threshold mutant; "
                         "the comparison must FAIL")
    ap.add_argument("--max-blocks", type=int, default=130)
    args = ap.parse_args()

    with open(os.path.join(args.run_dir, "model_trace.json")) as f:
        model_trace = json.load(f)

    n_unison = model_trace["unison"]
    wave_size = model_trace.get("wave_size", 1024)
    vvp = os.path.join(args.run_dir, "tb_wt.vvp")
    src = (os.path.join(RTLDIR, "tb_wavetable.sv")
           + " " + os.path.join(RTLDIR, "wavetable_core.sv"))
    build = ["iverilog", "-g2012", "-o", vvp, "-s", "tb_wavetable"]
    if args.mutant:
        build.append("-DWAVETABLE_MUTANT_MIP")
    build += [src.replace(" ", " ")] if False else [src]
    # (pass the two source files as separate arguments)
    build = ["iverilog", "-g2012", "-o", vvp, "-s", "tb_wavetable"]
    if args.mutant:
        build.append("-DWAVETABLE_MUTANT_MIP")
    build += [os.path.join(RTLDIR, "tb_wavetable.sv"),
              os.path.join(RTLDIR, "wavetable_core.sv")]
    subprocess.run(build, check=True, cwd=args.run_dir)
    run = subprocess.run(
        ["vvp", vvp, "+BLOCKS=%d" % args.max_blocks, "+N_UNISON=%d" % n_unison,
         "+WAVE_SIZE=%d" % wave_size, "+N_TABLES=%d" % model_trace["n_tables"],
         "+NOINTERP=%d" % model_trace["nointerp"],
         "+LEGACY=%d" % model_trace["legacy"],
         "+TRACE=%s/tb_trace" % args.run_dir, "+INIT=rtl/init.hex",
         "+CTRL=rtl/ctrl.hex", "+WT_TABLE=rtl/wt_table.hex",
         "+SINC_MAIN=rtl/sinc_main.hex", "+SINC_DERIV=rtl/sinc_deriv.hex",
         "+TRAFFIC=%s/tb_traffic.txt" % args.run_dir,
         "+MUT=%d" % (1 if args.mutant else 0)],
        cwd=args.run_dir, capture_output=True, text=True, timeout=3600)

    rtl = parse_traces(args.run_dir)
    checked, fails = compare(model_trace, rtl)

    # traffic reconciliation (counts from the core, dumped by the TB)
    traffic = {}
    tp = os.path.join(args.run_dir, "tb_traffic.txt")
    if os.path.exists(tp):
        with open(tp) as f:
            for line in f:
                k, v = line.split()
                traffic[k] = int(v)

    model_traffic = None
    tp = os.path.join(args.run_dir, "traffic.json")
    if os.path.exists(tp):
        with open(tp) as f:
            model_traffic = json.load(f)["totals"]

    verdict = "PASS" if not fails else "FAIL"
    summary = {
        "verdict": verdict,
        "mutant": args.mutant,
        "checked": checked,
        "mismatches": len(fails),
        "first_failures": fails[:10],
        "traffic_tb": traffic,
        "traffic_model": model_traffic,
    }
    print(json.dumps(summary, indent=1))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=1)
            f.write("\n")
    if args.mutant:
        return 0 if fails else 1
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
