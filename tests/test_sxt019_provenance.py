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
    stale exemptions and exemptions of non-exemptible rules all fail,
  - an occurrence-scoped exemption covers only its named occurrences: a
    foreign quotation added elsewhere in the same file still fails.

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


def _set_record_status(root, record_status, index_status):
    record = root / "decision-records" / "0001-example.md"
    record.write_text(
        cp.SKELETON_RECORD.replace("**Status**: ratified", f"**Status**: {record_status}"),
        encoding="utf-8",
    )
    index = root / "decision-records" / "README.md"
    index.write_text(
        cp.SKELETON_INDEX.replace("| ratified |", f"| {index_status} |"), encoding="utf-8"
    )


def test_recorded_status_is_accepted_and_unknown_status_still_fails(tmp_path):
    """DR-0013 / DR-0016 use "RECORDED ..."; accepting it must not open the vocabulary."""
    root = _skeleton(tmp_path)
    _set_record_status(
        root,
        "RECORDED CONTRACT REVISION — owner ratification pending",
        "RECORDED CONTRACT REVISION — owner ratification pending",
    )
    assert "record-status-unrecognized" not in _rules_fired(root)
    _set_record_status(root, "vibes — decided by feel", "vibes — decided by feel")
    assert "record-status-unrecognized" in _rules_fired(root)


def test_attribution_statement_row_covers_nothing_implicitly(tmp_path):
    """An 'attribution-statement' row only answers the tripwires it lists in
    'covers'; a row without 'covers' must not launder a pasted license body."""
    root = _skeleton(tmp_path)
    cp._write(root, "docs/attribution.md", cp.FIXTURE_GPL_BODY + "pin 58914e59\n")
    row = {
        "path": "docs/attribution.md",
        "class": "attribution-statement",
        "content": "synthetic attribution prose",
        "upstream": "synthetic upstream",
        "pinned_commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
        "upstream_license": "MIT",
        "decision_record": "0001",
    }
    cp._patch_manifest(root, lambda d: d["entries"].append(dict(row)))
    fired = _rules_fired(root)
    assert "foreign-license-text" in fired
    assert "manifest-unknown-class" not in fired
    cp._patch_manifest(root, lambda d: d["entries"][-1].update({"covers": ["foreign-license-text"]}))
    assert "foreign-license-text" not in _rules_fired(root)


# --- occurrence-scoped exemptions (#181 self-copy false positive) -------------


def _own_copy_tree(tmp_path, text, occurrences, path="docs/own_copy.md"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = _skeleton(tmp_path)
    cp._write(root, "docs/own_copy.md", text)
    cp._scoped_exemption(root, occurrences, path=path)
    return root


def _fired_on(root, rel):
    findings, _ = cp.audit(root)
    return {f.rule for f in findings if f.path == rel}


def test_scoped_exemption_covers_only_the_named_occurrence(tmp_path):
    occ = [cp.FIXTURE_OWN_COPY_OCCURRENCE]
    clean = _own_copy_tree(tmp_path / "a", cp.FIXTURE_OWN_COPY_DOC, occ)
    assert not cp.audit(clean)[0]
    # A real foreign copy in the SAME file, in the SAME marker wording, fails.
    foreign = _own_copy_tree(
        tmp_path / "b", cp.FIXTURE_OWN_COPY_DOC + cp.FIXTURE_FOREIGN_COPY_LINE, occ
    )
    assert "self-declared-quotation" in _fired_on(foreign, "docs/own_copy.md")


def test_scoped_exemption_goes_stale_and_cannot_be_a_blanket(tmp_path):
    gone = _own_copy_tree(
        tmp_path / "a", cp.FIXTURE_OWN_COPY_DOC, ["a sentence that is not there"]
    )
    assert "exemption-stale" in _rules_fired(gone)
    glob = _own_copy_tree(
        tmp_path / "b", cp.FIXTURE_OWN_COPY_DOC, [cp.FIXTURE_OWN_COPY_OCCURRENCE],
        path="docs/*.md",
    )
    assert "exemption-bad-pattern" in _rules_fired(glob)


def test_classic_readme_exemption_does_not_launder_a_foreign_copy(tmp_path):
    """The committed exemption for model/oscillators/classic/README.md is
    occurrence-scoped: the README as committed passes, and the same README
    with a foreign 'copied verbatim' line appended fails."""
    rel = "model/oscillators/classic/README.md"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    [entry] = [e for e in manifest["exemptions"] if e.get("path") == rel]
    assert entry.get("occurrences"), "the #181 exemption must stay occurrence-scoped"
    readme = (REPO / rel).read_text(encoding="utf-8")
    for label, text, expect_fail in (
        ("as-committed", readme, False),
        ("with-foreign-copy", readme + cp.FIXTURE_FOREIGN_COPY_LINE, True),
    ):
        (tmp_path / label).mkdir()
        root = _skeleton(tmp_path / label)
        cp._write(root, rel, text)
        cp._patch_manifest(root, lambda d: d["exemptions"].append(dict(entry)))
        # the synthetic manifest now quotes the occurrence, as the real one does
        cp._patch_manifest(
            root,
            lambda d: d["exemptions"].append(
                {
                    "path": cp.MANIFEST_REL,
                    "rules": ["self-declared-quotation"],
                    "reason": "synthetic: manifest quotes the occurrence",
                }
            ),
        )
        assert ("self-declared-quotation" in _fired_on(root, rel)) is expect_fail, label
