#!/usr/bin/env python3
"""SXT-028a negative controls: each control must DEMONSTRABLY FAIL the check
it targets; a control that passes is a broken control (finding).

NC-A  generic substitute: a generic Schroeder-style reverb (deliberately
      convenient, implemented inline here, committed NOWHERE as a model)
      driven by the same tapped input must FAIL the same [PROPOSED]
      slot-boundary budgets - adapted != supported.
NC-B  dropped tail: the model render truncated before the declared tail span
      must FAIL the tail-region agreement check.
NC-C  wrong order: two serial AW-49 instances (different params) rendered
      A->B vs B->A - the order-sensitive equality check must flag the
      permutation (outputs differ).
NC-D  stale stub: a trace whose frozen-revision word does not match the
      model file must be REFUSED by the comparator (never reported PASS).
NC-E  conditioning sensitivity: the model driven WITHOUT the tapped vibrato
      control-plane trajectory (self-derived from static params) must FAIL
      the slot-boundary budgets - proves the tapped conditioning is
      load-bearing, not decorative.

Exits 0 iff every control fails the check it targets.
Original to this repository (Apache-2.0).
"""

import hashlib
import json
import math
import os
import shutil
import tempfile
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-49"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import galactic_model as gm  # noqa: E402
import compare_rtl_model_aw49 as cr  # noqa: E402
from compare_aw49_reference import PROPOSED  # noqa: E402  (single source)

OUT = os.path.join(REPO, "reports", "sxt-028a", "negative-controls")
CANONICAL_NPZ = os.path.join(REPO, "reports", "sxt-028a", "fixtures",
                             "temple__seq-notes-coverage-v1-aw49-taps.npz")


def load_canonical(n_blocks=512):
    npz = np.load(CANONICAL_NPZ)
    gal_in = npz["gal_in"][:n_blocks]
    gal_out = npz["gal_out"][:n_blocks]
    vib = npz["vibM"][:n_blocks * 32]
    return gal_in, gal_out, vib


def temple_ctrl():
    fx = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs",
                                     "aw-49-temple.json")))
    g = next(e for e in fx["chain"] if e["type"] == 14 and e["aw"] == 49)["galactic"]
    return gm.build_control(
        {"a": g["A_replace_f"], "b": g["B_brightness_f"],
         "c": g["C_modulation_f"], "d": g["D_size_f"], "e": g["E_mix_f"]},
        {"fpdL": 0, "fpdR": 0})


def run_model(ctrl, vib, gal_in):
    m = gm.Galactic49Fixed(ctrl, vib=vib)
    n = len(gal_in)
    out = np.zeros((n, 32, 2), dtype=np.float32)
    for b in range(n):
        bl = [gm.f32_to_s32i(x) for x in gal_in[b, :, 0]]
        br = [gm.f32_to_s32i(x) for x in gal_in[b, :, 1]]
        ol, orr = m.process_block(bl, br)
        out[b, :, 0] = [gm.s32i_to_f32(v) for v in ol]
        out[b, :, 1] = [gm.s32i_to_f32(v) for v in orr]
    return out


def metrics(ref, mod):
    d = np.abs(ref.astype(np.float64) - mod.astype(np.float64)).reshape(-1)
    r = ref.astype(np.float64).reshape(-1)
    m = mod.astype(np.float64).reshape(-1)
    rms_ref = float(np.sqrt((r * r).mean())) or 1e-30
    rms_abs = float(np.sqrt(((r - m) ** 2).mean()))
    return {"max_abs_diff": float(d.max()),
            "rms_rel_db": float(20 * math.log10(max(rms_abs / rms_ref, 1e-30)))}


def budget_fail(m):
    """True when the [PROPOSED] budgets are VIOLATED (the check fails)."""
    return (m["max_abs_diff"] > PROPOSED["max_abs_diff"]
            or m["rms_rel_db"] > PROPOSED["rms_rel_db"])


