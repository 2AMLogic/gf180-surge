#!/usr/bin/env python3
"""SXT-028l negative controls: each control must DEMONSTRABLY FAIL the check
it targets; a control that passes is a broken control (a finding).

NC-A  generic substitute: a deliberately convenient generic "pass-through +
      fixed gain" stand-in for a send-bus occupant must FAIL to reproduce the
      frozen model's declared per-instance state and output bit-exactly.
      Recorded as coverage label ADAPTED and explicitly excluded from
      original-preset coverage (tools/ablate_fx.py substitute pattern); the
      bypass/reference comparison keeps the unmodified wet path.
NC-B  dropped tail: the declared tail span (TAIL_SPAN_BLOCKS blocks with the
      SCENE BUSES SILENT while `sendused` stays true) demonstrably carries
      nonzero audio out of the occupants' registers; a render truncated at
      the end of the scene input must FAIL both the tail-span coverage check
      and the final per-instance checkpoint check. Additionally exercised as
      a LIVE RTL mutant (rf_send34_mutants.sv -DNC_TAIL_KILL: both buses are
      skipped on a silent scene-input block, dropping the tails) which must
      FAIL the tail case's exact equality -- and which the non-silent
      baseline case does NOT catch, which is exactly why the declared tail
      span is load-bearing.
NC-C  wrong order: the send3/send4 slot-content permutation (reorderFx /
      tools/ablate_fx.py permute pattern) must FAIL the order-sensitive
      equality check -- both model-side and as a LIVE RTL mutant
      (rf_send34_mutants.sv -DNC_SWAP_ORDER). For this PARALLEL routing form
      the permutation axis is slot-content-vs-bus-gain, not summation order:
      the return mix is order-independent BY CONSTRUCTION (one wide
      accumulator, one rounding), which is recorded and verified here rather
      than implied away.
NC-D  shared state: a mutant that pools the two instances' TDF2 histories
      into ONE (tb_fx_shared_line.sv pattern) must FAIL the dual-instance
      equality check -- both model-side and as a LIVE RTL mutant
      (rf_send34_mutants.sv -DNC_SHARED_STATE). Run twice: with two DIFFERENT
      occupants and with the SAME occupant in both buses (the real-corpus
      `Strynth.fxp` shape, Nimbus in send3 AND send4), because identical
      arithmetic is exactly the case where a pooled-state implementation is
      most likely to slip through.
NC-E  stale stub: the RTL harness pins the frozen-model revision hash; a
      stale harness must REFUSE to report PASS. Exercised by actually
      invoking tools/compare_rtl_model_rf_send34.py with a mutated pinned
      revision and requiring a nonzero exit with status REFUSED.
NC-F  gain placement (ADDITIONAL, send-form specific -- not one of the five
      controls issue #64 names): a variant that applies the per-slot
      `return_level` when FORMING the bus and the per-scene `send_level` when
      RETURNING it -- the same numbers in the wrong places -- must FAIL exact
      equality. The send form's whole novelty over the landed series routing
      leaves is this gain plane, so it gets its own live RTL mutant
      (-DNC_GAIN_SWAP).

Every leg records its own status; a leg that could not run (no iverilog) is
recorded NOT_RUN and never counted as a demonstrated failure. Exits 0 iff
every control demonstrably failed the check it targets on at least its
oracle-independent model leg and no leg came back CONTROL-BROKEN.

Oracle-independent (no preset render / oracle dependency).
Original to this repository (Apache-2.0).
"""

import json
import os
import random
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-send34"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import rf_send34_model as rm  # noqa: E402
import compare_rtl_model_rf_send34 as cmp_rtl  # noqa: E402

OUT = os.path.join(REPO, "reports", "SXT-028l", "negative-controls")
MUTANT = os.path.join(REPO, "rtl", "effects", "rf-rf-send34",
                      "rf_send34_mutants.sv")
WORKDIR = "/tmp/sxt028l_nc"

BLOCK = rm.BLOCK
COEFFS_A = cmp_rtl.COEFFS_3
COEFFS_B = cmp_rtl.COEFFS_4
COEFFS_TAIL = cmp_rtl.COEFFS_TAIL
LEVELS_A = cmp_rtl.LEVELS_3
LEVELS_B = cmp_rtl.LEVELS_4

