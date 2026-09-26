#!/usr/bin/env python3
"""Issue #111 checks: the tail-SHAPE (windowed decay-curve) leg of the wet-path
tail gate (compare_audio_reference.tail_check / stereo_tail_gate).

Legs
----
[0] Canonical re-runs. The two existing check tools are re-run as-is so their
    committed records reflect the gate with the new leg:
      tools/tail_gate_checks.py --baseline-rev PRE_111_REV
          (#93: shared mono comparator wet controls + dry byte-parity against
          the pre-#111 tool)
      tools/stereo_tail_gate_checks.py --write-artifacts
          (#100: the six SXT-028c cases, the stereo controls -- including the
          late-tail probes, now required-FAIL controls -- and the sxt-023 /
          sxt-024 re-runs)
    A non-zero exit of either tool FAILS this leg.

[1] Landed-verdict re-run. Every landed verdict the gate feeds is compared
    between the committed record at PRE_111_REV (read with `git show`, so the
    comparison survives the regenerated artifacts landing) and the re-run
    from leg 0:
      SXT-028c  six chorus-comparator cases     (reports/SXT-028c/artifacts)
      sxt-023   three fx-comparator cases       (#100 gated re-run record)
      sxt-024   three reverb-comparator cases   (#100 gated re-run record)
      #93       shared mono-comparator controls (checks-summary.json)
    For each case the verdict STATUS before/after, the tail-gate result
    before/after, and the new leg's numbers (worst per-window deviation and
    graded window count, mono / L / R) are recorded. A verdict STATUS change
    in either direction FAILS the leg: that is the issue's stop/escalate
    condition, and this leg reports it instead of tuning a budget. A tail-gate
    change under an unchanged status is reported explicitly, never silently.

[2] Late-tail controls. Built from the COMMITTED SXT-028c alienappears model
    render (stereo chorus comparator) and from the committed Behemoth SXT-012
    wet fixture (mono shared comparator; model := reference, so its PASS is a
    tool self-test, not a fidelity result):
      baseline                      -> PASS required
      zero-late-tail-from-N%        -> FAIL required (N = 30, 40, 60, 80, 90
                                       stereo; 40, 60, 95 Behemoth and 44
                                       Koala 2 mono)
      late-tail-decays-too-fast     extra exp decay (tau 0.2 s) from 40% of
                                    the declared region -> FAIL required
      right-channel-late-tail-drop  R zeroed from 60% (stereo) -> FAIL required
    Each control is also run through the PRE-#111 tool (materialized from
    PRE_111_REV) so the record shows which ones the old gate let through.
    One CHARACTERIZATION row (not a control, never counted as evidence) shows
    the declared floor's limit: Koala 2's tail from 46% of the region lies
    below -100 dBFS (but is not digital silence), so zeroing it is invisible
    to the shape leg by construction.

Claim scope
-----------
Comparator behaviour only. Control renders are derived from committed
renders; nothing here is a model-vs-reference, RTL, preset-support, or sound
claim, and no budget is frozen (freeze gated on SXT-017 #12 and #16).

Usage:
  python3 tools/tail_shape_leg_checks.py [--legs 0,1,2] [--scratch-root DIR]
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import wave

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402
from stereo_tail_gate_checks import read_f32, write_f32  # noqa: E402

ART = os.path.join(REPO, "reports", "tail-shape-leg", "artifacts")
CHORUS = os.path.join(REPO, "tools", "compare_chorus_reference.py")
SHARED = os.path.join(REPO, "tools", "compare_audio_reference.py")
SXT028C = os.path.join(REPO, "reports", "SXT-028c")
STEREO_ART = "reports/stereo-comparator-tail-gate/artifacts"
SHARED_ART = "reports/shared-comparator-tail-gate/artifacts"
# main immediately before issue #111 (the landed records this leaf re-grades)
PRE_111_REV = "8ade1d184d1b26f94caa9b3fa3bfbbab2069ff9e"

CASES_028C = [(s, q) for s in ("alienappears", "fmcombo", "fmtwang2")
              for q in ("seq-notes-coverage-v1", "seq-poly-8-v1")]
SXT023 = ("dexie", "fm_bass_1", "metallic")
SXT024 = ("click-wet", "preset-notes-coverage-wet", "hardreset-midpatch-wet")


def emit(lines, s=""):
    lines.append(s)
    print(s)


def status_of(verdict):
    return (verdict or "").split(" ", 1)[0]


def git_show(rev, path):
    r = subprocess.run(["git", "show", "%s:%s" % (rev, path)],
                       capture_output=True, cwd=REPO)
    return r.stdout if r.returncode == 0 else None


def run(cmd, cwd=REPO):
    return subprocess.run([sys.executable] + cmd, capture_output=True,
                          text=True, cwd=cwd)


def write_i16(path, a):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.asarray(a).astype("<i2").tobytes())


def shape_numbers(tc):
    """(max_dev_db, graded_windows, ok) of one tail_check's shape leg."""
    dc = (tc or {}).get("tail_decay_curve") or {}
    return dc.get("max_dev_db"), dc.get("graded_windows"), dc.get("ok")


