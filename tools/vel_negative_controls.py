#!/usr/bin/env python3
"""SXT-036 negative controls that need NO pinned oracle (issue #70, re-queue
policy of #96). Each control must DEMONSTRABLY FAIL the check it targets.

These controls target the RTL-vs-model INTEGER-EXACTNESS check
(tools/compare_vel_rtl_model.py) and model discrimination (a mutated model
must differ from the unmutated model). They do NOT establish the acceptance
item 5 (reference-budget) controls, which require the pinned engine render
and are reported NOT_RUN (see reports/SXT-036/EVIDENCE.md).

Controls:
  E1..E4  model-trace mutants vs the UNMODIFIED RTL stimulus/schedule:
          --zero-route (all six routes, one at a time), --source-swap-mw,
          --shared-state, --stale-slot-relvel. The exactness check must FAIL
          (mismatches > 0).
  E-rtl   RTL mutants vs the unmodified model trace:
          shared-slot (one scene-wide {vel, relvel} pair), rounding
          (truncate instead of round in the qmul), velocity ROM floor
          (no +127 rounding), stale-slot-reinit (construction does not clear
          the slot's release-velocity register), release-one-block-late (the
          release latch moved after the control pass). The exactness check
          must FAIL.
  M1      model discrimination: each mutated model render must differ from
          the unmutated model render (samples16), i.e. the routes are
          observable in the model output.
  M2      invariance: --strip-vel-routes reproduces the landed SXT-022
          model render bit-identically (sha256 equal), on a sequence with
          no velocity dependence in the landed model.
  R1      refusal: out-of-class route (velocity -> 'A Highpass' 303) exits 2;
          --zero-route of a route that does not exist exits 2.
  R2      refusal: the scene-B route the named carrier 'House Of Chords.fxp'
          actually carries (velocity -> 'B Osc 1 Sync' 502) exits 2. The
          frozen destination class is scene A only and per-instance state is
          never shared across scenes, so a scene-B destination must be
          refused rather than folded into a scene-A destination.
Positive control: the unmutated RTL vs the unmodified model trace PASSES.

`--sequence` runs the whole control set on a different stimulus. Use it to
show that the exactness check is falsifiable on the sequences NAMED BY ISSUE
#70 as well (`tools/vel_declared_coverage.py` runs the positive direction
there): a PASS on a new stimulus means nothing unless a mutant on the SAME
stimulus demonstrably FAILS. Artifacts are written under a sequence-specific
suffix for any non-default sequence, so the default-sequence transcript is
never overwritten.

A control whose STIMULUS PRECONDITION is unmet is reported NOT_RUN with the
reason named -- never as a pass, never as "control broken". Three such
preconditions exist here:

  per_instance   the per-instance-state controls (E3 shared-state, E-rtl
                 shared-slot) require a stimulus with two or more
                 concurrently-live voices carrying distinct source words; on
                 a monophonic stimulus a shared register is behaviourally
                 identical to per-voice registers and the control cannot fire.
  slot_reuse     the construction-time re-initialization controls (E4
                 stale-slot-relvel, E-rtl stale-slot-reinit) require a
                 stimulus that REUSES a voice slot after that slot's previous
                 voice was released with a NONZERO release velocity; with no
                 such reuse a missing ctor clear is unobservable.
  release_word   the release-timing control (E-rtl release-one-block-late)
                 requires at least one block in which a voice is released
                 with a nonzero release-velocity word AND runs a control pass
                 in that same block; otherwise a one-block-late latch is
                 unobservable.

Exit codes: 0 = every control fired as required; 3 = every applicable control
fired but at least one is NOT_RUN on an unmet, named precondition; 1 = a
control that should have fired did not; 2 = argparse/usage.

Usage: python3 tools/vel_negative_controls.py --artifacts DIR
       python3 tools/vel_negative_controls.py --artifacts DIR \
           --sequence seq-notes-holds-v1
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vel_state_coverage import trace_preconditions   # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "model", "voice", "run_vel_model.py")
LANDED = os.path.join(REPO, "model", "voice", "run_model.py")
CMP = os.path.join(REPO, "tools", "compare_vel_rtl_model.py")
TB = os.path.join(REPO, "rtl", "voice", "tb_vel.sv")
SEQ = "sxt036-vel-overlap-v1"
INV_SEQ = "seq-notes-repeated-v1"
ROUTES = ["vel:cutoff", "vel:reso", "vel:fegmod", "vel:vca",
          "relvel:cutoff", "relvel:vca"]

_RELEASE_LATCH = """        if (ctrl_mem[base+3][0]) begin
          relvel_q[s] = vel_rom(ctrl_mem[base+4]);
        end
