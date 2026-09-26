#!/usr/bin/env python3
"""SXT-028h negative controls: each control must DEMONSTRABLY FAIL the check
it targets; a control that passes is a broken control (a finding).

NC-A  generic substitute: a deliberately convenient generic "pass-through +
      fixed gain" stand-in for a per-slot occupant must FAIL to reproduce the
      frozen model's declared per-instance state and output bit-exactly.
      Recorded as coverage label ADAPTED and explicitly excluded from
      original-preset coverage (tools/ablate_fx.py substitute pattern); the
      bypass/reference comparison keeps the unmodified wet path.
NC-B  dropped tail: the declared tail span (TAIL_SPAN_BLOCKS blocks of SILENT
      input while the scene stays live) demonstrably carries nonzero audio
      out of the occupant's registers; a render truncated at the end of the
      input must FAIL both the tail-span coverage check and the final
      per-instance checkpoint check.
NC-C  wrong order: the bins1/bins2 slot-content permutation (reorderFx /
      tools/ablate_fx.py permute pattern) must FAIL the order-sensitive
      equality check -- both model-side and as a LIVE RTL mutant
      (rf_bins12_mutants.sv -DNC_SWAP_ORDER) compared against the frozen
      model.
NC-D  shared state: a mutant that pools the two instances' TDF2 histories
      into ONE (tb_fx_shared_line.sv pattern) must FAIL the dual-instance
      equality check -- both model-side and as a LIVE RTL mutant
      (rf_bins12_mutants.sv -DNC_SHARED_STATE).
NC-E  stale stub: the RTL harness pins the frozen-model revision hash; a
      stale harness must REFUSE to report PASS. Exercised by actually
      invoking tools/compare_rtl_model_rf_bins12.py with a mutated pinned
      revision and requiring a nonzero exit with status REFUSED.

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
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-bins12"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import rf_bins12_model as rm  # noqa: E402
import compare_rtl_model_rf_bins12 as cmp_rtl  # noqa: E402

OUT = os.path.join(REPO, "reports", "SXT-028h", "negative-controls")
MUTANT = os.path.join(REPO, "rtl", "effects", "rf-rf-bins12",
                      "rf_bins12_mutants.sv")
WORKDIR = "/tmp/sxt028h_nc"

BLOCK = rm.BLOCK
COEFFS_A = cmp_rtl.COEFFS_1
COEFFS_B = cmp_rtl.COEFFS_2
COEFFS_TAIL = cmp_rtl.COEFFS_TAIL
# Saturating pair used by NC-C: two LTI biquads in series COMMUTE in exact
# arithmetic, so a permutation of a purely linear pair is detectable only
# through fixed-point rounding (1 LSB). With an intermediate stage that
# SATURATES (the hot occupant below), the permutation changes the output
# grossly -- and the engine's real insert occupants are not LTI at all. Both
# legs are reported; see reports/SXT-028h/EVIDENCE.md.
COEFFS_HOT = cmp_rtl.COEFFS_HOT
COEFFS_QUIET = (rm.to_q(0.05, 29, 32), 0, 0, rm.to_q(0.1, 29, 32), 0)

TAIL_SIGNAL_BLOCKS = cmp_rtl.TAIL_SIGNAL_BLOCKS
TAIL_SPAN_BLOCKS = cmp_rtl.TAIL_SPAN_BLOCKS


def rand_block(rs, amp=0.3):
    return ([rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(BLOCK)])


def run_bus(nblocks, coeffs1, coeffs2, seed=11, amp=0.3, sc_schedule=None,
            occupied1=True, occupied2=True, silent_from=None):
    """Runs the frozen SceneBInsertBus for nblocks; returns (outs, final_cp)."""
    bus = rm.SceneBInsertBus()
    rs = random.Random(seed)
    outs = []
    for b in range(nblocks):
        bus.apply_control(rm.FXB_ALL_FX, 0,
                          occupied1, b == 0, coeffs1,
                          occupied2, b == 0, coeffs2)
        if silent_from is not None and b >= silent_from:
            il, ir = [0] * BLOCK, [0] * BLOCK
        else:
            il, ir = rand_block(rs, amp)
        sc_in = True if sc_schedule is None else sc_schedule[b]
        ol, orr, _sc = bus.process_block(il, ir, sc_in)
        outs.append((ol, orr))
    return outs, bus.checkpoint()


def leg(name, ok, detail, metrics=None, status=None):
    return {"leg": name,
            "status": status or ("CONTROL-OK" if ok else "CONTROL-BROKEN"),
            "ok": bool(ok), "detail": detail, "metrics": metrics or {}}


# ---------------------------------------------------------------- NC helpers
def iverilog_available():
    return shutil.which(cmp_rtl.IV) is not None and \
        shutil.which(cmp_rtl.VVP) is not None


def rtl_mutant_leg(name, defect, case_name, detail):
    """Compile rf_bins12_mutants.sv with `defect` and require that it FAILS
    exact integer equality against the frozen model on `case_name`."""
    if not iverilog_available():
        return leg(name, False,
                   f"{detail} -- NOT RUN: iverilog/vvp unavailable in this "
                   f"environment (never counted as a demonstrated failure)",
                   status="NOT_RUN")
    os.makedirs(WORKDIR, exist_ok=True)
    vvp_path = os.path.join(WORKDIR, f"mutant_{defect.lower()}.vvp")
    cmp_rtl.compile_tb(vvp_path, core=MUTANT, defines=[defect])
    case = next(c for c in cmp_rtl.declared_cases() if c["name"] == case_name)
    rtl_blocks = cmp_rtl.run_case(vvp_path, case, WORKDIR)
    checked, fails = cmp_rtl.compare_case(case, rtl_blocks)
    cp_fails = sum(1 for f in fails if "checkpoint" in f)
    return leg(name, bool(fails), detail,
               {"case": case_name, "defect": defect,
                "samples_compared": checked["outputs"],
                "checkpoints_compared": checked["checkpoints"],
                "mismatches": len(fails),
                "checkpoint_mismatches": cp_fails,
                "first_failures": fails[:3]})


# ---------------------------------------------------------------- controls
def nc_generic_substitute():
    """NC-A: a 'generic' per-slot occupant (pass-through + fixed 0.5 gain, no
    TDF2 state at all -- the convenient substitute a shortcut implementation
    might reach for) must NOT reproduce the frozen model's per-instance state
    or output. Labeled ADAPTED and excluded from original-preset coverage."""
    class GenericPassthrough:
        """NEGATIVE CONTROL ONLY -- committed nowhere as a model. No TDF2
        state; a fixed 0.5 linear gain instead of the declared occupant."""
        def __init__(self, slot_bit):
            self.occupied = True
            self.slot_bit = slot_bit
            self.biquad = rm.BiquadInstance()   # stays all-zero on purpose

        def process_ringout(self, in_l, in_r, indata):
            if not indata:
                return list(in_l), list(in_r), False
            return ([v // 2 for v in in_l], [v // 2 for v in in_r], True)

    bus = rm.SceneBInsertBus()
    bus.apply_control(rm.FXB_ALL_FX, 0, True, True, COEFFS_A,
                      True, True, COEFFS_B)
    bus.slot2 = GenericPassthrough(rm.FXSLOT_BINS2)
    rs = random.Random(11)
    generic_outs = []
    for _b in range(4):
        il, ir = rand_block(rs)
        ol, orr, _sc = bus.process_block(il, ir, True)
        generic_outs.append((ol, orr))
    generic_cp = bus.checkpoint()

    faithful_outs, faithful_cp = run_bus(4, COEFFS_A, COEFFS_B, seed=11)
    out_differs = generic_outs != faithful_outs
    cp_differs = generic_cp != faithful_cp
    legs = [
        leg("output bit-exactness", out_differs,
            "the generic pass-through+gain substitute must not reproduce the "
            "declared occupant's output bit-exactly",
            {"blocks_compared": 4,
             "blocks_different": sum(1 for x, y in zip(generic_outs,
                                                       faithful_outs)
                                     if x != y)}),
        leg("per-instance state", cp_differs,
            "the substitute keeps no per-instance TDF2 history, so the "
            "dual-instance checkpoint must differ",
            {"substitute_slot2_state_all_zero":
                generic_cp[2] == (0, 0) and generic_cp[3] == (0, 0)}),
    ]
    ok = all(l["ok"] for l in legs)
    return {"control": "NC-A generic substitute (pass-through + fixed gain "
                       "occupant in bins2)",
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
    """NC-B: the declared tail span is TAIL_SPAN_BLOCKS blocks of SILENT input
    while the scene stays live; the occupant's registers keep producing real
    audio there. A render truncated at the end of the input must FAIL."""
    nfull = TAIL_SIGNAL_BLOCKS + TAIL_SPAN_BLOCKS
    full_outs, full_cp = run_bus(nfull, COEFFS_TAIL, COEFFS_B, seed=22,
                                 amp=0.05, silent_from=TAIL_SIGNAL_BLOCKS)
    trunc_outs, trunc_cp = run_bus(TAIL_SIGNAL_BLOCKS, COEFFS_TAIL, COEFFS_B,
                                   seed=22, amp=0.05,
                                   silent_from=TAIL_SIGNAL_BLOCKS)
    dropped = full_outs[TAIL_SIGNAL_BLOCKS:]
    dropped_energy = sum(abs(v) for ol, orr in dropped for v in ol + orr)
    dropped_nonzero_blocks = sum(1 for ol, orr in dropped
                                 if any(v != 0 for v in ol + orr))
    legs = [
        leg("declared tail span carries audio", dropped_energy > 0,
            "a truncation control proves nothing unless the dropped region "
            "actually contains nonzero tail samples",
            {"dropped_blocks": len(dropped),
             "dropped_blocks_with_nonzero_output": dropped_nonzero_blocks,
             "dropped_abs_energy": dropped_energy}),
        leg("tail-span coverage check", len(trunc_outs) < nfull,
            "the truncated render must fail the declared-tail-span coverage "
            "check",
            {"declared_blocks": nfull, "rendered_blocks": len(trunc_outs)}),
        leg("final per-instance checkpoint", trunc_cp != full_cp,
            "the truncated render's final per-instance state must not match "
            "the full render's",
            {"checkpoints_equal": trunc_cp == full_cp}),
    ]
    ok = all(l["ok"] for l in legs)
    return {"control": f"NC-B dropped tail (render truncated to "
                       f"{TAIL_SIGNAL_BLOCKS}/{nfull} declared blocks)",
            "targets": "declared tail-span coverage",
            "legs": legs,
            "verdict": ("CONTROL-OK (truncated render FAILS the declared-"
                        "tail-span coverage and checkpoint checks, and the "
                        "dropped region demonstrably contained real audio)"
                        if ok else
                        "CONTROL-BROKEN (truncation NOT detected!)"),
            "ok": ok}


def nc_wrong_order():
    """NC-C: bins1 -> bins2 vs the SAME two slot occupants permuted."""
    # leg 1: saturating pair -- gross divergence
    ab_sat, ab_cp = run_bus(6, COEFFS_HOT, COEFFS_QUIET, seed=33, amp=400.0)
    ba_sat, ba_cp = run_bus(6, COEFFS_QUIET, COEFFS_HOT, seed=33, amp=400.0)
    sat_diffs = [abs(x - y)
                 for (al, ar), (bl, br) in zip(ab_sat, ba_sat)
                 for x, y in zip(al + ar, bl + br)]
    # leg 2: purely linear pair -- rounding-only divergence (documented)
    ab_lin, _ = run_bus(8, COEFFS_A, COEFFS_B, seed=34)
    ba_lin, _ = run_bus(8, COEFFS_B, COEFFS_A, seed=34)
    lin_diffs = [abs(x - y)
                 for (al, ar), (bl, br) in zip(ab_lin, ba_lin)
                 for x, y in zip(al + ar, bl + br)]
    legs = [
        leg("model permutation (saturating pair)",
            any(d > 0 for d in sat_diffs),
            "permuting the two slot occupants must change the bus output "
            "when the chain saturates in between",
            {"samples_compared": len(sat_diffs),
             "samples_different": sum(1 for d in sat_diffs if d),
             "max_abs_diff": max(sat_diffs),
             "checkpoints_differ": ab_cp != ba_cp}),
        leg("model permutation (purely linear pair)",
            any(d > 0 for d in lin_diffs),
            "two LTI biquads in series COMMUTE in exact arithmetic, so a "
            "linear-pair permutation is detectable only through fixed-point "
            "rounding -- integer-exact equality still flags it, and the "
            "bound is recorded rather than hidden",
            {"samples_compared": len(lin_diffs),
             "samples_different": sum(1 for d in lin_diffs if d),
             "max_abs_diff": max(lin_diffs)}),
        rtl_mutant_leg("live RTL order mutant", "NC_SWAP_ORDER",
                       "both-slots-all-fx",
                       "rf_bins12_mutants.sv -DNC_SWAP_ORDER evaluates bins2 "
                       "before bins1; it must FAIL exact equality against the "
                       "frozen model"),
    ]
    ok = all(l["ok"] for l in legs if l["status"] != "NOT_RUN") and \
        legs[0]["ok"] and legs[1]["ok"]
    return {"control": "NC-C wrong order (bins1/bins2 slot-content "
                       "permutation)",
            "targets": "order-sensitive equality of the series insert chain",
            "legs": legs,
            "verdict": ("CONTROL-OK (the order-sensitive check flags the "
                        "permutation; the linear-commutation bound is "
                        "recorded)" if ok else
                        "CONTROL-BROKEN (permutation undetected!)"),
            "ok": ok}


def nc_shared_state():
    """NC-D: a mutant that pools bins1's and bins2's TDF2 registers into ONE
    instance (tb_fx_shared_line.sv pattern) must FAIL the dual-instance
    independence check against the correctly-isolated bus."""
    class SharedSlot:
        """NEGATIVE CONTROL ONLY -- pools BOTH slots' state into one
        BiquadInstance, switching its coefficients per call (the
        shared-arithmetic-but-NOT-independent-state bug this leaf's
        acceptance forbids)."""
        def __init__(self, shared_biquad, slot_bit):
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

    shared_bq = rm.BiquadInstance()

    class MutantBus(rm.SceneBInsertBus):
        def __init__(self):
            super().__init__()
            self.slot1 = SharedSlot(shared_bq, rm.FXSLOT_BINS1)
            self.slot2 = SharedSlot(shared_bq, rm.FXSLOT_BINS2)

        def process_block(self, in_l, in_r, sc_in):
            shared_bq.set_coeffs(*COEFFS_A)
            bus_l, bus_r = list(in_l), list(in_r)
            sc = sc_in
            bus_l, bus_r, sc = self.slot1.process_ringout(bus_l, bus_r, sc)
            shared_bq.set_coeffs(*COEFFS_B)
            bus_l, bus_r, sc = self.slot2.process_ringout(bus_l, bus_r, sc)
            return bus_l, bus_r, sc

    mbus = MutantBus()
    rs = random.Random(44)
    mutant_outs = []
    for _b in range(6):
        il, ir = rand_block(rs)
        ol, orr, _sc = mbus.process_block(il, ir, True)
        mutant_outs.append((ol, orr))
    mutant_cp = mbus.checkpoint()

    isolated_outs, isolated_cp = run_bus(6, COEFFS_A, COEFFS_B, seed=44)
    legs = [
        leg("model pooled-history mutant", mutant_outs != isolated_outs,
            "pooling both instances' histories must diverge from the "
            "correctly-isolated bus on the SAME per-block inputs",
            {"blocks_compared": 6,
             "blocks_different": sum(1 for x, y in zip(mutant_outs,
                                                       isolated_outs)
                                     if x != y)}),
        leg("model dual-instance checkpoint", mutant_cp != isolated_cp,
            "the pooled mutant cannot reproduce two independent checkpoint "
            "halves",
            {"pooled_slot1_equals_slot2":
                mutant_cp[0] == mutant_cp[2] and mutant_cp[1] == mutant_cp[3],
             "isolated_slot1_equals_slot2":
                isolated_cp[0] == isolated_cp[2] and
                isolated_cp[1] == isolated_cp[3]}),
        rtl_mutant_leg("live RTL shared-state mutant", "NC_SHARED_STATE",
                       "both-slots-all-fx",
                       "rf_bins12_mutants.sv -DNC_SHARED_STATE pools both "
                       "slots onto one register set; it must FAIL exact "
                       "equality (output AND per-instance checkpoint) against "
                       "the frozen model"),
    ]
    ok = all(l["ok"] for l in legs if l["status"] != "NOT_RUN") and \
        legs[0]["ok"] and legs[1]["ok"]
    return {"control": "NC-D shared state (both insert slots pooled into one "
                       "history)",
            "targets": "dual-instance (per-instance state) independence",
            "legs": legs,
            "verdict": ("CONTROL-OK (pooled-state mutants FAIL the "
                        "dual-instance-independence check, model-side and in "
                        "live RTL)" if ok else
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
         os.path.join(REPO, "tools", "compare_rtl_model_rf_bins12.py"),
         "--assert-model-revision", stale, "--no-write"],
        capture_output=True, text=True)
    refused = proc.returncode != 0 and '"status": "REFUSED"' in proc.stdout
    legs = [
        leg("revision pin function", in_process,
            "revision_pin_ok() must reject a stale pin and accept the live one",
            {"live_revision_tail": live[-16:], "stale_revision_tail": stale[-16:]}),
        leg("live comparator refusal", refused,
            "the comparator invoked with a stale pin must exit nonzero with "
            "status REFUSED instead of reporting PASS",
            {"exit_code": proc.returncode,
             "status_line_present": '"status": "REFUSED"' in proc.stdout}),
    ]
    ok = all(l["ok"] for l in legs)
    return {"control": "NC-E stale stub (frozen-revision pin)",
            "targets": "stale-harness refusal (never a false PASS)",
            "legs": legs,
            "verdict": ("CONTROL-OK (a stale pin is REFUSED -- the comparator "
                        "cannot report PASS)" if ok else
                        "CONTROL-BROKEN (stale revision accepted!)"),
            "ok": ok}


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
    not_run = [f"{r['control']} / {l['leg']}" for r in results
               for l in r["legs"] if l["status"] == "NOT_RUN"]
    out_doc = {"schema_version": 1, "leaf": "SXT-028h",
               "claim": "negative controls; each must fail the check it "
                        "targets",
               "model_revision": rm.model_revision(),
               "iverilog_available": iverilog_available(),
               "legs_not_run": not_run,
               "controls": results,
               "status": "PASS" if ok else "FAIL (broken control!)"}
    with open(os.path.join(OUT, "negative-controls.json"), "w") as f:
        json.dump(out_doc, f, indent=2, sort_keys=True)
        f.write("\n")
    lines = []
    for r in results:
        lines.append(f"{r['control']}: {r['verdict']}")
        for l in r["legs"]:
            lines.append(f"    - {l['leg']}: {l['status']}")
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
