#!/usr/bin/env python3
"""SXT-019 provenance audit — the undeclared-carrier tripwires.

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule
or message was changed, reordered or reflowed). This module holds the content
and structural signals that a file carries third-party material, and the pass
that reads every byte view of every entry for them.
"""

from __future__ import annotations

import os
import re

from check_provenance_payload import (
    MEMBER_JOIN,
)
from check_provenance_rules import (
    BY_REFERENCE_CLASS,
    EXEMPTIBLE_RULES,
    MANIFEST_REL,
    RULES,
    TRIPWIRE_RULES,
)
from check_provenance_signals import (
    COPYRIGHT_PREFILTERS,
    FOREIGN_LICENSE_BODY_RES,
    FOREIGN_SOURCE_EXTS,
    Finding,
    OWN_LICENSE_PATHS,
    QUOTATION_MARKER_RES,
    SPDX_RE,
    UPSTREAM_ASSET_EXTS,
    UPSTREAM_CITATION_PREFILTERS,
    foreign_copyright_match,
    occurrence_regex,
    quotation_marker_matches,
    spdx_foreign_ids,
)
from check_provenance_tree import (
    Tree,
    WORKTREE_VIEW,
    entry_views,
    read_index_blob,
    view_evidence_prefix,
)


# --- tripwires ----------------------------------------------------------------


def _extension_suffix(rel):
    """The extension used for tripwire matching, `.gz` compression stripped.

    Without this, renaming any upstream asset or foreign-source file with a
    trailing `.gz` (`Bank Sine.wt.gz`, `copied_filter.cpp.gz`) drops it from
    both extension tripwires with no actual compression required — see PR
    #114 review, finding 3. The repository's own gzipped evidence traces
    (`*.json.gz`, `*.hex.gz`) fall through to an extension that is in neither
    set, so this does not newly flag them.
    """
    name = rel.rsplit("/", 1)[-1]
    if name.lower().endswith(".gz"):
        name = name[: -len(".gz")]
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def member_name_signals(label):
    """[(component, suffix, what it is)] for one wrapper member's name label.

    EVERY `!`-joined component is judged, not just the last: a zip member named
    `Bank Sine.wt` that is itself a gzip would otherwise be labelled
    `Bank Sine.wt!inner.json` and read as a `.json`, which is the same
    "stop at the first answer" masking shape increments 2-5 closed on the
    license rule. The two extension sets are the ones that judge a file's own
    name, so a member name is held to exactly the standard its own path would
    be held to if it were committed unwrapped.
    """
    out = []
    for component in label.split(MEMBER_JOIN):
        suffix = _extension_suffix(component)
        if suffix in UPSTREAM_ASSET_EXTS:
            out.append((component, suffix, "upstream asset / opaque bundle"))
        elif suffix in FOREIGN_SOURCE_EXTS:
            out.append((component, suffix, "foreign-language source"))
    return out


