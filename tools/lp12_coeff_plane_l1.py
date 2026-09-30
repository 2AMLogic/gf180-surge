#!/usr/bin/env python3
"""SXT-037 coefficient-plane (L1) leg from the committed coeffs.jsonl alone.

Why this exists (#102, findings F-038-3 / F-038-4): three of the eight
committed SXT-037 tap bundles (`badnews-cut-hi`, `badnews-cut-lo`,
`t9-substd`) carry only `coeffs.jsonl` + `meta.json` (their `units.bin`
audio taps were not committed), so `model/voice/filter_lp12/run_filter_leg.py`
cannot run on them.  The L1 leg does not depend on the audio at all: the
model's block-start coefficients depend only on the control plane
(cutoff/reso/subtype/FirstRun from the engine records) and on the per-block
C read-back, and the kernel's `C[i] += dC[i]` reload is independent of the
input signal.  This tool therefore drives `run_filter_leg.run_instance`
with a ZERO input stream and reports only the L1 fields — the exact same
code path and arithmetic as the full leg (checked: on every bundle that
does carry audio taps the L1 numbers are identical to the full run's).

Reported per instance: L1 max/rms over C and dC (the SXT-037 budget
fields), a per-coefficient-role max|ΔC| breakdown (C0..C7), and the
first-run-only max (pure construction error, no smoothing drift).  L2 audio
legs are NOT produced here; they need the audio taps.

`--model-file` loads an alternative `filter_lp12_model.py` (e.g. the
pre-#102 model extracted with `git show <rev>:model/voice/filter_lp12/
filter_lp12_model.py`) so the before/after comparison is reproducible from
committed sources.

Usage:
  python3 tools/lp12_coeff_plane_l1.py [--model-file PATH] [--label NAME] \\
      [--artifacts reports/sxt-037/artifacts] [--out JSON]

Original to this repository (Apache-2.0); no engine source is copied.
"""

import argparse
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEG_DIR = os.path.join(REPO, "model", "voice", "filter_lp12")
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, LEG_DIR)

PROPOSED = {"l1_C_max_lsb": 16, "l1_C_rms_lsb": 4}   # tools/compare_lp12_model.py
CASES = ("badnews", "rainy", "t9", "badnews-reso1", "badnews-cut-hi",
         "badnews-cut-lo", "t9-substd", "badnews-toggle")


