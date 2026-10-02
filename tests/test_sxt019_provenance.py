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
    payloads on every run,
  - a wrapper whose members carry no marker at all is answered by the member
    NAMES: a `.wt` wavetable in a zip renamed `.dat`, a stripped `.cpp` in a
    tar, a gzip whose FNAME header is its only name, and an asset member two
    wrappers deep are each flagged (and an outer member name is not masked by
    what it wraps), while this repository's own FNAME-carrying traces and
    `.npy`-member `.npz` fixtures stay clean — the rule is answered by a row
    declaring `covers`, never by an exemption,
  - the audited SET is the git index, and that boundary is disclosed rather
    than silent: an unattributed carrier left unstaged is NAMED in
    `entries_present_but_not_in_the_index` (and still not flagged), the count
    is printed even when zero, `--include-untracked` audits it and the rule
    fires, and ignored paths plus declared scope exclusions stay out of both,
  - the audited BYTES are both of an entry's byte sources, not just the one on
    disk: a carrier `git add`ed and then cleaned (or deleted, or hidden behind
    `assume-unchanged` / `skip-worktree`) is flagged from its STAGED blob — the
    bytes a commit would publish — and the finding says which view offended,
    while an unstaged paste into a tracked file still fires as a working-tree
    finding, an innocuous edit is counted and read but never flagged, and a
    gitlink stays a by-reference entry,
  - the ANSWERS are held to the same standard as the questions: a provenance
    row, an exemption, a scope exclusion, an index row or a widened `covers`
    list that exists on disk and in no commit answers nothing — the same row
    staged as well does, an ordinary file's divergence does not open a second
    answer set, and a bookkeeping edit that changes no answer is disclosed and
    produces nothing,
  - the EVIDENCE a bookkeeping judgement reads out of an entry is held to the
    same standard, with the bookkeeping itself agreeing in both views: a
    declared carrier staged with its provenance statement stripped (or staged
    uncited and then deleted from disk) no longer corroborates its row, and a
    citation of a nonexistent record staged and then cleaned off disk still
    resolves against nothing — while the same two defects on disk only keep
    firing unlabelled, a divergent carrier that states its provenance in both
    views is read in both and flagged in neither, and a declared binary
    payload, which has no text in either view, is disclosed rather than read.

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


def test_duplicated_occurrence_is_ambiguous_and_fails(tmp_path):
    """The named sentence repeated WORD FOR WORD with a foreign referent.

    Before #260 the occurrence regex matched every copy of the literal wording,
    so a genuinely foreign quotation worded as the exact same sentence was
    exempted alongside the legitimate self-copy and the tree audited clean.
    Wording cannot separate the two referents, so a duplicated occurrence is
    now a finding on the manifest, and the exemption is not applied at all.
    """
    occ = [cp.FIXTURE_OWN_COPY_OCCURRENCE]
    duplicated = _own_copy_tree(
        tmp_path / "dup",
        cp.FIXTURE_OWN_COPY_DOC + cp.FIXTURE_DUPLICATE_OCCURRENCE_LINE,
        occ,
    )
    fired = _rules_fired(duplicated)
    assert "exemption-ambiguous" in fired
    # ...on the manifest item, not on the document, and quoting the count.
    [finding] = [
        f
        for f in cp.audit(duplicated)[0]
        if f.rule == "exemption-ambiguous"
    ]
    assert finding.path == cp.MANIFEST_REL
    assert "appears 2 times" in finding.detail
    assert cp.FIXTURE_OWN_COPY_OCCURRENCE in finding.detail
    # Three copies are ambiguous too, and the exempted file is left unexempted.
    thrice = _own_copy_tree(
        tmp_path / "thrice",
        cp.FIXTURE_OWN_COPY_DOC
        + cp.FIXTURE_DUPLICATE_OCCURRENCE_LINE
        + cp.FIXTURE_DUPLICATE_OCCURRENCE_LINE,
        occ,
    )
    assert "exemption-ambiguous" in _rules_fired(thrice)
    assert "self-declared-quotation" in _fired_on(thrice, "docs/own_copy.md")


def test_committed_scoped_occurrences_are_unique_in_their_file(tmp_path):
    """The live positive control: every committed occurrence names one place.

    A file-level uniqueness rule can only be enforced if the committed
    manifest satisfies it; this pins that directly rather than inferring it
    from the tree audit's exit code.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    scoped = [e for e in manifest["exemptions"] if e.get("occurrences")]
    assert scoped, "the #181 occurrence-scoped exemption must still exist"
    for entry in scoped:
        text = (REPO / entry["path"]).read_text(encoding="utf-8")
        for occurrence in entry["occurrences"]:
            hits = cp.occurrence_regex(occurrence).findall(text)
            assert len(hits) == 1, (
                f"{entry['path']}: occurrence {occurrence!r} appears "
                f"{len(hits)} times"
            )


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
    with a foreign 'copied verbatim' line appended fails — including the
    adversarial case where the foreign line is the named sentence repeated
    word for word with a different referent (#260)."""
    rel = "model/oscillators/classic/README.md"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    [entry] = [e for e in manifest["exemptions"] if e.get("path") == rel]
    assert entry.get("occurrences"), "the #181 exemption must stay occurrence-scoped"
    readme = (REPO / rel).read_text(encoding="utf-8")
    [occurrence] = entry["occurrences"]
    identical_wording = f"\nThe Surge oscillator: {occurrence}.\n"
    for label, text, expect_fail in (
        ("as-committed", readme, False),
        ("with-foreign-copy", readme + cp.FIXTURE_FOREIGN_COPY_LINE, True),
        ("with-identical-wording", readme + identical_wording, True),
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
        ambiguous = "exemption-ambiguous" in _fired_on(root, cp.MANIFEST_REL)
        assert ambiguous is (label == "with-identical-wording"), label


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
        # A QUIET render is the hazard increment 10 had to be measured against:
        # every sample is a low byte beside a NUL high byte, which is exactly the
        # byte shape of a UTF-16-LE string.
        ("quiet-pcm", "fixtures/audio/render.wav", cp.FIXTURE_QUIET_PCM_WAV),
        ("f32", "reports/artifacts/ref.f32", cp.FIXTURE_PLAIN_FLOAT_DUMP),
        ("npy", "reports/traces/click.npy", cp.FIXTURE_TENSOR_PAYLOAD),
        ("trace.gz", "reports/artifacts/trace.json.gz", cp.FIXTURE_OWN_GZIPPED_TRACE),
        # The residual increment 10 declares rather than closes: a notice carried
        # in a TRANSFORMED encoding is not text at any stride.
        ("base64", "fixtures/audio/render.wav", cp.FIXTURE_BASE64_NOTICE_IN_A_PAYLOAD),
    ):
        root = _masked_tree(tmp_path, f"clean-{label}", "")
        cp._write(root, rel, payload)
        findings, _ = cp.audit(root)
        assert not findings, f"{label}: {[f.as_dict() for f in findings]}"


# --- the same payload, read in a WIDE encoding (increment 10) -----------------
#
# Increment 8 harvested a refused payload's printable-ASCII runs and declared the
# rest: "the harvest reads ASCII, so a notice written in a WIDE encoding inside a
# binary payload stays out of reach". A "Unicode" save is an ordinary editor
# default, so that residual was an ordinary evasion, not an exotic one: each tree
# below audited PASS / exit 0 with UNCHANGED tripwire counts on the previous tool
# (demonstrated on the real tree in `reports/sxt-019/EVIDENCE.md` §16).


def test_wide_encoded_notice_in_a_payload_is_flagged(tmp_path):
    """Every stride, both byte orders, BOM or not, committed or inside a wrapper."""
    for label, rel, payload in (
        ("utf-16-le", "fixtures/audio/render.wav", cp.FIXTURE_WIDE_NOTICE_IN_A_PAYLOAD),
        ("utf-16-be", "reports/artifacts/ref.f32", cp.FIXTURE_UTF16BE_NOTICE_IN_A_PAYLOAD),
        ("utf-32-le", "fixtures/audio/render.wav", cp.FIXTURE_UTF32LE_NOTICE_IN_A_PAYLOAD),
        ("utf-32-be", "fixtures/audio/render.wav", cp.FIXTURE_UTF32BE_NOTICE_IN_A_PAYLOAD),
        ("bom-in-wav", "fixtures/audio/render.wav", cp.FIXTURE_WAV_WITH_WIDE_NOTICE),
        (
            "odd-offset",
            "fixtures/audio/render.wav",
            cp.FIXTURE_WIDE_NOTICE_AT_AN_ODD_OFFSET,
        ),
        (
            "wrapper-member",
            "compiler/golden/bundle.dat",
            cp.FIXTURE_GZIPPED_WIDE_NOTICE_PAYLOAD,
        ),
    ):
        root = _masked_tree(tmp_path, f"wide-{label}", "")
        cp._write(root, rel, payload)
        fired = [f for f in cp.audit(root)[0] if f.path == rel]
        assert any(f.rule == "foreign-license-text" for f in fired), (
            f"{label}: a wide-encoded notice inside a payload was not flagged"
        )
        assert any(cp.WIDE_NOTICE_LOCATOR in f.detail for f in fired), (
            f"{label}: the finding does not quote the offending notice: "
            + "; ".join(f.detail for f in fired)
        )


def test_wide_run_harvest_reads_each_encoding_and_refuses_decimated_noise():
    """Unit-level pin on the admission test, including the shape that must FAIL.

    The second halving step (which resolves UTF-32) must only read a data stream
    whose other half is ALL NUL. Without that, quiet 16-bit PCM — a low byte
    beside a NUL high byte — decimates into printable noise and manufactures runs
    on a rule that cannot be exempted.
    """
    notice = cp.FIXTURE_WIDE_NOTICE_TEXT
    # Every byte alignment, not just the even one: a notice spliced into a
    # payload starts at an odd offset as often as an even one, and reading the
    # data byte on the wrong side of its padding is how that was missed first.
    for encoding in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be", "utf-16"):
        for lead in range(4):
            raw = b"\x81\x7f\x93\xee"[:lead] + notice.encode(encoding) + b"\xfe\x81"
            runs = cp._wide_runs(raw)
            assert any(cp.WIDE_NOTICE_LOCATOR in run for run in runs), (
                encoding,
                lead,
                runs,
            )
    # The narrow runs are NOT what answers these: a NUL after every character
    # means there is no printable-ASCII run six bytes long anywhere in the
    # payload, which is exactly why increment 8 missed it.
    narrow = [
        match.group()
        for match in cp.PRINTABLE_RUN_RE.finditer(notice.encode("utf-16-le"))
        if cp.RUN_WORD_RE.search(match.group())
    ]
    assert narrow == [], narrow
    # A quiet render carries no run that names a holder, and the audit counts
    # whatever it did find rather than reporting nothing at all.
    text, count = cp.harvest_payload(cp.FIXTURE_QUIET_PCM_WAV)
    assert "Upstream" not in text, text[:200]
    assert count == len(cp._wide_runs(cp.FIXTURE_QUIET_PCM_WAV))
    # The sign spelling is admitted inside a wide run and normalised to `(c)`.
    sign_runs = cp._wide_runs(cp.FIXTURE_WIDE_COPYRIGHT_SIGN_IN_A_PAYLOAD)
    assert any("(c" + ") 20" + "19" in run for run in sign_runs), sign_runs
    assert all(cp.COPYRIGHT_SIGN_CHAR not in run for run in sign_runs)


