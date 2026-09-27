#!/usr/bin/env python3
"""SXT-028k: RTL-vs-frozen-model EXACTNESS comparator for the Airwindows
"Logical" (streamed id 4) leaf.

Claim scope
-----------
This tool establishes ONE claim: the SystemVerilog core in
`rtl/effects/aw-4/` reproduces the frozen fixed-point model in
`model/effects/aw-4/logical4_model.py` EXACTLY — integer equality of every
output word and every per-block, per-instance state checkpoint, for both
instances, across the declared cases.

It says NOTHING about agreement with the pinned Surge engine (a separate
claim, NOT_RUN here) and NOTHING about musical quality.

Stale-stub control
------------------
The frozen model's revision word is written into `cfg.hex` word 0 and echoed
by the harness on the trace's `R` line. If the echoed word does not match the
model this process just ran, the comparator REFUSES (exit 2) instead of
reporting PASS. `--stale-pin` deliberately writes a wrong word so the refusal
itself is exercised as a live control.

Usage
-----
    python3 tools/compare_rtl_model_aw4.py                 # all cases
    python3 tools/compare_rtl_model_aw4.py --case sel2-hot
    python3 tools/compare_rtl_model_aw4.py --mutant NC_FIX_Q2 --case sel2-hot
    python3 tools/compare_rtl_model_aw4.py --stale-pin --case sel0-dad

Original to this repository (Apache-2.0).
"""

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-4"))

import logical4_model as M  # noqa: E402

RTL_DIR = os.path.join(REPO, "rtl", "effects", "aw-4")
OUT_DIR = os.path.join(REPO, "out", "aw-4")
REPORT = os.path.join(REPO, "reports", "SXT-028k")

PLANE_WORDS = 31
MASK96 = (1 << 96) - 1

# ---- carrier parameter sets (census-derived; see model/effects/fx_inputs/)
PARAMS = {
    "acoustic-snare": dict(A_threshold=0.245, B_ratio=0.654286,
                           C_attack=0.288449, D_makeup=0.720713, E_mix=1.0),
    "dad": dict(A_threshold=0.596429, B_ratio=0.345714, C_attack=0.13202,
                D_makeup=0.5, E_mix=1.0),
    "3x101": dict(A_threshold=0.65, B_ratio=0.447286, C_attack=0.301511,
                  D_makeup=0.5, E_mix=1.0),
    "bass-guitar-5": dict(A_threshold=0.473214, B_ratio=1.0, C_attack=0.0,
                          D_makeup=0.250893, E_mix=1.0),
    "moogy-reese-ains2": dict(A_threshold=0.173001, B_ratio=0.703544,
                              C_attack=0.866333, D_makeup=0.71891, E_mix=1.0),
    "moogy-reese-global1": dict(A_threshold=0.5, B_ratio=0.504564,
                                C_attack=0.098164, D_makeup=0.5, E_mix=1.0),
    # loader defaults (Logical4.cpp constructor) and a partial-mix corner
    "defaults": dict(A_threshold=0.5, B_ratio=0.2, C_attack=0.19202020202020202,
                     D_makeup=0.5, E_mix=1.0),
    "halfmix": dict(A_threshold=0.245, B_ratio=0.654286, C_attack=0.288449,
                    D_makeup=0.720713, E_mix=0.5),
    # synthetic parameter corners (extremes of each named param; NOT presets)
    "extreme-lo": dict(A_threshold=0.0, B_ratio=0.0, C_attack=0.0,
                       D_makeup=0.0, E_mix=0.0),
    "extreme-hi": dict(A_threshold=1.0, B_ratio=1.0, C_attack=1.0,
                       D_makeup=1.0, E_mix=1.0),
    # inputgain = 10 (A = 0) so the +-36 hard clip is reachable
    "clip-corner": dict(A_threshold=0.0, B_ratio=0.654286, C_attack=0.288449,
                        D_makeup=0.5, E_mix=1.0),
}


# --------------------------------------------------------------------------
# Stimulus
# --------------------------------------------------------------------------

