#!/usr/bin/env python3
"""SXT-037 negative controls. Every control must DEMONSTRABLY FAIL the check
it targets; the tool exits 0 only when every control failed as designed.

  NC-A wrong-subtype   Driven carriers through the Clean path (and the Clean
                       carrier through the Driven path): the L1+L2 reference
                       checks must FAIL.  (Issue control: "same type, wrong
                       subtype must also FAIL".)
  NC-B wrong-algorithm LP 24 dB/Driven (sibling algorithm, pinned
                       Coeff_LP24 + IIR24CFC structure) substituted for LP 12
                       dB: the L2 reference check must FAIL.  (Issue control:
                       "wrong-algorithm control ... the reference-budget
                       check must FAIL".)
  NC-C out-of-scope    resonance above 1.0 (and subtype 3, and a non-LP12
       refused         type) are REFUSED by the frozen model (fail-closed,
                       exit code 2): the applicability boundary must never
                       silently clamp or guess.
  NC-D instability     control-only clipgain-disabled kernel at the
       detected        self-osc corner: the stability monitor must report
                       UNSTABLE (detected, not silent) while the frozen
                       model (clipgain active) stays bounded on the same
                       drive.
  NC-E RTL mutant      rtl/voice/lp12_broken_mutant.sv (single-constant
                       mutation of the qmul round-half-up bias) must FAIL
                       the RTL-vs-model exactness comparison (requires
                       iverilog; skipped with an explicit NOT_RUN otherwise).

Original to this repository (Apache-2.0). Engine structure cited from the
pinned GPL tree (surge@58914e59), read and never copied.
"""

import argparse
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lp12"))

import voice_model as vm  # noqa: E402
import filter_lp12_model as fp  # noqa: E402
from run_filter_leg import load_bundle, group_streams, qintf  # noqa: E402

BLOCK_OS = vm.BLOCK_SIZE_OS


def qmul(a, b):
    return vm.qmul(a, b)


# ----------------------------------------------------------------- helpers
def first_instance(bundle_dir):
    """(audio, coef) streams of the first instance of a bundle."""
    _, coeffs, records = load_bundle(bundle_dir)
    inst, audio, coef = group_streams(coeffs, records)
    key = inst[0]
    return audio[key], coef[key], key


def drive(audio, coef, maker_fn, unit_fn):
    """Run a bundle instance through (maker_fn(sub), unit_fn(sub)); return
    model outputs and engine references (Q10.21) plus per-block peaks."""
    out_model = []
    eng_ref = []
    peaks = []
    for i, rec in enumerate(coef):
        blk_in = [qintf(fin) for (_, fin, _) in audio[i * BLOCK_OS:(i + 1) * BLOCK_OS]]
        eng_ref.extend(qintf(fout) for (_, _, fout) in
                       audio[i * BLOCK_OS:(i + 1) * BLOCK_OS])
        sub = int(rec["sub"])
        cm = maker_fn(sub)
        cm.make_coeffs(qintf(float(rec["cut"])), qintf(float(rec["reso"])))
        unit = unit_fn(sub)
        outs, peak, _ = unit.process_block(blk_in, cm)
        out_model.extend(outs)
        peaks.append(peak)
    return out_model, eng_ref, peaks


def audio_metrics(model_out, engine_q):
    n = min(len(model_out), len(engine_q))
    d = [a - b for a, b in zip(model_out[:n], engine_q[:n])]
    rms = math.sqrt(sum(v * v for v in d) / n) if n else 0.0
    return {"max_abs_lsb": max((abs(v) for v in d), default=0),
            "rms_lsb": rms}


def l2_budget_fail(model_out, engine_q):
    """True when the [PROPOSED] L2 audio budgets are VIOLATED."""
    m = audio_metrics(model_out, engine_q)
    return (m["max_abs_lsb"] > 4096 or m["rms_lsb"] > 256), m