def test_wide_run_coverage_is_reported_for_the_real_tree():
    """Coverage separate from agreement: the layer ran, and says how much.

    The upper bound is a PRECISION pin on real data, and the only one available:
    the guard that makes the UTF-32 step read a stream whose other half is all
    NUL is what keeps a real (correlated, musical) render from decimating into
    printable noise, and synthetic LCG noise does not reproduce that — measured
    on this tree, 71 runs with that guard against 978 without it. Compare with
    `--json`'s `wide_encoded_runs_harvested` if this ever trips; several hundred
    would mean the guard has been lost, not that the tree grew.
    """
    _, stats = cp.audit(REPO)
    assert stats["wide_encoded_runs_harvested"] >= 1, stats
    assert stats["wide_encoded_runs_harvested"] <= 300, stats
    proc = run_tool()
    assert "wide-encoded (UTF-16/UTF-32) runs harvested" in proc.stdout, proc.stdout


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
    """Unit-level pin: a wrapper yields (name, member), a render yields None."""
    entries, truncated = cp.unwrap_payload(cp.FIXTURE_GZIPPED_NOTICE)
    assert entries and not truncated
    assert cp.WIDE_NOTICE_LOCATOR.encode("ascii") in entries[0][1]
    assert cp.unwrap_payload(cp.FIXTURE_PLAIN_PCM_WAV) == (None, False)
    assert cp.unwrap_payload(b"") == (None, False)
    # Nested: a tar inside a gzip resolves to the tar's member, not the tar,
    # and the member keeps its own NAME (increment 9).
    entries, _ = cp.unwrap_payload(cp.FIXTURE_TAR_GZ_WITH_NOTICE)
    assert any(
        b"filter" not in payload and cp.WIDE_NOTICE_LOCATOR.encode() in payload
        for _, payload in entries
    )
    assert any("vendor/filter.cpp" in name for name, _ in entries), entries


def test_truncated_payload_scan_is_disclosed_not_silent(tmp_path, monkeypatch):
    """A scan that could not finish must never look like one that passed."""
    monkeypatch.setattr(cp, "MAX_UNWRAPPED_BYTES", 32)
    entries, truncated = cp.unwrap_payload(cp.FIXTURE_GZIPPED_NOTICE)
    assert truncated and entries and len(entries[0][1]) == 32
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


# --- wrapper member NAMES (#25 acceptance item 4, increment 9) -----------------
#
# Increment 8 unwrapped wrappers and content-scanned their members, then
# declared the remainder: "a wrapper whose members carry no marker at all is
# covered only by the extension tripwires — unwrapping reads member CONTENT, and
# member NAMES are not themselves tripwired". That is the shape upstream assets
# actually arrive in: a `.wt` wavetable payload states no copyright, and a
# stripped `.cpp` states nothing either, so there is no content signal to find.
# Each tree below audited CLEAN on the previous tool.


def test_wrapper_member_name_is_judged_like_a_committed_path(tmp_path):
    """A marker-free member is answered by its NAME or by nothing at all."""
    for label, rel, payload, quoted in (
        ("zip-wt", "compiler/golden/bundle.dat",
         cp.FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME, "Bank Sine.wt"),
        ("tar-cpp", "compiler/golden/bundle.dat",
         cp.FIXTURE_TAR_GZ_WITH_SOURCE_MEMBER_NAME, "Reverb1.cpp"),
        ("gzip-fname", "compiler/golden/bundle.dat",
         cp.FIXTURE_GZIP_WITH_ASSET_FNAME, "Bank Sine.wt"),
        ("gzipped-zip", "compiler/golden/bundle.dat",
         cp.FIXTURE_GZIPPED_ZIP_WITH_ASSET_MEMBER, "Bank Sine.wt"),
        ("wrapped-member", "compiler/golden/bundle.dat",
         cp.FIXTURE_ZIP_WITH_WRAPPED_ASSET_MEMBER, "Bank Sine.wt"),
    ):
        root = _masked_tree(tmp_path, f"member-{label}", "")
        cp._write(root, rel, payload)
        fired = [f for f in cp.audit(root)[0] if f.path == rel]
        rules = [f.rule for f in fired]
        assert "wrapper-member-name" in rules, f"{label}: not flagged ({rules})"
        assert any(quoted in f.detail for f in fired), (
            f"{label}: the finding does not locate {quoted!r}: "
            + "; ".join(f.detail for f in fired)
        )


def test_marker_free_asset_member_reaches_no_content_rule(tmp_path):
    """Why the NAME is load-bearing: there is no text in the file to read.

    The member name must therefore be judged BEFORE the content rules' early
    `text is None` return, not after it — moving the check below that return
    silently restores the whole mask.
    """
    root = _masked_tree(tmp_path, "no-text", "")
    rel = "compiler/golden/bundle.dat"
    cp._write(root, rel, cp.FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME)
    tree = cp.Tree(root, [])
    assert tree.text(rel) is None, repr(tree.text(rel))
    assert tree.carried_names(rel) == ("wavetables/Bank Sine.wt",)
    assert [r for r, _ in cp.tripwire_hits(tree, rel)] == ["wrapper-member-name"]


def test_outer_member_name_is_not_masked_by_what_it_wraps():
    """Every `!`-joined component is judged, not just the innermost one."""
    entries, _ = cp.unwrap_payload(cp.FIXTURE_ZIP_WITH_WRAPPED_ASSET_MEMBER)
    label = entries[0][0]
    assert label == "Bank Sine.wt" + cp.MEMBER_JOIN + "meta.json", label
    # Judged whole, the label reads as a '.json' and nothing fires.
    assert cp._extension_suffix(label) == ".json"
    assert [c for c, _, _ in cp.member_name_signals(label)] == ["Bank Sine.wt"]


def test_gzip_header_name_is_parsed_and_absent_when_unset():
    """The FNAME field is the only name a single-stream wrapper carries."""
    assert cp._gzip_header_name(cp.FIXTURE_GZIP_WITH_ASSET_FNAME) == "Bank Sine.wt"
    # `gzip.compress` writes no FNAME, so there is no name to judge — and the
    # absence must read as "no name", never as an empty-string member.
    assert cp._gzip_header_name(cp.FIXTURE_OWN_GZIPPED_TRACE) is None
    assert cp._gzip_header_name(cp.FIXTURE_PLAIN_PCM_WAV) is None
    assert cp._gzip_header_name(b"") is None
    assert cp._gzip_header_name(cp.GZIP_MAGIC + b"\x08" + b"\x00" * 7) is None


def test_our_own_wrapper_shapes_still_audit_clean(tmp_path):
    """The unanswerable direction: `wrapper-member-name` cannot be exempted.

    15 of this repository's tracked `*.json.gz` / `*.hex.gz` traces really do
    carry an FNAME, and the `.npz` tap fixture is a zip of `.npy` members. A
    false positive on either could only be answered by switching the rule off.
    """
    for label, rel, payload in (
        ("trace-fname", "reports/artifacts/trace.json.gz",
         cp.FIXTURE_OWN_GZIPPED_TRACE_WITH_FNAME),
        ("npz", "reports/fixtures/taps.npz", cp.FIXTURE_OWN_NPZ_MEMBERS),
    ):
        root = _masked_tree(tmp_path, f"own-wrapper-{label}", "")
        cp._write(root, rel, payload)
        findings, _ = cp.audit(root)
        assert not findings, f"{label}: {[f.as_dict() for f in findings]}"


def test_real_tree_member_names_are_read_and_none_offend():
    """Non-vacuity in CI, measured on this repository rather than asserted.

    Coverage separate from agreement: names must actually be READ here (a
    wrapper the audit cannot open contributes none, so "0 offenders" and "no
    names examined" must not look alike), and none of them may offend.
    """
    findings, stats = cp.audit(REPO)
    assert stats["wrapper_member_names_read"] >= 20, stats
    assert stats["tripwire_hits"]["wrapper-member-name"] == 0, stats
    assert not [f for f in findings if f.rule == "wrapper-member-name"], findings


def test_wrapper_member_name_cannot_be_exempted(tmp_path):
    """It is answered by a provenance row, never by an exemption."""
    root = _masked_tree(tmp_path, "member-exempt", "")
    cp._write(
        root, "compiler/golden/bundle.dat", cp.FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME
    )
    cp._patch_manifest(
        root,
        lambda d: d["exemptions"].append(
            {
                "path": "compiler/golden/bundle.dat",
                "rules": ["wrapper-member-name"],
                "reason": "trying to wave away an archive of upstream wavetables",
            }
        ),
    )
    rules = {f.rule for f in cp.audit(root)[0]}
    assert "exemption-non-exemptible-rule" in rules, rules
    assert "wrapper-member-name" in rules, rules


# --- concatenated gzip member names (#25 acceptance item 4, increment 12) ----
#
# Increment 9 read the gzip FNAME header once per STREAM, while the unwrap
# inflated every MEMBER of it. `cat a.gz b.gz > c.gz` is a valid gzip file, so
# a `.wt` named by the second member's header was never judged — and the same
# two members written in the other order fired. Order-dependence was the tell;
# the coverage counter did not disclose it, because a two-name stream reported
# `wrapper_member_names_read` of 1, which is what a one-name stream reports.


def test_every_member_of_a_concatenated_gzip_is_named():
    """Unit-level pin: both members' names AND both members' payloads."""
    for label, payload in (
        ("second-offends", cp.FIXTURE_MULTI_MEMBER_GZIP_SECOND_NAMES_AN_ASSET),
        ("first-offends", cp.FIXTURE_MULTI_MEMBER_GZIP_FIRST_NAMES_AN_ASSET),
    ):
        entries, truncated = cp.unwrap_payload(payload)
        assert not truncated, label
        names = [name for name, _ in entries]
        assert sorted(names) == ["Bank Sine.wt", "notes.json"], f"{label}: {names}"
        # Content coverage is unchanged: every member is still inflated whole.
        assert sum(len(p) for _, p in entries) == 14 + len(
            cp.FIXTURE_MARKER_FREE_ASSET_PAYLOAD
        ), label


def test_concatenated_gzip_member_name_is_judged_in_either_order(tmp_path):
    """The defect, stated as the property it violated: order-independence."""
    rel = "compiler/golden/bundle.dat"
    for label, payload in (
        ("second-offends", cp.FIXTURE_MULTI_MEMBER_GZIP_SECOND_NAMES_AN_ASSET),
        ("first-offends", cp.FIXTURE_MULTI_MEMBER_GZIP_FIRST_NAMES_AN_ASSET),
    ):
        root = _masked_tree(tmp_path, f"concat-{label}", "")
        cp._write(root, rel, payload)
        fired = [f for f in cp.audit(root)[0] if f.path == rel]
        rules = [f.rule for f in fired]
        assert "wrapper-member-name" in rules, f"{label}: not flagged ({rules})"
        assert any("Bank Sine.wt" in f.detail for f in fired), (
            f"{label}: " + "; ".join(f.detail for f in fired)
        )


def test_concatenated_gzip_contributes_one_name_per_member(tmp_path):
    """Coverage, not just agreement: the counter must see BOTH names.

    This is the half the coverage line could not disclose — a two-member stream
    reporting 1 name read is indistinguishable from a one-member stream.
    """
    root = _masked_tree(tmp_path, "concat-coverage", "")
    rel = "reports/artifacts/trace.json.gz"
    cp._write(root, rel, cp.FIXTURE_OWN_MULTI_MEMBER_GZIPPED_TRACE)
    findings, stats = cp.audit(root)
    tree = cp.Tree(root, [])
    assert tree.carried_names(rel) == (
        "trace_seq-notes-coverage-v1.json",
        "trace_seq-notes-coverage-v2.json",
    ), tree.carried_names(rel)
    assert stats["wrapper_member_names_read"] == 2, stats
    # And the false-positive direction: two of our own members stay clean.
    assert not findings, [f.as_dict() for f in findings]


def test_concatenated_gzip_keeps_the_inflation_budget_accounting(
    tmp_path, monkeypatch
):
    """The Stop/escalate clause: the budget and its disclosure are unchanged.

    One `remaining` counter is threaded across the members of one stream,
    exactly as `_unwrap_archive` already threads one across a zip's members, so
    the per-stream total is still `MAX_UNWRAPPED_BYTES` and a scan stopped by it
    is still reported as TRUNCATED rather than as a pass.
    """
    monkeypatch.setattr(cp, "MAX_UNWRAPPED_BYTES", 20)
    entries, truncated = cp.unwrap_payload(
        cp.FIXTURE_MULTI_MEMBER_GZIP_SECOND_NAMES_AN_ASSET
    )
    assert truncated, entries
    assert sum(len(p) for _, p in entries) == 20, entries
    root = _masked_tree(tmp_path, "concat-truncated", "")
    rel = "reports/artifacts/trace.json.gz"
    cp._write(root, rel, cp.FIXTURE_OWN_MULTI_MEMBER_GZIPPED_TRACE)
    _, stats = cp.audit(root)
    assert stats["payload_scans_truncated"] == [rel], stats


