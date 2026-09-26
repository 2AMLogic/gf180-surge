"""SXT-019 provenance-audit tests (governance issue #25; run by CI).

Covers the automatable guarantees of `tools/check_provenance.py` only:
  - the committed tree audits clean (every carriage signal answered by a
    provenance row or a declared exemption; decision-record bookkeeping
    self-consistent),
  - every audit rule fires on a deliberate violation (the tool's own
    `--negative-control` self-test, run as a test so a rule that silently
    stops firing fails CI — the false-negative failure mode),
  - the decision-record index lists every record on disk with the record's
    own status keyword and date,
  - deliberately unattributed third-party-derived content injected into a
    synthetic tree IS flagged: a GPL header, an upstream asset payload, a
    foreign-language source file, and a self-declared quotation,
  - the manifest cannot be weakened silently: blanket patterns, stale rows,
    stale exemptions and exemptions of non-exemptible rules all fail.

These tests make NO claim that no third-party content was copied into this
repository (see the tool's declared limits: a marker-free copy is not
detectable by bookkeeping), and no claim that any decision record has been
ratified by the owner.

Python 3 standard library only (pytest as runner).
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "check_provenance.py"
MANIFEST = REPO / "decision-records" / "provenance.json"
RECORD_DIR = REPO / "decision-records"

sys.path.insert(0, str(REPO / "tools"))

import check_provenance as cp  # noqa: E402  (path set above)


def run_tool(*args):
    proc = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    return proc


# --- the committed tree -------------------------------------------------------


def test_repository_audits_clean():
    findings, stats = cp.audit(REPO)
    detail = "\n".join(f"[{f.rule}] {f.path}: {f.detail}" for f in findings)
    assert not findings, f"provenance findings in the committed tree:\n{detail}"
    assert stats["files_scanned"] >= 1200, stats
    assert stats["provenance_rows"] >= 1, stats


def test_cli_exit_codes_and_verdict():
    proc = run_tool("--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "PASS"
    assert payload["findings"] == []
    # coverage is reported separately from agreement (AGENTS.md)
    assert payload["coverage"]["files_scanned"] >= 1200
    assert "not proof" in payload["caveat"]


def test_manifest_rows_cite_existing_indexed_records():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == cp.SCHEMA_VERSION
    assert manifest["entries"], "the manifest must carry the current provenance rows"
    for entry in manifest["entries"]:
        number = entry["decision_record"]
        matches = sorted(RECORD_DIR.glob(f"{number}-*.md"))
        assert matches, f"{entry} cites a nonexistent decision record"
        assert entry["class"] in cp.KNOWN_CLASSES
        assert entry["upstream_license"], entry


def test_decision_record_index_lists_every_record():
    """The staleness this issue was filed for is now a test, not a review habit."""
    tree = cp.Tree(REPO, [])
    records, record_findings = cp.parse_records(tree)
    rows, index_findings = cp.parse_index(tree)
    assert not record_findings, [f.detail for f in record_findings]
    assert not index_findings, [f.detail for f in index_findings]
    assert set(records) == set(rows), (
        f"records on disk: {sorted(records)}; index rows: {sorted(rows)}"
    )
    for number, record in records.items():
        assert cp.status_keyword(rows[number]["status"]) == record["status_keyword"]
        assert rows[number]["date"] == record["date"]


# --- the audit's own failure detection ---------------------------------------


def test_negative_control_every_rule_fires():
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FAIL" not in proc.stdout, proc.stdout
    assert "all 29 rules fired" in proc.stdout or "rules fired" in proc.stdout


def test_every_rule_has_a_negative_control():
    missing = sorted(set(cp.RULES) - set(cp._controls()))
    assert not missing, f"rules with no negative control: {missing}"


# --- synthetic-tree controls (the AC's "deliberately unattributed file") ------


def _skeleton(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    cp.build_skeleton(root)
    findings, _ = cp.audit(root)
    assert not findings, [f.detail for f in findings]
    return root


def _rules_fired(root):
    findings, _ = cp.audit(root)
    return {f.rule for f in findings}


def test_unattributed_gpl_header_is_flagged(tmp_path):
    root = _skeleton(tmp_path)
    # The fixture text is built from fragments inside check_provenance.py on
    # purpose (see the note there): a contiguous license body in this file
    # would make the audit flag its own test suite.
    cp._write(root, "model/pasted.py", cp.FIXTURE_GPL_BODY)
    assert "foreign-license-text" in _rules_fired(root)


def test_unattributed_upstream_asset_is_flagged(tmp_path):
    root = _skeleton(tmp_path)
    cp._write(root, "assets/Bank Sine.wt", b"\x00\x01payload")
    assert "upstream-asset-extension" in _rules_fired(root)


def test_unattributed_foreign_source_is_flagged(tmp_path):
    root = _skeleton(tmp_path)
    cp._write(root, "src/copied_kernel.cpp", "float f(float x){return x;}\n")
    assert "foreign-source-language" in _rules_fired(root)


def test_self_declared_quotation_without_row_is_flagged(tmp_path):
    root = _skeleton(tmp_path)
    cp._write(root, "model/table.py", cp.FIXTURE_TRANSCRIBED)
    assert "self-declared-quotation" in _rules_fired(root)


def test_row_pointing_at_the_wrong_file_is_flagged(tmp_path):
    """A provenance row must be corroborated by the file it claims to describe."""
    root = _skeleton(tmp_path)
    cp._write(root, "model/carrier.py", "TABLE = [1, 2, 3]  # no provenance stated\n")
    assert "manifest-uncorroborated" in _rules_fired(root)


def test_blanket_pattern_cannot_cover_future_files(tmp_path):
    root = _skeleton(tmp_path)
    cp._patch_manifest(
        root,
        lambda d: d["entries"].append(
            {
                "pattern": "model/**",
                "class": "quoted-constants",
                "content": "everything under model/",
                "upstream": "x",
                "upstream_license": "GPL-3.0-or-later",
                "decision_record": "0001",
            }
        ),
    )
    assert "manifest-bad-pattern" in _rules_fired(root)


def test_non_exemptible_rules_cannot_be_exempted(tmp_path):
    root = _skeleton(tmp_path)
    cp._patch_manifest(
        root,
        lambda d: d["exemptions"].append(
            {
                "path": "docs/plain.md",
                "rules": ["foreign-license-text"],
                "reason": "waving away a GPL header",
            }
        ),
    )
    assert "exemption-non-exemptible-rule" in _rules_fired(root)


def test_partial_scan_is_not_a_pass(tmp_path):
    """A scan below the declared floor fails instead of reporting a clean tree."""
    root = _skeleton(tmp_path)
    cp._patch_manifest(root, lambda d: d.update(scan_floor=10_000))
    assert "scan-underflow" in _rules_fired(root)
