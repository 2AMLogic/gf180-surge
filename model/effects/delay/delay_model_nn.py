"""NEGATIVE CONTROL (b) -- NOT the frozen model: nearest-neighbour tap
substitution of the 12-tap sinc read. Must FAIL the model-vs-reference
budget check (tools/run_ncb_nn_model.py).

Issue #16 revision (2026-10-09): this module used to be a full copy of the
frozen model whose "nearest-neighbour" read had lost its read position
(it read line[(sinc_phase * 12 + 6) & mask], a near-fixed region at the
start of the line, never the delayed sample), so it controlled for a
missing wet path rather than for wrong tap interpolation. It is now a
subclass of the frozen DelayModel that differs ONLY in the tap read:
everything else (control plane, load-time LFO step, float32-grid fused
time lag, filters, write path, width, mix, per-instance state) is the
frozen model's, so a FAIL here is attributable to the interpolation alone.

Nearest neighbour, derived from the sinc table construction
(model/effects/delay/sinc_table.py): phase j's taps are centred at tap
index 5 + j/256 (t = -i + 6 + j/256 - 1 = 0), so the nearest line word to
the interpolated position rp + 5 + j/256 is rp + 5 for j < 128 and rp + 6
for j >= 128. One word is read per channel per sample.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model.effects.delay.delay_model import (  # noqa: E402,F401
    DelayModel as FrozenDelayModel, DelayParams, LINE_MASK,
)
from model.effects.delay.sinc_table import FIRIPOL_M, FIR_OFFSET  # noqa: E402

NN_TAP0 = FIR_OFFSET - 1          # tap index of the table centre at phase 0


class DelayModel(FrozenDelayModel):
    """Frozen DelayModel with the sinc read replaced by nearest neighbour."""

    TAP_READS = 1

    @staticmethod
    def _tap_read(line, rp, sp):
        tap = NN_TAP0 + (1 if 2 * sp >= FIRIPOL_M else 0)
        return line[(rp + tap) & LINE_MASK]
