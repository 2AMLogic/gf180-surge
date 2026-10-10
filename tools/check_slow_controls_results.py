#!/usr/bin/env python3
"""Gate the slow-controls workflow's JUnit report (stdlib only, #415).

Reads tests/negative_controls_registry.json and the JUnit XML of
``NC_LIVE_SLOW=1 pytest tests/test_negative_controls_live.py``.

FAIL (exit 1) when any of these is not an executed, non-skipped testcase:
  * ``test_control_script_executes_and_all_controls_fail_their_checks[<s>]``
    for every registry script whose status is LIVE (slow or not);
  * ``test_failure_control_budget_noop_is_rejected_despite_exit_zero``.
Registry rows whose status is not LIVE (NOT_RUN:needs-oracle) may be skipped;
they are reported as NOT_RUN and never counted as passes. A failed/errored
case is also reported as FAIL here. Missing report or missing case -> FAIL.
Exit 2 for usage errors.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

EXEC = "test_control_script_executes_and_all_controls_fail_their_checks"
BUDGET = "test_failure_control_budget_noop_is_rejected_despite_exit_zero"
REGISTRY = Path(__file__).resolve().parents[1] / "tests" / "negative_controls_registry.json"


def _outcomes(report: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for tc in ET.parse(report).getroot().iter("testcase"):
        if tc.find("failure") is not None or tc.find("error") is not None:
            st = "FAIL"
        elif tc.find("skipped") is not None:
            st = "NOT_RUN"
        else:
            st = "PASS"
        out[tc.get("name", "")] = st
    return out


def evaluate(registry: dict, outcomes: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return (report lines, failures)."""
    lines, bad = [], []
    wanted = [(f"{EXEC}[{n}]", f"{n} ({e['status']})", e["status"] == "LIVE")
              for n, e in sorted(registry["scripts"].items())]
    wanted.append((BUDGET, "profile-budget no-op failure control", True))
    for key, label, must in wanted:
        st = outcomes.get(key)
        if st is None:
            st = "MISSING"
        if must:
            if st == "PASS":
                lines.append(f"LIVE        PASS     {label}")
            else:
                lines.append(f"LIVE        FAIL     {label}: {st}")
                bad.append(f"{label}: {st}")
        else:
            if st == "FAIL":
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
        outcomes = _outcomes(Path(argv[1]))
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError, ValueError) as exc:
        print(f"FAIL: cannot read report/registry: {exc}", file=sys.stderr)
        return 1
    lines, bad = evaluate(registry, outcomes)
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
