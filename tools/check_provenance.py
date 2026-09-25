#!/usr/bin/env python3
"""SXT-019 provenance audit — governance issue #25, acceptance item 4.

Flags any file that carries (or admits carrying) third-party-derived content
without a provenance row, and keeps the `decision-records/` bookkeeping
self-consistent. The rules this enforces come from `AGENTS.md` ("copying
Surge-derived code, tables, or assets into this repository requires a visible
license decision record before merge"; "record file/table-level provenance
before adopting any third-party code, table, or asset") and from
`docs/REUSE-AUDIT.md` § "Adoption mechanics".

The audit has four groups of checks:

  1. **Decision-record index integrity** — every `decision-records/NNNN-*.md`
     has exactly one row in the `README.md` index, every row resolves to an
     existing record, and each row's status keyword and date match the
     record's own header fields. (A missing row is how this issue's own
     staleness happened; the check makes recurrence a CI failure.)
  2. **Citation integrity** — every `decision-records/NNNN` / `DR-NNNN`
     citation anywhere in the scanned tree resolves to a record that exists
     and is indexed. A PR cannot claim a license decision record that is not
     there.
  3. **Provenance manifest integrity** — `decision-records/provenance.json`
     rows are exact and current: the path exists, the class is known, the
     cited decision record exists and is indexed, and the file itself
     corroborates the row (it cites the record, or the pinned upstream
     commit the row names). Stale rows, blanket patterns, and exemptions
     that match nothing all fail.
  4. **Undeclared-carrier tripwires** — content signals that a file carries
     third-party material. A tripwire hit must be answered by a provenance
     row (or, for the one exemptible rule, by an explicit exemption with a
     reason). The tripwires are deliberately high-precision:
       * `foreign-license-text`        — foreign license body, non-Apache
                                         SPDX tag, or foreign copyright line
       * `upstream-asset-extension`    — Surge/third-party asset or opaque
                                         binary-bundle extensions
       * `foreign-source-language`     — source languages this repository
                                         does not author
       * `self-declared-quotation`     — the repo's own quotation vocabulary
                                         ("quoted as data", "QUOTED",
                                         "transcribed from", "vendored", …)
                                         co-occurring with an upstream
                                         citation                (exemptible)

DECLARED LIMITS — read before quoting this tool as evidence:

  * A PASS is **not** proof that no third-party content was copied. Code
    copied with every marker stripped, a re-typed constant table with no
    citation, or content under a path excluded from scope (printed on every
    run) will not be detected. The tool enforces *bookkeeping*, and detects
    the carriage signals listed above; it does not perform similarity
    matching against upstream trees.
  * A PASS says nothing about whether a decision record's *reasoning* is
    right, or whether the owner has ratified it. Most records are PROPOSED.
  * Coverage (files scanned, rows checked) is reported separately from
    agreement (findings), per `AGENTS.md`.

Self-test: `--negative-control` rebuilds a synthetic tree, injects one
deliberate violation per rule, and requires every rule to fire. A rule that
silently stops firing — the false-negative failure mode that would otherwise
pass review unnoticed — fails the self-test, and therefore CI.

Usage:
    python3 tools/check_provenance.py                # audit this repository
    python3 tools/check_provenance.py --root DIR     # audit another tree
    python3 tools/check_provenance.py --json         # machine-readable report
    python3 tools/check_provenance.py --negative-control

Exit codes: 0 = PASS, 1 = findings (FAIL), 2 = the audit itself could not run
(or a negative control did not fire).

Python 3 standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MANIFEST_REL = "decision-records/provenance.json"
INDEX_REL = "decision-records/README.md"
RECORD_DIR_REL = "decision-records"

SCHEMA_VERSION = 1

# Every provenance row must cite a decision record: "Nothing is adopted
# without a recorded decision in #25" (docs/REUSE-AUDIT.md, standing rules).
KNOWN_CLASSES = {
    # engine/third-party data constants quoted into this repository
    "quoted-constants": "third-party data constants quoted as data",
    # identity (path/hash/dims) of an external asset whose payload stays out
    "external-asset-identity": "external asset identity only, payload external",
    # original source here that compiles against pinned third-party headers
    "api-client-harness": "original source built against pinned upstream headers",
    # in-repo tooling that drives an externally built/patched upstream binary
    "external-build-client": "drives an externally built upstream binary",
    # a file copied from a third party (pinned, attributed, license recorded)
    "vendored-copy": "file copied from a third-party source",
}

# --- rule ids -----------------------------------------------------------------

RULES = {
    # group 1: decision-record index integrity
    "index-missing-row": "decision record on disk with no index row",
    "index-unknown-record": "index row whose record file does not exist",
    "index-duplicate-row": "decision record listed more than once in the index",
    "index-status-mismatch": "index status keyword differs from the record",
    "index-date-mismatch": "index date differs from the record",
    "index-number-gap": "gap in the decision-record numbering",
    "record-status-unrecognized": "record status keyword outside the vocabulary",
    "record-header-missing": "record without a parseable Status/Date header",
    # group 2: citation integrity
    "dangling-record-citation": "citation of a decision record that does not exist",
    "unindexed-record-citation": "citation of a record missing from the index",
    # group 3: provenance manifest integrity
    "manifest-missing": "provenance manifest absent or unreadable",
    "manifest-schema": "provenance manifest schema problem",
    "manifest-field-missing": "provenance row missing a required field",
    "manifest-unknown-class": "provenance row with an unknown class",
    "manifest-stale-path": "provenance row whose path matches no file",
    "manifest-bad-pattern": "provenance row pattern too broad or malformed",
    "manifest-missing-record": "provenance row citing a nonexistent record",
    "manifest-unindexed-record": "provenance row citing an unindexed record",
    "manifest-uncorroborated": "file does not corroborate its provenance row",
    "exemption-field-missing": "exemption missing a required field",
    "exemption-non-exemptible-rule": "exemption of a non-exemptible rule",
    "exemption-stale": "exemption matching no file",
    "exemption-bad-pattern": "exemption pattern too broad or malformed",
    "scope-exclusion-stale": "declared scope exclusion matching no file",
    "scan-underflow": "fewer files scanned than the manifest's declared floor",
    # group 4: undeclared-carrier tripwires
    "foreign-license-text": "foreign license/copyright text without a provenance row",
    "upstream-asset-extension": "upstream asset / opaque bundle without a provenance row",
    "foreign-source-language": "foreign-language source file without a provenance row",
    "self-declared-quotation": "self-declared quotation without a provenance row",
}

TRIPWIRE_RULES = (
    "foreign-license-text",
    "upstream-asset-extension",
    "foreign-source-language",
    "self-declared-quotation",
)

# Only the prose-marker tripwire may be exempted: a document may *discuss*
# quotation without carrying anything. A foreign license body, an upstream
# asset payload, or foreign-language source must be answered by a real
# provenance row — never by an exemption.
EXEMPTIBLE_RULES = frozenset({"self-declared-quotation"})

STATUS_VOCABULARY = (
    "ratified",
    "accepted",
    "proposed",
    "escalated",
    "superseded",
    "withdrawn",
    "rejected",
)

# --- content signals ----------------------------------------------------------

# Third-party trees this repository cites but must not carry. The pinned Surge
# commit is the one in AGENTS.md; the substrate names come from the reuse
# survey (docs/REUSE-AUDIT.md). Matched as lowercase substrings.
UPSTREAM_CITATION_PREFILTERS = (
    "58914e59c608ed4384ba6002e44c3465c58b2e71",
    "surge-synthesizer/surge",
    "sst-basic-blocks",
    "sst-effects",
    "sst-filters",
    "airwindows",
    "airwin",
    "torchsynth",
    "parasynth",
    "klayout-tools",
)

# The repository's own vocabulary for "this is upstream data, not our work".
# (name, lowercase prefilter, confirming regex) — the prefilter must be a
# superset of what the regex can match.
QUOTATION_MARKER_RES = (
    ("quoted-as-data", "quoted as ", re.compile(r"quoted as (?:cited )?data", re.IGNORECASE)),
    ("QUOTED", "quoted", re.compile(r"\bQUOTED\b")),
    ("transcribed-from", "transcribed", re.compile(r"transcribed from", re.IGNORECASE)),
    (
        "copied-verbatim",
        "verbatim",
        re.compile(r"copied verbatim|verbatim cop(?:y|ied)", re.IGNORECASE),
    ),
    ("vendored", "vendor", re.compile(r"\bvendored?\b", re.IGNORECASE)),
)

# The license-body patterns are split across string fragments on purpose: a
# contiguous license phrase in this file would make the audit flag its own
# source (the rule is not exemptible, by design). See the fixture note further
# down. Do not "tidy" these into single literals.
FOREIGN_LICENSE_BODY_RES = (
    (
        "gpl-body",
        "general public license",
        re.compile(r"GNU (?:LESSER |AFFERO )?GENERAL PUBLIC LICENSE", re.IGNORECASE),
    ),
    (
        "fsf-body",
        "free software",
        re.compile("This program is " + "free software", re.IGNORECASE),
    ),
    (
        "mit-body",
        "permission is hereby granted",
        re.compile("Permission is hereby granted, " + "free of charge", re.IGNORECASE),
    ),
    (
        "bsd-body",
        "redistribution and use",
        re.compile("Redistribution and use in source " + "and binary forms", re.IGNORECASE),
    ),
    (
        # Prefilter deliberately just "mozilla": a case-insensitive regex
        # matches its own lowercase prefilter if the prefilter spells out the
        # whole phrase.
        "mpl-body",
        "mozilla",
        re.compile("MOZILLA " + "PUBLIC LICENSE", re.IGNORECASE),
    ),
)

# Assembled from fragments so this file does not itself contain a contiguous
# SPDX tag (see the fixture note below).
SPDX_RE = re.compile("SPDX-License" "-Identifier" + r":\s*([^\s*/#\"']+)")
OWN_SPDX = "apache-2.0"
COPYRIGHT_PREFILTERS = ("copyright", "(c)", "©")

COPYRIGHT_RE = re.compile(
    r"(?:Copyright|\(c\)|©)\s*(?:\(c\)\s*|©\s*)?(?:19|20)\d\d",
    re.IGNORECASE,
)
OWN_HOLDER_RE = re.compile(r"2AM\s*Logic|2AMLogic|gf180-surge", re.IGNORECASE)

# The repository's own Apache-2.0 license text (its appendix contains a
# copyright placeholder). Hardcoded rather than exemptible: the LICENSE file
# is required to be there, and no provenance row can describe it.
OWN_LICENSE_PATHS = frozenset({"LICENSE"})

# Surge/third-party asset payload types plus opaque bundles that no review can
# read. `.gz` is deliberately absent: this repository gzips its own evidence
# traces. `.wav`/`.bin`/`.hex`/`.npy`/`.npz` are this project's own render and
# RTL artifacts (fixtures/README.md § Licensing / provenance).
UPSTREAM_ASSET_EXTS = frozenset(
    {
        ".wt", ".wtscan", ".fxp", ".fxb", ".srg",
        ".zip", ".tar", ".tgz", ".rar", ".7z", ".jar", ".whl", ".egg",
        ".so", ".dylib", ".dll", ".a", ".lib", ".o", ".obj",
        ".pt", ".pth", ".safetensors", ".h5", ".onnx",
    }
)

# Languages this repository authors: Python, SystemVerilog/Verilog, shell,
# markdown/JSON/CSV data. Anything else is either vendored or an explicitly
# recorded API-client harness (e.g. oracle/sxt038/lp24_ref_harness.cpp, DR-0010).
FOREIGN_SOURCE_EXTS = frozenset(
    {
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl",
        ".rs", ".go", ".java", ".kt", ".swift", ".m", ".mm",
        ".ts", ".tsx", ".js", ".jsx", ".rb", ".pl", ".lua", ".cs", ".scala",
        ".vhd", ".vhdl",
    }
)

RECORD_CITATION_RE = re.compile(r"(?:decision-records/|\bDR-?)(\d{4})")
RECORD_FILE_RE = re.compile(r"^(\d{4})-[A-Za-z0-9._-]+\.md$")
INDEX_ROW_RE = re.compile(
    r"^\|\s*\[(\d{4})\]\(([^)]+)\)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$"
)

CAVEAT = (
    "NOTE: bookkeeping + carriage-signal audit only. A PASS is not proof that "
    "no third-party content was copied (see --limits), and says nothing about "
    "whether any decision record has been ratified."
)

BINARY_SNIFF_BYTES = 8192


class AuditError(Exception):
    """The audit could not be performed (exit 2, never a silent pass)."""


class Finding:
    def __init__(self, rule, path, detail):
        if rule not in RULES:
            raise AuditError(f"internal: unknown rule id {rule!r}")
        self.rule = rule
        self.path = path
        self.detail = detail

    def as_dict(self):
        return {"rule": self.rule, "path": self.path, "detail": self.detail}

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Finding({self.rule!r}, {self.path!r}, {self.detail!r})"


# --- file discovery -----------------------------------------------------------


def list_files(root: Path):
    """Repo-relative POSIX paths of candidate files, deterministically sorted.

    Uses `git ls-files` when the tree is a git checkout (so untracked scratch
    files are not audited), and falls back to a filesystem walk otherwise
    (synthetic trees in tests and in --negative-control).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        names = [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]
        if names:
            return sorted(names)
    except (OSError, subprocess.CalledProcessError):
        pass

    out = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/__pycache__/" in f"/{rel}":
            continue
        out.append(rel)
    return sorted(out)


