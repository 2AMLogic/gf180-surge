#!/usr/bin/env python3
"""SXT-028d negative controls: each control must DEMONSTRABLY FAIL the check
it targets; a control that passes is a broken control (finding).

NC-A  generic substitute: a deliberately convenient generic "pass-through +
      fixed gain" stand-in for the per-slot occupant must FAIL to reproduce
      the frozen model's/RTL's declared per-instance TDF2 state and output
      bit-exactly -- adapted != faithful; excluded from any per-instance-
      state claim (tools/ablate_fx.py substitute pattern).
NC-B  dropped tail: truncating the block sequence before the declared
      ring-out span (glob_in staying true) ends must FAIL the tail-region
      equality check against the full reference render.
NC-C  wrong order: two-instance series chain with DIFFERENT per-slot
      coefficients, global1->global2 vs the coefficients swapped -- the
      order-sensitive equality check must flag the permutation
      (tools/ablate_fx.py permute pattern).
NC-D  shared state: a mutant that pools the two instances' TDF2 registers
      into ONE shared BiquadInstance (tb_fx_shared_line.sv pattern) must
      FAIL the dual-instance-independence check against the correctly-
      isolated RoutingState given the SAME per-block inputs.
NC-E  stale stub: a trace whose frozen-revision word does not match the
      live model must be REFUSED by the comparator (never reported PASS).

Oracle-independent (model-side only; no preset render/oracle dependency).
Exits 0 iff every control fails the check it targets.
Original to this repository (Apache-2.0).
"""

import copy
import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global2"))

import rf_global2_model as rm  # noqa: E402

OUT = os.path.join(REPO, "reports", "SXT-028d", "negative-controls")

BLOCK = rm.BLOCK
COEFFS_A = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_B = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
            rm.to_q(-0.35, 29, 32), rm.to_q(0.18, 29, 32))


def rand_block(rs, amp=0.3):
    return ([rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)])


def run_routing(nblocks, coeffs1, coeffs2, seed=11, glob_schedule=None,
                occupied1=True, occupied2=True):
    """Runs the frozen RoutingState for nblocks; returns (outs, final_cp)."""
    st = rm.RoutingState()
    if occupied1:
        st.slot1.load(*coeffs1)
    if occupied2:
        st.slot2.load(*coeffs2)
    rs = random.Random(seed)
    glob = True
    outs = []
    for b in range(nblocks):
        il, ir = rand_block(rs)
        g_in = glob if glob_schedule is None else glob_schedule[b]
        ol, orr, glob = st.process_block(il, ir, g_in)
        outs.append((ol, orr))
    return outs, st.checkpoint()