def _tone(n, seed, amp, silence_from=None, dc=0.0):
    rs = random.Random(seed)
    out_l, out_r = [], []
    for i in range(n):
        if silence_from is not None and i >= silence_from:
            out_l.append(0)
            out_r.append(0)
            continue
        t = i / float(M.SAMPLE_RATE)
        vl = amp * math.sin(2 * math.pi * 220.0 * t) + 0.2 * amp * rs.uniform(-1, 1) + dc
        vr = amp * math.sin(2 * math.pi * 331.0 * t + 0.7) + 0.2 * amp * rs.uniform(-1, 1) + dc
        out_l.append(M.q(vl, M.F_A))
        out_r.append(M.q(vr, M.F_A))
    return out_l, out_r


def _blocks(sig_l, sig_r):
    n = len(sig_l) // M.BLOCK
    return [(sig_l[b * M.BLOCK:(b + 1) * M.BLOCK],
             sig_r[b * M.BLOCK:(b + 1) * M.BLOCK]) for b in range(n)]


class Case:
    def __init__(self, name, p0, p1, blocks, insts, resets, why):
        self.name = name
        self.p0 = p0
        self.p1 = p1
        self.blocks = blocks
        self.insts = insts          # instance index per block
        self.resets = resets        # bool per block: reset BOTH before block
        self.why = why


def build_cases():
    cases = []

    def simple(name, param, nblk, amp, why, seed=7, silence_from=None, dc=0.0):
        n = nblk * M.BLOCK
        l, r = _tone(n, seed, amp, silence_from, dc)
        bl = _blocks(l, r)
        return Case(name, param, param, bl, [0] * len(bl),
                    [b == 0 for b in range(len(bl))], why)

    cases.append(simple("sel0-dad", "dad", 24, 0.5,
                        "ratioselector 0: one active stage, the commonest "
                        "carrier shape (global1 Ambiance/Dad.fxp)"))
    cases.append(simple("sel1-snare", "acoustic-snare", 24, 0.5,
                        "ratioselector 1: two active stages, the crossfade "
                        "straddles A and B (Cybersoda Acoustic Snare.fxp)"))
    cases.append(simple("sel1-edge-3x101", "3x101", 20, 0.4,
                        "ratio fraction 0.000243 -- immediately above the "
                        "selector boundary (Exquis MPE 3x101.fxp)"))
    cases.append(simple("sel2-bass", "bass-guitar-5", 24, 0.5,
                        "ratioselector 2: all three stages active, exercises "
                        "the stage-C quirk Q2 path (Slowboat Bass Guitar 5)"))
    cases.append(simple("sel2-hot", "bass-guitar-5", 24, 3.0,
                        "hot input, all three stages: drives the +-36 hard "
                        "clip and the sag clamp", seed=11))
    cases.append(simple("wrap-1024", "acoustic-snare", 36, 0.5,
                        "1152 samples: crosses the 500-sample gcount period "
                        "twice, so the quirk-Q1 3-sample taps are live",
                        seed=13))
    cases.append(simple("tail-silence", "acoustic-snare", 40, 0.6,
                        "burst then silence for the declared tail span: the "
                        "gain-recovery tail is the tail this effect has",
                        seed=17, silence_from=8 * M.BLOCK))
    cases.append(simple("dc-asym", "acoustic-snare", 24, 0.2,
                        "sustained positive DC offset: drives one polarity's "
                        "target toward its 1e-6 floor, the c96 range case",
                        seed=19, dc=1.5))
    cases.append(simple("defaults", "defaults", 16, 0.5,
                        "the Logical4 constructor defaults", seed=23))
    cases.append(simple("halfmix", "halfmix", 16, 0.5,
                        "E_mix = 0.5: the wet/dry branch is live", seed=29))
    cases.append(simple("extreme-lo", "extreme-lo", 16, 0.5,
                        "every named parameter at 0.0 (inputgain 10, "
                        "outputgain 0.1, ratio 0, mix 0 -- dry-only path)",
                        seed=41))
    cases.append(simple("extreme-hi", "extreme-hi", 16, 0.5,
                        "every named parameter at 1.0 (inputgain 0.1, "
                        "outputgain 10, ratio clamped to 2.99999)", seed=43))
    cases.append(simple("clip-corner", "clip-corner", 16, 11.0,
                        "hot input into inputgain 10: the +-36 hard clip is "
                        "engaged (asserted non-zero, so the clip is a live "
                        "path and not dead code)", seed=47))
    cases.append(simple("sagclamp-corner", "defaults", 16, 30.0,
                        "|x| ~ 30 drives the sag accumulator past 1.0, so "
                        "the `clamp` branch (control > 1) is engaged",
                        seed=53))

    # ---- tail RESUME case: burst, silence for the declared span, burst again
    # The dropped-tail defect is invisible in the silent region itself (a
    # compressor emits silence into silence); it shows up in the SECOND
    # burst, which a dropped tail processes with a freshly-reset gain state.
    ctrl_tail = M.build_control(PARAMS["acoustic-snare"])
    span = M.tail_window_blocks(ctrl_tail)
    burst = 8
    nb = burst + span + 8
    l, r = _tone(nb * M.BLOCK, 59, 0.6)
    for i in range(burst * M.BLOCK, (burst + span) * M.BLOCK):
        l[i] = 0
        r[i] = 0
    bl = _blocks(l, r)
    cases.append(Case("tail-resume", "acoustic-snare", "acoustic-snare", bl,
                      [0] * len(bl), [b == 0 for b in range(len(bl))],
                      "burst, then the DECLARED tail span of silence, then a "
                      "second burst: the gain-recovery tail is only "
                      "observable in the second burst, so this is the case "
                      "the dropped-tail control has to fail"))

    # ---- dual-instance case: two DIFFERENT coefficient planes, interleaved
    n = 24 * M.BLOCK
    l, r = _tone(n, 31, 0.5)
    bl = _blocks(l, r)
    insts = [b % 2 for b in range(len(bl))]
    cases.append(Case(
        "dual-moogy", "moogy-reese-ains2", "moogy-reese-global1", bl, insts,
        [b == 0 for b in range(len(bl))],
        "the two Logical slots Moogy Reese.fxp actually carries (ains2 and "
        "global1) as two concurrent instances with different planes, "
        "interleaved block by block; every checkpoint dumps both"))

    # ---- mid-stream panic reset
    n = 16 * M.BLOCK
    l, r = _tone(n, 37, 0.5)
    bl = _blocks(l, r)
    resets = [b == 0 or b == 8 for b in range(len(bl))]
    cases.append(Case("reset-mid", "acoustic-snare", "acoustic-snare", bl,
                      [0] * len(bl), resets,
                      "panic/reset mid-tail: the constructor state must be "
                      "restored exactly on both sides"))
    return cases


