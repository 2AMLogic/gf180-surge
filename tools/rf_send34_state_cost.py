#!/usr/bin/env python3
"""SXT-028l: state/cost inventory for the extended send-rack routing form,
DERIVED from the frozen model's own declared word widths rather than
hand-counted.

Scope of the claim: this leaf's OWN state/cost contribution -- the routing /
scheduling / lifecycle logic, its per-bus send+return gain plane, and its
synthetic register-only occupant kernel. It is NOT the external-memory
footprint of whichever concrete Surge FX algorithm actually occupies
send3/send4 in a real preset (Reverb 2, Nimbus, Spring Reverb, Delay,
Chorus, Distortion, Phaser all appear on these buses in the committed
corpus); that is that algorithm leaf's own SXT-015/016 accounting, and the
AGGREGATE remains `[PENDING-SXT-016]` per the issue text. No
cycles-per-frame, schedule-fit or bundle-closure number is asserted.

Writes reports/SXT-028l/artifacts/state-cost.json.
Original to this repository (Apache-2.0).
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-send34"))

import rf_send34_model as rm  # noqa: E402

OUT = os.path.join(REPO, "reports", "SXT-028l", "artifacts", "state-cost.json")

N_INSTANCES = 2          # send3, send4
TDF2_REGS_PER_INSTANCE = 4   # reg0/reg1 x {L, R}
COEFFS_PER_INSTANCE = 5      # b0 b1 b2 a1 a2
GAINS_PER_BUS = 3            # send_gain_a, send_gain_b, return_gain
OCCUPANCY_BITS_PER_INSTANCE = 1   # `occupied` / RTL prev_occ latch


def build():
    history_bits = TDF2_REGS_PER_INSTANCE * rm.R_BITS
    per_instance_history = history_bits + OCCUPANCY_BITS_PER_INSTANCE
    coeff_bits = COEFFS_PER_INSTANCE * rm.C_BITS
    gain_bits = GAINS_PER_BUS * rm.G_BITS
    routing_control_bits = {
        "fx_bypass (2-bit mode)": 2,
        f"fx_disable (16-bit, engine layout; only bits "
        f"{rm.FXSLOT_SEND3}/{rm.FXSLOT_SEND4} consumed)": 16,
        "scene_b_active (scene B instantiated at all)": 1,
        "per-bus ring memory (send_ring[2] / ring3, ring4)": 2,
    }
    fsm_bits = {
        "FSM state": 3, "sample counter k": 6,
        "run_b3/run_b4 gate latches": 2,
    }
    shared_routing = sum(routing_control_bits.values())
    shared_fsm = sum(fsm_bits.values())
    comparable_total = N_INSTANCES * per_instance_history + shared_routing
    gain_plane_total = N_INSTANCES * gain_bits
    full_total = (N_INSTANCES * (per_instance_history + coeff_bits + gain_bits)
                  + shared_routing + shared_fsm)
    return {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "issue": "#64",
        "form": "rf-send34",
        "basis": "derived from the frozen model's declared word widths "
                 "(rf_send34_model.R_BITS / C_BITS / G_BITS and the RTL's "
                 "register declarations), not hand-counted",
        "claim": "This leaf's OWN state/cost addition (the routing / "
                 "scheduling / lifecycle logic, its per-bus send+return gain "
                 "plane, and its synthetic per-slot occupant kernel) -- NOT "
                 "the ext-mem footprint of whichever concrete Surge FX "
                 "algorithm actually occupies send3/send4 in a real preset, "
                 "which is that algorithm leaf's own SXT-015/016 accounting.",
        "external_writable_memory": {
            "words_total": 0,
            "note": "the synthetic occupant kernel (BiquadInstance) is "
                    "register-only (on-chip); it owns no delay line and "
                    "touches no external buffer. The send buses themselves "
                    "are per-block scratch, not history. A concrete "
                    "tail-bearing occupant (Reverb 2 / Nimbus / Spring "
                    "Reverb / Delay are all real corpus occupants of these "
                    "two buses) landed in this slot owns its own "
                    "external-memory accounting separately.",
        },
        "external_traffic": {
            "words_per_sample": 0,
            "note": "no external-memory transactions originate from this "
                    "leaf's own routing/scheduling/lifecycle logic, its gain "
                    "plane or its synthetic occupant; the frozen model's "
                    "per-slot ext_reads/ext_writes counters stay at 0 "
                    "(asserted by tests/test_sxt028l.py).",
        },
        "on_chip_small_state": {
            "per_instance": {
                "tdf2_history_bits": history_bits,
                "occupancy_bits": OCCUPANCY_BITS_PER_INSTANCE,
                "coefficient_register_bits": coeff_bits,
                "history_plus_occupancy_bits": per_instance_history,
            },
            "per_bus_gain_plane_bits": gain_bits,
            "gain_plane_total_bits": gain_plane_total,
            "gain_plane_note":
                "NEW in this routing form: the series insert/global leaves "
                "have no gain plane at all. Three Q1.30 words per bus "
                "(scene-A send, scene-B send, return). Bus state, not "
                "occupant state -- a loadFx() does not disturb it.",
            "instances": N_INSTANCES,
            "shared_routing_control_bits": routing_control_bits,
            "shared_fsm_bits": fsm_bits,
            "sibling_comparable_bits_total": comparable_total,
            "sibling_comparable_note":
                "histories + occupancy + routing-control bits only -- the "
                "same accounting the landed sibling routing leaves "
                "(rf-rf-global2: 661 bits, rf-rf-bins12: 663 bits, "
                "rf-rf-global34: 661 bits) used, so the routing forms are "
                "directly comparable. This form's gain plane "
                f"(+{gain_plane_total} bits) is reported SEPARATELY rather "
                "than folded into that number, because it has no counterpart "
                "in the series forms.",
            "full_bits_total": full_total,
            "full_note": "additionally counts the per-slot coefficient "
                         "configuration registers, the per-bus gain plane "
                         "and the block FSM, which the RTL really "
                         "instantiates.",
            "full_bytes_total": (full_total + 7) // 8,
        },
        "ext_mem_traffic_estimate":
            "[PENDING-SXT-016] this leaf's own contribution is 0 "
            "words/sample (see external_traffic above); the AGGREGATE "
            "estimate for a concrete preset also depends on whichever "
            "algorithm leaf's occupant actually lands in send3/send4 -- and "
            "the corpus really does put long-buffer classes there (Reverb 2, "
            "Nimbus, Spring Reverb, Delay) -- which is out of this leaf's "
            "scope; no aggregate number is invented here",
        "long_buffers_policy":
            "delay/reverb-class buffers live in external WRITABLE memory; "
            "processing stays on-chip; flash is not writable delay memory "
            "(AGENTS.md). Not applicable to this leaf's own (register-only) "
            "contribution, but it IS the live question for the concrete "
            "occupants the corpus puts on these buses -- routed to "
            "SXT-015/016, not answered here.",
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
        "gain_plane_total_bits":
            doc["on_chip_small_state"]["gain_plane_total_bits"],
        "full_bits_total": doc["on_chip_small_state"]["full_bits_total"],
        "external_words_per_sample": doc["external_traffic"]["words_per_sample"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
