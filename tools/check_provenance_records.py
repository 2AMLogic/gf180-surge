#!/usr/bin/env python3
"""SXT-019 provenance audit — decision records, their index and citations.

Split out of `tools/check_provenance.py` (a behavior-preserving move; no rule
or message was changed, reordered or reflowed). This module parses the
`decision-records/` tree and its `README.md` index, and resolves every
record citation found anywhere in the audited tree.
"""

from __future__ import annotations

import re

from check_provenance_rules import (
    INDEX_REL,
    MANIFEST_REL,
    RECORD_DIR_REL,
    STATUS_VOCABULARY,
)
from check_provenance_signals import (
    AuditError,
    Finding,
    INDEX_ROW_RE,
    RECORD_CITATION_RE,
    RECORD_FILE_RE,
)
from check_provenance_tree import (
    Tree,
    _staged_evidence,
    entry_views,
)


# --- pattern handling ---------------------------------------------------------


def glob_to_regex(pattern: str):
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def pattern_problem(pattern: str):
    """Reject blanket patterns: the last segment must name a file or *.ext.

    A bare `reports/**` would silently cover any future file of any type —
    exactly the hole this audit exists to close.
    """
    if not pattern or pattern.startswith("/") or ".." in pattern.split("/"):
        return "pattern must be a relative repo path"
    if "**" in pattern.replace("**/", ""):
        return "'**' is only allowed as a '**/' directory wildcard"
    last = pattern.rsplit("/", 1)[-1]
    if "*" in last and not re.fullmatch(r"\*\.[A-Za-z0-9]+", last):
        return (
            "the last segment must be a literal file name or '*.ext' "
            f"(got {last!r}) — blanket patterns are not accepted"
        )
    return None


# --- decision records ---------------------------------------------------------


def status_keyword(text):
    if not text:
        return None
    first = re.split(r"[^A-Za-z-]+", text.strip(), maxsplit=1)[0].lower()
    return first or None


def parse_records(tree: Tree):
    """{number: {'path', 'status', 'status_keyword', 'date'}} for records on disk."""
    records = {}
    findings = []
    for rel in tree.files:
        parent, _, name = rel.rpartition("/")
        if parent != RECORD_DIR_REL:
            continue
        match = RECORD_FILE_RE.match(name)
        if not match:
            continue
        number = match.group(1)
        text = tree.text(rel) or ""
        status = _header_field(text, "Status")
        date = _header_field(text, "Date")
        if status is None or date is None:
            findings.append(
                Finding(
                    "record-header-missing",
                    rel,
                    "expected '- **Status**: …' and '- **Date**: …' header lines",
                )
            )
        keyword = status_keyword(status)
        if status is not None and keyword not in STATUS_VOCABULARY:
            findings.append(
                Finding(
                    "record-status-unrecognized",
                    rel,
                    f"status keyword {keyword!r} not in {list(STATUS_VOCABULARY)}",
                )
            )
        records[number] = {
            "path": rel,
            "status": status,
            "status_keyword": keyword,
            "date": date,
        }
    return records, findings


