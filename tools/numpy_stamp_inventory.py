#!/usr/bin/env python3
"""Enumerate every committed NumPy version stamp under reports/ (issue #373).

Read-only. The committed inventory `docs/numpy-stamp-inventory.md` classifies
each record that stamps a NumPy version as Live / Historical provenance /
Declared cross-environment; `--check` fails when a stamp exists that the
inventory does not list (a silently missing row), when a listed reports/ path
no longer stamps (a stale row), or when a row carries a class outside the
three defined ones. It never compares an installed NumPy version against a
stamp and never re-grades a record.

Search domain: `reports/` only. `oracle/manifest.json` is a separate row in
the inventory (its live consumer, oracle/fetch-and-build.sh, is outside this
domain); the inventory records the repo-wide grep that shows no other domain
stamps a version.
"""

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_DIR = "reports"
DOC = os.path.join(REPO, "docs", "numpy-stamp-inventory.md")
CLASSES = ("Live", "Historical provenance", "Declared cross-environment")

# Matches the three committed stamp shapes: a JSON/text key ("numpy": "1.26.4",
# "numpy_in_pinned_python": "1.26.0", "numpy   : 1.26.4", numpy==X), a prose
# mention ("numpy 2.4.1" / "NumPy 1.26.4", including inside a runtime string
# like "3.11.16 (numpy 1.26.4)"), and an explicit null stamp ("numpy": null,
# written when the recording tool ran without numpy).
STAMP_RE = re.compile(
    r'numpy[a-z_]*"?\s*[:=]\s*"?(?P<kv>\d+\.\d+\.\d+)"?'
    r'|\bnumpy\s+(?P<prose>\d+\.\d+\.\d+)'
    r'|"numpy[a-z_]*"\s*:\s*null',
    re.IGNORECASE)

BINARY_SUFFIXES = (
    ".wav", ".gz", ".png", ".jpg", ".jpeg", ".gif", ".bin", ".so", ".pyc",
    ".zip", ".tar", ".pdf", ".ico", ".f32",
)
MAX_TEXT_BYTES = 8 * 1024 * 1024


class Stamp(object):
    __slots__ = ("path", "line", "version", "text")

    def __init__(self, path, line, version, text):
        self.path = path
        self.line = line
        self.version = version
        self.text = text

    def __repr__(self):
        return "%s:%d: %s" % (self.path, self.line, self.text)


class Row(object):
    __slots__ = ("group", "files", "version", "cls", "notes")

    def __init__(self, group, files, version, cls, notes):
        self.group = group
        self.files = frozenset(files)
        self.version = version
        self.cls = cls
        self.notes = notes


class Audit(object):
    __slots__ = ("missing", "unclassified", "stale")

    def __init__(self, missing, unclassified, stale):
        self.missing = missing
        self.unclassified = unclassified
        self.stale = stale

    @property
    def ok(self):
        return not (self.missing or self.unclassified or self.stale)


def find_stamps(root=REPO):
    """Every NumPy stamp under <root>/reports, sorted by path then line."""
    out = []
    base = os.path.join(root, SEARCH_DIR)
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in sorted(filenames):
            if name.lower().endswith(BINARY_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            try:
                if os.path.getsize(full) > MAX_TEXT_BYTES:
                    continue
                with open(full, encoding="utf-8") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            for lineno, line in enumerate(text.splitlines(), 1):
                m = STAMP_RE.search(line)
                if m:
                    version = m.group("kv") or m.group("prose") or "null"
                    out.append(Stamp(rel, lineno, version, line.strip()))
    out.sort(key=lambda s: (s.path, s.line))
    return out


def parse_inventory(text):
    """The classification table rows of the inventory markdown."""
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 5 or set(cells[0]) <= {"-", ":", " "}:
            continue
        if cells[0].lower() == "group":
            continue
        files = re.findall(r"`([^`]+)`", cells[1])
        if not files:
            continue
        vm = re.search(r"\d+\.\d+\.\d+", cells[2])
        rows.append(Row(cells[0], files, vm.group(0) if vm else "",
                        cells[3], cells[4]))
    return rows


def audit(root=REPO, doc=DOC):
    """(missing, unclassified, stale) between the tree and the inventory."""
    with open(doc, encoding="utf-8") as f:
        rows = parse_inventory(f.read())
    unclassified = [r.group for r in rows if r.cls not in CLASSES]
    listed = set()
    for r in rows:
        listed |= r.files
    found_paths = {s.path for s in find_stamps(root)}
    missing = found_paths - listed
    stale = {p for p in listed if p.startswith(SEARCH_DIR + "/")} \
        - found_paths
    return Audit(missing, unclassified, stale)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO)
    ap.add_argument("--doc", default=DOC)
    ap.add_argument("--check", action="store_true",
                    help="exit nonzero on any missing/unclassified/stale row")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable stamp list on stdout")
    args = ap.parse_args(argv)

    stamps = find_stamps(args.root)
    if args.json:
        print(json.dumps(
            [{"path": s.path, "line": s.line, "version": s.version,
              "text": s.text} for s in stamps], indent=1))
        return 0
    cur = None
    for s in stamps:
        if s.path != cur:
            cur = s.path
            print("\n%s" % s.path)
        print("  %4d  numpy %s   %s" % (s.line, s.version, s.text[:100]))
    print("\n%d stamp occurrence(s) in %d file(s) under %s/"
          % (len(stamps), len({s.path for s in stamps}), SEARCH_DIR))
    if args.check:
        result = audit(args.root, args.doc)
        if result.missing:
            print("FAIL: stamped file(s) missing from the inventory:",
                  file=sys.stderr)
            for p in sorted(result.missing):
                print("  %s" % p, file=sys.stderr)
        if result.unclassified:
            print("FAIL: row(s) without one of the three classes:",
                  file=sys.stderr)
            for g in result.unclassified:
                print("  %s" % g, file=sys.stderr)
        if result.stale:
            print("FAIL: inventory row(s) stamping nothing under %s/:"
                  % SEARCH_DIR, file=sys.stderr)
            for p in sorted(result.stale):
                print("  %s" % p, file=sys.stderr)
        if result.ok:
            print("check: inventory covers every stamp; all rows classified")
            return 0
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