def symlink_escape(tree: Tree, rel):
    """Why this symlink's target is not plain in-tree content, or None.

    A symlink that stays inside the tree and lands on in-scope content is not a
    carriage signal: whatever it points at is audited at its own path. What IS a
    signal is a link whose target the audit cannot see — absolute, escaping via
    `..`, unresolvable here, or inside a declared scope exclusion. In every one
    of those cases the bytes that reach a build are not the bytes this audit
    read, so only a provenance row can describe them.
    """
    link = tree.root / rel
    if tree.history:
        # A commit's symlink IS a blob whose content is the target path; the
        # working-tree copy at this path belongs to whatever is checked out now,
        # which is a different tree (increment 17).
        raw = read_index_blob(tree.root, tree.index_blobs.get(rel, ""))
        if raw is None:
            return "symlink target unreadable: the commit's blob could not be read"
        target = raw.decode("utf-8", "replace").strip()
        if not target:
            return "symlink with an empty target"
    else:
        try:
            target = os.readlink(link)
        except OSError:
            # The index says mode 120000 but the filesystem has no symlink here: a
            # `core.symlinks=false` checkout materialises the entry as a regular
            # file whose CONTENT is the target path. Read it that way rather than
            # inventing a finding on a rule that cannot be exempted.
            try:
                target = link.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as exc:  # pragma: no cover - raced away
                return f"symlink target unreadable: {exc}"
            if not target:
                return "symlink with an empty target"
    if os.path.isabs(target):
        return f"absolute target outside the audited tree: {target!r}"
    logical = os.path.normpath(os.path.join(os.path.dirname(rel), target))
    if logical == ".." or logical.startswith(".." + os.sep) or logical.startswith("../"):
        return f"target escapes the audited tree: {target!r} -> {logical!r}"
    if tree.history:
        # Resolution against the COMMIT's own entry set, not the filesystem: the
        # question is whether the tree that commit publishes contains the target,
        # and a `resolve()` here would answer it from whatever is checked out now.
        inside = logical.replace(os.sep, "/")
        if inside not in tree.all_files and not any(
            other.startswith(inside + "/") for other in tree.all_files
        ):
            return f"target does not resolve in this commit's tree: {target!r}"
        excluded = tree.excluded_by(inside)
        if excluded is not None:
            return (
                f"target {inside!r} is under the declared scope exclusion "
                f"{excluded!r}, which this audit does not scan"
            )
        return None
    try:
        resolved = link.resolve(strict=True)
        root = tree.root.resolve()
    except (OSError, RuntimeError, ValueError):
        # Absent at audit time. This is the CI shape for a link into the
        # pinned oracle: the external working directory is not checked out, so
        # the content is invisible here but present wherever the link resolves.
        return f"target does not resolve in this tree: {target!r}"
    try:
        inside = resolved.relative_to(root).as_posix()
    except ValueError:
        return f"target resolves outside the audited tree: {str(resolved)!r}"
    excluded = tree.excluded_by(inside)
    if excluded is not None:
        return (
            f"target {inside!r} is under the declared scope exclusion "
            f"{excluded!r}, which this audit does not scan"
        )
    return None


def submodule_evidence(tree: Tree, rel):
    """Finding evidence for a committed gitlink / nested repository."""
    commit = tree.gitlink_commits.get(rel)
    url = tree.submodule_urls.get(rel)
    detail = "committed submodule / nested repository"
    if commit:
        detail += f" pinned at {commit[:12]}"
    if url:
        detail += f", url {url}"
    detail += " — its files are in the build tree but not in this audit"
    excluded = tree.excluded_by(rel)
    if excluded is not None:
        # The locator a reviewer needs: the entry is inside a declared hole, so
        # it looks exempted and is not. An exclusion withholds content from the
        # content rules; it cannot withhold the existence of another repository.
        detail += (
            f"; it sits under the declared scope exclusion {excluded!r}, which "
            "withholds content from the content rules but does not hide a "
            "by-reference entry"
        )
    return detail


def _extension_tripwire_rules(rel):
    """Tripwire rule ids implied purely by `rel`'s own (de-gzipped) extension.

    These are structural properties of the whole file — every byte of a `.wt`
    file is upstream-asset content by virtue of being a `.wt` file — so a
    provenance row naming this exact file safely covers them in full. This is
    unlike the content-signal tripwires (`foreign-license-text`,
    `self-declared-quotation`), which can appear anywhere in a file's text
    independent of what the row's 'content' field describes, and therefore
    require an explicit 'covers' declaration instead of blanket coverage
    (see PR #114 review, finding 1).
    """
    suffix = _extension_suffix(rel)
    rules = set()
    if suffix in UPSTREAM_ASSET_EXTS:
        rules.add("upstream-asset-extension")
    if suffix in FOREIGN_SOURCE_EXTS:
        rules.add("foreign-source-language")
    return rules


