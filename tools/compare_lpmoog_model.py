#!/usr/bin/env python3
"""SXT-039 model-vs-reference comparison against [PROPOSED] budgets.

Compares the frozen model's run (`model/voice/filter_lpmoog/run_filter_leg.py`
-> model_trace.json) against the pinned-kernel reference streams rendered by
`tools/render_lpmoog_reference.py` (ref-<case>.f32 / refcoef-<case>.f32) and
writes one JSON verdict artifact per case.

Legs:
  L1  coefficient plane: model C[8]/dC[8] vs the pinned maker's C/dC
      (Q2.29 LSB)
  L1r register state:    model R[0..4] at every block end vs the pinned
      kernel's registers (Q10.21 LSB) -- reported, not budgeted
  L2  audio:             model output vs the pinned kernel output
      (Q10.21 LSB + log-spectral correlation)

The budgets below are PROPOSALS for the SXT-013/#12 fidelity freeze, NOT
frozen policy, and they are a faithful port of the SXT-037 filter-leaf
proposal class to this leaf's word lengths (the coefficient bounds are the
same VALUES, expressed in this leaf's finer Q2.29 coefficient word).  This
tool records achieved numbers and marks verdicts PENDING-FREEZE; it never
declares fidelity established, and it never says anything about how the
filter sounds.

The reference is the PINNED KERNEL, not the full engine: see
`reports/SXT-039/EVIDENCE.md` for exactly what that does and does not cover
(the engine-integrated leg is recorded NOT_RUN).

Usage:
  python3 tools/compare_lpmoog_model.py --run-dirs /tmp/run-* \
      --ref-dir reports/SXT-039/artifacts --out-dir reports/SXT-039/artifacts
"""

import argparse
import json
import math
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lpmoog"))

import voice_model as vm  # noqa: E402
import filter_lpmoog_model as fp  # noqa: E402

FQ = vm.FQ
CFQ = fp.COEF_FQ

# [PROPOSED] budgets -- not frozen, not tuned against achieved numbers.
PROPOSED = {
    "l1_C_max_lsb_q229": 4096,      # == 16 LSB in the SXT-037 Q10.21 proposal
    "l1_C_rms_lsb_q229": 1024,      # == 4 LSB in the SXT-037 Q10.21 proposal
    "l2_max_abs_lsb": 4096,         # ~0.2 % FS in Q10.21
    "l2_rms_lsb": 256,
    "l2_spectral_corr_min": 0.999,
}


def q(x, frac):
    return vm.sat(int(math.floor(x * (1 << frac) + 0.5)))


