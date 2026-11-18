#!/usr/bin/env python3
"""SXT-019 provenance audit — the tree layer (what exists, in which byte view).

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule
or message was changed, reordered or reflowed). This module decides what
EXISTS as far as the audit is concerned and what kind of entry each path is,
and serves each entry's bytes in every view it has — working tree, index,
staged blob and committed history — through the `Tree` cache.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from check_provenance_payload import (
    harvest_payload,
    sniff_encoding,
    unwrap_payload,
)
from check_provenance_rules import (
    INDEX_REL,
    MANIFEST_REL,
    RECORD_DIR_REL,
)
from check_provenance_signals import (
    AuditError,
    BINARY_SNIFF_BYTES,
    RECORD_FILE_RE,
)


# --- file discovery -----------------------------------------------------------
#
# This layer decides what EXISTS as far as the audit is concerned, and — new in
# increment 7 — what KIND of entry each path is. Everything above it reads
# bytes; a tree entry that carries its content by REFERENCE has no bytes of its
# own to read, so the signal layers never saw it:
#
#   * a committed submodule (mode 160000) is one index entry whose files are
#     not listed in the parent at all. `open()` on it raises IsADirectoryError,
#     so it decoded to None and reached no content rule — a gitlink pinning the
#     GPL Surge engine audited clean, which is the single highest-volume way
#     upstream content can enter this tree (and `AGENTS.md`/#25 forbid creating
#     one "by silent default").
#   * a tracked symlink (mode 120000) whose target leaves the tree carries
#     upstream content at a product path. `open()` follows it, so a target that
#     resolves is read — but a target that is absent at audit time (the CI
#     shape: the pinned oracle is an EXTERNAL working directory by design) read
#     as "undecodable payload" and was counted with the renders.
#
# Both are therefore judged here, from the entry itself, before any byte is
# read. `.gitmodules` is used only to name the upstream in the finding.

# `git ls-files -s` modes for entries that are not regular files.
GIT_MODE_KINDS = {"120000": "symlink", "160000": "gitlink"}

# How many un-indexed working-tree paths the text report names individually.
# The COUNT is always printed; this only bounds the listing (`--json` carries
# the full list either way).
UNINDEXED_PATHS_LISTED = 10


def list_entries(root: Path):
    """[(rel, kind, gitlink_commit)] for candidate entries, sorted by path.

    `kind` is "file", "symlink" or "gitlink". Uses `git ls-files -s` when the
    tree is a git checkout (so untracked scratch files are not audited, and the
    recorded MODE is read rather than guessed), and falls back to a filesystem
    walk otherwise (synthetic trees in tests and in --negative-control).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-s", "-z"],
            capture_output=True,
            check=True,
        )
        records = [r for r in proc.stdout.decode("utf-8", "replace").split("\0") if r]
        if records:
            seen = {}
            for record in records:
                meta, _, rel = record.partition("\t")
                if not rel:
                    continue
                fields = meta.split()
                mode = fields[0] if fields else ""
                blob = fields[1] if len(fields) > 1 else ""
                kind = GIT_MODE_KINDS.get(mode, "file")
                # Conflict stages repeat a path; the first stage is enough.
                # The object id is kept for EVERY kind, not just gitlinks: for a
                # blob it is how the STAGED bytes are read (increment 14), and
                # for a gitlink it is the commit the entry pins (increment 7).
                seen.setdefault(rel, (kind, blob))
            return sorted((rel, kind, blob) for rel, (kind, blob) in seen.items())
    except (OSError, subprocess.CalledProcessError):
        pass
    return sorted(_walk_entries(root))


# --- the index boundary (increment 11) ---------------------------------------
#
# `list_entries` reads the git INDEX, so what it audits is "what this repository
# has committed or staged", not "what is in this working tree". That boundary is
# right for CI — a PR's files are all tracked — but it was SILENT, and silence
# is the one thing every other residual in this tool is not:
#
#   * a file dropped into the working tree and not yet `git add`ed is scanned by
#     no rule at all. Dropping an unattributed file carrying a GPL body, a
#     foreign SPDX tag and a foreign copyright line into `model/` audited
#     **PASS**, and the coverage line printed the SAME file count as the clean
#     tree — so "no unattributed file is here" and "one is here, unlooked at"
#     were indistinguishable in the output;
#   * that is exactly the local, pre-commit run acceptance item 4's own wording
#     describes ("demonstrate it once on a deliberately unattributed file"), and
#     the demonstration only worked after staging the file.
#
# The boundary is kept — auditing a developer's scratch files by default would
# put unanswerable findings on a non-exemptible rule — but it is now DISCLOSED
# per run (a count, printed even when zero, so "none present" and "never looked"
# do not look alike), DECLARED in `--limits`, and crossable on demand with
# `--include-untracked`.
#
# Ignored files are deliberately not counted: `.gitignore` is this repository's
# own statement that a path is not part of it, and build output would otherwise
# drown the signal. That sub-boundary is declared and control-pinned too.


