#!/usr/bin/env python3
"""SXT-028j: state/cost inventory for the extended-rack routing form,
DERIVED from the frozen model's own declared word widths rather than
hand-counted.

Scope of the claim: this leaf's OWN state/cost contribution -- the routing /
scheduling / lifecycle logic plus its synthetic register-only occupant
kernel. It is NOT the external-memory footprint of whichever concrete Surge
FX algorithm actually occupies global3/global4 in a real preset; that is
that algorithm leaf's own SXT-015/016 accounting, and the AGGREGATE remains
`[PENDING-SXT-016]` per the issue text. No cycles-per-frame, schedule-fit or
bundle-closure number is asserted.

Writes reports/SXT-028j/artifacts/state-cost.json.
Original to this repository (Apache-2.0).
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global34"))

import rf_global34_model as rm  # noqa: E402

OUT = os.path.join(REPO, "reports", "SXT-028j", "artifacts", "state-cost.json")

N_INSTANCES = 2          # global3, global4
TDF2_REGS_PER_INSTANCE = 4   # reg0/reg1 x {L, R}
COEFFS_PER_INSTANCE = 5      # b0 b1 b2 a1 a2
OCCUPANCY_BITS_PER_INSTANCE = 1   # `occupied` / RTL prev_occ latch


def build():
    history_bits = TDF2_REGS_PER_INSTANCE * rm.R_BITS
    per_instance_history = history_bits + OCCUPANCY_BITS_PER_INSTANCE
    coeff_bits = COEFFS_PER_INSTANCE * rm.C_BITS
    routing_control_bits = {
        "fx_bypass (2-bit mode)": 2,
        f"fx_disable (16-bit, engine layout; only bits "
        f"{rm.FXSLOT_GLOBAL3}/{rm.FXSLOT_GLOBAL4} consumed)": 16,
        "ring memory (glob_ring / glob_out)": 1,
    }
    fsm_bits = {
        "FSM state": 3, "sample counter k": 6,
        "run_s3/run_s4 gate latches": 2, "glob_cur": 1,
    }
    shared_routing = sum(routing_control_bits.values())
    shared_fsm = sum(fsm_bits.values())
    comparable_total = N_INSTANCES * per_instance_history + shared_routing
    full_total = (N_INSTANCES * (per_instance_history + coeff_bits)
                  + shared_routing + shared_fsm)
    return {
        "schema_version": 1,
        "leaf": "SXT-028j",
        "issue": "#62",
        "form": "rf-global34",
        "basis": "derived from the frozen model's declared word widths "
                 "(rf_global34_model.R_BITS / C_BITS and the RTL's register "
                 "declarations), not hand-counted",
        "claim": "This leaf's OWN state/cost addition (the routing / "
                 "scheduling / lifecycle logic plus its synthetic per-slot "
                 "occupant kernel) -- NOT the ext-mem footprint of whichever "
                 "concrete Surge FX algorithm actually occupies "
                 "global3/global4 in a real preset, which is that algorithm "
                 "leaf's own SXT-015/016 accounting.",
        "external_writable_memory": {
            "words_total": 0,
            "note": "the synthetic occupant kernel (BiquadInstance) is "
                    "register-only (on-chip); it owns no delay line and "
                    "touches no external buffer. A concrete tail-bearing "
                    "occupant (Delay/Reverb1/Reverb2/Chorus/etc.) landed in "
                    "this slot owns its own external-memory accounting "
                    "separately.",
        },
        "external_traffic": {
            "words_per_sample": 0,
            "note": "no external-memory transactions originate from this "
                    "leaf's own routing/scheduling/lifecycle logic or its "
                    "synthetic occupant; the frozen model's per-slot "
                    "ext_reads/ext_writes counters stay at 0 (asserted by "
                    "tests/test_sxt028j.py).",
        },
        "on_chip_small_state": {
            "per_instance": {
                "tdf2_history_bits": history_bits,
                "occupancy_bits": OCCUPANCY_BITS_PER_INSTANCE,
                "coefficient_register_bits": coeff_bits,
                "history_plus_occupancy_bits": per_instance_history,
            },
            "instances": N_INSTANCES,
            "shared_routing_control_bits": routing_control_bits,
            "shared_fsm_bits": fsm_bits,
            "sibling_comparable_bits_total": comparable_total,
            "sibling_comparable_note":
                "histories + occupancy + routing-control bits only -- the "
                "same accounting the landed sibling routing leaves "
                "(rf-rf-global2: 661 bits, rf-rf-bins12: 663 bits) used, so "
                "the three routing forms are directly comparable.",
            "full_bits_total": full_total,
            "full_note": "additionally counts the per-slot coefficient "
                         "configuration registers and the block FSM, which "
                         "the RTL really instantiates.",
            "full_bytes_total": (full_total + 7) // 8,
        },
        "ext_mem_traffic_estimate":
            "[PENDING-SXT-016] this leaf's own contribution is 0 "
            "words/sample (see external_traffic above); the AGGREGATE "
            "estimate for a concrete preset also depends on whichever "
            "algorithm leaf's occupant actually lands in global3/global4, "
            "which is out of this leaf's scope -- no aggregate number is "
            "invented here",
        "long_buffers_policy":
            "delay/reverb-class buffers live in external WRITABLE memory; "
            "processing stays on-chip; flash is not writable delay memory "
            "(AGENTS.md) -- not applicable to this leaf's own (register-"
            "only) contribution",
        "cost_closure": {
            "status": "[PENDING-SXT-016]",
            "note": "no cycles-per-frame, schedule-fit or bundle-closure "
                    "number is asserted by this leaf. SXT-015 accounting "
                    "consumes the inventory above; SXT-016 decides fit; "
                    "profile v1 is NOT frozen (SXT-017, issue #12).",
        },
        "model_revision": rm.model_revision(),
    }


def main():
    doc = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({
        "sibling_comparable_bits_total":
            doc["on_chip_small_state"]["sibling_comparable_bits_total"],
        "full_bits_total": doc["on_chip_small_state"]["full_bits_total"],
        "external_words_per_sample": doc["external_traffic"]["words_per_sample"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
