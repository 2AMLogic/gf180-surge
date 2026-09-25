#!/usr/bin/env python3
"""SXT-028f external-memory requirement report (SXT-015/016 accounting).

State residency and traffic are MEASURED from the frozen model's own
per-instance ext_read/ext_write counters (transaction-log basis, the
SXT-023/024/028c convention) and cross-checked against the structure
declared by the pinned header. Per Reverb 2 instance at the engine
allocation profile:

  * predelay ring        1,536,000 words (PREDELAY_BUFFER_SIZE = 48000*8*4)
  * 12 allpass rings     12 x 131,072 words (MAX_ALLPASS_LEN = 16384*8)
  * 4 delay rings         4 x 131,072 words (MAX_DELAY_LEN   = 16384*8)
    = 3,633,152 x 32-bit words = 14,532,608 B = 13.859 MiB per instance.

  * traffic per sample: 29 reads (1 predelay + 12 allpass + 4 delays x 4)
    and 17 writes (1 predelay + 12 allpass + 4 delays x 1) = 46 words.

All processing stays on-chip; the long buffers are external WRITABLE
memory and flash is never writable delay memory (plan section 3 /
AGENTS.md). Two configured Reverb 2 slots are two instances over two
disjoint regions.

This report is a state/traffic accounting. It makes NO fit claim: the
SXT-016 cost closure for `cyc_fxreverb2_frame` is [PENDING-SXT-016] and
the SXT-017 profile-v1 freeze (#12) is the only place a fit may be
declared.

Original to this repository (Apache-2.0).
"""
import argparse
import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-reverb 2"))

from reverb2_model import (  # noqa: E402
    Reverb2Model, Reverb2Params, ENGINE_PROFILE, HARNESS_PROFILE,
    MAX_ALLPASS_LEN, MAX_DELAY_LEN, PREDELAY_BUFFER_SIZE, NUM_ALLPASSES,
    NUM_BLOCKS, BLOCK, per_sample_transactions, model_revision,
)
from model.resources.fx_classes import fx_class_spec  # noqa: E402

