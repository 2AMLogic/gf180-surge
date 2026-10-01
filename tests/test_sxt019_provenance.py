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
    while every own-attribution layout still audits clean,
  - an entry that carries its content BY REFERENCE is judged at the discovery
    layer: a committed submodule gitlink (or a nested repository checkout in a
    non-git tree) and a symlink whose target leaves the audited tree are
    findings, a declared one is not, and an ordinary in-tree symlink
    (`CLAUDE.md -> AGENTS.md`, this repository's own shape) stays clean,
  - a payload the encoding sniff refuses is not evidence-free: a wrapper
    (gzip/bzip2/xz stream, zip or tar, nested, found by MAGIC rather than by
    name) is unwrapped and its members content-scanned, and a payload that is
    still not text is read as the printable-ASCII runs it carries — while this
    repository's own renders, float dumps, tensors and gzipped traces stay
    clean, which `test_repository_audits_clean` re-checks against all 335 real
    payloads on every run.

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
    assert f"all {len(cp.RULES)} rules fired" in proc.stdout, proc.stdout


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


# --- decode-layer masking (#25 acceptance item 4, increment 6) ----------------
#
# Increments 1-5 all hardened the SIGNAL layer and silently assumed the file
# had become text. A file the sniff refused to decode reaches no content rule
# at all, so "any NUL byte in the head" as the binary test was itself a mask.


def test_utf16_encoded_license_body_is_flagged(tmp_path):
    """A 'Unicode' editor save must not hide a GPL header.

    `.py`/`.sv` are not in FOREIGN_SOURCE_EXTS (this repo authors them), so no
    extension tripwire covered these files either: the carrier was invisible.
    """
    for label, payload in (
        ("bom", cp.FIXTURE_UTF16_BOM_NOTICE),
        ("le", cp.FIXTURE_UTF16LE_BOMLESS_NOTICE),
        ("be", cp.FIXTURE_UTF16BE_BOMLESS_NOTICE),
        ("nul", cp.FIXTURE_STRAY_NUL_NOTICE),
    ):
        root = _masked_tree(tmp_path, label, payload)
        assert "foreign-license-text" in _fired_on(root, cp.MASKED_REL), (
            f"{label}: a foreign license body survived the decode layer"
        )


def test_sniff_encoding_admits_text_and_refuses_payloads():
    """Unit-level pin on the admission test itself.

    The sniff is deliberately NOT loosened by the payload layer below: decoding
    a render as prose would turn 264 renders into garbage findings on a rule
    nobody can exempt. A refused payload is handled by unwrapping/harvesting
    instead.
    """
    assert cp.sniff_encoding(b"plain ascii\n") == "utf-8"
    assert cp.sniff_encoding("x = 1\n".encode("utf-16")) == "utf-16-le"
    assert cp.sniff_encoding("x = 1\n".encode("utf-16-be")) == "utf-16-be"
    assert cp.sniff_encoding(b"ok\x00ay, mostly text\n" + b"a" * 400) == "utf-8"
    # Opaque payloads stay refused, including a tensor-like run of NULs.
    assert cp.sniff_encoding(bytes(range(256)) * 8) is None
    assert cp.sniff_encoding(b"\x00" * 4096) is None


def test_unscanned_file_count_is_disclosed(tmp_path):
    """Coverage is reported separately from agreement (AGENTS.md).

    A PASS that silently skipped files would overstate what was checked. A
    payload with no ASCII run in it at all reaches no content rule, and says so.
    """
    root = _masked_tree(tmp_path, "disclose", "")
    cp._write(root, "fixtures/render.wav", b"\x00" * 4096)
    _, stats = cp.audit(root)
    assert stats["files_not_content_scanned"] == 1
    proc = run_tool("--root", str(root))
    assert "not content-scanned" in proc.stdout, proc.stdout


# --- the payload layer (#25 acceptance item 4, increment 8) -------------------
#
# Below the decode layer: a payload the sniff refuses is either a WRAPPER one
# `read()` from text, or binary data with ASCII runs in it. Increment 6 declared
# both out of reach and pinned that declaration with a positive control; every
# case below audited clean on the real tree while `--negative-control` reported
# all 31 rules and all 40 masking controls behaving.


def test_wrapped_license_body_is_flagged(tmp_path):
    """A wrapper is found by MAGIC, not by name — `.gz` is stripped, `.dat` lies."""
    for label, rel, payload in (
        ("gzip", "model/pasted_helper.py.gz", cp.FIXTURE_GZIPPED_NOTICE),
        ("xz", "model/pasted_helper.py.gz", cp.FIXTURE_XZ_NOTICE),
        ("bzip2", "model/pasted_helper.py.gz", cp.FIXTURE_BZIP2_NOTICE),
        ("zip", "compiler/golden/bundle.dat", cp.FIXTURE_ZIP_WITH_NOTICE),
        ("tar.gz", "compiler/golden/bundle.dat", cp.FIXTURE_TAR_GZ_WITH_NOTICE),
        ("npz", "reports/fixtures/taps.npz", cp.FIXTURE_NPZ_WITH_NOTICE),
        ("zip-in-gzip", "compiler/golden/bundle.dat", cp.FIXTURE_GZIPPED_ZIP_WITH_NOTICE),
        ("gzip-in-zip", "compiler/golden/bundle.dat", cp.FIXTURE_ZIP_WITH_GZIPPED_MEMBER),
    ):
        root = _masked_tree(tmp_path, f"wrap-{label}", "")
        cp._write(root, rel, payload)
        fired = [f for f in cp.audit(root)[0] if f.path == rel]
        assert any(f.rule == "foreign-license-text" for f in fired), (
            f"{label}: a GPL body survived the wrapper layer"
        )
        assert any(cp.WIDE_NOTICE_LOCATOR in f.detail for f in fired), (
            f"{label}: the finding does not quote the offending notice: "
            + "; ".join(f.detail for f in fired)
        )


def test_notice_embedded_in_a_binary_payload_is_flagged(tmp_path):
    """The limit increment 6 declared, now closed by harvesting ASCII runs.

    A WAV `LIST/INFO` `ICOP` chunk is where an upstream sample pack states its
    holder; a notice spliced into a float dump is the same shape by hand.
    """
    for label, rel, payload in (
        ("wav-icop", "fixtures/audio/render.wav", cp.FIXTURE_WAV_WITH_COPYRIGHT_CHUNK),
        ("float-dump", "reports/artifacts/ref.f32", cp.FIXTURE_FLOAT_DUMP_WITH_NOTICE),
        ("opaque", "fixtures/audio/render.wav", cp.FIXTURE_NOTICE_IN_AN_OPAQUE_PAYLOAD),
        ("sign", "fixtures/audio/render.wav", cp.FIXTURE_COPYRIGHT_SIGN_IN_A_PAYLOAD),
    ):
        root = _masked_tree(tmp_path, f"embed-{label}", "")
        cp._write(root, rel, payload)
        fired = [f.rule for f in cp.audit(root)[0] if f.path == rel]
        assert "foreign-license-text" in fired, (
            f"{label}: a notice inside a binary payload was not flagged"
        )


def test_our_own_payload_shapes_still_audit_clean(tmp_path):
    """The unanswerable direction: `foreign-license-text` cannot be exempted.

    A false positive on a render, a float dump, a tensor or a gzipped trace
    could only be answered by switching the rule off, so these must stay clean.
    """
    for label, rel, payload in (
        ("pcm", "fixtures/audio/render.wav", cp.FIXTURE_PLAIN_PCM_WAV),
        ("f32", "reports/artifacts/ref.f32", cp.FIXTURE_PLAIN_FLOAT_DUMP),
        ("npy", "reports/traces/click.npy", cp.FIXTURE_TENSOR_PAYLOAD),
        ("trace.gz", "reports/artifacts/trace.json.gz", cp.FIXTURE_OWN_GZIPPED_TRACE),
        ("wide", "fixtures/audio/render.wav", cp.FIXTURE_WIDE_NOTICE_IN_A_PAYLOAD),
    ):
        root = _masked_tree(tmp_path, f"clean-{label}", "")
        cp._write(root, rel, payload)
        findings, _ = cp.audit(root)
        assert not findings, f"{label}: {[f.as_dict() for f in findings]}"


def test_harvest_keeps_notices_and_drops_payload_noise():
    """Unit-level pin on the harvest's admission test."""
    notice = ("Copy" + "right (C) 20" + "19 Some Upstream Author").encode("ascii")
    harvested = cp.harvest_strings(b"\x00\x01\x02" + notice + b"\xff\xfe")
    assert notice.decode("ascii") in harvested
    # The sign spelling (U+00A9) is normalised to ASCII instead of ending the
    # run. Written as an escape so this file carries no notice of its own.
    sign_notice = "\u00a9 20" + "19 Upstream Author"
    harvested_sign = cp.harvest_strings(sign_notice.encode("utf-8"))
    assert harvested_sign.startswith("(c" + ") 20"), harvested_sign
    assert sign_notice[0] not in harvested_sign
    # 16-bit PCM yields runs with no word in them, which are dropped.
    pcm = cp._wav_payload()
    assert not cp.RUN_WORD_RE.search(b"\x37\x22\x37\x37\x37\x47")
    assert "Copy" + "right" not in cp.harvest_strings(pcm)


def test_unwrap_payload_reads_wrappers_and_refuses_ordinary_payloads():
    """Unit-level pin: a wrapper yields members, a render yields None."""
    payloads, truncated = cp.unwrap_payload(cp.FIXTURE_GZIPPED_NOTICE)
    assert payloads and not truncated
    assert cp.WIDE_NOTICE_LOCATOR.encode("ascii") in payloads[0]
    assert cp.unwrap_payload(cp.FIXTURE_PLAIN_PCM_WAV) == (None, False)
    assert cp.unwrap_payload(b"") == (None, False)
    # Nested: a tar inside a gzip resolves to the tar's member, not the tar.
    payloads, _ = cp.unwrap_payload(cp.FIXTURE_TAR_GZ_WITH_NOTICE)
    assert any(b"filter" not in p and cp.WIDE_NOTICE_LOCATOR.encode() in p for p in payloads)


def test_truncated_payload_scan_is_disclosed_not_silent(tmp_path, monkeypatch):
    """A scan that could not finish must never look like one that passed."""
    monkeypatch.setattr(cp, "MAX_UNWRAPPED_BYTES", 32)
    payloads, truncated = cp.unwrap_payload(cp.FIXTURE_GZIPPED_NOTICE)
    assert truncated and payloads and len(payloads[0]) == 32
    root = _masked_tree(tmp_path, "truncated", "")
    cp._write(root, "reports/artifacts/trace.json.gz", cp.FIXTURE_GZIPPED_NOTICE)
    _, stats = cp.audit(root)
    assert stats["payload_scans_truncated"] == ["reports/artifacts/trace.json.gz"], stats


def test_payload_scan_modes_are_reported_for_the_real_tree():
    """Non-vacuity in CI: the new layer actually runs on this repository.

    Coverage is reported separately from agreement, and a weaker scan mode is
    reported separately from a full decode.
    """
    _, stats = cp.audit(REPO)
    assert stats["files_unwrapped_from_wrappers"] >= 1, stats
    assert stats["files_scanned_as_extracted_strings"] >= 100, stats
    assert stats["payload_scans_truncated"] == [], stats


def test_payload_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    assert cp._payload_controls(), "the payload controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cp._payload_controls():
        assert case[0] in proc.stdout, f"{case[0]} not exercised by --negative-control"


# --- discovery-layer carriage (#25 acceptance item 4, increment 7) ------------
#
# Below the decode layer: an entry that carries its content BY REFERENCE has no
# bytes of its own, so `open()` failed and it was counted as an undecodable
# payload among the renders. A committed submodule gitlink pinning the GPL
# Surge engine, and a symlink into the external (and in CI absent) pinned
# oracle, both audited clean on a tree that reported every other rule firing.


def _discovery_tree(tmp_path, label):
    root = tmp_path / f"tree-{label}"
    root.mkdir()
    cp.build_skeleton(root)
    findings, _ = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    return root


def test_committed_submodule_gitlink_is_flagged(tmp_path):
    """`AGENTS.md`/#25: no submodule by silent default — now mechanically so."""
    root = _discovery_tree(tmp_path, "gitlink")
    cp._git_submodule_entry(root)
    findings, stats = cp.audit(root)
    fired = [f for f in findings if f.rule == "submodule-reference"]
    assert fired, [f.as_dict() for f in findings]
    assert fired[0].path == cp.FIXTURE_SUBMODULE_REL
    # The evidence must name the upstream and the pin, or the finding is not
    # answerable: a gitlink has no text a reviewer can read instead.
    assert cp.FIXTURE_SUBMODULE_COMMIT[:12] in fired[0].detail
    assert "surge-synthesizer/surge" in fired[0].detail
    assert stats["entries_by_reference"]["gitlink"] == 1
    # …and it is NOT reported as an undecodable payload (that mislabelling is
    # how it hid among the renders).
    assert stats["files_not_content_scanned"] == 0


def test_nested_repository_in_a_non_git_tree_is_flagged(tmp_path):
    """The unpacked-tarball shape: a vendored checkout with no gitlink mode."""
    root = _discovery_tree(tmp_path, "nested")
    cp._nested_repo(root)
    findings, _ = cp.audit(root)
    assert [f.path for f in findings if f.rule == "submodule-reference"] == [
        cp.FIXTURE_NESTED_REPO_REL
    ], [f.as_dict() for f in findings]


def test_submodule_row_must_name_the_committed_commit(tmp_path):
    """A gitlink carries its own pin, so the row is checked against it exactly."""
    root = _discovery_tree(tmp_path, "gitlink-pin")
    cp._git_submodule_entry(root)
    cp._patch_manifest(root, lambda d: d["entries"].append(cp._submodule_row()))
    assert not cp.audit(root)[0], [f.as_dict() for f in cp.audit(root)[0]]

    root = _discovery_tree(tmp_path, "gitlink-wrong-pin")
    cp._git_submodule_entry(root)
    cp._patch_manifest(
        root, lambda d: d["entries"].append(cp._submodule_row(commit="0" * 40))
    )
    assert "manifest-uncorroborated" in _rules_fired(root)


def test_symlink_leaving_the_tree_is_flagged(tmp_path):
    """Every way a link's target can be out of the audit's reach."""
    cases = {
        "absent": cp.FIXTURE_ESCAPING_LINK_TARGET,  # the CI shape: oracle not checked out
        "absolute": "/opt/surge/include/sst/effects/Reverb1.h",
    }
    for label, target in cases.items():
        root = _discovery_tree(tmp_path, f"link-{label}")
        cp._symlink(root, cp.FIXTURE_ESCAPING_LINK_REL, target)
        findings, stats = cp.audit(root)
        fired = [f for f in findings if f.rule == "external-symlink-target"]
        assert fired, f"{label}: {[f.as_dict() for f in findings]}"
        assert fired[0].path == cp.FIXTURE_ESCAPING_LINK_REL
        assert stats["entries_by_reference"]["symlink"] == 1
        assert stats["files_not_content_scanned"] == 0


def test_symlink_into_a_declared_scope_exclusion_is_flagged(tmp_path):
    """A declared hole must not be re-imported at a product path."""
    root = _discovery_tree(tmp_path, "link-hole")
    cp._write(root, ".loom/vendored_table.py", "TABLE = [7, 8, 9]\n")
    cp._patch_manifest(
        root,
        lambda d: d["scope_exclusions"].append(
            {"prefix": ".loom/", "reason": "synthetic declared hole"}
        ),
    )
    cp._symlink(root, cp.FIXTURE_ESCAPING_LINK_REL, "../.loom/vendored_table.py")
    fired = [f for f in cp.audit(root)[0] if f.rule == "external-symlink-target"]
    assert fired and "scope exclusion" in fired[0].detail


def test_resolvable_escaping_symlink_is_still_content_scanned(tmp_path):
    """The structural rule must not replace the content rules.

    `text()` follows the link, so a target that does resolve is read by every
    content rule — a fix that short-circuited on the entry kind would have
    dropped them silently.
    """
    root = _discovery_tree(tmp_path, "link-resolves")
    cp._write(tmp_path / "external-oracle", "Reverb1.h", cp.FIXTURE_GPL_BODY)
    cp._symlink(
        root, cp.FIXTURE_ESCAPING_LINK_REL, "../../external-oracle/Reverb1.h"
    )
    fired = _fired_on(root, cp.FIXTURE_ESCAPING_LINK_REL)
    assert "foreign-license-text" in fired
    assert "external-symlink-target" in fired


def test_in_tree_symlinks_still_audit_clean(tmp_path):
    """The other failure direction, and this repository's own shape.

    `CLAUDE.md -> AGENTS.md` is a tracked symlink here. Neither by-reference
    rule is exemptible, so a false positive on an ordinary in-tree link could
    only be answered by switching the rule off.
    """
    root = _discovery_tree(tmp_path, "link-in-tree")
    cp._symlink(root, "CLAUDE.md", "docs/plain.md")
    cp._symlink(root, "docs/model", "../model")
    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["entries_by_reference"]["symlink"] == 2


def test_declared_by_reference_entries_audit_clean(tmp_path):
    """A row naming the exact path answers the structural rule in full."""
    root = _discovery_tree(tmp_path, "link-declared")
    cp._symlink(root, cp.FIXTURE_ESCAPING_LINK_REL, cp.FIXTURE_ESCAPING_LINK_TARGET)
    cp._patch_manifest(
        root,
        lambda d: d["entries"].append(
            {
                "path": cp.FIXTURE_ESCAPING_LINK_REL,
                "class": "external-reference",
                "content": "synthetic: a link into the external oracle tree",
                "upstream": "surge-synthesizer/surge",
                "pinned_commit": cp.FIXTURE_SUBMODULE_COMMIT,
                "upstream_license": "GPL-3.0-or-later",
                "decision_record": "0001",
            }
        ),
    )
    findings, _ = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]