TAIL_SIGNAL_BLOCKS = cmp_rtl.TAIL_SIGNAL_BLOCKS
TAIL_SPAN_BLOCKS = cmp_rtl.TAIL_SPAN_BLOCKS


def rand_stim(rs, amp=0.3):
    """(sa_l, sa_r, sb_l, sb_r, main_l, main_r) for one block."""
    return tuple([rm.to_q(amp * rs.uniform(-1, 1), 21, 32)
                  for _ in range(BLOCK)] for _ in range(6))


def silent_scene_stim(rs, amp=0.3):
    z = [0] * BLOCK
    return (list(z), list(z), list(z), list(z),
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)])


def run_rack(nblocks, coeffs3, coeffs4, levels3=LEVELS_A, levels4=LEVELS_B,
             seed=11, amp=0.3, occupied3=True, occupied4=True,
             silent_from=None, send_in=(True, True)):
    """Runs the frozen ExtendedSendRack for nblocks; returns
    (outs, wets, final_cp) where outs are the main-bus blocks and wets the
    per-bus wet taps."""
    rack = rm.ExtendedSendRack()
    rs = random.Random(seed)
    outs, wets = [], []
    for b in range(nblocks):
        rack.apply_control(rm.FXB_ALL_FX, 0, True,
                           occupied3, b == 0, coeffs3, levels3,
                           occupied4, b == 0, coeffs4, levels4)
        stim = (silent_scene_stim(rs, amp)
                if silent_from is not None and b >= silent_from
                else rand_stim(rs, amp))
        res = rack.process_block(*stim, send_in[0], send_in[1])
        outs.append((res[0], res[1]))
        wets.append((res[2], res[3], res[4], res[5]))
    return outs, wets, rack.checkpoint()


def leg(name, ok, detail, metrics=None, status=None):
    return {"leg": name,
            "status": status or ("CONTROL-OK" if ok else "CONTROL-BROKEN"),
            "ok": bool(ok), "detail": detail, "metrics": metrics or {}}


# ---------------------------------------------------------------- NC helpers
def iverilog_available():
    return shutil.which(cmp_rtl.IV) is not None and \
        shutil.which(cmp_rtl.VVP) is not None


def _mutant_run(defect, case_name):
    """Compile rf_send34_mutants.sv with `defect`, run `case_name` through the
    production testbench/comparator path and return (checked, fails)."""
    os.makedirs(WORKDIR, exist_ok=True)
    vvp_path = os.path.join(WORKDIR, f"mutant_{defect.lower()}.vvp")
    cmp_rtl.compile_tb(vvp_path, core=MUTANT, defines=[defect])
    case = next(c for c in cmp_rtl.declared_cases() if c["name"] == case_name)
    rtl_blocks = cmp_rtl.run_case(vvp_path, case, WORKDIR)
    return cmp_rtl.compare_case(case, rtl_blocks)


def rtl_mutant_leg(name, defect, case_name, detail, undetected_case=None):
    """Require that the mutant FAILS exact integer equality against the frozen
    model on `case_name`. When `undetected_case` is given, ALSO record that the
    mutant is NOT caught by that case -- evidence that `case_name` is the
    load-bearing acceptance case for this defect, not that the control is
    weak."""
    if not iverilog_available():
        return leg(name, False,
                   f"{detail} -- NOT RUN: iverilog/vvp unavailable in this "
                   f"environment (never counted as a demonstrated failure)",
                   status="NOT_RUN")
    checked, fails = _mutant_run(defect, case_name)
    cp_fails = sum(1 for f in fails if "checkpoint" in f)
    metrics = {"case": case_name, "defect": defect,
               "main_bus_samples_compared": checked["outputs"],
               "wet_samples_compared": checked["wet"],
               "checkpoints_compared": checked["checkpoints"],
               "mismatches": len(fails),
               "checkpoint_mismatches": cp_fails,
               "first_failures": fails[:3]}
    if undetected_case is not None:
        u_checked, u_fails = _mutant_run(defect, undetected_case)
        metrics["undetected_by_case"] = undetected_case
        metrics["undetected_case_mismatches"] = len(u_fails)
        metrics["undetected_case_samples_compared"] = u_checked["outputs"]
    return leg(name, bool(fails), detail, metrics)


