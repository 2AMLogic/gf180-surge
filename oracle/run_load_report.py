#!/usr/bin/env python3
"""SXT-010: load every census manifest entry into the pinned native engine.

Loads all 3,561 .fxp entries from corpus/census-v0.1/corpus-manifest.json into
the pinned Surge XT engine (surgepy binding, 48 kHz) and records per-entry
normalized-load status. Files are never repaired; failures (including the
static census's unresolved `Percussion/Snare Tight.fxp`) are resolved only by
native loader behavior: the engine loads it or reports the engine's own error.

Outputs (under --repo-root, default: this script's repository):
  reports/sxt-010/load-report.csv
  reports/sxt-010/load-summary.json

The CSV is flushed per entry, and --start N resumes after a crash, so a hard
engine fault cannot silently drop entries.
"""

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oracle_common as oc  # noqa: E402

REPORT_SUBDIR = os.path.join("reports", "sxt-010")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--start", type=int, default=0, help="resume from entry index")
    ap.add_argument("--end", type=int, default=None, help="exclusive end index")
    ap.add_argument("--report-root", default=None, help="override output directory")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo_root)
    oc.reexec_under_pinned_python(repo)
    out_dir = args.report_root or os.path.join(repo, REPORT_SUBDIR)
    os.makedirs(out_dir, exist_ok=True)

    manifest = oc.load_census_manifest(repo)
    entries = manifest["entries"]
    end = args.end if args.end is not None else len(entries)

    # The oracle manifest pin must match the census pin; refuse to mix trees.
    with open(os.path.join(repo, "oracle", "manifest.json"), "r", encoding="utf-8") as f:
        oracle_manifest = json.load(f)
    if oracle_manifest["engine"]["commit"] != manifest["commit"]:
        print(
            f"REFUSING: oracle manifest pins {oracle_manifest['engine']['commit']} "
            f"but census manifest pins {manifest['commit']}",
            file=sys.stderr,
        )
        return 2

    oc.apply_engine_env()
    surgepy = oc.import_surgepy()
    sr = 48000
    s = surgepy.createSurge(sr)
    engine_commit = oracle_manifest["engine"]["commit"]

    csv_path = os.path.join(out_dir, "load-report.csv")
    write_header = args.start == 0 or not os.path.exists(csv_path)
    csv_f = open(csv_path, "a", newline="", encoding="utf-8")
    writer = csv.writer(csv_f)
    if write_header:
        writer.writerow(
            [
                "index",
                "path",
                "bank",
                "size",
                "census_blob_sha1",
                "actual_blob_sha1",
                "blob_match",
                "status",
                "detail",
                "elapsed_ms",
                "engine_commit",
                "sample_rate",
            ]
        )
        csv_f.flush()

    t_all = time.time()
    n = 0
    for i in range(args.start, end):
        e = entries[i]
        rel = e["path"]
        bank = "factory" if "patches_factory" in rel else "contributor"
        fxp = os.path.join(oc.data_home(), os.path.relpath(rel, "resources/data"))
        detail = ""
        t0 = time.time()
        try:
            actual_sha = oc.git_blob_sha1(fxp)
        except FileNotFoundError:
            writer.writerow([i, rel, bank, e["size"], e["git_blob_sha1"], "", "False",
                             "missing_file", "file absent from pinned tree",
                             0, engine_commit, sr])
            csv_f.flush()
            continue
        if actual_sha != e["git_blob_sha1"] or os.path.getsize(fxp) != e["size"]:
            print(f"REFUSING: corpus tree mismatch at index {i}: {rel}", file=sys.stderr)
            csv_f.flush()
            csv_f.close()
            return 3
        try:
            s.allNotesOff()
            ok = bool(s.loadPatch(fxp))
            status = "ok" if ok else "load_false"
        except Exception as exc:  # engine's own error, recorded verbatim
            ok = False
            status = "exception"
            detail = f"{type(exc).__name__}: {exc}"
        elapsed_ms = int((time.time() - t0) * 1000)
        writer.writerow([i, rel, bank, e["size"], e["git_blob_sha1"], actual_sha,
                         "True", status, detail, elapsed_ms, engine_commit, sr])
        csv_f.flush()
        n += 1
        if n % 250 == 0:
            print(f"  {i + 1}/{end} loaded ({time.time() - t_all:.1f}s)", flush=True)

    csv_f.flush()
    csv_f.close()

    if end >= len(entries):
        summarize(out_dir, csv_path, engine_commit, sr, time.time() - t_all)
    return 0


def summarize(out_dir, csv_path, engine_commit, sr, total_wall_s):
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    counts = {}
    failures = []
    snare = None
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] != "ok":
            failures.append({"path": r["path"], "status": r["status"], "detail": r["detail"]})
        if r["path"].endswith("Percussion/Snare Tight.fxp"):
            snare = {
                "path": r["path"],
                "native_verdict": "loads_natively" if r["status"] == "ok" else r["status"],
                "detail": r["detail"],
                "note": "resolved by native loader behavior only; file not repaired",
            }
    summary = {
        "issue": "SXT-010",
        "engine_commit": engine_commit,
        "sample_rate": sr,
        "census_manifest": "corpus/census-v0.1/corpus-manifest.json",
        "census_source_lock": "corpus/census-v0.1/source-lock.json",
        "entries_total": len(rows),
        "counts": counts,
        "successes": counts.get("ok", 0),
        "failures_count": len(failures),
        "failures": failures,
        "snare_tight": snare,
        "wall_seconds": round(total_wall_s, 1),
        "note": (
            "Load coverage only: this report establishes that the pinned native "
            "loader accepted or rejected each file. It makes no audio-support, "
            "fidelity, or preset-quality claim."
        ),
    }
    with open(os.path.join(out_dir, "load-summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: summary[k] for k in ("entries_total", "counts", "snare_tight")}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
