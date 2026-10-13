#!/usr/bin/env python3
"""Issue #373: every committed NumPy stamp is inventoried and classified.

The inventory (docs/numpy-stamp-inventory.md) classifies each record that
stamps a NumPy version as Live / Historical provenance / Declared
cross-environment, so #354 can pick a CI pin without conflating oracle
runtime provenance with a CI obligation. These tests are the failure
control: a record whose stamp is missing from the inventory, or a row
classified without justification, fails here instead of passing silently.

Claim scope: inventory completeness only. Nothing here re-grades a
committed record, regenerates evidence, or compares any installed NumPy
version against a stamp.
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import numpy_stamp_inventory as nsi  # noqa: E402

DOC = os.path.join(REPO, "docs", "numpy-stamp-inventory.md")
CLASSES = {"Live", "Historical provenance", "Declared cross-environment"}


def test_every_committed_stamp_is_listed_exactly_once_and_classified():
    rows = nsi.parse_inventory(open(DOC, encoding="utf-8").read())
    assert rows, "inventory doc has no parsable classification rows"
    for r in rows:
        assert r.cls in CLASSES, (r.group, r.cls)
        assert r.version, (r.group, "row without a stamped version")

    found = nsi.find_stamps(REPO)
    assert found, "the stamp search found nothing; the search is broken"
    listed = {}
    for r in rows:
        for f in r.files:
            assert f not in listed, \
                (f, "listed in both %r and %r" % (listed.get(f), r.group))
            listed[f] = r.group

    missing = {s.path for s in found} - set(listed)
    assert not missing, \
        ("committed stamp(s) missing from the inventory", sorted(missing))
    stale = {p for p in listed
             if p.startswith("reports/")} - {s.path for s in found}
    assert not stale, \
        ("inventory row(s) stamp nothing under reports/", sorted(stale))


def test_oracle_runtime_is_a_separate_live_row_not_a_report_record():
    rows = nsi.parse_inventory(open(DOC, encoding="utf-8").read())
    oracle = [r for r in rows
              if "oracle/manifest.json" in r.files]
    assert oracle, "oracle/manifest.json runtime row missing from inventory"
    assert oracle[0].cls == "Live", oracle[0].cls
    body = open(DOC, encoding="utf-8").read()
    # the live consumer that makes it Live, and the scope warning that keeps
    # #354 from conflating the oracle build pin with a CI pin
    assert "oracle/fetch-and-build.sh" in body
    assert "not a CI pin" in body or "not a CI obligation" in body


def test_scratch_injected_stamp_fails_the_audit():
    """The control the inventory exists to make fail: a silently missing row.

    A record injected into a scratch copy of reports/ (not in the inventory)
    must be flagged as missing, while the real tree audits clean.
    """
    scratch = json.dumps({"environment": {"numpy": "9.9.9"}, "issue": "X"})
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="numpy-stamp-control-")
    try:
        os.makedirs(os.path.join(tmp, "reports", "scratch-control"))
        with open(os.path.join(tmp, "reports", "scratch-control",
                               "injected.json"), "w") as f:
            f.write(scratch)
        audit = nsi.audit(root=tmp, doc=DOC)
        injected = os.path.join("reports", "scratch-control", "injected.json")
        assert injected in audit.missing, audit.missing
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    assert not nsi.audit(root=REPO, doc=DOC).missing, \
        "control leaked: the real tree must audit clean"


def test_unclassified_row_fails_the_audit():
    body = open(DOC, encoding="utf-8").read()
    marker = "| Historical provenance |"
    assert marker in body, "expected class cell not found in inventory table"
    bad_path = DOC + ".unclassified-tmp"
    try:
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write(body.replace(marker, "| NOT-CLASSIFIED (untraced) |", 1))
        audit = nsi.audit(root=REPO, doc=bad_path)
        assert audit.unclassified, \
            "a row classified as NOT-CLASSIFIED (untraced) must fail the audit"
    finally:
        if os.path.exists(bad_path):
            os.remove(bad_path)
