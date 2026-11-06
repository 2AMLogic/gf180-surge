#!/usr/bin/env python3
"""Shared census-blob lookup and git-blob hash for leaf extractors/renderers.

Replaces the per-script private copies of `census_blob(rel)` and
`git_blob_sha1(path)` (issue #493). Same drift hazard #154 addressed for the
census-vs-graphs cross-check in `tools/_census_graphs_common.py`.

Dependency-free on purpose: standard library plus `refusal` only. It must not
import `oracle/oracle_common.py` (heavy imports, pinned-interpreter re-exec).

`census_blob` raises `Refuse` when a preset path is absent from the census
CSV; it never returns None. This is a tooling helper only: it makes no
fidelity, RTL or preset-quality claim.

Original to this repository (Apache-2.0).
"""

import csv
import hashlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from refusal import Refuse  # noqa: E402

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")


def census_blob(rel):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def git_blob_sha1(path):
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