# --------------------------------------------------------------------------
# Model side
# --------------------------------------------------------------------------

def run_model(case):
    c0 = M.build_control(PARAMS[case.p0])
    c1 = M.build_control(PARAMS[case.p1])
    inst = [M.Logical4Fixed(c0, label="inst0"),
            M.Logical4Fixed(c1, label="inst1")]
    outs, cps = [], []
    for b, (il, ir) in enumerate(case.blocks):
        if case.resets[b]:
            inst[0].reset()
            inst[1].reset()
        sel = case.insts[b]
        ol, orr = inst[sel].process_block(il, ir)
        outs.append((ol, orr))
        cps.append((inst[0].st.checkpoint(), inst[1].st.checkpoint()))
    return c0, c1, inst, outs, cps


def flat_checkpoint(cp):
    """Flatten one instance checkpoint into the field order the harness
    dumps (see tb_logical4.sv::dump_inst)."""
    v = [cp["gcount"], cp["fp_flip"]]
    for s in range(M.N_STAGES):
        for c in range(M.N_CH):
            v += [cp["c_apos"][s][c], cp["c_aneg"][s][c],
                  cp["c_bpos"][s][c], cp["c_bneg"][s][c]]
    for s in range(M.N_STAGES):
        for c in range(M.N_CH):
            v += [cp["t_pos"][s][c], cp["t_neg"][s][c]]
    for s in range(M.N_STAGES):
        for c in range(M.N_CH):
            v += [cp["avg"][s][c], cp["nvg"][s][c]]
    for s in range(M.N_STAGES):
        for c in range(M.N_CH):
            v.append(cp["sag_ctrl"][s][c])
    for s in range(M.N_STAGES):
        for c in range(M.N_CH):
            v += list(cp["sag_line"][s][c])
    return v


# --------------------------------------------------------------------------
# Stimulus files
# --------------------------------------------------------------------------