def test_entry_kinds_are_read_from_the_git_index(tmp_path):
    """Unit pin on the discovery layer itself: modes, not guesses."""
    root = _discovery_tree(tmp_path, "modes")
    cp._git_submodule_entry(root)
    cp._symlink(root, "CLAUDE.md", "docs/plain.md")
    cp._git(root, "add", "-f", "CLAUDE.md")
    kinds = dict((rel, kind) for rel, kind, _ in cp.list_entries(root))
    assert kinds[cp.FIXTURE_SUBMODULE_REL] == "gitlink"
    assert kinds["CLAUDE.md"] == "symlink"
    assert kinds["model/carrier.py"] == "file"
    commits = {
        rel: blob for rel, kind, blob in cp.list_entries(root) if kind == "gitlink"
    }
    assert commits[cp.FIXTURE_SUBMODULE_REL] == cp.FIXTURE_SUBMODULE_COMMIT
    assert cp.parse_gitmodules(root) == {
        cp.FIXTURE_SUBMODULE_REL: cp.FIXTURE_SUBMODULE_URL
    }


def test_repository_has_no_undeclared_by_reference_entries():
    """The committed tree itself: every symlink/gitlink is in-tree or declared."""
    tree = cp.Tree(REPO, [])
    by_reference = {
        rel: tree.kind(rel) for rel in tree.files if tree.kind(rel) != "file"
    }
    # This repository has exactly one tracked symlink today (CLAUDE.md ->
    # AGENTS.md) and no submodules; the assertion is about findings, not count.
    for rel, kind in by_reference.items():
        if kind == "symlink":
            assert cp.symlink_escape(tree, rel) is None, (
                f"{rel} leaves the audited tree with no provenance row"
            )
    _, stats = cp.audit(REPO)
    assert stats["entries_by_reference"]["gitlink"] == 0, (
        "a submodule appeared: it needs a provenance row and a decision record"
    )


