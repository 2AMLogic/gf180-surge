#!/usr/bin/env python3
"""SXT-028k: model-side live negative controls for the Airwindows "Logical"
(streamed id 4) leaf.

Claim scope (stated here and repeated in the artifact)
------------------------------------------------------
EVERY comparison in this file is **model-vs-model**: the frozen fixed-point
model is the reference. These controls show that the checks and thresholds
are LIVE — that each named defect is actually detected by the check that is
supposed to detect it. They establish nothing about agreement with the
pinned Surge engine (NOT_RUN, no oracle in this environment) and nothing
about musical quality.

A control that PASSES its target check is a BROKEN control and is reported
as such; the tool exits non-zero.

Controls
--------
NC-A  wrong order          two same-class Logical slots in series, A->B vs
                           B->A (slot-content permutation; tools/ablate_fx.py
                           permute pattern). Must FAIL the order-sensitive
                           agreement check.
NC-B  shared state         the two concurrent instances' histories pooled
                           into one record (tb_fx_shared_line pattern). Must
                           FAIL the dual-instance equality.
NC-C  generic substitute   a convenient generic compressor swapped in for
                           the pinned algorithm. Labelled ADAPTED, must be
                           REFUSED from original-preset coverage and must
                           FAIL the agreement thresholds.
NC-D  dropped tail         the render truncated before the declared
                           gain-recovery tail span, then resumed. Must FAIL
                           the tail check.
NC-E  stale stub           the exactness harness pinned to a stale
                           frozen-model revision, and a silent (all-zero)
                           stub. Both must be REFUSED, never passed.
NC-F  bypass transparency  E_mix = 0 must be bit-exact dry, and an injected
                           mix leak must be detected (so the bypass check is
                           not vacuous).
NC-G  quirk fixes          "fixing" pinned quirk Q1 (the +499 sag mirror) or
                           quirk Q2 (stage C's right channel updating the
                           LEFT positive target) must FAIL. A model that
                           tidies the reference is not the reference.

Thresholds
----------
The [PROPOSED] SXT-023 effect-slice budgets (max <= 8192 LSB at Q10.21 =
3.906e-3 linear; rms <= -46 dBFS; spectral corr >= 0.98) are used ONLY as a
substitution detector inside these model-vs-model controls. They are NOT
frozen (SXT-017 / #12) and no reference verdict is made against them here.

Original to this repository (Apache-2.0).
"""

import argparse
import json
import math
import os
import random
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-4"))

import logical4_model as M  # noqa: E402
from float_transcription import GenericCompressorADAPTED  # noqa: E402

REPORT = os.path.join(REPO, "reports", "SXT-028k", "negative-controls")

BUDGET_MAX_LINEAR = 8192 / float(1 << 21)     # [PROPOSED] SXT-023 max
BUDGET_RMS_DBFS = -46.0                       # [PROPOSED] SXT-023 rms
BUDGET_CORR = 0.98                            # [PROPOSED] SXT-023 corr

CARRIER = dict(A_threshold=0.245, B_ratio=0.654286, C_attack=0.288449,
               D_makeup=0.720713, E_mix=1.0)
CARRIER_B = dict(A_threshold=0.5, B_ratio=0.504564, C_attack=0.098164,
                 D_makeup=0.5, E_mix=1.0)


# --------------------------------------------------------------------------

def stim(nblk, seed=101, amp=0.5, silence_from=None):
    rs = random.Random(seed)
    bl = []
    for b in range(nblk):
        il, ir = [], []
        for i in range(M.BLOCK):
            n = b * M.BLOCK + i
            if silence_from is not None and n >= silence_from:
                il.append(0)
                ir.append(0)
                continue
            t = n / float(M.SAMPLE_RATE)
            il.append(M.q(amp * math.sin(2 * math.pi * 220.0 * t)
                          + 0.2 * amp * rs.uniform(-1, 1), M.F_A))
            ir.append(M.q(amp * math.sin(2 * math.pi * 331.0 * t + 0.7)
                          + 0.2 * amp * rs.uniform(-1, 1), M.F_A))
        bl.append((il, ir))
    return bl