def list_untracked(root: Path):
    """Repo-relative paths present in the working tree but not in the index.

    Ignored files are excluded (`--exclude-standard`). Returns `[]` for a tree
    that is not a git checkout, where "untracked" has no meaning: the
    filesystem walk in `_walk_entries` already sees every file there.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    if not _is_git_checkout(root):
        return []
    return sorted(r for r in proc.stdout.decode("utf-8", "replace").split("\0") if r)


def _is_git_checkout(root: Path):
    """True when `list_entries` read `root`'s own git index rather than walking.

    Guards against the one way the two discovery paths can disagree: a
    NON-git synthetic tree created inside a git checkout would make
    `git -C <tree> ls-files --others` succeed against the ENCLOSING repository
    and report every file in the tree as untracked, while `list_entries` had
    already walked and audited them all.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    top = proc.stdout.decode("utf-8", "replace").strip()
    if not top:
        return False
    try:
        return Path(top).resolve() == Path(root).resolve()
    except OSError:
        return False


# --- the staged-content boundary (increment 14) -------------------------------
#
# The layer below enumeration is not WHICH entries are read but WHICH BYTES an
# enumerated entry is read as. Increment 7 moved the discovery rules onto the
# INDEX (an entry's mode, a gitlink's pinned commit are read from `ls-files -s`),
# and increment 11 disclosed that the audited SET is the index. The CONTENT rules
# never followed: `Tree._read` opened `root / rel` — the WORKING TREE — so the
# bytes judged were not the bytes the index holds, and `git commit` commits the
# index. Two shapes audited **PASS** on a tree whose staged blob carried a
# complete GPL body, a foreign SPDX tag and a foreign copyright line:
#
#   * `git add carrier.py` and then overwrite the working-tree copy with
#     innocuous text (no re-add). Every content rule read the innocuous copy;
#     the commit published the body. Coverage printed nothing at all — the file
#     count, `files_not_content_scanned` and the un-indexed list were identical
#     to the clean tree's.
#   * `git add carrier.py` and then delete the working-tree copy. `ls-files`
#     still names it, `open()` raised `OSError`, the entry was recorded
#     "unreadable" and counted among the renders in `files_not_content_scanned`
#     — the same place increment 7's gitlink hid.
#
# So the audit now reads BOTH views of an entry whose staged blob and
# working-tree bytes differ: the working-tree view (unchanged — an unstaged
# paste into a tracked file must keep firing, which is what the audit is for
# before a `git add`) and the STAGED view, read from the index blob with
# `git cat-file`. Findings from the staged view say so in their evidence, and
# the divergence is reported as coverage on every run, printed even when zero.
#
# The divergence set is git's own index-vs-working-tree comparison
# (`diff-files`), so a legitimate difference introduced by a CRLF/clean filter
# is not called divergence — and when it is, the only cost is an extra scan of
# the committable bytes. Added to it are the entries git was TOLD not to
# compare: `assume-unchanged` (lowercase `ls-files -v` tag) and `skip-worktree`
# (`S`) both make `diff-files` report an entry clean no matter what its working
# copy holds, which is a "stop looking" switch sitting exactly under this rule.
# Those are audited from the index unconditionally rather than trusted.

# How many divergent paths the text report names individually (the COUNT is
# always printed; `--json` carries the full list either way).
STAGED_PATHS_LISTED = 10

# The two byte sources a single entry can be read as.
WORKTREE_VIEW = "working tree"
STAGED_VIEW = "staged"

# A third, DERIVED selector (increment 15), used as a `Tree`'s default view
# rather than as a byte source of its own: "the bytes a commit would publish"
# resolves per entry to its STAGED blob when the two views diverge, and to its
# working-tree copy when git itself says the two are equal — in which case the
# working-tree copy IS the committable content, and reading it is both cheaper
# and the same bytes. It exists because increment 14 moved the carriage rules
# onto both views while the ANSWERS to them (the provenance rows, exemptions,
# scope exclusions, the record index and the records' own headers) stayed on the
# working-tree copy, so an answer could be published by no commit at all.
COMMITTED_VIEW = "committed"

# The files that ANSWER a carriage finding rather than raise one. When any of
# them is staged-divergent, the audited tree has two different answer sets and
# the committable one has to be judged on its own (increment 15).
def _is_bookkeeping(rel):
    if rel in (MANIFEST_REL, INDEX_REL):
        return True
    parent, _, name = rel.rpartition("/")
    return parent == RECORD_DIR_REL and bool(RECORD_FILE_RE.match(name))

# `git ls-files -v` tags for entries git has been told not to compare against
# the working tree. A lowercase tag means assume-unchanged for any state.
SKIP_WORKTREE_TAG = "S"


def _view_label(rel, view):
    """`rel`, naming the byte source when it is not the working-tree copy.

    Used wherever coverage or a finding quotes a path: "which bytes offended" is
    not answerable from the path alone once an entry has two views.
    """
    return rel if view == WORKTREE_VIEW else f"{rel} [{view} blob]"


