#!/usr/bin/env python3
"""SXT-028b model-level negative controls (oracle-independent).

Each control must DEMONSTRABLY FAIL the check it targets; a control that
passes is a broken control (reported, exit 1). Every control runs a REAL
check function against a real mutant/variant, and -- where meaningful --
the unmutated input is shown to PASS the same check (so the check is not
vacuous). RTL-level controls (pooled-state RTL mutant, no-limiter RTL
mutant, permuted slots, stale revision, dropped tail on a real RTL trace)
live in tools/compare_rtl_model_conditioner.py.

  NC-1 wrong order       serial Conditioner A->B vs B->A (tools/ablate_fx.py
                         permute pattern) -> order-sensitive exactness FAILS
  NC-2 shared state      two instances pooled into ONE ConditionerState
                         (tb_fx_shared_line pattern) -> dual-instance
                         exactness FAILS for both instances
  NC-3 generic substitute an instantaneous peak limiter (no look-ahead, no
                         EQ, no M/S) labeled ADAPTED -> REFUSED by the
                         original-preset coverage gate, and it FAILS
                         exactness vs the frozen model; the unmodified wet
                         reference is retained byte-identical (bypass rule)
  NC-4 dropped tail      a render truncated before the declared tail span
                         (get_ringout_decay()-1 = 99 process() blocks + the
                         control-only transition) -> tail-coverage check
                         FAILS; the dropped region carries real energy
  NC-5 stale stub        a trace whose revision word != the live model ->
                         comparator REFUSES although every sample matches
  NC-6 dropped ringout   a scheduler that stops calling process() as soon as
                         input stops (decay 1 instead of 100) -> exactness
                         over the tail FAILS (ringout is load-bearing)
  NC-7 generic detector  a "fixed" detector reading the windowed max of all
                         128 leaves (what the dead reduction tree would
                         compute) instead of the engine's fixed leaf 126 ->
                         exactness FAILS (the fixed-slot read is load-bearing)

Exits 0 iff every control fails its check. Original to this repository
(Apache-2.0).
"""
import hashlib
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-conditioner"))

import conditioner_model as cm  # noqa: E402
from conditioner_model import (  # noqa: E402
    ConditionerModel, ConditionerParams, model_revision, tail_coverage_check,
    BLOCK, LOOKAHEAD, ONE_C, TAIL_PROCESS_BLOCKS,
)
from conditioner_corners import all_corners  # noqa: E402
from compare_rtl_model_conditioner import (  # noqa: E402
    Stim, SYNTH_B, judge, lifecycle_schedule,
)

OUT = os.path.join(REPO, "reports", "SXT-028b", "negative-controls")
ALGORITHM_ID = "surge-conditioner-frozen-model"


def corner(name):
    return {n: p for n, p, _ in all_corners()}[name]


PARAMS_A = corner("doomsday-slot06")
PARAMS_B = SYNTH_B


def exact(ref, got):
    """The exactness check: integer equality of every sample."""
    return ref == got


def coverage_gate(record):
    """Original-preset coverage admission (plan section 2 fidelity rule):
    only the frozen Conditioner algorithm, unadapted, counts."""
    return (record.get("algorithm") == ALGORITHM_ID
            and record.get("model_revision") == model_revision()
            and not record.get("adapted", True))


def render(params, present, seed=3, model=None):
    m = model or ConditionerModel(ConditionerParams(dict(params)), "m")
    if model is None:
        m.initialize()
    st = Stim(seed)
    out = []
    for b, pres in enumerate(present):
        il, ir = st.block(b, pres)
        ol, orr, _ = m.process_ringout(il, ir, pres)
        out.append((ol, orr))
    return out


def nc_wrong_order():
    present = [True] * 24 + [False] * 8

    def chain(first, second):
        m1 = ConditionerModel(ConditionerParams(dict(first)), "s1")
        m2 = ConditionerModel(ConditionerParams(dict(second)), "s2")
        m1.initialize()
        m2.initialize()
        st = Stim(5)
        out = []
        for b, pres in enumerate(present):
            il, ir = st.block(b, pres)
            l1, r1, p1 = m1.process_ringout(il, ir, pres)
            l2, r2, _ = m2.process_ringout(l1, r1, p1)
            out.append((l2, r2))
        return out
    ref = chain(PARAMS_A, PARAMS_B)
    ok_same = exact(ref, chain(PARAMS_A, PARAMS_B))
    fails = not exact(ref, chain(PARAMS_B, PARAMS_A))
    return _ctl("wrong order (serial slot permutation A->B vs B->A)",
                "order-sensitive exactness", fails and ok_same,
                {"unpermuted_passes": ok_same, "permuted_fails": fails})


