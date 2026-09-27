#!/usr/bin/env python3
"""SXT-028b state-residency and memory-traffic report (SXT-015 accounting
convention; the aggregate profile estimate stays [PENDING-SXT-016]).

Measured from the frozen model (transaction counters, not estimated):

  * per-instance writable state: the 128-sample stereo look-ahead ring
    (2 x 128 x Q10.21 = 1,024 B) + 128 squared-peak leaves (128 x Q24.43 =
    1,024 B) + three biquads, four lipol ramps, envelope trackers, bufpos.
  * state-memory traffic per processed sample: 3 reads (delayed L/R at
    bufpos, the fixed leaf 126) + 3 writes (delayed L/R, one leaf).

Classification: the whole instance is far below the SXT-015 external
threshold (65,536 B, model/resources registry), so it is ON-CHIP state and
generates ZERO external-memory traffic -- the look-ahead ring is short
writable state, not a delay/reverb-class buffer. Flash is never used as
writable state. This is an accounting record from the frozen model, not a
gf180mcu area/placement claim.

Reconciliation with SXT-015 (model/resources/fx_classes.py): Conditioner was
carried as tier `no_long_buffer`, 8,192 B placeholder, external False, 0
ext reads/writes, justified as "gain/lipol state, no delay line" -- that
justification text was inaccurate (there IS a 128-sample look-ahead line,
~1 KiB, far under the threshold). #133/#117 replaced the placeholder with
this leaf's measurement (2,444 B) and corrected the justification text;
`sxt015_reconciliation` below now reads that live value, so this record's
own `sxt015_state_bytes` field tracks the table rather than the retired
placeholder.

Original to this repository (Apache-2.0).
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-conditioner"))

from conditioner_model import (  # noqa: E402
    ConditionerModel, ConditionerParams, LOOKAHEAD, BLOCK, model_revision,
)
from compare_rtl_model_conditioner import Stim, SYNTH_B  # noqa: E402
from model.resources import fx_classes  # noqa: E402

OUT = os.path.join(REPO, "reports", "SXT-028b", "artifacts",
                   "buffer-requirement.json")


def main():
    m = ConditionerModel(ConditionerParams(dict(SYNTH_B)), "m")
    m.initialize()
    st = Stim(7)
    n_blocks = 64
    for b in range(n_blocks):
        il, ir = st.block(b, True)
        m.process_block(il, ir)
    samples = n_blocks * BLOCK
    rps = m.st.state_reads / samples
    wps = m.st.state_writes / samples

    bits = {
        "look-ahead ring delayed[2][128] (Q10.21)": 2 * LOOKAHEAD * 32,
        "squared-peak leaves lamax[0..127] (Q24.43)": LOOKAHEAD * 64,
        "biquads band1+band2 (5 lag + 5 target + 4 TDF2 regs, Q24.43)": 2 * 14 * 64,
        "biquad hp (5 lag + 5 target + 2 TDF2 regs, mono, Q24.43)": 12 * 64,
        "lipol ampL/ampR/width/postamp (cur + tgt, Q13.18)": 4 * 2 * 32,
        "envelope flamax, flamax2, gain + block attack/release (Q24.43)": 5 * 64,
        "bufpos (7 b) + Effect ringout counter (24 b, control plane)": 7 + 24,
    }
    total_bits = sum(bits.values())
    total_bytes = (total_bits + 7) // 8
    spec = fx_classes.fx_class_spec("Conditioner")
    thresh = fx_classes.REG.external_threshold_bytes
    doc = {
        "schema_version": 1, "leaf": "SXT-028b", "issue": "#54",
        "model_revision": model_revision(),
        "scope": "per Conditioner instance, 48 kHz, frozen word formats",
        "on_chip_state": {"bits": total_bits, "bytes": total_bytes,
                          "breakdown_bits": bits,
                          "writable_line_bytes": 2 * LOOKAHEAD * 4 + LOOKAHEAD * 8},
        "state_memory_traffic": {
            "basis": f"model state_reads/state_writes counters over {n_blocks} "
                     "processed blocks (measured)",
            "reads_per_sample": rps, "writes_per_sample": wps,
            "note": "3 reads (delayed L/R at bufpos, fixed leaf 126) + 3 writes "
                    "(delayed L/R, leaf at bufpos) per processed sample; "
                    "process_only_control() blocks touch no ring state"},
        "external_memory": {
            "external_threshold_bytes": thresh,
            "classification": "ON-CHIP" if total_bytes <= thresh else "EXTERNAL",
            "external_bytes": 0 if total_bytes <= thresh else total_bytes,
            "external_traffic_bytes_per_sample": 0.0,
            "flash_used_as_writable_state": False},
        "multi_instance": {"per_additional_instance_bytes": total_bytes,
                           "note": "two slots = two disjoint copies; never shared"},
        "sxt015_reconciliation": {
            "sxt015_tier": spec["tier"], "sxt015_state_bytes": spec["state_bytes"],
            "sxt015_external": spec["external"],
            "sxt015_ext_reads_writes": [spec["ext_reads"], spec["ext_writes"]],
            "measured_bytes": total_bytes,
            "placeholder_conservative": total_bytes <= spec["state_bytes"],
            "external_classification_agrees": spec["external"] is False
            and total_bytes <= thresh,
            "justification_text_finding": "fx_classes previously said 'no delay "
            "line'; the pinned source has a 128-sample stereo look-ahead line "
            "(1 KiB). Classification unaffected; the placeholder was replaced "
            "with this measurement by #133/#117.",
            "aggregate_profile_estimate": "PENDING-SXT-016"},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({k: doc[k] for k in ("on_chip_state", "state_memory_traffic",
                                          "sxt015_reconciliation")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
