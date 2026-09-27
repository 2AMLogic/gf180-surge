"""SXT-029 (#22) coverage publication: republishability of reports/coverage-v1/.

The apparatus documents itself as deterministic ("same committed inputs =>
byte-identical outputs") and fail-closed ("a stale/missing leaf evidence must
DOWNGRADE affected presets"). Issue #125 recorded the failure mode those two
sentences allow when nobody checks them: three leaf evidence records were
legitimately edited after the last publication, their pins were never revised,
and the *committed* `coverage.json` / `per-preset.csv` kept asserting gates
(including `PASS` fx-gate cells) that their own inputs no longer supported --
for days, invisibly, because nothing re-derived the artifact.

These tests are that missing check. They assert bookkeeping only: nothing here
establishes any leaf's RTL-vs-model or model-vs-reference verdict, and nothing
here is a preset-support, fidelity, or sound claim.
"""
import csv
import hashlib
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COV = os.path.join(REPO, "reports", "coverage-v1")
TABLE = os.path.join(COV, "leaf-verification.json")
TOOL = os.path.join(REPO, "tools", "publish_coverage.py")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_table():
    with open(TABLE, encoding="utf-8") as f:
        return json.load(f)


def pinned_records(table):
    """(section_key, entry_key, path, sha256) for every pin in the table."""
    out = []
    for section in ("gates", "leaves", "routing_leaves", "airwindows_leaves"):
        for key, entry in (table.get(section) or {}).items():
            if not isinstance(entry, dict):
                continue
            for item in entry.get("evidence") or []:
                out.append((section, key, item["path"], item["sha256"]))
    return out


def publish(outdir, leaf_table=None):
    cmd = [sys.executable, TOOL, "--outdir", outdir]
    if leaf_table is not None:
        cmd += ["--leaf-table", leaf_table]
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)


def read_rows(outdir):
    with open(os.path.join(outdir, "per-preset.csv"), newline="",
              encoding="utf-8") as f:
        return {r["path"]: r for r in csv.DictReader(f)}


# --------------------------------------------------------------- pin integrity

def test_every_evidence_pin_matches_its_file():
    """No pin in the ledger may be STALE against the file it pins.

    The publisher downgrades a stale leaf (correctly), so a drifted pin does
    not fail the tool -- it silently hardens the published gates instead, and
    the committed artifact stops matching its own inputs. Asserting every pin
    here is what makes that drift visible at the moment it is introduced,
    rather than at the next unrelated leaf's PR (the #125 failure mode).
    """
    table = load_table()
    records = pinned_records(table)
    assert records, "no evidence pins found -- table shape changed"
    stale = []
    for section, key, rel, pin in records:
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            stale.append(f"{section}[{key}] {rel}: MISSING")
            continue
        got = sha256_file(path)
        if got != pin:
            stale.append(
                f"{section}[{key}] {rel}: table says {pin}, file hashes {got}")
    assert not stale, (
        "stale evidence pin(s); re-pin to the current file (and record which "
        "edit moved it in leaf-verification.json::evidence_pin_revisions) or "
        "restore the file, then republish reports/coverage-v1/:\n  "
        + "\n  ".join(stale))


def test_pin_revisions_record_is_coherent():
    """Every recorded re-pin must describe the pin the table actually carries."""
    table = load_table()
    revisions = table.get("evidence_pin_revisions", [])
    by_path = {}
    for _section, _key, rel, pin in pinned_records(table):
        by_path.setdefault(rel, set()).add(pin)
    for rev in revisions:
        rel = rev["path"]
        assert rel in by_path, f"re-pin recorded for unpinned path {rel}"
        assert by_path[rel] == {rev["sha256"]}, (
            f"re-pin record for {rel} does not match the table pin(s) "
            f"{sorted(by_path[rel])}")
        assert rev["previous_sha256"] != rev["sha256"], (
            f"re-pin record for {rel} records no movement")
        assert rev["moved_by"].strip(), f"re-pin for {rel} names no edit"
        assert rev["decision"].strip(), f"re-pin for {rel} records no decision"


# ------------------------------------------------------- republishability

