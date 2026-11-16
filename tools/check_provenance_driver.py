#!/usr/bin/env python3
"""SXT-019 provenance audit — the audit drivers and their reporters.

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule,
message or output line was changed, reordered or reflowed). This module runs
the checks in order over a tree (`audit`) or over a commit range
(`audit_history`) and renders each one's report. It is the last layer before
the CLI facade and imports every layer below it.
"""

from __future__ import annotations

import json
from pathlib import Path

from check_provenance_manifest import (
    FROM_DISK,
    check_manifest,
    load_manifest,
    scope_exclusion_prefixes,
)
from check_provenance_records import (
    check_citations,
    check_index,
    parse_index,
    parse_records,
)
from check_provenance_register import (
    check_register,
)
from check_provenance_rules import (
    INDEX_REL,
    MANIFEST_REL,
    TRIPWIRE_RULES,
)
from check_provenance_signals import (
    AuditError,
    CAVEAT,
    Finding,
)
from check_provenance_tree import (
    COMMITTED_VIEW,
    HISTORY_COMMITS_LISTED,
    HISTORY_VIEW,
    STAGED_PATHS_LISTED,
    STAGED_VIEW,
    Tree,
    UNINDEXED_PATHS_LISTED,
    _view_label,
    commit_label,
    commit_log,
    commit_publishes_manifest,
    list_entries_at_commit,
    read_index_blob,
)
from check_provenance_tripwires import (
    check_tripwires,
)


# --- audit driver -------------------------------------------------------------


COMMITTED_PREFIX = (
    "in the ANSWER SET a commit would publish (the staged "
    "decision-records bookkeeping differs from the copy on disk)"
)


def _committed_pass(root: Path, tree: Tree, already):
    """Re-judge the tree against the ANSWER SET a commit would publish.

    Increment 15. Increment 14 moved the carriage rules (group 4) onto both byte
    views an entry can have; the four groups' ANSWERS — a provenance row, an
    exemption, a scope exclusion, the record index, a record's own header —
    stayed on the working-tree copy of `decision-records/`. So an answer could
    be published by no commit at all: `git add` the carrier, then add its row to
    `provenance.json` on disk WITHOUT staging it, and the audit passed with
    coverage identical to a legitimately declared tree's, while the commit
    published the carrier and a manifest that does not mention it.

    The fix is not a new rule. It is to run the SAME four groups a second time
    with every read resolved to the committable bytes (`COMMITTED_VIEW`), and
    only when the bookkeeping actually diverges — so a tree whose
    `decision-records/` is staged, or has no unstaged edits at all, takes this
    path not at all and behaves exactly as before.

    `already` is the (rule, path) set pass one produced: a finding both answer
    sets agree on is reported once, by the pass that reads what the author is
    looking at. What survives here is the finding that exists ONLY in the
    committable tree, which is the whole mask.

    Note the deliberate asymmetry with group 4's two views: a carriage question
    is asked of BOTH views (an unstaged paste must fire before a `git add`),
    while an answer is accepted only from the view that raised the question. An
    answer is a claim this repository publishes; a question is a fact about bytes
    on hand.
    """
    divergent = tree.divergent_bookkeeping()
    if not divergent:
        return [], []
    # The staged manifest's own bytes, read through the shared cache. Read from
    # the FIRST tree, because the committable tree's scope exclusions come out
    # of this manifest and cannot be known before it is parsed.
    # When the manifest itself does not diverge, `FROM_DISK` makes this read
    # byte-for-byte the one pass one performed, rather than a second read
    # through the content-scan machinery that could differ on an odd encoding.
    raw = (
        tree.text(MANIFEST_REL, STAGED_VIEW) if MANIFEST_REL in divergent else FROM_DISK
    )
    label = _view_label(MANIFEST_REL, STAGED_VIEW)
    manifest, findings = load_manifest(root, raw=raw, label=label)
    if manifest is None:
        manifest = {"entries": [], "exemptions": [], "scope_exclusions": []}
    # include_untracked is deliberately NOT carried over: the committable tree
    # is the index. A file that is not in the index is published by no commit,
    # so judging it here would report a finding against a tree that does not
    # exist — pass one already audits it when the flag is on, and increment 11's
    # coverage line discloses it when the flag is off.
    committed = Tree(
        root,
        scope_exclusion_prefixes(manifest),
        include_untracked=False,
        default_view=COMMITTED_VIEW,
        share_reads_from=tree,
    )
    records, record_findings = parse_records(committed)
    try:
        rows, index_findings = parse_index(committed)
    except AuditError as exc:
        # The working-tree README parsed (pass one got this far), so this is a
        # statement about the committable bytes alone: reported as a finding
        # against the staged index, never as an audit that could not run.
        return findings + [
            Finding(
                "index-row-malformed",
                _view_label(INDEX_REL, STAGED_VIEW),
                f"{exc} — {COMMITTED_PREFIX}",
            )
        ], divergent
    findings += record_findings + index_findings
    findings += check_index(records, rows)
    findings += check_citations(committed, records, rows)
    manifest_findings, coverage, exemptions = check_manifest(
        committed, manifest, records, rows, manifest_rel=label
    )
    findings += manifest_findings
    tripwire_findings, _ = check_tripwires(committed, coverage, exemptions)
    findings += tripwire_findings
    tagged = []
    for finding in findings:
        if (finding.rule, finding.path) in already:
            continue
        tagged.append(Finding(finding.rule, finding.path, f"{COMMITTED_PREFIX} — {finding.detail}"))
    return tagged, divergent


