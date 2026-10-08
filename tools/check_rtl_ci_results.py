#!/usr/bin/env python3
"""Validate a pytest JUnit XML report for the ``rtl-sim`` CI job (stdlib only).

Two independent checks, both of which must pass:

1. Skip policy (#345). Fails when the report is missing or malformed, when
   zero tests were collected, or when any skipped case carries a
   simulator-dependent reason (``iverilog`` or ``vvp``, case-insensitive).
   Unrelated intentional skips are reported as NOT_RUN but do not fail.

2. Required-case coverage (#356). A committed inventory
   (``tests/rtl_sim_required_cases.txt`` by default) lists pytest node IDs of
   simulator-dependent cases. Each entry must appear in the pytest collection
   listing for the same checkout (``--collected``; a renamed or deselected
   test leaves a stale entry, which fails) and exactly once in the JUnit
   report, not skipped -- regardless of the skip reason's wording. Node IDs
   are mapped to JUnit ``(classname, name)`` with pytest's own mangling; any
   ambiguity (two node IDs mapping to one identity, duplicate testcases,
   duplicate or malformed inventory lines) fails rather than guessing.

This checker establishes execution coverage only. pytest's own exit status
(agreement) must be preserved separately by the caller (the CI step gates
both); a failed or errored required case counts as present and executed
here and is left to that independent gate.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SIM_RE = re.compile(r"iverilog|vvp", re.IGNORECASE)
DEFAULT_INVENTORY = (
    Path(__file__).resolve().parents[1] / "tests" / "rtl_sim_required_cases.txt"
)
# tests/<path>.py::<name>[::<name>...] with an optional trailing [param id];
# no whitespace anywhere.
NODEID_RE = re.compile(
    r"^tests/[^\s:\[\]]+\.py(::[A-Za-z_][A-Za-z0-9_]*)+(\[[^\s]*\])?$"
)


class ReportError(Exception):
    pass


def junit_identity(nodeid: str) -> tuple[str, str]:
    """pytest's ``mangle_test_address``: nodeid -> (classname, name)."""
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


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
    # identity -> list of outcomes ("skipped" or "executed"), in report order.
    cases: dict[tuple[str, str], list[str]] = {}
    for case in root.iter("testcase"):
        total += 1
        sk = case.find("skipped")
        ident = (case.get("classname", ""), case.get("name", ""))
        name = f"{ident[0]}::{ident[1]}"
        cases.setdefault(ident, []).append("executed" if sk is None else "skipped")
        if sk is None:
            executed += 1
            continue
        # The message attribute is the skip reason; the element text also
        # embeds the file path, which must not influence the match.
        reason = sk.get("message") or (sk.text or "").strip()
        skipped.append((name, reason, bool(SIM_RE.search(reason))))
    return {"total": total, "executed": executed, "skipped": skipped, "cases": cases}


def load_inventory(path: str) -> tuple[list[str], list[str]]:
    """Return (entries, errors). Comments/blank lines ignored."""
    try:
        text = Path(path).read_text()
    except OSError as exc:
        return [], [f"inventory unreadable: {path}: {exc}"]
    entries: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not NODEID_RE.match(line):
            errors.append(f"malformed inventory entry (line {lineno}): {line!r}")
            continue
        if line in seen:
            errors.append(f"duplicate inventory entry (line {lineno}): {line}")
            continue
        seen.add(line)
        entries.append(line)
    if not entries and not errors:
        errors.append(f"inventory is empty: {path}")
    return entries, errors


def load_collected(path: str) -> tuple[list[str], list[str]]:
    """Parse ``pytest --collect-only -q`` output: node-ID lines contain '::'."""
    try:
        text = Path(path).read_text()
    except OSError as exc:
        return [], [f"collection listing unreadable: {path}: {exc}"]
    ids = [ln.strip() for ln in text.splitlines() if "::" in ln and " " not in ln.strip()]
    errors = []
    if not ids:
        errors.append(f"collection listing has no node IDs: {path}")
    dups = sorted({i for i in ids if ids.count(i) > 1})
    for d in dups:
        errors.append(f"duplicate node ID in collection listing: {d}")
    return ids, errors


def check_coverage(report: dict, inventory: list[str], collected: list[str]) -> dict:
    """Reconcile inventory vs collection vs JUnit; return counts + failures."""
    failures: list[str] = []
    collected_set = set(collected)
    # Identity map over everything collected, to detect mangling collisions.
    by_ident: dict[tuple[str, str], list[str]] = {}
    for nid in collected:
        by_ident.setdefault(junit_identity(nid), []).append(nid)
    inv_ident: dict[tuple[str, str], list[str]] = {}
    for nid in inventory:
        inv_ident.setdefault(junit_identity(nid), []).append(nid)

    counts = {"required": len(inventory), "collected": 0, "present": 0,
              "executed": 0, "skipped": 0, "missing": 0}
    for nid in inventory:
        ident = junit_identity(nid)
        if nid not in collected_set:
            failures.append(f"stale inventory entry (not in pytest collection): {nid}")
        else:
            counts["collected"] += 1
        clash = sorted(set(by_ident.get(ident, [])) | set(inv_ident[ident]))
        if len(clash) > 1:
            failures.append(
                f"ambiguous JUnit identity {ident[0]}::{ident[1]} for node IDs: "
                + ", ".join(clash))
            continue
        outcomes = report["cases"].get(ident, [])
        if not outcomes:
            counts["missing"] += 1
            failures.append(f"required case missing from JUnit report: {nid}")
            continue
        counts["present"] += 1
        if len(outcomes) > 1:
            failures.append(
                f"required case appears {len(outcomes)} times in JUnit report: {nid}")
            continue
        if outcomes[0] == "skipped":
            counts["skipped"] += 1
            failures.append(f"required case skipped: {nid}")
        else:
            counts["executed"] += 1
    return {"counts": counts, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("junit_xml")
    ap.add_argument("--inventory", default=str(DEFAULT_INVENTORY),
                    help="committed required-case inventory (default: %(default)s)")
    ap.add_argument("--collected", required=True,
                    help="output of `pytest --collect-only -q` for the same invocation")
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

    rc = 0
    if r["total"] == 0:
        print("FAIL: zero tests collected", file=sys.stderr)
        rc = 1
    for name, reason, _ in sim:
        print(f"FAIL: simulator-dependent skip: {name}: {reason}", file=sys.stderr)
        rc = 1

    inventory, inv_err = load_inventory(args.inventory)
    collected, col_err = load_collected(args.collected)
    for e in inv_err + col_err:
        print(f"FAIL: {e}", file=sys.stderr)
    if inv_err or col_err:
        print("required-case coverage: NO_VERDICT (inventory/collection invalid)")
        return 1
    cov = check_coverage(r, inventory, collected)
    c = cov["counts"]
    print(f"inventory: {args.inventory}")
    print(f"required: {c['required']}")
    print(f"required in collection: {c['collected']}")
    print(f"required present in report: {c['present']}")
    print(f"required executed: {c['executed']}")
    print(f"required skipped: {c['skipped']}")
    print(f"required missing: {c['missing']}")
    for f in cov["failures"]:
        print(f"FAIL: {f}", file=sys.stderr)
    if cov["failures"]:
        rc = 1
    if rc == 0:
        print("PASS: no simulator-dependent skips; all required cases executed")
    return rc


if __name__ == "__main__":
    sys.exit(main())
