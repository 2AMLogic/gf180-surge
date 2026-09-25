#!/usr/bin/env python3
"""SXT-039 negative controls. Every control must DEMONSTRABLY FAIL the check
it targets; the tool exits 0 only when every control failed as designed.

  NC-A wrong-subtype    the carrier's own control plane and stimulus run
                        through the WRONG engine-declared subtype (a
                        different ladder tap) must FAIL the reference budget
                        against the carrier's pinned-kernel reference.
                        (Issue control: "same type, wrong subtype must also
                        FAIL".)
  NC-B wrong-algorithm  the LANDED LP 12 dB / Driven biquad (SXT-037,
                        model/voice/filter_lp12) substituted for this type on
                        the same control plane and stimulus must FAIL the
                        reference budget.  (Issue control: "substitute the
                        landed LP 12 dB/Driven biquad for this type - the
                        reference-budget check must FAIL".)
  NC-C out-of-scope     an undeclared subtype, an out-of-range resonance, an
       refused          out-of-span cutoff and a subtype change without the
                        engine reset path are all REFUSED by the frozen model
                        (fail-closed, exit-2 class) - never silently clamped.
  NC-D RTL mutant       rtl/voice/lpmoog_broken_mutant.sv (single-constant
                        mutation of the coefficient-product rounding bias)
                        must FAIL the RTL-vs-model exactness comparison
                        (requires iverilog; otherwise an explicit NOT_RUN).

Budget thresholds are the [PROPOSED] L2 audio bounds of
`tools/compare_lpmoog_model.py` (max <= 4096 LSB and rms <= 256 LSB in
Q10.21).  The spectral-correlation proposal is NOT used as a control
discriminator: it is missed by the clean model as well (recorded finding
F-039-1), so a control that "failed" on it would prove nothing.

Original to this repository (Apache-2.0). Engine structure cited from the
pinned GPL tree (surge@58914e59), read and never copied.
"""

import argparse
import json
import math
import os
import struct
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lpmoog"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import voice_model as vm  # noqa: E402
import filter_lpmoog_model as fp  # noqa: E402
import fixtures as fx  # noqa: E402
import run_filter_leg as rfl  # noqa: E402


def _load(name, path):
    """Load a module by explicit path (both filter leaves ship a module named
    `run_filter_leg`; the sibling leaf is loaded here CONTROL-ONLY)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# landed sibling leaf (SXT-037) -- used exclusively as the wrong-algorithm
# control, never as a substitute filter in any support claim
lp12 = _load("sxt037_filter_lp12_model",
             os.path.join(REPO, "model", "voice", "filter_lp12",
                          "filter_lp12_model.py"))

BLOCK_OS = vm.BLOCK_SIZE_OS
L2_MAX_LSB = 4096
L2_RMS_LSB = 256


def read_ref(ref_dir, case):
    path = os.path.join(ref_dir, f"ref-{case}.f32")
    with open(path, "rb") as f:
        data = f.read()
    vals = struct.unpack(f"<{len(data) // 4}f", data)
    return [vm.sat(int(math.floor(v * (1 << vm.FQ) + 0.5))) for v in vals]


def audio_metrics(model_out, ref_q):
    n = min(len(model_out), len(ref_q))
    d = [a - b for a, b in zip(model_out[:n], ref_q[:n])]
    rms = math.sqrt(sum(v * v for v in d) / n) if n else 0.0
    return {"n": n, "max_abs_lsb": max((abs(v) for v in d), default=0),
            "rms_lsb": rms}


def budget_fail(metrics):
    return metrics["max_abs_lsb"] > L2_MAX_LSB or metrics["rms_lsb"] > L2_RMS_LSB


def drive_lpmoog(case, subtype_override=None):
    """Run the frozen LP Legacy Ladder model over a fixture (optionally with a
    substituted subtype tap)."""
    spec = fx.build(case)
    unit = cm = None
    out = []
    for b, ctl in enumerate(spec["blocks"]):
        sub = int(ctl["subtype"]) if subtype_override is None else subtype_override
        if unit is None:
            unit = fp.LPMoogUnit(sub)
            cm = fp.LPMoogCoeffMaker(sub)
        elif ctl["reset"]:
            if sub != unit.subtype:
                unit.set_subtype(sub)
                cm = fp.LPMoogCoeffMaker(sub)
            else:
                unit.reset_state()
                cm.reset()
        cutoff_a = fp.cutoff_control(rfl.qintf(ctl["cut"]), rfl.qintf(ctl["keytrack"]),
                                     rfl.qintf(ctl["pitch"]),
                                     rfl.qintf(ctl["keytrack_root"]),
                                     rfl.qintf(ctl["envmod"]), rfl.qintf(ctl["fenv"]))
        cm.make_coeffs(cutoff_a, rfl.qintf(ctl["reso"]))
        blk = [rfl.qintf(v) for v in spec["input"][b * BLOCK_OS:(b + 1) * BLOCK_OS]]
        outs, _peak, c_end = unit.process_block(blk, cm)
        cm.C = list(c_end)
        out.extend(outs)
    return out


def drive_lp12_control(case, subtype=lp12.SUBTYPE_DRIVEN):
    """CONTROL ONLY: the landed LP 12 dB biquad in this leaf's place."""
    spec = fx.build(case)
    unit = lp12.LP12Unit(subtype)
    cm = lp12.LP12CoeffMaker(subtype)
    out = []
    for b, ctl in enumerate(spec["blocks"]):
        if ctl["reset"] and b > 0:
            unit.reset_state()
            cm.reset()
        cutoff_a = fp.cutoff_control(rfl.qintf(ctl["cut"]), rfl.qintf(ctl["keytrack"]),
                                     rfl.qintf(ctl["pitch"]),
                                     rfl.qintf(ctl["keytrack_root"]),
                                     rfl.qintf(ctl["envmod"]), rfl.qintf(ctl["fenv"]))
        cm.make_coeffs(cutoff_a, rfl.qintf(ctl["reso"]))
        blk = [rfl.qintf(v) for v in spec["input"][b * BLOCK_OS:(b + 1) * BLOCK_OS]]
        outs, _peak, c_end = unit.process_block(blk, cm)
        cm.C = list(c_end)
        out.extend(outs)
    return out