class Tree:
    """In-scope file set plus cached text reads."""

    def __init__(self, root: Path, exclusions):
        self.root = root
        self.exclusions = exclusions
        self.all_files = list_files(root)
        self.excluded = {}
        self.files = []
        for rel in self.all_files:
            hit = self._excluded_by(rel)
            if hit is None:
                self.files.append(rel)
            else:
                self.excluded.setdefault(hit, []).append(rel)
        self._text_cache = {}
        self._lower_cache = {}

    def _excluded_by(self, rel):
        for prefix in self.exclusions:
            if rel == prefix or rel.startswith(prefix):
                return prefix
        return None

    def text(self, rel):
        """Decoded text, or None for binary/unreadable files.

        Sniffs the first block for NUL bytes before reading the rest, so a
        multi-megabyte render or trace payload is never fully decoded.
        """
        if rel in self._text_cache:
            return self._text_cache[rel]
        value = None
        try:
            with (self.root / rel).open("rb") as handle:
                head = handle.read(BINARY_SNIFF_BYTES)
                if b"\0" not in head:
                    value = (head + handle.read()).decode("utf-8", "replace")
        except OSError:
            value = None
        self._text_cache[rel] = value
        return value

    def lower(self, rel):
        """Lowercased text (cached) — the cheap prefilter for every signal."""
        if rel not in self._lower_cache:
            text = self.text(rel)
            self._lower_cache[rel] = None if text is None else text.lower()
        return self._lower_cache[rel]


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
    findings = []
    for rel in tree.files:
        if rel == MANIFEST_REL:
            continue
        low = tree.lower(rel)
        # Cheap prefilter (superset of RECORD_CITATION_RE): skip files that
        # cannot cite a record at all.
        if low is None or not any(
            token in low for token in ("decision-records/", "dr-0", "dr0")
        ):
            continue
        text = tree.text(rel)
        for number in sorted(set(RECORD_CITATION_RE.findall(text))):
            if number not in records:
                findings.append(
                    Finding(
                        "dangling-record-citation",
                        rel,
                        f"cites decision record {number}, which does not exist",
                    )
                )
            elif number not in rows:
                findings.append(
                    Finding(
                        "unindexed-record-citation",
                        rel,
                        f"cites decision record {number}, which is missing from "
                        f"the {INDEX_REL} index",
                    )
                )
    return findings


