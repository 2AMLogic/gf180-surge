#!/usr/bin/env python3
"""SXT-038 negative controls — each MUST fail the check it targets.

A control that passes its target check is a broken control: it proves the
check cannot see the defect it is supposed to see.  This tool therefore
exits 0 only when EVERY control failed as designed (AGENTS.md live negative
controls rule).

  NC-A  wrong subtype   — the correct LP24 algorithm driven through the wrong
                          engine subtype (one probe per subtype, against the
                          matching carrier's pinned reference): the
                          reference-budget check must FAIL.
  NC-B  wrong algorithm — the LANDED LP 12 dB leaf's coefficient maker and
                          kernel (model/voice/filter_lp12) substituted for
                          LP 24 dB on the same control plane: the
                          reference-budget check must FAIL.
  NC-C  applicability   — out-of-scope requests (subtype 3, reso > 1,
                          reso < 0, cutoff beyond the declared span, a
                          non-LP24 type) must be REFUSED, never clamped.
  NC-D  RTL mutant      — rtl/voice/lp24_broken_mutant.sv (one mutated
                          constant) must FAIL the exactness harness.
  NC-E  control-plane   — a tampered control word in a reference bundle must
                          make the runner REFUSE (proves the fail-closed
                          both-legs-same-control-plane check is live).

Usage:
  python3 tools/lp24_negative_controls.py [--artifacts DIR] [--runs DIR]
"""

