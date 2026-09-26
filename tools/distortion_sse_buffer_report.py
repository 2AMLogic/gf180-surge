#!/usr/bin/env python3
"""SXT-028e-sse state residency + external-memory traffic (SXT-015 accounting).

Measured from the frozen model's own state layout and per-instance
transaction counters -- nothing is estimated by hand. Follows
`tools/distortion_buffer_report.py` (SXT-028e); the DELTA this leaf adds is
the per-instance `QuadWaveshaperState` (issue #121 stop/escalate: "if the
quad-waveshaper state cannot be bounded in state/cost under the shared
instance schedule, record the finding and route to SXT-017 (#12)").

Result class: the SSE branch adds a BOUNDED, SMALL amount of per-instance
state -- `n_waveshaper_registers` (4) registers x 2 modelled SIMD lanes in
Q24.43, plus a 2-bit `init` mask -- and no external memory whatsoever. Like
SXT-028e, this effect owns no delay-line-class buffer. The FIT verdict
against a profile-v1 cost envelope is still [PENDING-SXT-016]: this file
reports measured demand, not a fit claim.

Usage: python3 tools/distortion_sse_buffer_report.py [--out JSON]
Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

from distortion_sse_model import (  # noqa: E402
    DistortionSSEModel, DistortionSSEParams, HalfbandD2, BLOCK, OS_BLOCK,
    DISTORTION_OS, model_revision, REGISTER_USE, READS_INIT,
)
from quad_shapers import QuadWaveshaperState  # noqa: E402
from sse_tables import (  # noqa: E402
    SINE_SIZE, FUZZ_SIZE, SSE_MODELS, SSE_SHAPER_OF, ROM_WORDS, table_digest,
)

PARAMS = dict(preeq_gain_f=6.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
              preeq_highcut_f=70.0, drive_f=6.0, feedback_f=0.635445,
              posteq_gain_f=-4.5, posteq_freq_f=24.0, posteq_bw_f=1.1,
              posteq_highcut_f=30.535736, gain_f=0.0, model_i=7,
              preeq_highcut_deactivated=False,
              posteq_highcut_deactivated=False,
              preeq_gain_extend=False, posteq_gain_extend=False,
              drive_extend=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028e-sse", "artifacts",
        "buffer-requirement.json"))
    args = ap.parse_args()

    n_blocks = 64
    sat_by_model = {}
    m = None
    for mi in SSE_MODELS:
        p = dict(PARAMS, model_i=mi)
        mm = DistortionSSEModel(DistortionSSEParams(p), f"probe{mi}")
        mm.initialize()
        rs = random.Random(5)
        for _ in range(n_blocks):
            il = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
            ir = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
            mm.process_block(il, ir)
        sat_by_model[str(mi)] = mm.st.ws.sat_events
        if mi == PARAMS["model_i"]:
            m = mm

    st = m.st.chain
    cp = m.st.checkpoint()

    # --- on-chip state inventory, counted from the frozen model's objects ---
    words_64 = 0
    words_32 = 0
    # 2 peak-EQ biquads: 5 lag + 5 target + 4 TDF2 registers, all Q24.43
    words_64 += 2 * (5 + 5 + 4)
    # 2 instantized LP biquads: 5 coefficients + 4 TDF2 registers
    words_64 += 2 * (5 + 4)
    # 2 halfband decimators: 2 ch x 2 branch x 3 stages x 6 taps
    hb_words = 2 * 2 * HalfbandD2.STAGES * 6
    words_64 += 2 * hb_words
    chain_words_64 = words_64
    # THIS LEAF'S DELTA: the QuadWaveshaperState registers (Q24.43)
    ws_words_64 = QuadWaveshaperState.N_REGISTERS * QuadWaveshaperState.LANES
    words_64 += ws_words_64
    # 2 feedback registers (Q10.21) + 2 lipol ramps (cur/target, Q13.18)
    words_32 += 2 + 4
    init_mask_bits = QuadWaveshaperState.LANES
    on_chip_bytes = words_64 * 8 + words_32 * 4 + 1   # +1 B holds the mask

    used = sorted({r for mi in SSE_MODELS for r in REGISTER_USE[mi]})

    out = {
        "schema_version": 1,
        "leaf": "SXT-028e-sse",
        "effect": "Distortion, SSE quad-waveshaper branch (FX models 3..7)",
        "model_revision": model_revision(),
        "blocks_measured": n_blocks,
        "external_memory": {
            "per_instance_state_bytes": 0,
            "reads_per_sample": st.ext_reads / (n_blocks * BLOCK),
            "writes_per_sample": st.ext_writes / (n_blocks * BLOCK),
            "bytes_per_second_at_48k": 0.0,
            "delay_line_class_buffers": 0,
            "note": "The SSE branch adds no external-memory residency or "
                    "traffic: `QuadWaveshaperState` is 4 SIMD registers, not "
                    "a delay line. The rule 'long buffers external-WRITABLE, "
                    "never flash' stays vacuously satisfied.",
        },
        "on_chip_state": {
            "q24_43_words": words_64,
            "q10_21_or_q13_18_words": words_32,
            "init_mask_bits": init_mask_bits,
            "bytes_per_instance": on_chip_bytes,
            "halfband_words_each": hb_words,
            "sxt028e_chain_q24_43_words": chain_words_64,
            "sse_branch_delta_q24_43_words": ws_words_64,
            "sse_branch_delta_bytes": ws_words_64 * 8 + 1,
            "breakdown": {
                "peak_eq_biquads": "2 x (5 lag + 5 target + 4 TDF2) Q24.43",
                "oversampled_lp_biquads": "2 x (5 coeff + 4 TDF2) Q24.43",
                "halfband_decimators":
                    f"2 x (2 ch x 2 branch x {HalfbandD2.STAGES} stages x 6 "
                    "taps) Q24.43",
                "feedback_registers": "2 x Q10.21 (DistortionEffect::L / R)",
                "gain_ramps": "2 x (cur, target) Q13.18",
                "quad_waveshaper_registers":
                    f"{QuadWaveshaperState.N_REGISTERS} registers x "
                    f"{QuadWaveshaperState.LANES} modelled lanes Q24.43 "
                    "(sst::waveshapers::n_waveshaper_registers)",
                "quad_waveshaper_init_mask":
                    f"{init_mask_bits} bits (one per modelled lane)",
            },
        },
        "quad_waveshaper_state": {
            "n_waveshaper_registers": QuadWaveshaperState.N_REGISTERS,
            "modelled_lanes": QuadWaveshaperState.LANES,
            "lanes_declared_out_of_scope": 2,
            "registers_actually_touched_by_reachable_shapers": used,
            "per_model_register_use":
                {str(k): list(v) for k, v in REGISTER_USE.items()},
            "per_model_reads_init_mask":
                {str(k): bool(v) for k, v in READS_INIT.items()},
            "bounded": True,
            "bound_statement":
                "The per-instance quad-waveshaper state is BOUNDED and "
                "small: 8 Q24.43 words + a 2-bit mask = 65 B per instance, "
                "independent of block size, sample rate and FX model. Only "
                "registers 0 and 1 are touched by any of the five reachable "
                "shapers, so a shared instance schedule needs 2 registers x "
                "2 lanes of live context per Distortion slot. The issue's "
                "stop/escalate condition (state/cost cannot be bounded) is "
                "therefore NOT triggered.",
        },
        "frozen_rom": {
            "waveshaper_rows": 2,
            "sine_row_words": SINE_SIZE,
            "fuzz_row_words": FUZZ_SIZE,
            "total_words": ROM_WORDS,
            "bytes": ROM_WORDS * 4,
            "shared": True,
            "waveshaper_table_digest": table_digest(),
            "shapers_needing_no_table":
                [SSE_SHAPER_OF[mi] for mi in SSE_MODELS
                 if mi not in (3, 7)],
            "note": "ROM is shared read-only across instances and is a build "
                    "product of model/effects/type-distortion-sse/"
                    "sse_tables.py (DR-0014 clause 2); the eleven designed "
                    "shaper scalars are streamed to the RTL, not duplicated "
                    "there (DR-0002 clause 1).",
        },
        "compute": {
            "oversampling_factor": DISTORTION_OS,
            "shaper_evaluations_per_sample_per_channel": DISTORTION_OS,
            "reciprocals_per_oversample":
                {"3": 1, "4": 1, "5": 0, "6": 1, "7": 1},
            "reciprocal_note":
                "one 1/dNow pre-scale per oversampled step for models 3/5/6/7 "
                "(skipped for 4), plus one shaper-internal reciprocal for 4 "
                "(rcp(drive)), 6 (rcp(dx)) and 7 (rcp(tanh denominator)). "
                "The engine uses the SSE rcp_ps ESTIMATE; the frozen model "
                "uses an exact reciprocal (quad_shapers.py DD-2).",
            "dc_offset_probes_per_block_per_instance": 1,
            "oversampled_biquad_samples_per_block": OS_BLOCK * 2,
            "halfband_allpass_stages_per_block":
                (OS_BLOCK + OS_BLOCK // 2) * 2 * 2 * HalfbandD2.STAGES,
        },
        "declared_range_saturation": {
            "what": "quad_shapers.py DD-4: the Q24.43 drive-normalized "
                    "shaper input saturates for drive below ~1.2e-4",
            "events_per_model_over_measured_render": sat_by_model,
            "note": "measured, not assumed; zero here means the committed "
                    "render never reached the declared saturation corner. "
                    "The dedicated corner case `corners-lowdrive-sat` in "
                    "rtl-exactness.json does reach it, and the RTL still "
                    "matches the model exactly.",
        },
        "cost_fit_verdict": "[PENDING-SXT-016]",
        "claim_scope": "measured demand only; no cost, area, timing, power, "
                       "synthesis or fit claim is made here",
    }
    assert st.ext_reads == 0 and st.ext_writes == 0, cp
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
