#!/usr/bin/env python3
"""SXT-028e state residency + external-memory traffic (SXT-015 accounting).

Measured from the frozen model's own state layout and per-instance
transaction counters — nothing is estimated by hand.

Result class for Distortion: this effect owns NO delay-line-class buffer.
Its entire per-instance state is small on-chip state (biquad registers,
halfband allpass registers, two feedback words, two gain ramps). External
writable-memory residency and traffic are therefore ZERO words/sample, and
the "long buffers external-writable, never flash" rule is vacuously
satisfied (there is nothing long to place). The FIT verdict against a
profile-v1 cost envelope is still [PENDING-SXT-016] — this file reports the
measured demand, not a fit claim.

Usage: python3 tools/distortion_buffer_report.py [--out JSON]
Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

from distortion_model import (  # noqa: E402
    DistortionModel, DistortionParams, HalfbandD2, BLOCK, OS_BLOCK,
    DISTORTION_OS, model_revision,
)
from ws_tables import TABLE_SIZE, FROZEN_MODELS, table_digest  # noqa: E402

PARAMS = dict(preeq_gain_f=6.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
              preeq_highcut_f=70.0, drive_f=6.0, feedback_f=0.635445,
              posteq_gain_f=-4.5, posteq_freq_f=24.0, posteq_bw_f=1.1,
              posteq_highcut_f=30.535736, gain_f=0.0, model_i=0,
              preeq_highcut_deactivated=False,
              posteq_highcut_deactivated=False,
              preeq_gain_extend=False, posteq_gain_extend=False,
              drive_extend=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028e", "artifacts", "buffer-requirement.json"))
    args = ap.parse_args()

    m = DistortionModel(DistortionParams(PARAMS), "probe")
    m.initialize()
    rs = random.Random(5)
    n_blocks = 64
    for _ in range(n_blocks):
        il = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        m.process_block(il, ir)

    st = m.st
    cp = st.checkpoint()

    # on-chip state inventory, counted from the frozen model's own objects
    words_64 = 0
    words_32 = 0
    # 2 peak-EQ biquads: 5 lag + 5 target + 4 TDF2 registers, all Q24.43
    words_64 += 2 * (5 + 5 + 4)
    # 2 instantized LP biquads: 5 coefficients + 4 TDF2 registers
    words_64 += 2 * (5 + 4)
    # 2 halfband decimators: 2 ch x 2 branch x 3 stages x 6 taps
    hb_words = 2 * 2 * HalfbandD2.STAGES * 6
    words_64 += 2 * hb_words
    # 2 feedback registers (Q10.21) + 2 lipol ramps (cur/target, Q13.18)
    words_32 += 2 + 4
    on_chip_bytes = words_64 * 8 + words_32 * 4

    # frozen ROM (shared across instances, not per-instance state)
    rom_words = len(FROZEN_MODELS) * TABLE_SIZE + 12   # waveshapers + halfband

    out = {
        "schema_version": 1,
        "leaf": "SXT-028e",
        "effect": "Distortion (DistortionEffect)",
        "model_revision": model_revision(),
        "blocks_measured": n_blocks,
        "external_memory": {
            "per_instance_state_bytes": 0,
            "reads_per_sample": st.ext_reads / (n_blocks * BLOCK),
            "writes_per_sample": st.ext_writes / (n_blocks * BLOCK),
            "bytes_per_second_at_48k": 0.0,
            "delay_line_class_buffers": 0,
            "note": "Distortion has no delay-line-class buffer: there is no "
                    "external-memory residency or traffic at all. The rule "
                    "'long buffers external-WRITABLE, never flash' is "
                    "vacuously satisfied — nothing long exists to place.",
        },
        "on_chip_state": {
            "q24_43_words": words_64,
            "q10_21_or_q13_18_words": words_32,
            "bytes_per_instance": on_chip_bytes,
            "halfband_words_each": hb_words,
            "breakdown": {
                "peak_eq_biquads": "2 x (5 lag + 5 target + 4 TDF2) Q24.43",
                "oversampled_lp_biquads": "2 x (5 coeff + 4 TDF2) Q24.43",
                "halfband_decimators":
                    f"2 x (2 ch x 2 branch x {HalfbandD2.STAGES} stages x 6 taps) Q24.43",
                "feedback_registers": "2 x Q10.21 (DistortionEffect::L / R)",
                "gain_ramps": "2 x (cur, target) Q13.18",
            },
        },
        "frozen_rom": {
            "waveshaper_rows": len(FROZEN_MODELS),
            "waveshaper_words": len(FROZEN_MODELS) * TABLE_SIZE,
            "halfband_coefficient_words": 12,
            "total_words": rom_words,
            "bytes": rom_words * 4,
            "shared": True,
            "waveshaper_table_digest": table_digest(),
            "note": "ROM is shared read-only across instances; the halfband "
                    "coefficients are streamed to the RTL (DR-0002 clause 1).",
        },
        "compute": {
            "oversampling_factor": DISTORTION_OS,
            "shaper_evaluations_per_sample_per_channel": DISTORTION_OS,
            "oversampled_biquad_samples_per_block": OS_BLOCK * 2,
            "halfband_allpass_stages_per_block":
                (OS_BLOCK + OS_BLOCK // 2) * 2 * 2 * HalfbandD2.STAGES,
        },
        "cost_fit_verdict": "[PENDING-SXT-016]",
        "claim_scope": "measured demand only; no cost, area, timing, power, "
                       "synthesis or fit claim is made here",
    }
    # sanity: the frozen model must not have touched external memory at all
    assert st.ext_reads == 0 and st.ext_writes == 0, cp
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