import argparse
import copy
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lp24"))
sys.path.insert(0, os.path.join(REPO, "model", "voice", "filter_lp12"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import filter_lp24_model as fp          # noqa: E402
import filter_lp12_model as fp12        # noqa: E402
import compare_lp24_model as budget     # noqa: E402


def _load_runner():
    """Load THIS leaf's runner by path (the LP12 leaf has a same-named file)."""
    import importlib.util
    path = os.path.join(REPO, "model", "voice", "filter_lp24", "run_filter_leg.py")
    spec = importlib.util.spec_from_file_location("lp24_run_filter_leg", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


leg = _load_runner()

ART = os.path.join(REPO, "reports", "SXT-038", "artifacts")

# One probe per subtype: (case, its true subtype, the wrong subtype to force)
NC_A_PROBES = [
    ("chords-std", 0, 1),      # Standard carrier driven as Driven
    ("edges", 1, 2),           # Driven carrier driven as Clean
    ("chords-clean", 2, 0),    # Clean carrier driven as Standard
]
NC_B_PROBES = [("edges", 1), ("phase1", 1)]


def _verdict(case_name, res):
    row = budget.evaluate(res)
    return row["verdict"], row


def nc_a(lines):
    out = []
    for case_name, true_sub, wrong_sub in NC_A_PROBES:
        bundle = os.path.join(ART, f"bundle-{case_name}")
        meta, coeffs, audio, regs = leg.load_bundle(bundle)
        case = leg.cp.load_case(os.path.join(leg.CASES_DIR, f"{case_name}.json"))
        res, _ = leg.run_case(case, coeffs, audio, regs, subtype_override=wrong_sub)
        verdict, row = _verdict(case_name, res)
        ok = verdict == "FAIL"
        lines.append(f"  NC-A {case_name}: true subtype {true_sub} -> forced {wrong_sub}: "
                     f"budget {verdict} (max {row['checks']['L2_max_abs_lsb']['achieved']} LSB, "
                     f"rms {row['checks']['L2_rms_lsb']['achieved']}) "
                     f"=> {'CONTROL-OK' if ok else 'CONTROL-BROKEN'}")
        out.append({"control": "NC-A", "case": case_name, "true_subtype": true_sub,
                    "forced_subtype": wrong_sub, "budget_verdict": verdict,
                    "max_abs_lsb": row["checks"]["L2_max_abs_lsb"]["achieved"],
                    "rms_lsb": row["checks"]["L2_rms_lsb"]["achieved"],
                    "control_ok": ok})
    return out


def nc_b(lines):
    out = []
    for case_name, sub in NC_B_PROBES:
        bundle = os.path.join(ART, f"bundle-{case_name}")
        meta, coeffs, audio, regs = leg.load_bundle(bundle)
        case = leg.cp.load_case(os.path.join(leg.CASES_DIR, f"{case_name}.json"))
        res, _ = leg.run_case(case, coeffs, audio, regs,
                              maker=fp12.LP12CoeffMaker, kernel=fp12.LP12Unit)
        verdict, row = _verdict(case_name, res)
        ok = verdict == "FAIL"
        lines.append(f"  NC-B {case_name}: LP 12 dB (landed SXT-037 model, subtype {sub}) "
                     f"substituted for LP 24 dB: budget {verdict} "
                     f"(max {row['checks']['L2_max_abs_lsb']['achieved']} LSB, "
                     f"rms {row['checks']['L2_rms_lsb']['achieved']}) "
                     f"=> {'CONTROL-OK' if ok else 'CONTROL-BROKEN'}")
        out.append({"control": "NC-B", "case": case_name, "substituted": "fut_lp12",
                    "budget_verdict": verdict,
                    "max_abs_lsb": row["checks"]["L2_max_abs_lsb"]["achieved"],
                    "rms_lsb": row["checks"]["L2_rms_lsb"]["achieved"],
                    "control_ok": ok})
    return out


def nc_c(lines):
    probes = [
        ("subtype 3 (outside the engine-declared LP24 set)",
         lambda: fp.LP24CoeffMaker(3)),
        ("kernel with subtype 3",
         lambda: fp.LP24Unit(3)),
        ("resonance 1.5 (> 1)",
         lambda: fp.LP24CoeffMaker(1).make_coeffs(fp.qint(0.0), fp.qint(1.5))),
        ("resonance -0.25 (< 0)",
         lambda: fp.LP24CoeffMaker(1).make_coeffs(fp.qint(0.0), fp.qint(-0.25))),
        ("cutoff +300 st (beyond the declared parameter span)",
         lambda: fp.LP24CoeffMaker(0).make_coeffs(fp.qint(300.0), fp.qint(0.1))),
        ("cutoff -300 st (beyond the declared parameter span)",
         lambda: fp.LP24CoeffMaker(0).make_coeffs(fp.qint(-300.0), fp.qint(0.1))),
    ]
    out = []
    for name, fn in probes:
        try:
            fn()
            refused = False
            detail = "ACCEPTED (no refusal)"
        except fp.Refuse as e:
            refused = True
            detail = f"REFUSED: {e}"
        lines.append(f"  NC-C {name}: {detail} "
                     f"=> {'CONTROL-OK' if refused else 'CONTROL-BROKEN'}")
        out.append({"control": "NC-C", "probe": name, "refused": refused,
                    "control_ok": refused})
    # A non-LP24 case file must also be refused by the case plan builder.
    case = leg.cp.load_case(os.path.join(leg.CASES_DIR, "edges.json"))
    bad = copy.deepcopy(case)
    bad["filter"]["type"] = 1
    try:
        leg.cp.build_plan(bad)
        refused, detail = False, "ACCEPTED (no refusal)"
    except leg.cp.Refuse as e:
        refused, detail = True, f"REFUSED: {e}"
    lines.append(f"  NC-C case with filter type 1 (fut_lp12): {detail} "
                 f"=> {'CONTROL-OK' if refused else 'CONTROL-BROKEN'}")
    out.append({"control": "NC-C", "probe": "case file with a non-LP24 type",
                "refused": refused, "control_ok": refused})
    return out


def nc_d(lines, runs_dir):
    run_dir = os.path.join(runs_dir, "run-edges-toggle")
    if not os.path.exists(os.path.join(run_dir, "model_trace.json")):
        lines.append(f"  NC-D: NOT_RUN (no model trace at {run_dir}) => CONTROL-NOT_RUN")
        return [{"control": "NC-D", "control_ok": False, "status": "NOT_RUN"}]
    cmd = [sys.executable, os.path.join(REPO, "tools", "compare_rtl_model_lp24.py"),
           "--run-dir", run_dir,
           "--tb", os.path.join(REPO, "rtl", "voice", "lp24_broken_mutant.sv"),
           "--expect", "fail"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    summary = json.loads(p.stdout[p.stdout.index("{"):]) if "{" in p.stdout else {}
    ok = summary.get("verdict") == "FAIL"
    lines.append(f"  NC-D RTL mutant (rounding bias 2^19): exactness "
                 f"{summary.get('verdict')} with {summary.get('mismatches')} mismatches "
                 f"=> {'CONTROL-OK' if ok else 'CONTROL-BROKEN'}")
    return [{"control": "NC-D", "verdict": summary.get("verdict"),
             "mismatches": summary.get("mismatches"), "control_ok": ok}]


def nc_e(lines):
    bundle = os.path.join(ART, "bundle-edges")
    meta, coeffs, audio, regs = leg.load_bundle(bundle)
    case = leg.cp.load_case(os.path.join(leg.CASES_DIR, "edges.json"))
    tampered = copy.deepcopy(coeffs)
    tampered[17]["cut"] = float(tampered[17]["cut"]) + 1.0
    try:
        leg.run_case(case, tampered, audio, regs)
        refused, detail = False, "ACCEPTED (no refusal)"
    except leg.Refuse as e:
        refused, detail = True, f"REFUSED: {e}"
    lines.append(f"  NC-E tampered control word (block 17 cutoff +1 st): {detail} "
                 f"=> {'CONTROL-OK' if refused else 'CONTROL-BROKEN'}")
    return [{"control": "NC-E", "refused": refused, "control_ok": refused}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default=ART)
    ap.add_argument("--runs", default="/tmp/sxt038")
    args = ap.parse_args()

    lines = ["SXT-038 (#72) LP 24 dB leaf — negative controls",
             "Each control MUST fail the check it targets; exit 0 only if all did.",
             ""]
    results = []
    lines.append("NC-A wrong subtype (reference-budget check must FAIL):")
    results += nc_a(lines)
    lines.append("")
    lines.append("NC-B wrong algorithm (reference-budget check must FAIL):")
    results += nc_b(lines)
    lines.append("")
    lines.append("NC-C applicability boundary (must REFUSE, never clamp):")
    results += nc_c(lines)
    lines.append("")
    lines.append("NC-D RTL mutant (exactness harness must FAIL):")
    results += nc_d(lines, args.runs)
    lines.append("")
    lines.append("NC-E control-plane tamper (runner must REFUSE):")
    results += nc_e(lines)
    lines.append("")

    all_ok = all(r["control_ok"] for r in results)
    lines.append(f"RESULT: {sum(1 for r in results if r['control_ok'])}/{len(results)} "
                 f"controls failed their target check as designed — "
                 f"{'ALL CONTROLS OK' if all_ok else 'CONTROL SET BROKEN'}")
    text = "\n".join(lines) + "\n"
    print(text, end="")
    os.makedirs(args.artifacts, exist_ok=True)
    with open(os.path.join(args.artifacts, "negative-control.txt"), "w",
              encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(args.artifacts, "negative-controls.json"), "w",
              encoding="utf-8") as f:
        json.dump({"issue": "SXT-038", "all_controls_ok": all_ok,
                   "controls": results}, f, indent=2)
        f.write("\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
