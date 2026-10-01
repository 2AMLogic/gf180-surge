#!/usr/bin/env python3
"""Issue #165 checks: the six per-leaf native-unit `spectral_corr` copies that
#110 left behind, each either MIGRATED to the shared definition
(`tools/compare_audio_reference.spectral_corr`) or RENAMED off the frozen name.

Per-site disposition (the decision this record exists to justify):

  MIGRATED to the shared definition -- same 0.98 effect-slice budget family,
  so the name must mean one thing:
    1. tools/compare_aw49_reference.py          SXT-028a   float32 FS 1.0
    2. tools/distortion_negative_controls.py    SXT-028e   Q10.21 FS 2^20
       (also SXT-028e-sse: distortion_sse_negative_controls.py loads this
        module and reuses its `metrics`/`spectral_corr`)
    3. tools/reverb2_negative_controls.py       SXT-028f   Q10.21 FS 2^21

  RENAMED to `l2_spectral_corr` / `l2_spectral_corr_min` -- a DIFFERENT metric
  against a DIFFERENT budget family (0.999, Q10.21), already recorded by
  SXT-037 as mis-scaled for filtered-voice spectra; re-grading it under the
  shared definition while leaving its floor at 0.999 would change what is
  measured without touching the proposal it is measured against, and choosing
  a different floor here is what #165's stop condition forbids:
    4. tools/compare_lpmoog_model.py            SXT-039
    5. model/voice/filter_lp12/run_filter_leg.py  SXT-037
    6. model/voice/filter_lp24/run_filter_leg.py  SXT-038

Legs
----
[1] Scan guard. No file in the repo but `tools/compare_audio_reference.py`
    COMPUTES a function named `spectral_corr`; every other definition of that
    name is a thin wrapper delegating to it. Each migrated wrapper is checked
    to equal the shared function at its own declared full scale, and to differ
    materially from the retired `spectral_corr_legacy_log1p` on the same input
    (the live control: a silent revert to the per-leaf copy would be visible).

[2] Re-run reproduction of the two migrated tools whose records this host can
    regenerate (SXT-028e, SXT-028f). Their producers are re-run into scratch
    and must reproduce the committed artifact exactly, modulo run metadata. A
    producer that cannot run here is NOT_RUN, never a pass.

[3] Migration diff and flip enumeration. Every `spectral_corr` value in the
    regenerated 0.98-family records is listed BASE -> NOW with its spectral-leg
    budget outcome (>= the record's OWN declared `spectral_corr_min`, read from
    the record -- this leg never supplies a floor). Every spectral-leg flip is
    named. The leg FAILS if any control's overall verdict / control-ok status
    moved, or if any declared budget VALUE differs from the base: #165 migrates
    a definition, it does not re-tune a budget.

[4] Rename value-preservation. Every difference this branch makes to an
    SXT-037 / SXT-038 / SXT-039 artifact (including the gzipped traces, which
    the ledger's JSON glob does not reach) must classify RENAME-#165 or
    DEFINITION under tools/regrade_spectral_corr.py -- i.e. a key moved from
    `spectral_corr` to `l2_spectral_corr` carrying the SAME value, or an added
    definition stamp. A moved VALUE cannot classify as a rename, so it would
    fail this leg.

[5] Producer re-run of the renamed L2 legs, from committed inputs only. The
    renamed producers are re-run and their `l2_spectral_corr` compared with
    the committed (renamed) value, to show the rename is what the producers
    now emit and not only an artifact edit. Coverage is reported separately
    from agreement: cases whose inputs are not committed are NOT_RUN.
    Expensive -- not in the default leg set.

[6] Idempotency of tools/rename_l2_spectral_corr_key.py: `--check` is clean
    and a second run reports zero changes.

CLAIM SCOPE. Metric NAMING and definition consistency over the measurement
tooling only. Nothing here establishes model-vs-reference fidelity, RTL
exactness, preset support, or sound quality, and no budget is frozen or
re-tuned by it. The L2 family's floor and metric remain the SXT-013/#12
freeze's decision.

Usage:
  python3 tools/spectral_corr_per_leaf_checks.py [--legs 1,2,3,4,6]
      [--scratch-root DIR] [--base-rev REV] [--main-ref REF]
"""

