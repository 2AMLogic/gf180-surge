#!/usr/bin/env python3
"""Regenerate the committed SXT-021 negative-control mutant.

rtl/control/control_broken_mutant.sv is rtl/control/control_top.sv with ONE
constant changed (QUEUE_DEPTH 16 -> 15). Running this script must be a
no-op against the committed file (byte-identical); the comparator
(tools/compare_control_rtl.py --dut rtl/control/control_broken_mutant.sv)
must FAIL against the model — that failure IS the negative control.
"""

import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "rtl", "control", "control_top.sv")
DST = os.path.join(REPO, "rtl", "control", "control_broken_mutant.sv")

HEADER = """\
// SXT-021 COMMITTED NEGATIVE CONTROL (do not fix in place).
//
// Deliberately mutated copy of rtl/control/control_top.sv: the event-queue
// depth constant is changed from 16 to 15 (one constant). The comparator
// (tools/compare_control_rtl.py --dut <this file>) MUST FAIL against the
// SXT-021 model: queue-overflow drop records and queue-count checkpoints
// diverge (e.g. the 30-event burst fixture drops 14 words in the mutant vs
// the model's 16-deep queue). If this file ever PASSES the comparator, the
// comparator's divergence detection is broken and must be repaired before
// any RTL-vs-model equality claim stands.
//
// Regenerate with: python3 tools/make_control_mutant.py

`timescale 1ns/1ps
"""


def main():
    src = open(SRC).read()
    mut = src.replace("parameter int QUEUE_DEPTH = 16,",
                      "parameter int QUEUE_DEPTH = 15,")
    if mut == src:
        raise SystemExit("mutation anchor not found in control_top.sv")
    body = mut.replace("`timescale 1ns/1ps\n", "", 1)
    current = open(DST).read() if os.path.exists(DST) else None
    if current == HEADER + body:
        print("control_broken_mutant.sv already up to date (byte-identical)")
    else:
        open(DST, "w").write(HEADER + body)
        print("control_broken_mutant.sv regenerated (content changed)")


if __name__ == "__main__":
    main()