def entry_views(tree, rel):
    """Every byte view of `rel` this run reads, in the order it reads them.

    The view set increment 14 introduced for the carriage rules: the
    working-tree copy of every in-scope entry, plus the STAGED blob of every
    entry whose index bytes are not known to equal it. It lived inline in
    `check_tripwires` until increment 16 needed it in two MORE places — the two
    checks outside group 4 that read an entry's own content as EVIDENCE for a
    bookkeeping judgement (`check_citations`, `_corroborate`), each of which
    read exactly one view until then and so could be satisfied, or silenced, by
    bytes no commit publishes. It is a function rather than three copies of the
    same two lines precisely so a later increment cannot move one and leave the
    others behind, which is the shape of every mask this series has closed.

    A history tree (increment 17) has exactly one view of each entry — the blob
    its commit names — and that view is its PRIMARY one, so the structural
    signals belong to it rather than to a working-tree copy that describes some
    other tree entirely.
    """
    if tree.primary_view != WORKTREE_VIEW:
        return [tree.primary_view]
    views = [WORKTREE_VIEW]
    if rel in tree.staged_views:
        views.append(STAGED_VIEW)
    return views


def view_evidence_prefix(view):
    """How a finding names the bytes it read, or "" for the working-tree copy.

    One definition, used by both places that say it (increment 17 added the
    third view and would otherwise have inherited the staged wording for bytes
    that have nothing to do with an index).
    """
    if view == WORKTREE_VIEW:
        return ""
    if view == HISTORY_VIEW:
        return "in the content this COMMIT publishes (commit blob) — "
    return f"in the STAGED content ({view} blob), not in the working-tree copy — "


def _staged_evidence(view, detail):
    """`detail`, saying so when the bytes it describes are not the working copy.

    The path alone does not answer "which bytes" once an entry has two views,
    and the answer changes what the author must do — the same reason
    `_view_tripwire_findings` prefixes its evidence.
    """
    return view_evidence_prefix(view) + detail


def list_staged_divergent(root: Path):
    """Index entries whose STAGED bytes may differ from the working tree's.

    `git diff-files` answers the question directly and with git's own filter /
    CRLF semantics. Union-ed with the entries git was told not to compare
    (`assume-unchanged`, `skip-worktree`), whose staged bytes are therefore
    unknown here and are read rather than assumed clean.

    Returns `[]` for a tree that is not a git checkout, where there is no index
    to diverge from: `_walk_entries` has already read every file in it.
    """
    if not _is_git_checkout(root):
        return []
    divergent = set()
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff-files", "--name-only", "-z"],
            capture_output=True,
            check=True,
        )
        divergent.update(r for r in proc.stdout.decode("utf-8", "replace").split("\0") if r)
    except (OSError, subprocess.CalledProcessError):
        return []
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-v", "-z"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return sorted(divergent)
    for record in proc.stdout.decode("utf-8", "replace").split("\0"):
        if len(record) < 3 or record[1] != " ":
            continue
        tag, rel = record[0], record[2:]
        if tag.islower() or tag == SKIP_WORKTREE_TAG:
            divergent.add(rel)
    return sorted(divergent)


def read_index_blob(root: Path, oid: str):
    """The staged bytes of blob `oid`, or None when they cannot be read.

    None is "this view yielded nothing", never "this view is clean": the caller
    records it as an unreadable scan, and a view that was never read is reported
    separately from one that was read and carried no signal.
    """
    if not oid or not re.fullmatch(r"[0-9a-f]{40,64}", oid):
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", oid],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return proc.stdout


# --- the history boundary (increment 17) --------------------------------------
#
# Increments 11, 14 and 15 walked down one axis: WHICH entries are audited (the
# working tree, then the index), WHICH BYTES an audited entry is read as (the
# working-tree copy, then the staged blob), and WHICH ANSWER SET judges them
# (the copy on disk, then the committable one). Every one of those reads the
# repository as it stands NOW. The set nobody enumerated is the one a clone
# actually carries: **every tree every commit publishes**.
#
# That is not an abstract residual here. This repository merges with MERGE
# COMMITS (squash and rebase merges are disabled on the forge), so every
# intermediate commit of every merged branch is permanently reachable from
# `main` — `git clone` fetches its blobs, and `git show` prints them. A carrier
# added in one commit and deleted in a later one is therefore published content
# that no tree audit, in any of the four views above, ever reads: the final tree
# does not contain it.
#
# `--commits <rev-range>` audits each commit in a range as its own tree: the
# entries are that commit's (`git ls-tree -r`), the bytes are that commit's
# blobs, and the ANSWERS come from that commit's own `decision-records/`
# bookkeeping — the same asymmetry increment 15 established, one step further
# out. An answer is a claim a commit publishes, so a commit answers for the
# bytes it publishes; a later commit's apology is not retroactive.
#
# What this does NOT do, and says so on every run: it judges the commits in the
# range it was given, not all of history. Commits that predate the provenance
# manifest entirely have no answer set to be judged against, and are reported as
# NOT judged (a count and a list, never folded into a PASS) rather than buried
# under a finding per carrier per commit. Deleting the manifest does not buy
# that silence: once a commit in the range has published one, every later commit
# in the range is judged, and a commit that drops it is judged with no answers
# at all.

