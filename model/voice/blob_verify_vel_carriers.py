#!/usr/bin/env python3
"""SXT-036 (#70) blob-verify-carriers leg: hash the four carrier `.fxp`
payloads this leaf names against the committed census `git_blob_sha1`,
using the ACTUAL bytes inside the pinned-engine checkout (`ORACLE_SURGE_DIR`,
`resources/data/`) -- not a cross-check between two committed artifacts
(that weaker check is what `model/voice/audit_vel_carriers.py` already does
from `graphs.jsonl` + the census CSV alone, oracle-independent).

This is the cheapest leg `tools/vel_oracle_status.py` names
(`gate: GATE_CHECKOUT`, "pinned checkout only (no built surgepy needed)"):
it needs the pinned engine's `resources/data/` tree on disk, nothing built.
It therefore works under EITHER accepted oracle provisioning shape
(git-worktree checkout, or a sha256-verified prebuilt install, #232) --
`resources/data/` is present identically in both (oracle/fetch-and-build.sh's
`--prebuilt` layout note).

Carriers (the three named by #70's "Fixtures and oracle" section, plus the
fixture carrier this leaf actually uses, Attacky.fxp):
  Bad News.fxp, Rainy Day Dreamaway.fxp, House Of Chords.fxp, Attacky.fxp

Fail-closed: refuses (exit 2) if ORACLE_SURGE_DIR is unset/absent, if a
carrier is missing from the census, or if a carrier file is missing from the
checkout. A blob MISMATCH is not a refusal -- it is the result this leg
exists to report, so it is recorded as `verified: false` per-carrier with an
overall non-zero exit, never silently passed over.

Usage:
  python3 model/voice/blob_verify_vel_carriers.py \
      --out reports/SXT-036/artifacts/blob-verify-carriers.json
"""

import argparse
import csv
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402
from refusal import Refuse  # noqa: E402

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")

CARRIERS = [
    ("resources/data/patches_3rdparty/Bluelight/Pads/Bad News.fxp",
     "named carrier (#70 Fixtures and oracle)"),
    ("resources/data/patches_3rdparty/Bluelight/Pads/Rainy Day Dreamaway.fxp",
     "named carrier (#70 Fixtures and oracle)"),
    ("resources/data/patches_3rdparty/Damon Armani/Pads/House Of Chords.fxp",
     "named carrier (#70 Fixtures and oracle)"),
    ("resources/data/patches_factory/Basses/Attacky.fxp",
     "fixture carrier actually used by model/voice/run_vel_model.py "
     "(SXT-035/SXT-032 substitution convention; the three named carriers "
     "are outside the landed classic-voice class)"),
]


def subprocess_is_git_worktree(engine_dir):
    r = subprocess.run(["git", "-C", engine_dir, "rev-parse",
                        "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def census_blobs():
    out = {}
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["path"]] = row["git_blob_sha1"]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-036", "artifacts", "blob-verify-carriers.json"))
    args = ap.parse_args()

    engine_dir = oc.engine_dir()
    if not engine_dir or not os.path.isdir(engine_dir):
        raise Refuse(
            f"ORACLE_SURGE_DIR not set to a present directory ({engine_dir!r}); "
            "this leg needs the pinned-engine checkout (git-worktree or "
            "sha256-verified prebuilt, #232), not surgepy")
    data_home = oc.data_home()
    if not os.path.isdir(data_home):
        raise Refuse(f"{data_home!r} not found under the checkout; this is "
                     "not a usable pinned-engine provisioning")

    census = census_blobs()
    results = []
    all_verified = True
    for rel, note in CARRIERS:
        if rel not in census:
            raise Refuse(f"carrier not in census: {rel}")
        expected = census[rel]
        on_disk = os.path.join(data_home, rel[len("resources/data/"):])
        if not os.path.exists(on_disk):
            raise Refuse(f"carrier missing from checkout: {on_disk}")
        actual = oc.git_blob_sha1(on_disk)
        ok = actual == expected
        all_verified = all_verified and ok
        results.append({
            "path": rel, "note": note,
            "census_blob_sha1": expected,
            "checkout_blob_sha1": actual,
            "verified": ok,
        })

    is_git = subprocess_is_git_worktree(engine_dir)
    out = {
        "schema_version": 1,
        "issue": "SXT-036",
        "leg": "blob-verify-carriers",
        "gate": "pinned checkout only (no built surgepy needed)",
        "engine_pin": "58914e59c608ed4384ba6002e44c3465c58b2e71",
        "provisioning": "git-worktree" if is_git else (
            "not-a-git-worktree (sha256-verification against "
            "oracle/manifest.json's prebuilt.<platform> entry is tracked "
            "separately by tools/vel_oracle_status.py, not duplicated here)"),
        "carriers": results,
        "all_verified": all_verified,
        "rule": "a blob mismatch is a finding about this host's checkout, "
                "never silently passed over -- recorded per-carrier, not "
                "collapsed into one boolean",
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if all_verified else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