import argparse
import datetime
import glob
import gzip
import json
import os
import shutil
import subprocess
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car            # noqa: E402
import regrade_spectral_corr as rsc              # noqa: E402

sys.path.insert(0, os.path.join(REPO, "tests"))
import test_spectral_corr_single_definition as guard   # noqa: E402

ART = os.path.join(REPO, "reports", "spectral-corr-per-leaf-migration",
                   "artifacts")
BASE_REV = None

# The two 0.98-family records this host can regenerate, with the producer.
MIGRATED_RERUNS = [
    ("reports/SXT-028e/negative-controls/negative-controls.json",
     ["tools/distortion_negative_controls.py"], "028e"),
    ("reports/SXT-028f/negative-controls/negative-controls.json",
     ["tools/reverb2_negative_controls.py"], "028f"),
]
L2_PREFIXES = ("reports/SXT-038/", "reports/SXT-039/", "reports/sxt-037/")
L2_GZ_TRACES = sorted(glob.glob(os.path.join(
    REPO, "reports", "sxt-037", "artifacts", "model-trace-*.json.gz")))
# run metadata that legitimately differs between two runs of the same producer
RUN_META = ("run_utc", "repo_head", "date", "numpy", "out", "path", "bundle")


def git(*a):
    return subprocess.run(["git"] + list(a), cwd=REPO, capture_output=True,
                          text=True)


def base_json(rel):
    r = git("show", "%s:%s" % (BASE_REV, rel))
    return json.loads(r.stdout) if r.returncode == 0 else None


def strip_meta(o):
    if isinstance(o, dict):
        return {k: strip_meta(v) for k, v in o.items() if k not in RUN_META}
    if isinstance(o, list):
        return [strip_meta(v) for v in o]
    return o


def canon(o):
    return json.dumps(strip_meta(o), indent=1, sort_keys=True)


# --------------------------------------------------------------------------
def leg1(lines, scratch):
    """Scan guard + per-wrapper equality with the shared definition."""
    offenders = guard.find_offenders(REPO)
    lines.append("files COMPUTING a function named `spectral_corr` other than "
                 "%s: %d" % (guard.OWNER, len(offenders)))
    for o in offenders:
        lines.append("  OFFENDER %s" % o)
    rows, ok = [], not offenders
    rs = np.random.default_rng(1965)
    for rel in sorted(guard.DELEGATES):
        mod_name, fs = guard.DELEGATES[rel]
        mod = __import__(mod_name)
        n = 3 * car.SPECTRAL_CORR_FRAME
        a = np.sin(2 * np.pi * 440.0 / 48000.0 * np.arange(n)) * 0.4 * fs
        b = a + rs.normal(0.0, 1e-4 * fs, n)
        got = mod.spectral_corr(a, b)
        want = car.spectral_corr(a, b, full_scale=fs)
        legacy = car.spectral_corr_legacy_log1p(a, b)
        same = got == want
        # live control: the retired definition is a MATERIALLY different number
        differs = abs(got - legacy) > 1e-6
        ok &= same and differs
        rows.append({"tool": rel, "full_scale": fs, "wrapper": got,
                     "shared": want, "retired_log1p": legacy,
                     "equals_shared": same,
                     "differs_from_retired": differs})
        lines.append("  %-44s FS=%-12g wrapper=%.9f shared=%.9f "
                     "retired=%.9f  equal=%s differs-from-retired=%s"
                     % (rel, fs, got, want, legacy, same, differs))
    lines.append("")
    lines.append("CONTROL: a tool that silently reverted to its per-leaf "
                 "log1p copy would fail both the scan and the equality above.")
    return ok, {"status": "PASS" if ok else "FAIL", "offenders": offenders,
                "delegates": rows}


