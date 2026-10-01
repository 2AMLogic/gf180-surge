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
    foreign quotation added elsewhere in the same file still fails,
  - the non-exemptible `foreign-license-text` rule cannot be masked by our own
    attribution: a pasted upstream copyright line or SPDX tag still fires when
    our own header sits above it (or a `gf180-surge` mention beside it), when
    this project is named inside the foreign notice's own holder line, when our
    own licence is merely the leading operand of a compound SPDX expression,
    and when a license body is wrapped mid-phrase across a comment leader —
    while every own-attribution layout still audits clean.

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


# --- own-attribution masking (#25 acceptance item 4: the rule must still fire) -


def _masked_tree(tmp_path, label, text):
    (tmp_path / label).mkdir(parents=True, exist_ok=True)
    root = _skeleton(tmp_path / label)
    cp._write(root, cp.MASKED_REL, text)
    return root


def test_foreign_copyright_below_our_own_header_is_flagged(tmp_path):
    """Reading only a file's FIRST copyright line disarmed the rule.

    `foreign-license-text` cannot be exempted, so the only way to lose it is
    to make it stop firing: a pasted upstream notice under our own header used
    to audit clean, because the signal inspected one match per file.
    """
    root = _masked_tree(
        tmp_path,
        "under-own",
        cp.FIXTURE_OWN_COPYRIGHT + cp.FIXTURE_FILLER + cp.FIXTURE_FOREIGN_COPYRIGHT_LINE,
    )
    assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL)


def test_foreign_copyright_beside_a_project_mention_is_flagged(tmp_path):
    """A holder is read from its own notice line, not from a ±120-char window.

    Any nearby mention of this project (an own header, or prose naming
    `gf180-surge`) satisfied the window and suppressed the foreign notice.
    """
    root = _masked_tree(
        tmp_path,
        "beside-mention",
        cp.FIXTURE_OWN_PROJECT_LINE + cp.FIXTURE_FOREIGN_COPYRIGHT_LINE,
    )
    assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL)


def test_foreign_spdx_below_our_own_tag_is_flagged(tmp_path):
    root = _masked_tree(
        tmp_path,
        "spdx",
        cp.FIXTURE_OWN_SPDX_TAG + cp.FIXTURE_FILLER + cp.FIXTURE_FOREIGN_SPDX_TAG,
    )
    assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL)


def test_our_own_attribution_alone_still_audits_clean(tmp_path):
    """The positive half: a rule that flags our own header would be turned off."""
    for label, text in (
        ("own-copyright", cp.FIXTURE_OWN_COPYRIGHT + cp.FIXTURE_FILLER),
        ("own-spdx", cp.FIXTURE_OWN_SPDX_TAG + cp.FIXTURE_FILLER),
        ("own-both", cp.FIXTURE_OWN_SPDX_TAG + cp.FIXTURE_OWN_COPYRIGHT + cp.FIXTURE_FILLER),
    ):
        (tmp_path / label).mkdir(parents=True, exist_ok=True)
        root = _skeleton(tmp_path / label)
        cp._write(root, cp.OWN_ONLY_REL, text)
        findings, _ = cp.audit(root)
        assert not findings, (label, [f.detail for f in findings])


# --- the same masking one level in: inside the notice / tag / phrase ----------


def test_foreign_holder_naming_this_project_is_still_flagged(tmp_path):
    """A holder is read from the HOLDER FIELD, not from anywhere on the line.

    Line-scoping the holder test (the previous fix) still let a pasted upstream
    notice suppress itself by *mentioning* this project on its own line — in a
    parenthetical, or after a spaced hyphen, which is exactly how a modified
    vendored file gets annotated. Both audited clean on the non-exemptible rule.
    """
    for label, text in (
        ("parenthetical", cp.FIXTURE_FOREIGN_COPYRIGHT_PARENTHETICAL),
        ("after-dash", cp.FIXTURE_FOREIGN_COPYRIGHT_AFTER_DASH),
    ):
        root = _masked_tree(tmp_path, label, text)
        assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL), label


