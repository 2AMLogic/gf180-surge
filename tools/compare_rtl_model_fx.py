#!/usr/bin/env python3
"""SXT-023 exactness harness: RTL trace vs frozen model trace (integer equality).

Compares, with INTEGER EQUALITY (any mismatch = FAIL):
  * every output sample of every render block (O lines) against the model's
    out block (L then R, Q10.21 words),
  * every declared checkpoint's per-instance state (T lines): delay
    wpos/fb_sign/lag states/targets/biquad registers/line hash/ext counters,
    EQ bi/lag/registers/targets. Control-plane accumulators (lfophase, LFOval,
    direction) are streamed to the RTL inside the time targets and are not
    compared as state.

Also runs the negative-control mutants when pointed at them (--tb).
Usage:
  python3 tools/compare_rtl_model_fx.py --slug metallic \
      [--tb rtl/effects/tb_fx_mutant.sv] [--out out.json]
"""

import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(REPO, "reports", "sxt-023", "artifacts")
SINC = os.path.join(REPO, "rtl", "effects", "sinc_q29.hex")
IV = os.environ.get("IVERILOG", "/opt/homebrew/bin/iverilog")
VVP = os.environ.get("VVP", "vvp")

PCONFIG = {"metallic": 1, "fm_bass_1": 2, "dexie": 3}

DLY_MAP = {
    "wpos": "wpos", "fbsign": "fb_sign",
    "tlv": "time_l_v", "tlt": "time_l_tgt",
    "trv": "time_r_v", "trt": "time_r_tgt",
    "fb": "fb_tgt", "cf": "cf_tgt", "mix": "mix_tgt", "pan": "pan_tgt", "ws": "ws_tgt",
    "hash": "line_hash", "er": "ext_reads", "ew": "ext_writes",
}
for i in range(5):
    DLY_MAP[f"lp{i}"] = ("lp_lag", i)
    DLY_MAP[f"hp{i}"] = ("hp_lag", i)
DLY_MAP.update({
    "lpr0": ("lp_reg0", 0), "lpr1": ("lp_reg1", 0),
    "lpr0b": ("lp_reg0", 1), "lpr1b": ("lp_reg1", 1),
    "hpr0": ("hp_reg0", 0), "hpr1": ("hp_reg1", 0),
    "hpr0b": ("hp_reg0", 1), "hpr1b": ("hp_reg1", 1),
})
SKIP_FIELDS = {"lfophase", "lfoval", "lfo_dir", "name"}


def parse_tb_trace(path):
    O = {}
    T = {}
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "O":
                b = int(parts[1])
                O[b] = [int(v) for v in parts[2:]]
            elif parts[0] == "T":
                b = int(parts[1])
                tag = parts[2]
                d = {}
                for j in range(3, len(parts), 2):
                    d[parts[j]] = int(parts[j + 1])
                T[(b, tag)] = d
    return O, T


def checkpoint_set(model_trace):
    settle = model_trace["settle_blocks"]
    n_total = model_trace["n_blocks_total"]
    cps = {settle - 1, settle, settle + 1, n_total - 1}
    b = settle
    while b < n_total:
        cps.add(b)
        b += 64
    return cps