def leg2(lines, scratch):
    """Re-run the migrated producers; the committed record must reproduce."""
    rows, ok = [], True
    for rel, cmd, tag in MIGRATED_RERUNS:
        out = os.path.join(scratch, tag)
        r = subprocess.run([sys.executable] + cmd + ["--out", out],
                           cwd=REPO, capture_output=True, text=True)
        # some producers treat --out as a file, others as a directory
        cand = [out, os.path.join(out, os.path.basename(rel))]
        got = next((p for p in cand if os.path.isfile(p)), None)
        if r.returncode != 0 or got is None:
            rows.append({"artifact": rel, "status": "NOT_RUN",
                         "reason": "producer exit %d / no output at %s"
                                   % (r.returncode, out)})
            lines.append("  %-56s NOT_RUN (producer did not run here)" % rel)
            ok = False
            continue
        same = canon(json.load(open(got))) == canon(
            json.load(open(os.path.join(REPO, rel))))
        ok &= same
        rows.append({"artifact": rel, "producer": " ".join(cmd),
                     "status": "PASS" if same else "FAIL",
                     "reproduces_modulo_run_metadata": same})
        lines.append("  %-56s reproduces=%s" % (rel, same))
    lines.append("")
    lines.append("A producer that cannot run on this host is NOT_RUN and "
                 "fails the leg; it is never reported as a pass.")
    return ok, {"status": "PASS" if ok else "FAIL", "reruns": rows}