def audit(root: Path, include_untracked=False):
    root = Path(root)
    manifest, findings = load_manifest(root)
    if manifest is None:
        manifest = {"entries": [], "exemptions": [], "scope_exclusions": []}
    tree = Tree(root, scope_exclusion_prefixes(manifest), include_untracked)
    records, record_findings = parse_records(tree)
    rows, index_findings = parse_index(tree)
    findings = list(findings) + record_findings + index_findings
    findings += check_index(records, rows)
    findings += check_citations(tree, records, rows)
    manifest_findings, coverage, exemptions = check_manifest(tree, manifest, records, rows)
    findings += manifest_findings
    register_findings, register_stats = check_register(tree, manifest, records, rows)
    findings += register_findings
    tripwire_findings, tripwire_counts = check_tripwires(tree, coverage, exemptions)
    findings += tripwire_findings
    committed_findings, divergent_bookkeeping = _committed_pass(
        root, tree, {(f.rule, f.path) for f in findings}
    )
    findings += committed_findings
    stats = {
        "files_scanned": len(tree.files),
        "files_excluded": sum(len(v) for v in tree.excluded.values()),
        "exclusions": {k: len(v) for k, v in sorted(tree.excluded.items())},
        "records": len(records),
        "index_rows": len(rows),
        "provenance_rows": len(manifest.get("entries", []) or []),
        "files_covered_by_rows": len(coverage),
        "exemptions": len(manifest.get("exemptions", []) or []),
        # GPL-boundary register (issue #370): rows reconciled, and the rows
        # listed but flagged `provenance incomplete` (disclosed, not failed).
        "gpl_boundary_register": register_stats,
        # Disclosed, not silent: these files reached no content rule at all,
        # so a PASS says nothing about what is inside them (DECLARED LIMITS).
        # Counted over REGULAR files only: a by-reference entry has no bytes of
        # its own, and reporting it here read as "an undecodable payload" —
        # which is how a gitlink hid among the renders (increment 7).
        "files_not_content_scanned": sum(
            1
            for rel in tree.files
            if tree.kind(rel) == "file" and tree.scan_mode(rel) in ("none", "unreadable")
        ),
        # The two weaker scan modes, reported SEPARATELY from a full decode:
        # a wrapper's members were read as their own payloads, and a binary
        # payload was read only as the ASCII runs it carries (increment 8).
        "files_unwrapped_from_wrappers": sum(
            1 for rel in tree.files if tree.scan_mode(rel) == "unwrapped"
        ),
        "files_scanned_as_extracted_strings": sum(
            1 for rel in tree.files if tree.scan_mode(rel) == "strings"
        ),
        # Names recovered from inside wrappers and judged by the extension sets
        # (increment 9). Reported because a wrapper the audit could not open
        # contributes none, so "0 names" and "no wrappers" must not look alike.
        "wrapper_member_names_read": sum(
            len(tree.carried_names(rel)) for rel in tree.files
        ),
        # Wide-encoded (UTF-16/UTF-32) runs read out of those payloads
        # (increment 10). Reported for the same reason as the member names: a
        # payload whose wide runs were never examined must not be reported the
        # same way as one that carried none.
        "wide_encoded_runs_harvested": sum(tree.wide_runs(rel) for rel in tree.files),
        # A scan that could not finish must never look like one that passed.
        "payload_scans_truncated": tree.truncated_scans(),
        # The INDEX boundary (increment 11): entries present in the working
        # tree that this run did not audit because they are not in the git
        # index. Reported as a count AND as the paths themselves, and printed
        # even when zero — "none present" and "never looked" must not look
        # alike. `--include-untracked` audits them, which empties this list.
        "entries_present_but_not_in_the_index": tree.untracked_not_audited(),
        "untracked_entries_audited": (
            len(tree.untracked) if tree.include_untracked else 0
        ),
        # The STAGED-CONTENT boundary (increment 14): entries whose index blob is
        # not known to equal their working-tree bytes, and whose committable
        # bytes were therefore read as a SECOND view. Reported as the paths and
        # printed even when zero, for the same reason as the index boundary
        # above: "nothing diverges here" and "the committable bytes were never
        # read" must not look alike.
        "entries_whose_staged_content_differs_from_the_working_tree": list(
            tree.staged_views
        ),
        "staged_payloads_content_scanned": sum(
            1
            for rel in tree.staged_views
            if tree.scan_mode(rel, STAGED_VIEW) not in ("none", "unreadable")
        ),
        # The subset with no working-tree copy at all: their working-tree view
        # reaches no content rule, so the staged view is the only read there is.
        "staged_entries_absent_from_the_working_tree": tree.staged_only(),
        # The EVIDENCE boundary (increment 16): staged views that a BOOKKEEPING
        # check — a record citation, a provenance row's corroboration — read as
        # evidence, as opposed to the carriage rules reading them for signals.
        # Printed even when empty: until increment 16 this was always empty
        # while the divergence list above was not, and nothing said so.
        "staged_views_read_as_bookkeeping_evidence": (
            tree.staged_views_read_as_evidence()
        ),
        # The ANSWER-SET boundary (increment 15): bookkeeping files whose staged
        # bytes are not known to equal the working tree's, which means this tree
        # has two different answer sets and the committable one was judged on
        # its own. Printed even when empty, for the reason the two boundaries
        # above are: "the answers agree in both views" and "only the copy on
        # disk was ever consulted" must not look alike.
        "divergent_bookkeeping_files": divergent_bookkeeping,
        "committed_answer_set_findings": len(committed_findings),
        "entries_by_reference": {
            kind: sum(1 for rel in tree.files if tree.kind(rel) == kind)
            for kind in ("symlink", "gitlink")
        },
        # Gitlinks a declared exclusion covers but does not hide (increment 13).
        # Reported as the paths themselves, printed even when empty: a prefix
        # that happens to contain no submodule must not look like one whose
        # submodule was never examined.
        "by_reference_entries_inside_declared_exclusions": (
            tree.by_reference_inside_exclusions()
        ),
        "tripwire_hits": tripwire_counts,
    }
    findings.sort(key=lambda f: (f.rule, f.path))
    return findings, stats