def test_a_corrupt_or_trailing_garbage_gzip_is_not_read_as_a_wrapper():
    """Parity with what `gzip.GzipFile` raising `BadGzipFile` used to produce.

    Unparseable means "not a wrapper", so the payload falls through to the
    string harvest and stays disclosed — it must never mean "clean".
    """
    good = cp.FIXTURE_GZIP_WITH_ASSET_FNAME
    assert cp.unwrap_payload(good + b"nonsense-tail") == (None, False)
    assert cp.unwrap_payload(good[:-4]) == (None, False)
    assert cp._gzip_members(b"", 1 << 20) == (None, False)


def test_real_tree_gzip_streams_are_all_single_member():
    """Re-derives this increment's exposure claim instead of asserting it.

    Every tracked gzip in this repository is single-member, so closing the gap
    changed no committed file's status. A future multi-member commit makes this
    count move, which is the point of measuring it rather than quoting it.
    """
    manifest = cp.load_manifest(REPO)[0] or {}
    tree = cp.Tree(REPO, cp.scope_exclusion_prefixes(manifest))
    multi = []
    for rel in tree.files:
        path = REPO / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if not raw.startswith(cp.GZIP_MAGIC):
            continue
        members, _ = cp._gzip_members(raw, cp.MAX_UNWRAPPED_BYTES)
        if members and len(members) > 1:
            multi.append((rel, len(members)))
    assert multi == [], multi


def test_wrapper_name_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    assert cp._wrapper_name_controls(), "the wrapper controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cp._wrapper_name_controls():
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


# --- inside increment 7's own fix (increment 13) -------------------------------
#
# Four ways a DECLARED by-reference entry was described by nothing. None was a
# mask of the rule increment 7 closed — the tripwire still fired, and still made
# a row mandatory — but the row is the entry's only description, so a row that
# records no pin, or that says it carries no upstream content at all, answers
# the rule without describing the reference. A gitlink under a declared scope
# exclusion was not judged at all, while a symlink INTO the same prefix was
# already a reportable escape. And one verdict was not a mask but a function of
# the auditing MACHINE: whether the external target happened to be checked out.


def test_by_reference_row_must_carry_a_pinned_commit(tmp_path):
    """R1: the field is optional only where the bytes can corroborate the row."""
    root = _discovery_tree(tmp_path, "pin-omitted")
    cp._git_submodule_entry(root)
    cp._patch_manifest(
        root, lambda d: d["entries"].append(cp._submodule_row(commit=None))
    )
    fired = [f for f in cp.audit(root)[0] if f.rule == "manifest-field-missing"]
    assert fired, [f.as_dict() for f in cp.audit(root)[0]]
    assert "pinned_commit" in fired[0].detail
    assert cp.FIXTURE_SUBMODULE_REL in fired[0].detail

    # The same for a symlink row, which has no committed pin to fall back on.
    root = _discovery_tree(tmp_path, "pin-omitted-link")
    cp._symlink(root, cp.FIXTURE_ESCAPING_LINK_REL, cp.FIXTURE_ESCAPING_LINK_TARGET)
    row = cp._escaping_link_row()
    row.pop("pinned_commit")
    cp._patch_manifest(root, lambda d: d["entries"].append(row))
    assert "manifest-field-missing" in _rules_fired(root)

    # The false-positive direction: `pinned_commit` stays OPTIONAL for a row
    # whose file the audit reads, which is every content class. Weakening that
    # into a blanket requirement would make the manifest's own clean rows fail.
    root = _discovery_tree(tmp_path, "pin-optional")

    def drop_pin(data):
        data["entries"][0].pop("pinned_commit")

    cp._patch_manifest(root, drop_pin)
    assert not cp.audit(root)[0], [f.as_dict() for f in cp.audit(root)[0]]


def test_declared_escaping_symlink_audits_the_same_wherever_it_is_run(tmp_path):
    """R2: one committed tree, one verdict — not one per developer machine.

    The row's corroboration used to be read out of the RESOLVED (upstream)
    bytes, so the identical tree passed in CI, where the pinned oracle is not
    checked out, and failed on a box that had it. Requiring upstream bytes to
    cite one of this repository's decision records is not a tooling question,
    so the "no body to write provenance in" reading now covers both.
    """
    verdicts = {}
    for label, materialise in (
        ("absent", lambda root: None),
        (
            "checked-out",
            lambda root: cp._write(
                tmp_path / "oracle-present", "oracle_tables.py", "TABLE = [7, 8, 9]\n"
            ),
        ),
    ):
        root = _discovery_tree(tmp_path, f"env-{label}")
        materialise(root)
        cp._symlink(
            root,
            cp.FIXTURE_ESCAPING_LINK_REL,
            "../../oracle-present/oracle_tables.py",
        )
        # Same committed tree, same link, same row — the only difference is
        # whether the external target resolves on this machine.
        resolves = (root / cp.FIXTURE_ESCAPING_LINK_REL).exists()
        assert resolves == (label == "checked-out"), label
        cp._patch_manifest(
            root, lambda d: d["entries"].append(cp._escaping_link_row())
        )
        verdicts[label] = sorted(
            f"{f.rule}@{f.path}" for f in cp.audit(root)[0]
        )
    assert verdicts["absent"] == verdicts["checked-out"] == [], verdicts

    # …and the structural rule is still what makes that row mandatory: the same
    # resolvable link with NO row must still fire, undeclared.
    root = _discovery_tree(tmp_path, "env-undeclared")
    cp._write(tmp_path / "oracle-present", "oracle_tables.py", "TABLE = [7, 8, 9]\n")
    cp._symlink(
        root, cp.FIXTURE_ESCAPING_LINK_REL, "../../oracle-present/oracle_tables.py"
    )
    assert "external-symlink-target" in _fired_on(root, cp.FIXTURE_ESCAPING_LINK_REL)


def test_gitlink_inside_a_declared_scope_exclusion_is_judged_and_answerable(tmp_path):
    """R3: an exclusion withholds content; a gitlink has none of its own."""
    root = _discovery_tree(tmp_path, "excluded-gitlink")
    cp._declared_hole(root)
    cp._git_submodule_entry(root, rel=cp.FIXTURE_EXCLUDED_SUBMODULE_REL)
    findings, stats = cp.audit(root)
    fired = [f for f in findings if f.rule == "submodule-reference"]
    assert fired, [f.as_dict() for f in findings]
    assert fired[0].path == cp.FIXTURE_EXCLUDED_SUBMODULE_REL
    # The locator a reviewer needs: it looks exempted and is not.
    assert "scope exclusion" in fired[0].detail
    # Disclosed as coverage, not only as a finding.
    assert stats["by_reference_entries_inside_declared_exclusions"] == [
        cp.FIXTURE_EXCLUDED_SUBMODULE_REL
    ]

    # A finding that cannot be answered where it fires is a trap: before this
    # increment a row naming an excluded path was read as a STALE row.
    root = _discovery_tree(tmp_path, "excluded-gitlink-declared")
    cp._declared_hole(root)
    cp._git_submodule_entry(root, rel=cp.FIXTURE_EXCLUDED_SUBMODULE_REL)
    cp._patch_manifest(
        root,
        lambda d: d["entries"].append(
            cp._submodule_row(rel=cp.FIXTURE_EXCLUDED_SUBMODULE_REL)
        ),
    )
    assert not cp.audit(root)[0], [f.as_dict() for f in cp.audit(root)[0]]

    # The exclusion itself is still LIVE when its only member is that gitlink:
    # it declares the hole, and declaring it must not read as stale.
    root = _discovery_tree(tmp_path, "excluded-gitlink-only")
    cp._git_submodule_entry(root, rel=cp.FIXTURE_EXCLUDED_SUBMODULE_REL)
    cp._patch_manifest(
        root,
        lambda d: d["scope_exclusions"].append(
            {"prefix": cp.FIXTURE_DECLARED_HOLE_PREFIX, "reason": "synthetic hole"}
        ),
    )
    assert "scope-exclusion-stale" not in _rules_fired(root)


def test_by_reference_rules_require_the_by_reference_class(tmp_path):
    """R4: the row must say what the rule needs said, not merely exist."""
    assert cp.BY_REFERENCE_CLASS in cp.KNOWN_CLASSES

    root = _discovery_tree(tmp_path, "class-gitlink")
    cp._git_submodule_entry(root)
    cp._patch_manifest(
        root,
        lambda d: d["entries"].append(
            cp._submodule_row(row_class="attribution-statement")
        ),
    )
    assert "submodule-reference" in _rules_fired(root)

    root = _discovery_tree(tmp_path, "class-symlink")
    cp._symlink(root, cp.FIXTURE_ESCAPING_LINK_REL, cp.FIXTURE_ESCAPING_LINK_TARGET)
    cp._patch_manifest(
        root,
        lambda d: d["entries"].append(
            cp._escaping_link_row(row_class="quoted-constants")
        ),
    )
    assert "external-symlink-target" in _rules_fired(root)

    # The right class still answers both rules in full (no 'covers' needed).
    root = _discovery_tree(tmp_path, "class-right")
    cp._git_submodule_entry(root)
    cp._symlink(root, cp.FIXTURE_ESCAPING_LINK_REL, cp.FIXTURE_ESCAPING_LINK_TARGET)
    cp._git(root, "add", "-f", cp.FIXTURE_ESCAPING_LINK_REL)
    cp._patch_manifest(
        root,
        lambda d: d["entries"].extend([cp._submodule_row(), cp._escaping_link_row()]),
    )
    assert not cp.audit(root)[0], [f.as_dict() for f in cp.audit(root)[0]]


def test_discovery_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    assert cp._discovery_controls(), "the discovery controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cp._discovery_controls():
        assert case[0] in proc.stdout, f"{case[0]} not exercised by --negative-control"


# --- the index boundary (increment 11) ----------------------------------------
#
# `list_entries` reads the git INDEX, so the audited set is what the repository
# has committed or staged, not what is on disk. That is right for CI and wrong
# to leave SILENT: before this increment, an unattributed file carrying a GPL
# body, a foreign SPDX tag and a foreign copyright line, dropped into `model/`
# and left unstaged, audited PASS with a file count identical to the clean
# tree's. The boundary is kept and now disclosed; `--include-untracked` crosses
# it on demand, which is how acceptance item 4's own demonstration ("a
# deliberately unattributed file") runs against a working tree without staging
# the fixture first.


def _staged_tree(tmp_path, label):
    """A skeleton committed to a real index, so `ls-files` is the discovery path."""
    root = _discovery_tree(tmp_path, label)
    cp._git(root, "init", "-q")
    cp._git(root, "add", "-A", "-f")
    return root


def test_unstaged_carrier_is_disclosed_rather_than_silently_skipped(tmp_path):
    """The finding this increment exists for: silence, not a missed rule."""
    root = _staged_tree(tmp_path, "unstaged")
    cp._write(root, cp.FIXTURE_UNTRACKED_REL, cp.FIXTURE_GPL_BODY)

    findings, stats = cp.audit(root)
    # Default behaviour is deliberately "no finding" — so the assertion that
    # matters is what the run SAID about the entry it did not audit.
    assert not findings, [f.as_dict() for f in findings]
    assert stats["entries_present_but_not_in_the_index"] == [cp.FIXTURE_UNTRACKED_REL]
    assert stats["untracked_entries_audited"] == 0