# --- manifest -----------------------------------------------------------------


REQUIRED_ENTRY_FIELDS = (
    "class",
    "content",
    "upstream",
    "upstream_license",
    "decision_record",
)


def load_manifest(root: Path):
    path = root / MANIFEST_REL
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Finding("manifest-missing", MANIFEST_REL, f"cannot read: {exc}")]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [Finding("manifest-missing", MANIFEST_REL, f"invalid JSON: {exc}")]
    if not isinstance(data, dict):
        return None, [Finding("manifest-schema", MANIFEST_REL, "top level must be an object")]
    findings = []
    if data.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "manifest-schema",
                MANIFEST_REL,
                f"schema_version {data.get('schema_version')!r} != {SCHEMA_VERSION}",
            )
        )
    for key in ("entries", "exemptions", "scope_exclusions"):
        value = data.get(key, [])
        if not isinstance(value, list):
            findings.append(Finding("manifest-schema", MANIFEST_REL, f"{key!r} must be a list"))
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


def check_manifest(tree: Tree, manifest, records, rows):
    """Validate rows/exemptions and return (findings, coverage)."""
    findings = []
    coverage = {}  # rel -> list of entry descriptions
    exemptions = {}  # rel -> {rule -> reason}

    for index, entry in enumerate(manifest.get("entries", []) or []):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            findings.append(Finding("manifest-schema", MANIFEST_REL, f"{label} must be an object"))
            continue
        if bool(entry.get("path")) == bool(entry.get("pattern")):
            findings.append(
                Finding(
                    "manifest-field-missing",
                    MANIFEST_REL,
                    f"{label}: exactly one of 'path' or 'pattern' is required",
                )
            )
            continue
        missing = [f for f in REQUIRED_ENTRY_FIELDS if not entry.get(f)]
        if missing:
            findings.append(
                Finding(
                    "manifest-field-missing",
                    MANIFEST_REL,
                    f"{label} ({entry.get('path') or entry.get('pattern')}): "
                    f"missing required field(s) {missing}",
                )
            )
        if entry.get("class") and entry["class"] not in KNOWN_CLASSES:
            findings.append(
                Finding(
                    "manifest-unknown-class",
                    MANIFEST_REL,
                    f"{label}: class {entry['class']!r} not in "
                    f"{sorted(KNOWN_CLASSES)}",
                )
            )
        kind, target, matches = _matcher(entry)
        if kind == "pattern":
            problem = pattern_problem(target)
            if problem:
                findings.append(
                    Finding("manifest-bad-pattern", MANIFEST_REL, f"{label}: {problem}")
                )
                continue
        hits = [rel for rel in tree.files if matches(rel)]
        if not hits:
            findings.append(
                Finding(
                    "manifest-stale-path",
                    MANIFEST_REL,
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
                        MANIFEST_REL,
                        f"{label}: decision_record {number!r} does not exist",
                    )
                )
            elif number not in rows:
                findings.append(
                    Finding(
                        "manifest-unindexed-record",
                        MANIFEST_REL,
                        f"{label}: decision_record {number!r} is not in the index",
                    )
                )
        for rel in hits:
            coverage.setdefault(rel, []).append(
                f"{entry.get('class')} / DR-{number or '????'}"
            )
            findings.extend(_corroborate(tree, rel, entry, number, label))

    for index, item in enumerate(manifest.get("exemptions", []) or []):
        label = f"exemptions[{index}]"
        if not isinstance(item, dict):
            findings.append(Finding("manifest-schema", MANIFEST_REL, f"{label} must be an object"))
            continue
        if bool(item.get("path")) == bool(item.get("pattern")):
            findings.append(
                Finding(
                    "exemption-field-missing",
                    MANIFEST_REL,
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
                    MANIFEST_REL,
                    f"{label}: non-empty 'rules' list and 'reason' are required",
                )
            )
            rules = rules if isinstance(rules, list) else []
        bad = [r for r in rules if r not in EXEMPTIBLE_RULES]
        if bad:
            findings.append(
                Finding(
                    "exemption-non-exemptible-rule",
                    MANIFEST_REL,
                    f"{label}: rule(s) {bad} cannot be exempted (only "
                    f"{sorted(EXEMPTIBLE_RULES)} may be); answer them with a "
                    "provenance row instead",
                )
            )
        kind, target, matches = _matcher(item)
        if kind == "pattern":
            problem = pattern_problem(target)
            if problem:
                findings.append(
                    Finding("exemption-bad-pattern", MANIFEST_REL, f"{label}: {problem}")
                )
                continue
        hits = [rel for rel in tree.files if matches(rel)]
        if not hits:
            findings.append(
                Finding(
                    "exemption-stale",
                    MANIFEST_REL,
                    f"{label}: {target!r} matches no in-scope file (stale "
                    "exemption — remove it)",
                )
            )
        for rel in hits:
            for rule in rules:
                if rule in EXEMPTIBLE_RULES:
                    exemptions.setdefault(rel, {})[rule] = reason

    for index, item in enumerate(manifest.get("scope_exclusions", []) or []):
        label = f"scope_exclusions[{index}]"
        if not isinstance(item, dict) or not item.get("prefix") or not item.get("reason"):
            findings.append(
                Finding(
                    "manifest-schema",
                    MANIFEST_REL,
                    f"{label}: 'prefix' and 'reason' are required",
                )
            )
            continue
        if not tree.excluded.get(str(item["prefix"])):
            findings.append(
                Finding(
                    "scope-exclusion-stale",
                    MANIFEST_REL,
                    f"{label}: prefix {item['prefix']!r} excludes nothing "
                    "(stale — remove it)",
                )
            )

    floor = manifest.get("scan_floor")
    if isinstance(floor, int) and len(tree.files) < floor:
        findings.append(
            Finding(
                "scan-underflow",
                MANIFEST_REL,
                f"scanned {len(tree.files)} in-scope files, below the declared "
                f"scan_floor of {floor} — the audit may have walked the wrong "
                "tree; a partial scan is not a pass",
            )
        )
    return findings, coverage, exemptions