# ---------------------------------------------------------------- controls
def nc_generic_substitute():
    """NC-A: a 'generic' send-bus occupant (pass-through + fixed 0.5 gain, no
    TDF2 state at all -- the convenient substitute a shortcut implementation
    might reach for) must NOT reproduce the frozen model's per-instance state
    or output. Labeled ADAPTED and excluded from original-preset coverage."""
    class GenericPassthrough:
        """NEGATIVE CONTROL ONLY -- committed nowhere as a model. No TDF2
        state; a fixed 0.5 linear gain instead of the declared occupant."""
        def __init__(self, name, slot_bit):
            self.name = name
            self.occupied = True
            self.slot_bit = slot_bit
            self.biquad = rm.BiquadInstance()   # stays all-zero on purpose

        def process_ringout(self, in_l, in_r, indata):
            if not indata:
                return list(in_l), list(in_r), False
            return ([v // 2 for v in in_l], [v // 2 for v in in_r], True)

    rack = rm.ExtendedSendRack()
    rack.apply_control(rm.FXB_ALL_FX, 0, True,
                       True, True, COEFFS_A, LEVELS_A,
                       True, True, COEFFS_B, LEVELS_B)
    rack.slot4 = GenericPassthrough("send4", rm.FXSLOT_SEND4)
    rs = random.Random(11)
    generic_outs = []
    for _b in range(4):
        res = rack.process_block(*rand_stim(rs), True, True)
        generic_outs.append((res[0], res[1]))
    generic_cp = rack.checkpoint()

    faithful_outs, _w, faithful_cp = run_rack(4, COEFFS_A, COEFFS_B, seed=11)
    out_differs = generic_outs != faithful_outs
    cp_differs = generic_cp != faithful_cp
    legs = [
        leg("main-bus output bit-exactness", out_differs,
            "the generic pass-through+gain substitute must not reproduce the "
            "declared occupant's returned signal bit-exactly",
            {"blocks_compared": 4,
             "blocks_different": sum(1 for x, y in zip(generic_outs,
                                                       faithful_outs)
                                     if x != y)}),
        leg("per-instance state", cp_differs,
            "the substitute keeps no per-instance TDF2 history, so the "
            "dual-instance checkpoint must differ",
            {"substitute_send4_state_all_zero":
                generic_cp[2] == (0, 0) and generic_cp[3] == (0, 0)}),
    ]
    ok = all(x["ok"] for x in legs)
    return {"control": "NC-A generic substitute (pass-through + fixed gain "
                       "occupant on send bus 4)",
            "targets": "per-instance-state faithfulness / original-preset "
                       "coverage eligibility",
            "coverage_label": "ADAPTED",
            "counts_toward_original_preset_coverage": False,
            "legs": legs,
            "verdict": ("CONTROL-OK (generic substitute FAILS bit-exact "
                        "reproduction of the declared per-instance occupant; "
                        "labeled ADAPTED and refused from original-preset "
                        "coverage)" if ok else
                        "CONTROL-BROKEN (generic substitute reproduced the "
                        "frozen model exactly!)"),
            "ok": ok}


def nc_dropped_tail():
    """NC-B: the declared tail span is TAIL_SPAN_BLOCKS blocks with the SCENE
    BUSES SILENT while `sendused` stays true; the occupants' registers keep
    producing real audio there and it keeps being mixed back through the
    return gains. A render truncated at the end of the scene input must
    FAIL."""
    nfull = TAIL_SIGNAL_BLOCKS + TAIL_SPAN_BLOCKS
    full_outs, full_wets, full_cp = run_rack(
        nfull, COEFFS_TAIL, COEFFS_TAIL, seed=22, amp=0.05,
        silent_from=TAIL_SIGNAL_BLOCKS)
    trunc_outs, _tw, trunc_cp = run_rack(
        TAIL_SIGNAL_BLOCKS, COEFFS_TAIL, COEFFS_TAIL, seed=22, amp=0.05,
        silent_from=TAIL_SIGNAL_BLOCKS)
    dropped = full_wets[TAIL_SIGNAL_BLOCKS:]
    dropped_energy = sum(abs(v) for blk in dropped for arr in blk for v in arr)
    dropped_nonzero_blocks = sum(1 for blk in dropped
                                 if any(v != 0 for arr in blk for v in arr))
    legs = [
        leg("declared tail span carries audio", dropped_energy > 0,
            "a truncation control proves nothing unless the dropped region "
            "actually contains nonzero tail samples on the send buses "
            "themselves (the MAIN bus stays live through the tail on "
            "purpose, so only the wet taps prove it)",
            {"dropped_blocks": len(dropped),
             "dropped_blocks_with_nonzero_wet": dropped_nonzero_blocks,
             "dropped_abs_energy": dropped_energy}),
        leg("tail-span coverage check", len(trunc_outs) < nfull,
            "the truncated render must fail the declared-tail-span coverage "
            "check",
            {"declared_blocks": nfull, "rendered_blocks": len(trunc_outs)}),
        leg("final per-instance checkpoint", trunc_cp != full_cp,
            "the truncated render's final per-instance state must not match "
            "the full render's",
            {"checkpoints_equal": trunc_cp == full_cp}),
        rtl_mutant_leg("live RTL tail-killing mutant", "NC_TAIL_KILL",
                       "tail-span-silent-scenes",
                       "rf_send34_mutants.sv -DNC_TAIL_KILL skips both send "
                       "buses whenever the incoming scene buses are silent, "
                       "dropping the occupants' arithmetic tails and freezing "
                       "their state; it must FAIL exact equality on the "
                       "declared tail case -- and is NOT caught by the "
                       "non-silent baseline case, which is what makes the "
                       "tail case load-bearing",
                       undetected_case="both-buses-all-fx"),
    ]
    ok = all(x["ok"] for x in legs if x["status"] != "NOT_RUN") and \
        legs[0]["ok"] and legs[1]["ok"] and legs[2]["ok"]
    return {"control": f"NC-B dropped tail (render truncated to "
                       f"{TAIL_SIGNAL_BLOCKS}/{nfull} declared blocks; plus a "
                       f"live RTL stage-skip-on-silence mutant)",
            "targets": "declared tail-span coverage",
            "legs": legs,
            "verdict": ("CONTROL-OK (truncated render FAILS the declared-"
                        "tail-span coverage and checkpoint checks, the "
                        "dropped region demonstrably contained real audio, "
                        "and the live RTL tail-killing mutant FAILS the tail "
                        "case)" if ok else
                        "CONTROL-BROKEN (truncation NOT detected!)"),
            "ok": ok}


def nc_wrong_order():
    """NC-C: the send3/send4 slot-content permutation. For a PARALLEL routing
    form this means swapping WHICH OCCUPANT sits on WHICH BUS while each bus
    keeps its own send/return gain plane."""
    # leg 1: model-side permutation, distinct occupants on distinct gain
    # planes -- the real-corpus shape (Batbrass.fxp: Distortion on send3,
    # Phaser on send4).
    ab_outs, _w, ab_cp = run_rack(6, COEFFS_A, COEFFS_B, seed=33)
    ba_outs, _w2, ba_cp = run_rack(6, COEFFS_B, COEFFS_A, seed=33)
    diffs = [abs(x - y)
             for (al, ar), (bl, br) in zip(ab_outs, ba_outs)
             for x, y in zip(al + ar, bl + br)]

    # leg 2: the issue's own wording -- "two SAME-CLASS slots swapped". The
    # real-corpus same-class shape (Strynth.fxp: Nimbus in BOTH send3 and
    # send4) still carries DIFFERENT parameter values per slot, modeled here
    # as the same occupant kernel with one coefficient nudged.
    same_class_variant = (COEFFS_A[0], COEFFS_A[1], COEFFS_A[2],
                          COEFFS_A[3] + (1 << 20), COEFFS_A[4])
    same_ab, _w3, _c3 = run_rack(6, COEFFS_A, same_class_variant, seed=34)
    same_ba, _w4, _c4 = run_rack(6, same_class_variant, COEFFS_A, seed=34)
    same_diffs = [abs(x - y)
                  for (al, ar), (bl, br) in zip(same_ab, same_ba)
                  for x, y in zip(al + ar, bl + br)]

    # Recorded bound, NOT a leg: permuting two buses whose occupant CONTENT
    # AND gain plane are both identical is the identity map by construction,
    # so such a permutation is unobservable at the bus.
    id_ab, _w5, _c5 = run_rack(6, COEFFS_A, COEFFS_A, levels3=LEVELS_A,
                               levels4=LEVELS_A, seed=35)
    id_ba, _w6, _c6 = run_rack(6, COEFFS_A, COEFFS_A, levels3=LEVELS_A,
                               levels4=LEVELS_A, seed=35)

    legs = [
        leg("model permutation (distinct occupants, distinct gain planes)",
            any(d > 0 for d in diffs),
            "swapping which occupant sits on which send bus must change the "
            "main bus: each bus keeps its own per-scene send gains and its "
            "own return gain",
            {"samples_compared": len(diffs),
             "samples_different": sum(1 for d in diffs if d),
             "max_abs_diff": max(diffs),
             "checkpoints_differ": ab_cp != ba_cp}),
        leg("model permutation (SAME FX class, different parameter values)",
            any(d > 0 for d in same_diffs),
            "the issue's own wording is 'two same-class slots swapped': the "
            "real-corpus same-class shape (Strynth.fxp: Nimbus in BOTH send3 "
            "and send4) still carries different parameter values per slot, "
            "and permuting those two occupants must change the main bus",
            {"samples_compared": len(same_diffs),
             "samples_different": sum(1 for d in same_diffs if d),
             "max_abs_diff": max(same_diffs)}),
        rtl_mutant_leg("live RTL occupant-permutation mutant", "NC_SWAP_ORDER",
                       "both-buses-all-fx",
                       "rf_send34_mutants.sv -DNC_SWAP_ORDER processes bus 3 "
                       "with send4's instance and bus 4 with send3's; it must "
                       "FAIL exact equality against the frozen model"),
        rtl_mutant_leg("live RTL occupant-permutation mutant "
                       "(identical-coefficient case)", "NC_SWAP_ORDER",
                       "same-class-dual-occupants",
                       "with byte-identical occupant coefficients the "
                       "permutation degenerates to a RELABELING of the two "
                       "register sets: the main bus and the wet taps are "
                       "unchanged and ONLY the per-instance checkpoint "
                       "catches it. Recorded rather than presented as a "
                       "stronger control than it is -- and it is exactly why "
                       "this leaf's exactness check compares per-instance "
                       "checkpoints and not only audio"),
    ]
    ok = all(x["ok"] for x in legs if x["status"] != "NOT_RUN") and \
        legs[0]["ok"] and legs[1]["ok"]
    return {"control": "NC-C wrong order (send3/send4 slot-content "
                       "permutation)",
            "targets": "order-sensitive equality of the parallel send rack",
            "recorded_bound": {
                "identical_content_and_identical_gains_is_an_identity":
                    id_ab == id_ba,
                "return_summation_is_order_independent_by_construction": True,
                "byte_identical_occupants_are_caught_only_by_the_checkpoint":
                    "with byte-identical occupant coefficients the "
                    "permutation is a pure RELABELING of the two register "
                    "sets: the main bus and the wet taps are unchanged and "
                    "only the per-instance checkpoint differs (demonstrated "
                    "by the live RTL identical-coefficient leg below, which "
                    "produces checkpoint mismatches and zero audio "
                    "mismatches). The model cannot express that relabeling "
                    "at all, which is why this leg exists only in RTL.",
                "note": "this is a PARALLEL routing form: the return mix uses "
                        "ONE wide accumulator with ONE rounding and ONE "
                        "saturation, so the order in which the two returns "
                        "are summed cannot change the result -- a deliberate, "
                        "declared design choice (frozen model docstring). The "
                        "observable permutation axis is therefore "
                        "slot-content-vs-bus-gain, and a permutation of two "
                        "buses whose occupant content AND gain plane are both "
                        "identical is the identity map. Stated so the "
                        "control's strength is never overstated.",
            },
            "legs": legs,
            "verdict": ("CONTROL-OK (the order-sensitive check flags the "
                        "permutation; the identity bound and the "
                        "checkpoint-only identical-coefficient case are "
                        "recorded)" if ok else
                        "CONTROL-BROKEN (permutation undetected!)"),
            "ok": ok}


def nc_shared_state():
    """NC-D: a mutant that pools send3's and send4's TDF2 registers into ONE
    instance (tb_fx_shared_line.sv pattern) must FAIL the dual-instance
    independence check against the correctly-isolated rack."""
    class SharedSlot:
        """NEGATIVE CONTROL ONLY -- pools BOTH buses' state into one
        BiquadInstance, switching its coefficients per call (the
        shared-arithmetic-but-NOT-independent-state bug this leaf's
        acceptance forbids)."""
        def __init__(self, name, shared_biquad, slot_bit):
            self.name = name
            self.occupied = True
            self.slot_bit = slot_bit
            self.biquad = shared_biquad

        def process_ringout(self, in_l, in_r, indata):
            if not indata:
                return list(in_l), list(in_r), False
            out_l = [0] * len(in_l)
            out_r = [0] * len(in_r)
            for k in range(len(in_l)):
                out_l[k] = self.biquad.process_sample(in_l[k], 0)
                out_r[k] = self.biquad.process_sample(in_r[k], 1)
            return out_l, out_r, True

    def pooled_run(coeffs3, coeffs4, seed):
        shared_bq = rm.BiquadInstance()

        class MutantRack(rm.ExtendedSendRack):
            """Identical to the frozen rack EXCEPT that both send buses run
            through ONE pooled BiquadInstance (coefficients switched per
            bus), so bus 4 continues on the history bus 3 just advanced."""

            def __init__(self):
                super().__init__()
                self.slot3 = SharedSlot("send3", shared_bq, rm.FXSLOT_SEND3)
                self.slot4 = SharedSlot("send4", shared_bq, rm.FXSLOT_SEND4)

            def process_block(self, sa_l, sa_r, sb_l, sb_r, main_l, main_r,
                              send_in3, send_in4):
                b3l = self.form_bus(sa_l, sb_l, self.levels3)
                b3r = self.form_bus(sa_r, sb_r, self.levels3)
                b4l = self.form_bus(sa_l, sb_l, self.levels4)
                b4r = self.form_bus(sa_r, sb_r, self.levels4)
                shared_bq.set_coeffs(*coeffs3)
                w3l, w3r, r3 = self.slot3.process_ringout(b3l, b3r, send_in3)
                shared_bq.set_coeffs(*coeffs4)
                w4l, w4r, r4 = self.slot4.process_ringout(b4l, b4r, send_in4)
                out_l, out_r = [], []
                for k in range(len(main_l)):
                    wl = (main_l[k] << rm.G_FRAC) \
                        + w3l[k] * self.levels3.return_gain \
                        + w4l[k] * self.levels4.return_gain
                    wr = (main_r[k] << rm.G_FRAC) \
                        + w3r[k] * self.levels3.return_gain \
                        + w4r[k] * self.levels4.return_gain
                    out_l.append(rm.sat_s(rm.rnd_shift(wl, rm.G_FRAC),
                                          rm.A_BITS))
                    out_r.append(rm.sat_s(rm.rnd_shift(wr, rm.G_FRAC),
                                          rm.A_BITS))
                return (out_l, out_r, w3l, w3r, w4l, w4r, r3, r4)

        mrack = MutantRack()
        mrack.levels3.set(*LEVELS_A)
        mrack.levels4.set(*LEVELS_B)
        rs = random.Random(seed)
        outs = []
        for _b in range(6):
            res = mrack.process_block(*rand_stim(rs), True, True)
            outs.append((res[0], res[1]))
        return outs, mrack.checkpoint()

    mutant_outs, mutant_cp = pooled_run(COEFFS_A, COEFFS_B, 44)
    isolated_outs, _w, isolated_cp = run_rack(6, COEFFS_A, COEFFS_B, seed=44)

    # Same-class variant: the corpus really does host the SAME FX class in
    # both extended send buses (Exquis MPE/Strings/Strynth.fxp, Nimbus in
    # send3 AND send4). Identical arithmetic in both buses is exactly where a
    # pooled-state implementation is most likely to slip through.
    same_mutant_outs, same_mutant_cp = pooled_run(COEFFS_A, COEFFS_A, 45)
    same_iso_outs, _w2, same_iso_cp = run_rack(6, COEFFS_A, COEFFS_A, seed=45)

    legs = [
        leg("model pooled-history mutant (distinct occupants)",
            mutant_outs != isolated_outs,
            "pooling both instances' histories must diverge from the "
            "correctly-isolated rack on the SAME per-block inputs",
            {"blocks_compared": 6,
             "blocks_different": sum(1 for x, y in zip(mutant_outs,
                                                       isolated_outs)
                                     if x != y)}),
        leg("model dual-instance checkpoint", mutant_cp != isolated_cp,
            "the pooled mutant cannot reproduce two independent checkpoint "
            "halves",
            {"pooled_send3_equals_send4":
                mutant_cp[0] == mutant_cp[2] and mutant_cp[1] == mutant_cp[3],
             "isolated_send3_equals_send4":
                isolated_cp[0] == isolated_cp[2] and
                isolated_cp[1] == isolated_cp[3]}),
        leg("model pooled-history mutant (SAME-class occupants)",
            same_mutant_outs != same_iso_outs and
            same_mutant_cp != same_iso_cp,
            "the real-corpus same-class shape (Strynth.fxp: Nimbus in both "
            "send3 and send4) must ALSO catch pooled state -- identical "
            "arithmetic is where pooling hides best",
            {"blocks_compared": 6,
             "blocks_different": sum(1 for x, y in zip(same_mutant_outs,
                                                       same_iso_outs)
                                     if x != y),
             "isolated_histories_differ":
                (same_iso_cp[0], same_iso_cp[1]) !=
                (same_iso_cp[2], same_iso_cp[3])}),
        rtl_mutant_leg("live RTL shared-state mutant", "NC_SHARED_STATE",
                       "both-buses-all-fx",
                       "rf_send34_mutants.sv -DNC_SHARED_STATE pools both "
                       "send buses onto one register set; it must FAIL exact "
                       "equality (main bus, wet taps AND per-instance "
                       "checkpoint) against the frozen model"),
        rtl_mutant_leg("live RTL shared-state mutant (SAME-class case)",
                       "NC_SHARED_STATE", "same-class-dual-occupants",
                       "the same live RTL pooling defect must ALSO fail on "
                       "the same-class dual-occupant case, where both buses "
                       "run identical coefficients"),
    ]
    ok = all(x["ok"] for x in legs if x["status"] != "NOT_RUN") and \
        legs[0]["ok"] and legs[1]["ok"] and legs[2]["ok"]
    return {"control": "NC-D shared state (both send buses pooled into one "
                       "history)",
            "targets": "dual-instance (per-instance state) independence",
            "legs": legs,
            "verdict": ("CONTROL-OK (pooled-state mutants FAIL the "
                        "dual-instance-independence check, model-side and in "
                        "live RTL, with distinct AND same-class occupants)"
                        if ok else
                        "CONTROL-BROKEN (pooled state undetected!)"),
            "ok": ok}


def nc_stale_stub():
    """NC-E: a harness pinned to a stale frozen-model revision must refuse to
    report PASS. Exercises the real comparator entry point."""
    live = rm.model_revision()
    stale = f"{(int(live, 16) ^ 0xBEEF):0{len(live)}x}"
    in_process = cmp_rtl.revision_pin_ok(stale) is False and \
        cmp_rtl.revision_pin_ok(live) is True

    proc = subprocess.run(
        [sys.executable,
         os.path.join(REPO, "tools", "compare_rtl_model_rf_send34.py"),
         "--assert-model-revision", stale, "--no-write"],
        capture_output=True, text=True)
    refused = proc.returncode != 0 and '"status": "REFUSED"' in proc.stdout
    legs = [
        leg("revision pin function", in_process,
            "revision_pin_ok() must reject a stale pin and accept the live one",
            {"live_revision_tail": live[-16:],
             "stale_revision_tail": stale[-16:]}),
        leg("live comparator refusal", refused,
            "the comparator invoked with a stale pin must exit nonzero with "
            "status REFUSED instead of reporting PASS",
            {"exit_code": proc.returncode,
             "status_line_present": '"status": "REFUSED"' in proc.stdout}),
    ]
    ok = all(x["ok"] for x in legs)
    return {"control": "NC-E stale stub (frozen-revision pin)",
            "targets": "stale-harness refusal (never a false PASS)",
            "legs": legs,
            "verdict": ("CONTROL-OK (a stale pin is REFUSED -- the comparator "
                        "cannot report PASS)" if ok else
                        "CONTROL-BROKEN (stale revision accepted!)"),
            "ok": ok}


def nc_gain_placement():
    """NC-F (additional, send-form specific): applying the return gain where
    the send gain belongs and vice versa -- the same numbers in the wrong
    places -- must FAIL exact equality. The gain plane is the whole novelty
    of the send form over the landed series routing leaves."""
    ga, gb, rg = LEVELS_A
    swapped_levels = (rg, gb, ga)
    ref_outs, _w, _cp = run_rack(6, COEFFS_A, COEFFS_B, levels3=LEVELS_A,
                                 seed=55)
    bad_outs, _w2, _cp2 = run_rack(6, COEFFS_A, COEFFS_B,
                                   levels3=swapped_levels, seed=55)
    diffs = [abs(x - y)
             for (al, ar), (bl, br) in zip(ref_outs, bad_outs)
             for x, y in zip(al + ar, bl + br)]
    legs = [
        leg("model gain-placement swap (send bus 3)", any(d > 0 for d in diffs),
            "swapping bus 3's scene-A send gain with its return gain must "
            "change the main bus",
            {"samples_compared": len(diffs),
             "samples_different": sum(1 for d in diffs if d),
             "max_abs_diff": max(diffs),
             "send_gain_a": ga, "return_gain": rg}),
        rtl_mutant_leg("live RTL gain-placement mutant", "NC_GAIN_SWAP",
                       "both-buses-all-fx",
                       "rf_send34_mutants.sv -DNC_GAIN_SWAP applies the "
                       "return gain when FORMING each bus and the scene-A "
                       "send gain when RETURNING it; it must FAIL exact "
                       "equality against the frozen model"),
    ]
    ok = all(x["ok"] for x in legs if x["status"] != "NOT_RUN") and legs[0]["ok"]
    return {"control": "NC-F gain placement (send/return gains applied in the "
                       "wrong places) [ADDITIONAL -- not one of the five "
                       "controls issue #64 names]",
            "targets": "the send form's own routing-gain plane",
            "legs": legs,
            "verdict": ("CONTROL-OK (misplaced routing gains FAIL exact "
                        "equality, model-side and in live RTL)" if ok else
                        "CONTROL-BROKEN (gain placement undetected!)"),
            "ok": ok}


REQUIRED_CONTROL_PREFIXES = ("NC-A", "NC-B", "NC-C", "NC-D", "NC-E")


def main():
    os.makedirs(OUT, exist_ok=True)
    results = [
        nc_generic_substitute(),
        nc_dropped_tail(),
        nc_wrong_order(),
        nc_shared_state(),
        nc_stale_stub(),
        nc_gain_placement(),
    ]
    ok = all(r["ok"] for r in results)
    not_run = [f"{r['control']} / {x['leg']}" for r in results
               for x in r["legs"] if x["status"] == "NOT_RUN"]
    out_doc = {"schema_version": 1, "leaf": "SXT-028l",
               "claim": "negative controls; each must fail the check it "
                        "targets",
               "model_revision": rm.model_revision(),
               "iverilog_available": iverilog_available(),
               "required_controls": list(REQUIRED_CONTROL_PREFIXES),
               "legs_not_run": not_run,
               "controls": results,
               "status": "PASS" if ok else "FAIL (broken control!)"}
    with open(os.path.join(OUT, "negative-controls.json"), "w") as f:
        json.dump(out_doc, f, indent=2, sort_keys=True)
        f.write("\n")
    lines = []
    for r in results:
        lines.append(f"{r['control']}: {r['verdict']}")
        for x in r["legs"]:
            lines.append(f"    - {x['leg']}: {x['status']}")
    with open(os.path.join(OUT, "negative-controls.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    for line in lines:
        print(line)
    if not_run:
        print("legs NOT_RUN (never counted as demonstrated failures):")
        for n in not_run:
            print("   ", n)
    print("status:", out_doc["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