def _structural_tripwire_rules(tree: Tree, rel, entry):
    """Tripwire rules implied by the ENTRY itself, not by any text it holds.

    Extension rules plus the by-reference kinds. Like an extension rule, the
    kind is a property of the whole entry — a gitlink *is* a reference to
    another tree, a symlink *is* its target — so a row naming this exact path
    describes it in full and covers the rule without a 'covers' declaration.
    The content-signal rules still require 'covers', because text can appear
    anywhere in a file regardless of what the row's 'content' field says.

    The two by-reference rules additionally require the row to be of the class
    that describes a by-reference entry (increment 13). Before that, ANY row at
    the exact path covered them: a row whose class said
    "restates an upstream attribution, carries no upstream content" answered a
    committed GPL engine checkout, with the row and its record — the only
    description a by-reference entry has — describing something else entirely.
    A row of the wrong class is not a laundering trick to catch, it is a row
    that does not say what the rule needs said; `external-reference` was
    already named as the required class both in `KNOWN_CLASSES` and in the
    manifest's own notes, so what moved was the enforcement, not the contract
    (control `discovery/gitlink-answered-by-a-row-of-the-wrong-class`).
    """
    rules = _extension_tripwire_rules(rel)
    kind = tree.kind(rel)
    by_reference = {
        "gitlink": "submodule-reference",
        "symlink": "external-symlink-target",
    }
    row_class = str((entry or {}).get("class") or "")
    if kind in by_reference and row_class == BY_REFERENCE_CLASS:
        rules.add(by_reference[kind])
    return rules


def tripwire_hits(tree: Tree, rel, view=WORKTREE_VIEW):
    """`_tripwire_hits`, memoised per (path, blob) when a cache is in use.

    The history pass (increment 17) audits one tree per commit, and a blob that
    survives two hundred commits would otherwise be scanned two hundred times.
    Signals are a function of a REGULAR file's path and bytes, so (path, blob) is
    a sound key for those; a by-reference entry is deliberately not cached, since
    its evidence is read from the tree around it (`.gitmodules`, the declared
    exclusions, where the link resolves) and not from bytes of its own. The
    ANSWERS are never cached — they are precisely what differs between commits.
    """
    cache = tree.signal_cache
    if cache is None or tree.kind(rel) != "file":
        return _tripwire_hits(tree, rel, view)
    key = (rel, tree.index_blobs.get(rel, ""), view)
    if key not in cache:
        cache[key] = _tripwire_hits(tree, rel, view)
    return cache[key]