def test_compound_spdx_expression_behind_our_own_operand_is_flagged(tmp_path):
    """An SPDX tag carries an expression; only its first operand was compared.

    `Apache-2.0 OR <foreign>` is the standard dual-licence spelling, so this
    was not an exotic evasion — it read as "our own licence" and audited clean.
    """
    root = _masked_tree(tmp_path, "compound-spdx", cp.FIXTURE_COMPOUND_SPDX_OWN_FIRST)
    assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL)


def test_license_body_wrapped_across_a_comment_leader_is_flagged(tmp_path):
    """A pasted license body is a comment block, and may wrap mid-phrase.

    `\\s+` between two words does not span `"\\n# "`, and the old multi-word
    prefilter did not survive the wrap either, so a header whose phrase broke
    across lines carried no signal at all.
    """
    for label, text in (
        ("wrapped-fsf", cp.FIXTURE_WRAPPED_FSF_BODY),
        ("wrapped-gpl-title", cp.FIXTURE_WRAPPED_GPL_TITLE),
    ):
        root = _masked_tree(tmp_path, label, text)
        assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL), label


def test_own_attribution_variants_still_audit_clean(tmp_path):
    """The positive half of the holder-field and SPDX-expression fixes.

    Each of these is an own-attribution layout that the fixes could plausibly
    have started flagging (an aside on the notice line, an 'Authors' spelling, a
    holder after a spaced hyphen, a tag quoted mid-sentence). A rule that fires
    on our own header gets switched off, and the protection goes with it.
    """
    for label, text in (
        ("own-with-aside", cp.FIXTURE_OWN_COPYRIGHT_WITH_ASIDE),
        ("own-authors", cp.FIXTURE_OWN_COPYRIGHT_AUTHORS),
        ("own-after-dash", cp.FIXTURE_OWN_COPYRIGHT_AFTER_DASH),
        ("own-spdx-in-prose", cp.FIXTURE_OWN_SPDX_IN_PROSE),
    ):
        (tmp_path / label).mkdir(parents=True, exist_ok=True)
        root = _skeleton(tmp_path / label)
        cp._write(root, cp.OWN_ONLY_REL, text + cp.FIXTURE_FILLER)
        findings, _ = cp.audit(root)
        assert not findings, (label, [f.detail for f in findings])


def test_leaderless_prose_wrap_is_a_declared_boundary(tmp_path):
    """Pins the deliberate scope limit, so it cannot drift silently either way.

    The comment-leader gap accepts a line break only when the continuation
    carries a comment leader. A leaderless prose wrap of a license NAME is not
    a comment-block paste and is not treated as carriage — the rule is
    non-exemptible, so a finding here could not be answered by an exemption.
    """
    (tmp_path / "prose").mkdir(parents=True, exist_ok=True)
    root = _skeleton(tmp_path / "prose")
    cp._write(root, "docs/mentions.md", cp.FIXTURE_PROSE_WRAP_LICENSE_NAME)
    findings, _ = cp.audit(root)
    assert not findings, [f.detail for f in findings]


def test_spdx_expression_parse_is_exact():
    """Unit-level: every operand examined, prose after the expression ignored."""
    assert cp.spdx_foreign_ids("Apache-2.0") == []
    assert cp.spdx_foreign_ids("apache-2.0") == []
    assert cp.spdx_foreign_ids("Apache-2.0 OR GPL-3.0-or-later") == ["GPL-3.0-or-later"]
    assert cp.spdx_foreign_ids("Apache-2.0 AND MIT") == ["MIT"]
    assert cp.spdx_foreign_ids("(MIT OR Apache-2.0)") == ["MIT"]
    assert cp.spdx_foreign_ids("GPL-3.0-or-later") == ["GPL-3.0-or-later"]
    assert cp.spdx_foreign_ids("Apache-2.0 tags are used below") == []
    assert cp.spdx_foreign_ids("Apache-2.0 */") == []


# --- increment 4: delimiter-led holder fields, SPDX operands past the
# --- expression, yearless notices, wrapped holder lists -----------------------