def test_unstaged_carrier_is_audited_when_included(tmp_path):
    """`--include-untracked` crosses the boundary and the rule fires."""
    root = _staged_tree(tmp_path, "unstaged-included")
    cp._write(root, cp.FIXTURE_UNTRACKED_REL, cp.FIXTURE_GPL_BODY)

    findings, stats = cp.audit(root, include_untracked=True)
    assert stats["entries_present_but_not_in_the_index"] == []
    assert stats["untracked_entries_audited"] == 1
    fired = {f.rule for f in findings if f.path == cp.FIXTURE_UNTRACKED_REL}
    assert "foreign-license-text" in fired, [f.as_dict() for f in findings]


def test_index_boundary_count_is_printed_even_when_zero(tmp_path):
    """"None present" and "never looked" must not look alike in the report."""
    root = _staged_tree(tmp_path, "staged-zero")
    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["entries_present_but_not_in_the_index"] == []

    proc = run_tool("--root", str(root))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NOT in the git index: 0 entries" in proc.stdout


def test_index_boundary_report_names_the_unaudited_paths(tmp_path):
    """A count alone is not answerable: the report names what it skipped."""
    root = _staged_tree(tmp_path, "unstaged-report")
    cp._write(root, cp.FIXTURE_UNTRACKED_REL, cp.FIXTURE_GPL_BODY)

    proc = run_tool("--root", str(root))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NOT in the git index: 1 entries" in proc.stdout
    assert cp.FIXTURE_UNTRACKED_REL in proc.stdout

    proc = run_tool("--root", str(root), "--include-untracked")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "AUDITED (--include-untracked)" in proc.stdout
    assert "foreign-license-text" in proc.stdout


def test_ignored_paths_are_neither_counted_nor_audited(tmp_path):
    """A declared sub-boundary: `.gitignore` is this repo's own statement."""
    root = _discovery_tree(tmp_path, "ignored")
    cp._write(root, ".gitignore", cp.FIXTURE_UNTRACKED_REL + "\n")
    cp._git(root, "init", "-q")
    cp._git(root, "add", "-A", "-f")
    cp._write(root, cp.FIXTURE_UNTRACKED_REL, cp.FIXTURE_GPL_BODY)

    for included in (False, True):
        findings, stats = cp.audit(root, include_untracked=included)
        assert stats["entries_present_but_not_in_the_index"] == []
        assert not [f for f in findings if f.path == cp.FIXTURE_UNTRACKED_REL], (
            "an ignored path was audited; the sub-boundary is declared, "
            f"include_untracked={included}"
        )


def test_unstaged_path_inside_a_declared_scope_exclusion_is_not_recounted(tmp_path):
    """An already-disclosed hole is not disclosed twice under a second name."""
    root = _discovery_tree(tmp_path, "unstaged-excluded")
    cp._patch_manifest(
        root,
        lambda d: d["scope_exclusions"].append(
            {"prefix": ".loom/", "reason": "synthetic declared hole"}
        ),
    )
    # A tracked file inside the hole, so the exclusion is not itself stale.
    cp._write(root, ".loom/notes.md", "declared, unaudited.\n")
    cp._git(root, "init", "-q")
    cp._git(root, "add", "-A", "-f")
    cp._write(root, ".loom/pasted_unstaged.py", cp.FIXTURE_GPL_BODY)

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["entries_present_but_not_in_the_index"] == []


def test_non_git_tree_reports_zero_and_still_audits_every_file(tmp_path):
    """`list_untracked` must not report an enclosing repository's view.

    In a synthetic (non-checkout) tree every file is WALKED, so nothing is
    un-indexed — and the carrier must still fire. A `git ls-files --others`
    answered by an enclosing repository would report the whole tree as
    un-audited while every rule had in fact run on it.
    """
    root = _discovery_tree(tmp_path, "non-git")
    cp._write(root, cp.FIXTURE_UNTRACKED_REL, cp.FIXTURE_GPL_BODY)

    assert cp.list_untracked(root) == []
    findings, stats = cp.audit(root)
    assert stats["entries_present_but_not_in_the_index"] == []
    assert "foreign-license-text" in _fired_on(root, cp.FIXTURE_UNTRACKED_REL)


def test_real_tree_discloses_its_own_index_boundary():
    """Coverage reported separately from agreement, on the committed tree."""
    _, stats = cp.audit(REPO)
    assert "entries_present_but_not_in_the_index" in stats
    assert isinstance(stats["entries_present_but_not_in_the_index"], list)
    assert stats["untracked_entries_audited"] == 0


def test_index_boundary_is_declared_in_limits():
    """A limit that is not printed is not declared."""
    proc = run_tool("--limits")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "not in the git index" in proc.stdout
    assert "--include-untracked" in proc.stdout
    assert "entries_present_but_not_in_the_index" in proc.stdout


def test_coverage_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    cases = cp._coverage_controls() + cp._coverage_include_untracked_controls()
    assert cases, "the index-boundary coverage controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cases:
        assert case[0] in proc.stdout, f"{case[0]} not exercised by --negative-control"


# --- the staged-content boundary (increment 14) --------------------------------
#
# The audited SET came from the index (increment 11), but the audited BYTES came
# from the working tree: `Tree._read` opened `root / rel`. `git commit` commits
# the INDEX, so the two disagree exactly where it matters. Before this increment,
# `git add` on a file carrying a GPL body, a foreign SPDX tag and a foreign
# copyright line, followed by overwriting (or deleting) the working-tree copy,
# audited PASS with coverage identical to a clean tree's — while the staged blob
# the commit would publish was read by nothing. Both views are now read; the
# working-tree one is NOT replaced, because an unstaged paste into a tracked file
# is what a local pre-commit run is for.


def _staged_carrier_tree(tmp_path, label, staged=None, working=cp.FIXTURE_INNOCUOUS,
                         rel=cp.FIXTURE_STAGED_REL, assume_unchanged=False):
    """A real git index holding `staged` at `rel`, with `working` on disk."""
    root = _discovery_tree(tmp_path, label)
    cp._stage_then_replace(
        root,
        rel=rel,
        staged=staged,
        working=working,
        assume_unchanged=assume_unchanged,
    )
    return root


def test_staged_carrier_with_a_cleaned_working_copy_is_flagged(tmp_path):
    """The finding this increment exists for: the committable bytes were unread."""
    root = _staged_carrier_tree(tmp_path, "staged-cleaned")

    # The working-tree copy really is innocuous: the old tool read only this.
    assert "PUBLIC LICENSE" not in (root / cp.FIXTURE_STAGED_REL).read_text()
    findings, stats = cp.audit(root)
    fired = [
        f
        for f in findings
        if f.rule == "foreign-license-text" and f.path == cp.FIXTURE_STAGED_REL
    ]
    assert fired, [f.as_dict() for f in findings]
    # The evidence must name WHICH bytes offended: the remedy differs.
    assert any("STAGED" in f.detail for f in fired), [f.as_dict() for f in fired]
    assert stats["entries_whose_staged_content_differs_from_the_working_tree"] == [
        cp.FIXTURE_STAGED_REL
    ]
    assert stats["staged_payloads_content_scanned"] == 1


def test_staged_carrier_deleted_from_the_working_tree_is_flagged(tmp_path):
    """`open()` failed, the entry was counted among the opaque payloads."""
    root = _staged_carrier_tree(tmp_path, "staged-deleted", working=None)

    findings, stats = cp.audit(root)
    assert "foreign-license-text" in _fired_on(root, cp.FIXTURE_STAGED_REL)
    assert stats["staged_entries_absent_from_the_working_tree"] == [
        cp.FIXTURE_STAGED_REL
    ]
    # Its working-tree view still reaches no content rule — which is why the
    # staged view is the only read there is, and why that is disclosed.
    tree = cp.Tree(root, [])
    assert tree.scan_mode(cp.FIXTURE_STAGED_REL) == "unreadable"
    assert tree.scan_mode(cp.FIXTURE_STAGED_REL, cp.STAGED_VIEW) == "decoded"
    assert findings


