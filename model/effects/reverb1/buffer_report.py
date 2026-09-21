#!/usr/bin/env python3
"""SXT-024 measured buffer requirement for one Reverb1 instance (issue #17
acceptance: "Buffer requirement measured and reconciled with the
external-memory model; processing stays in-chip").

Structure constants are read from the frozen model (reverb1_fixed.py), not
estimated. Classification policy: the composite tap array and predelay line
are EXTERNAL WRITABLE memory (>64 KiB policy, SXT-015/plan section 3); flash
is never a substitute for writable delay memory. All processing (taps,
damping, feedback, pans, biquads, width, mix) stays on-chip.

Outputs reports/sxt-024/buffer-requirement.json.
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))

import reverb1_fixed as rf  # noqa: E402

OUT = os.path.join(REPO, "reports", "sxt-024", "buffer-requirement.json")

SAMPLE_RATE = 48000


def main():
    taps_words = rf.REV_TAPS * rf.MAX_REV_DLY
    pd_words = rf.MAX_REV_DLY
    word_bits = rf.STORAGE_BITS
    taps_bits = taps_words * word_bits
    pd_bits = pd_words * word_bits

    on_chip = {
        "out_tap[16]": 16 * 32,
        "delay_pos": 15,
        "delay_time[16]": 16 * 23,        # max 2*2711583*2 < 2^23
        "delay_fb[16]": 16 * 32,
        "pan_L[16] + pan_R[16]": 32 * 32,
        "damp + damp_m1": 2 * 32,
        "biquad coeffs (3 filters x 5 x 2 ch-shared)": 15 * 32,
        "biquad regs (3 x 2 ch x 2 regs x 80b)": 12 * 80,
        "mix/width lags": 2 * 32,
        "block/frame counters": 32,
    }
    on_chip_bits = sum(on_chip.values())

    # external-memory transactions per output frame (frame = one 32-sample
    # block; the model logs them exactly)
    m = rf.Reverb1Fixed({
        "delay_time": [9839 * 256] * 16, "delay_fb": [0.5] * 16, "pdtime": 64,
        "pan_l": [0.7] * 16, "pan_r": [0.7] * 16, "damp": 0.5, "damp_m1": 0.5,
        "band1": (1.0, 0.0, 0.0, 0.0, 0.0), "locut": (1.0, 0.0, 0.0, 0.0, 0.0),
        "hicut": (1.0, 0.0, 0.0, 0.0, 0.0), "lowcut_active": False,
        "hicut_active": False, "mix": 1.0, "width_s": 1.0,
    }, assert_width=False)
    blk = [0] * rf.BLOCK
    m.process_block(blk, blk)
    reads_per_sample = m.ext_reads / rf.BLOCK
    writes_per_sample = m.ext_writes / rf.BLOCK

    # NOTE: "frame" in the SXT-015/016 accounting = one audio sample period
    # (1/48 kHz); the model counters above are already per-sample.
    per_sample_words = reads_per_sample + writes_per_sample
    bytes_per_sample = per_sample_words * 4
    out = {
        "issue": "SXT-024",
        "scope": "per Reverb1 instance, 48 kHz, frozen Q4.28/32-bit-word format",
        "external_writable_memory": {
            "classification_policy": "composite tap array + predelay line are "
                                     "external WRITABLE memory (>64 KiB policy, "
                                     "plan section 3 / SXT-015); flash is never "
                                     "writable delay memory; all processing in-chip",
            "composite_taps": {"words": taps_words, "bits": taps_bits,
                               "bytes": taps_bits // 8,
                               "layout": "16 interleaved circular taps x 32768 "
                                         "samples; word = (pos<<4)+tap"},
            "predelay_line": {"words": pd_words, "bits": pd_bits,
                              "bytes": pd_bits // 8},
            "total_bits": taps_bits + pd_bits,
            "total_bytes": (taps_bits + pd_bits) // 8,
            "total_MiB": round((taps_bits + pd_bits) / 8 / 2**20, 6),
        },
        "on_chip_small_state": {"bits": on_chip_bits,
                                "bytes": on_chip_bits // 8,
                                "breakdown": on_chip},
        "external_traffic": {
            "reads_per_sample": reads_per_sample,
            "writes_per_sample": writes_per_sample,
            "words_per_sample_32bit": per_sample_words,
            "bytes_per_sample": bytes_per_sample,
            "bytes_per_second_at_48k": bytes_per_sample * SAMPLE_RATE,
            "transaction_log_basis": "model ext_reads/ext_writes counters "
                                     "(measured by running the frozen model)",
        },
        "sxt016_reconciliation": {
            "sxt015_logical_words_per_frame": "17r + 17w",
            "sxt016_probe_words_per_frame": 34,
            "sxt016_bytes_per_frame": 136,
            "this_model_words_per_sample": per_sample_words,
            "agreement": per_sample_words == 34,
            "divergence_note": "SXT-016 state_bits priced 24-bit storage words "
                               "(taps 12,582,912 b + predelay 786,432 b); the frozen "
                               "Q4.28 word is 32-bit after the stability analysis, so "
                               "capacity is 16,777,216 + 1,048,576 b (+33%); traffic "
                               "is UNCHANGED at 34 x 32-bit words per sample (136 B) "
                               "because the 16-bit external bus is accessed in 32-bit "
                               "words in both models. Do NOT edit committed "
                               "sxt-015/sxt-016 files; this record supersedes the "
                               "capacity figure for Reverb 1.",
        },
        "multi_instance": {
            "per_additional_instance_external_bytes": (taps_bits + pd_bits) // 8,
            "note": "per-instance state is never shared (AGENTS.md); two Reverb1 "
                    "slots = two independent buffer sets",
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
