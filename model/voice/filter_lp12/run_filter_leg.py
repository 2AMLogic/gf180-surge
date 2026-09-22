#!/usr/bin/env python3
"""SXT-037 filter-leg runner: tap bundle -> frozen model -> metrics + RTL stimulus.

A tap bundle is produced by `tools/render_lp12_reference.py` through the
ORACLE TAP INSTRUMENTATION (decision-records/0005): a DSP-neutral,
externally patched build of the pinned engine that writes, per rendered
fixture,

  coeffs.jsonl  one record per (block, unit, voice-lane): the engine's
                cutoff/reso inputs to MakeCoeffs and its C[8]/dC[8] results
                (block-start coefficients after FromDirect smoothing), plus
                the pre-call FirstRun flag, type, and subtype;
  units.bin     per OS sample per wrapped LP12 unit call: tag (0=unit1,
                1=unit2), active SIMD lane, OS-sample sequence, the filter
                input and the filter output as float32.

This runner drives the FROZEN fixed-point model (filter_lp12_model.py) with
the bundle's control plane and input signal, and reports:

  L1  model coefficients vs engine coefficients (coefficient plane)
  L2a model audio path (own coefficients) vs engine filter output
  L2b model audio path driven by ENGINE coefficients (diagnostic
      attribution leg)

and writes the RTL stimulus (rtl/*.hex) + model trace for the exactness
harness.  Fail-closed: missing fields, subtype changes without an engine
reset flag, sample-count misalignment, or out-of-scope parameters are
REFUSED (exit 2), never guessed around.

Usage:
  python3 model/voice/filter_lp12/run_filter_leg.py --bundle DIR --out-dir DIR
"""

import argparse
import json
import math
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import voice_model as vm  # noqa: E402
import filter_lp12_model as fp  # noqa: E402

BLOCK_OS = vm.BLOCK_SIZE_OS
UNIT_NAMES = {0: "unit1", 1: "unit2"}
TAG_BITS = 0
MASK32 = (1 << 32) - 1


def qintf(x):
    """Quantize an engine float32 to Q10.21 round-half-up (declared)."""
    return vm.sat(int(math.floor(x * (1 << vm.FQ) + 0.5)))


class Refuse(Exception):
    pass


