#!/usr/bin/env python3
"""SXT-039 filter-leg runner: fixture -> frozen model -> trace + RTL stimulus.

Drives the FROZEN LP Legacy Ladder model (`filter_lpmoog_model.py`) with one
fixture (`fixtures.py`) and writes

  model_trace.json   per block: the quantized control plane, the block-start
                     C[8]/dC[8], the input words, the model outputs and the
                     end-of-block register/coefficient checkpoint;
  rtl/init.hex       [n_blocks]
  rtl/ctrl.hex       per block, 18 words: flags(b0 active, b1 reset),
                     subtype, C[8] block-start, dC[8]
  rtl/in.hex         64 input words per block

The trace is the exactness reference for `rtl/voice/tb_lpmoog.sv`
(integer equality; `tools/compare_rtl_model_lpmoog.py`) and the model side of
the reference budgets (`tools/compare_lpmoog_model.py`).

Fail-closed: an out-of-scope parameter, subtype or fixture is REFUSED
(exit 2), never clamped or guessed around.

Usage:
  python3 model/voice/filter_lpmoog/run_filter_leg.py --case king-b1 \
      --out-dir /tmp/run-king-b1
"""

import argparse
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, HERE)

import voice_model as vm  # noqa: E402
import filter_lpmoog_model as fp  # noqa: E402
import fixtures as fx  # noqa: E402

BLOCK_OS = vm.BLOCK_SIZE_OS
MASK32 = (1 << 32) - 1


def qintf(x):
    """Quantize an engine float32 to Q10.21 round-half-up (declared)."""
    return vm.sat(int(math.floor(x * (1 << vm.FQ) + 0.5)))


def run_case(case):
    """Run one fixture through the frozen model; return the trace dict."""
    spec = fx.build(case)
    unit = None
    cm = None
    blocks_out = []
    peaks = []
    n_reset = 0
    n_sub_change = 0
    prev_sub = None
    for b, ctl in enumerate(spec["blocks"]):
        sub = int(ctl["subtype"])
        reset = bool(ctl["reset"])
        if prev_sub is not None and sub != prev_sub:
            n_sub_change += 1
            if not reset:
                raise fp.Refuse(f"block {b}: subtype change without the engine "
                                "reset path (memset + CM.Reset)")
        prev_sub = sub
        if unit is None:
            unit = fp.LPMoogUnit(sub)
            cm = fp.LPMoogCoeffMaker(sub)
        elif reset:
            n_reset += 1
            if sub != unit.subtype:
                unit.set_subtype(sub)
                cm = fp.LPMoogCoeffMaker(sub)
            else:
                unit.reset_state()
                cm.reset()

        cut_q = qintf(ctl["cut"])
        kt_q = qintf(ctl["keytrack"])
        pitch_q = qintf(ctl["pitch"])
        ktroot_q = qintf(ctl["keytrack_root"])
        em_q = qintf(ctl["envmod"])
        fenv_q = qintf(ctl["fenv"])
        reso_q = qintf(ctl["reso"])
        cutoff_a = fp.cutoff_control(cut_q, kt_q, pitch_q, ktroot_q, em_q, fenv_q)
        cm.make_coeffs(cutoff_a, reso_q)

        blk_in = [qintf(v) for v in
                  spec["input"][b * BLOCK_OS:(b + 1) * BLOCK_OS]]
        c_start = list(cm.C)
        d_start = list(cm.dC)
        outs, peak, c_end = unit.process_block(blk_in, cm)
        # the voice path reads the advanced kernel C back into the coefficient
        # maker after every block (SurgeVoice.cpp GetQFB:
        # CM[u].C[i] = get1f(fbq->FU[u].C[i], fbqi)) -- mirrored exactly
        cm.C = list(c_end)
        peaks.append(peak)
        blocks_out.append({
            "b": b,
            "subtype": sub,
            "reset": reset,
            "cutoff_a_q": cutoff_a,
            "reso_q": reso_q,
            "C_start": c_start,
            "dC": d_start,
            "in": blk_in,
            "out_model": outs,
            "after": {"r": list(unit.r), "C_end": list(c_end)},
        })
    meta = {k: v for k, v in spec.items() if k not in ("blocks", "input")}
    return {
        "format": "sxt-039-lpmoog-trace/1",
        "meta": meta,
        "n_blocks": spec["n_blocks"],
        "resets": n_reset,
        "subtype_changes": n_sub_change,
        "subtypes": sorted({int(b["subtype"]) for b in spec["blocks"]}),
        "qmul_count": unit.qmul_count if unit else 0,
        "stability_peaks": peaks,
        "stability_verdict": fp.stability_verdict(peaks),
        "trace_blocks": blocks_out,
    }


def write_rtl_stimulus(trace, out_dir):
    rtl_dir = os.path.join(out_dir, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)
    with open(os.path.join(rtl_dir, "init.hex"), "w", encoding="utf-8") as f:
        f.write(f"{trace['n_blocks'] & MASK32:08x}\n")
    inp = []
    with open(os.path.join(rtl_dir, "ctrl.hex"), "w", encoding="utf-8") as f:
        for blk in trace["trace_blocks"]:
            flags = 1 | (2 if blk["reset"] else 0)
            words = [flags, blk["subtype"], *blk["C_start"], *blk["dC"]]
            f.write("".join(f"{(w & MASK32):08x}\n" for w in words))
            inp.extend(blk["in"])
    with open(os.path.join(rtl_dir, "in.hex"), "w", encoding="utf-8") as f:
        for w in inp:
            f.write(f"{(w & MASK32):08x}\n")
    return len(inp)


def write_model_f32(trace, path):
    """Model outputs as float32 (for side-by-side listening/plotting only)."""
    vals = [v / float(vm.ONE) for blk in trace["trace_blocks"]
            for v in blk["out_model"]]
    with open(path, "wb") as f:
        f.write(struct.pack(f"<{len(vals)}f", *vals))
    return len(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help=f"one of {sorted(fx.CASES)}")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--no-f32", action="store_true")
    args = ap.parse_args()

    trace = run_case(args.case)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "model_trace.json"), "w",
              encoding="utf-8") as f:
        json.dump(trace, f, indent=1)
        f.write("\n")
    n_in = write_rtl_stimulus(trace, args.out_dir)
    if not args.no_f32:
        write_model_f32(trace, os.path.join(args.out_dir, f"model-{args.case}.f32"))
    out_peak = max((abs(v) for blk in trace["trace_blocks"]
                    for v in blk["out_model"]), default=0)
    print(json.dumps({
        "case": args.case,
        "blocks": trace["n_blocks"],
        "subtypes": trace["subtypes"],
        "resets": trace["resets"],
        "subtype_changes": trace["subtype_changes"],
        "rtl_input_words": n_in,
        "qmul_count": trace["qmul_count"],
        "model_peak_lsb": out_peak,
        "stability": trace["stability_verdict"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except fp.Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
    except fx.Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