def test_assume_unchanged_does_not_hide_the_staged_content(tmp_path):
    """git's own "stop looking" bit sits directly under this rule."""
    root = _staged_carrier_tree(tmp_path, "staged-assume", assume_unchanged=True)

    # `diff-files` alone reports nothing for an assume-unchanged entry …
    diff = subprocess.run(
        ["git", "-C", str(root), "diff-files", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert cp.FIXTURE_STAGED_REL not in diff
    # … so the divergence set must not be built from it alone.
    assert cp.FIXTURE_STAGED_REL in cp.list_staged_divergent(root)
    assert "foreign-license-text" in _fired_on(root, cp.FIXTURE_STAGED_REL)


def test_skip_worktree_does_not_hide_the_staged_content(tmp_path):
    """The other index bit with the same effect on `diff-files`."""
    root = _discovery_tree(tmp_path, "staged-skip")
    cp._write(root, cp.FIXTURE_STAGED_REL, cp.FIXTURE_GPL_BODY)
    cp._stage_all(root)
    cp._write(root, cp.FIXTURE_STAGED_REL, cp.FIXTURE_INNOCUOUS)
    cp._git(root, "update-index", "--skip-worktree", cp.FIXTURE_STAGED_REL)

    assert cp.FIXTURE_STAGED_REL in cp.list_staged_divergent(root)
    assert "foreign-license-text" in _fired_on(root, cp.FIXTURE_STAGED_REL)


def test_unstaged_working_tree_carrier_still_fires(tmp_path):
    """The regression direction: a SECOND view, not a different one.

    Reading the index INSTEAD of the working tree would close this increment's
    masking path by opening the one the audit is most used for — the local run
    before `git add`.
    """
    root = _staged_carrier_tree(
        tmp_path,
        "staged-unstaged-paste",
        staged=cp.FIXTURE_INNOCUOUS,
        working=cp.FIXTURE_GPL_BODY,
    )

    findings, _ = cp.audit(root)
    fired = [
        f
        for f in findings
        if f.rule == "foreign-license-text" and f.path == cp.FIXTURE_STAGED_REL
    ]
    assert fired, [f.as_dict() for f in findings]
    assert not any("STAGED" in f.detail for f in fired), (
        "a working-tree paste was reported as staged content"
    )


def test_innocuous_divergence_is_counted_and_read_but_not_flagged(tmp_path):
    """An edited working tree is the normal state; a finding there is noise."""
    root = _staged_carrier_tree(
        tmp_path,
        "staged-innocuous",
        staged=cp.FIXTURE_INNOCUOUS,
        working=cp.FIXTURE_INNOCUOUS + "# one more line, still nothing\n",
    )

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["entries_whose_staged_content_differs_from_the_working_tree"] == [
        cp.FIXTURE_STAGED_REL
    ]
    assert stats["staged_payloads_content_scanned"] == 1
    assert stats["staged_entries_absent_from_the_working_tree"] == []


def test_staged_wrapper_member_name_is_judged(tmp_path):
    """The name layer reads the staged bytes too, where no content signal exists."""
    root = _staged_carrier_tree(
        tmp_path,
        "staged-wrapper",
        rel=cp.FIXTURE_STAGED_BUNDLE_REL,
        staged=cp.FIXTURE_ZIP_WITH_ASSET_MEMBER_NAME,
        working=b"not an archive at all\n",
    )

    fired = _fired_on(root, cp.FIXTURE_STAGED_BUNDLE_REL)
    assert "wrapper-member-name" in fired, fired


def test_staged_view_is_read_from_the_index_blob(tmp_path):
    """Unit pin: the blob id is carried for files, and the read uses it."""
    root = _staged_carrier_tree(tmp_path, "staged-unit")

    blobs = {rel: blob for rel, kind, blob in cp.list_entries(root) if kind == "file"}
    assert blobs[cp.FIXTURE_STAGED_REL], "no blob id carried for a regular file"
    staged = cp.read_index_blob(root, blobs[cp.FIXTURE_STAGED_REL])
    assert b"PUBLIC LICENSE" in staged
    tree = cp.Tree(root, [])
    assert "PUBLIC LICENSE" in tree.text(cp.FIXTURE_STAGED_REL, cp.STAGED_VIEW)
    assert "PUBLIC LICENSE" not in tree.text(cp.FIXTURE_STAGED_REL)
    # A bad or absent id is "unread", never "clean".
    assert cp.read_index_blob(root, "") is None
    assert cp.read_index_blob(root, "not-an-object-id") is None


def test_gitlink_is_not_read_as_a_staged_blob(tmp_path):
    """A gitlink's object is a commit elsewhere, not a blob here."""
    root = _discovery_tree(tmp_path, "staged-gitlink")
    cp._git_submodule_entry(root)

    findings, stats = cp.audit(root)
    divergent = stats["entries_whose_staged_content_differs_from_the_working_tree"]
    assert cp.FIXTURE_SUBMODULE_REL not in divergent
    assert "submodule-reference" in _fired_on(root, cp.FIXTURE_SUBMODULE_REL)
    assert findings


def test_staged_divergence_inside_a_declared_scope_exclusion_is_not_counted(tmp_path):
    """An already-disclosed hole is not re-disclosed under a second name."""
    root = _discovery_tree(tmp_path, "staged-excluded")
    cp._patch_manifest(
        root,
        lambda d: d["scope_exclusions"].append(
            {"prefix": ".loom/", "reason": "synthetic declared hole"}
        ),
    )
    cp._write(root, ".loom/notes.md", "declared, unaudited.\n")
    cp._stage_then_replace(root, rel=".loom/pasted_staged.py")

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["entries_whose_staged_content_differs_from_the_working_tree"] == []


def test_scoped_exemption_does_not_carry_across_to_the_staged_view(tmp_path):
    """Spans are offsets into ONE view's text; the staged view resolves its own.

    The exemption names an occurrence of this project's own copy. A genuinely
    foreign quotation present only in the STAGED content must still fail — reusing
    the working-tree spans would exempt whatever happened to sit at those offsets.
    """
    occ = [cp.FIXTURE_OWN_COPY_OCCURRENCE]
    root = tmp_path / "staged-scoped"
    root.mkdir(parents=True, exist_ok=True)
    cp.build_skeleton(root)
    cp._write(
        root,
        "docs/own_copy.md",
        cp.FIXTURE_OWN_COPY_DOC + cp.FIXTURE_FOREIGN_COPY_LINE,
    )
    cp._scoped_exemption(root, occ)
    cp._stage_all(root)
    # The working-tree copy keeps only the exempted occurrence; the staged blob
    # still carries the foreign quotation beside it.
    cp._write(root, "docs/own_copy.md", cp.FIXTURE_OWN_COPY_DOC)

    findings, stats = cp.audit(root)
    assert "docs/own_copy.md" in (
        stats["entries_whose_staged_content_differs_from_the_working_tree"]
    )
    fired = [
        f
        for f in findings
        if f.rule == "self-declared-quotation" and f.path == "docs/own_copy.md"
    ]
    assert fired, [f.as_dict() for f in findings]
    assert any("STAGED" in f.detail for f in fired), [f.as_dict() for f in fired]


def test_scoped_exemption_still_covers_a_divergent_file_it_names(tmp_path):
    """The false-positive direction of the same mechanism.

    When the staged content carries the exempted occurrence and nothing else,
    re-resolving the spans must clear it — an exemption that stopped applying to
    the committable bytes would make an ordinary edit unanswerable.
    """
    occ = [cp.FIXTURE_OWN_COPY_OCCURRENCE]
    root = tmp_path / "staged-scoped-clean"
    root.mkdir(parents=True, exist_ok=True)
    cp.build_skeleton(root)
    cp._write(root, "docs/own_copy.md", cp.FIXTURE_OWN_COPY_DOC)
    cp._scoped_exemption(root, occ)
    cp._stage_all(root)
    cp._write(root, "docs/own_copy.md", "Leading sentence.\n\n" + cp.FIXTURE_OWN_COPY_DOC)

    findings, stats = cp.audit(root)
    assert "docs/own_copy.md" in (
        stats["entries_whose_staged_content_differs_from_the_working_tree"]
    )
    assert not findings, [f.as_dict() for f in findings]


def test_staged_divergence_count_is_printed_even_when_zero(tmp_path):
    """"Nothing diverges" and "the committable bytes were never read" differ."""
    root = _discovery_tree(tmp_path, "staged-zero-divergence")
    cp._stage_all(root)

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["entries_whose_staged_content_differs_from_the_working_tree"] == []

    proc = run_tool("--root", str(root))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "staged content not known to match the working tree: 0 entries" in proc.stdout


def test_staged_report_names_the_divergent_paths(tmp_path):
    """A count alone is not answerable: the report names what it also read."""
    root = _staged_carrier_tree(tmp_path, "staged-report", working=None)

    proc = run_tool("--root", str(root))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "staged content not known to match the working tree: 1 entries" in proc.stdout
    assert f"also audited (staged blob): {cp.FIXTURE_STAGED_REL}" in proc.stdout
    assert "not present in the working tree" in proc.stdout
    assert "STAGED" in proc.stdout


def test_real_tree_discloses_its_staged_content_boundary():
    """Coverage reported separately from agreement, on the committed tree.

    No assertion that the number is zero: a developer's working tree legitimately
    diverges from its index mid-edit, and in CI (a fresh checkout) it is zero. The
    claim under test is that the run REPORTS it either way.
    """
    _, stats = cp.audit(REPO)
    assert "entries_whose_staged_content_differs_from_the_working_tree" in stats
    assert isinstance(
        stats["entries_whose_staged_content_differs_from_the_working_tree"], list
    )
    assert isinstance(stats["staged_entries_absent_from_the_working_tree"], list)
    assert stats["staged_payloads_content_scanned"] <= len(
        stats["entries_whose_staged_content_differs_from_the_working_tree"]
    )


def test_staged_content_boundary_is_declared_in_limits():
    """A limit that is not printed is not declared."""
    proc = run_tool("--limits")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "entries_whose_staged_content_differs_from_the_working_tree" in proc.stdout
    assert "assume-unchanged" in proc.stdout
    assert "staged_entries_absent_from_the_working_tree" in proc.stdout


def test_staged_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    cases = cp._staged_controls()
    assert cases, "the staged-content controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cases:
        assert case[0] in proc.stdout, f"{case[0]} not exercised by --negative-control"


def test_bookkeeping_groups_fail_loudly_on_a_staged_only_record(tmp_path):
    """A record in the index and absent on disk is loud in either direction.

    This was increment 14's declared safe direction and it remains true after
    increment 15 moved the ANSWER SET onto the committable bytes: whichever view
    is read, a record whose header cannot be read is a finding, never a silent
    pass that lets the bookkeeping drift.
    """
    root = _discovery_tree(tmp_path, "staged-only-record")
    cp._stage_all(root)
    (root / "decision-records" / "0001-example.md").unlink()

    findings, _ = cp.audit(root)
    assert any(f.rule == "record-header-missing" for f in findings), [
        f.as_dict() for f in findings
    ]


# --- the ANSWER SET a commit publishes (increment 15) --------------------------
#
# Increment 14 asked each carriage question of both byte views an entry can
# have. The ANSWERS kept coming from the working-tree copy of
# `decision-records/` alone: `load_manifest` opened `root / MANIFEST_REL`
# directly, and `parse_records` / `parse_index` / `check_manifest` read the
# default (working-tree) view. So an answer could be published by no commit at
# all — `git add` the carrier, then write its provenance row to disk WITHOUT
# staging it, and the audit passed with the carrier's own bytes identical in
# both views, while the commit published the carrier and a manifest that does
# not mention it.
#
# The fix adds no rule. The same four groups run a second time with every read
# resolved to the committable bytes, and only when the bookkeeping actually
# diverges. Note the deliberate asymmetry with group 4's two views: a question
# is asked of BOTH views (an unstaged paste must fire before a `git add`), while
# an answer is accepted only from the view that raised the question.


def _answer_tree(tmp_path, label):
    """A clean skeleton, fully staged: one answer set, published and on disk."""
    root = _discovery_tree(tmp_path, label)
    cp._stage_all(root)
    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["divergent_bookkeeping_files"] == []
    return root


def _patch_disk_manifest(root, mutate):
    """Rewrite the manifest on disk ONLY — the whole mask in one helper."""
    cp._patch_manifest(root, mutate, stage=False)


def _committable_findings(root, rule, rel):
    findings, stats = cp.audit(root)
    fired = [f for f in findings if f.rule == rule and f.path == rel]
    return fired, findings, stats


def test_provenance_row_present_only_on_disk_does_not_answer_the_carrier(tmp_path):
    """The finding this increment exists for.

    The carrier is staged and its bytes are the same in both views. Only the
    row answering it is unstaged — so `git commit` publishes an undeclared
    GPL-bodied file, which the pre-increment tool audited PASS.
    """
    root = _answer_tree(tmp_path, "answer-unstaged-row")
    rel = cp.FIXTURE_COMMITTED_CARRIER_REL
    cp._write(root, rel, cp.FIXTURE_COMMITTED_CARRIER)
    cp._stage_all(root)
    _patch_disk_manifest(root, lambda d: d["entries"].append(cp._committed_row()))

    # The row really is there, on disk, and really is well-formed: a
    # working-tree read finds the carrier fully declared.
    on_disk = json.loads((root / cp.MANIFEST_REL).read_text(encoding="utf-8"))
    assert any(e.get("path") == rel for e in on_disk["entries"])

    fired, findings, stats = _committable_findings(root, "foreign-license-text", rel)
    assert fired, [f.as_dict() for f in findings]
    assert cp.MANIFEST_REL in stats["divergent_bookkeeping_files"]
    assert stats["committed_answer_set_findings"] >= 1


def test_the_same_row_staged_as_well_answers_the_carrier(tmp_path):
    """The positive control: the legitimate shape must stay silent.

    Without this, "flag everything" would pass the test above, and the
    increment would be a tool that cannot be used.
    """
    root = _answer_tree(tmp_path, "answer-staged-row")
    cp._write(root, cp.FIXTURE_COMMITTED_CARRIER_REL, cp.FIXTURE_COMMITTED_CARRIER)
    cp._patch_manifest(root, lambda d: d["entries"].append(cp._committed_row()))
    cp._stage_all(root)

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["divergent_bookkeeping_files"] == []
    assert stats["committed_answer_set_findings"] == 0


def test_a_row_removed_from_the_index_only_stops_answering(tmp_path):
    """The converse shape, indistinguishable from a declared file on disk."""
    root = _answer_tree(tmp_path, "answer-row-unstaged-removal")
    rel = cp.FIXTURE_SKELETON_CARRIER_REL
    full = json.loads((root / cp.MANIFEST_REL).read_text(encoding="utf-8"))
    stripped = dict(full)
    stripped["entries"] = [e for e in full["entries"] if e.get("path") != rel]
    cp._write(root, cp.MANIFEST_REL, json.dumps(stripped, indent=2) + "\n")
    cp._stage_all(root)
    cp._write(root, cp.MANIFEST_REL, json.dumps(full, indent=2) + "\n")

    fired, findings, _ = _committable_findings(root, "self-declared-quotation", rel)
    assert fired, [f.as_dict() for f in findings]


def test_an_exemption_present_only_on_disk_does_not_answer_the_rule(tmp_path):
    """The one exemptible rule cannot be exempted by an unpublished exemption."""
    root = _answer_tree(tmp_path, "answer-unstaged-exemption")
    rel = cp.FIXTURE_SKELETON_CARRIER_REL
    full = json.loads((root / cp.MANIFEST_REL).read_text(encoding="utf-8"))
    stripped = dict(full)
    stripped["entries"] = [e for e in full["entries"] if e.get("path") != rel]
    cp._write(root, cp.MANIFEST_REL, json.dumps(stripped, indent=2) + "\n")
    cp._stage_all(root)
    cp._write(root, cp.MANIFEST_REL, json.dumps(stripped, indent=2) + "\n")
    _patch_disk_manifest(
        root,
        lambda d: d["exemptions"].append(
            {
                "path": rel,
                "rules": ["self-declared-quotation"],
                "reason": "synthetic: unstaged exemption",
            }
        ),
    )

    fired, findings, _ = _committable_findings(root, "self-declared-quotation", rel)
    assert fired, [f.as_dict() for f in findings]


def test_a_scope_exclusion_present_only_on_disk_hides_nothing(tmp_path):
    """A declared hole is a statement this repository PUBLISHES.

    An exclusion prefix on disk alone withholds the carrier from no commit, so
    the committable tree must still scan it. This is the sub-case that forced the
    second pass to build its own `Tree`: the audited set itself differs.
    """
    root = _answer_tree(tmp_path, "answer-unstaged-exclusion")
    rel = cp.FIXTURE_COMMITTED_CARRIER_REL
    cp._write(root, rel, cp.FIXTURE_COMMITTED_CARRIER)
    cp._stage_all(root)
    _patch_disk_manifest(
        root,
        lambda d: d["scope_exclusions"].append(
            {"prefix": "model/", "reason": "synthetic: unstaged hole"}
        ),
    )

    fired, findings, _ = _committable_findings(root, "foreign-license-text", rel)
    assert fired, [f.as_dict() for f in findings]


def test_an_index_row_present_only_on_disk_does_not_index_the_record(tmp_path):
    """Group 1/2: the published README indexes no such record.

    This is the leg that needs the committable DEFAULT VIEW rather than the
    staged manifest read — reverting one leaves the other, and only this case
    fails.
    """
    root = _answer_tree(tmp_path, "answer-unstaged-index-row")
    cp._write(
        root,
        cp.FIXTURE_SECOND_RECORD_REL,
        "# 0002 second\n\n- **Status**: PROPOSED\n- **Date**: 2026-10-01\n",
    )
    cp._write(root, "docs/cites_0002.md", "This follows decision-records/0002-second.md.\n")
    cp._stage_all(root)
    cp._write(
        root,
        cp.INDEX_REL,
        (root / cp.INDEX_REL).read_text(encoding="utf-8").rstrip("\n")
        + "\n| [0002](0002-second.md) | Second record (synthetic) | PROPOSED | 2026-10-01 |\n",
    )

    fired, findings, stats = _committable_findings(
        root, "unindexed-record-citation", "docs/cites_0002.md"
    )
    assert fired, [f.as_dict() for f in findings]
    assert cp.INDEX_REL in stats["divergent_bookkeeping_files"]


def test_a_committable_finding_names_the_answer_set_as_its_source(tmp_path):
    """"Your file is undeclared" would be wrong AND unactionable here.

    The file IS declared — on disk — and the remedy is `git add
    decision-records/`, not a new row. A finding that does not say so sends the
    author looking for a row that is already written.
    """
    root = _answer_tree(tmp_path, "answer-finding-wording")
    rel = cp.FIXTURE_COMMITTED_CARRIER_REL
    cp._write(root, rel, cp.FIXTURE_COMMITTED_CARRIER)
    cp._stage_all(root)
    _patch_disk_manifest(root, lambda d: d["entries"].append(cp._committed_row()))

    fired, findings, _ = _committable_findings(root, "foreign-license-text", rel)
    assert fired, [f.as_dict() for f in findings]
    assert all("ANSWER SET" in f.detail for f in fired), [f.detail for f in fired]
    assert any("staged" in f.detail for f in fired), [f.detail for f in fired]


def test_an_ordinary_divergence_does_not_open_a_second_answer_set(tmp_path):
    """The second pass is scoped to the bookkeeping, not to any divergence.

    A working copy differing from the index is the normal state of a tree being
    edited. Re-judging the answer set on every such edit would double the audit's
    work and its noise for no gain, since the answers themselves did not move.
    """
    root = _answer_tree(tmp_path, "answer-ordinary-divergence")
    cp._stage_then_replace(
        root, staged=cp.FIXTURE_INNOCUOUS, working=cp.FIXTURE_INNOCUOUS + "# edited\n"
    )

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["divergent_bookkeeping_files"] == []
    # Increment 14's disclosure is unaffected: the entry IS divergent.
    assert cp.FIXTURE_STAGED_REL in stats[
        "entries_whose_staged_content_differs_from_the_working_tree"
    ]


def test_a_bookkeeping_edit_that_changes_no_answer_is_disclosed_not_flagged(tmp_path):
    """A developer rewording a `note` field is not committing a violation."""
    root = _answer_tree(tmp_path, "answer-innocuous-bookkeeping-edit")
    _patch_disk_manifest(
        root,
        lambda d: d["entries"][0].update({"content": "synthetic TABLE (reworded)"}),
    )

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert cp.MANIFEST_REL in stats["divergent_bookkeeping_files"]
    assert stats["committed_answer_set_findings"] == 0


def test_the_committed_pass_does_not_audit_untracked_files(tmp_path):
    """The committable tree IS the index, `--include-untracked` or not.

    A file no commit publishes must not produce a finding against the tree a
    commit would publish; increment 11's own boundary already owns that case.
    """
    root = _answer_tree(tmp_path, "answer-untracked-under-divergence")
    _patch_disk_manifest(
        root,
        lambda d: d["entries"][0].update({"content": "synthetic TABLE (reworded)"}),
    )
    cp._write(root, cp.FIXTURE_UNTRACKED_REL, cp.FIXTURE_GPL_BODY)

    findings, stats = cp.audit(root)
    committable = [f for f in findings if "ANSWER SET" in f.detail]
    assert not committable, [f.as_dict() for f in committable]
    assert cp.FIXTURE_UNTRACKED_REL in stats["entries_present_but_not_in_the_index"]


def test_a_path_removed_from_the_index_is_not_read_from_disk(tmp_path):
    """`git rm --cached` leaves the file on disk and in no commit.

    In the committable view such an entry has no content at all, so the
    working-tree copy must not stand in for bytes no commit would publish.
    """
    root = _answer_tree(tmp_path, "answer-rm-cached")
    tree = cp.Tree(root, [], default_view=cp.COMMITTED_VIEW)
    assert tree.view_for("docs/not-an-entry.md") == cp.STAGED_VIEW
    assert tree.view_for(cp.FIXTURE_SKELETON_CARRIER_REL) == cp.WORKTREE_VIEW
    assert tree.text("docs/not-an-entry.md") is None


def test_a_manifest_absent_from_the_index_answers_nothing(tmp_path):
    """`git rm --cached` the manifest: a commit publishes NO manifest.

    The sentinel case. `load_manifest(raw=...)` must distinguish "no text was
    supplied" from "this view holds no readable manifest" — spelling both
    `None` would make the committable pass fall back to the copy on disk and
    answer from the exact bytes it exists to stop answering from.
    """
    root = _answer_tree(tmp_path, "answer-manifest-rm-cached")
    cp._git(root, "rm", "--cached", "-q", cp.MANIFEST_REL)

    findings, stats = cp.audit(root)
    assert cp.MANIFEST_REL in stats["divergent_bookkeeping_files"], (
        "a bookkeeping file absent from the index is the largest possible "
        "difference between two answer sets and must be disclosed"
    )
    assert any(f.rule == "manifest-missing" for f in findings), [
        f.as_dict() for f in findings
    ]
    # And the carrier it used to declare is no longer answered by anything.
    assert any(
        f.rule == "self-declared-quotation" and f.path == cp.FIXTURE_SKELETON_CARRIER_REL
        for f in findings
    ), [f.as_dict() for f in findings]


def test_the_disk_sentinel_is_not_none(tmp_path):
    """Pinned directly, because the bug it prevents is invisible in behaviour.

    If `FROM_DISK` were `None`, every test above would still pass — the fallback
    only fires for a view that yields no text, which is the one case no other
    control constructs.
    """
    assert cp.FROM_DISK is not None
    manifest, findings = cp.load_manifest(tmp_path, raw=None)
    assert manifest is None
    assert [f.rule for f in findings] == ["manifest-missing"]


def test_divergent_bookkeeping_count_is_printed_even_when_zero(tmp_path):
    """"The answers agree" and "only disk was consulted" must not look alike."""
    proc = run_tool()
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    assert "bookkeeping whose staged bytes are not known to match" in proc.stdout


def test_committed_answer_set_is_declared_in_limits():
    """A limit that is not printed is not declared."""
    proc = run_tool("--limits")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "divergent_bookkeeping_files" in proc.stdout
    assert "committed_answer_set_findings" in proc.stdout


def test_committed_bookkeeping_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    cases = cp._committed_bookkeeping_controls()
    assert cases, "the committed-answer-set controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cases:
        assert case[0] in proc.stdout, f"{case[0]} not exercised by --negative-control"


def test_fixture_manifest_patches_are_staged_by_default(tmp_path):
    """Two pre-existing controls were passing on an answer no commit published.

    `_patch_manifest` wrote the manifest to disk without staging it, so
    `discovery/submodule-gitlink-answered-by-a-row` and its excluded twin were
    answered by an unstaged row. Fixed by staging the fixture's answer, not by
    exempting the controls — and pinned here so it cannot silently regress.
    """
    root = _discovery_tree(tmp_path, "fixture-staging")
    cp._git_submodule_entry(root)
    cp._patch_manifest(root, lambda d: d["entries"].append(cp._submodule_row()))

    findings, stats = cp.audit(root)
    assert stats["divergent_bookkeeping_files"] == [], (
        "the fixture left its own answer unstaged"
    )
    assert not findings, [f.as_dict() for f in findings]


# --- the EVIDENCE a bookkeeping judgement reads (increment 16) ------------------
#
# Increment 14 moved group 4 onto both byte views of an entry; increment 15
# moved the four groups' ANSWER SET onto the committable bookkeeping. Neither
# reached the two places where a BOOKKEEPING group reads an ENTRY's own content
# as the evidence for its judgement — `check_citations` (group 2) and a
# provenance row's corroboration (group 3). Both read the tree's default view
# alone, and neither increment's trigger covers them: group 4 enumerates views
# for its own rules, and the committable pass fires only when
# `decision-records/` diverges, which it does not when the divergent entry is
# the CARRIER.
#
# Every must-fire case below therefore audited PASS on increment 15's tool, with
# the carrier disclosed as divergent and found clean by group 4 — correctly,
# because the staged bytes carry no carriage signal. The defect is in what
# answers the bookkeeping, not in what the bytes carry.


def _evidence_tree(tmp_path, label):
    """A clean skeleton, fully staged, with no bookkeeping divergence at all."""
    root = _discovery_tree(tmp_path, label)
    cp._stage_all(root)
    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert stats["divergent_bookkeeping_files"] == []
    return root


def _restage(root, rel, staged, working):
    """Put `staged` in the index and `working` (or nothing) on disk."""
    cp._write(root, rel, staged)
    cp._git(root, "add", "-f", rel)
    if working is None:
        (root / rel).unlink()
    else:
        cp._write(root, rel, working)


def test_a_row_corroborated_only_by_the_copy_on_disk_is_flagged(tmp_path):
    """The finding this increment exists for.

    The row is staged, well-formed and identical in both views. Only the
    CARRIER diverges — and the bytes a commit publishes cite neither its
    decision record nor its pinned commit, so the published row describes a
    file that states no provenance at all.
    """
    root = _evidence_tree(tmp_path, "evidence-row-on-disk-only")
    rel = cp.FIXTURE_SKELETON_CARRIER_REL
    _restage(root, rel, cp.FIXTURE_UNCITED_CARRIER, cp.SKELETON_CARRIER)

    findings, stats = cp.audit(root)
    fired = [f for f in findings if f.rule == "manifest-uncorroborated" and f.path == rel]
    assert fired, [f.as_dict() for f in findings]
    # The defect is NOT an answer-set divergence: the committable pass never ran.
    assert stats["divergent_bookkeeping_files"] == []
    assert stats["committed_answer_set_findings"] == 0
    assert rel in stats["entries_whose_staged_content_differs_from_the_working_tree"]
    assert rel in stats["staged_views_read_as_bookkeeping_evidence"]
    assert any("STAGED" in f.detail for f in fired), [f.as_dict() for f in fired]


def test_a_row_whose_only_published_carrier_was_deleted_from_disk_is_flagged(tmp_path):
    """The shape whose working-tree view used to answer for the staged one.

    `tree.text()` returns None for a path that is not on disk, and the
    pre-increment `_corroborate` read exactly one view and returned [] on None —
    so the only bytes a commit publishes were read by no bookkeeping check.
    """
    root = _evidence_tree(tmp_path, "evidence-carrier-deleted")
    rel = cp.FIXTURE_SKELETON_CARRIER_REL
    _restage(root, rel, cp.FIXTURE_UNCITED_CARRIER, None)

    findings, stats = cp.audit(root)
    fired = [f for f in findings if f.rule == "manifest-uncorroborated" and f.path == rel]
    assert fired, [f.as_dict() for f in findings]
    assert rel in stats["staged_entries_absent_from_the_working_tree"]
    assert rel in stats["staged_views_read_as_bookkeeping_evidence"]


def test_a_record_citation_only_in_the_staged_bytes_must_resolve(tmp_path):
    """A citation published by the index is still published."""
    root = _evidence_tree(tmp_path, "evidence-staged-citation")
    rel = cp.FIXTURE_EVIDENCE_DOC_REL
    _restage(
        root,
        rel,
        cp.FIXTURE_DANGLING_CITATION,
        cp.FIXTURE_EVIDENCE_INNOCUOUS_DOC,
    )

    findings, stats = cp.audit(root)
    fired = [
        f for f in findings if f.rule == "dangling-record-citation" and f.path == rel
    ]
    assert fired, [f.as_dict() for f in findings]
    assert any("STAGED" in f.detail for f in fired), [f.as_dict() for f in fired]
    assert stats["divergent_bookkeeping_files"] == []


def test_the_working_tree_view_is_joined_not_replaced(tmp_path):
    """The regression direction, for both checks at once.

    A pre-commit run on an unstaged edit is what this audit is most used for.
    Closing the staged hole by reading the index INSTEAD of the working tree
    would open that one, so both defects are written on disk only here and must
    still fire — and must not be mislabelled as staged content.
    """
    root = _evidence_tree(tmp_path, "evidence-worktree-still-fires")
    doc = cp.FIXTURE_EVIDENCE_DOC_REL
    carrier = cp.FIXTURE_SKELETON_CARRIER_REL
    _restage(root, doc, cp.FIXTURE_EVIDENCE_INNOCUOUS_DOC, cp.FIXTURE_DANGLING_CITATION)
    _restage(root, carrier, cp.SKELETON_CARRIER, cp.FIXTURE_UNCITED_CARRIER)

    findings, _ = cp.audit(root)
    for rule, rel in (
        ("dangling-record-citation", doc),
        ("manifest-uncorroborated", carrier),
    ):
        fired = [f for f in findings if f.rule == rule and f.path == rel]
        assert fired, (rule, rel, [f.as_dict() for f in findings])
        assert not any("STAGED" in f.detail for f in fired), [f.as_dict() for f in fired]


def test_a_carrier_that_states_its_provenance_in_both_views_is_read_not_flagged(
    tmp_path,
):
    """The positive control: an ordinary unstaged edit must stay silent.

    Without it, "flag every divergent declared carrier" would pass the tests
    above and the audit would be unusable on any tree being edited.
    """
    root = _evidence_tree(tmp_path, "evidence-both-views-cite")
    rel = cp.FIXTURE_SKELETON_CARRIER_REL
    _restage(root, rel, cp.SKELETON_CARRIER, cp.SKELETON_CARRIER + "\nEXTRA = [7]\n")

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert rel in stats["entries_whose_staged_content_differs_from_the_working_tree"]
    assert rel in stats["staged_views_read_as_bookkeeping_evidence"]


def test_a_binary_payloads_row_is_corroborated_in_neither_view(tmp_path):
    """"No text in this view, so the row is the record" stays a boundary.

    It is now a per-view statement rather than a per-entry one, which is what
    closed the deleted-carrier shape above. A payload that yields no text in
    EITHER view must still be disclosed, not read, and not flagged — otherwise
    every declared opaque asset becomes a finding the moment its bytes change.
    """
    root = _evidence_tree(tmp_path, "evidence-opaque-row")
    rel = cp.FIXTURE_OPAQUE_ROW_REL
    cp._write(root, rel, cp._float_dump(seed=11))
    cp._patch_manifest(
        root,
        lambda d: d["entries"].append(
            {
                "path": rel,
                "class": "quoted-constants",
                "content": "synthetic opaque dump",
                "upstream": "synthetic upstream",
                "pinned_commit": cp.FIXTURE_SUBMODULE_COMMIT,
                "upstream_license": "GPL-3.0-or-later",
                "decision_record": "0001",
            }
        ),
    )
    cp._stage_all(root)
    _restage(root, rel, cp._float_dump(seed=22), cp._float_dump(seed=33))

    findings, stats = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]
    assert rel in stats["entries_whose_staged_content_differs_from_the_working_tree"]
    assert rel not in stats["staged_views_read_as_bookkeeping_evidence"]


def test_entry_views_is_the_single_definition_of_the_view_set(tmp_path):
    """Group 4 and the two bookkeeping checks must enumerate the same views.

    Three copies of the same two lines is how one of them gets moved and the
    others left behind — the shape of every mask this series has closed. The
    enumeration `check_tripwires` performed inline is now `entry_views`, and
    every entry in `staged_views` is in `files` by construction, so the per-entry
    loop covers exactly what the two sequential loops did.
    """
    root = _evidence_tree(tmp_path, "evidence-one-enumeration")
    rel = cp.FIXTURE_SKELETON_CARRIER_REL
    _restage(root, rel, cp.SKELETON_CARRIER, cp.SKELETON_CARRIER + "\nEXTRA = [7]\n")
    tree = cp.Tree(root, [])
    assert set(tree.staged_views) <= set(tree.files)
    assert cp.entry_views(tree, rel) == [cp.WORKTREE_VIEW, cp.STAGED_VIEW]
    clean = next(r for r in tree.files if r not in tree.staged_views)
    assert cp.entry_views(tree, clean) == [cp.WORKTREE_VIEW]


def test_bookkeeping_evidence_coverage_is_printed_even_when_empty():
    """"Both views agreed" and "only one view was read" must not look alike."""
    proc = run_tool()
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    assert "staged views read as BOOKKEEPING evidence" in proc.stdout


def test_committable_evidence_boundary_is_declared_in_limits():
    """A limit that is not printed is not declared."""
    proc = run_tool("--limits")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "staged_views_read_as_bookkeeping_evidence" in proc.stdout


def test_committable_evidence_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    cases = cp._committable_evidence_controls()
    assert cases, "the committable-evidence controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cases:
        assert case[0] in proc.stdout, f"{case[0]} not exercised by --negative-control"


# --- the history boundary (increment 17) --------------------------------------
#
# Every family above audits a tree that exists NOW — the working copy, the index,
# the committable bytes, the committable answers. These audit what the commit
# graph PUBLISHES, which in a merge-commit repository is permanent: a carrier
# added by one commit and deleted by the next stays in every clone while the
# final tree audits clean.


def _history_tree(tmp_path, label):
    """A clean skeleton that is a git checkout with one clean commit."""
    root = _discovery_tree(tmp_path, label)
    cp._history_repo(root)
    return root


def _history_rules(findings):
    return sorted({f.rule for f in findings})


def test_a_carrier_published_then_deleted_is_invisible_to_the_tree_audit(tmp_path):
    """The premise of the whole increment, asserted rather than assumed."""
    root = _history_tree(tmp_path, "history-premise")
    rel = cp.FIXTURE_HISTORY_CARRIER_REL
    cp._write(root, rel, cp.FIXTURE_GPL_BODY)
    cp._commit_all(root, "add an undeclared carrier")
    (root / rel).unlink()
    cp._commit_all(root, "delete it again")

    findings, _ = cp.audit(root)
    assert not findings, [f.as_dict() for f in findings]

    # …and the bytes are still there, in the commit that published them.
    history, stats = cp.audit_history(root, cp.HISTORY_CONTROL_RANGE)
    assert "foreign-license-text" in _history_rules(history), [
        f.as_dict() for f in history
    ]
    assert stats["commits_judged"] == 3, stats
    offender = next(f for f in history if f.rule == "foreign-license-text")
    assert offender.path.startswith(rel + " [commit "), offender.path
    assert cp.TIP_ABSENT in offender.detail, offender.detail


def test_history_answers_come_from_the_commit_that_published_the_bytes(tmp_path):
    """A row added by a later commit does not declare what an earlier one published."""
    root = _history_tree(tmp_path, "history-late-row")
    rel = cp.FIXTURE_HISTORY_CARRIER_REL
    cp._write(root, rel, cp.FIXTURE_GPL_BODY)
    cp._commit_all(root, "add the carrier")
    cp._write(root, rel, cp.FIXTURE_GPL_BODY + "\n# Provenance: " + "DR-" + "0001.\n")
    cp._patch_manifest(
        root, lambda d: d["entries"].append(cp._history_row(rel)), stage=False
    )
    cp._commit_all(root, "declare it, one commit late")

    tree_findings, _ = cp.audit(root)
    assert not tree_findings, [f.as_dict() for f in tree_findings]
    history, stats = cp.audit_history(root, cp.HISTORY_CONTROL_RANGE)
    assert "foreign-license-text" in _history_rules(history), [
        f.as_dict() for f in history
    ]
    offender = next(f for f in history if f.rule == "foreign-license-text")
    assert cp.TIP_ANSWERED in offender.detail, offender.detail
    assert stats["findings_by_standing_at_the_range_tip"][cp.TIP_ANSWERED] >= 1, stats


def test_a_carrier_declared_in_its_own_commit_is_not_a_history_finding(tmp_path):
    """The positive control: the mode must not be a blanket alarm on history."""
    root = _history_tree(tmp_path, "history-declared")
    rel = cp.FIXTURE_HISTORY_CARRIER_REL
    cp._write(root, rel, cp.FIXTURE_GPL_BODY)
    cp._patch_manifest(
        root, lambda d: d["entries"].append(cp._history_row(rel)), stage=False
    )
    cp._commit_all(root, "add a carrier and its row together")

    history, stats = cp.audit_history(root, cp.HISTORY_CONTROL_RANGE)
    assert not history, [f.as_dict() for f in history]
    assert stats["commits_judged"] == 2, stats


def test_a_commit_with_no_answer_set_is_disclosed_not_judged(tmp_path):
    """NOT_RUN, named, and never folded into a PASS.

    The pre-bookkeeping era (and, in a merge-commit history, every commit of a
    branch forked before the manifest landed) has no answer set to be judged
    against. Judging it anyway would produce one finding per carrier per commit
    and bury the signal; skipping it silently would be worse.
    """
    root = tmp_path / "history-pre-manifest"
    root.mkdir()
    cp.build_skeleton(root)
    (root / cp.MANIFEST_REL).unlink()
    cp._write(root, cp.FIXTURE_HISTORY_CARRIER_REL, cp.FIXTURE_GPL_BODY)
    cp._git(root, "init", "-q")
    cp._commit_all(root, "a tree from before the provenance manifest existed")
    (root / cp.FIXTURE_HISTORY_CARRIER_REL).unlink()
    cp.build_skeleton(root)
    cp._commit_all(root, "introduce the provenance manifest")

    history, stats = cp.audit_history(root, cp.HISTORY_CONTROL_RANGE)
    assert not history, [f.as_dict() for f in history]
    assert stats["commits_judged"] == 1, stats
    unjudged = stats["commits_not_judged_no_answer_set_yet"]
    assert len(unjudged) == 1, unjudged
    assert "subject" in unjudged[0] and unjudged[0]["commit"], unjudged


def test_deleting_the_manifest_does_not_make_a_commit_unjudged(tmp_path):
    """The one way the NOT_RUN disclosure above could have become an escape hatch."""
    root = _history_tree(tmp_path, "history-dropped-manifest")
    cp._write(root, cp.FIXTURE_HISTORY_CARRIER_REL, cp.FIXTURE_GPL_BODY)
    (root / cp.MANIFEST_REL).unlink()
    cp._commit_all(root, "delete the answer set and add a carrier at once")

    history, stats = cp.audit_history(root, cp.HISTORY_CONTROL_RANGE)
    assert "foreign-license-text" in _history_rules(history), [
        f.as_dict() for f in history
    ]
    assert stats["commits_that_published_no_manifest_after_one_existed"], stats
    assert not stats["commits_not_judged_no_answer_set_yet"], stats


def test_history_reads_structural_signals_from_the_commits_own_entries(tmp_path):
    """The extension and by-reference rules must be reachable in a commit tree.

    They are gated on the tree's PRIMARY view. Spelled `== WORKTREE_VIEW`, that
    gate makes every extension rule and both by-reference rules silently
    unreachable here — a whole rule group reporting "nothing offended" for a view
    it never examined.
    """
    root = _history_tree(tmp_path, "history-structural")
    asset = cp.FIXTURE_HISTORY_ASSET_REL
    cp._write(root, asset, cp.FIXTURE_MARKER_FREE_ASSET_PAYLOAD)
    cp._symlink(root, cp.FIXTURE_ESCAPING_LINK_REL, cp.FIXTURE_ESCAPING_LINK_TARGET)
    cp._commit_all(root, "publish an upstream asset and an escaping link")
    (root / asset).unlink()
    (root / cp.FIXTURE_ESCAPING_LINK_REL).unlink()
    cp._commit_all(root, "delete both")

    tree_findings, _ = cp.audit(root)
    assert not tree_findings, [f.as_dict() for f in tree_findings]
    history, _ = cp.audit_history(root, cp.HISTORY_CONTROL_RANGE)
    rules = _history_rules(history)
    assert "upstream-asset-extension" in rules, [f.as_dict() for f in history]
    assert "external-symlink-target" in rules, [f.as_dict() for f in history]
    escape = next(f for f in history if f.rule == "external-symlink-target")
    assert "escapes the audited tree" in escape.detail, escape.detail


def test_an_in_repo_symlink_in_history_is_not_a_signal(tmp_path):
    """The must-NOT-fire half of the same read, on a non-exemptible rule.

    `CLAUDE.md -> AGENTS.md` is this repository's own shape. Resolving a historical
    link against the current checkout — where the link no longer exists — would
    invent an `external-symlink-target` finding that no exemption can answer.
    """
    root = _history_tree(tmp_path, "history-in-repo-link")
    cp._symlink(root, cp.FIXTURE_HISTORY_ALIAS_REL, "plain.md")
    cp._commit_all(root, "add an in-repo alias")
    (root / cp.FIXTURE_HISTORY_ALIAS_REL).unlink()
    cp._commit_all(root, "delete the alias")

    history, stats = cp.audit_history(root, cp.HISTORY_CONTROL_RANGE)
    assert not history, [f.as_dict() for f in history]
    assert stats["commits_judged"] == 3, stats


def test_the_signal_cache_is_keyed_by_path_and_blob(tmp_path):
    """Identical bytes at two paths carry different structural signals."""
    root = _history_tree(tmp_path, "history-cache-key")
    first = cp.FIXTURE_HISTORY_CARRIER_REL
    second = cp.FIXTURE_HISTORY_ASSET_REL
    cp._write(root, first, cp.FIXTURE_GPL_BODY)
    cp._commit_all(root, "publish the bytes at a .py path")
    (root / first).unlink()
    cp._write(root, second, cp.FIXTURE_GPL_BODY)
    cp._commit_all(root, "republish the same bytes at a .wt path")
    (root / second).unlink()
    cp._commit_all(root, "delete it")

    history, _ = cp.audit_history(root, cp.HISTORY_CONTROL_RANGE)
    pairs = {(f.rule, f.path.split(" [commit ")[0]) for f in history}
    assert ("foreign-license-text", first) in pairs, pairs
    assert ("upstream-asset-extension", second) in pairs, pairs


def test_an_empty_commit_range_is_an_error_not_a_pass(tmp_path):
    """"Nothing audited" and "nothing offended" must never look alike."""
    root = _history_tree(tmp_path, "history-empty-range")
    try:
        cp.audit_history(root, "HEAD..HEAD")
    except cp.AuditError as exc:
        assert "no commits" in str(exc), str(exc)
    else:  # pragma: no cover - the refusal is the behaviour under test
        raise AssertionError("an empty range reported a verdict")


def test_history_mode_is_reachable_from_the_cli_and_discloses_its_coverage(tmp_path):
    """The mode a reviewer actually runs, including its NOT_RUN disclosures.

    Against a fixture repository of its own, NOT this checkout: `HEAD~1` does not
    resolve in a shallow clone, and `actions/checkout@v4` fetches depth 1 by
    default, so running the range against `REPO` made the test assert on the
    clone depth of whatever tree it happened to run in (it passed locally and
    failed in CI with "ambiguous argument 'HEAD~1..HEAD'"). The fixture is built
    with two commits here, so the rev-range spelling is still exercised — which
    is the part of the CLI surface this test exists to cover.
    """
    root = _history_tree(tmp_path, "history-cli")
    cp._write(root, "docs/second.md", "A second commit with nothing of interest.\n")
    cp._commit_all(root, "a second clean commit, so HEAD~1 resolves")
    proc = run_tool("--root", str(root), "--commits", "HEAD~1..HEAD")
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    for line in (
        "provenance history audit of",
        "commits in range",
        "not judged (no provenance manifest had been published yet",
        "published no manifest after one had existed",
        "distinct (path, blob) pairs published by the judged commits",
        "findings by standing at the range tip",
    ):
        assert line in proc.stdout, proc.stdout


def test_history_boundaries_are_declared_in_limits():
    """A limit that is not printed is not declared."""
    proc = run_tool("--limits")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for line in (
        "--commits",
        "commits_not_judged_no_answer_set_yet",
        "the rules applied are TODAY's",
    ):
        assert line in proc.stdout, "missing from --limits: " + line


def test_history_controls_run_in_the_self_test():
    """Wired into `--negative-control`, not merely defined."""
    cases = cp._history_controls()
    assert cases, "the history controls must not be empty"
    proc = run_tool("--negative-control")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for case in cases:
        assert case[0] in proc.stdout, f"{case[0]} not exercised by --negative-control"


# --- the CI gate on per-commit declaration (#300) -----------------------------
#
# The history mode is a documented step until something runs it; #300 decided it
# gates every pull request, over that branch's own commits, with the
# declare-in-the-adding-commit policy stated rather than left implicit in the
# range. These cases read the workflow and exercise the gate's exit-code
# contract. Like the CLI case above, none of them run a range against THIS
# checkout: a test that did would be asserting on the clone depth it happened to
# run in rather than on the gate.

CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
REUSE_AUDIT_DOC = REPO / "docs" / "REUSE-AUDIT.md"


def _ci_job_block(name):
    """The lines of one ci.yml job, by indentation.

    Deliberately not a YAML parse: the `tests` job installs numpy and pytest
    only, so PyYAML is not importable in the one environment whose verdict
    counts, and a test that skipped there would be NOT_RUN disguised as green.
    """
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  {name}:")
    block = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("    "):
            break
        block.append(line)
    assert block, f"job {name} has no body"
    return "\n".join(block)


def test_ci_gates_pull_requests_on_per_commit_declaration():
    """The decision of #300, read off the workflow rather than off its prose."""
    block = _ci_job_block("provenance-audit")
    # Without this the range is unresolvable and the gate can only ever say
    # NOT_RUN (exit 2) -- it would be a job that cannot run, not a check.
    assert "fetch-depth: 0" in block, block
    assert "--commits" in block, block
    # This branch's own commits: excludes the base branch's history (so main's
    # 16 existing findings are never re-litigated here, #25) and GitHub's
    # synthetic refs/pull/N/merge commit, and resolves on a fork PR.
    assert "refs/remotes/origin/${BASE_REF}..${HEAD_SHA}" in block, block
    # The gate is an addition, not a replacement: the tree audit and the
    # audit's own negative control must still run ahead of it.
    assert "--negative-control" in block, block
    # No way for the gate to be green without having run. Checked against the
    # directives only -- the job's comments discuss the absence of a bypass.
    directives = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )
    assert "continue-on-error" not in directives, directives
    # A non-pull_request event has no such range; it must say so, not pass.
    assert "NOT_RUN" in block, block


