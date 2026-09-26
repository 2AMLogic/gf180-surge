#!/usr/bin/env python3
"""SXT-022 (#123): score the two candidate HalfbandD2 branch assignments
against the PINNED `HalfRateFilter::process_block_D2` kernel.

Context
-------
`model/voice/voice_model.py::HalfbandD2` reconstructs the decimated output
from two 6-stage allpass cascades (coefficient sets A and B).  Two readings
of the pinned kernel are possible, and the pinned header's own prose comment
and its code disagree with each other:

  a_even : out[n] = (A[2n] + B[2n+1]) * 0.5   <- what the header's PROSE says
  b_even : out[n] = (B[2n] + A[2n+1]) * 0.5   <- what the header's CODE does

Reading cannot settle that.  This tool settles it by EXECUTION: it runs the
pinned kernel (via `oracle/sxt022/build_halfband_probe.sh`, whose binary is a
GPL combined work kept outside this repository — decision-records/0009,0010),
then replicates both candidate reconstructions in float64 from the SAME
coefficients the model uses, and reports each candidate's agreement with the
pinned output plus the passband/stopband response of each.

It makes NO fidelity claim and NO listening claim.  It establishes exactly
one thing: which scalar reconstruction reproduces the pinned kernel.

Usage:
  ./oracle/sxt022/build_halfband_probe.sh            # build once (external)
  python3 tools/halfband_d2_ordering_probe.py \
      --probe ~/.cache/sxt022-oracle/halfband_d2_probe \
      --json reports/halfband-branch-order/artifacts/pinned-kernel-ordering-probe.json
"""

import argparse
import json
import math
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402

ORDERS = ("a_even", "b_even")


def cascade_float(coeffs, xs):
    """y[n] = x[n-2] + a * (x[n] - y[n-2]) per stage, in float64."""
    v = list(xs)
    for a in coeffs:
        x = [0.0, 0.0, 0.0]
        y = [0.0, 0.0, 0.0]
        out = []
        for s in v:
            yn = x[1] + a * (s - y[1])
            x = [s, x[0], x[1]]
            y = [yn, y[0], y[1]]
            out.append(yn)
        v = out
    return v


def reconstruct(order, chain_a, chain_b, n_in):
    if order == "a_even":
        return [(chain_a[2 * n] + chain_b[2 * n + 1]) * 0.5
                for n in range(n_in // 2)]
    return [(chain_b[2 * n] + chain_a[2 * n + 1]) * 0.5
            for n in range(n_in // 2)]


def model_float(order, xs):
    """Float64 stand-in for the scalar model, both candidate orderings."""
    chain_a = cascade_float(vm.HALFBAND_A, xs)
    chain_b = cascade_float(vm.HALFBAND_B, xs)
    return reconstruct(order, chain_a, chain_b, len(xs))


def rms(v):
    if not v:
        return 0.0
    return math.sqrt(sum(x * x for x in v) / len(v))


def db(x, floor=-200.0):
    return floor if x <= 0 else 20.0 * math.log10(x)


def parse_probe(text):
    """-> {case_name: {"in": [...], "out": [...]}} in emission order."""
    cases = {}
    order = []
    cur = None
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "case":
            cur = parts[1]
            cases[cur] = {"in": [], "out": []}
            order.append(cur)
        elif parts[0] in ("in", "out"):
            if cur is None:
                raise SystemExit("probe output: sample record before any case")
            cases[cur][parts[0]].append(float(parts[2]))
    if not order:
        raise SystemExit("probe output: no cases found")
    return cases, order


def response_table(fracs, n=16384, warmup=2048):
    """Passband/stopband response of each ordering, RMS dB re: input RMS.

    `warmup` leading samples are discarded so the measurement is of the
    steady state, not the allpass start-up transient.
    """
    rows = []
    for f in fracs:
        xs = [math.sin(2.0 * math.pi * f * i) for i in range(n)]
        row = {"f_of_input_rate": f, "input_rms_db": db(rms(xs))}
        for order in ORDERS:
            out = model_float(order, xs)
            row[order + "_rms_db"] = db(rms(out[warmup // 2:]))
        rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", default=os.path.expanduser(
        "~/.cache/sxt022-oracle/halfband_d2_probe"),
        help="path to the externally built pinned-kernel probe binary")
    ap.add_argument("--json", help="write the full result JSON here")
    args = ap.parse_args()

    if not os.path.exists(args.probe):
        print("REFUSING: pinned-kernel probe binary not found: %s\n"
              "Build it first: ./oracle/sxt022/build_halfband_probe.sh"
              % args.probe, file=sys.stderr)
        return 2

    text = subprocess.run([args.probe], check=True, capture_output=True,
                          text=True).stdout
    cases, case_order = parse_probe(text)

    per_case = []
    totals = {o: 0.0 for o in ORDERS}
    for name in case_order:
        xs = cases[name]["in"]
        ref = cases[name]["out"]
        ref_peak = max((abs(v) for v in ref), default=0.0)
        # Normalize by the INPUT full scale, not the reference peak: a
        # stopband case has a near-zero reference peak, and dividing by it
        # would inflate a float32-rounding residual into a false mismatch.
        in_peak = max((abs(v) for v in xs), default=0.0) or 1.0
        row = {"case": name, "n_in": len(xs), "n_out": len(ref),
               "ref_peak": ref_peak, "in_peak": in_peak}
        for order in ORDERS:
            got = model_float(order, xs)
            if len(got) != len(ref):
                raise SystemExit("length mismatch on case %s" % name)
            err = max(abs(a - b) for a, b in zip(got, ref))
            row[order + "_max_abs_err"] = err
            row[order + "_err_re_input_fs"] = err / in_peak
            totals[order] = max(totals[order], row[order + "_err_re_input_fs"])
        per_case.append(row)

    # float32 accumulation in the pinned kernel vs float64 here: a match is
    # "at float32 rounding", not bit-exact.  A mismatch is gross (order 1).
    TOL = 1e-5
    matching = [o for o in ORDERS if totals[o] <= TOL]
    verdict = ("PASS" if len(matching) == 1 else "AMBIGUOUS")

    result = {
        "issue": "SXT-022 / #123",
        "claim": "which scalar reconstruction reproduces the PINNED "
                 "HalfRateFilter(M=6, steep)::process_block_D2 kernel",
        "not_claimed": ["model-vs-Surge-engine fidelity", "preset support",
                        "musical quality", "any hardware result"],
        "pinned_submodule": "libs/sst/sst-filters",
        "candidate_orderings": {
            "a_even": "out[n] = (A[2n] + B[2n+1]) * 0.5  (pinned header PROSE)",
            "b_even": "out[n] = (B[2n] + A[2n+1]) * 0.5  (pinned header CODE)",
        },
        "match_tolerance_err_re_input_fs": TOL,
        "worst_err_re_input_fs": totals,
        "matching_ordering": matching[0] if len(matching) == 1 else None,
        "verdict": verdict,
        "cases": per_case,
        "response_rms_db": response_table([0.05, 0.15, 0.25, 0.30, 0.45]),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, sort_keys=True)
            f.write("\n")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
