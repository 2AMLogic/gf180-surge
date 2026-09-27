#!/usr/bin/env python3
"""SXT-028e-sse: regenerate the RTL waveshaper ROM from the frozen generator.

The committed `rtl/effects/type-distortion-sse/ws_sse_q29.hex` is a BUILD
PRODUCT of `model/effects/type-distortion-sse/sse_tables.py`, never an
independent copy of engine data (DR-0014 clause 2, following DR-0012 clause
2). `tests/test_sxt028e_sse.py::test_ws_rom_matches_generator` asserts the
committed file is byte-for-byte what this script writes, so the ROM can
never drift into being a quoted table.

Layout (2049 words of Q2.29, one 8-digit hex word per line):
  [0    .. 1023]  wst_sine row (WaveshaperTables.h)         1024 words
  [1024 .. 2048]  LUTBase<1024, FuzzTable<1>>::data          1025 words

Original to this repository (Apache-2.0).
"""

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))

from sse_tables import rom_words, ROM_WORDS, table_digest  # noqa: E402

DEFAULT = os.path.join(REPO, "rtl", "effects", "type-distortion-sse",
                       "ws_sse_q29.hex")


def render():
    return "".join(f"{w & 0xFFFFFFFF:08x}\n" for w in rom_words())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed ROM instead of rewriting it")
    args = ap.parse_args()
    text = render()
    if args.check:
        with open(args.out) as f:
            got = f.read()
        if got != text:
            print("STALE: committed ROM differs from the generator output")
            return 1
        print(f"OK: {ROM_WORDS} words, digest {table_digest()[:16]}")
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(text)
    print(f"wrote {os.path.relpath(args.out, REPO)} "
          f"({ROM_WORDS} words, digest {table_digest()[:16]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