def plane_words(ctrl):
    w = [0] * PLANE_WORDS
    flags = ((1 if ctrl["inputgain_is_one"] else 0)
             | ((1 if ctrl["outputgain_is_one"] else 0) << 1)
             | ((1 if ctrl["wet_is_one"] else 0) << 2))
    w[0] = ctrl["ratioselector"]
    w[1] = flags
    w[2] = ctrl["inputgain_k"]
    w[3] = ctrl["inv_compoutgain_k"]
    w[4] = ctrl["outputgain_k"]
    w[5] = ctrl["ratio_k"]
    w[6] = ctrl["inv_ratio_k"]
    w[7] = ctrl["wet_k"]
    w[8] = ctrl["dry_k"]
    w[9], w[10], w[11] = ctrl["remainder_t"]
    w[12], w[13], w[14] = ctrl["divisor_t"]
    w[15] = M.INTENSITY_C
    w[16] = M.POWER_SAG_K
    w[17] = M.FP_OLD_K
    w[18] = M.FP_NEW_K
    w[19] = M.POS_FLOOR_T
    w[20] = M.LEAK_S
    w[21] = M.HALF_S
    w[22] = M.ONE_S
    w[23] = M.ONE_C
    w[24] = M.ONE_T
    w[25] = M.BRMAX_A
    w[26] = M.CLIP_A
    w[27] = ctrl["sag_offset"]
    w[28] = M.A48_MAX
    w[29] = M.RECIP_NUM
    w[30] = 0
    return w


def h96(v):
    return "%024x" % (int(v) & MASK96)


def write_cfg(path, c0, c1, revword):
    words = [revword] + plane_words(c0) + plane_words(c1)
    with open(path, "w") as f:
        for v in words:
            f.write(h96(v) + "\n")


def write_blocks(path, case):
    words = [len(case.blocks)]
    for b, (il, ir) in enumerate(case.blocks):
        hdr = (b & 0xFFFF)
        if case.resets[b]:
            hdr |= (1 << 95)
        if case.insts[b]:
            hdr |= (1 << 94)
        words.append(hdr)
        words += il
        words += ir
    with open(path, "w") as f:
        for v in words:
            f.write(h96(v) + "\n")


# --------------------------------------------------------------------------
# RTL side
# --------------------------------------------------------------------------

def compile_rtl(workdir, mutant=None):
    exe = os.path.join(workdir, "sim.vvp")
    src = ["tb_logical4.sv",
           "logical4_mutants.sv" if mutant else "logical4_core.sv"]
    cmd = ["iverilog", "-g2012", "-o", exe, "-I", RTL_DIR]
    if mutant:
        cmd.append("-D" + mutant)
    cmd += [os.path.join(RTL_DIR, s) for s in src]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("iverilog failed:\n" + r.stdout + r.stderr)
    return exe


def run_rtl(exe, workdir, cfg, blocks, trace):
    cmd = ["vvp", exe,
           "+CFG=" + cfg, "+BLOCKS=" + blocks, "+TRACE=" + trace,
           "+SINROM=" + os.path.join(RTL_DIR, "sin_q31.hex"),
           "+OMCROM=" + os.path.join(RTL_DIR, "omc_q31.hex")]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
    return r


def parse_trace(path):
    rev = None
    tlines, olines = {}, {}
    counters = None
    with open(path) as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "R":
                rev = int(p[1])
            elif p[0] == "T":
                tlines[int(p[1])] = (int(p[2]), [int(v) for v in p[3:]])
            elif p[0] == "O":
                olines[int(p[1])] = [int(v) for v in p[2:]]
            elif p[0] == "C":
                counters = {"divisions": int(p[1]), "clips": int(p[2]),
                            "tap_age3": int(p[3])}
    return rev, tlines, olines, counters


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