"""
_LATE_LATCH = """      for (s = 0; s < NSLOTS; s++) begin
        base = ci + 1 + s*SW;
        if (ctrl_mem[base+3][0]) relvel_q[s] = vel_rom(ctrl_mem[base+4]);
      end
      ci += STRIDE;"""

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
    # construction no longer clears the slot's release-velocity register:
    # a REUSED slot inherits the previous voice's release velocity (the
    # cited ctor fact releaseVelocitySource.set_output(0, 0) is dropped)
    "stale-slot-reinit": [
        ("""          vel_q[s]    = vel_rom(ctrl_mem[base+2]);
          relvel_q[s] = 0;""",
         """          vel_q[s]    = vel_rom(ctrl_mem[base+2]);
          // [mutant] ctor does not clear the release-velocity register""")],
    # the release latch is moved AFTER the per-voice control pass, so the
    # release-velocity term appears one block late instead of in the same
    # block's pass (the declared SXT-021 event timing)
    "release-one-block-late": [
        (_RELEASE_LATCH,
         "        // [mutant] release latch moved after the control pass\n"),
        ("      ci += STRIDE;", _LATE_LATCH)],
}

# stimulus precondition each RTL mutant needs in order to be able to fire
MUTANT_PRECONDITION = {
    "shared-slot": "per_instance",
    "stale-slot-reinit": "slot_reuse",
    "release-one-block-late": "release_word",
}


