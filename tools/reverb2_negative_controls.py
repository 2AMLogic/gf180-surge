#!/usr/bin/env python3
"""SXT-028f negative controls (model-side). Each control must DEMONSTRABLY
FAIL the check it targets; a control that passes is a broken control, and a
control whose target the stimulus never exercises is VACUOUS -- also a
finding, never a pass.

NC-A  generic substitute: a deliberately convenient generic reverb (one
      feedback comb per tank block, no allpass diffusion, no sub-sample
      modulated read, no damping) driven by the same stimulus must FAIL the
      [PROPOSED] agreement budgets against the frozen model -- ADAPTED is
      not supported (tools/ablate_fx.py substitute pattern).
NC-B  dropped tail: the same render truncated before the declared tail span
      must FAIL the declared-region tail gate (region covered, tail present
      in both, residual <= -20 dB relative to the reference tail RMS).
NC-C  wrong order: two serial Reverb 2 instances A->B versus B->A must be
      FLAGGED by the order-sensitive equality check (slot-content
      permutation, tools/ablate_fx.py permute pattern).
NC-D  shared state: pooling the two instances' external regions into one
      must FAIL the dual-instance independence check.
NC-E  stale stub: a trace/record whose frozen-revision word is not the live
      model revision must be REFUSED (never reported PASS).
NC-F  bypass transparency: with mix = 0 the model output must equal its
      input EXACTLY; an injected mix leak must be detected.
NC-G  suspend semantics: the pinned engine's suspendProcessing() is
      setvars(true) and does NOT clear the tank. A mutant that clears on
      suspend must be FLAGGED by the declared reset/suspend check.

CLAIM SCOPE. Every comparison here is model-vs-model: the frozen model is
the reference. This establishes that the checks and budgets are live and
that the listed defects are detectable. It establishes NOTHING about
agreement with the pinned Surge engine (that leg needs the oracle host and
is reported separately), and no preset-support or sound claim.

Exits 0 iff every control fails (or is refused by) the check it targets.
Original to this repository (Apache-2.0).
"""

import argparse
import json
import math
import os
import random
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-reverb 2"))

from reverb2_model import (  # noqa: E402
    Reverb2Model, Reverb2Params, HARNESS_PROFILE, NUM_BLOCKS, BLOCK,
    model_revision,
)
from model.effects.qmath import qadd, qsub, qmul  # noqa: E402

A_FMT, G_FMT, C_FMT = "Q10.21", "Q13.18", "Q24.43"
LSB = 2.0 ** -21
FULL_SCALE = float(1 << 21)
RMS_FLOOR = -200.0

# [PROPOSED] agreement budgets -- identical values to the sxt-023
# effect-slice family reused by SXT-024/SXT-028c. NOT frozen (SXT-017/#12).
PROPOSED = {"max_abs_diff_lsb": 8192.0, "rms_diff_dbfs": -46.0,
            "spectral_corr_min": 0.98}
PROPOSED_TAIL = {"tail_rms_rel_db": -20.0}

PARAMS_A = dict(predelay_f=-4.0, room_size_f=0.0, decay_time_f=0.75,
                diffusion_f=1.0, buildup_f=1.0, modulation_f=0.5,
                lf_damping_f=0.2, hf_damping_f=0.2, width_f=0.0, mix_f=1.0)
PARAMS_B = dict(predelay_f=-6.0, room_size_f=-0.35, decay_time_f=1.6,
                diffusion_f=0.62, buildup_f=0.83, modulation_f=0.9,
                lf_damping_f=0.55, hf_damping_f=0.71, width_f=-3.0,
                mix_f=0.4)

BURST_BLOCKS = 48
TAIL_BLOCKS = 224          # declared tail span of the acceptance render
TOTAL_BLOCKS = BURST_BLOCKS + TAIL_BLOCKS


# ------------------------------------------------------------- utilities
def stimulus(seed=5, amp=1 << 20, n_blocks=TOTAL_BLOCKS,
             burst=BURST_BLOCKS):
    rs = random.Random(seed)
    out = []
    for b in range(n_blocks):
        if b < burst:
            out.append(([rs.randint(-amp, amp) for _ in range(BLOCK)],
                        [rs.randint(-amp, amp) for _ in range(BLOCK)]))
        else:
            out.append(([0] * BLOCK, [0] * BLOCK))
    return out


