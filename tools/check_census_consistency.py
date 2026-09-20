#!/usr/bin/env python3
"""Internal bookkeeping consistency check for corpus/census-v0.1/.

Verifies only that the census bookkeeping files agree with each other:
  - corpus-manifest.json entry count == results/per-preset.csv data-row count
    == results/summary.json stated total
  - factory / contributor denominators equal the documented 641 / 2920, and
    per-preset.csv bank counts agree with summary.json
  - the known unresolved parser failure (Snare Tight.fxp) is still present as
    a recorded failure row in both files, not silently dropped
  - summary.json and per-preset.csv agree on the unresolved count

This is NOT a support claim, NOT a sound-quality claim, and NOT a
preset-coverage claim. The static census is an inventory and prioritization
aid only (see corpus/census-v0.1/README.md and AGENTS.md).

Python 3 standard library only.
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "corpus" / "census-v0.1" / "corpus-manifest.json"
SUMMARY = REPO_ROOT / "corpus" / "census-v0.1" / "results" / "summary.json"
PER_PRESET = REPO_ROOT / "corpus" / "census-v0.1" / "results" / "per-preset.csv"

EXPECTED_FACTORY_DENOMINATOR = 641
EXPECTED_CONTRIBUTOR_DENOMINATOR = 2920
UNRESOLVED_STATUS = "unresolved_by_static_parser"
KNOWN_UNRESOLVED_MARKER = "Snare Tight.fxp"
CAVEAT = (
    "NOTE: bookkeeping consistency only. This is not a support claim, not a "
    "sound-quality claim, and not a preset-coverage claim."
)


class CheckError(Exception):
    pass


def load_manifest_entries():
    try:
        with MANIFEST.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot read {MANIFEST.relative_to(REPO_ROOT)}: {exc}") from exc
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise CheckError("corpus-manifest.json: expected a non-empty 'entries' list")
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("path"):
            raise CheckError(f"corpus-manifest.json: entries[{i}] has no 'path'")
    return entries


def load_summary():
    try:
        with SUMMARY.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot read {SUMMARY.relative_to(REPO_ROOT)}: {exc}") from exc


def load_csv_rows():
    try:
        with PER_PRESET.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            missing = sorted({"path", "bank", "status", "error"} - set(header))
            if missing:
                raise CheckError(
                    "per-preset.csv: missing required column(s): " + ", ".join(missing)
                )
            rows = list(reader)
    except OSError as exc:
        raise CheckError(f"cannot read {PER_PRESET.relative_to(REPO_ROOT)}: {exc}") from exc
    if not rows:
        raise CheckError("per-preset.csv: no data rows")
    return rows


def summary_value(summary, keys):
    node = summary
    walked = []
    for key in keys:
        walked.append(key)
        if not isinstance(node, dict) or key not in node:
            raise CheckError(f"summary.json: missing key path '{' > '.join(walked)}'")
        node = node[key]
    return node


def run_checks():
    failures = []
    entries = load_manifest_entries()
    rows = load_csv_rows()
    summary = load_summary()

    manifest_count = len(entries)
    csv_count = len(rows)
    stated_total = summary_value(summary, ["groups", "combined", "manifest_presets"])
    content_verified = summary.get("content_verified_against_git_blob_manifest")

    if not (manifest_count == csv_count == stated_total):
        failures.append(
            f"total mismatch: corpus-manifest.json entries={manifest_count}, "
            f"per-preset.csv data rows={csv_count}, "
            f"summary.json groups.combined.manifest_presets={stated_total}"
        )
    if content_verified != manifest_count:
        failures.append(
            f"summary.json content_verified_against_git_blob_manifest="
            f"{content_verified!r} != manifest entry count {manifest_count}"
        )

    manifest_paths = [entry["path"] for entry in entries]
    if len(set(manifest_paths)) != len(manifest_paths):
        failures.append("corpus-manifest.json contains duplicate paths")

    factory_stated = summary_value(summary, ["groups", "factory", "manifest_presets"])
    contributor_stated = summary_value(
        summary, ["groups", "contributor", "manifest_presets"]
    )
    if factory_stated != EXPECTED_FACTORY_DENOMINATOR:
        failures.append(
            f"summary.json groups.factory.manifest_presets={factory_stated} "
            f"!= documented denominator {EXPECTED_FACTORY_DENOMINATOR}"
        )
    if contributor_stated != EXPECTED_CONTRIBUTOR_DENOMINATOR:
        failures.append(
            f"summary.json groups.contributor.manifest_presets={contributor_stated} "
            f"!= documented denominator {EXPECTED_CONTRIBUTOR_DENOMINATOR}"
        )

    bank_counts = Counter(row.get("bank", "") for row in rows)
    for bank in sorted(bank_counts):
        if bank not in {"factory", "contributor"}:
            failures.append(f"per-preset.csv: unexpected bank value {bank!r}")
    csv_factory = bank_counts.get("factory", 0)
    csv_contributor = bank_counts.get("contributor", 0)
    if csv_factory != factory_stated:
        failures.append(
            f"per-preset.csv factory bank rows={csv_factory} != summary.json "
            f"groups.factory.manifest_presets={factory_stated}"
        )
    if csv_contributor != contributor_stated:
        failures.append(
            f"per-preset.csv contributor bank rows={csv_contributor} != summary.json "
            f"groups.contributor.manifest_presets={contributor_stated}"
        )

    summary_unresolved = summary.get("unresolved")
    if not isinstance(summary_unresolved, list):
        raise CheckError("summary.json: 'unresolved' must be a list")
    summary_unresolved_paths = [
        item.get("path") if isinstance(item, dict) else None
        for item in summary_unresolved
    ]
    if any(not path for path in summary_unresolved_paths):
        failures.append("summary.json: 'unresolved' contains an entry without a 'path'")

    combined_unresolved = summary_value(summary, ["groups", "combined", "unresolved_presets"])
    factory_unresolved = summary_value(summary, ["groups", "factory", "unresolved_presets"])
    contributor_unresolved = summary_value(
        summary, ["groups", "contributor", "unresolved_presets"]
    )
    if factory_unresolved + contributor_unresolved != combined_unresolved:
        failures.append(
            f"summary.json: factory({factory_unresolved}) + contributor"
            f"({contributor_unresolved}) unresolved != combined({combined_unresolved})"
        )
    if combined_unresolved != len(summary_unresolved):
        failures.append(
            f"summary.json: groups.combined.unresolved_presets={combined_unresolved} "
            f"!= len(unresolved)={len(summary_unresolved)}"
        )

    csv_unresolved = [row for row in rows if row.get("status") == UNRESOLVED_STATUS]
    if len(csv_unresolved) != combined_unresolved:
        failures.append(
            f"unresolved count mismatch: per-preset.csv rows with status "
            f"'{UNRESOLVED_STATUS}'={len(csv_unresolved)} != summary.json "
            f"groups.combined.unresolved_presets={combined_unresolved}"
        )
    csv_unresolved_paths = sorted(row["path"] for row in csv_unresolved)
    known_paths = sorted(p for p in summary_unresolved_paths if p)
    if csv_unresolved_paths != known_paths:
        failures.append(
            "unresolved path sets differ between per-preset.csv and summary.json: "
            f"csv-only={sorted(set(csv_unresolved_paths) - set(known_paths))}, "
            f"summary-only={sorted(set(known_paths) - set(csv_unresolved_paths))}"
        )
    for row in csv_unresolved:
        if not (row.get("error") or "").strip():
            failures.append(
                f"per-preset.csv: unresolved row {row.get('path')!r} has an empty error"
            )

    snare_csv = [row for row in csv_unresolved if KNOWN_UNRESOLVED_MARKER in row["path"]]
    if not snare_csv:
        failures.append(
            f"per-preset.csv: no '{UNRESOLVED_STATUS}' row whose path contains "
            f"{KNOWN_UNRESOLVED_MARKER!r}; the known parser-failure row is missing"
        )
    elif snare_csv[0].get("bank") != "factory":
        failures.append(
            f"per-preset.csv: known unresolved row {snare_csv[0]['path']!r} has "
            f"bank={snare_csv[0].get('bank')!r}, expected 'factory'"
        )

    snare_summary = [
        path
        for path in summary_unresolved_paths
        if path and KNOWN_UNRESOLVED_MARKER in path
    ]
    if not snare_summary:
        failures.append(
            f"summary.json: 'unresolved' has no entry whose path contains "
            f"{KNOWN_UNRESOLVED_MARKER!r}; the known parser failure is silently dropped"
        )

    return failures, {
        "total": manifest_count,
        "factory": csv_factory,
        "contributor": csv_contributor,
        "unresolved": len(csv_unresolved),
    }


def main():
    try:
        failures, stats = run_checks()
    except CheckError as exc:
        print(f"FAIL: {exc}")
        print(CAVEAT)
        return 1
    if failures:
        print("FAIL: census bookkeeping is internally inconsistent:")
        for failure in failures:
            print(f"  - {failure}")
        print(CAVEAT)
        return 1
    print(
        f"PASS: census bookkeeping internally consistent: {stats['total']} manifest "
        f"entries = {stats['total']} per-preset.csv rows = stated total "
        f"(factory {stats['factory']}, contributor {stats['contributor']}, "
        f"unresolved {stats['unresolved']} incl. known '{KNOWN_UNRESOLVED_MARKER}' row)"
    )
    print(CAVEAT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