def test_foreign_holder_behind_a_project_mention_is_flagged(tmp_path):
    """Our name standing FIRST in the holder field is not enough to be ours.

    Each of these notices opens its holder field with a delimiter — a bracket, a
    parenthesis, a semicolon, an em dash — so the field itself held no name and
    the holder test fell back to searching the WHOLE line, reinstating the very
    masking the line-scoped and field-scoped fixes removed. Our name came first
    in all four, so all four audited clean on the non-exemptible rule.
    """
    for label, text in (
        ("brackets", cp.FIXTURE_FOREIGN_HOLDER_BEHIND_BRACKETS),
        ("parens", cp.FIXTURE_FOREIGN_HOLDER_BEHIND_PARENS),
        ("semicolon", cp.FIXTURE_FOREIGN_HOLDER_AFTER_SEMICOLON),
        ("em-dash", cp.FIXTURE_FOREIGN_HOLDER_AFTER_EM_DASH),
    ):
        root = _masked_tree(tmp_path, label, text)
        assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL), label


def test_spdx_operand_past_the_parseable_expression_is_flagged(tmp_path):
    """The expression walk stops at the first non-operator token, by design.

    That stop is also a mask: a comma list and a parenthetical both put a foreign
    operand past the end of the parseable expression, where nothing looked.
    """
    for label, text in (
        ("comma-list", cp.FIXTURE_SPDX_FOREIGN_AFTER_COMMA),
        ("parenthetical", cp.FIXTURE_SPDX_FOREIGN_IN_PARENTHETICAL),
    ):
        root = _masked_tree(tmp_path, label, text)
        assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL), label


def test_yearless_and_wrapped_notices_are_flagged(tmp_path):
    """A notice need not carry a year, and its holder list may wrap.

    A yearless pasted notice carried no signal at all; a holder list wrapped onto
    the next line put the second holder where no keyword stands to raise one.
    """
    for label, text in (
        ("yearless", cp.FIXTURE_YEARLESS_FOREIGN_COPYRIGHT),
        ("wrapped-holder-list", cp.FIXTURE_WRAPPED_HOLDER_LIST),
    ):
        root = _masked_tree(tmp_path, label, text)
        assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL), label


def test_wrapped_holder_finding_locates_the_offending_holder(tmp_path):
    """The wrapped-holder finding's snippet must name the holder, at any depth.

    `Finding` carries no line number, so `detail`'s snippet is the only locator a
    human has -- and `foreign-license-text` cannot be exempted, so an
    unanswerable finding could only be answered by switching the rule off.
    `_wrapped_holder_match` therefore has to search the full text with ABSOLUTE
    offsets: a match computed against the continuation-line slice quotes the
    right bytes only while the notice happens to sit at the top of the file,
    which is exactly what the unpadded fixture used to hide.
    """
    # Unit level: the match offsets must index `text`, not the line slice.
    for pad_lines in (0, 1, 10, 40):
        text = "x = 1\n" * pad_lines + cp.FIXTURE_WRAPPED_HOLDER_LIST
        match = cp.foreign_copyright_match(text)
        assert match is not None, pad_lines
        assert text[match.start() : match.end()] == "Chris", pad_lines
        assert "Chris Johnson / Airwindows" in cp._snippet(text, match), pad_lines

    # End to end: the finding the audit actually reports quotes the holder.
    root = _masked_tree(
        tmp_path, "wrapped-padded", cp.FIXTURE_FILLER + cp.FIXTURE_WRAPPED_HOLDER_LIST
    )
    findings, _ = cp.audit(root)
    wrapped = [
        f
        for f in findings
        if f.rule == "foreign-license-text" and f.path == cp.MASKED_REL
    ]
    assert wrapped, [f.detail for f in findings]
    assert any("Chris Johnson / Airwindows" in f.detail for f in wrapped), [
        f.detail for f in wrapped
    ]


