"""#428: census bookkeeping must reject equal-count identity corruption.

Every mutation runs on a temp copy of corpus/census-v0.1/ (the committed corpus
is never touched). Bookkeeping only: no support, fidelity, or quality claim.
"""
import csv
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import check_census_consistency as cc

SRC = os.path.join(REPO, "corpus", "census-v0.1")
TOOL = os.path.join(REPO, "tools", "check_census_consistency.py")


@pytest.fixture
def census(tmp_path):
    dst = tmp_path / "census-v0.1"
    shutil.copytree(SRC, dst)
    return dst


def _csv(census):
    return census / "results" / "per-preset.csv"


def _read(census):
    with open(_csv(census), newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def _write(census, fields, rows):
    with open(_csv(census), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _check(census, reconcile=True):
    failures, _ = cc.run_checks(
        manifest=census / "corpus-manifest.json",
        summary_path=census / "results" / "summary.json",
        per_preset=_csv(census),
        reconcile=reconcile,
    )
    return failures


def _parsed(rows, bank):
    return [i for i, r in enumerate(rows)
            if r["bank"] == bank and r["status"] == "parsed_static_only"]


def _dup_and_drop(census):
    fields, rows = _read(census)
    a, b = _parsed(rows, "contributor")[:2]
    rows[b] = dict(rows[a])  # duplicate a, drop b; count and banks unchanged
    _write(census, fields, rows)
    return rows[a]["path"]


def _nonexistent(census):
    fields, rows = _read(census)
    rows[_parsed(rows, "contributor")[0]]["path"] = (
        "resources/data/patches_3rdparty/Nope/Does Not Exist.fxp")
    _write(census, fields, rows)


def _blob(census):
    fields, rows = _read(census)
    rows[_parsed(rows, "contributor")[0]]["git_blob_sha1"] = "0" * 40
    _write(census, fields, rows)


def _size(census):
    fields, rows = _read(census)
    r = rows[_parsed(rows, "contributor")[0]]
    r["size"] = str(int(r["size"]) + 1)
    _write(census, fields, rows)


def _swap_banks(census):
    fields, rows = _read(census)
    f = _parsed(rows, "factory")[0]
    c = _parsed(rows, "contributor")[0]
    rows[f]["bank"], rows[c]["bank"] = "contributor", "factory"
    _write(census, fields, rows)


IDENTITY_MUTATIONS = {
    "dup_and_drop": (_dup_and_drop, ("duplicate path", "missing from")),
    "nonexistent_path": (_nonexistent, ("path set mismatch",)),
    "blob_hash": (_blob, ("git_blob_sha1 mismatch",)),
    "size": (_size, ("size mismatch",)),
    "bank_swap": (_swap_banks, ("derived from its path root",)),
}


def test_baseline_pass(census):
    assert _check(census) == []
    assert subprocess.run([sys.executable, TOOL], capture_output=True,
                          text=True, check=False).returncode == 0


@pytest.mark.parametrize("name", sorted(IDENTITY_MUTATIONS))
def test_identity_mutation_rejected(census, name):
    mutate, expected = IDENTITY_MUTATIONS[name]
    mutate(census)
    text = "\n".join(_check(census))
    assert text, f"{name}: corruption was not rejected"
    for fragment in expected:
        assert fragment in text, (name, fragment, text[:400])


@pytest.mark.parametrize("name", sorted(IDENTITY_MUTATIONS))
def test_control_disabled_reconciliation_misses_corruption(census, name):
    """Negative control: without the reconciliation the expected-rejection
    assertion above would fail (aggregates are preserved by construction)."""
    IDENTITY_MUTATIONS[name][0](census)
    assert _check(census, reconcile=True) != []
    assert _check(census, reconcile=False) == [], (
        f"{name}: aggregates alone already reject it; control is not meaningful")


def test_reorder_still_passes(census):
    fields, rows = _read(census)
    _write(census, fields, list(reversed(rows)))
    assert _check(census) == []
    fields, rows = _read(census)
    _write(census, fields, rows[1::2] + rows[0::2])
    assert _check(census) == []


@pytest.mark.parametrize("col", ["git_blob_sha1", "size", "bank", "path"])
def test_missing_identity_column_fails_cleanly(census, col):
    fields, rows = _read(census)
    _write(census, [f for f in fields if f != col],
           [{k: v for k, v in r.items() if k != col} for r in rows])
    p = subprocess.run([sys.executable, TOOL, "--census-dir", str(census)],
                       capture_output=True, text=True, check=False)
    assert p.returncode == 1
    assert p.stdout.startswith("FAIL") and "Traceback" not in p.stderr
    assert col in p.stdout


@pytest.mark.parametrize("bad", ["abc", "", "-5", "12.5", "1e3"])
def test_malformed_size_fails_cleanly(census, bad):
    fields, rows = _read(census)
    rows[_parsed(rows, "contributor")[0]]["size"] = bad
    _write(census, fields, rows)
    p = subprocess.run([sys.executable, TOOL, "--census-dir", str(census)],
                       capture_output=True, text=True, check=False)
    assert p.returncode == 1 and "malformed size" in p.stdout
    assert "Traceback" not in p.stderr


def test_malformed_blob_hash_fails_cleanly(census):
    fields, rows = _read(census)
    rows[0]["git_blob_sha1"] = "xyz"
    _write(census, fields, rows)
    assert any("malformed git_blob_sha1" in f for f in _check(census))


def test_snare_tight_historical_failure_still_checked(census):
    fields, rows = _read(census)
    keep = [r for r in rows if "Snare Tight.fxp" not in r["path"]]
    assert len(keep) == len(rows) - 1
    _write(census, fields, keep)
    assert _check(census)
    # and the committed row is still a recorded failure
    _, rows = _read(census)
    snare = [r for r in rows if "Snare Tight.fxp" in r["path"]]
    assert len(snare) == 0  # copy mutated; committed file asserted below
    with open(os.path.join(SRC, "results", "per-preset.csv"), newline="",
              encoding="utf-8") as f:
        committed = list(csv.DictReader(f))
    s = [r for r in committed if "Snare Tight.fxp" in r["path"]]
    assert len(s) == 1 and s[0]["status"] == cc.UNRESOLVED_STATUS
    assert s[0]["bank"] == "factory"