def _header_field(text, field):
    pattern = re.compile(
        r"^[-*]\s*\*\*" + field + r"\*\*:?\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    if match:
        return match.group(1).strip()
    pattern = re.compile(
        r"^[-*]\s*\*\*" + field + r":\*\*\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def parse_index(tree: Tree):
    """{number: {'link', 'title', 'status', 'date', 'line'}} from the index table."""
    text = tree.text(INDEX_REL)
    if text is None:
        raise AuditError(f"{INDEX_REL} is missing or unreadable")
    rows = {}
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = INDEX_ROW_RE.match(line)
        if not match:
            continue
        number, link, title, status, date = match.groups()
        if number in rows:
            findings.append(
                Finding(
                    "index-duplicate-row",
                    INDEX_REL,
                    f"record {number} listed twice (line {lineno} and "
                    f"line {rows[number]['line']})",
                )
            )
            continue
        rows[number] = {
            "link": link.strip(),
            "title": title.strip(),
            "status": status.strip(),
            "date": date.strip(),
            "line": lineno,
        }
    return rows, findings


def check_index(records, rows):
    findings = []
    for number in sorted(records):
        record = records[number]
        row = rows.get(number)
        if row is None:
            findings.append(
                Finding(
                    "index-missing-row",
                    record["path"],
                    f"record {number} is on disk but has no row in {INDEX_REL} "
                    "(add one; the index is the visible list of decisions)",
                )
            )
            continue
        expected_link = record["path"].split("/")[-1]
        if row["link"] != expected_link:
            findings.append(
                Finding(
                    "index-unknown-record",
                    INDEX_REL,
                    f"row {number} links to {row['link']!r}, expected "
                    f"{expected_link!r}",
                )
            )
        row_keyword = status_keyword(row["status"])
        if record["status_keyword"] and row_keyword != record["status_keyword"]:
            findings.append(
                Finding(
                    "index-status-mismatch",
                    INDEX_REL,
                    f"row {number} says {row['status']!r} "
                    f"({row_keyword!r}) but the record says "
                    f"{record['status']!r} ({record['status_keyword']!r})",
                )
            )
        if record["date"] and row["date"] != record["date"]:
            findings.append(
                Finding(
                    "index-date-mismatch",
                    INDEX_REL,
                    f"row {number} says date {row['date']!r} but the record "
                    f"says {record['date']!r}",
                )
            )
    for number in sorted(rows):
        if number not in records:
            findings.append(
                Finding(
                    "index-unknown-record",
                    INDEX_REL,
                    f"row {number} has no matching decision-records/{number}-*.md",
                )
            )
    numbers = sorted(int(n) for n in records)
    for expected, actual in enumerate(numbers, start=1):
        if expected != actual:
            findings.append(
                Finding(
                    "index-number-gap",
                    RECORD_DIR_REL,
                    f"decision-record numbering is not contiguous: expected "
                    f"{expected:04d}, found {actual:04d} (a superseded record "
                    "stays on disk and is marked in its Status line)",
                )
            )
            break
    return findings


def check_citations(tree: Tree, records, rows):
    """A record citation must resolve in EVERY byte view that makes it.

    Group 2 reads an ENTRY's content, and until increment 16 it read exactly one
    view of it — the tree's default — so a citation present only in the bytes
    `git commit` publishes resolved against nothing and audited PASS, with the
    carrier disclosed as divergent and read by group 4 alone.

    A citation is a QUESTION the entry's bytes raise ("does this record exist,
    and is it indexed?"), so it is asked of both views for the same reason
    increment 14 asks a carriage question of both: an unstaged paste must fire
    before a `git add`, and a staged one must fire whatever the working copy
    says. The ANSWER (which records exist, which are indexed) still comes from
    the view that raised it — `records`/`rows` are parsed per pass, which is
    what increment 15's committable pass supplies here.
    """
    findings = []
    for rel in tree.files:
        if rel == MANIFEST_REL:
            continue
        for view in entry_views(tree, rel):
            low = tree.lower(rel, view)
            # Cheap prefilter (superset of RECORD_CITATION_RE): skip files that
            # cannot cite a record at all.
            if low is None or not any(
                token in low for token in ("decision-records/", "dr-0", "dr0")
            ):
                continue
            text = tree.text(rel, view)
            tree.note_bookkeeping_read(rel, view)
            for number in sorted(set(RECORD_CITATION_RE.findall(text))):
                if number not in records:
                    findings.append(
                        Finding(
                            "dangling-record-citation",
                            rel,
                            _staged_evidence(
                                view,
                                f"cites decision record {number}, which does "
                                "not exist",
                            ),
                        )
                    )
                elif number not in rows:
                    findings.append(
                        Finding(
                            "unindexed-record-citation",
                            rel,
                            _staged_evidence(
                                view,
                                f"cites decision record {number}, which is "
                                f"missing from the {INDEX_REL} index",
                            ),
                        )
                    )
    return findings