# The byte source of an entry read from a commit's tree. A view name, like
# WORKTREE_VIEW / STAGED_VIEW: `_read` resolves it through the same
# `git cat-file blob <oid>` path the staged view uses, because an index blob and
# a commit's blob are the same kind of object read the same way.
HISTORY_VIEW = "commit"

# How many commits the text report names individually per disclosure list (the
# COUNT is always printed; `--json` carries the full list either way).
HISTORY_COMMITS_LISTED = 10


def list_entries_at_commit(root: Path, sha: str):
    """[(rel, kind, oid)] for every entry commit `sha` publishes, sorted.

    The commit-tree counterpart of `list_entries`: `git ls-tree -r` is to a
    commit what `git ls-files -s` is to the index — the recorded MODE is read
    rather than guessed (so a symlink and a gitlink are seen as such), and the
    object id is how the bytes are read.
    """
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", sha],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise AuditError(
            f"cannot list the tree of {sha}: "
            + proc.stderr.decode("utf-8", "replace").strip()
        )
    seen = {}
    for record in proc.stdout.decode("utf-8", "replace").split("\0"):
        if not record:
            continue
        meta, _, rel = record.partition("\t")
        if not rel:
            continue
        fields = meta.split()
        if len(fields) < 3:
            continue
        mode, _type, oid = fields[0], fields[1], fields[2]
        seen.setdefault(rel, (GIT_MODE_KINDS.get(mode, "file"), oid))
    return sorted((rel, kind, oid) for rel, (kind, oid) in seen.items())


# Field separator for the one `git log` call that reads the range: a unit
# separator cannot occur in a commit subject.
_LOG_SEP = "\x1f"


def commit_log(root: Path, revrange):
    """[(sha, date, parents, subject)] for `revrange`, PARENTS BEFORE CHILDREN.

    `--topo-order --reverse` is not cosmetic: whether a commit that publishes no
    provenance manifest is "older than the manifest" or "deleted the manifest" is
    decided from its PARENTS, and in a merge-commit history (which this
    repository's is) a branch forked before the manifest landed carries trees
    that legitimately have none, interleaved by date with commits that do.
    Walking parents first is what lets each commit be judged against its own
    ancestry rather than against the calendar.

    A range that resolves to no commits is an AuditError, never an empty PASS:
    "nothing to audit" and "nothing offended" must not look alike.
    """
    args = [a for a in str(revrange).split() if a]
    if not args:
        raise AuditError("--commits needs a revision range (e.g. origin/main..HEAD)")
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "log",
            "--reverse",
            "--topo-order",
            "--date=short",
            f"--format=%H{_LOG_SEP}%ad{_LOG_SEP}%P{_LOG_SEP}%s",
            *args,
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise AuditError(
            f"cannot resolve the commit range {revrange!r}: "
            + proc.stderr.decode("utf-8", "replace").strip()
        )
    commits = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split(_LOG_SEP)
        if len(parts) == 4:
            commits.append((parts[0], parts[1], parts[2].split(), parts[3]))
    if not commits:
        raise AuditError(
            f"the commit range {revrange!r} resolves to no commits — a range "
            "that audits nothing is not a pass"
        )
    return commits


def commit_publishes_manifest(root: Path, sha, memo):
    """Does commit `sha` publish a provenance manifest at all? (memoised)

    Asked of PARENTS, including parents outside the audited range, which is why
    it goes to git rather than reading the range's own bookkeeping: the question
    "did this commit delete the answer set" is about the commit before it,
    wherever that commit lives.
    """
    if sha in memo:
        return memo[sha]
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{sha}:{MANIFEST_REL}"],
        capture_output=True,
    )
    memo[sha] = proc.returncode == 0
    return memo[sha]


def commit_label(rel, sha):
    """`rel`, naming the commit whose bytes were judged.

    The history counterpart of `_view_label`: once the audited set spans
    commits, a path alone does not say which published bytes offended.
    """
    return f"{rel} [commit {sha[:12]}]"


def _walk_entries(root: Path):
    """Filesystem fallback for a tree that is not a git checkout.

    A directory that holds a `.git` entry is reported as a "gitlink": a nested
    repository checkout is the same by-reference carriage shape as a committed
    gitlink, and in a non-git tree (an unpacked tarball, a synthetic control
    tree) it is the only way to see one. It is not descended into — its files
    belong to that other repository, not this one.
    """
    out = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for path in children:
            if path.name in (".git", "__pycache__"):
                continue
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                out.append((rel, "symlink", ""))
            elif path.is_dir():
                if (path / ".git").exists():
                    out.append((rel, "gitlink", ""))
                    continue
                stack.append(path)
            elif path.is_file():
                out.append((rel, "file", ""))
    return out