def load_bundle(bundle_dir):
    with open(os.path.join(bundle_dir, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    coeffs = []
    with open(os.path.join(bundle_dir, "coeffs.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                coeffs.append(json.loads(line))
    records = []
    size = struct.calcsize("<IIIff")
    with open(os.path.join(bundle_dir, "units.bin"), "rb") as f:
        while True:
            buf = f.read(size)
            if len(buf) == 0:
                break
            if len(buf) != size:
                raise Refuse("truncated units.bin record")
            tag, lane, seq, fin, fout = struct.unpack("<IIIff", buf)
            records.append((tag, lane, seq, fin, fout))
    return meta, coeffs, records


def group_streams(coeffs, records):
    """Group into per-instance coefficient and audio streams.

    An instance is (unit_tag, lane).  The audio stream is the per-tag
    record sequence; the coefficient stream for an instance is the
    subsequence of that unit's records carrying the instance's lane.
    """
    audio = {}
    for tag, lane, seq, fin, fout in records:
        audio.setdefault((tag, lane), []).append((seq, fin, fout))
    coef = {}
    for rec in coeffs:
        coef.setdefault((rec["unit"], rec["lane"]), []).append(rec)
    inst = sorted(set(audio) | set(coef))
    for key in inst:
        a = audio.get(key, [])
        c = coef.get(key, [])
        if len(a) != len(c) * BLOCK_OS:
            raise Refuse(f"instance {key}: {len(a)} OS samples vs "
                         f"{len(c)} coefficient records ({len(c) * BLOCK_OS} expected)")
        seqs = [s for s, _, _ in a]
        if any(b <= a_ for a_, b in zip(seqs, seqs[1:])):
            raise Refuse(f"instance {key}: unit-sample sequence not monotone")
        for r in c:
            if r.get("type") != fp.TYPE_LP12:
                raise Refuse(f"instance {key}: non-LP12 type {r.get('type')} in bundle")
        # OS-sample sequence numbers are a per-tag counter shared across
        # lanes, so per-lane values are strictly monotone but not contiguous;
        # record order defines block order within an instance.
    return inst, audio, coef


def run_instance(key, audio, coef, use_engine_coeffs=False):
    """Drive one filter instance through the frozen model; return metrics."""
    tag, lane = key
    unit = None
    cm = None
    out_model = []
    eng_ref = []
    l1_c, l1_dc = [], []
    peaks = []
    firsts = 0
    sub_changes = 0
    prev_sub = None
    trace_blocks = []
    for i, rec in enumerate(coef):
        block_in = [vm.sat(int(math.floor(fin * (1 << vm.FQ) + 0.5)))
                    for (_, fin, _) in audio[i * BLOCK_OS:(i + 1) * BLOCK_OS]]
        block_ref = [vm.sat(int(math.floor(fout * (1 << vm.FQ) + 0.5)))
                     for (_, _, fout) in audio[i * BLOCK_OS:(i + 1) * BLOCK_OS]]
        sub = int(rec["sub"])
        if prev_sub is not None and sub != prev_sub:
            sub_changes += 1
            if not rec.get("first", False):
                raise Refuse(f"instance {key}: subtype change at record {i} "
                             "without engine reset flag (FirstRun)")
        prev_sub = sub
        if rec.get("first", False):
            firsts += 1
            if unit is None:
                unit = fp.LP12Unit(sub)
                cm = fp.LP12CoeffMaker(sub)
            else:
                if sub != unit.subtype:
                    unit.set_subtype(sub)
                    cm = fp.LP12CoeffMaker(sub)
                else:
                    unit.reset_state()
                    cm.reset()
        if unit is None:
            # stream began without a first-run marker: start cold (declared)
            unit = fp.LP12Unit(sub)
            cm = fp.LP12CoeffMaker(sub)
        cut_q = qintf(float(rec["cut"]))
        reso_q = qintf(float(rec["reso"]))
        cm.make_coeffs(cut_q, reso_q)

        eng_C = [qintf(float(v)) for v in rec["C"]]
        eng_dC = [qintf(float(v)) for v in rec["dC"]]
        l1_c.append([a - b for a, b in zip(cm.C, eng_C)])
        l1_dc.append([a - b for a, b in zip(cm.dC, eng_dC)])

        if use_engine_coeffs:
            provider = _ExternalCoefProvider(eng_C, eng_dC)
        else:
            provider = cm
        c_start = list(provider.C)
        d_start = list(provider.dC)
        outs, peak, c_end = unit.process_block(block_in, provider)
        # the voice path reads the advanced kernel C back into the
        # coefficient maker after every block (SurgeVoice.cpp GetQFB:
        # CM[u].C[i] = get1f(fbq->FU[u].C[i], fbqi)); mirror it exactly
        if not use_engine_coeffs:
            cm.C = list(c_end)
        peaks.append(peak)
        out_model.extend(outs)
        eng_ref.extend(block_ref)
        trace_blocks.append({
            "b": i,
            "subtype": sub,
            "reset": bool(rec.get("first", False)),
            "cut_q": cut_q, "reso_q": reso_q,
            "C_start": c_start,
            "dC": d_start,
            "in": block_in,
            "out_model": outs,
            "out_engine_q": block_ref,
            "after": {"r0": unit.r0, "r1": unit.r1, "r_clip": unit.r_clip,
                      "C_end": list(c_end)},
        })
    return {
        "key": {"tag": tag, "lane": lane, "name": UNIT_NAMES.get(tag, f"tag{tag}")},
        "blocks": len(coef),
        "subtypes": sorted({int(r["sub"]) for r in coef}),
        "first_runs": firsts,
        "subtype_changes": sub_changes,
        "l1_C_max": max((abs(v) for row in l1_c for v in row), default=0),
        "l1_C_rms": _rms(l1_c),
        "l1_dC_max": max((abs(v) for row in l1_dc for v in row), default=0),
        "l1_dC_rms": _rms(l1_dc),
        "l2a": _audio_metrics(out_model, eng_ref),
        "stability_peaks": peaks,
        "qmul_count": unit.qmul_count if unit else 0,
        "trace_blocks": trace_blocks,
    }


class _ExternalCoefProvider:
    """Diagnostic L2b provider: ENGINE coefficients, quantized."""

    def __init__(self, C, dC):
        self.C = list(C)
        self.dC = list(dC)


def _rms(rows):
    acc = 0
    n = 0
    for row in rows:
        for v in row:
            acc += v * v
            n += 1
    return math.sqrt(acc / n) if n else 0.0


def _audio_metrics(model_out, engine_q):
    n = min(len(model_out), len(engine_q))
    d = [a - b for a, b in zip(model_out[:n], engine_q[:n])]
    acc = sum(v * v for v in d)
    peak_e = max((abs(v) for v in engine_q), default=1) or 1
    return {
        "n": n,
        "max_abs_lsb": max((abs(v) for v in d), default=0),
        "rms_lsb": math.sqrt(acc / n) if n else 0.0,
        "rms_db_rel_engine_peak": (20 * math.log10(math.sqrt(acc / n) / peak_e))
        if n and acc else -999.0,
        "engine_peak_lsb": peak_e,
    }


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    if n < frame:
        return 1.0
    import numpy as np
    a = np.asarray(a[:n // frame * frame], dtype=float).reshape(-1, frame)
    b = np.asarray(b[:n // frame * frame], dtype=float).reshape(-1, frame)
    ra = np.log1p(np.abs(np.fft.rfft(a * np.hanning(frame), axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b * np.hanning(frame), axis=1))).ravel()
    ra -= ra.mean()
    rb -= rb.mean()
    d = math.sqrt((ra * ra).sum() * (rb * rb).sum())
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def write_rtl_stimulus(inst_res, out_dir, which=0):
    """Write init/ctrl/in hex for one instance for the RTL exactness run.

    init.hex: [n_blocks]
    ctrl.hex: per block, 18 words: flags(b0 active, b1 reset), subtype,
              C[8] block-start, dC[8]
    in.hex:   64 input words per block
    """
    rtl_dir = os.path.join(out_dir, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)
    res = inst_res[which]
    assert res.get("stimulated", True), "stimulated instance mismatch"
    inp = []
    with open(os.path.join(rtl_dir, "init.hex"), "w", encoding="utf-8") as f:
        f.write(f"{res['blocks'] & MASK32:08x}\n")
    with open(os.path.join(rtl_dir, "ctrl.hex"), "w", encoding="utf-8") as f:
        for blk in res["trace_blocks"]:
            flags = 1 | (2 if blk["reset"] else 0)
            words = [flags, blk["subtype"], *blk["C_start"], *blk["dC"]]
            f.write("".join(f"{(w & MASK32):08x}\n" for w in words))
            inp.extend(blk["in"])
    with open(os.path.join(rtl_dir, "in.hex"), "w", encoding="utf-8") as f:
        for w in inp:
            f.write(f"{(w & MASK32):08x}\n")
    return len(inp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--engine-coeffs", action="store_true",
                    help="L2b diagnostic: drive the kernel with engine coefficients")
    args = ap.parse_args()

    meta, coeffs, records = load_bundle(args.bundle)
    inst, audio, coef = group_streams(coeffs, records)
    os.makedirs(args.out_dir, exist_ok=True)

    results = []
    for key in inst:
        res = run_instance(key, audio[key], coef[key],
                           use_engine_coeffs=args.engine_coeffs)
        res["spectral_corr"] = spectral_corr(
            [v for blk in res["trace_blocks"] for v in blk["out_model"]],
            [v for blk in res["trace_blocks"] for v in blk["out_engine_q"]])
        res["leg"] = "L2b-engine-coeffs" if args.engine_coeffs else "L2a-own-coeffs"
        results.append(res)
    which_default = 0
    if results:
        # stimulate the instance carrying the subtype transitions when any
        primary = next((i for i, r in enumerate(results)
                        if r["subtype_changes"] or len(r["subtypes"]) > 1), 0)
        most_blocks = max(range(len(results)), key=lambda i: results[i]["blocks"])
        which_default = primary if results[primary]["blocks"] >= (results[most_blocks]["blocks"] // 4) else most_blocks
        results[which_default]["stimulated"] = True
        for i, r in enumerate(results):
            if i != which_default:
                r["stimulated"] = False

    trace = {
        "format": "sxt-037-lp12-trace/1",
        "leg": results[0]["leg"] if results else None,
        "bundle": os.path.abspath(args.bundle),
        "meta": meta,
        "stimulated_instance": which_default,
        "instances": [{k: v for k, v in r.items() if k != "trace_blocks"}
                      for r in results],
    }
    with open(os.path.join(args.out_dir, "model_trace.json"), "w", encoding="utf-8") as f:
        json.dump({**trace, "instances": [
            {**{k: v for k, v in r.items() if k != "trace_blocks"},
             "trace_blocks": r["trace_blocks"]} for r in results]}, f, indent=1)
    n_in = write_rtl_stimulus(results, args.out_dir, which_default)
    print(json.dumps({
        "instances": [{k: v for k, v in r.items()
                       if k in ("key", "blocks", "subtypes", "l1_C_max", "l1_C_rms",
                                "l2a", "spectral_corr", "leg")}
                      for r in results],
        "rtl_input_words": n_in,
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
