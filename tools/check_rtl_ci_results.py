#!/usr/bin/env python3
"""Validate a pytest JUnit XML report for the ``rtl-sim`` CI job (stdlib only).

Fails (nonzero exit) when the report is missing or malformed, when zero tests
were collected, or when any skipped case carries a simulator-dependent reason
(``iverilog`` or ``vvp``, case-insensitive).  Unrelated intentional skips are
reported as NOT_RUN but do not fail.

This checker only inspects the report.  pytest's own exit status must be
preserved separately by the caller (the CI step ORs both).
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET

SIM_RE = re.compile(r"iverilog|vvp", re.IGNORECASE)


class ReportError(Exception):
    pass


def analyze(path: str) -> dict:
    try:
        root = ET.parse(path).getroot()
    except FileNotFoundError as exc:
        raise ReportError(f"report missing: {path}") from exc
    except (ET.ParseError, OSError) as exc:
        raise ReportError(f"report malformed/unreadable: {path}: {exc}") from exc
    if root.tag not in ("testsuites", "testsuite"):
        raise ReportError(f"unexpected root element <{root.tag}>")
    total = executed = 0
    skipped: list[tuple[str, str, bool]] = []
    for case in root.iter("testcase"):
        total += 1
        sk = case.find("skipped")
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        if sk is None:
            executed += 1
            continue
        # The message attribute is the skip reason; the element text also
        # embeds the file path, which must not influence the match.
        reason = sk.get("message") or (sk.text or "").strip()
        skipped.append((name, reason, bool(SIM_RE.search(reason))))
    return {"total": total, "executed": executed, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("junit_xml")
    args = ap.parse_args(argv)
    try:
        r = analyze(args.junit_xml)
    except ReportError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    sim = [s for s in r["skipped"] if s[2]]
    other = [s for s in r["skipped"] if not s[2]]
    print(f"total collected: {r['total']}")
    print(f"executed (not skipped): {r['executed']}")
    print(f"skipped: {len(r['skipped'])}")
    print(f"simulator-dependent skipped: {len(sim)}")
    for name, reason, _ in other:
        print(f"NOT_RUN (unrelated skip): {name}: {reason}")
    if r["total"] == 0:
        print("FAIL: zero tests collected", file=sys.stderr)
        return 1
    if sim:
        for name, reason, _ in sim:
            print(f"FAIL: simulator-dependent skip: {name}: {reason}", file=sys.stderr)
        return 1
    print("PASS: no simulator-dependent skips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
