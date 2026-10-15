#!/usr/bin/env python3
"""Issue #456 one-shot verification driver (RETENTION + coverage gate on the
committed traces). Original to this repository (Apache-2.0).

Runs, against the COMMITTED sxt-024 traces:

  1. RETENTION: the pre-#456 tool (git OLD_TOOL_COMMIT:tools/
     compare_reverb_model.py -- a FIXED commit, never HEAD, which on the
     committed branch is the gated tool itself -- loaded from its blob, output redirected to a temp dir) vs the current
     tool -- every per-case field the old tool wrote must be reproduced
     exactly (float-exact), with `status` the only new per-case field; both
     must also agree with the COMMITTED comparison/sweep-t60.json.
  2. GATE: the current tool's aggregate on the committed traces -- required
     coverage, per-case statuses (the decay -4 case is excitation-bounded:
     both agreement checks NOT_RUN there), coverage and verdict.

Writes RETENTION.txt (this protocol + result) and committed-traces-
coverage.json next to itself. Never touches reports/sxt-024/comparison/.

Usage: python3 reports/sxt-024/artifacts/issue-456/driver.py <repo_root>
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                       os.path.dirname(os.path.dirname(os.path.dirname(
                           os.path.dirname(os.path.dirname(
                               os.path.abspath(__file__)))))))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "tools"))
import compare_reverb_model as crm  # noqa: E402


# last origin/main commit touching tools/compare_reverb_model.py before #456
OLD_TOOL_COMMIT = "e4c25bfc5aec129c0113ce74236aa00cf32aa521"


def load_old_module():
    blob = subprocess.run(
        ["git", "-C", REPO, "show",
         OLD_TOOL_COMMIT + ":tools/compare_reverb_model.py"],
        check=True, capture_output=True).stdout
    if b"REQUIRED_SWEEP_CASES" in blob:
        raise SystemExit("pinned old tool already carries the #456 gate")
    path = os.path.join(tempfile.mkdtemp(prefix="issue456-old-"),
                        "compare_reverb_model_old.py")
    with open(path, "wb") as f:
        f.write(blob)
    spec = importlib.util.spec_from_file_location("crm_old_issue456", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # the old blob derives REPO/TRACES from its temp __file__: point the
    # input at the committed traces and the output at a temp dir, so the
    # committed comparison/ record is never touched
    mod.REPO = tempfile.mkdtemp(prefix="issue456-oldout-")
    mod.TRACES = crm.TRACES
    # the old tool does not create its output directory
    os.makedirs(os.path.join(mod.REPO, "reports", "sxt-024", "comparison"))
    return mod


def main():
    lines = []
    old = load_old_module()
    old_rc = old.cmd_sweep(None)
    old_out = os.path.join(old.REPO, "reports", "sxt-024", "comparison",
                           "sweep-t60.json")
    old_results = json.load(open(old_out))

    new_out = os.path.join(tempfile.mkdtemp(prefix="issue456-new-"))
    new_rc = crm.cmd_sweep(type("A", (), {"traces_dir": crm.TRACES,
                                          "out_dir": new_out})())
    new_results = json.load(open(os.path.join(new_out, "sweep-t60.json")))
    coverage = json.load(open(os.path.join(new_out,
                                           "sweep-t60-coverage.json")))

    committed = json.load(open(os.path.join(
        REPO, "reports", "sxt-024", "comparison", "sweep-t60.json")))

    lines.append("issue #456 -- decay-sweep coverage gate: retention check")
    lines.append("")
    lines.append("environment: %s / numpy %s" % (sys.version.split()[0],
                                                 __import__("numpy").__version__))
    lines.append("old tool: git %s:tools/compare_reverb_model.py (fixed "
                 "commit, not HEAD; loaded from its blob; output redirected "
                 "to a temp dir)" % OLD_TOOL_COMMIT)
    lines.append("new tool: worktree tools/compare_reverb_model.py")
    lines.append("inputs : the committed reports/sxt-024/traces/ (unchanged)")
    lines.append("")
    lines.append("old exit: %d   new exit: %d" % (old_rc, new_rc))
    lines.append("old per-case count: %d   new: %d   committed: %d"
                 % (len(old_results), len(new_results), len(committed)))

    ok = True
    assert old_rc == 0, old_rc
    assert new_rc == 0, new_rc
    assert [r["trace"] for r in old_results] == \
        [r["trace"] for r in new_results] == \
        [r["trace"] for r in committed]
    for o, n, c in zip(old_results, new_results, committed):
        assert set(n) - set(o) == {"status"}, (o.get("trace"), set(n) - set(o))
        for k in o:
            if o[k] != n[k]:
                ok = False
                lines.append("OLD-NEW DIFF %s %s: %r != %r"
                             % (o["trace"], k, o[k], n[k]))
            if o[k] != c[k]:
                ok = False
                lines.append("OLD-COMMITTED DIFF %s %s: %r != %r"
                             % (o["trace"], k, o[k], c[k]))
        assert n["status"] == "PASS" or o["trace"] == "sweepmdecaymm4"
    lines.append("")
    lines.append("RETENTION: %s -- every pre-#456 per-case field is "
                 "reproduced exactly by the new tool and matches the "
                 "committed record; `status` is the only new per-case field"
                 % ("PASS" if ok else "FAIL"))
    lines.append("")
    lines.append("GATE on the committed traces (aggregate):")
    lines.append("  verdict : %s" % coverage["verdict"])
    lines.append("  coverage: %s" % coverage["coverage"])
    lines.append("  required %d / discovered %d / graded %d / unmeasurable %d"
                 % (coverage["cases_required"], coverage["cases_discovered"],
                    coverage["cases_graded"], coverage["cases_not_run"]))
    for c in coverage["cases"]:
        lines.append("  %-22s %-8s graded=%s not_run=%s%s"
                     % (c["trace"], c["status"], ",".join(c["graded_checks"])
                        or "-",
                        ",".join(c["not_run_checks"]) or "-",
                        "" if not c["reason"] else "  # " + c["reason"]))
    lines.append("")
    lines.append("The decay -4 case (sweepmdecaymm4) is excitation-bounded: "
                 "its tail falls below the -100 dBFS measurement floor, so "
                 "both agreement checks are NOT_RUN there. Before #456 that "
                 "vacuity was invisible (all(...) over non-None values); the "
                 "gate records it as an explicit per-case NOT_RUN and keeps "
                 "coverage partial. The committed sweep verdict is not "
                 "rewritten by this change.")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(HERE, "RETENTION.txt"), "w") as f:
        f.write(text)
    with open(os.path.join(HERE, "committed-traces-coverage.json"), "w") as f:
        json.dump(coverage, f, indent=2, sort_keys=True)
        f.write("\n")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
