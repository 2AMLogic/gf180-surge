#!/usr/bin/env python3
"""SXT-028g negative controls: each control must DEMONSTRABLY FAIL the check
it targets. A control that passes is a BROKEN control and this tool exits
non-zero.

NC-A  generic substitute: a deliberately convenient generic phaser (ONE
      fixed allpass stage, no LFO, no spread, identical L/R) driven by the
      same stimulus must FAIL the same declared agreement threshold the
      reference comparison uses. It is labelled ADAPTED and excluded from
      original-preset coverage (tools/ablate_fx.py substitute pattern).
NC-B  dropped tail: a render truncated before the declared tail span (the
      Phaser.h getRingoutDecay window after the input goes silent) must FAIL
      the tail check, on BOTH legs — region coverage and terminal energy.
      The untruncated render must PASS the same check.
NC-C  wrong order: two phaser instances with different parameters chained
      A->B vs B->A must differ (order-sensitive). The same detector must
      report equality for an unpermuted chain, so it is not always-firing.
NC-D  stale stub: the RTL exactness comparator must REFUSE a trace whose
      frozen-revision pin does not match the live model (never PASS).
NC-E  bypass transparency: with mix = 0 the model output must equal its
      input within the declared Q13.18 lipol smoothing floor, and an
      injected wet leak (mix = 0.05) must be DETECTED by the same check.
      The unmodified wet path is retained in both legs.
NC-F  LFO-depth sensitivity: halving the modulation depth must FAIL the
      declared agreement threshold — the LFO trajectory is load-bearing.
      The unmutated run must be bit-identical to itself (null leg).

ANCHOR AND CLAIM SCOPE. Without a pinned-engine checkout there is no wet
reference in this environment, so every control below is anchored on the
FROZEN MODEL and on the declared agreement threshold, never on the engine.
Each control therefore records a `reference_anchored_leg` field with status
NOT_RUN: re-running these controls against oracle fixtures is required
before any model-vs-reference statement, and nothing here is a fidelity,
agreement or support claim.

Oracle-independent. Exits 0 iff every control fails the check it targets.
Original to this repository (Apache-2.0).
"""

import json
import math
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-phaser"))

from phaser_model import (  # noqa: E402
    PhaserModel, PhaserParams, BLOCK, A_FMT, C_FMT, G_FMT, MonoBiquad,
    coeff_apf, calc_omega_d, model_revision, ringout_blocks,
)
from model.effects.qmath import FRAC, to_q, qadd, qsub, qmul, clip  # noqa: E402
from corners import CORNERS  # noqa: E402

OUT = os.path.join(REPO, "reports", "SXT-028g", "negative-controls")
ART = os.path.join(REPO, "reports", "SXT-028g", "artifacts")

# The declared agreement threshold: the same max_abs_diff budget the
# reference comparator proposes for this effect-slice family
# (tools/compare_chorus_reference.py PROPOSED["max_abs_diff_lsb"]); a mutant
# must exceed the very budget a reference comparison would grade against.
SENSITIVITY_LSB = 8192

# The Q13.18 lipol smoothing floor: set_target_smoothed converges as
# target <- round_half_up(0.25*f + 0.75*target), which STICKS at 2 LSB for
# f = 0 (round-half-up of 1.5 is 2). Declared model artifact of the pinned
# 0.25/0.75 recurrence at this word length (the engine's float ramp
# underflows to 0 instead); it bounds the fully-converged bypass residual.
MIX_FLOOR_LSB_Q1318 = 2
BYPASS_BOUND_LSB = 512      # declared bypass transparency bound in Q10.21 LSB

BURST_BLOCKS = 96
TAIL_TERMINAL_LSB = 4       # a captured tail must have died below this
CONTROL_CORNER = "synth-a"


def prs(n_blocks, seed, amp=1, silence_from=None):
    rs = random.Random(seed)
    blocks = []
    for b in range(n_blocks):
        if silence_from is not None and b >= silence_from:
            blocks.append(([0] * BLOCK, [0] * BLOCK))
        else:
            blocks.append((
                [rs.randint(-(amp << 21), amp << 21) for _ in range(BLOCK)],
                [rs.randint(-(amp << 21), amp << 21) for _ in range(BLOCK)]))
    return blocks