def _tripwire_hits(tree: Tree, rel, view=WORKTREE_VIEW):
    """[(rule, evidence)] for content signals of third-party carriage.

    Each signal is gated behind a cheap lowercase substring prefilter; the
    regexes below only run on files that could match. The prefilter tokens
    must stay a SUPERSET of what each regex can match, or the rule silently
    stops firing — `--negative-control` is what catches that mistake.

    `view` selects which bytes of `rel` are judged (increment 14). The
    structural signals — the by-reference kinds and the extension sets — are
    properties of the ENTRY and of its path, identical in both views, so they
    are evaluated once, on the tree's PRIMARY view; a secondary (staged) view
    runs the content signals and the wrapper-member-name signal, which are the
    ones that read bytes.

    "Primary" rather than "the working tree" because of increment 17: a commit
    tree's only view is the commit's own blobs, and gating the structural signals
    on `view == WORKTREE_VIEW` would have made every extension rule and both
    by-reference rules silently unreachable there — a whole rule group answering
    "nothing offended" for a view it never examined.
    """
    hits = []
    # The discovery layer first: an entry that carries its content by reference
    # has no bytes of its own for any signal below to read.
    kind = tree.kind(rel)
    primary = view == tree.primary_view
    if not primary:
        if kind == "gitlink":
            # A gitlink's object is a commit in another repository, not a blob
            # here: there is no staged payload to read. Its carriage is judged
            # at the discovery layer on the working-tree pass.
            return hits
    elif kind == "gitlink":
        # Nothing further applies: a gitlink has no extension and no text.
        return [("submodule-reference", submodule_evidence(tree, rel))]
    elif kind == "symlink":
        escape = symlink_escape(tree, rel)
        if escape is not None:
            hits.append(("external-symlink-target", escape))
        # Deliberately NOT a return: `text()` follows the link, so a target
        # that does resolve is still read by every content rule below.
    if primary:
        suffix = _extension_suffix(rel)
        if suffix in UPSTREAM_ASSET_EXTS:
            hits.append(("upstream-asset-extension", f"extension {suffix}"))
        if suffix in FOREIGN_SOURCE_EXTS:
            hits.append(("foreign-source-language", f"extension {suffix}"))
    # The names a wrapper carries INSIDE it, before the content rules: a member
    # that carries no marker at all (a `.wt` payload, a stripped `.cpp`) reaches
    # none of them, and `text()` is None for a wrapper whose members are all
    # opaque — so judging names after the `text is None` return would have left
    # the whole class unanswered. `carried_names` forces that read itself.
    offenders = [
        (label, signal)
        for label in tree.carried_names(rel, view)
        for signal in member_name_signals(label)
    ]
    if offenders:
        label, (component, member_suffix, what) = offenders[0]
        evidence = (
            f"wrapper member {component!r} ({what}, extension {member_suffix})"
        )
        if label != component:
            evidence += f", carried at {label!r}"
        if len(offenders) > 1:
            evidence += f", and {len(offenders) - 1} more member name(s)"
        hits.append(("wrapper-member-name", evidence))
    text = tree.text(rel, view)
    if text is None:
        return hits
    low = tree.lower(rel, view)
    if rel not in OWN_LICENSE_PATHS:
        for name, prefilter, regex in FOREIGN_LICENSE_BODY_RES:
            if prefilter not in low:
                continue
            match = regex.search(text)
            if match:
                hits.append(("foreign-license-text", f"{name}: {_snippet(text, match)}"))
                break
        # EVERY tag/line is inspected, not just the first: an own Apache tag or
        # own copyright header sitting ABOVE a pasted upstream header must not
        # mask it. `.search()` here made both signals silently stop firing in
        # exactly that layout — the false-negative shape this audit exists to
        # prevent, on a rule that cannot be exempted (issue #25, acceptance
        # item 4; controls `masking/*` in --negative-control).
        if "spdx-license-identifier" in low:
            for spdx in SPDX_RE.finditer(text):
                # EVERY operand of the expression, not just the leading one:
                # "Apache-2.0 OR GPL-3.0-or-later" is a foreign tag.
                foreign = spdx_foreign_ids(spdx.group(1))
                if foreign:
                    # Label assembled from fragments (see the fixture note below).
                    hits.append(
                        (
                            "foreign-license-text",
                            "SPDX-License" + "-Identifier tag: " + ", ".join(foreign),
                        )
                    )
                    break
        if any(token in low for token in COPYRIGHT_PREFILTERS):
            # EVERY notice is inspected (an own header above a pasted one must
            # not mask it), each judged from its own holder field, and a notice
            # may carry no year or wrap its holder list onto the next line.
            copyright_match = foreign_copyright_match(text)
            if copyright_match is not None:
                hits.append(
                    (
                        "foreign-license-text",
                        f"copyright line: {_snippet(text, copyright_match)}",
                    )
                )
    if any(token in low for token in UPSTREAM_CITATION_PREFILTERS):
        for name, prefilter, regex in QUOTATION_MARKER_RES:
            if prefilter not in low:
                continue
            match = regex.search(text)
            if match:
                hits.append(
                    ("self-declared-quotation", f"{name}: {_snippet(text, match)}")
                )
                break
    return hits