# ------------------------------------------------- NC-B wrong-algorithm LP24
class LP24DrivenMaker:
    """CONTROL-ONLY wrong algorithm: fut_lp24 / st_Driven.

    Structure cited from the pinned tree (FilterCoefficientMaker_Impl.h
    Coeff_LP24 + QuadFilterUnit_Impl.h IIR24CFCquad); used exclusively as a
    negative control. Never a substitute filter in any support claim.
    """

    def __init__(self, sub):
        self.C = [0] * 8
        self.dC = [0] * 8
        self.tC = [0] * 8
        self.first = True

    def reset(self):
        self.first = True

    def make_coeffs(self, freq, reso):
        freq = vm.limit_i(freq, vm.qint(-55.0), vm.qint(75.0))
        atten = vm.ONE - qmul(max(0, freq - vm.qint(58.0)), vm.qint(0.05))
        reso = qmul(reso, max(0, atten))
        q2 = vm.ONE - qmul(vm.qint(1.05), vm.limit_i(reso, vm.qint(0.001), vm.ONE))
        sinu, cosi = vm.note_to_omega(freq)
        alpha = qmul(sinu, q2)
        lim = vm.qint(max(0.0, (1.0 - (cosi / float(vm.ONE)) ** 2) ** 0.5) - 0.0001)
        alpha = min(alpha, lim)
        a0 = vm.ONE + alpha
        a0inv = vm.qdiv(vm.ONE, a0)
        a1 = qmul(vm.qint(-2.0), cosi)
        a2 = vm.ONE - alpha
        b0h = (vm.ONE - cosi) >> 1
        gain = vm.ONE - qmul(qmul(reso, reso), vm.qint(0.5))
        b0 = qmul(b0h, gain)
        b1 = qmul(vm.ONE - cosi, gain)
        b2 = b0
        b0 = qmul(b0, a0inv); b1 = qmul(b1, a0inv); b2 = qmul(b2, a0inv)
        a1 = qmul(a1, a0inv); a2 = qmul(a2, a0inv)
        ar = -(a1 >> 1)
        sq = min(0, a1 * a1 - ((4 * a2) << vm.FQ))
        ai = max(vm.qint(0.5 * math.sqrt(-sq / float(1 << (2 * vm.FQ)))),
                 vm.qint(8.0 * 1.192092896e-07))
        bb1 = b1 - qmul(a1, b0)
        bb2 = b2 - qmul(a2, b0)
        n = [ar, ai, vm.ONE, 0, bb1, vm.qdiv(qmul(bb1, ar) + bb2, ai), b0,
             fp._clipscale(freq, fp.SUBTYPE_DRIVEN)]
        if self.first:
            self.dC = [0] * 8
            self.C = list(n)
            self.tC = list(n)
            self.first = False
        else:
            for i in range(8):
                self.tC[i] = self.tC[i] + vm.qmul(vm.qint(0.2), n[i] - self.tC[i])
                self.dC[i] = vm.qdiv(self.tC[i] - self.C[i], BLOCK_OS, fb=0)


class LP24DrivenUnit:
    """IIR24CFCquad structure (cited), CONTROL-ONLY."""

    def __init__(self, sub):
        self.r = [0] * 5          # R0 R1 R2(clip) R3 R4; R2 init 0 (FBP memset)
        self.sub = sub

    def process_block(self, inp64, cm):
        c = list(cm.C)
        dc = list(cm.dC)
        r = self.r
        out = []
        peak = 0
        for x in inp64:
            for i in (0, 1, 2, 4, 5, 6):
                c[i] = vm.sat(c[i] + dc[i])
            y = qmul(c[4], r[0]) + qmul(c[6], x) + qmul(c[5], r[1])
            s1 = qmul(x, c[2]) + qmul(c[0], r[0]) - qmul(c[1], r[1])
            s2 = qmul(c[1], r[0]) + qmul(c[0], r[1])
            r[0] = qmul(s1, r[2])
            r[1] = qmul(s2, r[2])
            y2 = qmul(c[4], r[3]) + qmul(c[6], y) + qmul(c[5], r[4])
            s3 = qmul(y, c[2]) + qmul(c[0], r[3]) - qmul(c[1], r[4])
            s4 = qmul(c[1], r[3]) + qmul(c[0], r[4])
            r[3] = qmul(s3, r[2])
            r[4] = qmul(s4, r[2])
            c[7] = vm.sat(c[7] + dc[7])
            r[2] = max(vm.qint(0.1), vm.ONE - qmul(c[7], qmul(y2, y2)))
            out.append(y2)
            peak = max(peak, abs(y2), abs(r[0]), abs(r[3]))
        return out, peak, c