def compare_case(case, mutant=None, stale_pin=False, keep=False):
    workdir = os.path.join(OUT_DIR, case.name + ("-" + mutant if mutant else "")
                           + ("-stale" if stale_pin else ""))
    os.makedirs(workdir, exist_ok=True)
    c0, c1, inst, outs, cps = run_model(case)

    revword = M.revision_word()
    pinned = revword ^ 0xDEADBEEF if stale_pin else revword

    cfg = os.path.join(workdir, "cfg.hex")
    blk = os.path.join(workdir, "blocks.hex")
    trc = os.path.join(workdir, "tb_trace.txt")
    write_cfg(cfg, c0, c1, pinned)
    write_blocks(blk, case)

    exe = compile_rtl(workdir, mutant)
    r = run_rtl(exe, workdir, cfg, blk, trc)
    if not os.path.exists(trc):
        return {"case": case.name, "exact": False, "error": "no trace",
                "stdout": r.stdout[-2000:], "stderr": r.stderr[-2000:]}

    rev, tl, ol, counters = parse_trace(trc)

    result = {
        "case": case.name,
        "why": case.why,
        "mutant": mutant,
        "planes": {"instance0": case.p0, "instance1": case.p1},
        "ratioselector": {"instance0": c0["ratioselector"],
                          "instance1": c1["ratioselector"]},
        "blocks": len(case.blocks),
        "revision_pin": {"expected": revword, "echoed": rev,
                         "ok": rev == revword},
        "rtl_counters": counters,
    }

    if rev != revword:
        result["exact"] = False
        result["status"] = "REFUSED-STALE"
        result["note"] = ("harness echoed frozen-model revision word %r but "
                          "the model in this tree is %r; a stale harness "
                          "must not report PASS" % (rev, revword))
        return result

    mism_o = mism_f = 0
    checked_o = checked_f = 0
    first = None
    nonzero_blocks = 0
    for b in range(len(case.blocks)):
        exp = outs[b][0] + outs[b][1]
        got = ol.get(b, [])
        checked_o += len(exp)
        if any(v != 0 for v in exp):
            nonzero_blocks += 1
        if got != exp:
            for i, (e, g) in enumerate(zip(exp, got)):
                if e != g:
                    mism_o += 1
                    if first is None:
                        first = {"kind": "output", "block": b, "index": i,
                                 "model": e, "rtl": g}
            if len(got) != len(exp):
                mism_o += abs(len(got) - len(exp))
        expf = flat_checkpoint(cps[b][0]) + flat_checkpoint(cps[b][1])
        gotf = tl.get(b, (None, []))[1]
        checked_f += len(expf)
        for i, (e, g) in enumerate(zip(expf, gotf)):
            if e != g:
                mism_f += 1
                if first is None:
                    first = {"kind": "checkpoint", "block": b, "field": i,
                             "model": e, "rtl": g}
        if len(gotf) != len(expf):
            mism_f += abs(len(gotf) - len(expf))

    result.update({
        "checked": {"outputs": checked_o, "checkpoint_fields": checked_f},
        "mismatches": {"outputs": mism_o, "checkpoint_fields": mism_f},
        "first_mismatch": first,
        "nonzero_output_blocks": nonzero_blocks,
        "exact": (mism_o == 0 and mism_f == 0),
        "model_side": {
            "clip_hits": [inst[0].st.clip_hits, inst[1].st.clip_hits],
            "sag_clamp_hits": [inst[0].st.sag_clamp_hits,
                               inst[1].st.sag_clamp_hits],
            "tap_age3_hits": [inst[0].st.tap_age3_hits,
                              inst[1].st.tap_age3_hits],
            "saturations": [inst[0].st.saturations, inst[1].st.saturations],
            "recip_saturations": [inst[0].st.recip_saturations,
                                  inst[1].st.recip_saturations],
        },
    })
    if not keep:
        shutil.rmtree(workdir, ignore_errors=True)
    return result


MUTANT_EXPECT = {
    "NC_SHARED_STATE": ("dual-moogy",
                        "shared instead of per-instance state"),
    "NC_SWAP_STAGES": ("sel2-bass", "wrong stage order (same-class "
                       "permutation)"),
    "NC_TAIL_KILL": ("tail-resume", "dropped tail"),
    "NC_FIX_Q1": ("wrap-1024", "pinned quirk Q1 'fixed' away"),
    "NC_FIX_Q2": ("sel2-bass", "pinned quirk Q2 'fixed' away"),
}