def _snippet(text, match, width=70):
    start = max(0, match.start() - width // 2)
    end = min(len(text), match.end() + width // 2)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def live_quotation_spans(text, occurrences):
    """Spans of `occurrences` in `text` that actually contain a quotation marker.

    The same resolution `check_manifest` performs against the working-tree text,
    re-run here for a staged view (increment 14): an exemption names occurrences
    of the quotation vocabulary, and a span computed from one view's offsets
    means nothing in the other's. An occurrence that is absent from the view
    being judged contributes no span, so its markers are NOT exempt there —
    which is the conservative direction on a scoped exemption.
    """
    markers = quotation_marker_matches(text)
    spans = []
    for occurrence in occurrences or ():
        for match in occurrence_regex(occurrence).finditer(text):
            if any(
                match.start() <= mk.start() and mk.end() <= match.end()
                for _, mk in markers
            ):
                spans.append((match.start(), match.end()))
    return spans


def _view_tripwire_findings(tree: Tree, rel, view, coverage, exemptions, counts):
    """Findings for one BYTE VIEW of one entry, and the hits it contributes."""
    findings = []
    # True for any view whose offsets are not the ones `check_manifest` resolved
    # a scoped exemption's occurrences against: the staged blob (increment 14)
    # and a commit's blob (increment 17). Re-resolving is the conservative
    # direction — an occurrence absent from THESE bytes exempts nothing in them.
    reresolve = view != tree.view_for(rel)
    staged = view != WORKTREE_VIEW
    for rule, evidence in tripwire_hits(tree, rel, view):
        counts[rule] += 1
        if rule in coverage.get(rel, ()):
            continue
        exemption = exemptions.get(rel, {}).get(rule)
        if exemption and exemption["spans"] is None:
            continue
        if exemption:
            # Occurrence-scoped: exempt only markers inside a named span. The
            # spans resolved for the working-tree text do not address any other
            # view's offsets, so a staged view re-resolves them against its own
            # bytes rather than reusing them.
            spans = (
                live_quotation_spans(
                    tree.text(rel, view) or "", exemption.get("occurrences")
                )
                if reresolve
                else exemption["spans"]
            )
            outside = [
                (name, match)
                for name, match in quotation_marker_matches(tree.text(rel, view) or "")
                if not any(
                    start <= match.start() and match.end() <= end
                    for start, end in spans
                )
            ]
            if not outside:
                continue
            name, match = outside[0]
            evidence = (
                f"{name}: {_snippet(tree.text(rel, view), match)} (outside the "
                "occurrence(s) its exemption names)"
            )
        if staged:
            # The path alone does not say which bytes offended, and the answer
            # changes what the author must do: the working-tree copy is clean,
            # the STAGED one is not, and a commit would publish the staged one.
            evidence = view_evidence_prefix(view) + evidence
        findings.append(
            Finding(
                rule,
                rel,
                f"{RULES[rule]}: {evidence} — add a row to {MANIFEST_REL} "
                "(with its decision record)"
                + (
                    f", or an explicit '{rule}' exemption with a reason"
                    if rule in EXEMPTIBLE_RULES
                    else ""
                ),
            )
        )
    return findings


def check_tripwires(tree: Tree, coverage, exemptions):
    """Tripwire findings over every byte view of every in-scope entry.

    Two passes, not one (increment 14): the working-tree bytes of each in-scope
    entry, then the STAGED bytes of each entry whose index blob is not known to
    match them. A provenance row or exemption attached to the path answers both
    views — it is the file's third-party content that is being declared — but the
    occurrence spans of a scoped exemption are re-resolved per view.
    """
    findings = []
    counts = {rule: 0 for rule in TRIPWIRE_RULES}
    # `entry_views` is the single definition of that view set (increment 16),
    # which read it out of this loop so the two bookkeeping checks that now
    # share it cannot drift from the enumeration group 4 uses. Every entry in
    # `staged_views` is in `files` by construction (it is filtered on
    # `index_blobs` and on not being excluded), so iterating per entry covers
    # exactly what the two sequential loops here covered before.
    for rel in tree.files:
        for view in entry_views(tree, rel):
            findings += _view_tripwire_findings(
                tree, rel, view, coverage, exemptions, counts
            )
    return findings, counts
