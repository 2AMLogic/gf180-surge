"""No literal per-user / per-platform absolute paths in the `tools/` runners (#677).

`tools/run_reverb_rtl.py` and `tools/compare_rtl_model_aw49.py` each passed a
literal macOS `dir="/var/folders/<user>/T/opencode"` to `tempfile.mkdtemp`, so
both runners failed before the simulator started on every other host --
`signoff/t1-item1/README.md` records the Reverb1 runner as NOT_RUN for exactly
that reason. #607/#611 fixed the same class in `tools/smoke_fx_exactness.py`
but did not cover these two.

`tests/test_oracle_default_paths.py::test_no_personal_paths_in_live_sources`
already guards this class, but over a hardcoded 7-file allowlist whose only
needle is `/Users/<name>`: it matches neither runner nor `/var/folders/`, which
is how these two slipped through. This control is therefore **glob-driven** over
the tracked sources under `tools/` rather than an allowlist, so a newly added
runner is covered without anyone remembering to enroll it.

Scope is deliberately `tools/`, not all tracked `.py`: a repo-wide scan
false-positives on `tests/test_oracle_default_paths.py`, which builds its needle
as `"/Users/" + "joseph"` and so contains the literal on purpose. The needles
below are likewise assembled by concatenation so this file never matches itself.
"""

import functools
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Assembled, never written whole, so this file is not its own counterexample.
NEEDLES = (
    "/var/" + "folders/",      # macOS per-user temp root
    "/private/" + "tmp/",      # macOS /tmp realpath
    "/Users" + "/",            # macOS home root (any user, not just one name)
)

# The two runners #677 fixed. Asserted present in the scan so the glob cannot
# silently stop reaching them and pass vacuously.
EXPECTED_COVERED = (
    "tools/compare_rtl_model_aw49.py",
    "tools/run_reverb_rtl.py",
)


@functools.lru_cache(maxsize=1)
def tracked_tool_sources():
    """Tracked `.py` files under `tools/` (the runners a stale path breaks)."""
    out = subprocess.run(["git", "-C", REPO, "ls-files", "-z", "--", "tools"],
                         capture_output=True, text=True, check=True).stdout
    return tuple(sorted(p for p in out.split("\0") if p.endswith(".py")))


def test_scan_covers_the_known_runners():
    """Coverage, reported separately from agreement: the glob reaches the files."""
    scanned = tracked_tool_sources()
    assert len(scanned) > 1, f"tools/ scan found {len(scanned)} sources; glob is broken"
    for path in EXPECTED_COVERED:
        assert path in scanned, f"{path} not covered by the tools/ scan"


def test_no_literal_absolute_paths_in_tools():
    """No tracked tools/ source hardcodes a per-user or macOS-only absolute path."""
    offenders = []
    for path in tracked_tool_sources():
        with open(os.path.join(REPO, path), encoding="utf-8") as fh:
            text = fh.read()
        for needle in NEEDLES:
            if needle in text:
                line = next((i for i, l in enumerate(text.splitlines(), 1)
                             if needle in l), 0)
                offenders.append(f"{path}:{line} contains {needle!r}")
    assert not offenders, (
        "literal absolute path(s) in tools/ -- use tempfile's platform default "
        "(honours TMPDIR) instead:\n  " + "\n  ".join(offenders))