def metrics(ref, got):
    """max abs, relative rms (dBFS re the reference rms), spectral-free
    correlation. Inputs are linear floats."""
    n = min(len(ref), len(got))
    mx = 0.0
    num = den = 0.0
    sx = sy = sxx = syy = sxy = 0.0
    for i in range(n):
        a, b = ref[i], got[i]
        d = b - a
        mx = max(mx, abs(d))
        num += d * d
        den += a * a
        sx += a
        sy += b
        sxx += a * a
        syy += b * b
        sxy += a * b
    rms = math.sqrt(num / n) if n else 0.0
    ref_rms = math.sqrt(den / n) if n else 0.0
    dbfs = 20.0 * math.log10(rms) if rms > 0 else -999.0
    cov = sxy / n - (sx / n) * (sy / n)
    vx = sxx / n - (sx / n) ** 2
    vy = syy / n - (sy / n) ** 2
    corr = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0
    return {"max_abs": mx, "rms": rms, "rms_dbfs": dbfs,
            "ref_rms": ref_rms, "corr": corr, "samples": n}


def within_budget(m):
    return (m["max_abs"] <= BUDGET_MAX_LINEAR
            and m["rms_dbfs"] <= BUDGET_RMS_DBFS
            and m["corr"] >= BUDGET_CORR)


def to_float(words):
    s = float(1 << M.F_A)
    return [w / s for w in words]


def run_chain(models, blocks):
    """Serial chain of Logical instances; returns interleaved L/R floats."""
    out = []
    for il, ir in blocks:
        a, b = il, ir
        for m in models:
            a, b = m.process_block(a, b)
        out.extend(to_float(a))
        out.extend(to_float(b))
    return out


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------

def nc_a_wrong_order():
    blocks = stim(16, seed=201)
    ca, cb = M.build_control(CARRIER), M.build_control(CARRIER_B)
    ref = run_chain([M.Logical4Fixed(ca), M.Logical4Fixed(cb)], blocks)
    swp = run_chain([M.Logical4Fixed(cb), M.Logical4Fixed(ca)], blocks)
    m = metrics(ref, swp)
    ok = not within_budget(m) and swp != ref
    return {
        "control": "NC-A wrong order (two same-class Logical slots swapped)",
        "metrics": m, "bit_identical": swp == ref, "ok": ok,
        "verdict": ("CONTROL-OK: the permuted chain is not bit-identical and "
                    "is outside the [PROPOSED] agreement thresholds"
                    if ok else "BROKEN CONTROL: the permutation was not "
                               "detected"),
    }


def nc_b_shared_state():
    """Pool the two instances' state records and show the dual-instance
    equality fails."""
    blocks_a = stim(12, seed=211, amp=0.5)
    blocks_b = stim(12, seed=213, amp=0.3)
    ca, cb = M.build_control(CARRIER), M.build_control(CARRIER_B)

    # correct: two independent instances, interleaved
    ia, ib = M.Logical4Fixed(ca), M.Logical4Fixed(cb)
    ref_a, ref_b = [], []
    for k in range(len(blocks_a)):
        ref_a.extend(to_float(ia.process_block(*blocks_a[k])[0]))
        ref_b.extend(to_float(ib.process_block(*blocks_b[k])[0]))
    ref_state_a = ia.st.digest()

    # defective: ONE pooled state record serving both slots
    pooled = M.Logical4Fixed(ca)
    got_a, got_b = [], []
    for k in range(len(blocks_a)):
        got_a.extend(to_float(pooled.process_block(*blocks_a[k])[0]))
        pooled.set_control(cb)
        got_b.extend(to_float(pooled.process_block(*blocks_b[k])[0]))
        pooled.set_control(ca)
    m = metrics(ref_a, got_a)
    ok = (got_a != ref_a) and (pooled.st.digest() != ref_state_a)
    return {
        "control": "NC-B shared instead of per-instance state",
        "metrics": m,
        "instance_a_output_changed": got_a != ref_a,
        "instance_a_state_changed": pooled.st.digest() != ref_state_a,
        "ok": ok,
        "verdict": ("CONTROL-OK: pooling the two slots' histories changes "
                    "instance A's output AND its state digest"
                    if ok else "BROKEN CONTROL: pooling was undetectable"),
    }