def _corroborate(tree: Tree, rel, entry, number, label):
    """The file must show the provenance its row claims (row != reality guard)."""
    text = tree.text(rel)
    if text is None:
        return []  # binary payload: nothing to read; the row is the record
    commit = str(entry.get("pinned_commit") or "").strip()
    tokens = []
    if number:
        tokens.append(f"decision-records/{number}")
        tokens.append(f"DR-{number}")
        tokens.append(f"DR{number}")
    if len(commit) >= 8:
        tokens.append(commit[:8])
    if not tokens:
        return []
    if any(token.lower() in text.lower() for token in tokens):
        return []
    return [
        Finding(
            "manifest-uncorroborated",
            rel,
            f"{label}: the file cites neither decision record {number or '????'} "
            f"nor the pinned commit {commit[:12] or '(none given)'} — state the "
            "provenance in the file, or fix the row",
        )
    ]


# --- tripwires ----------------------------------------------------------------


def tripwire_hits(tree: Tree, rel):
    """[(rule, evidence)] for content signals of third-party carriage.

    Each signal is gated behind a cheap lowercase substring prefilter; the
    regexes below only run on files that could match. The prefilter tokens
    must stay a SUPERSET of what each regex can match, or the rule silently
    stops firing — `--negative-control` is what catches that mistake.
    """
    hits = []
    suffix = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel.rsplit("/", 1)[-1] else ""
    if suffix in UPSTREAM_ASSET_EXTS:
        hits.append(("upstream-asset-extension", f"extension {suffix}"))
    if suffix in FOREIGN_SOURCE_EXTS:
        hits.append(("foreign-source-language", f"extension {suffix}"))
    text = tree.text(rel)
    if text is None:
        return hits
    low = tree.lower(rel)
    if rel not in OWN_LICENSE_PATHS:
        for name, prefilter, regex in FOREIGN_LICENSE_BODY_RES:
            if prefilter not in low:
                continue
            match = regex.search(text)
            if match:
                hits.append(("foreign-license-text", f"{name}: {_snippet(text, match)}"))
                break
        if "spdx-license-identifier" in low:
            spdx = SPDX_RE.search(text)
            if spdx and spdx.group(1).strip().lower() != OWN_SPDX:
                # Label assembled from fragments (see the fixture note below).
                hits.append(
                    (
                        "foreign-license-text",
                        "SPDX-License" + "-Identifier tag: " + spdx.group(1),
                    )
                )
        if any(token in low for token in COPYRIGHT_PREFILTERS):
            copyright_match = COPYRIGHT_RE.search(text)
            if copyright_match and not OWN_HOLDER_RE.search(
                text[max(0, copyright_match.start() - 120) : copyright_match.end() + 120]
            ):
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