def test_own_attribution_and_copyright_prose_still_audit_clean(tmp_path):
    """The positive half of increment 4 — a false positive here is unanswerable.

    `foreign-license-text` cannot be exempted, so an own notice (or ordinary
    prose about copyright, or this repository's '(a) … (b) … (c)' leg markers)
    that became a finding could only be answered by switching the rule off.
    """
    for label, rel, text in (
        ("own-rights-reserved", cp.OWN_ONLY_REL, cp.FIXTURE_OWN_COPYRIGHT_RIGHTS_RESERVED),
        ("own-cross-reference", cp.OWN_ONLY_REL, cp.FIXTURE_OWN_COPYRIGHT_CROSS_REFERENCE),
        ("own-dash-with-aside", cp.OWN_ONLY_REL, cp.FIXTURE_OWN_DASH_HOLDER_WITH_ASIDE),
        ("own-then-prose", cp.OWN_ONLY_REL, cp.FIXTURE_OWN_COPYRIGHT_THEN_PROSE),
        ("own-quoted-in-prose", "docs/mentions.md", cp.FIXTURE_OWN_COPYRIGHT_QUOTED_IN_PROSE),
        ("lettered-list-markers", "docs/legs.md", cp.FIXTURE_LETTERED_LIST_MARKERS),
        ("copyright-prose", "docs/mentions.md", cp.FIXTURE_COPYRIGHT_PROSE_NOT_A_NOTICE),
    ):
        (tmp_path / label).mkdir(parents=True, exist_ok=True)
        root = _skeleton(tmp_path / label)
        cp._write(root, rel, text + cp.FIXTURE_FILLER)
        findings, _ = cp.audit(root)
        assert not findings, (label, [f.detail for f in findings])


def test_spdx_remainder_scan_reads_ids_not_prose():
    """Unit-level: a license id by shape past the expression, but never prose."""
    assert cp.spdx_foreign_ids("Apache-2.0, GPL-3.0-or-later") == ["GPL-3.0-or-later"]
    assert cp.spdx_foreign_ids("Apache-2.0 / GPL-3.0-or-later") == ["GPL-3.0-or-later"]
    assert cp.spdx_foreign_ids("Apache-2.0 (upstream MIT)") == ["MIT"]
    # the expression walk already reported it; the remainder must not double it
    assert cp.spdx_foreign_ids("Apache-2.0 OR GPL-3.0-or-later") == ["GPL-3.0-or-later"]
    # prose, a comment close, and a bare own tag stay clean
    assert cp.spdx_foreign_ids("Apache-2.0 tags are used below") == []
    assert cp.spdx_foreign_ids("Apache-2.0 (ours; see the record)") == []
    assert cp.spdx_foreign_ids("Apache-2.0 -->") == []


def test_own_holder_test_requires_our_name_alone():
    """Unit-level: ours iff our name is the first AND only holder in the field.

    Each argument is the holder side of a notice line only (the '|' stands where
    the year ends), so this file never contains a contiguous copyright notice —
    which the audit would correctly flag as unattributed carriage in its own
    source. Same reason as the runtime-assembled fixtures in the tool.
    """
    assert cp.own_copyright_holder("| 2AM Logic", 1)
    assert cp.own_copyright_holder("| The gf180-surge Authors", 1)
    assert cp.own_copyright_holder("| - 2AM Logic (SXT-019 governance)", 1)
    assert cp.own_copyright_holder("| 2AM Logic, All Rights Reserved.", 1)
    assert not cp.own_copyright_holder("| [gf180-surge] Some Upstream Author", 1)
    assert not cp.own_copyright_holder("| Some Upstream Author (for gf180-surge)", 1)
    assert not cp.own_copyright_holder("| Chris Johnson", 1)
    assert not cp.own_copyright_holder("|", 1)


# --- increment 5: the holder list continues past a delimiter on the SAME line -