SUBMODULE_PATH_RE = re.compile(r"^\s*path\s*=\s*(.+?)\s*$")
SUBMODULE_URL_RE = re.compile(r"^\s*url\s*=\s*(.+?)\s*$")


def parse_gitmodules(root: Path):
    """{submodule path: url} from `.gitmodules`, best effort (evidence only)."""
    try:
        text = (root / ".gitmodules").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    return parse_gitmodules_text(text)


def parse_gitmodules_text(text):
    """The same parse, from text already in hand.

    Split out for the history pass (increment 17): a commit's `.gitmodules` is a
    blob in that commit, not a file on disk, and reading the working-tree copy
    there would describe the wrong tree.
    """
    urls = {}
    path = None
    for line in text.splitlines():
        if line.lstrip().startswith("["):
            path = None
            continue
        match = SUBMODULE_PATH_RE.match(line)
        if match:
            path = match.group(1)
            continue
        match = SUBMODULE_URL_RE.match(line)
        if match and path:
            urls[path] = match.group(1)
    return urls


class Tree:
    """In-scope entry set (with kinds) plus cached text reads."""

    def __init__(self, root: Path, exclusions, include_untracked=False,
                 default_view=WORKTREE_VIEW, share_reads_from=None,
                 entries=None, primary_view=WORKTREE_VIEW, signal_cache=None):
        self.root = root
        self.exclusions = exclusions
        # The view that carries this tree's STRUCTURAL signals — an entry's
        # kind, its extension (increment 17). For every tree built over the
        # working checkout that is the working-tree view; for a commit tree it is
        # the commit's own blobs, which are the only bytes that tree has. It is
        # NOT the same question as `default_view`: the committable pass
        # (increment 15) reads committable BYTES while its entries are still the
        # working checkout's, and its primary view stays the working tree.
        self.primary_view = primary_view
        self.history = primary_view == HISTORY_VIEW
        # Carriage signals already derived for a (path, blob) pair, shared across
        # the commits of a history run (increment 17). Signals are a function of
        # a regular file's path and bytes alone, so a blob that survives 200
        # commits is scanned once; the ANSWERS are still re-derived per commit,
        # because they are what differs between commits. `None` disables it.
        self.signal_cache = signal_cache
        # Which bytes this tree reads when a caller names no view (increment
        # 15). `WORKTREE_VIEW` is the historical behaviour and stays the
        # default, so every existing call site is unchanged; `COMMITTED_VIEW`
        # makes the same code read what a commit would publish.
        self.default_view = default_view
        # `entries` is supplied only by the history pass, which enumerates a
        # COMMIT's tree rather than this checkout's index (increment 17).
        entries = list_entries(root) if entries is None else sorted(entries)
        # Present in the working tree, absent from the index (increment 11).
        # Always computed, because the COUNT is coverage that is reported
        # whether or not the entries are audited; `include_untracked` decides
        # only whether they also become ordinary entries. A commit's tree has no
        # working copy to be untracked relative to.
        self.untracked = [] if self.history else list_untracked(root)
        self.include_untracked = include_untracked
        if include_untracked:
            known = {rel for rel, _, _ in entries}
            entries = sorted(
                list(entries)
                + [
                    (rel, "symlink" if (root / rel).is_symlink() else "file", "")
                    for rel in self.untracked
                    if rel not in known
                ]
            )
        self.all_files = [rel for rel, _, _ in entries]
        self.kinds = {rel: kind for rel, kind, _ in entries}
        self.gitlink_commits = {
            rel: blob for rel, kind, blob in entries if kind == "gitlink" and blob
        }
        # Blob ids of the STAGED content of every entry that HAS content of its
        # own (increment 14). A gitlink's object is a commit in another
        # repository, not a blob here, so it is deliberately absent: its
        # by-reference carriage is judged from the index at the discovery layer
        # and its bytes are outside this audit in both views.
        self.index_blobs = {
            rel: blob for rel, kind, blob in entries if blob and kind != "gitlink"
        }
        # A commit's `.gitmodules` is a blob in that commit; read below, once the
        # caches exist, rather than from the working-tree copy of another tree.
        self.submodule_urls = {} if self.history else parse_gitmodules(root)
        self.excluded = {}
        # Gitlinks under a declared exclusion prefix (increment 13). A declared
        # exclusion is a hole in CONTENT scanning — "this prefix's bytes are
        # not product content, their provenance is the install as a whole" —
        # and a gitlink has no bytes of its own for that statement to be about.
        # Letting the prefix swallow it hid the single highest-volume entry a
        # tree can carry (a whole other repository) behind a line of manifest
        # text, while `symlink_escape()` was meanwhile treating a link INTO the
        # same prefix as a reportable escape: a hole you can point at but not
        # mount. So the existence of a by-reference entry is judged; only its
        # (nonexistent) content is excluded. Kept separately from
        # `self.excluded` so the exclusion is not double-counted as both
        # scanned and excluded, and so `scope-exclusion-stale` still sees a
        # prefix whose only member is a gitlink as live rather than stale.
        self.excluded_by_reference = {}
        self.files = []
        for rel in self.all_files:
            hit = self.excluded_by(rel)
            if hit is None:
                self.files.append(rel)
            elif self.kinds.get(rel) == "gitlink":
                self.excluded_by_reference.setdefault(hit, []).append(rel)
                self.files.append(rel)
            else:
                self.excluded.setdefault(hit, []).append(rel)
        # In-scope entries whose staged bytes are not known to equal the working
        # tree's, and which therefore get a SECOND content view (increment 14).
        # A path inside a declared scope exclusion is left out for the same
        # reason increment 11 leaves one out of its count: it is already
        # disclosed as a hole, and counting it here would read as coverage the
        # audit does not have.
        # A commit's tree has one view of each entry: the blob it names. There is
        # no index-vs-working-tree divergence to read there.
        self.staged_divergent = [] if self.history else list_staged_divergent(root)
        self.staged_views = [
            rel
            for rel in self.staged_divergent
            if rel in self.index_blobs and self.excluded_by(rel) is None
        ]
        self._staged_view_set = set(self.staged_views)
        # Read caches are keyed by (rel, VIEW), and a view's bytes do not depend
        # on which scope exclusions a manifest declares — so a second tree built
        # over the same root for the committable answer set shares them by
        # reference rather than re-inflating every payload (increment 15).
        self._text_cache = {}
        self._lower_cache = {}
        # How each file's text was obtained, and which scans were cut short.
        # Coverage is reported from these, so they are bookkeeping, not debug
        # state: a file scanned only as extracted strings has NOT had its whole
        # payload read as prose, and a truncated unwrap has not been read at all
        # past its budget.
        self._scan_modes = {}
        self._truncated = set()
        # Names a wrapper carries INSIDE it (increment 9). Bookkeeping, not
        # debug state: these are the only description a marker-free member has,
        # and the coverage line reports how many were read.
        self._carried_names = {}
        # Wide-encoded runs harvested from a payload (increment 10). Reported as
        # coverage for the same reason: a payload whose wide runs were never
        # examined must not look like one that carried none.
        self._wide_runs = {}
        # (rel, view) pairs a BOOKKEEPING check actually read as evidence
        # (increment 16). Reported as coverage, and NOT shared with a second
        # tree: the point of the count is which views THIS pass consulted, and
        # a tree whose staged views were read only by group 4 must not look
        # like one whose citations and provenance rows were checked against
        # them. Deliberately recorded at the point of a successful read, not
        # derived from `staged_views`, so a view the prefilter skipped or the
        # encoding sniff refused is not counted as examined.
        self._bookkeeping_reads = set()
        if share_reads_from is not None:
            self._text_cache = share_reads_from._text_cache
            self._lower_cache = share_reads_from._lower_cache
            self._scan_modes = share_reads_from._scan_modes
            self._truncated = share_reads_from._truncated
            self._carried_names = share_reads_from._carried_names
            self._wide_runs = share_reads_from._wide_runs
        if self.history and ".gitmodules" in self.index_blobs:
            self.submodule_urls = parse_gitmodules_text(self.text(".gitmodules") or "")

    def _key(self, rel, view):
        """Cache key for one read.

        The blob id joins the key for a commit view (increment 17): the same path
        holds different bytes in different commits, and a cache keyed on the path
        alone would answer a later commit's read with an earlier commit's text.
        """
        if view == HISTORY_VIEW:
            return (rel, view, self.index_blobs.get(rel, ""))
        return (rel, view)

    def view_for(self, rel):
        """The byte source this tree reads `rel` as when no view is named.

        The only non-trivial case is `COMMITTED_VIEW` (increment 15): the
        committable bytes of a DIVERGENT entry are its index blob, and of every
        other entry its working-tree copy — which git has just told us is the
        same content, so this is a cheaper spelling of the same read and not a
        weaker one. An entry with no blob in the index (a gitlink) is never in
        `staged_views`, so it keeps its by-reference treatment in both.
        """
        if self.default_view != COMMITTED_VIEW:
            return self.default_view
        if rel in self.index_blobs and rel not in self._staged_view_set:
            return WORKTREE_VIEW
        # No blob in the index (an entry `git rm --cached` left on disk, an
        # untracked path, a gitlink) or a divergent one: either way the answer
        # comes from the index, and for the first group that is deliberately
        # NOTHING — the working-tree copy must not stand in for content no
        # commit would publish.
        return STAGED_VIEW

    def divergent_bookkeeping(self):
        """Files that ANSWER findings rather than raise them, and that differ.

        Non-empty means this tree has two different answer sets — one on disk,
        one in the index — and the committable one has to be judged on its own.
        Reported as coverage on every run, empty included, for the same reason
        increment 14 prints its divergence list even when zero.

        Two ways an answer set can differ, not one. The obvious one is a
        staged-divergent file (increment 14's set). The other is a bookkeeping
        file in the working tree and NOT in the index — a record written and
        never staged, or a manifest `git rm --cached` left on disk. Its
        committable content is nothing at all, which is the largest possible
        difference, and leaving it out would have made the absent-manifest case
        the one shape the committable pass never looked at.
        """
        return sorted(
            {rel for rel in self.staged_views if _is_bookkeeping(rel)}
            | {rel for rel in self.untracked if _is_bookkeeping(rel)}
        )

    def note_bookkeeping_read(self, rel, view):
        """Record that a bookkeeping check read this view's bytes as evidence."""
        self._bookkeeping_reads.add((rel, view))

    def staged_views_read_as_evidence(self):
        """Staged views a bookkeeping check read (increment 16).

        Reported on every run, zero included: before increment 16 the staged
        views existed, were disclosed, and were read by the carriage rules
        alone — so "the bookkeeping groups agreed with the staged bytes" and
        "the bookkeeping groups never looked at them" were indistinguishable.
        """
        return sorted(rel for rel, view in self._bookkeeping_reads if view != WORKTREE_VIEW)

    def untracked_not_audited(self):
        """In-scope working-tree entries this run did NOT audit (increment 11).

        Empty when `--include-untracked` is on (they were audited) and when a
        path falls in a declared scope exclusion (already disclosed as a hole).
        """
        if self.include_untracked:
            return []
        return [rel for rel in self.untracked if self.excluded_by(rel) is None]

    def by_reference_inside_exclusions(self):
        """Gitlinks a declared exclusion covers but does not hide (increment 13).

        Reported as coverage on every run, zero included: an exclusion that
        happens to contain no submodule must not look like one whose submodule
        was never examined.
        """
        return sorted(
            rel for rels in self.excluded_by_reference.values() for rel in rels
        )

    def excluded_by(self, rel):
        for prefix in self.exclusions:
            if rel == prefix:
                return prefix
            # Path-boundary match only: an unslashed prefix like "corpus"
            # must not also match "corpus-eval/…" (PR #114 review, nit 3).
            boundary = prefix if prefix.endswith("/") else prefix + "/"
            if rel.startswith(boundary):
                return prefix
        return None

    def kind(self, rel):
        """"file" | "symlink" | "gitlink" — what sort of entry `rel` is."""
        return self.kinds.get(rel, "file")

    def staged_only(self):
        """Divergent entries with NO working-tree copy at all (increment 14).

        Reported separately because this is the shape whose working-tree view
        reaches no content rule: `open()` fails, the entry is recorded
        "unreadable" and counted among the opaque payloads, while its staged
        blob is the content a commit would publish.
        """
        return [rel for rel in self.staged_views if not os.path.lexists(self.root / rel)]

    def text(self, rel, view=None):
        """Text for the content rules, or None when the entry yields none.

        `view` selects the BYTE SOURCE (increment 14): the working-tree file, or
        the entry's staged blob. Both are read for an entry whose staged bytes
        and working-tree bytes differ — the working-tree view because an
        unstaged paste must still fire before a `git add`, the staged view
        because the index is what `git commit` publishes. `None` means "this
        tree's own default view" (increment 15), which is how the BOOKKEEPING
        groups — which name no view, because an answer set is one tree-wide
        thing rather than a per-entry choice — get moved onto the committable
        bytes without touching their call sites.

        A file this returns None for is scanned by NOTHING except the
        extension tripwires — so every step below is a detection surface, not a
        performance detail. Two increments of masking lived here:

          * treating "a NUL byte appears in the head" as "binary" let a
            UTF-16-encoded source file, or an ASCII one carrying a single stray
            NUL, carry a complete foreign license body, SPDX tag and copyright
            notice past every content rule (controls `masking/*-encoded-*`,
            `masking/stray-nul-*`);
          * treating an undecodable payload as opaque let a WRAPPER (a gzipped
            source file, a zip or tar renamed `.dat`) and an EMBEDDED notice (a
            WAV `LIST/INFO` copyright chunk, a notice spliced into a float dump)
            do the same (controls `payload/*`);
          * harvesting only the ASCII runs of such a payload let the same notice
            through once it was re-saved in a WIDE encoding — a "Unicode" save
            spliced into a render, a float dump or an opaque archive member
            (controls `payload/wide-*`, `payload/utf32-*`).

        So the order is: resolve an encoding; failing that, unwrap wrappers by
        magic and read their members; failing that, harvest the payload's
        word-bearing ASCII runs and its wide-encoded ones. What each file got is recorded in
        `_scan_modes` and reported as coverage — a strings-only scan is weaker
        than a decode, and says so, rather than being counted as a full read.
        """
        view = self.view_for(rel) if view is None else view
        key = self._key(rel, view)
        if key in self._text_cache:
            return self._text_cache[key]
        value, mode, truncated, names, wide = self._read(rel, view)
        self._scan_modes[key] = mode
        self._carried_names[key] = tuple(names)
        self._wide_runs[key] = wide
        if truncated:
            self._truncated.add(_view_label(rel, view))
        self._text_cache[key] = value
        return value

    def _read(self, rel, view=WORKTREE_VIEW):
        """(text|None, scan mode, truncated, member names, wide runs) for a view."""
        if view in (STAGED_VIEW, HISTORY_VIEW):
            raw = read_index_blob(self.root, self.index_blobs.get(rel, ""))
            if raw is None:
                # The index holds no blob for this entry (a gitlink), or git
                # could not produce it. Recorded as unread, never as clean.
                return None, "unreadable", False, (), 0
            encoding = sniff_encoding(raw[:BINARY_SNIFF_BYTES])
        else:
            try:
                with (self.root / rel).open("rb") as handle:
                    head = handle.read(BINARY_SNIFF_BYTES)
                    encoding = sniff_encoding(head)
                    raw = head + handle.read()
            except OSError:
                # A by-reference entry (a gitlink, a symlink to a directory), a
                # staged entry whose working copy was deleted, and an unreadable
                # file all land here. The discovery layer judges the first; the
                # second is answered by its staged view (increment 14).
                return None, "unreadable", False, (), 0
        if encoding is not None:
            value = raw.decode(encoding, "replace")
            # A stray NUL survives the narrow decode as U+0000 and would split a
            # regex's word gap; it is masking noise, not content. Drop it so the
            # signal layer sees the real text.
            if "\0" in value:
                value = value.replace("\0", "")
            return value, "decoded", False, (), 0
        entries, truncated = unwrap_payload(raw)
        if entries is not None:
            parts = []
            wide = 0
            for _, payload in entries:
                member_encoding = sniff_encoding(payload[:BINARY_SNIFF_BYTES])
                if member_encoding is None:
                    # A member the sniff refuses gets the same payload read as a
                    # committed one, wide runs included: a wrapper is not a place
                    # a re-encoded notice may hide (increment 10).
                    part, member_wide = harvest_payload(payload)
                    parts.append(part)
                    wide += member_wide
                else:
                    parts.append(
                        payload.decode(member_encoding, "replace").replace("\0", "")
                    )
            value = "\n".join(part for part in parts if part)
            names = tuple(name for name, _ in entries if name)
            # Scan mode describes the CONTENT read, as before: a wrapper whose
            # members are all opaque still read no text, and saying otherwise
            # because a NAME was recovered would overstate the content coverage.
            return (
                (value or None),
                ("unwrapped" if value else "none"),
                truncated,
                names,
                wide,
            )
        value, wide = harvest_payload(raw)
        return (value or None), ("strings" if value else "none"), truncated, (), wide

    def scan_mode(self, rel, view=None):
        """"decoded" | "unwrapped" | "strings" | "none" | "unreadable"."""
        view = self.view_for(rel) if view is None else view
        if self._key(rel, view) not in self._scan_modes:
            self.text(rel, view)
        return self._scan_modes.get(self._key(rel, view), "unreadable")

    def carried_names(self, rel, view=None):
        """Member names the wrapper at `rel` carries inside it (may be empty).

        Forces the read, like `scan_mode`: the unwrap that recovers these names
        happens there. Empty for every entry that is not a wrapper the audit
        could open — a corrupt stream and anything past the depth/inflation
        budget carry no names here, and that partial read is disclosed as a
        TRUNCATED payload scan rather than counted as a pass.
        """
        view = self.view_for(rel) if view is None else view
        if self._key(rel, view) not in self._carried_names:
            self.text(rel, view)
        return self._carried_names.get(self._key(rel, view), ())

    def wide_runs(self, rel, view=None):
        """How many wide-encoded runs this entry's payload yielded (increment 10).

        Forces the read, like `scan_mode`. Zero for a decoded file — a file the
        sniff admits is read whole, in its own encoding, by every content rule.
        """
        view = self.view_for(rel) if view is None else view
        if self._key(rel, view) not in self._wide_runs:
            self.text(rel, view)
        return self._wide_runs.get(self._key(rel, view), 0)

    def truncated_scans(self):
        """Paths whose payload scan hit the inflation/depth budget.

        A staged view carries its view in the label, so a truncated read of the
        committable bytes is not reported as if the working-tree copy had been
        the one cut short.
        """
        return sorted(self._truncated)

    def lower(self, rel, view=None):
        """Lowercased text — the cheap prefilter for every signal.

        Cached for ordinary decoded files. A payload-derived text (an inflated
        trace, a harvested render) is NOT cached: keeping a second copy of every
        unwrapped payload roughly doubled the audit's peak memory, and
        `str.lower()` on the few large ones costs milliseconds.
        """
        view = self.view_for(rel) if view is None else view
        key = self._key(rel, view)
        if key in self._lower_cache:
            return self._lower_cache[key]
        text = self.text(rel, view)
        value = None if text is None else text.lower()
        if value is None or self._scan_modes.get(key) == "decoded":
            self._lower_cache[key] = value
        return value