def check_tripwires(tree: Tree, coverage, exemptions):
    findings = []
    counts = {rule: 0 for rule in TRIPWIRE_RULES}
    for rel in tree.files:
        for rule, evidence in tripwire_hits(tree, rel):
            counts[rule] += 1
            if rel in coverage:
                continue
            reason = exemptions.get(rel, {}).get(rule)
            if reason:
                continue
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
    return findings, counts


# --- audit driver -------------------------------------------------------------


def audit(root: Path):
    root = Path(root)
    manifest, findings = load_manifest(root)
    if manifest is None:
        manifest = {"entries": [], "exemptions": [], "scope_exclusions": []}
    tree = Tree(root, scope_exclusion_prefixes(manifest))
    records, record_findings = parse_records(tree)
    rows, index_findings = parse_index(tree)
    findings = list(findings) + record_findings + index_findings
    findings += check_index(records, rows)
    findings += check_citations(tree, records, rows)
    manifest_findings, coverage, exemptions = check_manifest(tree, manifest, records, rows)
    findings += manifest_findings
    tripwire_findings, tripwire_counts = check_tripwires(tree, coverage, exemptions)
    findings += tripwire_findings
    stats = {
        "files_scanned": len(tree.files),
        "files_excluded": sum(len(v) for v in tree.excluded.values()),
        "exclusions": {k: len(v) for k, v in sorted(tree.excluded.items())},
        "records": len(records),
        "index_rows": len(rows),
        "provenance_rows": len(manifest.get("entries", []) or []),
        "files_covered_by_rows": len(coverage),
        "exemptions": len(manifest.get("exemptions", []) or []),
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


# --- negative control (self-test) --------------------------------------------


SKELETON_RECORD = """# 0001: Example quoted constants (synthetic)

- **Status**: ratified
- **Date**: 2026-01-01

## Decision

Synthetic record used only by the provenance audit's negative control.
"""

SKELETON_INDEX = """# Decision records

## Index

| Number | Title | Status | Date |
|---|---|---|---|
| [0001](0001-example.md) | Example quoted constants (synthetic) | ratified | 2026-01-01 |
"""

SKELETON_CARRIER = '''"""Synthetic carrier.

Constants below are QUOTED as data from
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71;
licensing decision: decision-records/0001-example.md.
"""

TABLE = [1, 2, 3]
'''


def _write(root: Path, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def build_skeleton(root: Path):
    """A minimal tree that must audit clean."""
    _write(root, f"{RECORD_DIR_REL}/0001-example.md", SKELETON_RECORD)
    _write(root, INDEX_REL, SKELETON_INDEX)
    _write(root, "model/carrier.py", SKELETON_CARRIER)
    _write(root, "docs/plain.md", "A document with no third-party content.\n")
    _write(
        root,
        MANIFEST_REL,
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "scan_floor": 1,
                "scope_exclusions": [],
                "entries": [
                    {
                        "path": "model/carrier.py",
                        "class": "quoted-constants",
                        "content": "synthetic TABLE",
                        "upstream": "synthetic upstream",
                        "pinned_commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
                        "upstream_license": "GPL-3.0-or-later",
                        "decision_record": "0001",
                    }
                ],
                "exemptions": [],
            },
            indent=2,
        )
        + "\n",
    )