def test_the_reuse_audit_doc_and_the_workflow_agree_about_enforcement():
    """The drift #300 was filed against: a rule assumed to be enforced.

    Either the doc states the gate and the workflow runs it, or the doc states
    that it does not -- never the pair that lets a reviewer assume a check they
    do not have.
    """
    doc = REUSE_AUDIT_DOC.read_text(encoding="utf-8")
    gated = "--commits" in _ci_job_block("provenance-audit")
    claims_ungated = "CI does **not** run it today" in doc
    assert gated != claims_ungated, (
        f"workflow gated={gated} but docs/REUSE-AUDIT.md claims ungated="
        f"{claims_ungated}"
    )
    if gated:
        assert "CI gates every pull request on" in doc, (
            "the gate exists but docs/REUSE-AUDIT.md does not state the policy "
            "it enforces"
        )


def test_the_ci_gate_fails_a_carrier_declared_one_commit_late(tmp_path):
    """#300's failure control, through the exact CLI the workflow step runs."""
    root = _history_tree(tmp_path, "ci-gate-late")
    rel = cp.FIXTURE_HISTORY_CARRIER_REL
    cp._write(root, rel, cp.FIXTURE_GPL_BODY)
    cp._commit_all(root, "add the carrier")
    cp._write(root, rel, cp.FIXTURE_GPL_BODY + "\n# Provenance: " + "DR-" + "0001.\n")
    cp._patch_manifest(
        root, lambda d: d["entries"].append(cp._history_row(rel)), stage=False
    )
    cp._commit_all(root, "declare it, one commit late")

    # The merged tree is clean -- which is precisely why the tree audit cannot
    # be the gate for this shape.
    tree = run_tool("--root", str(root))
    assert tree.returncode == 0, tree.stdout + tree.stderr

    gate = run_tool("--root", str(root), "--commits", "HEAD~2..HEAD")
    assert gate.returncode == 1, gate.stdout + gate.stderr
    assert "FAIL" in gate.stdout, gate.stdout
    assert rel in gate.stdout, gate.stdout