def report(findings, stats, root, as_json=False):
    if as_json:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "verdict": "PASS" if not findings else "FAIL",
                    "coverage": stats,
                    "findings": [f.as_dict() for f in findings],
                    "caveat": CAVEAT,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    print(f"provenance audit of {root}")
    print(
        "coverage: "
        f"{stats['files_scanned']} files scanned, "
        f"{stats['files_excluded']} excluded by declared scope exclusions, "
        f"{stats['records']} decision records, "
        f"{stats['provenance_rows']} provenance rows covering "
        f"{stats['files_covered_by_rows']} files, "
        f"{stats['exemptions']} exemptions"
    )
    for prefix, count in stats["exclusions"].items():
        print(f"  excluded: {prefix} ({count} files)")
    reg = stats["gpl_boundary_register"]
    print(
        f"  gpl-boundary register: {reg['register_rows']} GPL-derived rows, "
        f"{reg['register_mit_rows']} MIT-sourced rows, "
        f"{reg['register_exceptions']} provenance exception(s), "
        f"{reg['register_exclusions']} reviewed exclusion(s); "
        f"provenance incomplete: {', '.join(reg['register_provenance_incomplete']) or 'none'}"
    )
    print(
        f"  not content-scanned (no text in the payload at all): "
        f"{stats['files_not_content_scanned']} files — extension tripwires only"
    )
    print(
        f"  unwrapped by magic (compressed stream / archive): "
        f"{stats['files_unwrapped_from_wrappers']} files — members content-scanned, "
        f"{stats['wrapper_member_names_read']} member name(s) read and judged"
    )
    print(
        f"  scanned as extracted strings only: "
        f"{stats['files_scanned_as_extracted_strings']} files — printable-ASCII "
        "runs, plus the wide-encoded ones; a notice in some other encoding "
        "inside one would still be missed"
    )
    print(
        f"  wide-encoded (UTF-16/UTF-32) runs harvested from payloads and "
        f"judged: {stats['wide_encoded_runs_harvested']} — counted over every "
        "payload read as strings, members of wrappers included"
    )
    unindexed = stats["entries_present_but_not_in_the_index"]
    if stats["untracked_entries_audited"]:
        print(
            f"  present in the working tree but not in the git index: "
            f"{stats['untracked_entries_audited']} entries — AUDITED "
            "(--include-untracked)"
        )
    else:
        print(
            f"  present in the working tree but NOT in the git index: "
            f"{len(unindexed)} entries — not audited by any rule; "
            "re-run with --include-untracked to audit them"
        )
        for rel in unindexed[:UNINDEXED_PATHS_LISTED]:
            print(f"      not audited (not in the index): {rel}")
        if len(unindexed) > UNINDEXED_PATHS_LISTED:
            print(
                f"      … and {len(unindexed) - UNINDEXED_PATHS_LISTED} more "
                "(full list in --json)"
            )
    divergent = stats["entries_whose_staged_content_differs_from_the_working_tree"]
    absent = stats["staged_entries_absent_from_the_working_tree"]
    print(
        f"  staged content not known to match the working tree: "
        f"{len(divergent)} entries — their index blobs (what a commit would "
        f"publish) were read as a second view, "
        f"{stats['staged_payloads_content_scanned']} of them content-scanned; "
        f"{len(absent)} have no working-tree copy at all"
    )
    for rel in divergent[:STAGED_PATHS_LISTED]:
        print(
            f"      also audited (staged blob): {rel}"
            + (" — not present in the working tree" if rel in absent else "")
        )
    if len(divergent) > STAGED_PATHS_LISTED:
        print(
            f"      … and {len(divergent) - STAGED_PATHS_LISTED} more "
            "(full list in --json)"
        )
    evidence = stats["staged_views_read_as_bookkeeping_evidence"]
    print(
        f"  staged views read as BOOKKEEPING evidence (a record citation, a "
        f"provenance row's corroboration): {len(evidence)} of {len(divergent)}"
        + (f" — {', '.join(evidence[:STAGED_PATHS_LISTED])}" if evidence else "")
    )
    bookkeeping = stats["divergent_bookkeeping_files"]
    print(
        f"  bookkeeping whose staged bytes are not known to match the working "
        f"tree: {len(bookkeeping)} file(s) — "
        + (
            "the ANSWER SET a commit would publish was judged on its own, "
            f"finding {stats['committed_answer_set_findings']} issue(s) present "
            "only there"
            if bookkeeping
            else "one answer set, published and on disk alike"
        )
    )
    for rel in bookkeeping:
        print(f"      answers re-read from the staged blob: {rel}")
    for rel in stats["payload_scans_truncated"]:
        print(
            f"  TRUNCATED payload scan (unwrap budget/depth reached, NOT fully "
            f"read): {rel}"
        )
    by_reference = stats["entries_by_reference"]
    print(
        f"  by reference (content is not in the entry's own bytes): "
        f"{by_reference['symlink']} symlink(s), "
        f"{by_reference['gitlink']} submodule/nested repo(s) — judged at the "
        "discovery layer"
    )
    inside = stats["by_reference_entries_inside_declared_exclusions"]
    print(
        f"      of those, inside a declared scope exclusion: {len(inside)} — "
        "an exclusion withholds content, not the existence of another repository"
    )
    for rel in inside:
        print(f"      by-reference entry inside a declared exclusion: {rel}")
    hits = ", ".join(f"{k}={v}" for k, v in sorted(stats["tripwire_hits"].items()))
    print(f"tripwire hits (declared + undeclared): {hits}")
    if findings:
        print(f"\nFAIL: {len(findings)} provenance finding(s):")
        for finding in findings:
            print(f"  [{finding.rule}] {finding.path}")
            print(f"      {finding.detail}")
    else:
        print("\nPASS: every carriage signal is answered by a provenance row or "
              "a declared exemption, and the decision-record bookkeeping is "
              "self-consistent.")
    print(CAVEAT)