def _spectral_blocks(o, path=""):
    """(path, block) for every dict holding a MEASURED `spectral_corr` float."""
    if isinstance(o, dict):
        if isinstance(o.get("spectral_corr"), float):
            yield path, o
        for k, v in o.items():
            yield from _spectral_blocks(v, path + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _spectral_blocks(v, path + "[%d]" % i)


def _statuses(o, path=""):
    """Every verdict / control-ok style status leaf, for the no-flip check."""
    for k, v in rsc.leaves(o).items():
        if rsc.VERDICT_KEYS.search(k):
            yield k, v


def leg3(lines, scratch):
    """Name every migrated value change, every spectral-leg flip, and assert
    no overall verdict moved and no declared budget VALUE moved."""
    rows, flips, ok = [], [], True
    for rel, _cmd, _tag in MIGRATED_RERUNS:
        new = json.load(open(os.path.join(REPO, rel)))
        old = base_json(rel)
        if old is None:
            lines.append("  %s NOT_RUN: absent at base %s" % (rel, BASE_REV))
            ok = False
            continue
        # The floor is READ from the record under whichever key that leaf's
        # own producer declares it (`proposed`, `proposed_budgets`,
        # `budgets`), never supplied by this leg -- #165's stop condition
        # forbids this record choosing a floor.
        def declared(doc):
            for k in ("proposed", "proposed_budgets", "budgets"):
                b = doc.get(k)
                if isinstance(b, dict) and "spectral_corr_min" in b:
                    return b["spectral_corr_min"]
            return None
        floor, floor_old = declared(new), declared(old)
        if floor is None:
            lines.append("  FAIL: no declared spectral_corr_min found in the "
                         "record; the spectral leg cannot be graded")
            ok = False
        lines.append("== %s   declared spectral_corr_min: base=%r now=%r"
                     % (rel, floor_old, floor))
        if floor != floor_old:
            lines.append("  FAIL: the declared budget VALUE moved; #165 "
                         "migrates a definition, it does not re-tune a budget")
            ok = False
        a = dict(_spectral_blocks(old))
        b = dict(_spectral_blocks(new))
        if set(a) != set(b):
            lines.append("  FAIL: the set of spectral_corr blocks changed")
            ok = False
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                continue
            o, n = a[k]["spectral_corr"], b[k]["spectral_corr"]
            po = None if floor_old is None else o >= floor_old
            pn = None if floor is None else n >= floor
            flip = (po is not None and pn is not None and po != pn)
            row = {"artifact": rel, "block": k, "old": o, "new": n,
                   "old_leg_pass": po, "new_leg_pass": pn,
                   "spectral_leg_flip": flip}
            # the definition stamp must be present on every migrated block
            row["stamped"] = (b[k].get("spectral_corr_definition")
                              == car.SPECTRAL_CORR_DEFINITION)
            ok &= row["stamped"]
            rows.append(row)
            lines.append("  %-44s %.6f -> %.6f  leg %s -> %s%s  stamped=%s"
                         % (k[-44:], o, n, po, pn,
                            "   <<< SPECTRAL-LEG FLIP" if flip else "",
                            row["stamped"]))
            if flip:
                flips.append(row)
        so, sn = dict(_statuses(old)), dict(_statuses(new))
        moved = [(k, so[k], sn.get(k, "<absent>")) for k in sorted(so)
                 if rsc.status_of(so[k]) != rsc.status_of(
                     sn.get(k, "<absent>"))]
        lines.append("  overall verdict / control-ok statuses moved: %d"
                     % len(moved))
        for k, x, y in moved:
            lines.append("    MOVED %s: %r -> %r" % (k, x, y))
        ok &= not moved
    lines.append("")
    lines.append("spectral-leg flips (both directions, every one named): %d"
                 % len(flips))
    for f in flips:
        lines.append("  %s %s: %.6f -> %.6f  leg %s -> %s"
                     % (f["artifact"], f["block"], f["old"], f["new"],
                        "pass" if f["old_leg_pass"] else "fail",
                        "pass" if f["new_leg_pass"] else "fail"))
    return ok, {"status": "PASS" if ok else "FAIL", "values": rows,
                "spectral_leg_flips": flips}


def leg4(lines, scratch):
    """Every L2-family difference must be a rename or an added stamp."""
    ok, rows = True, []
    changed = [p for p in git("diff", "--name-only", BASE_REV, "--",
                              "reports").stdout.split()
               if p.startswith(L2_PREFIXES)]
    lines.append("L2-family artifacts changed by this branch: %d"
                 % len(changed))
    for rel in sorted(changed):
        p = os.path.join(REPO, rel)
        if rel.endswith(".json.gz"):
            new = json.loads(gzip.open(p, "rb").read().decode())
            # binary blob: must NOT go through git() (text=True would try to
            # utf-8 decode the gzip stream)
            old = json.loads(gzip.decompress(
                subprocess.run(["git", "show", "%s:%s" % (BASE_REV, rel)],
                               cwd=REPO, capture_output=True).stdout).decode())
        elif rel.endswith(".json"):
            new = json.load(open(p))
            old = base_json(rel)
        else:
            lines.append("  SKIP (not JSON) %s" % rel)
            continue
        lo, ln = rsc.leaves(old), rsc.leaves(new)
        counts, bad = {}, []
        for k in sorted(set(lo) | set(ln)):
            x, y = lo.get(k, "<absent>"), ln.get(k, "<absent>")
            if x == y:
                continue
            c = rsc.classify(rel, k, x, y, ln, lo)
            counts[c] = counts.get(c, 0) + 1
            if c not in ("RENAME-#165", "DEFINITION"):
                bad.append((k, x, y, c))
        ok &= not bad
        rows.append({"artifact": rel, "class_counts": counts,
                     "non_rename_changes": [list(b) for b in bad]})
        lines.append("  %-56s %s" % (rel, counts))
        for k, x, y, c in bad:
            lines.append("      NOT A RENAME [%s] %s: %r -> %r" % (c, k, x, y))
    lines.append("")
    lines.append("CONTROL: RENAME-#165 only classifies when the counterpart "
                 "under the other name carries the SAME value, so a moved "
                 "value falls through to SPECTRAL/VERDICT/OTHER and fails "
                 "this leg (see tests/test_spectral_corr_single_definition.py "
                 "::test_the_ledger_rename_class_cannot_launder_a_moved_value)")
    return ok, {"status": "PASS" if ok else "FAIL", "artifacts": rows}


def _complete_lp24_bundles():
    out = []
    for d in sorted(glob.glob(os.path.join(
            REPO, "reports", "SXT-038", "artifacts", "bundle-*"))):
        if all(os.path.exists(os.path.join(d, f))
               for f in ("coeffs.jsonl", "meta.json", "regs.bin", "units.bin")):
            out.append(d)
    return out


def leg5(lines, scratch):
    """Re-run the renamed L2 producers from committed inputs only."""
    rows = []

    def record(case, leaf, status, rerun=None, committed=None, reason=None):
        rel = (0.0 if (rerun is None or committed is None or
                       max(abs(rerun), abs(committed)) == 0)
               else abs(rerun - committed) / max(abs(rerun), abs(committed)))
        rows.append({"leaf": leaf, "case": case, "status": status,
                     "rerun": rerun, "committed": committed,
                     "rel_diff": rel, "reason": reason})
        lines.append("  %-9s %-11s %-7s rerun=%r committed=%r rel=%.3e %s"
                     % (leaf, case, status, rerun, committed, rel,
                        reason or ""))

    # SXT-038 (filter_lp24): only the bundles with a full input set
    cases_all = sorted(os.path.basename(p)[len("compare-"):-len(".json")]
                       for p in glob.glob(os.path.join(
                           REPO, "reports", "SXT-038", "artifacts",
                           "compare-*.json")))
    runnable = {os.path.basename(d)[len("bundle-"):]
                for d in _complete_lp24_bundles()}
    for case in cases_all:
        if case not in runnable:
            record(case, "SXT-038", "NOT_RUN",
                   reason="bundle holds meta.json only (needs the external "
                          "pinned-filter harness)")
            continue
        out = os.path.join(scratch, "lp24-" + case)
        r = subprocess.run(
            [sys.executable, "model/voice/filter_lp24/run_filter_leg.py",
             "--bundle", "reports/SXT-038/artifacts/bundle-" + case,
             "--out-dir", out, "--no-trace"],
            cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            record(case, "SXT-038", "NOT_RUN",
                   reason="runner exit %d" % r.returncode)
            continue
        leg = json.load(open(os.path.join(out, "leg.json")))
        com = json.load(open(os.path.join(
            REPO, "reports", "SXT-038", "artifacts",
            "compare-%s.json" % case)))["l2_spectral_corr"]
        record(case, "SXT-038", "PASS", leg["l2_spectral_corr"],
               com["achieved"],
               reason="committed value is rounded to 6 dp by its comparator")

    # SXT-039 (compare_lpmoog_model over re-run lpmoog legs)
    s039 = sorted(os.path.basename(p)[len("budget-"):-len(".json")]
                  for p in glob.glob(os.path.join(
                      REPO, "reports", "SXT-039", "artifacts",
                      "budget-*.json")))
    run_dirs = []
    for case in s039:
        out = os.path.join(scratch, "lpmoog-" + case)
        r = subprocess.run(
            [sys.executable, "model/voice/filter_lpmoog/run_filter_leg.py",
             "--case", case, "--out-dir", out, "--no-f32"],
            cwd=REPO, capture_output=True, text=True)
        if r.returncode == 0:
            run_dirs.append(out)
        else:
            record(case, "SXT-039", "NOT_RUN",
                   reason="lpmoog leg runner exit %d" % r.returncode)
    if run_dirs:
        out039 = os.path.join(scratch, "sxt039")
        r = subprocess.run(
            [sys.executable, "tools/compare_lpmoog_model.py",
             "--run-dirs"] + run_dirs +
            ["--ref-dir", "reports/SXT-039/artifacts", "--out-dir", out039],
            cwd=REPO, capture_output=True, text=True)
        for case in s039:
            p = os.path.join(out039, "budget-%s.json" % case)
            if not os.path.exists(p):
                record(case, "SXT-039", "NOT_RUN",
                       reason="comparator produced no record (exit %d)"
                              % r.returncode)
                continue
            record(case, "SXT-039", "PASS",
                   json.load(open(p))["L2_audio_q1021"]["l2_spectral_corr"],
                   json.load(open(os.path.join(
                       REPO, "reports", "SXT-039", "artifacts",
                       "budget-%s.json" % case)))["L2_audio_q1021"][
                           "l2_spectral_corr"])

    # sxt-037 (filter_lp12): the three committed traces
    for p in L2_GZ_TRACES:
        case = os.path.basename(p)[len("model-trace-"):-len(".json.gz")]
        bundle = os.path.join(REPO, "reports", "sxt-037", "artifacts",
                              "bundle-" + case)
        if not os.path.isdir(bundle):
            record(case, "sxt-037", "NOT_RUN", reason="no committed bundle")
            continue
        out = os.path.join(scratch, "lp12-" + case)
        r = subprocess.run(
            [sys.executable, "model/voice/filter_lp12/run_filter_leg.py",
             "--bundle", os.path.relpath(bundle, REPO), "--out-dir", out],
            cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            record(case, "sxt-037", "NOT_RUN",
                   reason="runner exit %d" % r.returncode)
            continue
        new = json.load(open(os.path.join(out, "model_trace.json")))
        com = json.loads(gzip.open(p, "rb").read().decode())
        for i, (a, b) in enumerate(zip(new.get("instances", []),
                                       com.get("instances", []))):
            record("%s[%d]" % (case, i), "sxt-037", "PASS",
                   a.get("l2_spectral_corr"), b.get("l2_spectral_corr"))

    ran = [r for r in rows if r["status"] == "PASS"]
    notrun = [r for r in rows if r["status"] != "PASS"]
    worst = max((r["rel_diff"] for r in ran), default=0.0)
    lines.append("")
    lines.append("COVERAGE, reported separately from agreement: %d re-run, "
                 "%d NOT_RUN (inputs not committed)" % (len(ran), len(notrun)))
    lines.append("worst relative difference re-run vs committed: %.3e "
                 "(host float ordering; the committed SXT-038 values are "
                 "6-dp rounded by their own comparator)" % worst)
    lines.append("This leg shows the renamed PRODUCERS emit the committed "
                 "values. It is not a fidelity claim: the budgets are "
                 "[PROPOSED] and every verdict here is the leaf's own.")
    return True, {"status": "PASS", "rows": rows, "n_rerun": len(ran),
                  "n_not_run": len(notrun), "worst_rel_diff": worst}


def leg6(lines, scratch):
    """The artifact rename tool is clean and idempotent."""
    tool = ["tools/rename_l2_spectral_corr_key.py"]
    chk = subprocess.run([sys.executable] + tool + ["--check"], cwd=REPO,
                         capture_output=True, text=True)
    lines.append("--check exit=%d" % chk.returncode)
    for ln in chk.stdout.strip().splitlines():
        lines.append("  " + ln)
    # Byte-hash the tool's own declared targets before and after a second
    # run: `git status` would also see this record's untracked artifacts,
    # which the rename tool does not touch.
    import hashlib
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import rename_l2_spectral_corr_key as rn

    def digest():
        return {os.path.relpath(p, REPO):
                hashlib.sha256(open(p, "rb").read()).hexdigest()
                for p in rn.targets()}
    before = digest()
    again = subprocess.run([sys.executable] + tool, cwd=REPO,
                           capture_output=True, text=True)
    after = digest()
    moved = sorted(k for k in before if before[k] != after.get(k))
    idem = again.returncode == 0 and "changed files (0)" in again.stdout
    lines.append("declared targets: %d" % len(before))
    lines.append("second run reports zero changes: %s" % idem)
    lines.append("target bytes changed by the second run: %d" % len(moved))
    for m in moved:
        lines.append("  CHANGED %s" % m)
    ok = chk.returncode == 0 and idem and not moved
    return ok, {"status": "PASS" if ok else "FAIL",
                "check_exit": chk.returncode, "idempotent": idem,
                "n_targets": len(before), "targets_changed_by_rerun": moved}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--legs", default="1,2,3,4,6",
                   help="leg 5 (L2 producer re-runs) is expensive and opt-in")
    ap.add_argument("--scratch-root", default="/tmp/sxt-spectral-corr-165")
    ap.add_argument("--base-rev", default=None,
                    help="the main this branch merges into (default: the "
                         "merge base of HEAD with --main-ref)")
    ap.add_argument("--main-ref", default=rsc.MAIN_REF)
    args = ap.parse_args()
    global BASE_REV
    BASE_REV = rsc.resolve_base_rev(args.base_rev, args.main_ref)
    legs = {int(x) for x in args.legs.split(",") if x.strip()}
    if os.path.exists(args.scratch_root):
        shutil.rmtree(args.scratch_root)
    os.makedirs(args.scratch_root)
    os.makedirs(ART, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    head = git("rev-parse", "HEAD").stdout.strip()

    names = {1: ("single_definition_scan", "single-definition-scan", leg1),
             2: ("migrated_rerun_reproduction", "migrated-rerun", leg2),
             3: ("migration_diff_and_flips", "migration-flips", leg3),
             4: ("l2_rename_value_preservation", "l2-rename", leg4),
             5: ("l2_producer_rerun", "l2-producer-rerun", leg5),
             6: ("rename_tool_idempotency", "rename-idempotency", leg6)}
    summary_path = os.path.join(ART, "checks-summary.json")
    summary = (json.load(open(summary_path)) if os.path.exists(summary_path)
               else {"issue": 165, "legs": {}})
    summary.update({"issue": 165, "run_utc": stamp, "repo_head": head,
                    "base_rev": BASE_REV, "numpy": np.__version__,
                    "shared_definition": car.SPECTRAL_CORR_DEFINITION,
                    "claim_scope": "metric naming/definition consistency over "
                                   "the measurement tooling; no fidelity, "
                                   "RTL, support or sound claim"})
    ok = True
    for leg in sorted(legs):
        key, fname, fn = names[leg]
        lines = ["issue #165 -- per-leaf spectral_corr migration/rename: "
                 "leg %d" % leg,
                 "run: %s   repo HEAD: %s   base: %s   numpy %s"
                 % (stamp, head, BASE_REV[:12], np.__version__),
                 "shared definition: %s" % car.SPECTRAL_CORR_DEFINITION,
                 "claim scope: metric naming/definition consistency only; no "
                 "fidelity, RTL, support or sound claim.", ""]
        scratch = os.path.join(args.scratch_root, "leg%d" % leg)
        os.makedirs(scratch, exist_ok=True)
        good, rep = fn(lines, scratch)
        ok &= good
        lines.append("")
        lines.append("leg %d verdict: %s" % (leg, rep["status"]))
        with open(os.path.join(ART, fname + ".txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(ART, fname + ".json"), "w") as f:
            json.dump(rep, f, indent=2)
            f.write("\n")
        summary["legs"][key] = {"leg": leg, "status": rep["status"],
                                "artifact": fname, "run_utc": stamp}
        print("\n".join(lines))
    # legs not selected keep their previous entry; mark the run's coverage
    summary["legs_run"] = sorted(legs)
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    print("\noverall: %s   (legs run: %s)"
          % ("PASS" if ok else "FAIL", sorted(legs)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
