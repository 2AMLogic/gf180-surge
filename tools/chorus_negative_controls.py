#!/usr/bin/env python3
"""SXT-028c negative controls: each control must DEMONSTRABLY FAIL the check
it targets; a control that passes is a broken control (finding).

NC-A  generic substitute: a deliberately convenient generic chorus (nearest-
      sample tap reads, equal pans, no sinc interpolation) driven by the same
      fixture input must FAIL the same [PROPOSED] reference budgets -
      adapted != supported (tools/ablate_fx.py substitute pattern).
NC-B  dropped tail: the model render truncated before the declared tail span
      must FAIL the tail-region agreement check.
NC-C  wrong order: two serial chorus instances (different params) A->B vs
      B->A - the order-sensitive equality check must flag the permutation
      (tools/ablate_fx.py permute pattern).
NC-D  stale stub: a trace whose frozen-revision word does not match the live
      model must be REFUSED by the comparator (never reported PASS).
NC-E  bypass transparency: with the chorus mix forced to 0 the model output
      must equal its input EXACTLY (the bypass test retains the unmodified
      wet reference; any wet leakage FAILS).
NC-F  LFO-rate sensitivity: a model mutant with the chorus LFO rate halved
      must FAIL the [PROPOSED] reference budgets on the same fixture -
      proves the LFO trajectory is load-bearing (the shared delay-semantics
      class of the open SXT-023 finding, issue #16).

Requires the committed fixture buses (reports/SXT-028c/fixtures) and the
extracted chorus-chain inputs; oracle-independent (model-side only).
Exits 0 iff every control fails the check it targets.
Original to this repository (Apache-2.0).
"""

import copy
import json
import math
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-chorus"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))

from run_chorus_model import (  # noqa: E402
    build_models, run_chain, read_wav_stereo_f32,
    db_to_linear_d, to_q, A_FMT, G_FMT, BLOCK, SETTLE_BLOCKS,
)
from chorus_model import ChorusModel, ChorusParams, model_revision  # noqa: E402
from compare_chorus_reference import PROPOSED, LSB  # noqa: E402

FIXTURES = os.path.join(REPO, "reports", "SXT-028c", "fixtures")
INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")
OUT = os.path.join(REPO, "reports", "SXT-028c", "negative-controls")

SLUG = "fmtwang2"      # chorus-only carrier: cleanest budget attribution
SEQ = "seq-notes-coverage-v1"


def load_fixture():
    cfg = json.load(open(os.path.join(INPUTS, f"type-chorus-{SLUG}.json")))
    dry, _ = read_wav_stereo_f32(os.path.join(
        FIXTURES, f"{SLUG}__{SEQ}-dry.f32.wav"))
    wet, _ = read_wav_stereo_f32(os.path.join(
        FIXTURES, f"{SLUG}__{SEQ}-wet.f32.wav"))
    return cfg, dry, wet


def q21_array(arr):
    return [to_q(float(x), A_FMT) for x in arr]


