#!/usr/bin/env python3
"""SXT-019 provenance audit — the provenance manifest check.

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule
or message was changed, reordered or reflowed). This module loads
`decision-records/provenance.json` and judges every row, exemption and scope
exclusion in it, including whether the named file itself corroborates the row
in every byte view that file has.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from check_provenance_records import (
    glob_to_regex,
    pattern_problem,
)
from check_provenance_rules import (
    BY_REFERENCE_CLASS,
    EXEMPTIBLE_RULES,
    KNOWN_CLASSES,
    MANIFEST_REL,
    SCHEMA_VERSION,
    TRIPWIRE_RULES,
)
from check_provenance_signals import (
    Finding,
    occurrence_regex,
    quotation_marker_matches,
)
from check_provenance_tree import (
    Tree,
    _staged_evidence,
    entry_views,
)
from check_provenance_tripwires import (
    _structural_tripwire_rules,
    symlink_escape,
)


# --- manifest -----------------------------------------------------------------


REQUIRED_ENTRY_FIELDS = (
    "class",
    "content",
    "upstream",
    "upstream_license",
    "decision_record",
)


FROM_DISK = object()
"""Sentinel: `load_manifest` should open the working-tree copy itself.

Deliberately NOT `None`. A view can legitimately yield `None` — a manifest
`git rm --cached` left on disk, or a staged blob the encoding sniff refuses —
and if that were spelled the same as "no text supplied", the committable pass
would fall back to the copy on disk and answer from the very bytes this
increment exists to stop answering from.
"""


def load_manifest(root: Path, raw=FROM_DISK, label=MANIFEST_REL):
    """Parse the provenance manifest from `root`, or from `raw` text if given.

    `raw` is how the COMMITTABLE manifest is parsed (increment 15): the index
    blob's text, read through the tree's own cache. `label` is the path every
    finding quotes, so a finding about the staged manifest names the staged
    manifest rather than looking like one about the file on disk.
    """
    if raw is FROM_DISK:
        path = root / MANIFEST_REL
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            return None, [Finding("manifest-missing", label, f"cannot read: {exc}")]
    if raw is None:
        return None, [
            Finding(
                "manifest-missing",
                label,
                "this view holds no readable manifest — a commit would publish "
                "none, so it answers nothing",
            )
        ]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [Finding("manifest-missing", label, f"invalid JSON: {exc}")]
    if not isinstance(data, dict):
        return None, [Finding("manifest-schema", label, "top level must be an object")]
    findings = []
    if data.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "manifest-schema",
                label,
                f"schema_version {data.get('schema_version')!r} != {SCHEMA_VERSION}",
            )
        )
    for key in ("entries", "exemptions", "scope_exclusions"):
        value = data.get(key, [])
        if not isinstance(value, list):
            findings.append(Finding("manifest-schema", label, f"{key!r} must be a list"))
            data[key] = []
    return data, findings


def scope_exclusion_prefixes(manifest):
    prefixes = []
    for item in (manifest or {}).get("scope_exclusions", []) or []:
        if isinstance(item, dict) and item.get("prefix"):
            prefixes.append(str(item["prefix"]))
    return prefixes


def _matcher(entry):
    """(kind, matcher) for an entry/exemption: exact path or extension glob."""
    if entry.get("path"):
        target = str(entry["path"])
        return "path", target, lambda rel: rel == target
    pattern = str(entry.get("pattern", ""))
    regex = glob_to_regex(pattern)
    return "pattern", pattern, lambda rel: bool(regex.match(rel))


def check_manifest(tree: Tree, manifest, records, rows, manifest_rel=MANIFEST_REL):
    """Validate rows/exemptions and return (findings, coverage).

    `manifest_rel` is the manifest path every finding here quotes. The committable
    pass (increment 15) passes the staged manifest's label, so a row that is
    wrong only in the bytes a commit would publish does not read as a finding
    about the file on disk — which is clean, and is what the author is
    looking at.
    """
    findings = []
    # rel -> set of tripwire rule ids this file's row(s) cover. Scoped per
    # rule, not blanket per-file: a row naming a file only suppresses the
    # rule(s) implied by that file's own extension plus whatever the row's
    # 'covers' field explicitly declares — never every rule the file happens
    # to trip (see PR #114 review, finding 1: an unrelated row was silently
    # laundering an appended, unmodified GPL license block past the
    # non-exemptible foreign-license-text tripwire).
    coverage = {}
    exemptions = {}  # rel -> {rule -> reason}

    for index, entry in enumerate(manifest.get("entries", []) or []):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            findings.append(Finding("manifest-schema", manifest_rel, f"{label} must be an object"))
            continue
        if bool(entry.get("path")) == bool(entry.get("pattern")):
            findings.append(
                Finding(
                    "manifest-field-missing",
                    manifest_rel,
                    f"{label}: exactly one of 'path' or 'pattern' is required",
                )
            )
            continue
        missing = [f for f in REQUIRED_ENTRY_FIELDS if not entry.get(f)]
        if missing:
            findings.append(
                Finding(
                    "manifest-field-missing",
                    manifest_rel,
                    f"{label} ({entry.get('path') or entry.get('pattern')}): "
                    f"missing required field(s) {missing}",
                )
            )
        if entry.get("class") and entry["class"] not in KNOWN_CLASSES:
            findings.append(
                Finding(
                    "manifest-unknown-class",
                    manifest_rel,
                    f"{label}: class {entry['class']!r} not in "
                    f"{sorted(KNOWN_CLASSES)}",
                )
            )
        kind, target, matches = _matcher(entry)
        if kind == "pattern":
            problem = pattern_problem(target)
            if problem:
                findings.append(
                    Finding("manifest-bad-pattern", manifest_rel, f"{label}: {problem}")
                )
                continue
        hits = [rel for rel in tree.files if matches(rel)]
        if not hits:
            findings.append(
                Finding(
                    "manifest-stale-path",
                    manifest_rel,
                    f"{label}: {target!r} matches no in-scope file (stale row — "
                    "remove it or fix the path)",
                )
            )
        number = str(entry.get("decision_record") or "").strip()
        if number:
            if number not in records:
                findings.append(
                    Finding(
                        "manifest-missing-record",
                        manifest_rel,
                        f"{label}: decision_record {number!r} does not exist",
                    )
                )
            elif number not in rows:
                findings.append(
                    Finding(
                        "manifest-unindexed-record",
                        manifest_rel,
                        f"{label}: decision_record {number!r} is not in the index",
                    )
                )
        covers_raw = entry.get("covers")
        covers_declared = set()
        if covers_raw is not None:
            if not isinstance(covers_raw, list):
                findings.append(
                    Finding("manifest-schema", manifest_rel, f"{label}: 'covers' must be a list")
                )
            else:
                bad = [r for r in covers_raw if r not in TRIPWIRE_RULES]
                if bad:
                    findings.append(
                        Finding(
                            "manifest-schema",
                            manifest_rel,
                            f"{label}: 'covers' rule(s) {bad} not in {sorted(TRIPWIRE_RULES)}",
                        )
                    )
                covers_declared = {r for r in covers_raw if r in TRIPWIRE_RULES}
        for rel in hits:
            coverage.setdefault(rel, set()).update(
                _structural_tripwire_rules(tree, rel, entry) | covers_declared
            )
            findings.extend(_corroborate(tree, rel, entry, number, label))

    for index, item in enumerate(manifest.get("exemptions", []) or []):
        label = f"exemptions[{index}]"
        if not isinstance(item, dict):
            findings.append(Finding("manifest-schema", manifest_rel, f"{label} must be an object"))
            continue
        if bool(item.get("path")) == bool(item.get("pattern")):
            findings.append(
                Finding(
                    "exemption-field-missing",
                    manifest_rel,
                    f"{label}: exactly one of 'path' or 'pattern' is required",
                )
            )
            continue
        rules = item.get("rules")
        reason = str(item.get("reason") or "").strip()
        if not isinstance(rules, list) or not rules or not reason:
            findings.append(
                Finding(
                    "exemption-field-missing",
                    manifest_rel,
                    f"{label}: non-empty 'rules' list and 'reason' are required",
                )
            )
            rules = rules if isinstance(rules, list) else []
        bad = [r for r in rules if r not in EXEMPTIBLE_RULES]
        if bad:
            findings.append(
                Finding(
                    "exemption-non-exemptible-rule",
                    manifest_rel,
                    f"{label}: rule(s) {bad} cannot be exempted (only "
                    f"{sorted(EXEMPTIBLE_RULES)} may be); answer them with a "
                    "provenance row instead",
                )
            )
        # Optional 'occurrences': the exemption then covers only the named
        # quotation-marker occurrences in ONE exact file, never the whole
        # file — any other marker in that file (a real foreign quotation added
        # later, even with the same wording) still fails. Required to be an
        # exact path: an occurrence list on a glob would be a blanket.
        occurrences = item.get("occurrences")
        if occurrences is not None:
            if (
                not isinstance(occurrences, list)
                or not occurrences
                or not all(isinstance(o, str) and o.strip() for o in occurrences)
            ):
                findings.append(
                    Finding(
                        "exemption-field-missing",
                        manifest_rel,
                        f"{label}: 'occurrences' must be a non-empty list of "
                        "non-empty strings",
                    )
                )
                continue
            if not item.get("path"):
                findings.append(
                    Finding(
                        "exemption-bad-pattern",
                        manifest_rel,
                        f"{label}: 'occurrences' requires an exact 'path', not a pattern",
                    )
                )
                continue
        kind, target, matches = _matcher(item)
        if kind == "pattern":
            problem = pattern_problem(target)
            if problem:
                findings.append(
                    Finding("exemption-bad-pattern", manifest_rel, f"{label}: {problem}")
                )
                continue
        hits = [rel for rel in tree.files if matches(rel)]
        if not hits:
            findings.append(
                Finding(
                    "exemption-stale",
                    manifest_rel,
                    f"{label}: {target!r} matches no in-scope file (stale "
                    "exemption — remove it)",
                )
            )
        for rel in hits:
            spans = None
            if occurrences is not None:
                spans = []
                text = tree.text(rel) or ""
                markers = quotation_marker_matches(text)
                for occurrence in occurrences:
                    located = [
                        (m.start(), m.end())
                        for m in occurrence_regex(occurrence).finditer(text)
                    ]
                    # A named occurrence must identify ONE place in the file.
                    # Matching the literal wording everywhere it appears would
                    # exempt a genuinely foreign quotation that happens to be
                    # worded as the exact same sentence with a different
                    # referent ("The Surge oscillator: `tb.sv` carries a
                    # verbatim copy of it."), which is indistinguishable from
                    # the legitimate self-copy by wording alone. Ambiguity is
                    # therefore a finding, not a silent widening: name the
                    # occurrence with enough surrounding text to be unique.
                    if len(located) > 1:
                        findings.append(
                            Finding(
                                "exemption-ambiguous",
                                MANIFEST_REL,
                                f"{label}: occurrence {occurrence!r} appears "
                                f"{len(located)} times in {rel}; an exemption "
                                "must name exactly one place (extend the quoted "
                                "text until it is unique)",
                            )
                        )
                        continue
                    live = [
                        (start, end)
                        for start, end in located
                        if any(start <= mk.start() and mk.end() <= end for _, mk in markers)
                    ]
                    if not live:
                        findings.append(
                            Finding(
                                "exemption-stale",
                                manifest_rel,
                                f"{label}: occurrence {occurrence!r} "
                                + (
                                    "contains no quotation marker"
                                    if located
                                    else "no longer appears"
                                )
                                + f" in {rel} (stale exemption — fix or remove it)",
                            )
                        )
                    spans.extend(live)
            for rule in rules:
                if rule in EXEMPTIBLE_RULES:
                    current = exemptions.setdefault(rel, {}).get(rule)
                    if current is not None and current["spans"] is None:
                        continue  # an unscoped exemption already covers the file
                    if spans is None or current is None:
                        # The occurrence LITERALS travel with the resolved spans:
                        # a second byte view of the same file needs its own
                        # offsets, and only the literals can produce them
                        # (increment 14).
                        exemptions[rel][rule] = {
                            "reason": reason,
                            "spans": spans,
                            "occurrences": None if occurrences is None else list(occurrences),
                        }
                    else:
                        current["spans"].extend(spans)
                        current["occurrences"] = (current.get("occurrences") or []) + list(
                            occurrences or []
                        )

    for index, item in enumerate(manifest.get("scope_exclusions", []) or []):
        label = f"scope_exclusions[{index}]"
        if not isinstance(item, dict) or not item.get("prefix") or not item.get("reason"):
            findings.append(
                Finding(
                    "manifest-schema",
                    manifest_rel,
                    f"{label}: 'prefix' and 'reason' are required",
                )
            )
            continue
        prefix = str(item["prefix"])
        # A prefix whose only member is a gitlink is NOT stale: it still
        # declares the hole, even though the gitlink itself is judged at the
        # discovery layer rather than excluded (increment 13).
        if not tree.excluded.get(prefix) and not tree.excluded_by_reference.get(prefix):
            findings.append(
                Finding(
                    "scope-exclusion-stale",
                    manifest_rel,
                    f"{label}: prefix {item['prefix']!r} excludes nothing "
                    "(stale — remove it)",
                )
            )

    floor = manifest.get("scan_floor")
    if isinstance(floor, int) and len(tree.files) < floor:
        findings.append(
            Finding(
                "scan-underflow",
                manifest_rel,
                f"scanned {len(tree.files)} in-scope files, below the declared "
                f"scan_floor of {floor} — the audit may have walked the wrong "
                "tree; a partial scan is not a pass",
            )
        )
    return findings, coverage, exemptions


def _pinned_commit_required(tree: Tree, rel, entry):
    """Why this row MUST carry a `pinned_commit`, or None (increment 13).

    The field is optional in general, and rightly so: a row describing quoted
    constants is corroborated by the file's own bytes, which the audit reads.
    It is not optional for a row describing content the audit never reads. A
    gitlink's entire content is "whatever that commit is", and
    `class: external-reference` says the same of a link into an external tree —
    the pin IS the description, so a row without one describes nothing
    checkable.

    Before this increment the field's absence also SHORT-CIRCUITED the gitlink
    arm's own comparison below (`actual and commit and …`), so the control that
    catches a row naming the WRONG commit was defeated by deleting the field
    rather than changing its value: a gitlink pinning the GPL engine, answered
    by a row with no pin at all, audited clean with no pin recorded anywhere
    (control `discovery/submodule-row-with-no-pinned-commit`).
    """
    if tree.kind(rel) == "gitlink":
        return f"{rel} is a committed gitlink, whose content is its commit"
    if str(entry.get("class") or "") == BY_REFERENCE_CLASS:
        return f"the row's class is {BY_REFERENCE_CLASS!r}"
    return None


def _corroborate(tree: Tree, rel, entry, number, label):
    """The file must show the provenance its row claims (row != reality guard).

    Checked against EVERY byte view the entry has (increment 16). The row is a
    claim this repository PUBLISHES, so the bytes a commit publishes have to
    carry the provenance it claims; and the working-tree copy has to as well,
    because an unstaged edit that strips the citation while the row stands is a
    real defect the author must see before `git add`. Until increment 16 only
    one view was read, so `git add`-ing a carrier with its citation removed and
    leaving the citing copy on disk audited PASS — and so did staging that
    carrier and deleting the working copy outright, where the only bytes a
    commit publishes were read by no bookkeeping check at all.
    """
    commit = str(entry.get("pinned_commit") or "").strip()
    kind = tree.kind(rel)
    if not commit:
        why = _pinned_commit_required(tree, rel, entry)
        if why is not None:
            return [
                Finding(
                    "manifest-field-missing",
                    MANIFEST_REL,
                    f"{label} ({rel}): missing required field "
                    f"['pinned_commit'] — {why}, so the row records nothing "
                    "this audit (or a reviewer) can check it against",
                )
            ]
    if kind == "gitlink":
        # A gitlink carries its own pin, so corroboration is exact here: the
        # commit in the index is what a build checks out, whatever the row says.
        # `commit` is non-empty by the guard above; `actual` can still be empty
        # for a nested repository in a non-git tree, which records no mode.
        actual = tree.gitlink_commits.get(rel)
        if actual and actual.lower() != commit.lower():
            return [
                Finding(
                    "manifest-uncorroborated",
                    rel,
                    f"{label}: the committed submodule points at {actual[:12]}, "
                    f"not the row's pinned_commit {commit[:12]} — the row "
                    "describes a tree this repository does not reference",
                )
            ]
        return []
    if kind == "symlink":
        escape = symlink_escape(tree, rel)
        if escape is not None:
            # The target is outside what this audit reads — an external tree, an
            # absolute path, a declared hole — WHETHER OR NOT it happens to be
            # checked out on the machine running the audit. There is no file
            # body in this tree in which to state provenance, so the row and its
            # record are the only description, as for a binary payload; the
            # structural tripwire is what makes the row mandatory in the first
            # place.
            #
            # Keyed on the escape, not on readability, because the previous
            # reading of the same reasoning ("the target is not readable here")
            # made the verdict depend on the auditing machine: one identical
            # committed tree audited PASS in CI, where the pinned oracle is not
            # checked out, and FAIL on a developer box that had it, where the
            # resolved UPSTREAM bytes were then required to cite one of this
            # repository's decision records. Requiring that is not a tooling
            # change — it would mean editing upstream bytes, which is #25's
            # question, not this tool's. DECLARED LIMIT, not a closed hole: for
            # an escaping link the row is corroborated by nothing but itself
            # (control
            # `discovery/declared-escaping-symlink-passes-whether-its-target-resolves-or-not`).
            return []
        # An in-tree target: the link resolves to content this audit scans at
        # its own path, so the row is still checked against what a reviewer
        # reads. The link target is what they read first; search it alongside.
        suffix = ""
        try:
            suffix = "\n" + os.readlink(tree.root / rel)
        except OSError:  # pragma: no cover - raced away
            pass
    else:
        suffix = ""
    tokens = []
    if number:
        tokens.append(f"decision-records/{number}")
        tokens.append(f"DR-{number}")
        tokens.append(f"DR{number}")
    if len(commit) >= 8:
        tokens.append(commit[:8])
    if not tokens:
        return []
    findings = []
    for view in entry_views(tree, rel):
        text = tree.text(rel, view)
        if text is None:
            # Binary payload (or, for the working-tree view of an entry staged
            # and then deleted, no file at all): nothing to read in THIS view,
            # so the row is the record here exactly as it always was. Declared
            # per view rather than per entry — which is what let the staged-only
            # shape past: its working-tree view yields None, and that answered
            # for the staged bytes too.
            continue
        tree.note_bookkeeping_read(rel, view)
        if any(token.lower() in (text + suffix).lower() for token in tokens):
            continue
        findings.append(
            Finding(
                "manifest-uncorroborated",
                rel,
                _staged_evidence(
                    view,
                    f"{label}: the file cites neither decision record "
                    f"{number or '????'} nor the pinned commit "
                    f"{commit[:12] or '(none given)'} — state the provenance in "
                    "the file, or fix the row",
                ),
            )
        )
    return findings