def test_committed_artifacts_are_republishable(tmp_path):
    """Re-running the publisher on the committed tree must reproduce the
    committed coverage.json and per-preset.csv byte-for-byte."""
    outdir = str(tmp_path / "out")
    r = publish(outdir)
    assert r.returncode == 0, f"publisher refused: {r.stderr}"
    for name in ("coverage.json", "per-preset.csv"):
        fresh = os.path.join(outdir, name)
        committed = os.path.join(COV, name)
        assert sha256_file(fresh) == sha256_file(committed), (
            f"reports/coverage-v1/{name} is not reproducible from the "
            "committed inputs; re-run `python3 tools/publish_coverage.py` and "
            "commit the result (no --control-allow-input-drift, no "
            "--leaf-table override)")


def test_published_artifact_claims_no_unearned_support():
    """The published ledger may never report a supported preset while the
    fidelity-freeze gate is unmet -- coverage is not a fidelity claim."""
    with open(os.path.join(COV, "coverage.json"), encoding="utf-8") as f:
        cov = json.load(f)
    gate = cov["leaf_ledger"]["gates"]["fidelity_freeze"]
    if gate["status"] != "PASS" or gate["evidence_state"] != "OK":
        assert cov["totals"]["supported"] == 0, (
            "supported > 0 with the fidelity-freeze gate unmet/stale")
    rows = read_rows(COV)
    assert len(rows) == 3561, f"corpus row count moved: {len(rows)}"
    for path, row in rows.items():
        if row["headline_status"] == "supported":
            assert row["fidelity_contract_gate"] == "PASS", path
            for col in ("voice_leaf_gate", "fx_leaves_gate",
                        "wavetable_leaf_gate", "routing_leaves_gate"):
                assert row[col] in ("", "PASS"), (path, col, row[col])


# ------------------------------------------------------------ failure control

def test_stale_pin_downgrades_affected_presets(tmp_path):
    """Failure control: corrupting one pin must downgrade the presets that
    depend on it to STALE in the *published artifact*, never leave them PASS.

    This is the negative control the apparatus documents, asserted against the
    real committed table (the counterfactual-world version lives in
    tools/coverage_negative_controls.py).
    """
    good_out = str(tmp_path / "good")
    assert publish(good_out).returncode == 0
    good = read_rows(good_out)
    baseline_pass = {p for p, r in good.items() if r["fx_leaves_gate"] == "PASS"}
    assert baseline_pass, (
        "no preset holds fx_leaves_gate PASS, so this control cannot observe a "
        "downgrade -- the control is not live and must be re-targeted")

    table = load_table()
    ev = table["leaves"]["fx:EQ"]["evidence"]
    assert len(ev) == 1
    tampered_path = tmp_path / "leaf-verification-tampered.json"
    ev[0]["sha256"] = "0" * 64
    tampered_path.write_text(json.dumps(table, indent=2, sort_keys=True),
                             encoding="utf-8")

    bad_out = str(tmp_path / "bad")
    r = publish(bad_out, leaf_table=str(tampered_path))
    assert r.returncode == 0, f"publisher refused: {r.stderr}"
    bad = read_rows(bad_out)

    # Only rows whose fx gate was actually reached can be downgraded: a row
    # whose structural status precedes the leaf gates carries an empty cell,
    # which is never a pass and needs no downgrade.
    affected = {p for p in good
                if "EQ" in (good[p]["fx_required"] or "").split(";")
                and good[p]["fx_leaves_gate"] != ""}
    assert affected, "no preset requires EQ -- control cannot be evaluated"
    downgraded = [p for p in affected if bad[p]["fx_leaves_gate"] == "STALE"]
    assert len(downgraded) == len(affected), (
        f"only {len(downgraded)}/{len(affected)} EQ presets downgraded")
    for p in affected:
        assert bad[p]["fx_leaves_gate"] != "PASS", p
        assert "stale_leaf:" in bad[p]["reasons"], p
    assert baseline_pass & affected, (
        "the corrupted pin covers no preset that previously held PASS -- "
        "the control would not detect a kept-PASS regression")
    with open(os.path.join(bad_out, "coverage.json"), encoding="utf-8") as f:
        bad_cov = json.load(f)
    assert bad_cov["leaf_ledger"]["leaves"]["fx:EQ"]["evidence_state"] == "STALE"
    assert bad_cov["totals"]["supported"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