def run_model(params, blocks):
    m = PhaserModel(PhaserParams(dict(params)), "x")
    m.initialize()
    out = []
    for il, ir in blocks:
        out.append(m.process_block(il, ir))
    return out, m


def flat(out):
    v = []
    for ol, orr in out:
        v += ol
        v += orr
    return v


def max_abs_diff_lsb(a, b):
    n = min(len(a), len(b))
    return max((abs(a[i] - b[i]) for i in range(n)), default=0)


# --------------------------------------------------------------------------
# NC-A generic substitute
# --------------------------------------------------------------------------

class GenericPhaserSubstitute:
    """A 'convenient generic': ONE static allpass per channel at a fixed
    centre, no LFO, no spread, no per-channel stereo, no feedback ramp.

    This is exactly the kind of substitution AGENTS.md forbids under a
    support claim. It is kept here only as a live control and is labelled
    ADAPTED: it can never count toward original-preset coverage.
    """

    coverage_class = "ADAPTED"
    counts_toward_original_preset_coverage = False

    def __init__(self, params):
        self.p = PhaserParams(dict(params))
        c5 = coeff_apf(calc_omega_d(2.0 * self.p.center_f), 1.0)
        self.l = MonoBiquad()
        self.r = MonoBiquad()
        self.l.new_targets(c5)
        self.r.new_targets(c5)
        self.mix = to_q(min(1.0, max(0.0, self.p.mix_f)), G_FMT)
        self.fb = to_q(0.95 * self.p.feedback_f, C_FMT)
        self.dl = 0
        self.dr = 0

    def process_block(self, il, ir):
        one = 1 << FRAC[G_FMT]
        ol, orr = [], []
        for k in range(BLOCK):
            dl = qadd(il[k], qmul(self.dl, self.fb, A_FMT, C_FMT, A_FMT), A_FMT)
            dr = qadd(ir[k], qmul(self.dr, self.fb, A_FMT, C_FMT, A_FMT), A_FMT)
            dl = self.l.process_sample(dl)
            dr = self.r.process_sample(dr)
            self.dl, self.dr = dl, dr
            inv = qsub(one, self.mix, G_FMT)
            ol.append(qadd(qmul(inv, il[k], G_FMT, A_FMT, A_FMT),
                           qmul(self.mix, dl, G_FMT, A_FMT, A_FMT), A_FMT))
            orr.append(qadd(qmul(inv, ir[k], G_FMT, A_FMT, A_FMT),
                            qmul(self.mix, dr, G_FMT, A_FMT, A_FMT), A_FMT))
        return ol, orr


def nc_generic_substitute(params, blocks):
    ref, _ = run_model(params, blocks)
    sub = GenericPhaserSubstitute(params)
    got = [sub.process_block(il, ir) for il, ir in blocks]
    d = max_abs_diff_lsb(flat(ref), flat(got))
    fails = d > SENSITIVITY_LSB
    ok = (fails
          and GenericPhaserSubstitute.coverage_class == "ADAPTED"
          and not GenericPhaserSubstitute
          .counts_toward_original_preset_coverage)
    return {
        "control": "NC-A generic substitute (single static allpass, no LFO)",
        "metrics": {"max_abs_diff_lsb": d,
                    "declared_threshold_lsb": SENSITIVITY_LSB},
        "coverage_class": "ADAPTED",
        "counts_toward_original_preset_coverage": False,
        "reference_anchored_leg": {
            "status": "NOT_RUN",
            "reason": "no pinned-engine fixture in this environment; the "
                      "substitute must also be re-scored against the wet "
                      "reference budgets before any agreement statement"},
        "verdict": ("CONTROL-OK (the generic substitute FAILS the declared "
                    "agreement threshold and is refused from original-preset "
                    "coverage as ADAPTED)" if ok else
                    "CONTROL-BROKEN (substitute indistinguishable or not "
                    "refused!)"),
        "ok": ok,
    }


