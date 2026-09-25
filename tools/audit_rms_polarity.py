#!/usr/bin/env python3
"""SXT-095 tooling audit: pre-fix shared-comparator outputs for inverted
``rms_diff_dbfs`` budget flags (issue #95, follow-up from the SXT-040 judge
review in PR #92).

Background
----------
``tools/compare_audio_reference.py`` reported its rms budget leg as
``rms_diff_dbfs >= budget`` -- inverted. ``rms_diff_dbfs`` is the RMS level of
the *difference* waveform in dBFS (more negative = quieter diff = better);
the budget ``<= -46 dBFS`` requires the diff to be at least ~46 dB below full
scale, so the correct predicate is ``rms_diff_dbfs <= budget``. PR #92 fixed
the predicate (commit c0658747233c7a8c02036b1e178af9d8a75f105e) for the
SXT-040 (Sine) leaf's own evidence, and flagged every other leaf's
pre-existing comparator JSON as suspect (see that commit's message, "the
historical rms flags in pre-2026-09-24 comparator JSONs on other leaves are
routed to a tool-lineage audit (follow-up issue)").

This script is that audit. It is read-only: it does not modify
``tools/compare_audio_reference.py`` (already fixed) or any committed
evidence file. It walks every committed JSON file under ``reports/``,
recursively locates every "row" whose schema is the *exact* flat output shape
of ``tools/compare_audio_reference.py`` (so leaf-specific tools that
independently reimplement the same field names -- e.g.
``compare_chorus_reference.py``, ``compare_fx_reference.py``, both already
correct-polarity and confirmed immune -- are not swept in by accident), and
recomputes the rms leg from the still-committed ``rms_diff_dbfs`` value and
budget. The max-abs and spectral-corr legs are never touched: they are
carried through unchanged from the committed row.

For every row this reports:
  * the committed ("old") rms flag and verdict,
  * the recomputed ("correct") rms flag under ``rms_diff_dbfs <= budget``,
  * whether the rms flag flips,
  * whether the *overall verdict* flips when only the rms leg is corrected
    (max-abs/spectral legs held at their committed values).

Per the issue's stop/escalate condition: this script only *reports* verdict
flips. It never rewrites a committed evidence file. A verdict flip on a
landed leaf is a stop condition routed to a follow-up issue, not something
this audit resolves.

Usage:
  python3 tools/audit_rms_polarity.py [--repo-root ROOT] [--out PATH]

Exits 0 always (this is a report, not a gate); the report JSON records
counts and flip flags for downstream routing.
"""

import argparse
import json
import os
import sys

# The exact key set written by tools/compare_audio_reference.py's own
# ``metrics`` dict (SXT-022, 2b71c94d8a766f348cb384f99df3131b584ba39a). A
# candidate dict must contain all of these keys AND lack the wrapper keys
# used by independent per-leaf tools (compare_chorus_reference.py,
# compare_fx_reference.py) that reuse the same field *names* inside a
# ``channels``/``leaf`` wrapper but compute the rms leg themselves (already
# correct polarity, confirmed immune -- not audited here).
SHARED_COMPARATOR_KEYS = {
    "frames",
    "ref_peak_lsb",
    "model_peak_lsb",
    "max_abs_diff_lsb",
    "rms_diff_lsb",
    "rms_diff_dbfs",
    "rms_diff_at_shift0_lsb",
    "best_shift",
    "rms_diff_at_best_shift_lsb",
    "spectral_corr",
    "proposed_budgets",
    "proposed_budget_results",
    "verdict",
}
WRAPPER_KEYS_EXCLUDE = {"channels", "leaf"}

FIX_COMMIT = "c0658747233c7a8c02036b1e178af9d8a75f105e"


def rms_leg_passes(rms_diff_dbfs, budget_dbfs):
    """The corrected shared-comparator rms predicate.

    Mirrors tools/compare_audio_reference.py post-PR#92:
    ``rms_diff_dbfs <= budget_dbfs`` (more negative rms_diff_dbfs is a
    quieter, better-matching diff). This is intentionally a one-line pure
    function so the unit tests below fail loudly if it is ever re-inverted.
    """
    return rms_diff_dbfs <= budget_dbfs