MUTANT_BLINDSPOT = {
    "NC_SWAP_STAGES": ("sel0-dad", "one active stage: a permutation of a "
                       "single-element cascade is a no-op, so this case "
                       "CANNOT detect the defect"),
    "NC_TAIL_KILL": ("sel1-snare", "no silent block: the silence branch is "
                     "never taken, so this case CANNOT detect the defect"),
    "NC_FIX_Q2": ("sel0-dad", "stage C inactive: the quirk path never runs"),
    "NC_FIX_Q1": ("defaults", "512 samples only just crosses one wrap; kept "
                  "as the short-run reference for the >= 1000-sample case"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append")
    ap.add_argument("--mutant")
    ap.add_argument("--stale-pin", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--write-report", action="store_true")
    args = ap.parse_args()

    if shutil.which("iverilog") is None:
        print("NOT_RUN: iverilog is not installed; the RTL-vs-model "
              "exactness leg did not run (this is not a pass).")
        return 3

    cases = build_cases()
    if args.case:
        cases = [c for c in cases if c.name in args.case]
        if not cases:
            print("no such case", file=sys.stderr)
            return 2

    os.makedirs(OUT_DIR, exist_ok=True)

    if args.mutant or args.stale_pin:
        out = [compare_case(c, args.mutant, args.stale_pin, args.keep)
               for c in cases]
        print(json.dumps(out, indent=2))
        return 0

    results = [compare_case(c, keep=args.keep) for c in cases]
    mutants = []
    for mut, (case_name, desc) in sorted(MUTANT_EXPECT.items()):
        case = [c for c in build_cases() if c.name == case_name][0]
        res = compare_case(case, mutant=mut, keep=args.keep)
        entry = {"control": mut, "defect": desc, "case": case_name,
                 "exact": res.get("exact"),
                 "mismatches": res.get("mismatches"),
                 "ok": res.get("exact") is False,
                 "verdict": ("CONTROL-OK: the injected defect FAILS the "
                             "exactness check it targets"
                             if res.get("exact") is False else
                             "BROKEN CONTROL: the defect passed")}
        if mut in MUTANT_BLINDSPOT:
            bs_case, bs_why = MUTANT_BLINDSPOT[mut]
            bcase = [c for c in build_cases() if c.name == bs_case][0]
            bres = compare_case(bcase, mutant=mut, keep=args.keep)
            entry["declared_blind_spot"] = {
                "case": bs_case, "why": bs_why,
                "detected_here": bres.get("exact") is False,
            }
        mutants.append(entry)

    # the stale-pin refusal, exercised for real
    stale = compare_case(cases[0], stale_pin=True, keep=args.keep)
    stale_ok = stale.get("status") == "REFUSED-STALE"

    all_exact = all(r.get("exact") for r in results)
    all_ctrl = all(m["ok"] for m in mutants)
    record = {
        "leaf": "SXT-028k",
        "issue": 63,
        "claim": "RTL matches the frozen fixed-point model EXACTLY "
                 "(integer equality). NOT a reference-fidelity claim, NOT a "
                 "musical-quality claim, NOT a synthesis or timing claim.",
        "model_revision": M.model_revision(),
        "tables_digest": __import__("tables").tables_digest(),
        "simulator": subprocess.run(["iverilog", "-V"], capture_output=True,
                                    text=True).stdout.splitlines()[0],
        "status": "PASS" if (all_exact and all_ctrl and stale_ok) else "FAIL",
        "cases": results,
        "mutant_controls": mutants,
        "stale_pin_control": {
            "ok": stale_ok,
            "status": stale.get("status"),
            "verdict": ("CONTROL-OK: a harness pinned to the wrong "
                        "frozen-model revision is REFUSED, not passed"
                        if stale_ok else "BROKEN CONTROL"),
        },
    }
    if args.write_report:
        os.makedirs(REPORT, exist_ok=True)
        with open(os.path.join(REPORT, "rtl-exactness.json"), "w") as f:
            json.dump(record, f, indent=2, sort_keys=True)
            f.write("\n")
    if args.json:
        with open(args.json, "w") as f:
            json.dump(record, f, indent=2, sort_keys=True)
    print(json.dumps({k: v for k, v in record.items()
                      if k not in ("cases", "mutant_controls")}, indent=2))
    for r in record["cases"]:
        print("  %-18s exact=%s outputs=%s fields=%s" %
              (r["case"], r.get("exact"), r.get("checked", {}).get("outputs"),
               r.get("checked", {}).get("checkpoint_fields")))
    for m in record["mutant_controls"]:
        print("  %-18s %s" % (m["control"], m["verdict"]))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