# --- the history pass (increment 17) -----------------------------------------


HISTORY_CAVEAT = (
    "\nNOTE: this judges the commits in the range it was given, and only the "
    "carriage question (group 4) — a commit's own bookkeeping self-consistency "
    "is the current tree's obligation, not a historical commit's. Commits "
    "outside the range are NOT_RUN, not clean, and every limit in --limits "
    "still applies to each tree judged here. The rules applied are TODAY's: a "
    "commit that passed the audit as it existed then can be flagged here, so a "
    "finding is 'what the current rule set says about bytes this history "
    "published', never 'a violation of the rule in force at the time'."
)

# How a finding relates to the ANSWER SET at the range's final commit. The
# distinction is the whole reason this mode is not a duplicate of the tree
# audit: only the middle one is a shape no audit of the current tree can see,
# and only the last one is also live today.
TIP_ANSWERED = "answered at the range tip (declared in a later commit)"
TIP_ABSENT = "the path does not exist at the range tip (published, then removed)"
TIP_SIGNAL_GONE = "the offending bytes are gone at the range tip (the path remains)"
TIP_UNANSWERED = "still unanswered at the range tip (the tree audit fails too)"


def audit_history(root: Path, revrange):
    """Audit every commit in `revrange` as the tree it publishes.

    Returns (findings, stats). Each commit is judged on the carriage question
    alone — does every signal in the bytes this commit publishes have an answer
    in the bookkeeping THIS COMMIT publishes — because that is the question a
    tree audit of HEAD cannot answer for a blob that no longer exists at HEAD,
    and because judging a 2026-03 commit's README table against today's index
    conventions would bury the signal under bookkeeping churn.

    Findings are deduplicated per (rule, path, blob) and attributed to the
    EARLIEST commit in the range that published them, with the number of commits
    in range that carried the same bytes — a carrier that survived forty commits
    is one finding about one blob, not forty.
    """
    root = Path(root)
    commits = commit_log(root, revrange)
    signals = {}
    pairs = set()
    found = {}
    judged = 0
    unjudged = []
    dropped = []
    unreadable_index = []
    by_reference_signals = 0
    by_reference_entries = 0
    published = {}
    tip = None
    for sha, date, parents, subject in commits:
        entries = list_entries_at_commit(root, sha)
        blobs = {rel: oid for rel, kind, oid in entries if kind != "gitlink"}
        published[sha] = MANIFEST_REL in blobs
        raw = None
        if MANIFEST_REL in blobs:
            payload = read_index_blob(root, blobs[MANIFEST_REL])
            raw = None if payload is None else payload.decode("utf-8", "replace")
        if raw is None:
            # No manifest here. Whether that is "this tree predates the
            # bookkeeping" or "this commit removed the bookkeeping" is decided
            # from the PARENTS, not from a range-wide latch: in a merge-commit
            # history a branch forked before the manifest landed carries trees
            # that legitimately have none, and a date-ordered latch would judge
            # all of them against an empty answer set.
            inherited = any(
                commit_publishes_manifest(root, parent, published)
                for parent in parents
            )
            if not inherited:
                # Nothing to judge this commit's carriage against. Disclosed as a
                # commit this run did NOT judge — never folded into a PASS, and
                # never turned into a finding per carrier per commit, which would
                # bury the signal this mode exists to surface.
                unjudged.append(
                    {"commit": sha, "date": date, "subject": subject}
                )
                continue
            # A parent published an answer set and this commit does not: judged
            # with NO answers, so deleting the manifest buys a commit nothing.
            # This is the one way the "not judged" disclosure above could have
            # become an escape hatch.
            dropped.append({"commit": sha, "date": date, "subject": subject})
        manifest, _ = load_manifest(root, raw=raw)
        if manifest is None:
            manifest = {"entries": [], "exemptions": [], "scope_exclusions": []}
            if raw is not None:
                # Present but unparseable: a manifest that answers nothing,
                # judged as such and disclosed with the deletions.
                dropped.append({"commit": sha, "date": date, "subject": subject})
        tree = Tree(
            root,
            scope_exclusion_prefixes(manifest),
            entries=entries,
            default_view=HISTORY_VIEW,
            primary_view=HISTORY_VIEW,
            signal_cache=signals,
        )
        records, _ = parse_records(tree)
        try:
            rows, _ = parse_index(tree)
        except AuditError:
            # The record index is this commit's bookkeeping, not its carriage. A
            # commit whose README cannot be parsed is still judged on content;
            # the unknown row set is disclosed rather than treated as an answer.
            rows = {}
            unreadable_index.append({"commit": sha, "date": date})
        _, coverage, exemptions = check_manifest(tree, manifest, records, rows)
        tripwire_findings, counts = check_tripwires(tree, coverage, exemptions)
        judged += 1
        # Kept for the LAST judged commit only: how each finding relates to the
        # answer set at the tip is what separates "declared one commit later"
        # from "published and then removed" — and the second is the shape no
        # audit of the current tree can see at all.
        tip = {
            "commit": sha,
            "coverage": coverage,
            "exemptions": exemptions,
            "files": set(tree.files),
            "blobs": blobs,
        }
        for rel in tree.files:
            pairs.add((rel, blobs.get(rel, "")))
            if tree.kind(rel) != "file":
                by_reference_entries += 1
        by_reference_signals += counts["submodule-reference"] + counts["external-symlink-target"]
        for finding in tripwire_findings:
            key = (finding.rule, finding.path, blobs.get(finding.path, ""))
            record = found.get(key)
            if record is None:
                found[key] = {
                    "commit": sha,
                    "date": date,
                    "subject": subject,
                    "detail": finding.detail,
                    # A SET of commits, not a count of findings: one blob can
                    # carry several signals of the same rule (a GPL body, a
                    # foreign SPDX tag and a foreign copyright line are three
                    # `foreign-license-text` hits), and counting findings here
                    # would report a one-commit carrier as "present in 3
                    # commits".
                    "commits": {sha},
                }
            else:
                record["commits"].add(sha)
    findings = []
    standing = {TIP_ANSWERED: 0, TIP_ABSENT: 0, TIP_SIGNAL_GONE: 0, TIP_UNANSWERED: 0}
    for (rule, rel, _oid), record in sorted(found.items()):
        if tip is None:  # pragma: no cover - no commit was judged at all
            where = TIP_UNANSWERED
        elif rel not in tip["files"]:
            where = TIP_ABSENT
        elif rule in tip["coverage"].get(rel, ()) or (
            tip["exemptions"].get(rel, {}).get(rule) is not None
        ):
            where = TIP_ANSWERED
        elif rule not in {
            hit
            for hit, _evidence in signals.get(
                (rel, tip["blobs"].get(rel, ""), HISTORY_VIEW), ()
            )
        }:
            # The path is still there, has no answer, and needs none: the bytes
            # that signalled are not the bytes the tip publishes. Distinct from
            # the case below, which the ordinary tree audit would fail on too —
            # and distinct from TIP_ABSENT, where the whole path went away.
            where = TIP_SIGNAL_GONE
        else:
            where = TIP_UNANSWERED
        standing[where] += 1
        findings.append(
            Finding(
                rule,
                commit_label(rel, record["commit"]),
                f"first published by {record['commit'][:12]} ({record['date']}) "
                f"{record['subject']!r}, present in {len(record['commits'])} "
                f"commit(s) in range; {where} — {record['detail']}",
            )
        )
    by_rule = {rule: 0 for rule in TRIPWIRE_RULES}
    for hits in signals.values():
        for rule, _evidence in hits:
            by_rule[rule] += 1
    stats = {
        "range": str(revrange),
        "commits_in_range": len(commits),
        "commits_judged": judged,
        # NOT_RUN, printed even when empty: "no commit predates the manifest" and
        # "half the range was never looked at" must not look alike.
        "commits_not_judged_no_answer_set_yet": unjudged,
        "commits_that_published_no_manifest_after_one_existed": dropped,
        "commits_whose_record_index_could_not_be_parsed": unreadable_index,
        "distinct_path_blob_pairs_published": len(pairs),
        # Regular-file signal derivations, memoised per (path, blob): the number
        # of distinct blobs this run actually read, as opposed to the number of
        # (commit, path) slots they occupy.
        "distinct_pairs_examined_for_signals": len(signals),
        "distinct_carriage_signals": sum(len(v) for v in signals.values()),
        "distinct_carriage_signals_by_rule": by_rule,
        "unanswered_signals": len(found),
        "range_tip_commit": None if tip is None else tip["commit"],
        "findings_by_standing_at_the_range_tip": standing,
        # By-reference entries are re-judged per commit (their evidence comes
        # from the tree around them, not from bytes of their own), so these are
        # per-commit totals rather than distinct counts, and say so.
        "by_reference_entry_slots_judged": by_reference_entries,
        "by_reference_signals_per_commit_total": by_reference_signals,
    }
    return findings, stats


