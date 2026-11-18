#!/usr/bin/env python3
"""#723 -- the shared non-vacuity guard itself refuses a vacuous scan.

What this pins, and what it does NOT:

  * PINS: `tests/evidence_scan.py`'s `scanned()` raises on an empty scan
    (default floor `at_least=1`), on a scan shorter than a declared
    `at_least` floor, and on a scan either shorter or longer than a
    declared `exactly` count; that `exactly` wins when both bounds are
    given; that a passing scan returns the materialized list; and that the
    failure message names the records, the scanned location, the found and
    expected counts, and the vacuous-PASS rationale.
  * DOES NOT: hash the helper's bytes (no committed record covers them),
    or detect a subtle weakening that preserves every raise/no-raise
    answer exercised here. This is the self-test half of #723's gap: a
    silently weakened helper now fails a committed test instead of passing
    silently. The helper's 11 guard call sites stay covered by their own
    suites.

Failure control (the issue's mutation measurement): force `ok = True` in
a scratch copy of the helper and every raises-assertion below goes red;
restore and the module is green again. On the unmutated helper with scans
forced empty, the guarded suites still fail (9 failed, 1 passed on #697
head f8c0ebd) -- this module does not change that, it only closes the
"10 passed" silence.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evidence_scan import scanned  # noqa: E402


def test_empty_scan_raises_under_the_default_floor():
    # neither bound given: the guard is `at_least=1`
    with pytest.raises(AssertionError, match="expected at least 1"):
        scanned([], what="records")


def test_short_scan_raises_against_a_declared_floor():
    with pytest.raises(AssertionError, match="expected at least 2"):
        scanned(["a"], what="records", at_least=2)
    # the boundary itself passes: exactly the floor is not short
    assert scanned(["a", "b"], what="records", at_least=2) == ["a", "b"]


def test_long_scan_raises_against_an_exact_count():
    with pytest.raises(AssertionError, match="expected exactly 2"):
        scanned(["a", "b", "c"], what="records", exactly=2)


def test_short_scan_raises_against_an_exact_count():
    with pytest.raises(AssertionError, match="expected exactly 2"):
        scanned(["a"], what="records", exactly=2)
    assert scanned(["a", "b"], what="records", exactly=2) == ["a", "b"]


def test_exact_wins_when_both_bounds_are_given():
    # one record: satisfies `exactly=1`, violates `at_least=2`
    assert scanned(["a"], what="records", at_least=2, exactly=1) == ["a"]
    with pytest.raises(AssertionError, match="expected exactly 1"):
        scanned(["a", "b"], what="records", at_least=1, exactly=1)


def test_passing_scan_returns_the_materialized_list():
    gen = (str(i) for i in range(3))
    out = scanned(gen, what="records", at_least=3)
    assert isinstance(out, list)
    assert out == ["0", "1", "2"]


def test_message_names_what_where_counts_and_the_vacuous_pass_rationale():
    with pytest.raises(AssertionError) as exc:
        scanned([], what="committed records", where="/tmp/nowhere")
    msg = str(exc.value)
    assert "non-vacuity guard failed: committed records" in msg
    assert "(scanning /tmp/nowhere)" in msg
    assert "found 0 record(s)" in msg
    assert "vacuous PASS" in msg
    # an empty scan has nothing to echo
    assert "scanned: [" not in msg


def test_small_nonempty_failure_echoes_the_scanned_records():
    with pytest.raises(AssertionError) as exc:
        scanned(["a", "b"], what="records", at_least=3)
    assert "found 2 record(s)" in str(exc.value)
    assert "scanned: ['a', 'b']" in str(exc.value)
