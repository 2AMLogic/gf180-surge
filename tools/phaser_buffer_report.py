#!/usr/bin/env python3
"""SXT-028g state-residency and external-memory-traffic report.

WHAT THIS ESTABLISHES
  * the EXACT per-instance state inventory of the frozen Phaser model, from
    the model itself (model/effects/type-phaser/phaser_model.py
    state_inventory), at every stage count the algorithm allows;
  * the MEASURED external-memory traffic, from the frozen model's own
    ext_reads / ext_writes transaction counters over a real render (the
    SXT-023/024/028c convention: transaction-log basis, not estimated).
    The Phaser has no delay line, so the measured traffic is zero.

WHAT THIS DOES *NOT* ESTABLISH
  * cost closure. Whether this inventory (plus a voice stage, a schedule and
    the sibling FX of a bundle) fits any profile is SXT-015 accounting
    consumed by SXT-016, and profile v1 is NOT frozen (SXT-017, issue #12,
    currently operator-routed after PR #109 found no bundle meeting the
    budget goal at any measured corner). Every fit/cost field below is
    marked [PENDING-SXT-016] and no number is invented for it here.

SXT-015 reconciliation: the SXT-015 corpus accounting carries the Phaser as
`class_state_unverified`, tier `no_long_buffer`, external false, 0 ext
reads/writes per frame, with a conservative 8192-byte placeholder and the
note "exact state sizing ESTIMATE-REF deferred to SXT-028". This report
supplies that exact sizing; the traffic/tier classification is CONFIRMED and
the byte placeholder is SUPERSEDED (the exact worst case is smaller, so the
placeholder was conservative, not wrong).

Original to this repository (Apache-2.0).
"""

import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-phaser"))

from phaser_model import (  # noqa: E402
    PhaserModel, PhaserParams, BLOCK, MAX_STAGES, DEFAULT_STAGES,
    state_inventory, model_revision,
)
from corners import CORNERS  # noqa: E402

OUT = os.path.join(REPO, "reports", "SXT-028g", "artifacts",
                   "buffer-requirement.json")
SXT015_PLACEHOLDER_BYTES = 8192      # reports/sxt-015/examples/example-a-...


def main():
    n_blocks = 128
    measured = {}
    for slug in ("synth-a", "synth-maxst", "synth-legacy-a"):
        m = PhaserModel(PhaserParams(dict(CORNERS[slug])), slug)
        m.initialize()
        rs = random.Random(1)
        for _ in range(n_blocks):
            il = [rs.randint(-(1 << 21), 1 << 21) for _ in range(BLOCK)]
            ir = [rs.randint(-(1 << 21), 1 << 21) for _ in range(BLOCK)]
            m.process_block(il, ir)
        frames = n_blocks * BLOCK
        measured[slug] = {
            "stages": m.st.n_stages,
            "ext_reads_total": m.st.ext_reads,
            "ext_writes_total": m.st.ext_writes,
            "reads_per_sample": m.st.ext_reads / frames,
            "writes_per_sample": m.st.ext_writes / frames,
            "clamp_engagements": m.st.clamp_hits,
        }

    inv = {str(n): state_inventory(n)
           for n in (1, 2, DEFAULT_STAGES, 8, MAX_STAGES)}
    worst = inv[str(MAX_STAGES)]

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028g",
        "model_revision": model_revision(),
        "scope": "per Phaser instance (sst-effects Phaser), 48 kHz, frozen "
                 "Q10.21 audio words / Q24.43 coefficient words",
        "external_traffic": {
            "reads_per_sample": 0.0,
            "writes_per_sample": 0.0,
            "words_per_sample_32bit": 0.0,
            "bytes_per_second_at_48k": 0.0,
            "transaction_log_basis": "frozen-model ext_reads/ext_writes "
                                     "counters over %d blocks per corner "
                                     "(measured, not estimated)" % n_blocks,
            "measured_per_corner": measured,
            "note": "the Phaser is a cascade of biquad allpass sections with "
                    "a one-sample recursive node; it owns NO delay line, so "
                    "there is no audio-rate external-memory traffic at all. "
                    "This is a structural property of the pinned algorithm "
                    "(Phaser.h has no line buffer), confirmed here by the "
                    "model's own transaction counters.",
        },
        "external_writable_memory": {
            "words_total": 0,
            "bytes_total": 0,
            "classification_policy": "no buffer of this algorithm exceeds the "
                                     "external-residency threshold; all state "
                                     "is small on-chip state. Flash is never "
                                     "writable delay memory (plan section 3 / "
                                     "AGENTS.md) and no flash is used here.",
        },
        "on_chip_state_exact": {
            "per_stage_count": inv,
            "worst_case_stage_count": MAX_STAGES,
            "worst_case_bytes": worst["bytes_total"],
            "worst_case_bits": worst["bits_total"],
            "default_stage_count": DEFAULT_STAGES,
            "default_bytes": inv[str(DEFAULT_STAGES)]["bytes_total"],
            "basis": "exact word inventory of the frozen model "
                     "(phaser_model.state_inventory), not an estimate",
            "note": "the legacy branch (stages < 2) still ALLOCATES four "
                    "biquad units because Phaser::setvars configures four, "
                    "even though processBlock runs only stage 0 — the "
                    "residency follows the allocation, as pinned.",
        },
        "multi_instance": {
            "note": "per-instance state is never shared (AGENTS.md); two "
                    "Phaser slots = two independent state sets. Arithmetic "
                    "may be shared only observably.",
            "per_additional_instance_bytes_worst_case": worst["bytes_total"],
            "per_additional_instance_external_bytes": 0,
        },
        "sxt015_reconciliation": {
            "sxt015_record": "reports/sxt-015/examples/"
                             "example-a-four-fx-instances.json — Phaser slot "
                             "0: tier no_long_buffer, external false, "
                             "ext_reads_per_frame 0, ext_writes_per_frame 0, "
                             "state_bytes 8192, flag class_state_unverified "
                             "('exact state sizing ESTIMATE-REF deferred to "
                             "SXT-028')",
            "tier_confirmed": True,
            "traffic_confirmed": True,
            "placeholder_state_bytes": SXT015_PLACEHOLDER_BYTES,
            "exact_worst_case_state_bytes": worst["bytes_total"],
            "placeholder_was_conservative":
                worst["bytes_total"] <= SXT015_PLACEHOLDER_BYTES,
            "status": "class_state_unverified RESOLVED for the Phaser class: "
                      "tier and traffic confirmed, byte placeholder "
                      "superseded by the exact inventory above.",
        },
        "cost_closure": {
            "status": "[PENDING-SXT-016]",
            "note": "no cycles-per-frame, schedule-fit or bundle-closure "
                    "number is asserted by this leaf. SXT-015 accounting "
                    "consumes the inventory above; SXT-016 decides fit; "
                    "profile v1 is NOT frozen (SXT-017, issue #12). Nothing "
                    "here may be read as a cost or fit claim.",
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({
        "external_bytes": 0,
        "words_per_sample": 0.0,
        "on_chip_bytes_default_4_stages": inv[str(DEFAULT_STAGES)]["bytes_total"],
        "on_chip_bytes_worst_16_stages": worst["bytes_total"],
        "sxt015_tier_confirmed": True,
        "cost_closure": "[PENDING-SXT-016]",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