# NOTE — the fixture strings below are deliberately assembled from fragments.
# If this file contained a contiguous foreign license body, copyright line or
# decision-record citation, the audit would (correctly) flag its own source as
# unattributed carriage — and the only ways out would be to exempt a
# non-exemptible rule or to special-case the audit's own path, both of which
# would punch a hole in the rule set. Assembling at runtime keeps the rules
# intact and the synthetic violations byte-identical to the real thing. Do not
# "tidy" these into single literals.
FIXTURE_GPL_BODY = (
    '"""Helper.\n\n'
    + "GNU GENERAL "
    + "PUBLIC LICENSE Version 3\n"
    + "Copy"
    + "right (C) 20"
    + "16 Somebody Else\n"
    + "This program is "
    + 'free software.\n"""\n'
)
FIXTURE_RECORD_CITATION = "Licensing: see " + "decision-records/" + "0099.\n"
FIXTURE_TRANSCRIBED = (
    '"""Table '
    + "transcribed from "
    + "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71.\n"
    + '"""\n\nT = [4, 5, 6]\n'
)


def _patch_manifest(root: Path, mutate):
    path = root / MANIFEST_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _controls():
    """{rule: (description, mutator)} — one deliberate violation per rule."""

    def add_second_record(root, indexed):
        _write(
            root,
            f"{RECORD_DIR_REL}/0002-second.md",
            "# 0002: Second (synthetic)\n\n- **Status**: proposed\n"
            "- **Date**: 2026-01-02\n",
        )
        if indexed:
            path = root / INDEX_REL
            path.write_text(
                path.read_text(encoding="utf-8")
                + "| [0002](0002-second.md) | Second (synthetic) | proposed | 2026-01-02 |\n",
                encoding="utf-8",
            )

    controls = {
        "foreign-license-text": (
            "an unattributed file carrying a foreign license body",
            lambda root: _write(root, "model/pasted_helper.py", FIXTURE_GPL_BODY),
        ),
        "upstream-asset-extension": (
            "an undeclared upstream asset payload",
            lambda root: _write(root, "assets/Bank Sine.wt", b"\x00\x01wt payload"),
        ),
        "foreign-source-language": (
            "an undeclared foreign-language source file",
            lambda root: _write(
                root, "src/copied_filter.cpp", "float run(float x) { return x; }\n"
            ),
        ),
        "self-declared-quotation": (
            "a file admitting quotation with no provenance row",
            lambda root: _write(root, "model/undeclared_table.py", FIXTURE_TRANSCRIBED),
        ),
        "dangling-record-citation": (
            "a citation of a decision record that does not exist",
            lambda root: _write(root, "docs/claim.md", FIXTURE_RECORD_CITATION),
        ),
        "unindexed-record-citation": (
            "a citation of a record missing from the index",
            lambda root: (
                add_second_record(root, indexed=False),
                _write(root, "docs/claim2.md", "See DR-0002 for the decision.\n"),
            ),
        ),
        "index-missing-row": (
            "a decision record on disk with no index row",
            lambda root: add_second_record(root, indexed=False),
        ),
        "index-unknown-record": (
            "an index row with no record file",
            lambda root: _write(
                root,
                INDEX_REL,
                SKELETON_INDEX
                + "| [0002](0002-ghost.md) | Ghost | proposed | 2026-01-02 |\n",
            ),
        ),
        "index-duplicate-row": (
            "the same record listed twice in the index",
            lambda root: _write(
                root,
                INDEX_REL,
                SKELETON_INDEX
                + "| [0001](0001-example.md) | Example | ratified | 2026-01-01 |\n",
            ),
        ),
        "index-status-mismatch": (
            "an index status keyword that no longer matches the record",
            lambda root: _write(
                root, INDEX_REL, SKELETON_INDEX.replace("| ratified |", "| PROPOSED |")
            ),
        ),
        "index-date-mismatch": (
            "an index date that no longer matches the record",
            lambda root: _write(
                root, INDEX_REL, SKELETON_INDEX.replace("2026-01-01 |", "2026-02-02 |")
            ),
        ),
        "index-number-gap": (
            "a gap in the decision-record numbering (a deleted record)",
            lambda root: (
                _write(
                    root,
                    f"{RECORD_DIR_REL}/0003-third.md",
                    "# 0003: Third (synthetic)\n\n- **Status**: proposed\n"
                    "- **Date**: 2026-01-03\n",
                ),
                _write(
                    root,
                    INDEX_REL,
                    SKELETON_INDEX
                    + "| [0003](0003-third.md) | Third | proposed | 2026-01-03 |\n",
                ),
            ),
        ),
        "record-status-unrecognized": (
            "a record whose status keyword is outside the vocabulary",
            lambda root: _write(
                root,
                f"{RECORD_DIR_REL}/0001-example.md",
                SKELETON_RECORD.replace("ratified", "maybe-someday"),
            ),
        ),
        "record-header-missing": (
            "a record with no parseable Status/Date header",
            lambda root: _write(
                root, f"{RECORD_DIR_REL}/0001-example.md", "# 0001: no header\n"
            ),
        ),
        "manifest-missing": (
            "a missing provenance manifest",
            lambda root: (root / MANIFEST_REL).unlink(),
        ),
        "manifest-schema": (
            "a manifest with an unknown schema_version",
            lambda root: _patch_manifest(root, lambda d: d.update(schema_version=99)),
        ),
        "manifest-field-missing": (
            "a provenance row missing required provenance fields",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].pop("upstream_license")
            ),
        ),
        "manifest-unknown-class": (
            "a provenance row with an unknown class",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"class": "vibes"})
            ),
        ),
        "manifest-stale-path": (
            "a provenance row whose file is gone",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"path": "model/deleted.py"})
            ),
        ),
        "manifest-bad-pattern": (
            "a blanket provenance pattern",
            lambda root: _patch_manifest(
                root,
                lambda d: d["entries"].append(
                    {
                        "pattern": "model/**",
                        "class": "quoted-constants",
                        "content": "everything",
                        "upstream": "x",
                        "upstream_license": "GPL-3.0-or-later",
                        "decision_record": "0001",
                    }
                ),
            ),
        ),
        "manifest-missing-record": (
            "a provenance row citing a nonexistent decision record",
            lambda root: _patch_manifest(
                root, lambda d: d["entries"][0].update({"decision_record": "0099"})
            ),
        ),
        "manifest-unindexed-record": (
            "a provenance row citing an unindexed decision record",
            lambda root: (
                add_second_record(root, indexed=False),
                _patch_manifest(
                    root, lambda d: d["entries"][0].update({"decision_record": "0002"})
                ),
            ),
        ),
        "manifest-uncorroborated": (
            "a provenance row the file itself does not corroborate",
            lambda root: _write(
                root, "model/carrier.py", "TABLE = [1, 2, 3]  # no provenance stated\n"
            ),
        ),
        "exemption-field-missing": (
            "an exemption with no reason",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {"path": "docs/plain.md", "rules": ["self-declared-quotation"]}
                ),
            ),
        ),
        "exemption-non-exemptible-rule": (
            "an exemption of a non-exemptible rule",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "path": "docs/plain.md",
                        "rules": ["foreign-license-text"],
                        "reason": "trying to wave away a GPL header",
                    }
                ),
            ),
        ),
        "exemption-stale": (
            "an exemption matching no file",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "path": "docs/gone.md",
                        "rules": ["self-declared-quotation"],
                        "reason": "stale",
                    }
                ),
            ),
        ),
        "exemption-bad-pattern": (
            "a blanket exemption pattern",
            lambda root: _patch_manifest(
                root,
                lambda d: d["exemptions"].append(
                    {
                        "pattern": "docs/**",
                        "rules": ["self-declared-quotation"],
                        "reason": "blanket",
                    }
                ),
            ),
        ),
        "scope-exclusion-stale": (
            "a scope exclusion that excludes nothing",
            lambda root: _patch_manifest(
                root,
                lambda d: d["scope_exclusions"].append(
                    {"prefix": "vendor-nothing/", "reason": "stale"}
                ),
            ),
        ),
        "scan-underflow": (
            "a scan that saw fewer files than the declared floor",
            lambda root: _patch_manifest(root, lambda d: d.update(scan_floor=10_000)),
        ),
    }
    return controls