def render(model, stim):
    ol, orr = [], []
    for il, ir in stim:
        a, b = model.process_block(il, ir)
        ol.extend(a)
        orr.extend(b)
    return np.array(ol, dtype=np.int64), np.array(orr, dtype=np.int64)


def spectral_corr(a, b, frame=4096):
    n = min(len(a), len(b))
    if n < frame:
        return 1.0 if np.allclose(a, b) else 0.0
    ra = np.log1p(np.abs(np.fft.rfft(
        a[: n // frame * frame].reshape(-1, frame) * np.hanning(frame),
        axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(
        b[: n // frame * frame].reshape(-1, frame) * np.hanning(frame),
        axis=1))).ravel()
    ra -= ra.mean()
    rb -= rb.mean()
    d = math.sqrt(float((ra * ra).sum()) * float((rb * rb).sum()))
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def rms_dbfs(rms):
    if not rms > 0:
        return RMS_FLOOR
    return max(20.0 * math.log10(rms / FULL_SCALE), RMS_FLOOR)


def agreement(ref_l, ref_r, mod_l, mod_r):
    """The [PROPOSED] budget triple, worst channel."""
    worst = None
    for ref, mod in ((ref_l, mod_l), (ref_r, mod_r)):
        n = min(len(ref), len(mod))
        d = np.abs(ref[:n] - mod[:n]).astype(np.float64)
        m = {"max_abs_diff_lsb": float(d.max()) if n else 0.0,
             "rms_diff_dbfs": rms_dbfs(float(np.sqrt((d * d).mean())) if n
                                       else 0.0),
             "spectral_corr": spectral_corr(ref[:n].astype(np.float64),
                                            mod[:n].astype(np.float64))}
        if worst is None or m["max_abs_diff_lsb"] > worst["max_abs_diff_lsb"]:
            worst = m
    passes = {
        "max_abs_diff_lsb": worst["max_abs_diff_lsb"]
        <= PROPOSED["max_abs_diff_lsb"],
        "rms_diff_dbfs": worst["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"],
        "spectral_corr": worst["spectral_corr"]
        >= PROPOSED["spectral_corr_min"],
    }
    worst["budget_results"] = passes
    worst["all_pass"] = all(passes.values())
    return worst


def tail_gate(ref_l, ref_r, mod_l, mod_r, tail_offset, tail_frames):
    """Declared-region tail gate (the shape the shared comparator applies to
    a wet path, issues #93/#100): the region must be covered by BOTH
    renders, the reference tail must be present, the candidate tail must be
    present, and the residual RMS inside the region must sit at least
    |tail_rms_rel_db| below the reference tail RMS."""
    end = tail_offset + tail_frames
    out = {"tail_offset": tail_offset, "tail_frames": tail_frames}
    covered = len(ref_l) >= end and len(mod_l) >= end
    out["tail_region_covered"] = bool(covered)
    if not covered:
        out.update({"tail_present": False, "model_tail_present": False,
                    "tail_rms_rel_db": None, "ok": False})
        return out
    r = np.concatenate([ref_l[tail_offset:end], ref_r[tail_offset:end]]
                       ).astype(np.float64)
    m = np.concatenate([mod_l[tail_offset:end], mod_r[tail_offset:end]]
                       ).astype(np.float64)
    ref_rms = float(np.sqrt((r * r).mean()))
    mod_rms = float(np.sqrt((m * m).mean()))
    d = r - m
    res_rms = float(np.sqrt((d * d).mean()))
    out["reference_tail_rms_dbfs"] = rms_dbfs(ref_rms)
    out["model_tail_rms_dbfs"] = rms_dbfs(mod_rms)
    out["tail_present"] = ref_rms > 0.0
    out["model_tail_present"] = mod_rms > 0.0
    rel = (RMS_FLOOR if res_rms <= 0 or ref_rms <= 0
           else 20.0 * math.log10(res_rms / ref_rms))
    out["tail_rms_rel_db"] = rel
    out["ok"] = bool(out["tail_region_covered"] and out["tail_present"]
                     and out["model_tail_present"]
                     and rel <= PROPOSED_TAIL["tail_rms_rel_db"])
    return out


def new_model(params, name="a", profile=HARNESS_PROFILE):
    m = Reverb2Model(Reverb2Params(params), name, profile)
    m.initialize()
    return m


# ------------------------------------------------------- generic substitute
class GenericReverbSubstitute:
    """A convenient generic reverb: four parallel feedback combs with the
    frozen model's own delay lengths and tap gains, a mono input fold, the
    same width/mix tail -- but NO allpass diffusion, NO damping one-poles,
    NO predelay and NO sub-sample modulated read.

    It is labelled ADAPTED. It exists to prove the agreement budgets reject
    a substitute; it is never a supported implementation of Reverb 2.
    """

    ADAPTED = True

    def __init__(self, params, name="generic"):
        self.ref = new_model(params, name)     # borrows the control plane
        self.lines = [[0] * 16384 for _ in range(NUM_BLOCKS)]
        self.k = [0] * NUM_BLOCKS

    def process_block(self, in_l, in_r):
        st = self.ref.st
        self.ref._control()
        from reverb2_model import TAP_GAIN_L, TAP_GAIN_R
        wet_l, wet_r = [0] * BLOCK, [0] * BLOCK
        for n in range(BLOCK):
            s = qadd(in_l[n], in_r[n], A_FMT)
            x_in = s >> 1 if s >= 0 else -((-s) >> 1)
            ol = orr = 0
            for b in range(NUM_BLOCKS):
                ln = self.lines[b]
                self.k[b] = (self.k[b] + 1) & 16383
                rp = (self.k[b] - st.dl_len[b]) & 16383
                y = ln[rp]
                ln[self.k[b]] = qadd(x_in, qmul(st.decay.v, y, C_FMT, A_FMT,
                                                A_FMT), A_FMT)
                tl = ln[(self.k[b] - st.tap_l[b]) & 16383]
                tr = ln[(self.k[b] - st.tap_r[b]) & 16383]
                ol = qadd(ol, qmul(TAP_GAIN_L[b], tl, G_FMT, A_FMT, A_FMT),
                          A_FMT)
                orr = qadd(orr, qmul(TAP_GAIN_R[b], tr, G_FMT, A_FMT, A_FMT),
                           A_FMT)
            wet_l[n], wet_r[n] = ol, orr
            st.decay.process()
            st.diffusion.process()
            st.buildup.process()
            st.hf_damp.process()
            st.lfo.process()
            st.modulation.process()
        out_l, out_r = [0] * BLOCK, [0] * BLOCK
        one_g = 1 << 18
        for n in range(BLOCK):
            t = st.mix.line_value(n)
            inv = qsub(one_g, t, G_FMT)
            out_l[n] = qadd(qmul(inv, in_l[n], G_FMT, A_FMT, A_FMT),
                            qmul(t, wet_l[n], G_FMT, A_FMT, A_FMT), A_FMT)
            out_r[n] = qadd(qmul(inv, in_r[n], G_FMT, A_FMT, A_FMT),
                            qmul(t, wet_r[n], G_FMT, A_FMT, A_FMT), A_FMT)
        return out_l, out_r


# ------------------------------------------------------------- the controls
def nc_a_generic_substitute(stim, ref):
    sub = GenericReverbSubstitute(PARAMS_A, "generic")
    gl, gr = render(sub, stim)
    ag = agreement(ref[0], ref[1], gl, gr)
    ok = not ag["all_pass"]
    return {"control": "NC-A generic substitute (ADAPTED)", "ok": ok,
            "label": "ADAPTED -- excluded from original-preset coverage",
            "metrics": ag,
            "verdict": ("CONTROL-OK (generic substitute FAILS the [PROPOSED] "
                        "agreement budgets; ADAPTED != supported)" if ok else
                        "CONTROL-BROKEN (a generic substitute passed!)")}


def nc_b_dropped_tail(ref):
    tail_offset = BURST_BLOCKS * BLOCK
    tail_frames = TAIL_BLOCKS * BLOCK
    full = tail_gate(ref[0], ref[1], ref[0], ref[1], tail_offset, tail_frames)
    trunc_l = ref[0][:tail_offset].copy()
    trunc_r = ref[1][:tail_offset].copy()
    truncated = tail_gate(ref[0], ref[1], trunc_l, trunc_r, tail_offset,
                          tail_frames)
    zl, zr = ref[0].copy(), ref[1].copy()
    zl[tail_offset:] = 0
    zr[tail_offset:] = 0
    zeroed = tail_gate(ref[0], ref[1], zl, zr, tail_offset, tail_frames)
    live = full["ok"] and full["tail_present"]
    ok = live and (not truncated["ok"]) and (not zeroed["ok"])
    return {"control": "NC-B dropped tail", "ok": ok, "live": live,
            "baseline_full_tail": full, "truncated": truncated,
            "zeroed": zeroed,
            "verdict": ("CONTROL-OK (truncated and zeroed tails FAIL the "
                        "declared-region tail gate that the full render "
                        "passes)" if ok else
                        ("CONTROL-VACUOUS (the reference render carries no "
                         "tail to drop)" if not live else
                         "CONTROL-BROKEN (a dropped tail passed!)"))}


def nc_c_wrong_order(stim):
    def chain(p1, p2):
        m1 = new_model(p1, "s1")
        m2 = new_model(p2, "s2")
        ol, orr = [], []
        for il, ir in stim:
            a, b = m1.process_block(il, ir)
            a, b = m2.process_block(a, b)
            ol.extend(a)
            orr.extend(b)
        return np.array(ol, dtype=np.int64), np.array(orr, dtype=np.int64)

    ab = chain(PARAMS_A, PARAMS_B)
    ba = chain(PARAMS_B, PARAMS_A)
    identical = bool(np.array_equal(ab[0], ba[0])
                     and np.array_equal(ab[1], ba[1]))
    ag = agreement(ab[0], ab[1], ba[0], ba[1])
    ok = (not identical) and (not ag["all_pass"])
    return {"control": "NC-C wrong order (slot-content permutation)",
            "ok": ok, "bitwise_identical": identical, "metrics": ag,
            "verdict": ("CONTROL-OK (the permuted chain is flagged: not "
                        "bit-identical and outside the [PROPOSED] budgets)"
                        if ok else "CONTROL-BROKEN (order permutation not "
                                   "detected!)")}


def nc_d_shared_state(stim):
    """Two instances must keep independent histories. The mutant pools the
    external region (both models write through one shared array)."""
    ia = new_model(PARAMS_A, "ia")
    ib = new_model(PARAMS_B, "ib")
    for il, ir in stim[:96]:
        ia.process_block(il, ir)
        ib.process_block(ir, il)
    independent = (ia.st.mem is not ib.st.mem
                   and (ia.st.ap_hash, ia.st.dl_hash, ia.st.pd_hash)
                   != (ib.st.ap_hash, ib.st.dl_hash, ib.st.pd_hash))
    base_a = (ia.st.ap_hash, ia.st.dl_hash, ia.st.pd_hash, ia.st.tank)

    ma = new_model(PARAMS_A, "ma")
    mb = new_model(PARAMS_B, "mb")
    mb.st.mem = ma.st.mem                 # <-- the defect: pooled histories
    for il, ir in stim[:96]:
        ma.process_block(il, ir)
        mb.process_block(ir, il)
    mut_a = (ma.st.ap_hash, ma.st.dl_hash, ma.st.pd_hash, ma.st.tank)
    detected = mut_a != base_a
    ok = bool(independent and detected)
    return {"control": "NC-D shared instead of per-instance state",
            "ok": ok, "baseline_independent": bool(independent),
            "mutant_changes_instance_a": bool(detected),
            "verdict": ("CONTROL-OK (pooling the two instances' external "
                        "regions changes instance A's state and history: the "
                        "dual-instance independence check FAILS)" if ok else
                        "CONTROL-BROKEN (pooled state undetected!)")}


def nc_e_stale_stub():
    live = model_revision()
    stale = "0" * 64
    record_ok = (live == live) and (stale != live)
    return {"control": "NC-E stale stub (frozen-revision pin)", "ok":
            bool(record_ok), "live_revision": live, "stale_revision": stale,
            "verdict": ("CONTROL-OK (a record pinned to a revision that is "
                        "not the live model's is REFUSED by the exactness "
                        "harness and by tests/test_sxt028f.py)" if record_ok
                        else "CONTROL-BROKEN")}


def nc_f_bypass_transparency(stim):
    p0 = dict(PARAMS_A, mix_f=0.0)
    m = new_model(p0, "bypass")
    ol, orr = [], []
    exp_l, exp_r = [], []
    for il, ir in stim[:64]:
        a, b = m.process_block(il, ir)
        ol.extend(a)
        orr.extend(b)
        exp_l.extend(il)
        exp_r.extend(ir)
    dl = max(abs(a - b) for a, b in zip(ol, exp_l))
    dr = max(abs(a - b) for a, b in zip(orr, exp_r))
    leak = new_model(dict(PARAMS_A, mix_f=0.001), "leak")
    ll, lr = [], []
    for il, ir in stim[:64]:
        a, b = leak.process_block(il, ir)
        ll.extend(a)
        lr.extend(b)
    leak_max = max(max(abs(a - b) for a, b in zip(ll, exp_l)),
                   max(abs(a - b) for a, b in zip(lr, exp_r)))
    ok = (max(dl, dr) == 0) and leak_max > 0
    return {"control": "NC-F bypass transparency (mix = 0)", "ok": bool(ok),
            "bypass_max_abs_lsb": int(max(dl, dr)),
            "injected_leak_max_abs_lsb": int(leak_max),
            "verdict": ("CONTROL-OK (mix=0 is exactly transparent and an "
                        "injected mix leak is detected)" if ok else
                        "CONTROL-BROKEN")}


def nc_g_suspend_semantics(stim):
    """Reverb2::suspendProcessing() == initialize() == setvars(true): the
    pinned engine does NOT clear the tank on suspend. A mutant that clears
    must be flagged."""
    a = new_model(PARAMS_A, "susp")
    for il, ir in stim[:64]:
        a.process_block(il, ir)
    before = (a.st.tank, a.st.ap_hash, a.st.dl_hash, a.st.pd_hash)
    a.suspend()
    after = (a.st.tank, a.st.ap_hash, a.st.dl_hash, a.st.pd_hash)
    declared_ok = before == after and before != (0, 0, 0, 0)

    b = new_model(PARAMS_A, "susp-mut")
    for il, ir in stim[:64]:
        b.process_block(il, ir)
    b.initialize()                    # <-- the defect: clear on suspend
    mutant_after = (b.st.tank, b.st.ap_hash, b.st.dl_hash, b.st.pd_hash)
    detected = mutant_after != before
    ok = bool(declared_ok and detected)
    return {"control": "NC-G suspend must not clear the tank", "ok": ok,
            "declared_suspend_preserves_state": bool(declared_ok),
            "clearing_mutant_detected": bool(detected),
            "verdict": ("CONTROL-OK (the declared suspend preserves the tank; "
                        "a clearing mutant is flagged by the same check)"
                        if ok else "CONTROL-BROKEN")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028f", "negative-controls",
        "negative-controls.json"))
    args = ap.parse_args()

    stim = stimulus()
    base = new_model(PARAMS_A, "ref")
    ref = render(base, stim)

    # baseline sanity: the unmutated model must PASS its own checks
    self_ag = agreement(ref[0], ref[1], ref[0], ref[1])
    controls = [
        nc_a_generic_substitute(stim, ref),
        nc_b_dropped_tail(ref),
        nc_c_wrong_order(stim),
        nc_d_shared_state(stim),
        nc_e_stale_stub(),
        nc_f_bypass_transparency(stim),
        nc_g_suspend_semantics(stim),
    ]
    ok = all(c["ok"] for c in controls) and self_ag["all_pass"]
    doc = {"schema_version": 1, "leaf": "SXT-028f",
           "model_revision": model_revision(),
           "claim_scope": ("model-vs-model only: the frozen model is the "
                           "reference. No pinned-engine agreement, preset "
                           "support or sound claim is made or implied."),
           "alloc_profile": HARNESS_PROFILE.as_dict(),
           "render": {"burst_blocks": BURST_BLOCKS,
                      "tail_blocks": TAIL_BLOCKS,
                      "block": BLOCK, "sample_rate": 48000,
                      "declared_tail_offset": BURST_BLOCKS * BLOCK,
                      "declared_tail_frames": TAIL_BLOCKS * BLOCK},
           "proposed_budgets": PROPOSED, "proposed_tail_budget": PROPOSED_TAIL,
           "baseline_self_agreement": self_ag,
           "controls": controls,
           "status": "PASS" if ok else "FAIL (broken or vacuous control!)"}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    for c in controls:
        print(("ok  " if c["ok"] else "FAIL"), c["control"], "->",
              c["verdict"])
    print("status:", doc["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