def fmt_dev(v):
    return "n/a" if v is None else "%.2f" % v


# ---------------------------------------------------------------- leg 0 --

def leg0(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[0] canonical re-runs of the #93 and #100 check tools")
    emit(lines, "=" * 74)
    ok = True
    rep = {}
    for key, cmd in (
            ("tail_gate_checks", ["tools/tail_gate_checks.py",
                                  "--baseline-rev", PRE_111_REV,
                                  "--scratch-root",
                                  os.path.join(scratch, "t93")]),
            ("stereo_tail_gate_checks", ["tools/stereo_tail_gate_checks.py",
                                         "--write-artifacts",
                                         "--scratch-root",
                                         os.path.join(scratch, "t100")])):
        r = run(cmd)
        tail = [x for x in r.stdout.splitlines() if x.startswith("OVERALL")]
        good = r.returncode == 0
        ok &= good
        rep[key] = {"exit": r.returncode,
                    "overall": tail[-1] if tail else None}
        emit(lines, "  %-26s exit %d  %s" % (" ".join(cmd[:1]), r.returncode,
                                             tail[-1] if tail else
                                             "(no OVERALL line)"))
        if not good:
            emit(lines, "    stderr: %s" % r.stderr.strip()[-600:])
    rep["status"] = "PASS" if ok else "FAIL"
    return ok, rep


# ---------------------------------------------------------------- leg 1 --

def _row(lines, case, st_b, st_a, gate_b, gate_a, legs, extra=None):
    changed = st_b != st_a
    gate_changed = gate_b != gate_a
    row = {"case": case, "status_before": st_b, "status_after": st_a,
           "verdict_status_changed": changed,
           "tail_gate_before": gate_b, "tail_gate_after": gate_a,
           "tail_gate_changed": gate_changed,
           "shape_leg": {k: {"max_dev_db": v[0], "graded_windows": v[1],
                             "ok": v[2]} for k, v in legs.items()}}
    if extra:
        row.update(extra)
    note = ("CHANGED -- STOP/ESCALATE" if changed else
            "unchanged; tail gate %s -> %s (REPORTED, status unchanged)"
            % (gate_b, gate_a) if gate_changed else "unchanged")
    emit(lines, "  %-52s %s -> %s  (%s)" % (case, st_b, st_a, note))
    graded = {k: v for k, v in legs.items() if v[1] is not None}
    emit(lines, "      shape leg: %s" % ("  ".join(
        "%s dev %s dB over %s windows %s" % (k, fmt_dev(v[0]), v[1],
                                            "ok" if v[2] else "FAIL")
        for k, v in graded.items()) or "not graded (refused, or the "
        "declared region is not covered by the model render)"))
    return row


def leg1(lines):
    emit(lines, "=" * 74)
    emit(lines, "[1] landed verdicts: committed record at %s vs re-run with "
                "the tail-shape leg" % PRE_111_REV[:12])
    emit(lines, "=" * 74)
    emit(lines, "  shape-leg budget: %s" % json.dumps(car.PROPOSED_TAIL,
                                                    sort_keys=True))
    emit(lines)
    rows = []

    def three(j):
        lr = j.get("tail_check_lr") or {}
        return {"mono": shape_numbers(j.get("tail_check")),
                "L": shape_numbers(lr.get("L")),
                "R": shape_numbers(lr.get("R"))}

    for slug, seq in CASES_028C:
        rel = "reports/SXT-028c/artifacts/compare-%s__%s.json" % (slug, seq)
        before = json.loads(git_show(PRE_111_REV, rel))
        after = json.load(open(os.path.join(REPO, rel)))
        rows.append(_row(lines, "SXT-028c %s x %s" % (slug, seq),
                         status_of(before["verdict"]),
                         status_of(after["verdict"]),
                         before["tail_gate_ok"], after["tail_gate_ok"],
                         three(after)))
    emit(lines)
    for p in SXT023:
        rel = "%s/sxt023-rerun/audio-%s.json" % (STEREO_ART, p)
        before = json.loads(git_show(PRE_111_REV, rel))
        after = json.load(open(os.path.join(REPO, rel)))
        leaf = json.loads(git_show(PRE_111_REV,
                                   "reports/sxt-023/artifacts/audio-%s.json"
                                   % p))
        rows.append(_row(lines, "sxt-023 %s" % p,
                         status_of(before["verdict"]),
                         status_of(after["verdict"]),
                         before["tail_gate_ok"], after["tail_gate_ok"],
                         three(after),
                         {"leaf_record_status": status_of(leaf["verdict"]),
                          "verdict_after": after["verdict"]}))
        emit(lines, "      leaf record (reports/sxt-023) status: %s"
             % status_of(leaf["verdict"]))
    emit(lines)
    for c in SXT024:
        rel = "%s/sxt024-rerun/%s.json" % (STEREO_ART, c)
        before = json.loads(git_show(PRE_111_REV, rel))
        after = json.load(open(os.path.join(REPO, rel)))
        st = lambda j: "PASS" if all(j["checks"].values()) else "FAIL"  # noqa
        rows.append(_row(lines, "sxt-024 %s" % c, st(before), st(after),
                         before["tail_gate"]["ok"], after["tail_gate"]["ok"],
                         three(after["tail_gate"]),
                         {"failing_checks_after": sorted(
                             k for k, v in after["checks"].items() if not v)}))
        emit(lines, "      failing checks after: %s" % (", ".join(sorted(
            k for k, v in after["checks"].items() if not v)) or "none"))
    emit(lines)
    before = json.loads(git_show(PRE_111_REV, SHARED_ART
                                 + "/checks-summary.json"))
    after = json.load(open(os.path.join(REPO, SHARED_ART,
                                        "checks-summary.json")))
    bc = {c["control"]: c for c in before["legs"]["wet_tail_controls"]
          ["controls"]}
    for c in after["legs"]["wet_tail_controls"]["controls"]:
        b = bc.get(c["control"], {})
        rel = "%s/tailgate-%s.json" % (SHARED_ART, c["control"])
        legs, gate_b, gate_a = {}, None, None   # refusals carry no gate
        if os.path.exists(os.path.join(REPO, rel)):
            ja = json.load(open(os.path.join(REPO, rel)))
            gate_a = (ja.get("tail_check") or {}).get("ok")
            legs = {"mono": shape_numbers(ja.get("tail_check"))}
            raw = git_show(PRE_111_REV, rel)
            if raw is not None:
                gate_b = (json.loads(raw).get("tail_check") or {}).get("ok")
        rows.append(_row(lines, "#93 %s" % c["control"], b.get("got"),
                         c["got"], gate_b, gate_a, legs,
                         {"required": c.get("expect"),
                          "as_required": c.get("as_required")}))
    emit(lines, "  #93 dry byte-parity vs the pre-#111 tool: %s"
         % after["legs"]["dry_rerun_parity"]["status"])
    flips = sum(1 for r in rows if r["verdict_status_changed"])
    gate_changes = [r["case"] for r in rows if r["tail_gate_changed"]]
    ok = flips == 0 and after["legs"]["dry_rerun_parity"]["status"] == "PASS"
    emit(lines)
    emit(lines, "  result: %d landed cases re-run; verdict status changes: %d; "
                "tail-gate changes under an unchanged status: %s"
         % (len(rows), flips, ", ".join(gate_changes) or "none"))
    return ok, {"status": "PASS" if ok else "FAIL", "pre_change_rev":
                PRE_111_REV, "cases": rows, "verdict_status_changes": flips,
                "tail_gate_changes_status_unchanged": gate_changes,
                "dry_parity_93": after["legs"]["dry_rerun_parity"]["status"]}


# ---------------------------------------------------------------- leg 2 --

def materialize_pre111(scratch):
    """Pre-#111 chorus + shared tools, runnable against this checkout."""
    root = os.path.join(scratch, "pre111", "tools")
    os.makedirs(root, exist_ok=True)
    for name in ("compare_audio_reference.py", "compare_chorus_reference.py"):
        src = git_show(PRE_111_REV, "tools/" + name)
        if src is None:
            return None
        with open(os.path.join(root, name), "wb") as f:
            f.write(src)
    return root


def _gate_legs(j):
    tcs = [j.get("tail_check") or {}] + list(
        (j.get("tail_check_lr") or {}).values())
    return {
        "tail_rms_rel_ok": all(t.get("tail_rms_rel_ok") for t in tcs),
        "tail_decay_curve_ok": all(t.get("tail_decay_curve_ok") for t in tcs),
    }


def leg2(lines, scratch):
    emit(lines, "=" * 74)
    emit(lines, "[2] late-tail controls (each must fail the check it targets)")
    emit(lines, "=" * 74)
    emit(lines, "  NOTE (claim scope): stereo baseline is the COMMITTED model "
                "render; mono baseline is the reference")
    emit(lines, "        itself (tool self-test). Nothing here is a fidelity, "
                "support, or sound claim.")
    pre = materialize_pre111(scratch)
    if pre is None:
        emit(lines, "  NOT_RUN: pre-#111 tools unavailable at %s" % PRE_111_REV)
        return False, {"status": "NOT_RUN"}
    rows = []
    ok = True
    d = os.path.join(scratch, "leg2")
    os.makedirs(d, exist_ok=True)

    def grade(name, kind, cur_cmd, pre_cmd, out, pre_out, required,
              control=True, extra=None):
        nonlocal ok
        r = run(cur_cmd + ["--json", out])
        run(pre_cmd + ["--json", pre_out])
        j = json.load(open(out)) if os.path.exists(out) else {}
        pj = json.load(open(pre_out)) if os.path.exists(pre_out) else {}
        st = "NO_VERDICT" if r.returncode == 2 else status_of(j.get("verdict"))
        pst = status_of(pj.get("verdict")) or "NO_VERDICT"
        good = st == required
        if control:
            ok &= good
        dev, n, _ = shape_numbers(j.get("tail_check"))
        row = {"control": name, "tool": kind, "required": required,
               "observed": st, "pre111_tool_status": pst,
               "result": (("CONTROL-OK" if good else "CONTROL-BROKEN")
                          if control else "CHARACTERIZATION"),
               "budgets": j.get("proposed_budget_results"),
               "tail_decay_curve_max_dev_db": dev,
               "tail_decay_curve_graded_windows": n,
               "tail_rms_rel_db": (j.get("tail_check") or {}).get(
                   "tail_rms_rel_db")}
        row.update(_gate_legs(j))
        if extra:
            row.update(extra)
        rows.append(row)
        emit(lines, "  %-40s %-6s required %-4s observed %-4s | pre-#111 tool "
                    "%-4s | %s"
             % (name, kind, required if control else "--", st, pst,
                row["result"]))
        emit(lines, "      budgets all pass=%s | residual leg %s (%s dB) | "
                    "shape leg %s (worst dev %s dB, %s graded windows)"
             % (all((row["budgets"] or {}).values()),
                "PASS" if row["tail_rms_rel_ok"] else "FAIL",
                fmt_dev(row["tail_rms_rel_db"]),
                "PASS" if row["tail_decay_curve_ok"] else "FAIL",
                fmt_dev(dev), n))
        return row

    # ---- stereo: chorus comparator, alienappears x notes -------------------
    slug, seq = "alienappears", "seq-notes-coverage-v1"
    region = car.declared_tail_region(
        os.path.join(SXT028C, "fixtures", "%s__%s.json" % (slug, seq)), "wet")
    off, length = region["tail_offset"], region["tail_frames"]
    end = off + length
    emit(lines, "  stereo fixture %s x %s: declared tail region [%d, %d)"
         % (slug, seq, off, end))
    model = os.path.join(SXT028C, "artifacts",
                         "model__%s__%s.f32.wav" % (slug, seq))
    base = read_f32(model).astype(np.float64)
    renders = [("baseline", model, "PASS")]
    for frac in (0.3, 0.4, 0.6, 0.8, 0.9):
        m = base.copy()
        m[:, off + int(length * frac):end] = 0.0
        renders.append(("zero-late-tail-from-%d%%" % int(frac * 100), m,
                        "FAIL"))
    m = base.copy()
    s0 = off + int(length * 0.4)
    m[:, s0:end] *= np.exp(-np.arange(end - s0) / 48000.0 / 0.2)
    renders.append(("late-tail-decays-too-fast", m, "FAIL"))
    m = base.copy()
    m[1, off + int(length * 0.6):end] = 0.0
    renders.append(("right-channel-late-tail-drop", m, "FAIL"))
    for name, arr, required in renders:
        if isinstance(arr, str):
            p = arr
        else:
            p = os.path.join(d, "stereo-%s.f32.wav" % name.replace("%", ""))
            write_f32(p, arr)
        tag = name.replace("%", "")
        args = ["--slug", slug, "--seq", seq, "--model", p]
        grade("stereo/%s" % name, "chorus", [CHORUS] + args,
              [os.path.join(pre, "compare_chorus_reference.py"),
               "--fixtures-dir", os.path.join(SXT028C, "fixtures")] + args,
              os.path.join(d, "stereo-%s.json" % tag),
              os.path.join(d, "stereo-%s.pre111.json" % tag), required)
    emit(lines)

    # ---- mono: shared comparator, Behemoth (all 50 windows above floor) ----
    # Behemoth's tail stays above the floor for the whole region (all 50
    # windows graded); Koala 2's falls below it after ~46% of the region.
    for fixture, controls in (
            ("behemoth", (("baseline", None, "PASS", True),
                          ("zero-late-tail-from-40%", 0.4, "FAIL", True),
                          ("zero-late-tail-from-60%", 0.6, "FAIL", True),
                          ("zero-late-tail-from-95%", 0.95, "FAIL", True))),
            ("koala2", (("zero-late-tail-from-44%", 0.44, "FAIL", True),
                        ("zero-late-tail-from-46%", 0.46, None, False)))):
        ref_p = os.path.join(REPO, "fixtures", "audio", fixture,
                             "seq-notes-coverage-v1-wet.wav")
        sc = os.path.join(REPO, "fixtures", "audio", fixture,
                          "seq-notes-coverage-v1.json")
        region = car.declared_tail_region(sc, "wet")
        off, length = region["tail_offset"], region["tail_frames"]
        ref, _ = car.read_wav(ref_p)
        emit(lines, "  mono fixture %s (SXT-012 wet, int16): declared tail "
                    "region [%d, %d)" % (fixture, off, off + length))
        for name, frac, required, control in controls:
            m = ref.copy()
            if frac is not None:
                m[off + int(length * frac):off + length] = 0
            p = os.path.join(d, "mono-%s-%s.wav"
                             % (fixture, name.replace("%", "")))
            write_i16(p, m)
            args = ["--path", "wet", "--sidecar", sc, "--ref", ref_p,
                    "--model", p]
            extra = None
            if not control:
                zs = off + int(length * frac)
                seg = ref[zs:off + length]
                lvl = car.rms_dbfs(float(np.sqrt((seg * seg).mean())),
                                   car.INT16_FULL_SCALE)
                extra = {"note": "reference level of the zeroed span is %.1f "
                                 "dBFS, below the declared %.1f dBFS floor: "
                                 "the shape leg does not see it by "
                                 "construction (not a control)"
                                 % (lvl, car.PROPOSED_TAIL[
                                     "decay_curve_floor_dbfs"]),
                         "zeroed_span_ref_dbfs": lvl}
            grade("mono/%s/%s" % (fixture, name), "shared", [SHARED] + args,
                  [os.path.join(pre, "compare_audio_reference.py")] + args,
                  p + ".json", p + ".pre111.json", required or "(none)",
                  control, extra)
            if extra:
                emit(lines, "      %s" % extra["note"])
        emit(lines)

    ctl = [r for r in rows if r["result"] != "CHARACTERIZATION"]
    n_ok = sum(1 for r in ctl if r["result"] == "CONTROL-OK")
    emit(lines, "  result: %d/%d controls behaved as required" % (n_ok,
                                                                  len(ctl)))
    newly = [r["control"] for r in ctl if r["required"] == "FAIL"
             and r["observed"] == "FAIL" and r["pre111_tool_status"] == "PASS"]
    emit(lines, "  controls the PRE-#111 gate let through as PASS and the "
                "shape leg now FAILS: %s" % (", ".join(newly) or "none"))
    shape_only = [r["control"] for r in ctl if r["required"] == "FAIL"
                  and r["observed"] == "FAIL"
                  and all((r["budgets"] or {}).values())
                  and r["tail_rms_rel_ok"] and not r["tail_decay_curve_ok"]]
    emit(lines, "  shape leg is load-bearing (budgets and residual leg PASS, "
                "verdict FAILs on the shape leg alone): %s"
         % (", ".join(shape_only) or "none"))
    return ok, {"status": "PASS" if ok else "FAIL", "controls": rows,
                "newly_failing_vs_pre111": newly,
                "shape_leg_load_bearing": shape_only}


# ----------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratch-root", default="/tmp/sxt-tail-shape-leg")
    ap.add_argument("--legs", default="0,1,2")
    args = ap.parse_args()
    legs = {int(x) for x in args.legs.split(",") if x.strip()}
    scratch = args.scratch_root
    if os.path.exists(scratch):
        shutil.rmtree(scratch)
    os.makedirs(scratch)
    os.makedirs(ART, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, cwd=REPO).stdout.strip()
    summary = {"issue": 111, "run_utc": stamp, "repo_head": head,
               "pre_change_rev": PRE_111_REV, "numpy": np.__version__,
               "proposed_tail_budget": dict(car.PROPOSED_TAIL), "legs": {}}
    names = {0: ("canonical_reruns", "canonical-reruns.txt"),
             1: ("landed_verdict_rerun", "landed-verdict-rerun.txt"),
             2: ("late_tail_controls", "late-tail-controls.txt")}
    ok = True
    for leg in (0, 1, 2):
        key, fname = names[leg]
        if leg not in legs:
            summary["legs"][key] = {"status": "NOT_RUN",
                                    "reason": "leg not selected"}
            ok = False           # a leg that did not run is never a pass
            continue
        lines = ["issue #111 -- wet-path tail gate: tail-shape (decay-curve) "
                 "leg: leg %d" % leg,
                 "run: %s   repo HEAD: %s   numpy %s" % (stamp, head,
                                                        np.__version__),
                 "claim scope: comparator behaviour only; no fidelity, "
                 "support, or sound claim; budgets are proposals.", ""]
        if leg == 0:
            good, rep = leg0(lines, scratch)
        elif leg == 1:
            good, rep = leg1(lines)
        else:
            good, rep = leg2(lines, scratch)
        ok &= good
        summary["legs"][key] = rep
        lines += ["", "leg %d verdict: %s" % (leg, rep["status"])]
        with open(os.path.join(ART, fname), "w") as f:
            f.write("\n".join(lines) + "\n")
    summary["overall"] = "PASS" if ok else "FAIL"
    with open(os.path.join(ART, "checks-summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    print("OVERALL: %s" % summary["overall"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