def nc_generic_substitute(ctrl, gal_in, ref):
    """NC-A: generic Schroeder 4-comb/2-allpass reverb, same boundary."""
    def comb(x, d, g):
        y = np.zeros_like(x)
        buf = np.zeros(d)
        for i, v in enumerate(x):
            t = v + g * buf[i % d]
            buf[i % d] = t
            y[i] = buf[i % d]
        return y

    def allpass(x, d, g):
        y = np.zeros_like(x)
        buf = np.zeros(d)
        for i, v in enumerate(x):
            xi = v + g * buf[i % d]
            y[i] = -g * xi + buf[i % d]
            buf[i % d] = xi
        return y

    L = gal_in[:, :, 0].reshape(-1).astype(np.float64)
    R = gal_in[:, :, 1].reshape(-1).astype(np.float64)
    wl = sum(comb(L, d, 0.77) for d in (1687, 1601, 2053, 2251)) / 4
    wr = sum(comb(R, d, 0.77) for d in (1699, 1607, 2063, 2255)) / 4
    wl = allpass(wl, 347, 0.5)
    wl = allpass(wl, 113, 0.5)
    wr = allpass(wr, 349, 0.5)
    wr = allpass(wr, 109, 0.5)
    mod = np.stack([wl, wr], axis=1).reshape(len(gal_in), 32, 2) \
        .astype(np.float32)
    m = metrics(ref, mod)
    fails = budget_fail(m)
    return {"control": "NC-A generic substitute",
            "metrics": m, "budgets": PROPOSED,
            "verdict": "CONTROL-OK (generic substitute FAILS the reference "
                       "budgets; adapted != supported)" if fails
                       else "CONTROL-BROKEN (generic substitute PASSED!)",
            "ok": fails}


def nc_dropped_tail(ctrl, gal_in, ref):
    """NC-B: truncate before the declared tail span -> tail check fails."""
    n = len(gal_in)
    vib = gm.TappedVibratoStream(None, np.load(CANONICAL_NPZ)["vibM"][:n * 32])
    full = run_model(ctrl, vib, gal_in)
    tail_blocks = int(2.0 * 48000) // 32     # the last 2 s are tail
    ref_tail = ref[-tail_blocks:].astype(np.float64)
    # truncated model render: drop the final tail blocks entirely
    trunc = full[:-tail_blocks]
    if len(trunc) < tail_blocks:
        trunc = full[:1]
    mod_tail = trunc[-tail_blocks:].astype(np.float64)
    d = np.abs(ref_tail - mod_tail)
    rms_abs = float(np.sqrt((d * d).mean()))
    rms_ref = float(np.sqrt((ref_tail * ref_tail).mean())) or 1e-30
    rms_rel = float(20 * math.log10(max(rms_abs / rms_ref, 1e-30)))
    fails = rms_rel > PROPOSED["rms_rel_db"]
    return {"control": "NC-B dropped tail",
            "metrics": {"tail_rms_rel_db": rms_rel,
                        "budget_rms_rel_db": PROPOSED["rms_rel_db"]},
            "verdict": ("CONTROL-OK (truncated render FAILS the tail check)"
                        if fails else
                        "CONTROL-BROKEN (truncation NOT detected!)"),
            "ok": fails}


def nc_wrong_order(ctrl):
    """NC-C: two serial instances A->B vs B->A must differ (order matters)."""
    ca = gm.build_control({"a": 0.2, "b": 0.7, "c": 0.0, "d": 0.8, "e": 1.0},
                          {"fpdL": 11, "fpdR": 22})
    cb = gm.build_control({"a": 0.9, "b": 0.1, "c": 0.0, "d": 1.0, "e": 1.0},
                          {"fpdL": 33, "fpdR": 44})
    rs = np.random.RandomState(5)
    n_blocks = 400   # long enough for both delay networks to fill and for
                     # the ordering of the two networks to be audible
    xs = [list(map(int, rs.randint(-(1 << 24), 1 << 24, 32)))
          for _ in range(n_blocks)]
    xa = gm.Galactic49Fixed(ca)
    xb = gm.Galactic49Fixed(cb)
    ab = []
    for blk in xs:
        o1 = xa.process_block(blk, blk)
        ab.append(xb.process_block(*o1))
    xa2 = gm.Galactic49Fixed(ca)
    xb2 = gm.Galactic49Fixed(cb)
    ba = []
    for blk in xs:
        o1 = xb2.process_block(blk, blk)
        ba.append(xa2.process_block(*o1))
    differ = ab != ba
    diff_blocks = 0
    if not differ:
        diff_blocks = 0
    else:
        diff_blocks = sum(1 for (a, b) in zip(ab, ba) if a != b)
    return {"control": "NC-C wrong order (A->B vs B->A serial permutation)",
            "metrics": {"blocks_different": diff_blocks,
                        "blocks_total": n_blocks},
            "verdict": ("CONTROL-OK (order-sensitive check flags the "
                        "permutation)" if differ else
                        "CONTROL-BROKEN (permutation undetected!)"),
            "ok": bool(differ)}