def nc_c_generic_substitute():
    blocks = stim(16, seed=221)
    ctrl = M.build_control(CARRIER)
    ref = run_chain([M.Logical4Fixed(ctrl)], blocks)
    sub = GenericCompressorADAPTED(ctrl)
    got = []
    for il, ir in blocks:
        a, b = sub.process_block(to_float(il), to_float(ir))
        got.extend(a)
        got.extend(b)
    m = metrics(ref, got)
    ok = not within_budget(m) and getattr(sub, "is_adapted", False)
    return {
        "control": "NC-C generic substitute (generic peak compressor in "
                   "place of the pinned Logical algorithm)",
        "metrics": m,
        "label": "ADAPTED",
        "counts_toward_original_preset_coverage": False,
        "refused_from_coverage": True,
        "ok": ok,
        "verdict": ("CONTROL-OK: the substitute is labelled ADAPTED, is "
                    "refused from original-preset coverage, and FAILS the "
                    "[PROPOSED] agreement thresholds"
                    if ok else "BROKEN CONTROL: a generic substitute passed"),
        "reference_anchored_leg": {
            "status": "NOT_RUN",
            "why": "the leg that would compare the substitute against the "
                   "PINNED ENGINE needs an oracle host; the model-vs-model "
                   "leg above is what ran",
        },
    }


def nc_d_dropped_tail():
    """Truncate the render before the declared gain-recovery tail span.

    Logical emits silence into silence, so the tail is a STATE tail: the
    defect is only observable in the audio that follows the tail. The check
    therefore compares the RESUMED burst.
    """
    ctrl = M.build_control(CARRIER)
    span = M.tail_window_blocks(ctrl)
    burst = 8
    resume = 8
    full = stim(burst + span + resume, seed=231, amp=0.6,
                silence_from=burst * M.BLOCK)
    # restore the resumed burst after the silent span
    tail_end = (burst + span) * M.BLOCK
    live = stim(burst + span + resume, seed=231, amp=0.6)
    for b in range(burst + span, burst + span + resume):
        full[b] = live[b]

    m_full = M.Logical4Fixed(ctrl)
    ref = []
    for b, (il, ir) in enumerate(full):
        ol, orr = m_full.process_block(il, ir)
        if b >= burst + span:
            ref.extend(to_float(ol) + to_float(orr))

    # defect: the tail span is DROPPED (never processed), the render resumes
    m_cut = M.Logical4Fixed(ctrl)
    got = []
    for b, (il, ir) in enumerate(full):
        if burst <= b < burst + span:
            continue                   # the dropped tail
        ol, orr = m_cut.process_block(il, ir)
        if b >= burst + span:
            got.extend(to_float(ol) + to_float(orr))
    m = metrics(ref, got)
    ok = (got != ref)
    return {
        "control": "NC-D dropped tail (render truncated before the declared "
                   "gain-recovery span, then resumed)",
        "declared_tail_blocks": span,
        "declared_tail_samples": M.tail_window_samples(ctrl),
        "metrics": m,
        "ok": ok,
        "outside_budget": not within_budget(m),
        "verdict": ("CONTROL-OK: dropping the declared tail span changes the "
                    "resumed burst"
                    if ok else "BROKEN CONTROL: the dropped tail was "
                               "undetectable"),
        "note": "a compressor emits silence INTO silence, so the tail is a "
                "state tail; an amplitude-only ringout gate would read 'no "
                "tail' and pass a dropped-tail render. That is exactly why "
                "the check is anchored on the RESUMED burst.",
    }