def read_f32(path):
    with open(path, "rb") as f:
        data = f.read()
    return struct.unpack(f"<{len(data) // 4}f", data)


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    if n < frame:
        return None
    import numpy as np
    a = np.asarray(a[:n // frame * frame], dtype=float).reshape(-1, frame)
    b = np.asarray(b[:n // frame * frame], dtype=float).reshape(-1, frame)
    win = np.hanning(frame)
    ra = np.log1p(np.abs(np.fft.rfft(a * win, axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(b * win, axis=1))).ravel()
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    d = math.sqrt(float((ra * ra).sum()) * float((rb * rb).sum()))
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def metrics(model, ref):
    n = min(len(model), len(ref))
    d = [a - b for a, b in zip(model[:n], ref[:n])]
    acc = sum(v * v for v in d)
    rms = math.sqrt(acc / n) if n else 0.0
    peak = max((abs(v) for v in ref), default=0)
    return {
        "n": n,
        "max_abs_lsb": max((abs(v) for v in d), default=0),
        "rms_lsb": rms,
        "ref_peak_lsb": peak,
        "rms_db_rel_ref_peak": (20 * math.log10(rms / peak)) if (rms > 0 and peak > 0)
        else None,
    }


def compare_case(run_dir, ref_dir):
    with open(os.path.join(run_dir, "model_trace.json"), encoding="utf-8") as f:
        trace = json.load(f)
    case = trace["meta"]["case"]
    ref = read_f32(os.path.join(ref_dir, f"ref-{case}.f32"))
    coefs = read_f32(os.path.join(ref_dir, f"refcoef-{case}.f32"))
    n_blocks = trace["n_blocks"]
    if len(coefs) != n_blocks * 21:
        raise SystemExit(f"[refused] {case}: reference coefficient dump has "
                         f"{len(coefs)} floats, expected {n_blocks * 21}")

    model_out = [v for blk in trace["trace_blocks"] for v in blk["out_model"]]
    ref_q = [q(v, FQ) for v in ref]
    l2 = metrics(model_out, ref_q)
    l2["spectral_corr"] = spectral_corr(model_out, ref_q)

    dC_err = []
    C_err = []
    R_err = []
    for i, blk in enumerate(trace["trace_blocks"]):
        base = i * 21
        for j in range(8):
            C_err.append(blk["C_start"][j] - q(coefs[base + j], CFQ))
            dC_err.append(blk["dC"][j] - q(coefs[base + 8 + j], CFQ))
        for j in range(5):
            R_err.append(blk["after"]["r"][j] - q(coefs[base + 16 + j], FQ))

    def agg(vals):
        return {"max_abs": max((abs(v) for v in vals), default=0),
                "rms": math.sqrt(sum(v * v for v in vals) / len(vals)) if vals else 0.0}

    l1_C = agg(C_err)
    l1_dC = agg(dC_err)
    l1_R = agg(R_err)

    l1_pass = (l1_C["max_abs"] <= PROPOSED["l1_C_max_lsb_q229"]
               and l1_C["rms"] <= PROPOSED["l1_C_rms_lsb_q229"])
    corr = l2["spectral_corr"]
    l2_pass = (l2["max_abs_lsb"] <= PROPOSED["l2_max_abs_lsb"]
               and l2["rms_lsb"] <= PROPOSED["l2_rms_lsb"]
               and (corr is None or corr >= PROPOSED["l2_spectral_corr_min"]))
    return {
        "schema_version": 1,
        "issue": "SXT-039",
        "case": case,
        "leg": "L2-kernel (pinned sst-filters kernel, standalone build; the "
               "engine-integrated leg is NOT_RUN -- see reports/SXT-039/EVIDENCE.md)",
        "carrier": trace["meta"]["carrier"]["rel"],
        "override": trace["meta"]["override"],
        "fenv_source": trace["meta"]["fenv_source"],
        "subtypes": trace["subtypes"],
        "L1_coefficients_q229": {"C": l1_C, "dC": l1_dC},
        "L1_registers_q1021_reported_not_budgeted": l1_R,
        "L2_audio_q1021": l2,
        "model_stability": trace["stability_verdict"],
        "model_state_peak_lsb": max(trace["stability_peaks"] or [0]),
        "proposed": PROPOSED,
        "verdicts": {
            "L1_coefficients": "PASS" if l1_pass else "FAIL",
            "L2_audio": "PASS" if l2_pass else "FAIL",
        },
        "verdict": ("PASS (PENDING-FREEZE: budgets are proposals, not frozen policy)"
                    if (l1_pass and l2_pass) else "FAIL against proposed budgets"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dirs", nargs="+", required=True)
    ap.add_argument("--ref-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    any_fail = False
    for run_dir in args.run_dirs:
        res = compare_case(run_dir, args.ref_dir)
        path = os.path.join(args.out_dir, f"budget-{res['case']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
        corr = res["L2_audio_q1021"]["spectral_corr"]
        print(f"{res['case']:9s} L1 max={res['L1_coefficients_q229']['C']['max_abs']:6d} "
              f"L2 max={res['L2_audio_q1021']['max_abs_lsb']:6d} "
              f"rms={res['L2_audio_q1021']['rms_lsb']:9.2f} "
              f"corr={corr if corr is None else round(corr, 5)} -> {res['verdict']}")
        if res["verdict"].startswith("FAIL"):
            any_fail = True
    # A budget miss is a RECORDED finding, not a tool error: exit 0 either way
    # so the achieved numbers are always written; the verdicts carry the
    # outcome.
    return 0 if not any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