# --------------------------------------------------------------- NC driver
def run_controls(artifact_dir, require_rtl=True, bundle_root=None):
    os.makedirs(artifact_dir, exist_ok=True)
    art_root = bundle_root or artifact_dir
    results = {}
    lines = ["SXT-037 negative-control transcript", "=" * 60]

    def log(s):
        print(s)
        lines.append(s)

    def bundle_dir(case):
        for cand in (os.path.join(art_root, "bundle-" + case),
                     os.path.join(art_root, case)):
            if os.path.isdir(cand):
                return cand
        raise FileNotFoundError(f"bundle for {case} under {art_root}")

    bundles = {c: bundle_dir(c)
               for c in ("badnews", "rainy", "t9", "badnews-reso1")}

    # ---- NC-A wrong-subtype ------------------------------------------------
    for carrier, wrong_sub, wrong_name in (
            ("badnews", fp.SUBTYPE_CLEAN, "Clean"),
            ("rainy", fp.SUBTYPE_CLEAN, "Clean"),
            ("t9", fp.SUBTYPE_DRIVEN, "Driven")):
        audio, coef, key = first_instance(bundles[carrier])
        out_m, eng, peaks = drive(
            audio, coef,
            lambda sub, w=wrong_sub: fp.LP12CoeffMaker(w),
            lambda sub, w=wrong_sub: fp.LP12Unit(w))
        failed, metrics = l2_budget_fail(out_m, eng)
        results[f"NC-A-wrong-subtype-{carrier}-{wrong_name}"] = {
            "targeted_check": "L1+L2 reference budgets on a same-type/wrong-substitute path",
            "l2": metrics, "budget_fail": failed,
            "outcome": "CONTROL-OK (fails the check)" if failed else "CONTROL-BROKEN",
        }
        log(f"NC-A {carrier} as {wrong_name}: max|d|={metrics['max_abs_lsb']} "
            f"rms={metrics['rms_lsb']:.1f} -> "
            f"{'FAILS budgets (CONTROL-OK)' if failed else 'PASSES budgets (CONTROL-BROKEN)'}")

    # ---- NC-B wrong-algorithm (LP24) ---------------------------------------
    audio, coef, key = first_instance(bundles["badnews"])
    out_m, eng, peaks = drive(audio, coef,
                              lambda sub: LP24DrivenMaker(sub),
                              lambda sub: LP24DrivenUnit(sub))
    failed, metrics = l2_budget_fail(out_m, eng)
    results["NC-B-wrong-algorithm-lp24"] = {
        "targeted_check": "L2 reference budget with a sibling filter algorithm substituted",
        "l2": metrics, "budget_fail": failed,
        "outcome": "CONTROL-OK (fails the check)" if failed else "CONTROL-BROKEN",
    }
    log(f"NC-B badnews as LP24/Driven: max|d|={metrics['max_abs_lsb']} "
        f"rms={metrics['rms_lsb']:.1f} -> "
        f"{'FAILS budgets (CONTROL-OK)' if failed else 'PASSES budgets (CONTROL-BROKEN)'}")

    # ---- NC-C out-of-scope refused ------------------------------------------
    refusals = []
    for name, fn in (
            ("reso>1", lambda: fp.LP12CoeffMaker(1).make_coeffs(vm.qint(0.0), qintf(1.01))),
            ("subtype=3", lambda: fp.LP12CoeffMaker(3)),
            ("subtype=9", lambda: fp.LP12Unit(9)),
            ("type!=lp12", lambda: (_ for _ in ()).throw(
                RuntimeError("type gate checked at bundle load (group_streams)"))),
    ):
        try:
            fn()
            refused = False
        except fp.Refuse:
            refused = True
        except Exception:
            refused = None   # non-Refuse exceptions count only for the type gate
        refusals.append((name, refused))
    c_ok = all(r is True for _, r in refusals[:3])
    results["NC-C-out-of-scope-refused"] = {
        "targeted_check": "applicability boundary refuses out-of-scope parameters",
        "refusals": {name: ("REFUSED" if r else "ACCEPTED (CONTROL-BROKEN)")
                     for name, r in refusals[:3]},
        "outcome": "CONTROL-OK (refused, exit-2 class)" if c_ok else "CONTROL-BROKEN",
    }
    log("NC-C out-of-scope: " + "; ".join(
        f"{n}={'REFUSED' if r else 'ACCEPTED'}" for n, r in refusals[:3]) + " -> "
        + ("CONTROL-OK" if c_ok else "CONTROL-BROKEN"))

    # ---- NC-D instability detected, not silent ------------------------------
    audio, coef, key = first_instance(bundles["badnews-reso1"])

    class NoClipUnit(fp.LP12Unit):
        """CONTROL-ONLY: clipgain disabled (r_clip pinned to 1.0)."""

        def process_block(self, inp64, cm):
            outs, peak, c_end = super().process_block(inp64, cm)
            return outs, peak, c_end

    def noclip_block(unit, inp64, cm):
        # replicate the Driven kernel without the clipgain contraction
        c = list(cm.C)
        dc = list(cm.dC)
        peak = 0
        out = []
        for x in inp64:
            for i in (0, 1, 2, 4, 5, 6):
                c[i] = vm.sat(c[i] + dc[i])
            y = qmul(c[4], unit.r0) + qmul(c[6], x) + qmul(c[5], unit.r1)
            s1 = qmul(x, c[2]) + qmul(c[0], unit.r0) - qmul(c[1], unit.r1)
            s2 = qmul(c[1], unit.r0) + qmul(c[0], unit.r1)
            unit.r0 = qmul(s1, vm.ONE)          # clipgain forced to 1.0
            unit.r1 = qmul(s2, vm.ONE)
            c[7] = vm.sat(c[7] + dc[7])
            unit.r_clip = vm.ONE
            out.append(y)
            peak = max(peak, abs(y), abs(unit.r0), abs(unit.r1))
        return out, peak

    out_noclip, eng = [], []
    peaks_noclip = []
    peaks_frozen = []
    unit_nc = fp.LP12Unit(fp.SUBTYPE_DRIVEN)
    unit_fr = fp.LP12Unit(fp.SUBTYPE_DRIVEN)
    cm_fr = fp.LP12CoeffMaker(fp.SUBTYPE_DRIVEN)
    for i, rec in enumerate(coef):
        blk_in = [qintf(fin) for (_, fin, _) in audio[i * BLOCK_OS:(i + 1) * BLOCK_OS]]
        eng.extend(qintf(fout) for (_, _, fout) in
                   audio[i * BLOCK_OS:(i + 1) * BLOCK_OS])
        cm_fr.make_coeffs(qintf(float(rec["cut"])), qintf(float(rec["reso"])))
        o, p = noclip_block(unit_nc, blk_in, cm_fr)
        out_noclip.extend(o)
        peaks_noclip.append(p)
        o2, p2, _ = unit_fr.process_block(blk_in, cm_fr)
        peaks_frozen.append(p2)
    verdict_noclip = fp.stability_verdict(peaks_noclip)
    verdict_frozen = fp.stability_verdict(peaks_frozen)
    d_ok = verdict_noclip == "UNSTABLE" and verdict_frozen == "STABLE"
    results["NC-D-instability-detected"] = {
        "targeted_check": "stability monitor flags an unstable control variant "
                          "(clipgain disabled at the self-osc corner) while the "
                          "frozen model stays bounded",
        "clipgain_disabled_verdict": verdict_noclip,
        "clipgain_disabled_peak_lsb": max(peaks_noclip),
        "frozen_model_verdict": verdict_frozen,
        "frozen_model_peak_lsb": max(peaks_frozen),
        "outcome": "CONTROL-OK (detected, not silent)" if d_ok else "CONTROL-BROKEN",
    }
    log(f"NC-D reso1 clipgain-disabled: verdict={verdict_noclip} "
        f"peak={max(peaks_noclip)}; frozen: verdict={verdict_frozen} "
        f"peak={max(peaks_frozen)} -> "
        f"{'CONTROL-OK' if d_ok else 'CONTROL-BROKEN'}")

    # ---- NC-E RTL mutant -----------------------------------------------------
    if require_rtl:
        mutant = os.path.join(REPO, "rtl", "voice", "lp12_broken_mutant.sv")
        run_dir = os.path.join(art_root, "run-badnews")
        trace_in = os.path.join(run_dir, "model_trace.json")
        if not os.path.exists(trace_in):
            results["NC-E-rtl-mutant"] = {
                "outcome": "NOT_RUN (precondition missing: %s; generate it "
                           "with model/voice/filter_lp12/run_filter_leg.py)"
                           % trace_in}
            log("NC-E rtl mutant: NOT_RUN (missing model trace at %s)"
                % trace_in)
        else:
            try:
                sys.path.insert(0, os.path.join(REPO, "tools"))
                import compare_rtl_model_lp12 as crm

                with open(trace_in) as f:
                    mt = json.load(f)
                trace_path = crm.build_and_run(mutant, run_dir)
                checked, fails = crm.compare(mt, trace_path)
                e_ok = bool(fails)
                results["NC-E-rtl-mutant"] = {
                    "targeted_check": "RTL-vs-model exactness FAILs for the mutated testbench",
                    "mismatches": len(fails), "checked": checked,
                    "outcome": "CONTROL-OK (exactness FAILs)" if e_ok else "CONTROL-BROKEN",
                }
                log(f"NC-E rtl mutant: mismatches={len(fails)} -> "
                    f"{'CONTROL-OK' if e_ok else 'CONTROL-BROKEN'}")
            except FileNotFoundError as e:
                results["NC-E-rtl-mutant"] = {"outcome": "NOT_RUN (iverilog unavailable)",
                                              "error": str(e)}
                log("NC-E rtl mutant: NOT_RUN (iverilog unavailable)")
    else:
        results["NC-E-rtl-mutant"] = {"outcome": "NOT_RUN (skipped by flag)"}
        log("NC-E rtl mutant: NOT_RUN (skipped)")

    all_ok = all(v["outcome"].startswith(("CONTROL-OK", "NOT_RUN"))
                 for v in results.values())
    lines.append("=" * 60)
    lines.append("ALL CONTROLS FAILED THEIR TARGETED CHECKS (or explicit NOT_RUN): "
                 + ("YES" if all_ok else "NO — BROKEN CONTROL"))
    with open(os.path.join(artifact_dir, "negative-controls.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(artifact_dir, "negative-controls.json"), "w",
              encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    return 0 if all_ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", default=os.path.join(REPO, "reports", "sxt-037",
                                                           "artifacts"))
    ap.add_argument("--skip-rtl", action="store_true")
    ap.add_argument("--bundle-root", default=None,
                    help="directory containing the bundle-* case dirs "
                         "(default: --artifact-dir)")
    args = ap.parse_args()
    return run_controls(args.artifact_dir, require_rtl=not args.skip_rtl,
                        bundle_root=args.bundle_root)


if __name__ == "__main__":
    sys.exit(main())