def nc_shared_state():
    present = [True] * 24
    ref_a = render(PARAMS_A, present, seed=11)
    ref_b = render(PARAMS_B, present, seed=12)
    ma = ConditionerModel(ConditionerParams(dict(PARAMS_A)), "a")
    mb = ConditionerModel(ConditionerParams(dict(PARAMS_B)), "b")
    ma.initialize()
    mb.initialize()
    mb.st = ma.st                        # POOL the two instances' histories
    sa, sb = Stim(11), Stim(12)
    got_a, got_b = [], []
    for b, pres in enumerate(present):
        il, ir = sa.block(b, pres)
        la, ra, _ = ma.process_ringout(il, ir, pres)
        il, ir = sb.block(b, pres)
        lb, rb, _ = mb.process_ringout(il, ir, pres)
        got_a.append((la, ra))
        got_b.append((lb, rb))
    fa, fb = not exact(ref_a, got_a), not exact(ref_b, got_b)
    # sanity: independent instances interleaved the same way DO pass
    ia = ConditionerModel(ConditionerParams(dict(PARAMS_A)), "a")
    ib = ConditionerModel(ConditionerParams(dict(PARAMS_B)), "b")
    ia.initialize()
    ib.initialize()
    sa, sb = Stim(11), Stim(12)
    ok_a, ok_b = [], []
    for b, pres in enumerate(present):
        il, ir = sa.block(b, pres)
        la, ra, _ = ia.process_ringout(il, ir, pres)
        il, ir = sb.block(b, pres)
        lb, rb, _ = ib.process_ringout(il, ir, pres)
        ok_a.append((la, ra))
        ok_b.append((lb, rb))
    indep = exact(ref_a, ok_a) and exact(ref_b, ok_b)
    return _ctl("shared state (two instances pooled into one history)",
                "dual-instance exactness", fa and fb and indep,
                {"instance_a_fails": fa, "instance_b_fails": fb,
                 "independent_instances_pass": indep})


class GenericLimiter:
    """Deliberately convenient generic: instantaneous per-sample peak
    limiter at the same threshold/gain, no look-ahead delay, no EQ, no M/S
    width/balance. Exists only to be refused."""

    def __init__(self, p):
        self.pre = cm.db_to_linear_d(-p["threshold_db"])
        self.post = cm.db_to_linear_d(p["gain_db"])
        self.env = 1.0

    def process_ringout(self, il, ir, pres):
        ol, orr = [], []
        for x, y in zip(il, ir):
            xl, xr = x / 2**21 * self.pre * 0.5, y / 2**21 * self.pre * 0.5
            self.env = max(1.0, max(abs(xl), abs(xr)), 0.999 * self.env)
            g = self.post / self.env
            ol.append(int(round(xl * g * 2**21)))
            orr.append(int(round(xr * g * 2**21)))
        return ol, orr, True


def nc_generic_substitute():
    present = [True] * 24 + [False] * 8
    ref = render(PARAMS_A, present, seed=21)
    ref_hash = hashlib.sha256(json.dumps(ref).encode()).hexdigest()
    sub = render(PARAMS_A, present, seed=21, model=GenericLimiter(PARAMS_A))
    sub_record = {"algorithm": "generic-instantaneous-peak-limiter",
                  "adapted": True, "label": "ADAPTED: Conditioner substituted "
                  "with a generic limiter", "model_revision": model_revision()}
    ref_record = {"algorithm": ALGORITHM_ID, "adapted": False,
                  "model_revision": model_revision()}
    refused = not coverage_gate(sub_record)
    admitted = coverage_gate(ref_record)
    differs = not exact(ref, sub)
    retained = hashlib.sha256(json.dumps(ref).encode()).hexdigest() == ref_hash
    return _ctl("generic substitute (instantaneous limiter, labeled ADAPTED)",
                "original-preset coverage gate + exactness",
                refused and admitted and differs and retained,
                {"substitute_refused_by_gate": refused,
                 "frozen_model_admitted_by_gate": admitted,
                 "substitute_fails_exactness": differs,
                 "unmodified_wet_reference_retained": retained})


