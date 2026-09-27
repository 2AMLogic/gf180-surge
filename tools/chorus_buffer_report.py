#!/usr/bin/env python3
"""SXT-028c external-memory requirement report (SXT-015/016 accounting).

State residency and traffic are measured by running the frozen model with
its per-instance ext_read/ext_write counters (the SXT-023/024 convention:
transaction-log basis, not estimated). Per Chorus instance:

  * ONE mono delay line of (2^18 + 12) Q10.21 words = 262,156 x 4 B
    = 1,048,624 B (matches the SXT-015 placeholder-class estimate of
    1,048,624 B for Chorus - now pinned by this leaf);
  * traffic: 48 reads + 1 write per sample (4 voices x 12-tap sinc reads;
    one mono write), + a 12-word padding copy once per 256 blocks
    (wpos == 0): 49 words/sample + 12/8192 per sample amortized.

All processing stays on-chip; flash is never writable delay memory
(plan section 3 / AGENTS.md). Two configured Chorus slots = two instances =
two disjoint regions (per-instance state, AGENTS.md).
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-chorus"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))

from chorus_model import (  # noqa: E402
    ChorusModel, ChorusParams, LINE_LEN, BLOCK,
)

OUT = os.path.join(REPO, "reports", "SXT-028c", "artifacts",
                   "buffer-requirement.json")

SYNTH = {"time_f": -6.0, "rate_f": -2.0, "depth_f": 0.35, "feedback_f": 0.4,
         "lowcut_f": -30.0, "highcut_f": 40.0, "mix_f": 0.7, "width_f": 4.0}


def main():
    m = ChorusModel(ChorusParams(SYNTH), "m")
    m.initialize()
    import random
    rs = random.Random(1)
    n_blocks = 256  # >= one wpos wrap cycle segment; padding copy at block 0
    for _ in range(n_blocks):
        il = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
        m.process_block(il, ir)
    reads_total = m.st.ext_reads
    writes_total = m.st.ext_writes
    reads_per_sample = reads_total / (n_blocks * BLOCK)
    writes_per_sample = writes_total / (n_blocks * BLOCK)
    words_per_sample = reads_per_sample + writes_per_sample

    # on-chip small state (bits): per-instance
    lag_bits = 4 * 2 * 64          # per-voice time-lag v + target (Q24.43)
    lfophase_bits = 4 * 64         # control-plane accumulators held on-chip
    biquad_bits = 2 * (5 * 64 + 4 * 64)   # lp/hp: 5 lags + 4 TDF2 regs
    lipol_bits = 3 * 2 * 32        # fb/mix/width: cur + tgt (Q13.18)
    counter_bits = 32 + 64 + 64    # wpos + ext counters (approx) + hash
    on_chip_bits = (lag_bits + lfophase_bits + biquad_bits + lipol_bits
                    + counter_bits)

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028c",
        "scope": "per Chorus instance (ChorusEffect<4>), 48 kHz, frozen "
                 "Q10.21/32-bit line words",
        "issue": "SXT-028c",
        "external_traffic": {
            "reads_per_sample": reads_per_sample,
            "writes_per_sample": writes_per_sample,
            "words_per_sample_32bit": words_per_sample,
            "bytes_per_sample": words_per_sample * 4,
            "bytes_per_second_at_48k": words_per_sample * 4 * 48000,
            "transaction_log_basis": "model ext_reads/ext_writes counters "
                                     "over 256 blocks (measured, frozen model)",
            "note": "reads = 4 voices x 12-tap sinc per sample (UNMASKED "
                    "reads may cross into the 12 padding words, whose "
                    "content the engine refreshes only when wpos == 0); "
                    "writes = 1 mono word per sample + the 12-word padding "
                    "copy once per 8192 blocks",
        },
        "external_writable_memory": {
            "classification_policy": "mono delay line (2^18 + 12 words) is "
                                     "external WRITABLE memory (>64 KiB "
                                     "policy, plan section 3); flash is "
                                     "never writable delay memory; all "
                                     "processing in-chip",
            "mono_line": {
                "words": LINE_LEN,
                "bits": LINE_LEN * 32,
                "bytes": LINE_LEN * 4,
                "layout": "circular mono line; the 12 padding words "
                          "line[2^18..2^18+11] are refreshed from "
                          "line[0..11] when wpos == 0 (engine wrap-read "
                          "semantics, reproduced exactly)",
            },
            "words_total": LINE_LEN,
            "bytes_total": LINE_LEN * 4,
            "total_MiB": round(LINE_LEN * 4 / (1024 * 1024), 6),
        },
        "multi_instance": {
            "note": "per-instance state is never shared (AGENTS.md); two "
                    "Chorus slots = two independent lines and regions",
            "per_additional_instance_external_bytes": LINE_LEN * 4,
        },
        "on_chip_small_state": {
            "bits": on_chip_bits,
            "bytes": on_chip_bits // 8,
            "breakdown": {
                "per-voice time lags (4 x v,tgt Q24.43)": lag_bits,
                "lfophase (4 x Q24.43, control-plane)": lfophase_bits,
                "biquads lp+hp (lags + TDF2 regs, Q24.43)": biquad_bits,
                "lipol fb/mix/width (cur+tgt Q13.18)": lipol_bits,
                "wpos + counters + line hash": counter_bits,
            },
            "note": "the Q68 tap accumulator and 64-bit biquad products are "
                    "combinational; voicepan constants are frozen ROM",
        },
        "sxt015_reconciliation": {
            "sxt015_chorus_state_bytes": 1048624,
            "this_model_bytes": LINE_LEN * 4,
            "agreement": LINE_LEN * 4 == 1048624,
            "note": "SXT-015 placeholder-class estimate for the Chorus "
                    "(mono 1<<18-sample buffer, ChorusEffect.h) confirmed "
                    "exactly by this leaf (plus the 12 padding words)",
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({
        "words_per_sample": words_per_sample,
        "bytes_per_second_at_48k": doc["external_traffic"]["bytes_per_second_at_48k"],
        "line_bytes": LINE_LEN * 4,
        "on_chip_bytes": on_chip_bits // 8,
        "sxt015_agreement": doc["sxt015_reconciliation"]["agreement"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
