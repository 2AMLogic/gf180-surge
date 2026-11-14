#!/usr/bin/env python3
"""Generate the SXT-030 (#316) committed negative-control mutants of
rtl/instrumentation/ext_mem_instr.sv.

Each mutant = an NC banner (ending in its own timescale line) + the real
source with its timescale line removed and the listed exact line
replacements applied (each `old` must occur exactly once). `--check` exits
non-zero if any committed mutant differs from what this script would write,
so a mutant cannot silently drift from the real design it mutates.

Since #623 that declaration is not here: the four entries live in
tools/make_rtl_mutants.py's shared table, in the `strip` composition shape
this script's rule became. The committed bytes are unchanged -- the shared
table reproduces this script's banner from each entry's own fields. What is
below is a view onto that table, kept so the names this module's consumers
use (MUTANTS, render, RTL_DIR, the mutation-site constants) and the
`--check` command reports/SXT-030/EVIDENCE.md cites keep working unchanged.

Original to this repository (Apache-2.0).
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tools import make_rtl_mutants as mk  # noqa: E402

RTL_DIR = os.path.join(REPO, mk.EXT_MEM_DIR)
SRC = os.path.join(REPO, mk.EXT_MEM_BASE)
TIMESCALE = mk.TIMESCALE

# The mutation sites in the real design, re-exported from the shared table.
HOLD = mk.EXT_MEM_HOLD
SILENCE = mk.EXT_MEM_SILENCE
COUNT = mk.EXT_MEM_COUNT
NO_COUNT = mk.EXT_MEM_NO_COUNT
LATCH = mk.EXT_MEM_LATCH
NO_LATCH = mk.EXT_MEM_NO_LATCH

# Repo-relative path of each mutant, keyed by the bare filename this module
# has always used. Order follows the shared table.
PATHS = {os.path.basename(path): path for path in mk.MUTANTS
         if mk.MUTANTS[path]["base"] == mk.EXT_MEM_BASE}

# A view onto the shared entries, not a second declaration: `replacements`
# IS the shared entry's `mutation` list.
MUTANTS = {name: {"replacements": list(mk.MUTANTS[path]["mutation"]),
                  "what": mk.MUTANTS[path]["what"],
                  "must": mk.MUTANTS[path]["must"]}
           for name, path in PATHS.items()}


def banner(name, spec=None):
    """The generated banner of one mutant (everything above the source)."""
    return mk.MUTANTS[PATHS[name]]["prefix"]


def render(name, src=None):
    """The exact bytes mutant `name` must have, as text."""
    return mk.render(PATHS[name], src)


def main(argv):
    check = "--check" in argv
    bad = 0
    for name, path in PATHS.items():
        want = render(name)
        full = os.path.join(REPO, path)
        if check:
            have = open(full).read() if os.path.exists(full) else None
            if have != want:
                print("STALE: %s" % path)
                bad += 1
        else:
            mk.write(path)
            print("wrote %s" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