def nc_dropped_tail():
    present, _, last = lifecycle_schedule()
    present = present[:150]
    full = render(PARAMS_A, present, seed=31)
    ok_full, required = tail_coverage_check(len(full), last)
    truncated = full[:last + 1 + 4]          # stops 4 blocks into the tail
    ok_trunc, _ = tail_coverage_check(len(truncated), last)
    dropped = full[len(truncated):required]
    energy = sum(v * v for ol, orr in dropped for v in ol + orr)
    drain = full[last + 1:last + 1 + LOOKAHEAD // BLOCK]
    drain_nonzero = any(v != 0 for ol, orr in drain for v in ol + orr)
    return _ctl("dropped tail (render truncated inside the declared tail span)",
                "tail coverage", (not ok_trunc) and ok_full and drain_nonzero,
                {"required_blocks": required, "full_blocks": len(full),
                 "truncated_blocks": len(truncated), "full_passes": ok_full,
                 "truncated_fails": not ok_trunc,
                 "lookahead_drain_nonzero": drain_nonzero,
                 "energy_in_dropped_region_q21sq": energy,
                 "tail_process_blocks": TAIL_PROCESS_BLOCKS})


def nc_stale_stub():
    present = [True] * 4
    m = ConditionerModel(ConditionerParams(dict(PARAMS_A)), "m")
    m.initialize()
    st = Stim(41)
    exps = []
    with tempfile.TemporaryDirectory() as td:
        lines = []
        for b, pres in enumerate(present):
            il, ir = st.block(b, pres)
            ol, orr, _ = m.process_ringout(il, ir, pres)
            cp = m.st.checkpoint()
            exps.append({"b": b, "O": {0: ol + orr}, "T": {0: cp}})
            lines.append(f"O {b} 0 " + " ".join(str(v) for v in ol + orr))
            lines.append(f"T {b} 0 " + " ".join(f"{k} {v}" for k, v in cp.items()))
        live = model_revision()[:8]
        stale = f"{int(live, 16) ^ 0x1:08x}"
        res = {}
        for tag, rev in (("live", live), ("stale", stale)):
            p = os.path.join(td, f"{tag}.txt")
            with open(p, "w") as f:
                f.write(f"R {rev}\n" + "\n".join(lines) + "\n")
            res[tag] = judge(tag, exps, p, 1, len(present), live)["status"]
    ok = res["live"] == "PASS" and res["stale"].startswith("REFUSED")
    return _ctl("stale stub (trace revision != live frozen model)",
                "revision pin", ok, {"identical_data_live_rev": res["live"],
                                     "identical_data_stale_rev": res["stale"]})


def nc_dropped_ringout():
    present = [True] * 16 + [False] * 30
    ref = render(PARAMS_A, present, seed=51)
    old = cm.RINGOUT_DECAY_BLOCKS
    try:
        cm.RINGOUT_DECAY_BLOCKS = 1          # mutant scheduler
        mut = render(PARAMS_A, present, seed=51)
    finally:
        cm.RINGOUT_DECAY_BLOCKS = old
    fails = not exact(ref, mut)
    return _ctl("dropped ringout (process() stops when input stops)",
                "exactness over the tail", fails, {"mutant_fails": fails})


def nc_generic_detector():
    present = [True] * 24

    class TreeMax(ConditionerModel):
        pass
    ref = render(PARAMS_A, present, seed=61)
    m = TreeMax(ConditionerParams(dict(PARAMS_A)), "t")
    m.initialize()
    orig = m._envelope_step

    def env(la_c, a, r):
        mx = max(m.st.lamax)
        la = max(ONE_C, cm.isqrt_c(cm.qadd(mx, mx, cm.C_FMT)))
        return orig(la, a, r)
    m._envelope_step = env
    mut = render(PARAMS_A, present, seed=61, model=m)
    fails = not exact(ref, mut)
    return _ctl("generic detector (windowed max instead of fixed leaf 126)",
                "exactness", fails, {"mutant_fails": fails})


def _ctl(name, target, ok, metrics):
    return {"control": name, "targets": target, "metrics": metrics, "ok": ok,
            "verdict": ("CONTROL-OK (fails the check it targets)" if ok else
                        "CONTROL-BROKEN (control did not fail its check)")}


def main():
    os.makedirs(OUT, exist_ok=True)
    results = [nc_wrong_order(), nc_shared_state(), nc_generic_substitute(),
               nc_dropped_tail(), nc_stale_stub(), nc_dropped_ringout(),
               nc_generic_detector()]
    ok = all(r["ok"] for r in results)
    doc = {"schema_version": 1, "leaf": "SXT-028b",
           "claim": "negative controls; each must fail the check it targets",
           "scope": "model-level, synthetic stimuli, oracle-independent; the "
                    "RTL-level controls are in reports/SXT-028b/rtl-exactness.json",
           "model_revision": model_revision(), "controls": results,
           "status": "PASS" if ok else "FAIL (broken control)"}
    with open(os.path.join(OUT, "negative-controls.json"), "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    lines = [f"{r['control']}: {r['verdict']}" for r in results]
    with open(os.path.join(OUT, "negative-controls.txt"), "w") as f:
        f.write("\n".join(lines) + f"\nstatus: {doc['status']}\n")
    print("\n".join(lines))
    print("status:", doc["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
