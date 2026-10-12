#!/usr/bin/env python3
"""Gate the slow-controls workflow's JUnit report (stdlib only, #415).

Reads tests/negative_controls_registry.json and the JUnit XML of
``NC_LIVE_SLOW=1 pytest tests/test_negative_controls_live.py``.

Required cases are looked up by full JUnit identity ``(classname, name)``,
never by name alone (#463): pytest mangles the node ID
``tests/test_negative_controls_live.py::<name>`` into classname
``tests.test_negative_controls_live`` (verified against a collected
--junitxml sample), so a same-name testcase from any other module is a
wrong-module substitute and never satisfies a required row. Each required
identity must appear exactly once and be an executed, non-skipped PASS;
duplicate required identities are rejected in any report order rather than
selecting an outcome by position.

FAIL (exit 1) when any of these is not an executed, non-skipped testcase:
  * ``test_control_script_executes_and_all_controls_fail_their_checks[<s>]``
    for every registry script whose status is LIVE (slow or not);
  * ``test_failure_control_budget_noop_is_rejected_despite_exit_zero``.
Registry rows whose status is not LIVE (NOT_RUN:needs-oracle) may be skipped;
they are reported as NOT_RUN and never counted as passes. A failed/errored
case is also reported as FAIL here. Missing report or missing case, duplicate
required case, wrong-module substitute, or an unsupported JUnit root -> FAIL.
Exit 2 for usage errors. pytest's own exit status stays a separate,
independent gate in the caller (.github/workflows/slow-controls.yml).
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

EXEC = "test_control_script_executes_and_all_controls_fail_their_checks"
BUDGET = "test_failure_control_budget_noop_is_rejected_despite_exit_zero"
# node ID tests/test_negative_controls_live.py::<name> -> this classname
# (pytest's mangle_test_address; sampled from this repo's own --junitxml
# output). A required case under any other classname does not count.
EXPECTED_CLASSNAME = "tests.test_negative_controls_live"
REGISTRY = Path(__file__).resolve().parents[1] / "tests" / "negative_controls_registry.json"


class ReportError(Exception):
    pass


def _outcome(tc: ET.Element) -> str:
    if tc.find("failure") is not None or tc.find("error") is not None:
        return "FAIL"
    if tc.find("skipped") is not None:
        return "NOT_RUN"
    return "PASS"


def _records(report: Path) -> dict[tuple[str, str], list[str]]:
    """JUnit XML -> (classname, name) -> outcomes, in report order."""
    root = ET.parse(report).getroot()
    if root.tag not in ("testsuites", "testsuite"):
        raise ReportError(f"unsupported root element <{root.tag}>")
    out: dict[tuple[str, str], list[str]] = {}
    for tc in root.iter("testcase"):
        ident = (tc.get("classname", ""), tc.get("name", ""))
        out.setdefault(ident, []).append(_outcome(tc))
    return out


def _identity_status(name: str, records: dict[tuple[str, str], list[str]],
                     expected_classname: str) -> str:
    """Display status of one required identity, multiplicity-aware."""
    outcomes = records.get((expected_classname, name))
    if outcomes is None:
        others = sorted({c for c, n in records
                         if n == name and c != expected_classname})
        if others:
            return ("MISSING (same name under other classname(s): "
                    + ", ".join(others) + ")")
        return "MISSING"
    if len(outcomes) > 1:
        return f"AMBIGUOUS ({len(outcomes)} report records)"
    return outcomes[0]


def evaluate(registry: dict, records: dict[tuple[str, str], list[str]],
             expected_classname: str = EXPECTED_CLASSNAME
             ) -> tuple[list[str], list[str]]:
    """Return (report lines, failures); records maps identity -> outcomes."""
    lines, bad = [], []
    wanted = [(f"{EXEC}[{n}]", f"{n} ({e['status']})", e["status"] == "LIVE")
              for n, e in sorted(registry["scripts"].items())]
    wanted.append((BUDGET, "profile-budget no-op failure control", True))
    for name, label, must in wanted:
        st = _identity_status(name, records, expected_classname)
        if must:
            if st == "PASS":
                lines.append(f"LIVE        PASS     {label}")
            else:
                lines.append(f"LIVE        FAIL     {label}: {st}")
                bad.append(f"{label}: {st}")
        elif "FAIL" in records.get((expected_classname, name), []):
            lines.append(f"NOT_RUN:needs-oracle FAIL {label}")
            bad.append(f"{label}: FAIL")
        else:
            lines.append(f"NOT_RUN     (allowed, not a pass) {label}")
    return lines, bad


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_slow_controls_results.py JUNIT_XML", file=sys.stderr)
        return 2
    try:
        records = _records(Path(argv[1]))
    except (OSError, ET.ParseError, ReportError) as exc:
        print(f"FAIL: cannot read report: {exc}", file=sys.stderr)
        return 1
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FAIL: cannot read registry: {exc}", file=sys.stderr)
        return 1
    lines, bad = evaluate(registry, records)
    print("\n".join(lines))
    if bad:
        print(f"FAIL: {len(bad)} slow-control case(s) not executed/passing:",
              file=sys.stderr)
        for b in bad:
            print(f"  - {b}", file=sys.stderr)
        return 1
    print("PASS: every LIVE control (incl. slow) executed and passed; "
          "skipped needs-oracle controls remain NOT_RUN.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
