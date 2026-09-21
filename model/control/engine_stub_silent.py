"""SXT-021 NEGATIVE-CONTROL stub: a stale/silent engine slot.

This file exists only for the negative control in
`reports/sxt-021/negative-controls.txt`: it models a stub that is stale or
mislabeled as real DSP — it emits all-zero stereo regardless of schedule
state. The output checker (tools/control_negative_controls.py, check A2)
must FAIL such a render when the counter stub is the declared expected
output; if it did not, a silently-dead engine slot would pass as sound.

Name carries the repo `*_stub*` convention. Never used by the committed
fixtures.
"""
from typing import List, Tuple

BLOCK_SIZE = 32


class SilentStubEngine:
    """Stale/silent slot: all-zero stereo output (the failure being tested)."""

    name = "silent_stub"

    def process_block(self, b: int, vcount: int, sample_index0: int
                      ) -> List[Tuple[int, int]]:
        return [(0, 0)] * BLOCK_SIZE