def sh(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--sequence", default=SEQ,
                    help=f"stimulus for every control (default {SEQ}); "
                         "a non-default value suffixes the artifact names")
    args = ap.parse_args()
    art = os.path.abspath(args.artifacts)
    os.makedirs(art, exist_ok=True)
    seq = args.sequence
    suffix = "" if seq == SEQ else "-" + seq
    work = tempfile.mkdtemp(prefix="sxt036-nc-")
    lines, results, ok_all = [], {}, True
    not_run = []

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
    log(f"sequence: {seq}" + ("" if seq == SEQ else "  (non-default: the "
        "control set re-run on a sequence named by issue #70)"))
    log("")

    rc, base, err = model("baseline", seq, [])
    assert rc == 0, err
    rc, j = exactness(base)
    log(f"[positive control] unmutated RTL vs unmutated model: "
        f"{j['verdict']} mismatches={j['mismatches']} checked={j['checked']}")
    results["positive"] = j
    if j["verdict"] != "PASS":
        ok_all = False
    base_trace = json.load(open(os.path.join(base, "model_trace.json")))
    base_s16 = base_trace["samples16"]

    # ---- stimulus precondition for the PER-INSTANCE-STATE controls --------
    # A scene-wide (shared) {vel, relvel} register is behaviourally identical
    # to per-voice registers unless the stimulus has, in some block, two or
    # more concurrently-live voices whose source words are NOT all equal. On
    # a monophonic stimulus the shared-state / shared-slot controls therefore
    # CANNOT fire; that is an unmet stimulus precondition, not a working
    # control and not a passing one. Such a control is reported NOT_RUN with
    # its reason named (never PASS -- AGENTS.md: a test that did not run must
    # never be reported as a pass) and the run exits 3.
    # Two further preconditions, measured from the same trace:
    #  * slot_reuse   -- a slot is CREATED again after its previous voice was
    #    released with a nonzero release-velocity word. Without such a reuse,
    #    omitting the constructor's clear of that register is unobservable.
    #  * release_word -- a voice is released with a nonzero release-velocity
    #    word AND runs a control pass in that same block. Without that, a
    #    release latch applied one block late is unobservable.
    # Measured by the ONE implementation shared with the coverage census
    # (tools/vel_state_coverage.py), so the two can never disagree about
    # whether a control was able to fire.
    testable = trace_preconditions(base_trace)
    concurrent_blocks = testable["concurrent_distinct_source_word_blocks"]
    reuse_blocks = testable["slot_reuse_after_nonzero_release_velocity_blocks"]
    release_word_blocks = testable["release_blocks_with_nonzero_relvel_word"]
    PRECONDITION_REASON = {
        "per_instance": (f"stimulus '{seq}' never has two concurrently-live "
                         "voices with distinct source words, so a shared "
                         "register is behaviourally identical to per-voice "
                         "registers"),
        "slot_reuse": (f"stimulus '{seq}' never reuses a voice slot after "
                       "that slot was released with a nonzero release "
                       "velocity, so a missing constructor clear of the "
                       "release-velocity register is unobservable"),
        "release_word": (f"stimulus '{seq}' never releases a running voice "
                         "with a nonzero release-velocity word, so a release "
                         "latch applied one block late is unobservable"),
    }
    log(f"[stimulus precondition] blocks with >=2 concurrently-live voices "
        f"carrying distinct (vel_q, relvel_q) words: {concurrent_blocks} -> "
        f"per-instance-state controls "
        f"{'TESTABLE' if testable['per_instance'] else 'NOT TESTABLE on this stimulus'}")
    log(f"[stimulus precondition] slot reuses after a nonzero release "
        f"velocity: {reuse_blocks} -> construction-re-initialization controls "
        f"{'TESTABLE' if testable['slot_reuse'] else 'NOT TESTABLE on this stimulus'}")
    log(f"[stimulus precondition] releases of a running voice with a nonzero "
        f"release-velocity word: {release_word_blocks} -> release-timing "
        f"control "
        f"{'TESTABLE' if testable['release_word'] else 'NOT TESTABLE on this stimulus'}")
    results["stimulus_precondition"] = {
        "concurrent_distinct_source_word_blocks": concurrent_blocks,
        "per_instance_state_controls_testable": testable["per_instance"],
        "slot_reuse_after_nonzero_release_velocity_blocks": reuse_blocks,
        "reinitialization_controls_testable": testable["slot_reuse"],
        "release_blocks_with_nonzero_relvel_word": release_word_blocks,
        "release_timing_control_testable": testable["release_word"],
    }

    def skip_precondition(name, key):
        """Record a control as NOT_RUN on an unmet, named precondition."""
        reason = PRECONDITION_REASON[key]
        log(f"[{name}] NOT_RUN - {reason}")
        not_run.append({"control": name, "reason": reason,
                        "precondition": key})

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

    # E1-E4: model-trace mutants against the unmodified RTL schedule
    mutants = [(f"E1 zero-route {r}", f"zero-{r.replace(':', '-')}",
                ["--zero-route", r], None) for r in ROUTES]
    mutants += [("E2 source-swap-mw", "source-swap-mw", ["--source-swap-mw"],
                 None),
                ("E3 shared-state", "shared-state", ["--shared-state"],
                 "per_instance"),
                ("E4 stale-slot-relvel", "stale-slot-relvel",
                 ["--stale-slot-relvel"], "slot_reuse")]
    for title, tag, extra, pre in mutants:
        if pre is not None and not testable[pre]:
            skip_precondition(title, pre)
            results[tag] = {"status": "NOT_RUN",
                            "reason": "stimulus precondition unmet",
                            "precondition": pre}
            continue
        rc, d, err = model(tag, seq, extra)
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

    # E-rtl: RTL mutants against the unmodified model trace
    src = open(TB, encoding="utf-8").read()
    for name, subs in MUTANTS.items():
        pre = MUTANT_PRECONDITION.get(name)
        if pre is not None and not testable[pre]:
            skip_precondition(f"E-rtl {name} mutant", pre)
            results["rtl-" + name] = {"status": "NOT_RUN",
                                      "reason": "stimulus precondition unmet",
                                      "precondition": pre}
            continue
        m = src
        for needle, rep in subs:
            if m.count(needle) < 1:
                log(f"[E-rtl {name}] mutation anchor missing: {needle!r}")
                ok_all = False
            m = m.replace(needle, rep)
        # the RTL mutants are a function of tb_vel.sv alone, not of the
        # stimulus, so they are NOT suffixed: a non-default sequence rewrites
        # byte-identical files rather than committing duplicates
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

    # R1/R2 refusals
    for tag, title, extra in [
            ("R1", "out-of-class route (velocity -> 'A Highpass' 303)",
             ["--out-of-class-route"]),
            ("R1", "zero-route of a nonexistent route",
             ["--zero-route", "relvel:fegmod"]),
            ("R2", "cross-scene route (velocity -> 'B Osc 1 Sync' 502, the "
                   "route the named carrier 'House Of Chords.fxp' carries)",
             ["--cross-scene-route"])]:
        rc, d, err = model("refuse", seq, extra)
        good = rc == 2
        log(f"[{tag} refusal] {title}: exit {rc} "
            f"({err.strip().splitlines()[-1][:110] if err.strip() else ''}) -> "
            f"{'REFUSED as required' if good else 'NOT REFUSED'}")
        results["refuse-" + title.split()[0]] = {"exit": rc, "refused": good,
                                                 "control": tag}
        ok_all &= good

    log("")
    log("Reference-budget negative controls (acceptance item 5: "
        "routing-zeroed and source-swap vs pinned-engine render): NOT_RUN "
        "- pinned oracle unavailable on dispatch host (#96). The E1/E2 rows "
        "above test the RTL-vs-model exactness check, NOT the reference-"
        "budget check.")
    if not_run:
        log("")
        log(f"{len(not_run)} control(s) NOT_RUN on this stimulus (never "
            "reported as a pass):")
        for nr in not_run:
            log(f"  - {nr['control']}: {nr['reason']}")
        log("  These controls DO fire on a stimulus that overlaps voices "
            "with distinct source words AND reuses slots after a nonzero "
            f"release velocity (the leaf-local '{SEQ}'); see "
            "negative-control.txt.")
    if not ok_all:
        verdict = "FAIL"
    elif not_run:
        verdict = (f"PASS for every control that ran; {len(not_run)} NOT_RUN "
                   "(stimulus precondition unmet) - NOT a full control pass "
                   "on this stimulus")
    else:
        verdict = "PASS (every control failed/held as required)"
    log(f"OVERALL (oracle-independent controls): {verdict}")
    open(os.path.join(art, f"negative-control{suffix}.txt"),
         "w").write("\n".join(lines) + "\n")
    with open(os.path.join(art, f"negative-controls{suffix}.json"), "w") as f:
        json.dump({"overall": ("FAIL" if not ok_all else
                               "PASS_WITH_NOT_RUN" if not_run else "PASS"),
                   "sequence": seq,
                   "controls_not_run": not_run,
                   "reference_budget_controls": "NOT_RUN",
                   "results": results}, f, indent=2)
        f.write("\n")
    shutil.rmtree(work, ignore_errors=True)
    # 0 = every control fired as required; 3 = all applicable controls fired
    # but at least one is NOT_RUN on an unmet, named stimulus precondition;
    # 1 = a control that should have fired did not.
    if not ok_all:
        return 1
    return 3 if not_run else 0


if __name__ == "__main__":
    sys.exit(main())