def test_the_ci_gate_passes_a_carrier_declared_in_its_own_commit(tmp_path):
    """The positive control: the gate must not fail every branch that declares."""
    root = _history_tree(tmp_path, "ci-gate-same-commit")
    rel = cp.FIXTURE_HISTORY_CARRIER_REL
    cp._write(
        root, rel, cp.FIXTURE_GPL_BODY + "\n# Provenance: " + "DR-" + "0001.\n"
    )
    cp._patch_manifest(
        root, lambda d: d["entries"].append(cp._history_row(rel)), stage=False
    )
    cp._commit_all(root, "add a carrier AND its row, together")

    gate = run_tool("--root", str(root), "--commits", "HEAD~1..HEAD")
    assert gate.returncode == 0, gate.stdout + gate.stderr
    assert "PASS" in gate.stdout, gate.stdout


def test_the_ci_gate_reports_an_unauditable_range_as_not_run(tmp_path):
    """A shallow checkout or a main push must never look like a clean gate.

    Both collapse to the same CLI behaviour the workflow relies on: a range
    that resolves to nothing is exit 2 with a NOT_RUN disclosure, never exit 0.
    """
    root = _history_tree(tmp_path, "ci-gate-unauditable")
    cp._write(root, "docs/second.md", "A second clean commit.\n")
    cp._commit_all(root, "a second clean commit")

    empty = run_tool("--root", str(root), "--commits", "HEAD..HEAD")
    assert empty.returncode == 2, empty.stdout + empty.stderr
    assert "NOT_RUN" in empty.stdout + empty.stderr, empty.stdout + empty.stderr

    missing = run_tool("--root", str(root), "--commits", "no/such/ref..HEAD")
    assert missing.returncode == 2, missing.stdout + missing.stderr