# --------------------------------------------------------------------------
# NC-B dropped tail
# --------------------------------------------------------------------------

def tail_window(params):
    """The DECLARED tail span of a Phaser instance, in blocks and seconds.

    Phaser::getRingoutDecay returns a ringout length in BLOCKS as a function
    of feedback; that is the span an acceptance render must cover after the
    input goes silent. -1 (|feedback| > 1: possible self-oscillation) means
    no finite span can be declared and the tail check REFUSES.
    """
    rb = ringout_blocks(PhaserParams(dict(params)).feedback_f)
    return {"ringout_blocks": rb,
            "ringout_seconds": None if rb < 0 else rb * BLOCK / 48000.0,
            "basis": "Phaser.h getRingoutDecay (blocks), feedback-dependent"}


def tail_check(params, out, silence_from, declared_blocks):
    """Two legs: the render must COVER the declared span after silence, and
    the captured tail must have decayed to the terminal floor by its end."""
    if declared_blocks < 0:
        return {"ok": False, "refused": True,
                "reason": "getRingoutDecay = -1 (possible self-oscillation): "
                          "no finite tail span can be declared"}
    have = len(out) - silence_from
    covered = have >= declared_blocks
    last_l, last_r = out[-1]
    terminal = max(max(abs(v) for v in last_l), max(abs(v) for v in last_r))
    onset_l, onset_r = out[silence_from]
    onset = max(max(abs(v) for v in onset_l), max(abs(v) for v in onset_r))
    decayed = terminal <= TAIL_TERMINAL_LSB
    present = onset > TAIL_TERMINAL_LSB
    return {"ok": bool(covered and decayed and present),
            "refused": False,
            "declared_tail_blocks": declared_blocks,
            "render_tail_blocks": have,
            "tail_region_covered": bool(covered),
            "tail_present_at_onset": bool(present),
            "tail_decayed_by_end": bool(decayed),
            "onset_peak_lsb": onset, "terminal_peak_lsb": terminal,
            "terminal_floor_lsb": TAIL_TERMINAL_LSB}