def report_history(findings, stats, root, as_json=False):
    if as_json:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "mode": "history",
                    "verdict": "PASS" if not findings else "FAIL",
                    "coverage": stats,
                    "findings": [f.as_dict() for f in findings],
                    "caveat": CAVEAT + HISTORY_CAVEAT,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    unjudged = stats["commits_not_judged_no_answer_set_yet"]
    dropped = stats["commits_that_published_no_manifest_after_one_existed"]
    unreadable = stats["commits_whose_record_index_could_not_be_parsed"]
    print(f"provenance history audit of {root}")
    print(f"  range: {stats['range']}")
    print(
        f"coverage: {stats['commits_in_range']} commits in range, "
        f"{stats['commits_judged']} judged, {len(unjudged)} NOT judged"
    )
    print(
        f"  not judged (no provenance manifest had been published yet in this "
        f"range — NOT_RUN, not a pass): {len(unjudged)} commit(s)"
    )
    for item in unjudged[:HISTORY_COMMITS_LISTED]:
        print(f"      not judged: {item['commit'][:12]} ({item['date']}) {item['subject']}")
    if len(unjudged) > HISTORY_COMMITS_LISTED:
        print(
            f"      … and {len(unjudged) - HISTORY_COMMITS_LISTED} more "
            "(full list in --json)"
        )
    print(
        f"  published no manifest after one had existed (judged with NO "
        f"answers): {len(dropped)} commit(s)"
    )
    for item in dropped[:HISTORY_COMMITS_LISTED]:
        print(f"      judged with no answer set: {item['commit'][:12]} ({item['date']})")
    print(
        f"  decision-record index unparseable (row set unknown, carriage still "
        f"judged): {len(unreadable)} commit(s)"
    )
    print(
        f"  distinct (path, blob) pairs published by the judged commits: "
        f"{stats['distinct_path_blob_pairs_published']}, of which "
        f"{stats['distinct_pairs_examined_for_signals']} were read for content "
        "signals (each blob once, however many commits carry it)"
    )
    hits = ", ".join(
        f"{k}={v}" for k, v in sorted(stats["distinct_carriage_signals_by_rule"].items())
    )
    print(
        f"  distinct carriage signals in those pairs: "
        f"{stats['distinct_carriage_signals']} — {hits}"
    )
    print(
        f"  by-reference entries judged (per-commit slots): "
        f"{stats['by_reference_entry_slots_judged']}, signalling "
        f"{stats['by_reference_signals_per_commit_total']} time(s)"
    )
    standing = stats["findings_by_standing_at_the_range_tip"]
    print(
        "  findings by standing at the range tip "
        f"({(stats['range_tip_commit'] or 'none')[:12]}): "
        + ", ".join(f"{k} = {v}" for k, v in sorted(standing.items()))
    )
    if findings:
        print(f"\nFAIL: {len(findings)} provenance finding(s) in published history:")
        for finding in findings:
            print(f"  [{finding.rule}] {finding.path}")
            print(f"      {finding.detail}")
    else:
        print(
            f"\nPASS: every carriage signal in the {stats['commits_judged']} "
            "judged commit(s) is answered by the provenance bookkeeping that "
            "same commit publishes."
        )
    print(CAVEAT + HISTORY_CAVEAT)
