#!/usr/bin/env python3
"""SXT-038 filter-leg runner: reference bundle -> frozen model -> metrics + RTL stimulus.

A bundle is produced by `tools/render_lp24_reference.py` from the pinned
filter submodule (decision-records/0010).  It contains

  coeffs.jsonl  one record per block: the control words the reference leg
                consumed (cut, reso, subtype, reset/FirstRun) and the pinned
                coefficient maker's resulting C[8] / dC[8];
  units.bin     per OS sample: tag, lane, seq, filter input, filter output
                (float32), same record layout as the SXT-037 tap bundles;
  regs.bin      per block: the reference unit's five registers R[0..4]
                after the block.

This runner drives the FROZEN fixed-point model (filter_lp24_model.py) with
the SAME control plane (re-derived from the committed case file and checked
against the bundle, fail-closed) and the SAME input signal, and reports

  L1  model coefficient plane vs pinned-code coefficient plane
  L2a model audio path (own coefficients) vs pinned-code filter output
  L2b model audio path driven by the PINNED coefficients (attribution leg)
  L3  model end-of-block registers vs the pinned unit's registers

and writes the RTL stimulus (rtl/*.hex) + the model trace consumed by
`tools/compare_rtl_model_lp24.py`.

Fail-closed: a control-plane mismatch, a sample-count mismatch, a subtype
change without the engine's reset flag, or an out-of-scope parameter is
REFUSED (exit 2), never worked around.

Usage:
  python3 model/voice/filter_lp24/run_filter_leg.py --bundle DIR --out-dir DIR
                                                    [--engine-coeffs]
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

import voice_model as vm            # noqa: E402
import filter_lp24_model as fp      # noqa: E402
import case_plan as cp              # noqa: E402

MASK32 = (1 << 32) - 1
CASES_DIR = os.path.join(REPO, "reports", "SXT-038", "artifacts", "cases")


class Refuse(Exception):
    pass


def qintf(x):
    """Quantize a reference float32 to Q10.21, round-half-up (declared)."""
    return vm.sat(int(math.floor(x * (1 << vm.FQ) + 0.5)))


def load_bundle(bundle_dir):
    with open(os.path.join(bundle_dir, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    coeffs = []
    with open(os.path.join(bundle_dir, "coeffs.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                coeffs.append(json.loads(line))
    size = struct.calcsize("<IIIff")
    raw = open(os.path.join(bundle_dir, "units.bin"), "rb").read()
    if len(raw) % size:
        raise Refuse("truncated units.bin")
    audio = []
    for i in range(len(raw) // size):
        tag, lane, seq, fin, fout = struct.unpack_from("<IIIff", raw, i * size)
        audio.append((tag, lane, seq, fin, fout))
    rraw = open(os.path.join(bundle_dir, "regs.bin"), "rb").read()
    nreg = fp.N_REG
    regs = [struct.unpack_from(f"<{nreg}f", rraw, i * 4 * nreg)
            for i in range(len(rraw) // (4 * nreg))]
    return meta, coeffs, audio, regs


def check_control_plane(case, coeffs):
    """Both legs must have consumed the same control plane (fail-closed)."""
    plan = cp.build_plan(case)
    if len(plan) != len(coeffs):
        raise Refuse(f"plan has {len(plan)} blocks, bundle has {len(coeffs)}")
    for i, (p, rec) in enumerate(zip(plan, coeffs)):
        if int(rec["type"]) != fp.TYPE_LP24:
            raise Refuse(f"block {i}: bundle type {rec['type']} is not fut_lp24")
        if int(rec["sub"]) != p["sub"]:
            raise Refuse(f"block {i}: subtype {rec['sub']} != plan {p['sub']}")
        if bool(rec["first"]) != bool(p["reset"]):
            raise Refuse(f"block {i}: reset flag {rec['first']} != plan {p['reset']}")
        if cp.f32(rec["cut"]) != cp.f32(p["cut"]) or cp.f32(rec["reso"]) != cp.f32(p["res"]):
            raise Refuse(f"block {i}: control words differ "
                         f"({rec['cut']},{rec['reso']}) vs ({p['cut']},{p['res']})")
    return plan


class _ExternalCoefProvider:
    """L2b provider: the PINNED coefficients, quantized (attribution leg)."""

    def __init__(self, C, dC):
        self.C = list(C)
        self.dC = list(dC)


def _rms(vals):
    if not vals:
        return 0.0
    return math.sqrt(sum(v * v for v in vals) / len(vals))


def _audio_metrics(model_out, ref_q):
    n = min(len(model_out), len(ref_q))
    d = [a - b for a, b in zip(model_out[:n], ref_q[:n])]
    peak_ref = max((abs(v) for v in ref_q), default=1) or 1
    rms = _rms(d)
    return {
        "n": n,
        "max_abs_lsb": max((abs(v) for v in d), default=0),
        "rms_lsb": rms,
        "rms_db_rel_ref_peak": (20 * math.log10(rms / peak_ref)) if rms > 0 else -999.0,
        "ref_peak_lsb": peak_ref,
    }


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    if n < frame:
        return 1.0
    import numpy as np
    a = np.asarray(a[:n // frame * frame], dtype=float).reshape(-1, frame)
    b = np.asarray(b[:n // frame * frame], dtype=float).reshape(-1, frame)
    win = np.hanning(frame)
    ra = np.log1p(np.abs(np.fft.rfft(a * win, axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b * win, axis=1))).ravel()
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    den = math.sqrt(float((ra * ra).sum()) * float((rb * rb).sum()))
    return float((ra * rb).sum() / den) if den > 0 else 0.0


def run_case(case, coeffs, audio, regs, use_ref_coeffs=False, maker=None,
             kernel=None, subtype_override=None):
    """Drive the frozen model over the whole case; return metrics + trace.

    `maker`/`kernel`/`subtype_override` exist for the negative controls in
    `tools/lp24_negative_controls.py` (wrong algorithm, wrong subtype); the
    leaf's own legs always leave them unset.
    """
    plan = check_control_plane(case, coeffs)
    if len(audio) != len(plan) * cp.BLOCK_OS:
        raise Refuse(f"{len(audio)} OS samples for {len(plan)} blocks")

    unit = None
    cm = None
    out_model, ref_out = [], []
    l1_c, l1_dc, l1_rel = [], [], []
    l1_first = []        # construction-only error (FirstRun blocks: no smoothing)
    l1_idx = [0] * fp.N_COEF
    l3 = []
    peaks = []
    trace_blocks = []
    prev_sub = None

    for i, rec in enumerate(coeffs):
        lo, hi = i * cp.BLOCK_OS, (i + 1) * cp.BLOCK_OS
        block_in = [qintf(a[3]) for a in audio[lo:hi]]
        block_ref = [qintf(a[4]) for a in audio[lo:hi]]
        sub = int(rec["sub"])
        reset = bool(rec["first"])
        if prev_sub is not None and sub != prev_sub and not reset:
            raise Refuse(f"block {i}: subtype change without the engine reset flag")
        prev_sub = sub

        sub_model = sub if subtype_override is None else int(subtype_override)
        mk = maker or fp.LP24CoeffMaker
        kn = kernel or fp.LP24Unit
        if unit is None:
            unit = kn(sub_model)
            cm = mk(sub_model)
        elif reset:
            if sub_model != unit.subtype:
                unit.set_subtype(sub_model)
                cm = mk(sub_model)
            else:
                unit.reset_state()
                cm.reset()

        cut_q = qintf(float(rec["cut"]))
        reso_q = qintf(float(rec["reso"]))
        cm.make_coeffs(cut_q, reso_q)

        ref_C = [qintf(v) for v in rec["C"]]
        ref_dC = [qintf(v) for v in rec["dC"]]
        l1_c.extend(a - b for a, b in zip(cm.C, ref_C))
        l1_dc.extend(a - b for a, b in zip(cm.dC, ref_dC))
        l1_rel.extend(abs(a - b) / max(1.0, abs(b) / float(fp.ONE))
                      for a, b in zip(cm.C, ref_C))
        for j, (a, b) in enumerate(zip(cm.C, ref_C)):
            l1_idx[j] = max(l1_idx[j], abs(a - b))
        if reset:
            l1_first.extend(abs(a - b) for a, b in zip(cm.C, ref_C))

        provider = _ExternalCoefProvider(ref_C, ref_dC) if use_ref_coeffs else cm
        c_start = list(provider.C)
        d_start = list(provider.dC)
        outs, peak, c_end = unit.process_block(block_in, provider)
        if not use_ref_coeffs:
            # SurgeVoice::GetQFB(): the advanced kernel C is read back into
            # the coefficient maker after every block.
            cm.C = list(c_end)
        peaks.append(peak)
        out_model.extend(outs)
        ref_out.extend(block_ref)
        r_now = list(getattr(unit, "r", []))
        if i < len(regs) and r_now:
            l3.extend(a - qintf(b) for a, b in zip(r_now, regs[i]))
        trace_blocks.append({
            "b": i,
            "subtype": sub,
            "reset": reset,
            "cut_q": cut_q,
            "reso_q": reso_q,
            "C_start": c_start,
            "dC": d_start,
            "in": block_in,
            "out_model": outs,
            "out_ref_q": block_ref,
            "after": {"r": r_now, "C_end": list(c_end)},
        })

    res = {
        "case": case["case"],
        "model": kn.__name__ if unit else None,
        "subtype_override": subtype_override,
        "leg": "L2b-reference-coeffs" if use_ref_coeffs else "L2a-own-coeffs",
        "blocks": len(coeffs),
        "segments": 1 + max(p["seg"] for p in plan),
        "resets": sum(1 for p in plan if p["reset"]),
        "subtypes": sorted({int(r["sub"]) for r in coeffs}),
        "l1": {
            "C_max_lsb": max((abs(v) for v in l1_c), default=0),
            "C_rms_lsb": _rms(l1_c),
            "C_max_rel_lsb": max(l1_rel, default=0.0),
            "dC_max_lsb": max((abs(v) for v in l1_dc), default=0),
            "dC_rms_lsb": _rms(l1_dc),
            # Construction-only error: FirstRun blocks take the pinned
            # FromDirect fast path (C = tC = N), so no smoothing recursion and
            # no within-block C advance contribute.  The gap between this and
            # C_max_lsb is the smoothing/dC-quantization drift.
            "C_max_lsb_firstrun": max(l1_first, default=0),
            "C_max_lsb_per_index": l1_idx,
        },
        "audio": _audio_metrics(out_model, ref_out),
        "l3_reg_max_lsb": max((abs(v) for v in l3), default=0),
        "spectral_corr": spectral_corr(out_model, ref_out),
        "stability_peaks_max": max(peaks) if peaks else 0,
        "stability_verdict": fp.stability_verdict(peaks),
        "qmul_count": unit.qmul_count if unit else 0,
        "qmul_per_sample": (unit.qmul_count / len(out_model)) if out_model else 0.0,
    }
    return res, trace_blocks


def write_rtl_stimulus(trace_blocks, out_dir):
    """init/ctrl/in hex for the RTL exactness run.

    init.hex: [n_blocks]
    ctrl.hex: per block 18 words: flags(b0 active, b1 reset), subtype,
              C[8] block-start, dC[8]
    in.hex:   64 input words per block
    """
    rtl_dir = os.path.join(out_dir, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)
    with open(os.path.join(rtl_dir, "init.hex"), "w", encoding="utf-8") as f:
        f.write(f"{len(trace_blocks) & MASK32:08x}\n")
    n_in = 0
    with open(os.path.join(rtl_dir, "ctrl.hex"), "w", encoding="utf-8") as fc, \
            open(os.path.join(rtl_dir, "in.hex"), "w", encoding="utf-8") as fi:
        for blk in trace_blocks:
            flags = 1 | (2 if blk["reset"] else 0)
            words = [flags, blk["subtype"], *blk["C_start"], *blk["dC"]]
            fc.write("".join(f"{(w & MASK32):08x}\n" for w in words))
            for w in blk["in"]:
                fi.write(f"{(w & MASK32):08x}\n")
                n_in += 1
    return n_in


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--engine-coeffs", action="store_true",
                    help="L2b attribution leg: drive the kernel with the pinned coefficients")
    ap.add_argument("--no-trace", action="store_true",
                    help="skip writing model_trace.json / RTL stimulus")
    args = ap.parse_args()

    meta, coeffs, audio, regs = load_bundle(args.bundle)
    case_path = os.path.join(CASES_DIR, f"{meta['case']}.json")
    if not os.path.exists(case_path):
        raise Refuse(f"no committed case file for {meta['case']}")
    case = cp.load_case(case_path)

    res, trace_blocks = run_case(case, coeffs, audio, regs,
                                 use_ref_coeffs=args.engine_coeffs)
    os.makedirs(args.out_dir, exist_ok=True)
    res["bundle"] = os.path.abspath(args.bundle)
    res["reference"] = meta["reference"]
    res["carrier"] = meta["carrier"]
    res["filter"] = meta["filter"]
    res["overrides"] = meta.get("overrides", {})

    if not args.no_trace:
        trace = {
            "format": "sxt-038-lp24-trace/1",
            "case": meta["case"],
            "leg": res["leg"],
            "bundle": res["bundle"],
            "meta": meta,
            "summary": {k: v for k, v in res.items() if k != "trace_blocks"},
            "trace_blocks": trace_blocks,
        }
        with open(os.path.join(args.out_dir, "model_trace.json"), "w", encoding="utf-8") as f:
            json.dump(trace, f)
        res["rtl_input_words"] = write_rtl_stimulus(trace_blocks, args.out_dir)

    with open(os.path.join(args.out_dir, "leg.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
        f.write("\n")
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
    except fp.Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
