#!/usr/bin/env python3
"""Shared census-blob, graphs-entry and git-blob helpers for leaf extractors.

Replaces the per-script private copies of `census_blob(rel)` and
`git_blob_sha1(path)` (issue #493) and of `graphs_entry(rel)` (issue #633).
Same drift hazard #154 addressed for the census-vs-graphs cross-check in
`tools/_census_graphs_common.py`.

Dependency-free on purpose: standard library plus `refusal` only. It must not
import `oracle/oracle_common.py` (heavy imports, pinned-interpreter re-exec).

`census_blob` raises `Refuse` when a preset path is absent from the census
CSV and `graphs_entry` raises `Refuse` when a preset path is absent from the
normalized graphs; neither ever returns None. These are tooling helpers
only: they make no fidelity, RTL or preset-quality claim.

Original to this repository (Apache-2.0).
"""

import csv
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from refusal import Refuse  # noqa: E402

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")


def census_blob(rel):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def graphs_entry(rel):
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel:
                return g
    raise Refuse(f"preset not in graphs.jsonl: {rel}")


def git_blob_sha1(path):
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
