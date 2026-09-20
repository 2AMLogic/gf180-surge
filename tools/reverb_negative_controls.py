#!/usr/bin/env python3
"""SXT-024 negative controls (issue #17 acceptance). Each control must
DEMONSTRABLY FAIL the check it targets; a control that passes is itself a
finding and is reported as such.

  NC-A generic-substitute : a plain Schroeder 4-comb + 2-allpass network at a
          similar decay, driven exactly like the frozen model, must FAIL the
          reference-budget check against the pinned Reverb1 render. This
          proves the check distinguishes Surge's Reverb1 from a convenient
          generic; anything passing it with the generic in place is an
          ADAPTED preset, never a supported one (AGENTS.md).
  NC-B tail-truncation    : the frozen model's wet render with the tail cut
          short must FAIL the tail-continuity check.
  NC-C patch-change/reset : covered by cases reset-midpatch-wet (engine
          loadPatch semantics, no added click) -- see comparison/*.json.
  NC-D word-length underfloor: a reduced-word-length variant of the frozen
          model (storage without headroom/guard: Q1.23, i.e. 24-bit words)
          must FAIL stability (loop saturation) or the reference-budget check.

Transcripts land in reports/sxt-024/negative-controls/. Exit code 0 iff every
control FAILED the check it targets (which is the PASS condition for the
control suite). Original to this repository (Apache-2.0).
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import numpy as np  # noqa: E402

import coefficient_plane as cp  # noqa: E402
import reverb1_fixed as rf  # noqa: E402
import compare_reverb_model as cm  # noqa: E402

TRACES = cm.TRACES
OUT = os.path.join(REPO, "reports", "sxt-024", "negative-controls")


def build_case(case):
    side = json.load(open(os.path.join(TRACES, case + ".json")))
    wet, _ = cm.read_bus(case)
    dry, _ = cm.read_bus(case.replace("wet", "dry"))
    model, c, st = cm.build_model(side)
    send, ret = cm.send_return_gains(st)
    seq = json.load(open(cm.SEQ_COV))
    last_t = max(e["t"] for e in seq["events"] if e["type"] in ("note_on", "note_off"))
    t0 = last_t + 4800
    return model, c, st, wet, dry, send, ret, t0


def nc_a_generic():
    """Generic Schroeder network must FAIL the wet fidelity budget."""
    model, c, st, wet, dry, send, ret, t0 = build_case("preset-notes-coverage-wet")
    n = len(dry[0])
    # drive the generic network with the same send signal; identical
    # send/return wiring; Schroeder comb lengths at 48 kHz, tuned t60 ~ 3.7 s
    # (the preset's nominal decay) so the substitution is as favorable as we
    # can make it.
    gen = rf.SchroederGeneric(t60_s=2.0 ** st["params"]["decaytime"])
    in_l = np.clip(np.round(np.float32(dry[0] * send) * (1 << 23)), 0, 0)  # placeholder
    in_l = np.clip(np.round(np.float32(dry[0] * send) * (1 << 23)), rf.S24_MIN, rf.S24_MAX)
    in_r = np.clip(np.round(np.float32(dry[1] * send) * (1 << 23)), rf.S24_MIN, rf.S24_MAX)
    out_l = np.zeros(n)
    for i in range(n):
        out_l[i] = gen.process((int(in_l[i]) + int(in_r[i])) / (1 << 23)) * ret
    wet_pred_l = np.float32(np.float32(dry[0]) + np.float32(out_l)).astype(np.float64)
    wet_pred_r = np.float32(np.float32(dry[1]) + np.float32(out_l)).astype(np.float64)
    res = cm.check_wet("nc-a-generic-schroeder", (wet[0], wet[1]), (wet_pred_l, wet_pred_r), t0,
                       extra={"generic": "Schroeder 4-comb/2-allpass, t60 matched to 2^decay",
                              "send_gain": send, "return_gain": ret})
    res["target_check"] = "wet_rms_rel / decay_curve / stereo_corr (reference budget)"
    res["verdict"] = ("CONTROL-OK (generic FAILS the reference budget)"
                      if not all(res["checks"][k] for k in
                                 ("wet_rms_rel", "decay_curve", "stereo_corr"))
                      else "CONTROL-BROKEN (generic PASSED the budget -- finding!)")
    return res


def nc_b_tail_truncation():
    """Model wet with the last 3 s of tail zeroed must FAIL tail continuity."""
    model, c, st, wet, dry, send, ret, t0 = build_case("preset-notes-coverage-wet")
    n = len(dry[0])
    (pred_l, pred_r), _ = cm.run_model_on_dry(model, dry[0], dry[1], send, ret)
    cut = t0 + 48000  # 1 s into the tail: still above the measurement floor
    pred_l[cut:] = 0.0
    pred_r[cut:] = 0.0
    res = cm.check_wet("nc-b-tail-truncation", (wet[0], wet[1]), (pred_l, pred_r), t0,
                       extra={"truncation_sample": cut,
                              "truncation_note": "tail zeroed 1 s after input stop; the "
                                                 "dropped tail is above the -100 dBFS floor "
                                                 "for several seconds"})
    res["target_check"] = "tail_rms_rel / decay_curve (tail continuity)"
    res["verdict"] = ("CONTROL-OK (truncated tail FAILS tail continuity)"
                      if not (res["checks"]["tail_rms_rel"] and res["checks"]["decay_curve"])
                      else "CONTROL-BROKEN (truncation PASSED -- finding!)")
    return res


def nc_d_word_underfloor():
    """24-bit storage words (Q1.23: zero headroom, audio-LSB grid) must FAIL
    stability or the reference budget. Implemented by re-deriving the model
    with DST_FRAC=23 and no <<IO_SHIFT widening (the historical defective
    configuration that measured -7 dB before the Q4.28 freeze)."""
    side = json.load(open(os.path.join(TRACES, "click-wet.json")))
    wet, _ = cm.read_bus("click-wet")
    dry, _ = cm.read_bus("click-dry")
    st = side["engine_patch_state"]
    deact = side.get("deactivated_flags_raw_fxp") or {}
    send, ret = cm.send_return_gains(st)
    c = cp.build(st["params"], deactivated={"lowcut": deact.get("lowcut", False),
                                            "highcut": deact.get("highcut", False)})

    # reduced-word variant: patch the module constants for this run
    saved = (rf.DST_FRAC, rf.IO_SHIFT)
    rf.DST_FRAC = 23
    rf.IO_SHIFT = 0
    try:
        m = rf.Reverb1Fixed(c, assert_width=False)
        n = len(dry[0])
        in_l = [int(v) for v in np.clip(np.round(np.float32(dry[0] * send) * (1 << 23)),
                                        rf.S24_MIN, rf.S24_MAX)]
        in_r = [int(v) for v in np.clip(np.round(np.float32(dry[1] * send) * (1 << 23)),
                                        rf.S24_MIN, rf.S24_MAX)]
        outs = []
        peak_state = 0
        for k in range(0, n, rf.BLOCK):
            ol, orr = m.process_block(in_l[k:k+32], in_r[k:k+32])
            outs += [rf.sat(v, rf.S24_MIN, rf.S24_MAX) for v in ol]
            peak_state = max(peak_state, max(abs(v) for v in m.out_tap))
        mod = np.array(outs, dtype=np.float64) / (1 << 23) * ret
        full = dry[0] + mod
        err = full - wet[0]
        res = {
            "case": "nc-d-word-underfloor",
            "variant": "24-bit storage words (Q1.23): no integer headroom, "
                       "audio-LSB state grid (the underfloor of the frozen Q4.28)",
            "peak_internal_state_q1_23_units": peak_state / (1 << 23),
            "state_headroom_exceeded": bool(peak_state > (1 << 23) - 1),
            "wet_max_abs": float(np.max(np.abs(err))),
            "wet_rms_rel_db": float(10 * np.log10(np.sqrt(np.mean(err ** 2)) /
                                                  (np.sqrt(np.mean(wet[0] ** 2)) + 1e-30) + 1e-30)),
            "budgets": {"wet_max_abs": cm.BUDGETS["wet_max_abs"],
                        "wet_rms_rel_db": cm.BUDGETS["wet_rms_rel_db"]},
        }
        fails_budget = (res["wet_max_abs"] > cm.BUDGETS["wet_max_abs"]
                        or res["wet_rms_rel_db"] > cm.BUDGETS["wet_rms_rel_db"])
        res["target_check"] = "fixed-point stability (headroom) or reference budget"
        res["verdict"] = ("CONTROL-OK (reduced words FAIL stability/budget)"
                          if (res["state_headroom_exceeded"] or fails_budget)
                          else "CONTROL-BROKEN (reduced words PASSED -- finding!)")
        return res
    finally:
        rf.DST_FRAC, rf.IO_SHIFT = saved


def main():
    os.makedirs(OUT, exist_ok=True)
    results = []
    for name, fn in (("nc-a-generic-schroeder", nc_a_generic),
                     ("nc-b-tail-truncation", nc_b_tail_truncation),
                     ("nc-d-word-underfloor", nc_d_word_underfloor)):
        res = fn()
        path = os.path.join(OUT, name + ".json")
        with open(path, "w") as f:
            json.dump(res, f, indent=2, sort_keys=True, default=float)
            f.write("\n")
        results.append(res)
        print(f"{name}: {res['verdict']}")
        print(f"  details -> {os.path.relpath(path, REPO)}")
    ok = all("CONTROL-OK" in r["verdict"] for r in results)
    print("SUITE:", "PASS (all controls failed their target checks)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