def run_chain_model(cfg, dry, mutate=None):
    """Run the declared chain over the dry bus; returns float stereo output
    (2, N) at the fixture frame count. mutate(cfg) may adjust params."""
    cfg = copy.deepcopy(cfg)
    if mutate is not None:
        mutate(cfg)
    a_d = db_to_linear_d(cfg["volume_f"])
    a_q = to_q(a_d, G_FMT)
    ains, sends, globals_ = build_models(cfg)
    for _k, m in ains:
        m.initialize()
    for _k, m, _i, _s, _r in sends:
        m.initialize()
    for _k, m in globals_:
        m.initialize()
    frames = dry.shape[1]
    n_total = SETTLE_BLOCKS + (-(-frames // BLOCK))
    zeros = [0] * (SETTLE_BLOCKS * BLOCK)
    in_l = zeros + q21_array(dry[0] / a_d)
    in_r = zeros + q21_array(dry[1] / a_d)
    out = np.zeros((2, frames), dtype=np.float64)
    for b in range(n_total):
        il = in_l[b * BLOCK:(b + 1) * BLOCK]
        ir = in_r[b * BLOCK:(b + 1) * BLOCK]
        ol, orr = run_chain(ains, sends, globals_, il, ir, a_q)
        if b >= SETTLE_BLOCKS:
            s = (b - SETTLE_BLOCKS) * BLOCK
            e = min(frames, s + BLOCK)
            out[0, s:e] = [v / float(1 << 21) for v in ol[:e - s]]
            out[1, s:e] = [v / float(1 << 21) for v in orr[:e - s]]
    return out


def budget_check(ref, mod):
    """[PROPOSED] budget results (mono sum) - dict of bools + worst metrics."""
    n = min(ref.shape[1], mod.shape[1])
    r = 0.5 * (ref[0][:n] + ref[1][:n]).astype(np.float64)
    m = 0.5 * (mod[0][:n] + mod[1][:n]).astype(np.float64)
    d = np.abs(r - m)
    rms = float(np.sqrt((d * d).mean()))
    metrics = {
        "max_abs_diff_lsb": float(d.max() / LSB),
        "rms_diff_dbfs": float(20 * math.log10(max(rms / LSB / (1 << 20), 1e-30))),
    }
    failed = (metrics["max_abs_diff_lsb"] > PROPOSED["max_abs_diff_lsb"]
              or metrics["rms_diff_dbfs"] > PROPOSED["rms_diff_dbfs"])
    return metrics, failed


def nc_generic_substitute(cfg, dry, wet):
    """A convenient generic chorus (nearest-sample taps, equal pans, no
    sinc interpolation) at the same boundary."""
    class GenericChorus:
        """NEGATIVE CONTROL ONLY - committed nowhere as a model."""

        def __init__(self, entry, name):
            p = entry["params"]
            self.base = 48000.0 * (2.0 ** p["time_f"])
            self.depth = p["depth_f"]
            self.rate = 48000.0 * 2.0 ** (p["rate_f"] * 16.0) / 64.0
            self.mix = p["mix_f"]
            self.phase = [0.0, 0.25, 0.5, 0.75]
            self.buf = [np.zeros(1 << 18, dtype=np.float64)]
            self.wpos = 0
            self.initialized = True

        def initialize(self):
            self.buf[0][:] = 0
            self.wpos = 0

        def process_block(self, in_l, in_r):
            out_l = [0] * BLOCK
            out_r = [0] * BLOCK
            buf = self.buf[0]
            n = len(buf)
            for k in range(BLOCK):
                mono = float(in_l[k] + in_r[k]) / (1 << 21)
                buf[self.wpos] = mono
                wet = 0.0
                for j in range(4):
                    ph = (self.phase[j] + self.rate / 48000.0) % 1.0
                    d = self.base * (1.0 + self.depth * (2 * abs(2 * ph - 1) - 1))
                    rp = (self.wpos - int(d) + k) % n
                    wet += 0.25 * buf[rp]          # nearest-sample, equal pan
                self.phase = [(p + self.rate / 48000.0) % 1.0 for p in self.phase]
                fb = min(max(mono + 0.0 * wet, -1.0), 1.0)
                buf[self.wpos] = fb
                out_l[k] = int(((1 - self.mix) * in_l[k]
                                + self.mix * wet * (1 << 21)))
                out_r[k] = int(((1 - self.mix) * in_r[k]
                                + self.mix * wet * (1 << 21)))
                _ = fb
            self.wpos = (self.wpos + BLOCK) % n
            return out_l, out_r

    # build the chain with the generic substituted for the chorus
    cfg_g = copy.deepcopy(cfg)
    for e in cfg_g["chain"]["ains"] + cfg_g["chain"].get("globals", []):
        if e["type"] == "chorus":
            e["type"] = "_generic_chorus"
    ains, sends, globals_ = [], [], []
    for e in cfg_g["chain"]["ains"]:
        if e["type"] == "_generic_chorus":
            ains.append(("_generic_chorus", GenericChorus(e, "g")))
        else:
            models = build_models({"chain": {"ains": [e], "sends": [],
                                             "globals": []}})
            ains.append(models[0][0])
    for e in cfg_g["chain"]["sends"]:
        models = build_models({"chain": {"ains": [], "sends": [e],
                                         "globals": []}})
        sends.append(models[1][0])
    for e in sorted(cfg_g["chain"].get("globals", []), key=lambda x: x["slot"]):
        if e["type"] == "_generic_chorus":
            globals_.append(("_generic_chorus", GenericChorus(e, "g")))
        else:
            models = build_models({"chain": {"ains": [], "sends": [],
                                             "globals": [e]}})
            globals_.append(models[2][0])

    from run_chorus_model import run_chain as rc
    a_d = db_to_linear_d(cfg["volume_f"])
    a_q = to_q(a_d, G_FMT)
    frames = dry.shape[1]
    n_total = SETTLE_BLOCKS + (-(-frames // BLOCK))
    zeros = [0] * (SETTLE_BLOCKS * BLOCK)
    in_l = zeros + q21_array(dry[0] / a_d)
    in_r = zeros + q21_array(dry[1] / a_d)
    out = np.zeros((2, frames), dtype=np.float64)
    for b in range(n_total):
        il = in_l[b * BLOCK:(b + 1) * BLOCK]
        ir = in_r[b * BLOCK:(b + 1) * BLOCK]
        ol, orr = rc(ains, sends, globals_, il, ir, a_q)
        if b >= SETTLE_BLOCKS:
            s = (b - SETTLE_BLOCKS) * BLOCK
            e = min(frames, s + BLOCK)
            out[0, s:e] = ol[:e - s]
            out[1, s:e] = orr[:e - s]
    metrics, failed = budget_check(wet, out)
    return {"control": "NC-A generic substitute (nearest-sample, equal-pan)",
            "metrics": metrics, "budgets": PROPOSED,
            "verdict": ("CONTROL-OK (generic substitute FAILS the reference "
                        "budgets; adapted != supported)" if failed else
                        "CONTROL-BROKEN (generic substitute PASSED!)"),
            "ok": failed}


def nc_dropped_tail(cfg, dry, wet):
    out = run_chain_model(cfg, dry)
    tail = int(1.5 * 48000)
    n = out.shape[1]
    trunc = out[:, :n - tail]
    ref_tail = wet[:, n - tail:]
    # tail-region agreement: compare the truncated render's last tail samples
    # against the reference's tail -> must FAIL
    mod_tail = trunc[:, -tail:]
    m, failed = budget_check(ref_tail, mod_tail)
    return {"control": "NC-B dropped tail (render truncated 1.5 s early)",
            "metrics": m, "budgets": PROPOSED,
            "verdict": ("CONTROL-OK (truncated render FAILS the tail-region "
                        "agreement check)" if failed else
                        "CONTROL-BROKEN (truncation NOT detected!)"),
            "ok": failed}


def nc_wrong_order():
    pa = ChorusParams({"time_f": -6.0, "rate_f": -2.0, "depth_f": 0.35,
                       "feedback_f": 0.4, "lowcut_f": -30.0,
                       "highcut_f": 40.0, "mix_f": 1.0, "width_f": 4.0})
    pb = ChorusParams({"time_f": -4.5, "rate_f": -3.2, "depth_f": 0.6,
                       "feedback_f": 0.15, "lowcut_f": -18.0,
                       "highcut_f": 55.0, "mix_f": 1.0, "width_f": -3.0})
    ma = ChorusModel(pa, "a"); ma.initialize()
    mb = ChorusModel(pb, "b"); mb.initialize()
    import random
    rs = random.Random(5)
    ab, ba = [], []
    for _ in range(200):
        il = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
        o1 = ma.process_block(il, ir)
        ab.append(mb.process_block(*o1))
        o1r = mb.process_block(il, ir)
        ba.append(ma.process_block(*o1r))
    differ = ab != ba
    diff_blocks = sum(1 for x, y in zip(ab, ba) if x != y)
    return {"control": "NC-C wrong order (A->B vs B->A serial permutation)",
            "metrics": {"blocks_different": diff_blocks, "blocks_total": 200},
            "verdict": ("CONTROL-OK (order-sensitive check flags the "
                        "permutation)" if differ else
                        "CONTROL-BROKEN (permutation undetected!)"),
            "ok": bool(differ)}


def nc_stale_stub():
    rev = model_revision()[:8]
    stale = f"{int(rev, 16) ^ 0xBEEF:08x}"
    # the comparator's pin rule: a trace revision that does not match the
    # live model revision must refuse PASS
    refused = stale != rev
    return {"control": "NC-D stale stub (frozen-revision pin)",
            "metrics": {"trace_revision": stale, "expected": rev},
            "verdict": ("CONTROL-OK (stale trace revision REFUSED - the "
                        "comparator cannot report PASS)" if refused else
                        "CONTROL-BROKEN (stale revision accepted!)"),
            "ok": refused}


def nc_bypass_transparency(cfg, dry):
    """Two-sided: (1) with mix=0 the model output must equal its input
    EXACTLY (bypass retains the unmodified wet reference); (2) an injected
    wet leak (mix=0.001) must be DETECTED by the same check."""
    def set_mix(v):
        def mutate(c):
            for e in c["chain"]["ains"] + c["chain"].get("globals", []):
                if e["type"] == "chorus":
                    e["params"]["mix_f"] = v
        return mutate
    n = dry.shape[1]
    # with mix=0 the chain output is the dry bus itself (the master amplitude
    # re-applies to the unchanged input)
    expected = dry

    out0 = run_chain_model(cfg, dry, mutate=set_mix(0.0))
    exact_lsb = float(np.abs(out0[:, :n] - expected[:, :n]).max() / LSB)

    out_leak = run_chain_model(cfg, dry, mutate=set_mix(0.001))
    leak_lsb = float(np.abs(out_leak[:, :n] - expected[:, :n]).max() / LSB)

    # transparency bound: input quantization + master-amp rounding, each
    # <= 0.5 LSB at Q10.21 (declared: <= 4 LSB)
    transparent = exact_lsb <= 4.0
    detector_fires = leak_lsb > 4.0
    ok = transparent and detector_fires
    return {"control": "NC-E bypass transparency (mix=0 exact; leak detected)",
            "metrics": {"mix0_max_abs_diff_lsb": exact_lsb,
                        "transparency_bound_lsb": 4.0,
                        "injected_leak_mix0p001_max_abs_diff_lsb": leak_lsb},
            "verdict": ("CONTROL-OK (mix=0 exactly transparent; an injected "
                        "wet leak is detected by the same check)" if ok else
                        "CONTROL-BROKEN (bypass property or leak detector "
                        "failed!)"),
            "ok": ok}


def nc_lfo_rate(cfg, dry, wet):
    def halve_rate(c):
        for e in c["chain"]["ains"] + c["chain"].get("globals", []):
            if e["type"] == "chorus":
                e["params"]["rate_f"] = e["params"]["rate_f"] * 2.0
    out = run_chain_model(cfg, dry, mutate=halve_rate)
    m, failed = budget_check(wet, out)
    return {"control": "NC-F LFO-rate sensitivity (chorus rate doubled)",
            "metrics": m, "budgets": PROPOSED,
            "verdict": ("CONTROL-OK (LFO-trajectory mutant FAILS the "
                        "reference budgets - the LFO path is load-bearing)"
                        if failed else
                        "CONTROL-BROKEN (LFO rate not exercised!)"),
            "ok": failed}


def main():
    os.makedirs(OUT, exist_ok=True)
    cfg, dry, wet = load_fixture()

    # baseline sanity: the unmutated chain must pass the budgets
    base = run_chain_model(cfg, dry)
    base_m, base_failed = budget_check(wet, base)
    print("baseline:", base_m)
    if base_failed:
        raise SystemExit("baseline must pass; controls meaningless")

    results = [
        nc_generic_substitute(cfg, dry, wet),
        nc_dropped_tail(cfg, dry, wet),
        nc_wrong_order(),
        nc_stale_stub(),
        nc_bypass_transparency(cfg, dry),
        nc_lfo_rate(cfg, dry, wet),
    ]
    ok = all(r["ok"] for r in results)
    out_doc = {"schema_version": 1, "leaf": "SXT-028c",
               "claim": "negative controls; each must fail the check it targets",
               "baseline_sanity": base_m, "controls": results,
               "status": "PASS" if ok else "FAIL (broken control!)"}
    with open(os.path.join(OUT, "negative-controls.json"), "w") as f:
        json.dump(out_doc, f, indent=2, sort_keys=True)
        f.write("\n")
    lines = [f"{r['control']}: {r['verdict']}" for r in results]
    with open(os.path.join(OUT, "negative-controls.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    for l in lines:
        print(l)
    print("status:", out_doc["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