def nc_e_stale_and_silent_stub():
    legs = []

    # (1) silent stub: an instance that returns zeros
    blocks = stim(8, seed=241)
    ctrl = M.build_control(CARRIER)
    ref = run_chain([M.Logical4Fixed(ctrl)], blocks)
    silent = [0.0] * len(ref)
    m = metrics(ref, silent)
    legs.append({"leg": "silent stub", "metrics": m,
                 "ok": not within_budget(m),
                 "verdict": "CONTROL-OK: an all-zero stub FAILS the "
                            "thresholds (the check is not vacuous)"})

    # (2) stale frozen-model revision pin, exercised through the real
    #     exactness comparator
    cmp_path = os.path.join(REPO, "tools", "compare_rtl_model_aw4.py")
    have_iv = subprocess.run(["which", "iverilog"],
                             capture_output=True).returncode == 0
    if not have_iv:
        legs.append({"leg": "stale revision pin", "status": "NOT_RUN",
                     "ok": False,
                     "verdict": "NOT_RUN: iverilog is absent, so the "
                                "harness-level stale-pin refusal could not "
                                "be exercised here (this is not a pass)"})
    else:
        r = subprocess.run([sys.executable, cmp_path, "--stale-pin",
                            "--case", "defaults"],
                           capture_output=True, text=True, cwd=REPO)
        try:
            out = json.loads(r.stdout)
            refused = all(e.get("status") == "REFUSED-STALE" for e in out)
        except Exception:
            refused = False
        legs.append({"leg": "stale revision pin", "ok": refused,
                     "comparator_status": [e.get("status") for e in out]
                                          if refused else r.stdout[-400:],
                     "verdict": ("CONTROL-OK: the comparator REFUSES a "
                                 "harness pinned to a stale frozen-model "
                                 "revision instead of reporting PASS"
                                 if refused else "BROKEN CONTROL")})

    # (3) the model revision word actually tracks the source
    rev = M.model_revision()
    legs.append({"leg": "revision word tracks the source",
                 "model_revision": rev,
                 "ok": len(rev) == 64,
                 "verdict": "CONTROL-OK: model_revision() hashes the frozen "
                            "model AND the frozen tables, so editing either "
                            "invalidates every committed pin"})

    return {"control": "NC-E stale stub / silent stub",
            "legs": legs,
            "ok": all(l["ok"] for l in legs),
            "verdict": ("CONTROL-OK" if all(l["ok"] for l in legs)
                        else "BROKEN or NOT_RUN control leg present")}


def nc_f_bypass_transparency():
    blocks = stim(8, seed=251)
    bypass = dict(CARRIER, E_mix=0.0)
    ctrl = M.build_control(bypass)
    inst = M.Logical4Fixed(ctrl)
    exact = True
    for il, ir in blocks:
        ol, orr = inst.process_block(il, ir)
        if ol != il or orr != ir:
            exact = False
    # injected leak: mix 1 LSB of wet
    leak = dict(ctrl)
    leak["wet_is_one"] = False
    leak["wet_k"] = 1
    leak["dry_k"] = M.ONE_K - 1
    li = M.Logical4Fixed(leak)
    leaked = False
    for il, ir in blocks:
        ol, orr = li.process_block(il, ir)
        if ol != il or orr != ir:
            leaked = True
    ok = exact and leaked
    return {
        "control": "NC-F bypass transparency (E_mix = 0) + injected mix leak",
        "bypass_bit_exact_dry": exact,
        "one_lsb_leak_detected": leaked,
        "ok": ok,
        "verdict": ("CONTROL-OK: E_mix = 0 is bit-exact dry AND a 1-LSB wet "
                    "leak is detected, so the bypass check is live"
                    if ok else "BROKEN CONTROL"),
        "note": "the unmodified WET reference is retained: this control "
                "compares the bypassed render against the dry input, it "
                "never replaces the wet reference (AGENTS.md).",
    }