def run_negative_control(verbose=True):
    """Every rule must fire on a deliberate violation. Returns exit code."""
    controls = _controls()
    missing = sorted(set(RULES) - set(controls))
    results = []
    ok = True

    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean"
        clean.mkdir()
        build_skeleton(clean)
        findings, _ = audit(clean)
        clean_ok = not findings
        ok = ok and clean_ok
        results.append(
            (
                "(clean skeleton)",
                "PASS" if clean_ok else "FAIL",
                "audits clean"
                if clean_ok
                else "false alarm on a clean tree: "
                + "; ".join(f"{f.rule}@{f.path}" for f in findings),
            )
        )

        for rule in sorted(controls):
            description, mutate = controls[rule]
            case = Path(tmp) / f"case-{rule}"
            case.mkdir()
            build_skeleton(case)
            mutate(case)
            findings, _ = audit(case)
            fired = [f for f in findings if f.rule == rule]
            if fired:
                results.append((rule, "PASS", f"{description} -> {fired[0].path}"))
            else:
                ok = False
                results.append(
                    (
                        rule,
                        "FAIL",
                        f"{description} -> rule did NOT fire (found: "
                        + (", ".join(sorted({f.rule for f in findings})) or "nothing")
                        + ")",
                    )
                )

    if verbose:
        print("negative control: one deliberate violation per rule\n")
        for name, verdict, detail in results:
            print(f"  {verdict:4}  {name}")
            print(f"        {detail}")
        if missing:
            print(
                "\nFAIL: rules with no negative control (add one before merging): "
                + ", ".join(missing)
            )
        print()
        if ok and not missing:
            print(
                f"PASS: all {len(controls)} rules fired on their deliberate "
                "violation, and the clean control tree produced no findings."
            )
        else:
            print("FAIL: the audit's own failure detection is not intact.")
        print(CAVEAT)
    return 0 if (ok and not missing) else 2


# --- cli ---------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root", default=str(REPO_ROOT), help="tree to audit (default: this repository)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    parser.add_argument(
        "--negative-control",
        action="store_true",
        help="self-test: every rule must fire on a deliberate violation",
    )
    parser.add_argument(
        "--limits", action="store_true", help="print the declared detection limits"
    )
    args = parser.parse_args(argv)

    if args.limits:
        print(__doc__)
        return 0
    if args.negative_control:
        return run_negative_control()

    try:
        findings, stats = audit(Path(args.root))
    except AuditError as exc:
        print(f"NOT_RUN: provenance audit could not run: {exc}")
        print(CAVEAT)
        return 2
    report(findings, stats, args.root, as_json=args.json)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