def test_second_holder_on_an_own_notice_line_is_flagged(tmp_path):
    """Our name in the first holder segment did not clear the rest of the line.

    The segment walk judged the FIRST segment holding a name and returned, so a
    second holder standing after that segment's closing delimiter was never read
    — the same "stop as soon as our own name is recognised" shape as the earlier
    increments, one segment to the right. All four of these audited clean on the
    non-exemptible rule, and all four are how a part-vendored file actually gets
    attributed.
    """
    for label, text in (
        ("semicolon", cp.FIXTURE_SECOND_HOLDER_AFTER_SEMICOLON),
        ("parenthetical", cp.FIXTURE_SECOND_HOLDER_IN_PARENTHETICAL),
        ("em-dash", cp.FIXTURE_SECOND_HOLDER_AFTER_EM_DASH),
        ("spaced-hyphen", cp.FIXTURE_SECOND_HOLDER_AFTER_DASH),
    ):
        root = _masked_tree(tmp_path, f"second-holder-{label}", text)
        assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL), label


def test_second_holder_finding_locates_the_offending_holder(tmp_path):
    """`detail`'s snippet is the only locator, so it must reach the 2nd holder."""
    root = _masked_tree(
        tmp_path, "second-holder-detail", cp.FIXTURE_SECOND_HOLDER_AFTER_SEMICOLON
    )
    findings, _ = cp.audit(root)
    quoting = [
        f
        for f in findings
        if f.rule == "foreign-license-text" and "Some Upstream Author" in f.detail
    ]
    assert quoting, [f.detail for f in findings]


def test_second_holder_bounds_are_declared_boundaries(tmp_path):
    """Pins both residual limits, so neither can drift silently either way.

    A later segment is read as naming a holder only on a TWO-WORD name shape, and
    only before the segment's first sentence break. Both bounds exist because
    `foreign-license-text` cannot be exempted: an own aside carries at most one
    capitalised token in practice, and text after a full stop is prose, not a
    continuing holder list — a finding on either could only be answered by
    switching the rule off.
    """
    for label, text in (
        ("single-name-aside", cp.FIXTURE_OWN_SINGLE_NAME_ASIDE),
        ("sentence-break", cp.FIXTURE_OWN_NOTICE_THEN_SENTENCE),
    ):
        (tmp_path / label).mkdir(parents=True, exist_ok=True)
        root = _skeleton(tmp_path / label)
        cp._write(root, cp.OWN_ONLY_REL, text + cp.FIXTURE_FILLER)
        findings, _ = cp.audit(root)
        assert not findings, (label, [f.detail for f in findings])


def test_own_holder_test_reads_the_whole_holder_side():
    """Unit-level: a second holder past the delimiter is not ours either.

    Each argument is the holder side of a notice line only ('|' stands where the
    year ends), so this file never contains a contiguous copyright notice — the
    audit would correctly flag that as unattributed carriage in its own source.
    """
    # ours: one holder, with asides the audit must not read as a second name
    assert cp.own_copyright_holder("| 2AM Logic (gf180-surge model sources)", 1)
    assert cp.own_copyright_holder("| 2AM Logic (generated from Verilog)", 1)
    assert cp.own_copyright_holder("| 2AM Logic; see NOTICE. Chris Johnson wrote it", 1)
    assert cp.own_copyright_holder("| The gf180-surge Authors (All Rights Reserved)", 1)
    # not ours: the holder list continues past the delimiter
    assert not cp.own_copyright_holder("| 2AM Logic; Some Upstream Author", 1)
    assert not cp.own_copyright_holder("| 2AM Logic (from Chris Johnson)", 1)
    assert not cp.own_copyright_holder("| 2AM Logic — Chris Johnson", 1)
    assert not cp.own_copyright_holder("| 2AM Logic - Some Upstream Author", 1)
    assert not cp.own_copyright_holder("| 2AM Logic [also Chris Johnson]", 1)
    assert not cp.own_copyright_holder("| The gf180-surge Authors — Some Upstream Author", 1)


def test_masking_controls_run_in_the_self_test(tmp_path):
    """The controls must be wired into `--negative-control`, not merely defined.

    Without this, deleting the masking list from the runner would keep the
    tests above green while CI stopped exercising them.
    """
    assert cp._masking_controls(), "the masking controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cp._masking_controls():
        label = case[0]
        assert label in proc.stdout, f"{label} not exercised by --negative-control"