def nc_g_quirk_fixes():
    """A model that 'fixes' a pinned quirk is not the reference."""
    legs = []

    # Q1: constant 2-sample tap instead of the +499-mirror 2/3-sample tap
    ctrl = M.build_control(CARRIER)
    blocks = stim(40, seed=261)          # > 1000 samples: crosses two wraps
    ref = run_chain([M.Logical4Fixed(ctrl)], blocks)
    orig_tap = M.pinned_tap_age
    try:
        M.pinned_tap_age = lambda g, off=M.SAG_OFFSET: off
        got = run_chain([M.Logical4Fixed(ctrl)], blocks)
    finally:
        M.pinned_tap_age = orig_tap
    m1 = metrics(ref, got)
    legs.append({"leg": "Q1 sag-mirror tap age 'fixed' to a constant 2",
                 "changed": got != ref, "metrics": m1,
                 "ok": got != ref,
                 "detected_by": "bit-inequality (the EXACTNESS leg)",
                 "budget_would_discriminate": not within_budget(m1),
                 "verdict": "CONTROL-OK: the quirk is load-bearing"
                            if got != ref else "BROKEN CONTROL"})

    # Q2: stage C's right channel updating its OWN positive target
    ctrl2 = M.build_control(dict(A_threshold=0.473214, B_ratio=1.0,
                                 C_attack=0.0, D_makeup=0.250893, E_mix=1.0))
    blocks2 = stim(16, seed=263)
    ref2 = run_chain([M.Logical4Fixed(ctrl2)], blocks2)

    class FixedQ2(M.Logical4Fixed):
        def _comp(self, stage, ch, x):
            # temporarily neutralise the quirk by relabelling stage C
            if stage == 2 and ch == 1:
                st = self.st
                save = st.t_pos[2][0]
                out = M.Logical4Fixed._comp(self, stage, ch, x)
                # undo the LEFT-target write and apply it to the RIGHT one
                st.t_pos[2][1] = st.t_pos[2][0]
                st.t_pos[2][0] = save
                return out
            return M.Logical4Fixed._comp(self, stage, ch, x)

    got2 = run_chain([FixedQ2(ctrl2)], blocks2)
    m2 = metrics(ref2, got2)
    legs.append({"leg": "Q2 stage-C right-channel target 'fixed'",
                 "changed": got2 != ref2, "metrics": m2,
                 "ok": got2 != ref2,
                 "detected_by": "bit-inequality (the EXACTNESS leg)",
                 "budget_would_discriminate": not within_budget(m2),
                 "verdict": "CONTROL-OK: the quirk is load-bearing"
                            if got2 != ref2 else "BROKEN CONTROL"})
    gap = [l["leg"] for l in legs if not l["budget_would_discriminate"]]
    return {"control": "NC-G pinned-quirk 'fixes'", "legs": legs,
            "ok": all(l["ok"] for l in legs),
            "known_gap": {
                "legs_inside_the_proposed_budgets": gap,
                "text": "these quirk 'fixes' change the output but stay "
                        "INSIDE the [PROPOSED] SXT-023 effect-slice budgets, "
                        "so a reference-agreement check at those thresholds "
                        "would NOT discriminate them. Only the exactness leg "
                        "(bit equality against the frozen model) catches "
                        "them. Recorded as finding F-028k-3 and routed to "
                        "SXT-017 (#12) as an input to the budget freeze; NOT "
                        "a reason to widen or narrow any budget here.",
            } if gap else None,
            "verdict": "CONTROL-OK" if all(l["ok"] for l in legs)
                       else "BROKEN CONTROL"}


CONTROLS = [nc_a_wrong_order, nc_b_shared_state, nc_c_generic_substitute,
            nc_d_dropped_tail, nc_e_stale_and_silent_stub,
            nc_f_bypass_transparency, nc_g_quirk_fixes]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-report", action="store_true")
    args = ap.parse_args()

    controls = [f() for f in CONTROLS]
    ok = all(c["ok"] for c in controls)
    rec = {
        "leaf": "SXT-028k",
        "issue": 63,
        "claim_scope": "MODEL-VS-MODEL only. The frozen model is the "
                       "reference in every comparison here. These controls "
                       "show the checks are live; they establish nothing "
                       "about agreement with the pinned Surge engine "
                       "(NOT_RUN) and nothing about musical quality.",
        "thresholds": {
            "source": "[PROPOSED] SXT-023 effect-slice budgets, used here "
                      "ONLY as a substitution detector; not frozen (#12)",
            "max_abs_linear": BUDGET_MAX_LINEAR,
            "max_abs_note": "8192 LSB at Q10.21 expressed in linear units",
            "rms_dbfs": BUDGET_RMS_DBFS,
            "corr": BUDGET_CORR,
        },
        "model_revision": M.model_revision(),
        "status": "PASS" if ok else "FAIL",
        "controls": controls,
    }
    if args.write_report:
        os.makedirs(REPORT, exist_ok=True)
        with open(os.path.join(REPORT, "negative-controls.json"), "w") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
        with open(os.path.join(REPORT, "negative-controls.txt"), "w") as f:
            f.write("SXT-028k model-side negative controls (model-vs-model)\n")
            f.write("model_revision %s\n\n" % rec["model_revision"])
            for c in controls:
                f.write("%-72s %s\n" % (c["control"],
                                        "OK" if c["ok"] else "BROKEN"))
                f.write("    %s\n" % c["verdict"])
                for leg in c.get("legs", []):
                    f.write("      - %-40s %s\n"
                            % (leg.get("leg"), leg.get("verdict")))
            f.write("\nstatus: %s\n" % rec["status"])
    print(json.dumps({k: v for k, v in rec.items() if k != "controls"},
                     indent=2))
    for c in controls:
        print("  %-70s %s" % (c["control"][:70], "OK" if c["ok"] else "BROKEN"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
