#!/usr/bin/env python3
"""SXT-039 cost accounting: measured MAC (qmul) counts and state words of the
frozen LP Legacy Ladder schedule.

Planning numbers only, at the declared assumption of 1 MAC/cycle (A-DSP-1c):
no clock, timing, area, power, synthesis or hardware claim of any kind is made
or implied.  The counts are the model's own `qmul` calls (the same products
the RTL performs -- the testbench's `qmul_count` is the cross-check).

Usage:
  python3 tools/count_lpmoog_model_qmuls.py --out reports/SXT-039/artifacts/costs.json
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lpmoog"))

import fixtures as fx  # noqa: E402
import run_filter_leg as rfl  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = {}
    for case in sorted(fx.CASES):
        trace = rfl.run_case(case)
        samples = trace["n_blocks"] * 64
        rows[case] = {
            "blocks": trace["n_blocks"],
            "os_samples": samples,
            "qmul_total": trace["qmul_count"],
            "qmul_per_os_sample": trace["qmul_count"] / samples,
        }

    out = {
        "schema_version": 1,
        "issue": "SXT-039",
        "assumption": "1 MAC/cycle (A-DSP-1c); block-rate coefficient recompute "
                      "amortised over 64 OS samples (one make_coeffs per block)",
        "per_instance_state_bits": {
            "ladder_registers": 5 * 32,
            "coefficient_plane_C_dC": 16 * 32,
            "coefficient_maker_tC (control plane)": 8 * 32,
            "note": "R[0..3] are the four ladder stages, R[4] the previous "
                    "R[3]; per-instance, never shared (AGENTS.md state rule)",
        },
        "per_os_sample_products": {
            "coefficient_products": 6,
            "softclip8_products": 3,
            "total_qmul": 9,
            "adds_saturating": 11,
            "audio_rate_divisions": 0,
        },
        "sxt016_probe_rows_for_context_not_reconciled": {
            "probe_filter__svf_tdf2_block_coeffs__a24__m32__onchip": {
                "cyc_filter_unit_frame": 1536000, "state_bytes": 192},
            "probe_filter__k35_ladder_tanh_poly__a24__m32__onchip": {
                "cyc_filter_unit_frame": 3840000, "state_bytes": 584},
            "note": "planning rows at their own declared per-kernel assumptions "
                    "(nearest structural analogues: the SVF row for a block-rate "
                    "coefficient plane, the K35 ladder row for a 4-stage ladder "
                    "with a nonlinearity).  No SXT-016 probe exists for "
                    "fut_lpmoog; the divergence is RECORDED, not reconciled "
                    "away, and an SXT-016-class probe is required before any "
                    "profile freeze.",
        },
        "cases": rows,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    for case, r in rows.items():
        print(f"{case:9s} qmul={r['qmul_total']:8d} "
              f"({r['qmul_per_os_sample']:.1f}/OS sample)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