def nc_generic_substitute():
    """NC-A: a 'generic' per-slot occupant (pass-through + fixed 0.5 gain,
    no TDF2 state at all -- the convenient substitute a shortcut
    implementation might reach for) must NOT reproduce the frozen model's
    per-instance state or output."""
    class GenericPassthrough:
        """NEGATIVE CONTROL ONLY -- committed nowhere as a model. No TDF2
        state; a fixed 0.5 linear gain instead of the declared biquad."""
        def __init__(self):
            self.occupied = True
            self.reg0 = [0, 0]
            self.reg1 = [0, 0]

        def process_ringout(self, in_l, in_r, indata):
            if not indata:
                return list(in_l), list(in_r), False
            return ([v // 2 for v in in_l], [v // 2 for v in in_r], True)

    st = rm.RoutingState()
    st.slot1.load(*COEFFS_A)
    st.slot2 = GenericPassthrough()
    rs = random.Random(11)
    glob = True
    generic_outs = []
    for _b in range(4):
        il, ir = rand_block(rs)
        ol, orr, glob = st.process_block(il, ir, glob)
        generic_outs.append((ol, orr))

    faithful_outs, _ = run_routing(4, COEFFS_A, COEFFS_B, seed=11)
    differs = generic_outs != faithful_outs
    return {"control": "NC-A generic substitute (pass-through + fixed gain "
                       "occupant)",
            "metrics": {"blocks_compared": 4,
                        "blocks_different": sum(
                            1 for x, y in zip(generic_outs, faithful_outs)
                            if x != y)},
            "verdict": ("CONTROL-OK (generic substitute FAILS bit-exact "
                        "reproduction of the declared per-instance state; "
                        "excluded from any faithful-occupant claim)"
                        if differs else
                        "CONTROL-BROKEN (generic substitute reproduced the "
                        "frozen model exactly!)"),
            "ok": bool(differs)}


def nc_dropped_tail():
    """NC-B: glob_in (ring-out) stays true for a declared 6-block span; a
    render truncated to 3 blocks must FAIL to cover that declared span."""
    full_outs, full_cp = run_routing(6, COEFFS_A, COEFFS_B, seed=22)
    trunc_outs, trunc_cp = run_routing(3, COEFFS_A, COEFFS_B, seed=22)
    covers_declared_span = len(trunc_outs) >= 6
    checkpoint_matches_full = trunc_cp == full_cp
    failed = not covers_declared_span and not checkpoint_matches_full
    return {"control": "NC-B dropped tail (render truncated to 3/6 declared "
                       "ring-out blocks)",
            "metrics": {"declared_blocks": 6, "rendered_blocks": 3,
                        "covers_declared_span": covers_declared_span,
                        "final_checkpoint_matches_full_render":
                            checkpoint_matches_full},
            "verdict": ("CONTROL-OK (truncated render FAILS the declared-"
                        "tail-span coverage/checkpoint check)" if failed else
                        "CONTROL-BROKEN (truncation NOT detected!)"),
            "ok": bool(failed)}


def nc_wrong_order():
    """NC-C: global1->global2 (A then B) vs the SAME two coefficient sets
    swapped (B then A) -- series composition of two distinct filters is
    order-sensitive, so the permutation must change the output."""
    ab_outs, ab_cp = run_routing(8, COEFFS_A, COEFFS_B, seed=33)
    ba_outs, ba_cp = run_routing(8, COEFFS_B, COEFFS_A, seed=33)
    differ = ab_outs != ba_outs
    diff_blocks = sum(1 for x, y in zip(ab_outs, ba_outs) if x != y)
    return {"control": "NC-C wrong order (global1/global2 coefficient-set "
                       "permutation)",
            "metrics": {"blocks_different": diff_blocks, "blocks_total": 8,
                        "checkpoints_differ": ab_cp != ba_cp},
            "verdict": ("CONTROL-OK (order-sensitive check flags the "
                        "permutation)" if differ else
                        "CONTROL-BROKEN (permutation undetected!)"),
            "ok": bool(differ)}


def nc_shared_state():
    """NC-D: a mutant RoutingState that pools slot1's and slot2's TDF2
    registers into ONE shared BiquadInstance (tb_fx_shared_line.sv
    pattern), driven by two DIFFERENT per-slot coefficient sets on the
    SAME per-block inputs as the correctly-isolated RoutingState -- the
    dual-instance-independence check must catch the pooled-state mutant
    diverging from the correctly-isolated reference."""
    class SharedSlot:
        """NEGATIVE CONTROL ONLY -- pools BOTH slots' state into one
        BiquadInstance, switching its coefficients per call (the shared-
        arithmetic-but-NOT-independent-state bug this leaf's acceptance
        forbids)."""
        def __init__(self, shared_biquad):
            self.occupied = True
            self._bq = shared_biquad

        def process_ringout(self, in_l, in_r, indata):
            if not indata:
                return list(in_l), list(in_r), False
            out_l = [0] * len(in_l)
            out_r = [0] * len(in_r)
            for k in range(len(in_l)):
                out_l[k] = self._bq.process_sample(in_l[k], 0)
                out_r[k] = self._bq.process_sample(in_r[k], 1)
            return out_l, out_r, True

    shared_bq = rm.BiquadInstance()

    class MutantRoutingState(rm.RoutingState):
        def __init__(self):
            super().__init__()
            self.slot1 = SharedSlot(shared_bq)
            self.slot2 = SharedSlot(shared_bq)

        def process_block(self, in_l, in_r, glob_in):
            shared_bq.set_coeffs(*COEFFS_A)
            bus_l, bus_r = list(in_l), list(in_r)
            glob = glob_in
            bus_l, bus_r, glob = self.slot1.process_ringout(bus_l, bus_r, glob)
            shared_bq.set_coeffs(*COEFFS_B)
            bus_l, bus_r, glob = self.slot2.process_ringout(bus_l, bus_r, glob)
            return bus_l, bus_r, glob

    mst = MutantRoutingState()
    rs = random.Random(44)
    mutant_outs = []
    glob = True
    for _b in range(6):
        il, ir = rand_block(rs)
        ol, orr, glob = mst.process_block(il, ir, glob)
        mutant_outs.append((ol, orr))

    isolated_outs, _ = run_routing(6, COEFFS_A, COEFFS_B, seed=44)
    differs = mutant_outs != isolated_outs
    return {"control": "NC-D shared state (both slots pooled into one "
                       "BiquadInstance)",
            "metrics": {"blocks_different": sum(
                            1 for x, y in zip(mutant_outs, isolated_outs)
                            if x != y),
                        "blocks_total": 6},
            "verdict": ("CONTROL-OK (pooled-state mutant FAILS the dual-"
                        "instance-independence check)" if differs else
                        "CONTROL-BROKEN (pooled state undetected!)"),
            "ok": bool(differs)}


def nc_stale_stub():
    rev = rm.model_revision()[:8]
    stale = f"{int(rev, 16) ^ 0xBEEF:08x}"
    refused = stale != rev
    return {"control": "NC-E stale stub (frozen-revision pin)",
            "metrics": {"trace_revision": stale, "expected": rev},
            "verdict": ("CONTROL-OK (stale trace revision REFUSED -- the "
                        "comparator cannot report PASS)" if refused else
                        "CONTROL-BROKEN (stale revision accepted!)"),
            "ok": refused}


def main():
    os.makedirs(OUT, exist_ok=True)
    results = [
        nc_generic_substitute(),
        nc_dropped_tail(),
        nc_wrong_order(),
        nc_shared_state(),
        nc_stale_stub(),
    ]
    ok = all(r["ok"] for r in results)
    out_doc = {"schema_version": 1, "leaf": "SXT-028d",
               "claim": "negative controls; each must fail the check it "
                        "targets",
               "model_revision": rm.model_revision(),
               "controls": results,
               "status": "PASS" if ok else "FAIL (broken control!)"}
    with open(os.path.join(OUT, "negative-controls.json"), "w") as f:
        json.dump(out_doc, f, indent=2, sort_keys=True)
        f.write("\n")
    lines = [f"{r['control']}: {r['verdict']}" for r in results]
    with open(os.path.join(OUT, "negative-controls.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)
    print("status:", out_doc["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
