"""SXT-021 counter STUB engine (the v1 schedule slot occupant).

This is a STUB — the name carries the repo `*_stub*` negative-control
convention. It occupies the engine slot so the timed control plane can be
proven end to end (scheduling, framing, continuous output) before any DSP
exists (SXT-022+). It makes NO audio, fidelity, or preset-quality claim and
its cost enters the schedule accounting as a named placeholder
(`STUB_CYCLES_PER_SAMPLE`, model/control/accounting.py).

Deterministic integer output (mirrored EXACTLY in rtl/control):

    for block b, sample index i (0..31), global sample g = b*32 + i,
    v = active voice count after this block's events:

        L = ((v & 0xF) << 12) | ((g + 1) & 0xFFF)      (16-bit unsigned)
        R = (L + 1) & 0xFFFF

Properties the output checker relies on:
  * never all-zero for a rendered range (bias +1 in the low field);
  * sample counter is monotone within the 12-bit field (a stale/repeating
    stub is detectable);
  * the voice-count nibble makes note-on/steal/patch-change effects visible
    in the recording, so allocation glitches are characterizable.
"""
from typing import List, Tuple

BLOCK_SIZE = 32  # engine pin


class CounterStubEngine:
    """Clearly-named stub engine: sample counter + voice nibble, stereo."""

    name = "counter_stub"

    def process_block(self, b: int, vcount: int, sample_index0: int
                      ) -> List[Tuple[int, int]]:
        frame = []
        for i in range(BLOCK_SIZE):
            g = sample_index0 + i
            l = ((vcount & 0xF) << 12) | ((g + 1) & 0xFFF)
            r = (l + 1) & 0xFFFF
            frame.append((l, r))
        return frame
