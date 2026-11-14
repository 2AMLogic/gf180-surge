#!/usr/bin/env python3
"""Regenerate the committed SXT-021 negative-control mutant.

rtl/control/control_broken_mutant.sv is rtl/control/control_top.sv with ONE
constant changed (QUEUE_DEPTH 16 -> 15). Running this script must be a
no-op against the committed file (byte-identical); the comparator
(tools/compare_control_rtl.py --dut rtl/control/control_broken_mutant.sv)
must FAIL against the model — that failure IS the negative control.

Since #623 this script declares no mutation rule of its own: the entry lives
in tools/make_rtl_mutants.py's shared table (banner kept verbatim, so the
committed bytes are unchanged), which also gates it with
`python3 tools/make_rtl_mutants.py --check` -- the committed-byte check this
script never had. This file stays as the regeneration entry point the
mutant's own banner and reports/sxt-021/EVIDENCE.md name.

Original to this repository (Apache-2.0).
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tools import make_rtl_mutants as mk  # noqa: E402

MUTANT = mk.CONTROL_MUTANT
SRC = os.path.join(REPO, mk.MUTANTS[MUTANT]["base"])
DST = os.path.join(REPO, MUTANT)
HEADER = mk.MUTANTS[MUTANT]["prefix"]


def main():
    # A lost anchor raises ValueError out of the shared table rather than
    # silently writing an un-mutated copy over the committed control.
    want = mk.render(MUTANT)
    current = open(DST).read() if os.path.exists(DST) else None
    if current == want:
        print("control_broken_mutant.sv already up to date (byte-identical)")
    else:
        mk.write(MUTANT)
        print("control_broken_mutant.sv regenerated (content changed)")


if __name__ == "__main__":
    main()