def nc_stale_stub():
    """NC-D: a trace whose frozen-revision word does not match the model file
    must be REFUSED by the real comparator (exact=False, never PASS)."""
    ctrl = temple_ctrl()
    rev = int(gm.frozen_revision()[:8], 16)
    stale_rev = rev ^ 0xDEAD
    model_trace = f"R {stale_rev}\nT 0 1\nO 0 0\n"
    wd = tempfile.mkdtemp(prefix="aw49-nc-stale-")
    os.makedirs(os.path.join(wd, "out/aw-49/rtl"), exist_ok=True)
    with open(os.path.join(wd, "out/aw-49/rtl/tb_trace.txt"), "w") as f:
        f.write(model_trace)
    with open(os.path.join(wd, "out/aw-49/rtl/txn_rtl.txt"), "w") as f:
        pass
    res = cr.compare_case("nc-stale-stub", model_trace, [], None, wd, False)
    shutil.rmtree(wd, ignore_errors=True)
    ok = (res["exact"] is False
          and res["revision_pin"]["ok"] is False
          and res["revision_pin"]["rtl_trace"] == stale_rev)
    return {"control": "NC-D stale stub (frozen-revision pin)",
            "metrics": {"trace_revision": stale_rev,
                        "expected_revision": rev,
                        "comparator_exact": res["exact"],
                        "revision_pin_ok": res["revision_pin"]["ok"]},
            "verdict": ("CONTROL-OK (stale trace revision REFUSED - the "
                        "comparator cannot report PASS)" if ok else
                        "CONTROL-BROKEN (stale trace accepted!)"),
            "ok": ok}


def nc_conditioning_sensitivity(ctrl, gal_in, ref):
    """NC-E: model WITHOUT the tapped vibrato trajectory must fail budgets."""
    vib = gm.VibratoStream(ctrl)   # self-derived from static params + fpd(0)
    mod = run_model(ctrl, vib, gal_in)
    m = metrics(ref, mod)
    fails = budget_fail(m)
    return {"control": "NC-E conditioning sensitivity (no tapped vibM)",
            "metrics": m,
            "verdict": ("CONTROL-OK (unconditioned model FAILS the budgets - "
                        "the tapped control plane is load-bearing)" if fails
                        else "CONTROL-BROKEN (conditioning not exercised!)"),
            "ok": fails}


def main():
    os.makedirs(OUT, exist_ok=True)
    gal_in, ref, vibM = load_canonical(512)
    ctrl = temple_ctrl()
    results = []

    vib = gm.TappedVibratoStream(None, np.load(CANONICAL_NPZ)["vibM"][:512 * 32])
    base = run_model(ctrl, vib, gal_in)
    base_m = metrics(ref.astype(np.float32), base)
    print("baseline (sanity):", base_m)
    assert not budget_fail(base_m), "baseline must pass; controls meaningless"

    # active region only: the first ~400 blocks are the predelay/line fill
    # (both the reference and any substitute are near-silent there, so a
    # comparison over the head would be vacuous)
    results.append(nc_generic_substitute(ctrl, gal_in[400:], ref[400:]))
    results.append(nc_dropped_tail(ctrl, gal_in, ref))
    results.append(nc_wrong_order(ctrl))
    results.append(nc_stale_stub())
    results.append(nc_conditioning_sensitivity(ctrl, gal_in, ref))

    ok = all(r["ok"] for r in results)
    out = {"schema_version": 1, "leaf": "SXT-028a",
           "claim": "negative controls; each must fail the check it targets",
           "baseline_sanity": base_m,
           "controls": results,
           "status": "PASS" if ok else "FAIL (broken control!)"}
    with open(os.path.join(OUT, "negative-controls.json"), "w") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    lines = []
    for r in results:
        lines.append(f"{r['control']}: {r['verdict']}")
    with open(os.path.join(OUT, "negative-controls.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    for l in lines:
        print(l)
    print("status:", out["status"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