PARAMS = dict(predelay_f=-4.0, room_size_f=0.0, decay_time_f=0.75,
              diffusion_f=1.0, buildup_f=1.0, modulation_f=0.5,
              lf_damping_f=0.2, hf_damping_f=0.2, width_f=0.0, mix_f=1.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028f", "artifacts", "buffer-requirement.json"))
    ap.add_argument("--blocks", type=int, default=128)
    args = ap.parse_args()

    # measurement runs on the bench profile (identical transaction COUNTS:
    # the allocation profile changes addresses, never the number of
    # transactions per sample, which is fixed by the pinned structure)
    m = Reverb2Model(Reverb2Params(PARAMS), "m", HARNESS_PROFILE)
    m.initialize()
    rs = random.Random(1)
    for _ in range(args.blocks):
        il = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        m.process_block(il, ir)

    samples = args.blocks * BLOCK
    reads = m.st.ext_reads / samples
    writes = m.st.ext_writes / samples
    declared = per_sample_transactions()

    words = ENGINE_PROFILE.words
    state_bytes = words * 4
    sxt015 = fx_class_spec("Reverb 2")

    on_chip = {
        "six coefficient ramps (v/new_v/dv, Q24.43)": 6 * 3 * 64,
        "eight one-pole registers (Q24.43)": 8 * 64,
        "LFO r/i/dr/di (Q24.43)": 4 * 64,
        "tank accumulator _state (Q10.21)": 32,
        "widthS + mix lipol (cur+tgt, Q13.18)": 4 * 32,
        "ring indices (predelay + 12 allpass + 4 delay)": 17 * 32,
        "configured lengths + tap times (12 + 4 + 8)": 24 * 32,
        "predelay tap + counters + region hashes": 5 * 64,
    }
    on_chip_bits = sum(on_chip.values())

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028f",
        "issue": "SXT-028f",
        "model_revision": model_revision(),
        "scope": ("per Reverb 2 instance (sst-effects Reverb2 tank reverb), "
                  "48 kHz, frozen Q10.21 32-bit buffer words"),
        "external_writable_memory": {
            "classification_policy": (
                "every Reverb 2 buffer is external WRITABLE memory (> 64 KiB "
                "policy, plan section 3); flash is never writable delay "
                "memory; all processing stays in-chip"),
            "predelay": {"words": PREDELAY_BUFFER_SIZE,
                         "bytes": PREDELAY_BUFFER_SIZE * 4,
                         "layout": "circular ring, index wraps at "
                                   "PREDELAY_BUFFER_SIZE; read at k - pdt "
                                   "with pdt clamped to [1, 1151999]"},
            "allpass_rings": {"count": NUM_ALLPASSES,
                              "words_each": MAX_ALLPASS_LEN,
                              "bytes": NUM_ALLPASSES * MAX_ALLPASS_LEN * 4,
                              "layout": "4 input + 4 tank blocks x 2; ring "
                                        "length is the configured _len, the "
                                        "allocation is the engine maximum"},
            "delay_rings": {"count": NUM_BLOCKS,
                            "words_each": MAX_DELAY_LEN,
                            "bytes": NUM_BLOCKS * MAX_DELAY_LEN * 4,
                            "layout": "power-of-two ring masked by "
                                      "DELAY_LEN_MASK; 2 output taps + 2 "
                                      "sub-sample interpolation reads"},
            "words_total": words,
            "bytes_total": state_bytes,
            "total_MiB": round(state_bytes / (1024.0 * 1024.0), 6),
        },
        "external_traffic": {
            "transaction_log_basis": (
                "model ext_reads/ext_writes counters over %d blocks "
                "(measured, frozen model)" % args.blocks),
            "reads_per_sample": reads,
            "writes_per_sample": writes,
            "words_per_sample_32bit": reads + writes,
            "bytes_per_sample": (reads + writes) * 4,
            "bytes_per_second_at_48k": (reads + writes) * 4 * 48000,
            "declared_from_structure": declared,
            "measured_matches_structure":
                abs(reads - declared["reads"]) < 1e-9
                and abs(writes - declared["writes"]) < 1e-9,
            "note": ("reads = 1 predelay + 12 allpass + 4 delays x (2 output "
                     "taps + 2 interpolation reads); writes = 1 predelay + "
                     "12 allpass + 4 delay writes"),
        },
        "multi_instance": {
            "per_additional_instance_external_bytes": state_bytes,
            "note": ("per-instance state is never shared (AGENTS.md); two "
                     "Reverb 2 slots = two independent tanks over two "
                     "disjoint external regions"),
        },
        "on_chip_small_state": {
            "bits": on_chip_bits,
            "bytes": (on_chip_bits + 7) // 8,
            "breakdown": on_chip,
            "note": ("the Q86/Q128 products of the coefficient multiplies are "
                     "combinational; the tap gains are frozen ROM"),
        },
        "alloc_profiles": {
            "engine": ENGINE_PROFILE.as_dict(),
            "harness": HARNESS_PROFILE.as_dict(),
            "note": ("the RTL bench runs the reduced harness profile so two "
                     "instances fit the simulator; transaction COUNTS are "
                     "identical and the model refuses a profile that would "
                     "alias a live tap (ProfileRefusal)"),
        },
        "sxt015_reconciliation": {
            "sxt015_state_bytes": sxt015["state_bytes"],
            "this_model_bytes": state_bytes,
            "state_agreement": sxt015["state_bytes"] == state_bytes,
            "sxt015_reads_per_sample": sxt015["ext_reads"],
            "sxt015_writes_per_sample": sxt015["ext_writes"],
            "traffic_agreement": (sxt015["ext_reads"] == declared["reads"]
                                  and sxt015["ext_writes"]
                                  == declared["writes"]),
            "note": ("state residency confirms the SXT-015 pinned entry "
                     "exactly. The SXT-015 per-sample TRAFFIC entry for "
                     "Reverb 2 (40 reads / 18 writes) is an over-estimate "
                     "relative to the structure measured here (29 reads / 17 "
                     "writes); this leaf records the finding and does NOT "
                     "edit the shared SXT-015 table, which is SXT-015/016 "
                     "scope. Over-estimating traffic is conservative for the "
                     "budget, so no SXT-016/017 result is invalidated."),
        },
        "fit_claim": ("NONE. cyc_fxreverb2_frame is a placeholder "
                      "[PENDING-SXT-016]; profile v1 is not frozen (#12, "
                      "STOP/ESCALATE fired in PR #109). This report "
                      "establishes state and traffic only."),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print("state bytes/instance:", state_bytes,
          "(%.3f MiB)" % (state_bytes / 1048576.0))
    print("traffic: %.3f reads + %.3f writes = %.3f words/sample (%.2f MB/s)"
          % (reads, writes, reads + writes,
             (reads + writes) * 4 * 48000 / 1e6))
    print("sxt015 state agreement:",
          doc["sxt015_reconciliation"]["state_agreement"],
          "| traffic agreement:",
          doc["sxt015_reconciliation"]["traffic_agreement"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
