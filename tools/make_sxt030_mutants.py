#!/usr/bin/env python3
"""Generate the SXT-030 (#316) committed negative-control mutants of
rtl/instrumentation/ext_mem_instr.sv.

Each mutant = an NC banner (ending in its own timescale line) + the real
source with its timescale line removed and the listed exact line
replacements applied (each `old` must occur exactly once). `--check` exits
non-zero if any committed mutant differs from what this script would write,
so a mutant cannot silently drift from the real design it mutates.

Original to this repository (Apache-2.0).
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RTL_DIR = os.path.join(REPO, "rtl", "instrumentation")
SRC = os.path.join(RTL_DIR, "ext_mem_instr.sv")
TIMESCALE = "`timescale 1ns/1ps\n"

HOLD = "{out_l, out_r} <= miss ? {out_l, out_r} : {smp_l, smp_r};"
SILENCE = "{out_l, out_r} <= miss ? 32'd0 : {smp_l, smp_r};"
COUNT = "wire stall_count = miss;"
NO_COUNT = "wire stall_count = 1'b0;"
LATCH = "win_l <= svc_window;"
NO_LATCH = "win_l <= SVC_WINDOW_NOMINAL;"

MUTANTS = {
    "ext_mem_instr_silence_mutant.sv": {
        "replacements": [(HOLD, SILENCE)],
        "what": ("on a deadline miss the output is forced to SILENCE "
                 "instead of holding the previous frame's sample"),
        "must": ("FAIL the NC-1 gate (over-subscribed output is silent: "
                 "the held-sample policy is violated)"),
    },
    "ext_mem_instr_zero_counters_mutant.sv": {
        "replacements": [(COUNT, NO_COUNT)],
        "what": ("the stall instrumentation is stubbed to zero: "
                 "STALL_FRAMES, STALL_CYCLES_MAX, FIRST_STALL_FRAME, "
                 "OUTPUT_FAULT, stall_strobe and stall_led never fire, while "
                 "the output still degrades (held samples) on a miss"),
        "must": ("be REFUSED by the NC-1 gate as NO_VERDICT (degraded "
                 "output with STALL_FRAMES == 0), never graded PASS"),
    },
    "ext_mem_instr_silence_zero_counters_mutant.sv": {
        "replacements": [(HOLD, SILENCE), (COUNT, NO_COUNT)],
        "what": ("silence on a miss AND the stall instrumentation stubbed "
                 "to zero (silence-with-zero-counters)"),
        "must": ("be REFUSED by the NC-1 gate as NO_VERDICT; silence with "
                 "zero counters is never reportable as a pass or a stall"),
    },
    "ext_mem_instr_throttle_never_mutant.sv": {
        "replacements": [(LATCH, NO_LATCH)],
        "what": ("the M2 service-window throttle never engages: "
                 "SVC_WINDOW_LIMIT still reads back the commanded value but "
                 "every frame latches the nominal window"),
        "must": ("FAIL the NC-1 gate (the over-subscribed run shows no "
                 "witness firing: over-subscription was never achieved)"),
    },
}


def banner(name, spec):
    lines = [
        "// SXT-030 (#316) COMMITTED NEGATIVE CONTROL (do not fix in place).",
        "//",
        "// Deliberately mutated copy of rtl/instrumentation/ext_mem_instr.sv:",
    ]
    for old, new in spec["replacements"]:
        lines.append("//   `%s`" % old)
        lines.append("//     -> `%s`" % new)
    lines += [
        "// Effect: %s." % spec["what"],
        "// Under tools/sxt030_stall_bench.py this build MUST %s." % spec["must"],
        "// If it ever grades PASS, the bench/gate is broken and must be",
        "// repaired before any SXT-030 instrumentation claim stands.",
        "//",
        "// Regenerate with: python3 tools/make_sxt030_mutants.py",
        "",
    ]
    return "\n".join(lines) + "\n" + TIMESCALE


def render(name, src=None):
    if src is None:
        with open(SRC) as f:
            src = f.read()
    spec = MUTANTS[name]
    assert src.count(TIMESCALE) == 1
    body = src.replace(TIMESCALE, "", 1)
    for old, new in spec["replacements"]:
        if body.count(old) != 1:
            raise ValueError("%s: mutation site %r occurs %d times"
                             % (name, old, body.count(old)))
        body = body.replace(old, new, 1)
    return banner(name, spec) + body


def main(argv):
    check = "--check" in argv
    bad = 0
    for name in MUTANTS:
        path = os.path.join(RTL_DIR, name)
        want = render(name)
        if check:
            have = open(path).read() if os.path.exists(path) else None
            if have != want:
                print("STALE: %s" % os.path.relpath(path, REPO))
                bad += 1
        else:
            with open(path, "w") as f:
                f.write(want)
            print("wrote %s" % os.path.relpath(path, REPO))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
