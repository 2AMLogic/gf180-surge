#!/usr/bin/env python3
"""SXT-023 follow-up smoke driver: truncated-slice RTL-vs-model exactness.

Runs the frozen fixed-point models over the first SMOKE_RENDER render blocks
(after the declared 240-block settle) of a fixture dry bus, emits the model
trace + RTL stimulus in the standard formats, runs the SV tb (iverilog or
Verilator), and compares with integer equality. Fast-iteration harness; the
canonical evidence run remains the full-length iverilog run.
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from model.effects.run_fx_model import (  # noqa: E402
    SETTLE_BLOCKS, build_models, run_chain, amp_to_linear_fixed,
    read_wav_stereo_f32, delay_ctrl_words, eq_ctrl_words, qhex,
)
from model.effects.qmath import to_q  # noqa: E402
from model.effects.delay.delay_model import db_to_linear_d  # noqa: E402
from tools.compare_rtl_model_fx import parse_tb_trace, compare  # noqa: E402

PCONFIG = {"metallic": 1, "fm_bass_1": 2, "dexie": 3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--render-blocks", type=int, default=16)
    ap.add_argument("--settle-blocks", type=int, default=SETTLE_BLOCKS)
    ap.add_argument("--tb", default=os.path.join(REPO, "rtl", "effects", "tb_fx.sv"))
    ap.add_argument("--sim", choices=["iverilog", "verilator"], default="iverilog")
    ap.add_argument("--workdir", default="/tmp/sxt023_smoke")
    ap.add_argument("--out")
    args = ap.parse_args()

    slug = args.slug
    wd = args.workdir
    os.makedirs(wd, exist_ok=True)
    n_total = args.settle_blocks + args.render_blocks

    cfg = json.load(open(os.path.join(REPO, "model/effects/fx_inputs", slug + ".json")))
    dry, _ = read_wav_stereo_f32(os.path.join(
        REPO, "reports/sxt-023/fixtures", f"{slug}__seq-notes-coverage-v1-dry.f32.wav"))
    frames = min(dry.shape[1], n_total * 32)
    a_q = to_q(db_to_linear_d(cfg["volume_f"]), "Q13.18")
    a_d = db_to_linear_d(cfg["volume_f"])

    zeros = [0] * (args.settle_blocks * 32)
    in_l = zeros + [to_q(float(x) / a_d, "Q10.21") for x in dry[0][:frames]]
    in_r = zeros + [to_q(float(x) / a_d, "Q10.21") for x in dry[1][:frames]]
    in_l += [0] * (n_total * 32 - len(in_l))
    in_r += [0] * (n_total * 32 - len(in_r))

    ains, sends = build_models(cfg)
    for _k, m in ains:
        m.initialize()
    for _k, m, _i, _s, _r in sends:
        m.initialize()

    def snapshot_ctrl(kind, m):
        if kind == "delay":
            m.ctrl["lp_coeffs"] = list(m.st.lp.tgt)
            m.ctrl["hp_coeffs"] = list(m.st.hp.tgt)
        else:
            m.ctrl["gain_tgt"] = to_q(db_to_linear_d(m.p.gain_out_f), "Q13.18")
            m.ctrl["mix_tgt"] = to_q(min(1.0, max(-1.0, m.p.mix_f)), "Q13.18")

    cps = {args.settle_blocks - 1, args.settle_blocks, args.settle_blocks + 1,
           n_total - 1}
    b = args.settle_blocks
    while b < n_total:
        cps.add(b)
        b += 64

    trace_blocks, blocks_in, ctrl_lines = [], [], []
    for blk in range(n_total):
        il = in_l[blk * 32:(blk + 1) * 32]
        ir = in_r[blk * 32:(blk + 1) * 32]
        blocks_in.append((il, ir))
        out_l, out_r, _sp = run_chain(ains, sends, il, ir, a_q)
        words = [qhex(a_q, 32)]
        for kind, m in ains:
            snapshot_ctrl(kind, m)
            words += delay_ctrl_words(m.ctrl) if kind == "delay" else eq_ctrl_words(m.ctrl, m)
        for kind, m, _i, sg_f, rl_f in sends:
            snapshot_ctrl(kind, m)
            words += delay_ctrl_words(m.ctrl) if kind == "delay" else eq_ctrl_words(m.ctrl, m)
            words.append(qhex(amp_to_linear_fixed(sg_f), 32))
            words.append(qhex(amp_to_linear_fixed(rl_f), 32))
        ctrl_lines.append(" ".join(words))
        if blk in cps or blk >= args.settle_blocks:
            rec = {"b": blk, "out": {"L": out_l, "R": out_r}, "instances": []}
            for kind, m in ains:
                rec["instances"].append({"kind": kind, **m.st.checkpoint()})
            for kind, m, _i, _s, _r in sends:
                rec["instances"].append({"kind": kind, **m.st.checkpoint()})
            trace_blocks.append(rec)

    trace = {
        "schema_version": 1, "slug": slug, "sequence": "smoke",
        "settle_blocks": args.settle_blocks, "n_blocks_total": n_total,
        "render_frames": frames, "a_fixed": a_q,
        "checkpoint_blocks": sorted(cps), "blocks": trace_blocks,
    }
    trace_path = os.path.join(wd, f"model_trace_{slug}_smoke.json")
    with open(trace_path, "w") as f:
        json.dump(trace, f)
    in_path = os.path.join(wd, f"{slug}_in.hex")
    ctrl_path = os.path.join(wd, f"{slug}_ctrl.hex")
    with open(in_path, "w") as fi:
        for il, ir in blocks_in:
            for v in il:
                fi.write(qhex(v, 32) + "\n")
            for v in ir:
                fi.write(qhex(v, 32) + "\n")
    with open(ctrl_path, "w") as fc:
        for line in ctrl_lines:
            for w in line.split():
                fc.write(w + "\n")

    vvp = os.path.join(wd, "tb_fx_smoke.vvp")
    trace_txt = os.path.join(wd, "tb_trace.txt")
    plusargs = [f"+PCONFIG={PCONFIG[slug]}", f"+NBLOCKS={n_total}",
                f"+RENDER0={args.settle_blocks}", f"+TRACE={trace_txt}",
                f"+INFILE={in_path}", f"+CTRLFILE={ctrl_path}",
                f"+SINC={os.path.join(REPO, 'rtl/effects/sinc_q29.hex')}",
                f"+ZEROS={os.path.join(REPO, 'rtl/effects/line_zeros.hex')}"]
    t0 = time.time()
    if args.sim == "iverilog":
        subprocess.run(["/opt/homebrew/bin/iverilog", "-g2012", "-o", vvp,
                        args.tb, os.path.join(REPO, "rtl/effects/fx_line_ext.sv")],
                       check=True)
        subprocess.run(["vvp", vvp] + plusargs,
                       check=True, stdout=subprocess.DEVNULL)
    else:
        subprocess.run(["verilator", "--binary", "--timing", "-Wno-fatal",
                        "--top-module", "tb_fx", args.tb,
                        os.path.join(REPO, "rtl/effects/fx_line_ext.sv"),
                        "-o", "simverilator", "--Mdir", os.path.join(wd, "obj_dir")],
                       check=True)
        subprocess.run([os.path.join(wd, "obj_dir", "simverilator")] + plusargs,
                       check=True, stdout=subprocess.DEVNULL, cwd=wd)
    sim_time = time.time() - t0

    rtl = parse_tb_trace(trace_txt)
    checked, fails = compare(slug, trace, rtl)
    summary = {
        "slug": slug, "sim": args.sim, "tb": os.path.basename(args.tb),
        "settle_blocks": args.settle_blocks, "blocks_total": n_total,
        "samples_total": n_total * 32,
        "verdict": "PASS" if not fails else "FAIL",
        "checked": checked, "mismatches": len(fails),
        "first_failures": fails[:10],
        "sim_seconds": round(sim_time, 2),
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
