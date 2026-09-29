#!/usr/bin/env python3
"""SXT-036 negative controls that need NO pinned oracle (issue #70, re-queue
policy of #96). Each control must DEMONSTRABLY FAIL the check it targets.

These controls target the RTL-vs-model INTEGER-EXACTNESS check
(tools/compare_vel_rtl_model.py) and model discrimination (a mutated model
must differ from the unmutated model). They do NOT establish the acceptance
item 5 (reference-budget) controls, which require the pinned engine render
and are reported NOT_RUN (see reports/SXT-036/EVIDENCE.md).

Controls:
  E1..E3  model-trace mutants vs the UNMODIFIED RTL stimulus/schedule:
          --zero-route (all six routes, one at a time), --source-swap-mw,
          --shared-state. The exactness check must FAIL (mismatches > 0).
  E4..E6  RTL mutants vs the unmodified model trace:
          shared-slot (one scene-wide {vel, relvel} pair), rounding
          (truncate instead of round in the qmul), velocity ROM floor
          (no +127 rounding). The exactness check must FAIL.
  M1      model discrimination: each mutated model render must differ from
          the unmutated model render (samples16), i.e. the routes are
          observable in the model output.
  M2      invariance: --strip-vel-routes reproduces the landed SXT-022
          model render bit-identically (sha256 equal), on a sequence with
          no velocity dependence in the landed model.
  R1      refusal: out-of-class route (velocity -> 'A Highpass' 303) exits 2;
          --zero-route of a route that does not exist exits 2.
Positive control: the unmutated RTL vs the unmodified model trace PASSES.

Usage: python3 tools/vel_negative_controls.py --artifacts DIR
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "model", "voice", "run_vel_model.py")
LANDED = os.path.join(REPO, "model", "voice", "run_model.py")
CMP = os.path.join(REPO, "tools", "compare_vel_rtl_model.py")
TB = os.path.join(REPO, "rtl", "voice", "tb_vel.sv")
SEQ = "sxt036-vel-overlap-v1"
INV_SEQ = "seq-notes-repeated-v1"
ROUTES = ["vel:cutoff", "vel:reso", "vel:fegmod", "vel:vca",
          "relvel:cutoff", "relvel:vca"]

MUTANTS = {
    "shared-slot": [("vel_q[s]    = vel_rom", "vel_q[0]    = vel_rom"),
                    ("relvel_q[s] = 0;", "relvel_q[0] = 0;"),
                    ("relvel_q[s] = vel_rom", "relvel_q[0] = vel_rom"),
                    ("(src == 0) ? vel_q[s] : relvel_q[s]",
                     "(src == 0) ? vel_q[0] : relvel_q[0]"),
                    ("b, s, vel_q[s], relvel_q[s]);",
                     "b, s, vel_q[0], relvel_q[0]);")],
    "round-trunc": [("r = (p + (64'sd1 << (sh-1))) >>> sh;",
                    "r = p >>> sh;")],
    "rom-floor": [("(64'(midi) << (FQ+1)) + 64'd127;",
                   "(64'(midi) << (FQ+1));")],
}


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    args = ap.parse_args()
    art = os.path.abspath(args.artifacts)
    os.makedirs(art, exist_ok=True)
    work = tempfile.mkdtemp(prefix="sxt036-nc-")
    lines, results, ok_all = [], {}, True

    def log(s=""):
        lines.append(s)
        print(s)

    def model(tag, seq, extra):
        d = os.path.join(work, tag)
        rc, out, err = sh([sys.executable, RUNNER, "--sequence", seq,
                           "--out-dir", d] + extra)
        return rc, d, err

    def exactness(run_dir, tb=TB):
        rc, out, err = sh([sys.executable, CMP, "--run-dir", run_dir,
                           "--tb", tb])
        try:
            j = json.loads(out)
        except Exception:
            j = {"verdict": "ERROR", "mismatches": None, "err": err[-300:]}
        return rc, j

    log("SXT-036 oracle-independent negative controls "
        "(exactness + model discrimination; reference-budget controls are "
        "NOT_RUN, #96)")
    log(f"sequence: {SEQ}")
    log("")

    rc, base, err = model("baseline", SEQ, [])
    assert rc == 0, err
    rc, j = exactness(base)
    log(f"[positive control] unmutated RTL vs unmutated model: "
        f"{j['verdict']} mismatches={j['mismatches']} checked={j['checked']}")
    results["positive"] = j
    if j["verdict"] != "PASS":
        ok_all = False
    base_trace = json.load(open(os.path.join(base, "model_trace.json")))
    base_s16 = base_trace["samples16"]

    def fail_expected(name, j, rc):
        nonlocal ok_all
        failed = j["verdict"] == "FAIL" and (j["mismatches"] or 0) > 0
        log(f"[{name}] exactness verdict={j['verdict']} "
            f"mismatches={j['mismatches']} "
            f"first={j.get('first_failures', [None])[:1]} -> "
            f"{'FAILS as required' if failed else 'DID NOT FAIL (control broken)'}")
        if not failed:
            ok_all = False
        return failed

    # E1-E3: model-trace mutants against the unmodified RTL schedule
    mutants = [(f"E1 zero-route {r}", f"zero-{r.replace(':', '-')}",
                ["--zero-route", r]) for r in ROUTES]
    mutants += [("E2 source-swap-mw", "source-swap-mw", ["--source-swap-mw"]),
                ("E3 shared-state", "shared-state", ["--shared-state"])]
    for title, tag, extra in mutants:
        rc, d, err = model(tag, SEQ, extra)
        if rc != 0:
            log(f"[{title}] model runner exit {rc}: {err[-200:]}")
            ok_all = False
            continue
        # unmodified RTL stimulus + schedule, mutated model trace
        cdir = os.path.join(work, "cross-" + tag)
        shutil.copytree(base, cdir)
        shutil.copy(os.path.join(d, "model_trace.json"),
                    os.path.join(cdir, "model_trace.json"))
        rc, j = exactness(cdir)
        f = fail_expected(title, j, rc)
        mt = json.load(open(os.path.join(d, "model_trace.json")))
        diff = max(abs(a - b) for a, b in zip(mt["samples16"], base_s16))
        differs = diff > 0
        log(f"    M1 model render differs from unmutated: max|delta|={diff} "
            f"LSB -> {'observable' if differs else 'NOT OBSERVABLE (control weak)'}")
        if not differs:
            ok_all = False
        results[tag] = {"exactness": j, "model_max_abs_delta_lsb": diff,
                        "fails_as_required": f, "model_differs": differs}

    # E4-E6: RTL mutants against the unmodified model trace
    src = open(TB, encoding="utf-8").read()
    for name, subs in MUTANTS.items():
        m = src
        for needle, rep in subs:
            if m.count(needle) < 1:
                log(f"[E-rtl {name}] mutation anchor missing: {needle!r}")
                ok_all = False
            m = m.replace(needle, rep)
        mp = os.path.join(art, f"tb_vel_{name.replace('-', '_')}_mutant.sv")
        open(mp, "w", encoding="utf-8").write(m)
        rc, j = exactness(base, tb=mp)
        f = fail_expected(f"E-rtl {name} mutant", j, rc)
        results["rtl-" + name] = {"exactness": j, "fails_as_required": f}
        # the exactness harness leaves its vvp/trace in the run dir; rerun
        # of the baseline below restores the unmutated trace

    rc, j = exactness(base)
    log(f"[positive control, re-run after mutants] {j['verdict']} "
        f"mismatches={j['mismatches']}")
    if j["verdict"] != "PASS":
        ok_all = False

    # M2 invariance
    ra, da, ea = sh([sys.executable, LANDED, "--sequence", INV_SEQ,
                     "--out-dir", os.path.join(work, "inv-landed")])
    rb, db, eb = model("inv-strip", INV_SEQ, ["--strip-vel-routes"])
    if ra == 0 and rb == 0:
        ha = sha(os.path.join(work, "inv-landed", "model.wav"))
        hb = sha(os.path.join(db, "model.wav"))
        eq = ha == hb
        log(f"[M2 invariance] {INV_SEQ}: landed run_model.py wav sha256 "
            f"{ha[:16]}.. vs --strip-vel-routes {hb[:16]}.. -> "
            f"{'IDENTICAL' if eq else 'DIFFER (invariance broken)'}")
        results["invariance"] = {"landed": ha, "stripped": hb, "equal": eq}
        ok_all &= eq
    else:
        log(f"[M2 invariance] runner errors: {ea[-150:]} {eb[-150:]}")
        ok_all = False

    # R1 refusals
    for title, extra in [("out-of-class route (velocity -> 'A Highpass' 303)",
                          ["--out-of-class-route"]),
                         ("zero-route of a nonexistent route",
                          ["--zero-route", "relvel:fegmod"])]:
        rc, d, err = model("refuse", SEQ, extra)
        good = rc == 2
        log(f"[R1 refusal] {title}: exit {rc} "
            f"({err.strip().splitlines()[-1][:110] if err.strip() else ''}) -> "
            f"{'REFUSED as required' if good else 'NOT REFUSED'}")
        results["refuse-" + title.split()[0]] = {"exit": rc, "refused": good}
        ok_all &= good

    log("")
    log("Reference-budget negative controls (acceptance item 5: "
        "routing-zeroed and source-swap vs pinned-engine render): NOT_RUN "
        "- pinned oracle unavailable on dispatch host (#96). The E1/E2 rows "
        "above test the RTL-vs-model exactness check, NOT the reference-"
        "budget check.")
    log(f"OVERALL (oracle-independent controls): "
        f"{'PASS (every control failed/held as required)' if ok_all else 'FAIL'}")
    open(os.path.join(art, "negative-control.txt"), "w").write("\n".join(lines) + "\n")
    with open(os.path.join(art, "negative-controls.json"), "w") as f:
        json.dump({"overall": "PASS" if ok_all else "FAIL",
                   "reference_budget_controls": "NOT_RUN",
                   "results": results}, f, indent=2)
        f.write("\n")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