def _index_as_symlink(root, rel, target_text):
    """Record `rel` as mode 120000 while leaving a REGULAR file on disk.

    This is what a `core.symlinks=false` checkout looks like: the index says
    symlink, the filesystem has a plain file whose content is the target path.
    """
    cp._write(root, rel, target_text)
    blob = subprocess.run(
        ["git", "-C", str(root), "hash-object", "-w", "--", rel],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    cp._git(root, "update-index", "--add", "--cacheinfo", f"120000,{blob},{rel}")


def test_symlink_entry_without_filesystem_symlink_support(tmp_path):
    """Both directions on a checkout that cannot create real symlinks.

    An in-tree link must not become a finding on a non-exemptible rule, and an
    escaping one must still fire — read from the recorded target either way.
    """
    root = _discovery_tree(tmp_path, "nosymlink-clean")
    cp._git(root, "init", "-q")
    cp._git(root, "add", "-A", "-f")
    _index_as_symlink(root, "CLAUDE.md", "docs/plain.md")
    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["entries_by_reference"]["symlink"] == 1

    root = _discovery_tree(tmp_path, "nosymlink-escaping")
    cp._git(root, "init", "-q")
    cp._git(root, "add", "-A", "-f")
    _index_as_symlink(
        root, cp.FIXTURE_ESCAPING_LINK_REL, cp.FIXTURE_ESCAPING_LINK_TARGET
    )
    assert "external-symlink-target" in _fired_on(root, cp.FIXTURE_ESCAPING_LINK_REL)


def test_discovery_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    assert cp._discovery_controls(), "the discovery controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cp._discovery_controls():
        assert case[0] in proc.stdout, f"{case[0]} not exercised by --negative-control"