def nc_dropped_tail(params):
    tw = tail_window(params)
    declared = tw["ringout_blocks"]
    full_blocks = BURST_BLOCKS + declared
    blocks = prs(full_blocks, 21, silence_from=BURST_BLOCKS)
    full_out, _ = run_model(params, blocks)
    full = tail_check(params, full_out, BURST_BLOCKS, declared)

    trunc_len = BURST_BLOCKS + max(1, declared // 8)
    trunc_out = full_out[:trunc_len]
    trunc = tail_check(params, trunc_out, BURST_BLOCKS, declared)

    ok = full["ok"] and not trunc["ok"]
    return {
        "control": "NC-B dropped tail (render truncated to 1/8 of the "
                   "declared getRingoutDecay span)",
        "tail_window": tw,
        "full_render": full,
        "truncated_render": trunc,
        "reference_anchored_leg": {
            "status": "NOT_RUN",
            "reason": "the wet-path tail-region gate against the pinned "
                      "engine (tools/compare_phaser_reference.py, issue "
                      "#100) needs an oracle fixture sidecar"},
        "verdict": ("CONTROL-OK (the full render passes the declared tail "
                    "check and the truncated render FAILS it)" if ok else
                    "CONTROL-BROKEN (tail check insensitive to truncation!)"),
        "ok": ok,
    }


# --------------------------------------------------------------------------
# NC-C wrong order
# --------------------------------------------------------------------------

def chain(param_list, blocks):
    models = [PhaserModel(PhaserParams(dict(p)), f"c{i}")
              for i, p in enumerate(param_list)]
    for m in models:
        m.initialize()
    out = []
    for il, ir in blocks:
        a, b = il, ir
        for m in models:
            a, b = m.process_block(a, b)
        out.append((a, b))
    return out


def nc_wrong_order():
    pa, pb = CORNERS["synth-a"], CORNERS["synth-b"]
    blocks = prs(64, 31)
    ab = chain([pa, pb], blocks)
    ba = chain([pb, pa], blocks)
    ab2 = chain([pa, pb], blocks)
    d_perm = max_abs_diff_lsb(flat(ab), flat(ba))
    d_null = max_abs_diff_lsb(flat(ab), flat(ab2))
    fires = d_perm > SENSITIVITY_LSB
    null_quiet = d_null == 0
    ok = fires and null_quiet
    return {
        "control": "NC-C wrong order (A->B vs B->A slot-content permutation)",
        "metrics": {"permuted_max_abs_diff_lsb": d_perm,
                    "unpermuted_max_abs_diff_lsb": d_null,
                    "declared_threshold_lsb": SENSITIVITY_LSB},
        "reference_anchored_leg": {
            "status": "NOT_RUN",
            "reason": "order-sensitive agreement against the pinned engine "
                      "needs an oracle fixture"},
        "verdict": ("CONTROL-OK (the permutation FAILS the order-sensitive "
                    "check and the unpermuted chain is bit-identical, so the "
                    "detector is not always-firing)" if ok else
                    "CONTROL-BROKEN (permutation undetected or detector "
                    "always fires!)"),
        "ok": ok,
    }


# --------------------------------------------------------------------------
# NC-D stale stub
# --------------------------------------------------------------------------

def nc_stale_stub():
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import compare_rtl_model_phaser as crm

    live = model_revision()[:8]
    stale = "deadbeef"
    exp = [{"b": 0, "O": {0: [0] * 64}, "X": {}, "T": {}}]
    tmp = os.path.join(OUT, "_stale_trace.txt")
    os.makedirs(OUT, exist_ok=True)
    with open(tmp, "w") as f:
        f.write(f"R {stale}\n")
        f.write("O 0 0 " + " ".join(["0"] * 64) + "\n")
    res = crm.judge("stale", exp, tmp, 1, live, 1)
    os.remove(tmp)
    ok = (res["exact"] is False) and (res["revision_pin"]["ok"] is False)
    return {
        "control": "NC-D stale stub (frozen-revision pin)",
        "metrics": {"live_revision": live, "trace_revision": stale,
                    "samples_matched": True},
        "verdict": ("CONTROL-OK (a trace whose outputs match but whose "
                    "revision pin is stale is REFUSED, never PASS)" if ok
                    else "CONTROL-BROKEN (stale trace accepted!)"),
        "ok": ok,
    }


# --------------------------------------------------------------------------
# NC-E bypass transparency
# --------------------------------------------------------------------------

def nc_bypass(params):
    blocks = prs(320, 41)
    p0 = dict(params, mix_f=0.0)
    out0, m0 = run_model(p0, blocks)
    settle = 200
    dry = flat([(il, ir) for il, ir in blocks[settle:]])
    wet0 = flat(out0[settle:])
    resid = max_abs_diff_lsb(dry, wet0)

    p_leak = dict(params, mix_f=0.05)
    out_leak, _ = run_model(p_leak, blocks)
    leak = max_abs_diff_lsb(dry, flat(out_leak[settle:]))

    transparent = resid <= BYPASS_BOUND_LSB
    detects = leak > BYPASS_BOUND_LSB
    ok = transparent and detects
    return {
        "control": "NC-E bypass transparency (mix = 0 within the declared "
                   "Q13.18 lipol floor; wet leak detected)",
        "metrics": {"mix0_residual_lsb": resid,
                    "declared_bypass_bound_lsb": BYPASS_BOUND_LSB,
                    "injected_leak_mix0p05_lsb": leak,
                    "mix_target_floor_q1318_lsb": m0.st.mix.target,
                    "expected_mix_floor_q1318_lsb": MIX_FLOOR_LSB_Q1318},
        "note": "the residual is not zero because the pinned 0.25/0.75 "
                "lipol_sse recurrence STICKS at 2 LSB in Q13.18 under "
                "round-half-up (the engine's float ramp underflows to 0). "
                "Declared model deviation, bounded and measured here.",
        "reference_anchored_leg": {
            "status": "NOT_RUN",
            "reason": "the bypass leg must also retain and re-grade the "
                      "unmodified wet reference once an oracle fixture "
                      "exists (AGENTS.md bypass rule)"},
        "verdict": ("CONTROL-OK (mix = 0 is transparent within the declared "
                    "floor and an injected wet leak is detected by the same "
                    "check)" if ok else
                    "CONTROL-BROKEN (bypass property or leak detector "
                    "failed!)"),
        "ok": ok,
    }


# --------------------------------------------------------------------------
# NC-F LFO-depth sensitivity
# --------------------------------------------------------------------------

def nc_lfo_depth(params, blocks):
    ref, _ = run_model(params, blocks)
    ref2, _ = run_model(params, blocks)
    mut, _ = run_model(dict(params, mod_depth_f=params["mod_depth_f"] * 0.5),
                       blocks)
    d = max_abs_diff_lsb(flat(ref), flat(mut))
    d_null = max_abs_diff_lsb(flat(ref), flat(ref2))
    ok = d > SENSITIVITY_LSB and d_null == 0
    return {
        "control": "NC-F LFO-depth sensitivity (modulation depth halved)",
        "metrics": {"mutant_max_abs_diff_lsb": d,
                    "null_leg_max_abs_diff_lsb": d_null,
                    "declared_threshold_lsb": SENSITIVITY_LSB},
        "reference_anchored_leg": {
            "status": "NOT_RUN",
            "reason": "LFO-trajectory agreement against the pinned engine "
                      "needs an oracle fixture"},
        "verdict": ("CONTROL-OK (the LFO-trajectory mutant FAILS the declared "
                    "threshold while the null leg is bit-identical)" if ok
                    else "CONTROL-BROKEN (LFO depth not load-bearing!)"),
        "ok": ok,
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(ART, exist_ok=True)
    params = CORNERS[CONTROL_CORNER]
    blocks = prs(96, 11)

    controls = [
        nc_generic_substitute(params, blocks),
        nc_dropped_tail(params),
        nc_wrong_order(),
        nc_stale_stub(),
        nc_bypass(params),
        nc_lfo_depth(params, blocks),
    ]
    ok_all = all(c["ok"] for c in controls)
    doc = {"schema_version": 1, "leaf": "SXT-028g",
           "model_revision": model_revision(),
           "corner": CONTROL_CORNER,
           "anchor": "frozen model + declared agreement threshold "
                     "(no pinned-engine reference is available in this "
                     "environment; every reference-anchored leg is NOT_RUN)",
           "declared_threshold_lsb": SENSITIVITY_LSB,
           "status": "PASS" if ok_all else "FAIL",
           "controls": controls}
    with open(os.path.join(OUT, "negative-controls.json"), "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    with open(os.path.join(OUT, "negative-controls.txt"), "w") as f:
        for c in controls:
            f.write(f"{c['control']}\n  {c['verdict']}\n")
        f.write(f"status: {doc['status']}\n")

    tw = {"schema_version": 1, "leaf": "SXT-028g",
          "basis": "Phaser.h getRingoutDecay (BLOCKS of 32 samples at 48 kHz)",
          "rule": "an acceptance render must cover this many blocks AFTER "
                  "the input goes silent; a shorter render FAILS the tail "
                  "check (coverage leg) and a still-loud final block FAILS "
                  "it (terminal-energy leg)",
          "terminal_floor_lsb_q1021": TAIL_TERMINAL_LSB,
          "windows": {}}
    for slug, p in sorted(CORNERS.items()):
        tw["windows"][slug] = tail_window(p)
    with open(os.path.join(ART, "tail-window.json"), "w") as f:
        json.dump(tw, f, indent=2, sort_keys=True)
        f.write("\n")

    for c in controls:
        print(c["control"], "->", c["verdict"])
    print("status:", doc["status"])
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