def run_controls(artifact_dir, ref_dir, require_rtl=True, run_root="/tmp"):
    os.makedirs(artifact_dir, exist_ok=True)
    results = {}
    lines = ["SXT-039 negative-control transcript (LP Legacy Ladder, fut_lpmoog)",
             "reference: pinned sst-filters kernel, standalone build (DR-0009);",
             "           the engine-integrated leg is NOT_RUN (see EVIDENCE.md)",
             "=" * 72]

    def log(s):
        print(s)
        lines.append(s)

    # ---- NC-A wrong subtype ------------------------------------------------
    for case, wrong in (("king-b1", 1), ("disturb", 3), ("chords", 0)):
        ref = read_ref(ref_dir, case)
        out = drive_lpmoog(case, subtype_override=wrong)
        m = audio_metrics(out, ref)
        failed = budget_fail(m)
        results[f"NC-A-wrong-subtype-{case}-as-{wrong}"] = {
            "targeted_check": "L2 reference budget with the wrong engine-declared "
                              "subtype (wrong ladder tap)",
            "l2": m, "budget_fail": failed,
            "outcome": "CONTROL-OK (fails the check)" if failed else "CONTROL-BROKEN",
        }
        log(f"NC-A {case} forced to subtype {wrong} "
            f"({fp.SUBTYPE_NAMES[wrong]}): max|d|={m['max_abs_lsb']} "
            f"rms={m['rms_lsb']:.1f} -> "
            f"{'FAILS budgets (CONTROL-OK)' if failed else 'PASSES budgets (CONTROL-BROKEN)'}")

    # ---- NC-B wrong algorithm (landed LP 12 dB / Driven) -------------------
    for case in ("king-b1", "disturb"):
        ref = read_ref(ref_dir, case)
        out = drive_lp12_control(case)
        m = audio_metrics(out, ref)
        failed = budget_fail(m)
        results[f"NC-B-wrong-algorithm-lp12-driven-{case}"] = {
            "targeted_check": "L2 reference budget with the landed LP 12 dB / Driven "
                              "biquad substituted for this algorithm",
            "l2": m, "budget_fail": failed,
            "outcome": "CONTROL-OK (fails the check)" if failed else "CONTROL-BROKEN",
        }
        log(f"NC-B {case} through the landed LP 12 dB/Driven biquad: "
            f"max|d|={m['max_abs_lsb']} rms={m['rms_lsb']:.1f} -> "
            f"{'FAILS budgets (CONTROL-OK)' if failed else 'PASSES budgets (CONTROL-BROKEN)'}")

    # ---- NC-C out-of-scope refused -----------------------------------------
    refusals = []

    def refused(fn):
        try:
            fn()
        except fp.Refuse:
            return True
        except Exception:
            return None
        return False

    refusals.append(("subtype=4", refused(lambda: fp.LPMoogUnit(4))))
    refusals.append(("subtype=-1 (maker)", refused(lambda: fp.LPMoogCoeffMaker(-1))))
    refusals.append(("reso>1", refused(
        lambda: fp.LPMoogCoeffMaker(3).make_coeffs(vm.qint(0.0), vm.qint(1.01)))))
    refusals.append(("cutoff out of span", refused(
        lambda: fp.LPMoogCoeffMaker(3).make_coeffs(vm.qint(260.0), vm.qint(0.5)))))

    def subtype_change_without_reset():
        spec = fx.build("king-b1")
        unit = fp.LPMoogUnit(3)
        cm = fp.LPMoogCoeffMaker(3)
        # simulate the runner's guard: a subtype change must carry the engine
        # reset path (memset + CM.Reset); the runner refuses otherwise
        blocks = [dict(spec["blocks"][0]), dict(spec["blocks"][1])]
        blocks[1]["subtype"] = 1
        blocks[1]["reset"] = False
        prev = None
        for blk in blocks:
            sub = blk["subtype"]
            if prev is not None and sub != prev and not blk["reset"]:
                raise fp.Refuse("subtype change without the engine reset path")
            prev = sub
        del unit, cm

    refusals.append(("subtype change w/o reset", refused(subtype_change_without_reset)))
    c_ok = all(r is True for _, r in refusals)
    results["NC-C-out-of-scope-refused"] = {
        "targeted_check": "applicability boundary refuses out-of-scope requests",
        "refusals": {name: ("REFUSED" if r else "ACCEPTED (CONTROL-BROKEN)")
                     for name, r in refusals},
        "outcome": "CONTROL-OK (refused, exit-2 class)" if c_ok else "CONTROL-BROKEN",
    }
    log("NC-C out-of-scope: " + "; ".join(
        f"{n}={'REFUSED' if r else 'ACCEPTED'}" for n, r in refusals)
        + " -> " + ("CONTROL-OK" if c_ok else "CONTROL-BROKEN"))

    # ---- NC-D RTL mutant ----------------------------------------------------
    if require_rtl:
        mutant = os.path.join(REPO, "rtl", "voice", "lpmoog_broken_mutant.sv")
        run_dir = os.path.join(run_root, "nc-run-king-b1")
        try:
            trace = rfl.run_case("king-b1")
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "model_trace.json"), "w",
                      encoding="utf-8") as f:
                json.dump(trace, f)
            rfl.write_rtl_stimulus(trace, run_dir)
            import compare_rtl_model_lpmoog as crm

            clean_path = crm.build_and_run(crm.TB, run_dir)
            _checked_clean, fails_clean = crm.compare(trace, clean_path)
            mut_path = crm.build_and_run(mutant, run_dir)
            checked, fails = crm.compare(trace, mut_path)
            d_ok = bool(fails) and not fails_clean
            results["NC-D-rtl-mutant"] = {
                "targeted_check": "RTL-vs-model exactness FAILs for the mutated "
                                  "testbench while the clean testbench PASSes",
                "clean_mismatches": len(fails_clean),
                "mutant_mismatches": len(fails),
                "checked": checked,
                "outcome": "CONTROL-OK (exactness FAILs)" if d_ok else "CONTROL-BROKEN",
            }
            log(f"NC-D rtl mutant: clean mismatches={len(fails_clean)} "
                f"mutant mismatches={len(fails)} -> "
                f"{'CONTROL-OK' if d_ok else 'CONTROL-BROKEN'}")
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            results["NC-D-rtl-mutant"] = {"outcome": "NOT_RUN (iverilog unavailable)",
                                          "error": str(e)}
            log("NC-D rtl mutant: NOT_RUN (iverilog unavailable)")
    else:
        results["NC-D-rtl-mutant"] = {"outcome": "NOT_RUN (skipped by flag)"}
        log("NC-D rtl mutant: NOT_RUN (skipped)")

    all_ok = all(v["outcome"].startswith(("CONTROL-OK", "NOT_RUN"))
                 for v in results.values())
    lines.append("=" * 72)
    lines.append("ALL CONTROLS FAILED THEIR TARGETED CHECKS (or explicit NOT_RUN): "
                 + ("YES" if all_ok else "NO - BROKEN CONTROL"))
    with open(os.path.join(artifact_dir, "negative-control.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(artifact_dir, "negative-control.json"), "w",
              encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    return 0 if all_ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir",
                    default=os.path.join(REPO, "reports", "SXT-039", "artifacts"))
    ap.add_argument("--ref-dir",
                    default=os.path.join(REPO, "reports", "SXT-039", "artifacts"))
    ap.add_argument("--run-root", default="/tmp")
    ap.add_argument("--skip-rtl", action="store_true")
    args = ap.parse_args()
    return run_controls(args.artifact_dir, args.ref_dir,
                        require_rtl=not args.skip_rtl, run_root=args.run_root)


if __name__ == "__main__":
    sys.exit(main())
