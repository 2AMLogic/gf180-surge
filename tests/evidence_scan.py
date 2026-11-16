"""Shared non-vacuity guard for committed-evidence scans in this suite.

A loop that asserts over a directory listing silently PASSES when the
scanned directory goes empty or its filter stops matching: the test then
reports coverage it never inspected. The rule (established for the
sweep-t60 declared case set in #456, applied per site with a different
spelling each time until #683 folded them onto this helper) is that
every committed-evidence scan refuses an empty -- or
shorter/longer-than-declared -- result, with the scanned location and
the expected count in the message. A future scan that skips the guard
is a visible diff against this shared idiom instead of an invisible
omission.

Usage -- `scanned()` materializes the iterable, enforces the declared
floor (or exact count), and returns the list, so call sites keep their
ordinary loops:

    for name in scanned(sorted(os.listdir(d)), what="...",
                        where=d, exactly=3):
        ...

With neither bound given the guard is `at_least=1`. Prefer a count the
owning leaf actually declares; never invent one.
"""


def scanned(items, *, what, where=None, at_least=None, exactly=None):
    """Materialize `items`, refusing an empty or out-of-range scan result.

    `what` names the records the scan claims to inspect; `where` is the
    scanned path (or a short description of it), echoed in the failure
    message. When both bounds are given `exactly` wins. Returns the
    list, so the caller's loop iterates exactly the objects it would
    have seen before the guard.
    """
    found = list(items)
    n = len(found)
    if exactly is not None:
        expect, ok = f"exactly {exactly}", n == exactly
    elif at_least is not None:
        expect, ok = f"at least {at_least}", n >= at_least
    else:
        expect, ok = "at least 1", n >= 1
    assert ok, (
        f"non-vacuity guard failed: {what}"
        + (f" (scanning {where})" if where else "")
        + f": found {n} record(s), expected {expect} -- a vacuous PASS "
          "over committed evidence that is missing, moved, or no longer "
          "matched by the scan filter"
        + (f"; scanned: {found[:8]}" if 0 < n <= 8 else ""))
    return found
