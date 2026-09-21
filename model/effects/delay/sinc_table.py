"""Windowed-sinc interpolation table for the Delay model, recomputed from the
pinned construction formula.

Source (READ, not copied): the pinned engine tree
  libs/sst/sst-basic-blocks/include/sst/basic-blocks/tables/SincTableProvider.h
  (SurgeSincTableProvider constructor, cutoff1X = 0.85f) and
  libs/sst/sst-basic-blocks/include/sst/basic-blocks/dsp/SpecialFunctions.h
  (symmetric_blackman, sincf).

The table is DERIVED here from the cited formulas in double precision and
quantized once; no table bytes are copied from the GPL tree. The engine stores
float32; this model stores Q2.29 (the <=1 ulp float32 rounding difference is a
declared model-vs-reference error source).

Frozen shape: FIRipol_M = 256 phases, FIRipol_N = 12 taps per phase,
table[(FIRipol_M + 1) * FIRipol_N], row-major: table[j * 12 + i],
t = -i + 6 + j/256 - 1, val = symmetric_blackman(t, 12) * 0.85 * sincf(0.85*t).
"""

import math

FIRIPOL_M = 256
FIRIPOL_N = 12
FIR_OFFSET = FIRIPOL_N >> 1  # = 6, Delay.h setvars constexpr FIRoffset

SINC_FMT = "Q2.29"

# Double-precision table (derived), plus the frozen Q2.29 quantization.
TABLE_D = []
TABLE_Q = []


def _symmetric_blackman(i, n):
    i -= n // 2
    return 0.42 - 0.5 * math.cos(2 * math.pi * i / n) + 0.08 * math.cos(4 * math.pi * i / n)


def _sincf(x):
    if x == 0:
        return 1.0
    return math.sin(math.pi * x) / (math.pi * x)


def _build():
    cutoff1x = 0.85
    for j in range(FIRIPOL_M + 1):
        for i in range(FIRIPOL_N):
            t = -float(i) + float(FIRIPOL_N / 2.0) + float(j) / float(FIRIPOL_M) - 1.0
            val = _symmetric_blackman(t, FIRIPOL_N) * cutoff1x * _sincf(cutoff1x * t)
            TABLE_D.append(val)
    from model.effects.qmath import to_q

    for v in TABLE_D:
        TABLE_Q.append(to_q(v, SINC_FMT))


_build()