def _load_model(path):
    if path:
        spec = importlib.util.spec_from_file_location("filter_lp12_model", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["filter_lp12_model"] = mod
        spec.loader.exec_module(mod)
    import run_filter_leg as leg  # noqa: E402  (binds to the loaded model)
    return leg


def _coeff_streams(bundle, _leg=None):
    coef = {}
    with open(os.path.join(bundle, "coeffs.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                coef.setdefault((rec["unit"], rec["lane"]), []).append(rec)
    return coef


def _db_table(x):
    """Surge's interpolated dB table (table_dB[i] = 10^(0.05 (i-384)), lerp)."""
    xf = x + 384.0
    e = int(xf)
    a = xf - e
    return ((1 - a) * 10.0 ** (0.05 * ((e & 511) - 384))
            + a * 10.0 ** (0.05 * (((e + 1) & 511) - 384)))


def discriminate(bundle):
    """Which construction does the ENGINE's own coefficient plane follow?

    Reconstructs the engine's per-block target word N from its tapped
    FromDirect state (FirstRun: N = C; otherwise tC = C + 64 dC and
    N = tC_prev + (tC - tC_prev)/0.2), in double from the float32 taps, and
    reports max/median |N - hypothesis| for:
      F-038-3  Standard C0 = F1 with sampleRateInv = 1/48000 vs 1/96000
               (only records whose F1 is not on the 0.11 clamp at 48000);
      F-038-4  Driven C7 = clipscale via Surge's dB table vs exact pow.
    Model-free: uses only the committed engine taps and the cited formulas.
    """
    import math
    acc = {"F-038-3 C0 sr=48000": [], "F-038-3 C0 sr=96000": [],
           "F-038-4 C7 dB-table": [], "F-038-4 C7 exact-pow": []}
    streams = _coeff_streams(bundle, None)
    for recs in streams.values():
        prev = {}
        for r in recs:
            sub = int(r["sub"])
            for idx in (0, 7):
                tc = float(r["C"][idx]) + 64.0 * float(r["dC"][idx])
                if r.get("first", False) or idx not in prev:
                    n = float(r["C"][idx])
                else:
                    n = prev[idx] + (tc - prev[idx]) / 0.2
                prev[idx] = tc
                if sub == 0 and idx == 0:
                    f = 440.0 * 2.0 ** (float(r["cut"]) / 12.0)
                    if f * 0.5 / 48000.0 < 0.11:
                        acc["F-038-3 C0 sr=48000"].append(
                            abs(n - 2 * math.sin(math.pi * f * 0.5 / 48000.0)))
                        acc["F-038-3 C0 sr=96000"].append(
                            abs(n - 2 * math.sin(math.pi * min(0.11, f * 0.5 / 96000.0))))
                if sub == 1 and idx == 7:
                    fq = min(max(float(r["cut"]), -55.0), 75.0) * 0.55
                    acc["F-038-4 C7 dB-table"].append(abs(n - _db_table(fq) / 64.0))
                    acc["F-038-4 C7 exact-pow"].append(abs(n - 10.0 ** (0.05 * fq) / 64.0))
    out = {}
    for k, v in acc.items():
        if v:
            s = sorted(v)
            out[k] = {"records": len(v), "max_abs": s[-1], "median_abs": s[len(s) // 2]}
    return out


def run_case(bundle, leg):
    out = []
    for key, recs in sorted(_coeff_streams(bundle, leg).items()):
        zeros = [(i, 0.0, 0.0) for i in range(len(recs) * leg.BLOCK_OS)]
        res = leg.run_instance(key, zeros, recs)
        per_role = [0] * 8
        first_max = 0
        for blk, rec in zip(res["trace_blocks"], recs):
            eng = [leg.qintf(float(v)) for v in rec["C"]]
            d = [abs(a - b) for a, b in zip(blk["C_start"], eng)]
            per_role = [max(p, v) for p, v in zip(per_role, d)]
            if rec.get("first", False):
                first_max = max(first_max, max(d))
        out.append({
            "instance": f"{res['key']['name']}.lane{key[1]}",
            "subtypes": res["subtypes"],
            "blocks": res["blocks"],
            "l1_C_max": res["l1_C_max"],
            "l1_C_rms": round(res["l1_C_rms"], 3),
            "l1_dC_max": res["l1_dC_max"],
            "l1_dC_rms": round(res["l1_dC_rms"], 3),
            "l1_C_max_per_role": per_role,
            "l1_first_run_only_max": first_max,
            "L1_verdict": "PASS" if (res["l1_C_max"] <= PROPOSED["l1_C_max_lsb"]
                                     and res["l1_C_rms"] <= PROPOSED["l1_C_rms_lsb"])
            else "FAIL",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-file", default=None)
    ap.add_argument("--label", default="current")
    ap.add_argument("--artifacts", default=os.path.join(REPO, "reports", "sxt-037",
                                                         "artifacts"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    leg = _load_model(args.model_file)
    result = {
        "schema_version": 1,
        "issue": "#102 (SXT-037 follow-up, F-038-3/F-038-4)",
        "leg": "L1 coefficient plane (zero-input drive; audio-independent)",
        "label": args.label,
        "model_file": os.path.relpath(leg.fp.__file__, REPO)
        if leg.fp.__file__.startswith(REPO) else os.path.basename(leg.fp.__file__),
        "proposed": PROPOSED,
        "cases": {},
    }
    for case in CASES:
        bundle = os.path.join(args.artifacts, "bundle-" + case)
        if not os.path.exists(os.path.join(bundle, "coeffs.jsonl")):
            result["cases"][case] = "NOT_RUN (no coeffs.jsonl)"
            continue
        result["cases"][case] = run_case(bundle, leg)
        result.setdefault("engine_plane_discrimination", {})[case] = discriminate(bundle)
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    for case, rows in result["cases"].items():
        if isinstance(rows, str):
            print(f"{case}: {rows}")
            continue
        for r in rows:
            print(f"{case:15s} {r['instance']:12s} subs={r['subtypes']} "
                  f"L1max={r['l1_C_max']} rms={r['l1_C_rms']} first={r['l1_first_run_only_max']} "
                  f"roles={r['l1_C_max_per_role']} {r['L1_verdict']}")
    for case, disc in result.get("engine_plane_discrimination", {}).items():
        for k, v in disc.items():
            print(f"engine plane {case:15s} {k:22s} n={v['records']:5d} "
                  f"max={v['max_abs']:.3e} median={v['median_abs']:.3e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