def find_rows(obj, path=""):
    """Recursively locate every dict in ``obj`` whose keys are a superset of
    SHARED_COMPARATOR_KEYS and which is not a wrapper produced by an
    independent per-leaf tool. Returns a list of (json_path, row_dict).
    """
    out = []
    if isinstance(obj, dict):
        if (SHARED_COMPARATOR_KEYS.issubset(obj.keys())
                and not (WRAPPER_KEYS_EXCLUDE & obj.keys())):
            out.append((path or "$", obj))
        else:
            for k in sorted(obj.keys()):
                out.extend(find_rows(obj[k], f"{path}/{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(find_rows(v, f"{path}[{i}]"))
    return out


def audit_row(rel_file, json_path, row):
    rms_value = row["rms_diff_dbfs"]
    budget = row["proposed_budgets"]["rms_diff_dbfs"]
    old_rms_flag = row["proposed_budget_results"]["rms_diff_dbfs"]
    old_max_abs_flag = row["proposed_budget_results"]["max_abs_diff_lsb"]
    old_spectral_flag = row["proposed_budget_results"]["spectral_corr"]
    old_verdict = row["verdict"]

    correct_rms_flag = rms_leg_passes(rms_value, budget)
    # Only the rms leg is recomputed; max-abs/spectral legs are carried
    # through at their committed values (never touched by this audit).
    recomputed_verdict_pass = bool(
        old_max_abs_flag and correct_rms_flag and old_spectral_flag)
    old_verdict_pass = old_verdict.strip().upper().startswith("PASS")

    return {
        "file": rel_file,
        "json_path": json_path,
        "rms_diff_dbfs": rms_value,
        "rms_budget_dbfs": budget,
        "old_rms_flag": bool(old_rms_flag),
        "correct_rms_flag": bool(correct_rms_flag),
        "rms_flag_flipped": bool(old_rms_flag) != bool(correct_rms_flag),
        "old_max_abs_flag": bool(old_max_abs_flag),
        "old_spectral_flag": bool(old_spectral_flag),
        "old_verdict": old_verdict,
        "old_verdict_pass": old_verdict_pass,
        "recomputed_verdict_pass": recomputed_verdict_pass,
        "verdict_flipped": old_verdict_pass != recomputed_verdict_pass,
    }


def scan(repo_root, reports_subdir="reports"):
    reports_root = os.path.join(repo_root, reports_subdir)
    rows = []
    files_scanned = 0
    files_with_rows = 0
    parse_errors = []
    json_files = []
    for dirpath, _dirnames, filenames in os.walk(reports_root):
        for fn in filenames:
            if fn.endswith(".json"):
                json_files.append(os.path.join(dirpath, fn))
    json_files.sort()

    for path in json_files:
        rel_file = os.path.relpath(path, repo_root)
        files_scanned += 1
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            parse_errors.append({"file": rel_file, "error": str(exc)})
            continue
        found = find_rows(doc)
        if not found:
            continue
        files_with_rows += 1
        for json_path, row in found:
            rows.append(audit_row(rel_file, json_path, row))

    rows.sort(key=lambda r: (r["file"], r["json_path"]))
    return rows, files_scanned, files_with_rows, parse_errors


def build_report(repo_root):
    rows, files_scanned, files_with_rows, parse_errors = scan(repo_root)
    rms_flips = [r for r in rows if r["rms_flag_flipped"]]
    verdict_flips = [r for r in rows if r["verdict_flipped"]]
    leaves_with_verdict_flip = sorted({
        r["file"].split(os.sep)[1] if os.sep in r["file"] else r["file"]
        for r in verdict_flips
    })

    report = {
        "schema_version": 1,
        "tool": "tools/audit_rms_polarity.py",
        "issue": 95,
        "fix_commit": FIX_COMMIT,
        "corrected_predicate": "rms_diff_dbfs <= proposed_budgets.rms_diff_dbfs",
        "scanned_root": "reports",
        "scope_note": (
            "Only rows whose JSON schema exactly matches the shared "
            "tools/compare_audio_reference.py output (flat metrics dict, "
            "no channels/leaf wrapper) are audited. Independent per-leaf "
            "comparators (compare_chorus_reference.py, "
            "compare_fx_reference.py) reuse the same field names but "
            "compute the rms leg themselves with correct polarity and are "
            "not in scope (confirmed immune)."
        ),
        "files_scanned": files_scanned,
        "files_with_rows": files_with_rows,
        "parse_errors": parse_errors,
        "rows_total": len(rows),
        "rows_rms_flag_flipped": len(rms_flips),
        "rows_verdict_flipped": len(verdict_flips),
        "leaves_with_verdict_flip": leaves_with_verdict_flip,
        "stop_escalate_note": (
            "Any non-empty leaves_with_verdict_flip is a STOP condition "
            "(issue #95 stop/escalate clause): this audit reports the flip "
            "but does not re-grade the affected leaf's evidence. Route the "
            "re-grade through that leaf's own PR or a visible follow-up "
            "issue." if verdict_flips else
            "No verdict flips found in this run."
        ),
        "rows": rows,
    }
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--repo-root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="repository root (default: parent of this file's tools/ dir)")
    ap.add_argument(
        "--out",
        default=None,
        help="write the JSON report here (default: print to stdout only)")
    args = ap.parse_args()

    report = build_report(args.repo_root)
    text = json.dumps(report, indent=2, sort_keys=False)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