def compare(slug, model_trace, rtl_trace):
    fails = []
    checked = {"outputs": 0, "checkpoints": 0, "fields": 0}
    O, T = rtl_trace
    cps = checkpoint_set(model_trace)

    for blk in model_trace["blocks"]:
        b = blk["b"]
        # outputs
        rtl_o = O.get(b)
        if rtl_o is None:
            if b >= model_trace["settle_blocks"]:
                fails.append(f"block {b}: missing O line")
            continue
        exp = blk["out"]["L"] + blk["out"]["R"]
        if len(rtl_o) != len(exp):
            fails.append(f"block {b}: O width {len(rtl_o)} != {len(exp)}")
            continue
        for k, (a, bv) in enumerate(zip(exp, rtl_o)):
            checked["outputs"] += 1
            if a != bv:
                fails.append(f"block {b} out[{k}]: model={a} rtl={bv}")
                if len(fails) > 25:
                    return checked, fails
        # checkpoints (declared set only)
        if b not in cps:
            continue
        insts = blk["instances"]
        tags = [f"d{i}" if s["kind"] == "delay" else "eq0" for i, s in enumerate(insts)]
        for tag, st in zip(tags, insts):
            rtl_t = T.get((b, tag))
            if rtl_t is None:
                fails.append(f"block {b} {tag}: missing T line")
                continue
            checked["checkpoints"] += 1
            mapping = {}
            if st["kind"] == "delay":
                for rk, mk in DLY_MAP.items():
                    if isinstance(mk, tuple):
                        mapping[rk] = st[mk[0]][mk[1]]
                    else:
                        mapping[rk] = st[mk]
            else:
                mapping["bi"] = st["bi"]
                for w in range(3):
                    for j in range(5):
                        mapping[f"lag{w}_{j}"] = st["band_lag"][w][j]
                # RTL r order: [band0 r0L, r0R, r1L, r1R, band1 r0L, r0R, r1L, r1R, band2 ...]
                for w in range(3):
                    mapping[f"r{4*w+0}"] = st["band_reg0"][w][0]
                    mapping[f"r{4*w+1}"] = st["band_reg0"][w][1]
                    mapping[f"r{4*w+2}"] = st["band_reg1"][w][0]
                    mapping[f"r{4*w+3}"] = st["band_reg1"][w][1]
                mapping["gtgt"] = st["gain_tgt"]
                mapping["mtgt"] = st["mix_tgt"]
            for rk, want in mapping.items():
                checked["fields"] += 1
                got = rtl_t.get(rk)
                if got != want:
                    fails.append(f"block {b} {tag} {rk}: model={want} rtl={got}")
                    if len(fails) > 25:
                        return checked, fails
    return checked, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--tb", default=os.path.join(REPO, "rtl", "effects", "tb_fx.sv"))
    ap.add_argument("--max-blocks", type=int, default=0,
                    help="compare only the first N blocks (0 = all)")
    ap.add_argument("--out")
    args = ap.parse_args()

    slug = args.slug
    trace_path = os.path.join(ART, f"model_trace_{slug}.json")
    with open(trace_path) as f:
        model_trace = json.load(f)
    n_total = model_trace["n_blocks_total"]
    n_blocks = args.max_blocks if args.max_blocks else n_total

    # compile
    vvp_path = "/tmp/tb_fx_compiled.vvp"
    subprocess.run([IV, "-g2012", "-o", vvp_path, args.tb,
                    os.path.join(REPO, "rtl", "effects", "fx_line_ext.sv")],
                   check=True)
    rtl_trace_path = "/tmp/tb_fx_trace.txt"
    sinc_path = SINC
    zeros_path = os.path.join(REPO, "rtl", "effects", "line_zeros.hex")
    vvp_args = [VVP, vvp_path,
                f"+PCONFIG={PCONFIG[slug]}",
                f"+NBLOCKS={n_blocks}",
                f"+RENDER0={model_trace['settle_blocks']}",
                f"+TRACE={rtl_trace_path}",
                f"+INFILE={os.path.join(ART, 'rtl', slug + '_in.hex')}",
                f"+CTRLFILE={os.path.join(ART, 'rtl', slug + '_ctrl.hex')}",
                f"+SINC={sinc_path}",
                f"+ZEROS={zeros_path}"]
    subprocess.run(vvp_args, check=True, stdout=subprocess.DEVNULL)

    rtl = parse_tb_trace(rtl_trace_path)
    checked, fails = compare(slug, model_trace, rtl)
    summary = {
        "slug": slug,
        "tb": os.path.basename(args.tb),
        "blocks_compared": n_blocks,
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
