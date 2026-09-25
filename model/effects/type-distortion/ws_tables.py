"""SXT-028e waveshaper lookup tables (formula re-derivation, nothing copied).

Structure authority (READ + cited; GPL-3.0-or-later tree, submodule pin
`libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce` per
`oracle/manifest.json`):

  include/sst/waveshapers/WaveshaperTables.h
      `WaveshaperTables::WaveshaperTables()` builds a 1024-entry float32 row
      per waveshaper type over x = (i - 512)/32, and
      `SurgeStorage::lookup_waveshape` (src/common/SurgeStorage.cpp:3295)
      reads it with x*32 + 512, integer truncation, and a linear lerp with
      hard rails (e > 0x3fd -> +1, e < 1 -> -1).

**No opaque designed constants.** Every table value is recomputed here from
the pinned *construction formula* (tanh / shafted_tanh / the hard-clip power
law), in the same double-then-float32 sequence the engine uses, and is then
quantized once to Q2.29. This is the `sinc_table.py` class of constant
(re-derived), NOT the DR-0002/DR-0003 class (quoted opaque data).

Frozen scope: only the three rows reachable from the Distortion FX path's
non-SSE branch are built — `wst_soft` (FX model 0), `wst_hard` (1),
`wst_asym` (2). `DistortionEffect::process` routes every
`ws >= wst_sine` (FX models 3..7) through `GetQuadWaveshaper`, a different
subsystem with its own per-instance registers and drive normalization; those
rows are NOT built here and the model refuses those model indices
(fail-closed, never silently substituted).
"""

import math
import struct

TABLE_SIZE = 1024
WS_FMT = "Q2.29"          # table words: |value| <= 1
WS_FRAC = 29

# FXWaveShapers[] index -> pinned WaveshaperType name
# (src/common/FilterConfiguration.h:236, n_fxws = 8)
FXWS_NAMES = ["wst_soft", "wst_hard", "wst_asym", "wst_sine", "wst_digital",
              "wst_ojd", "wst_fwrectify", "wst_fuzzsoft"]
# The three reachable through lookup_waveshape (ws < wst_sine).
FROZEN_MODELS = (0, 1, 2)


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def _shafted_tanh(x):
    """WaveshaperTables::shafted_tanh (double)."""
    return (math.exp(x) - math.exp(-x * 1.2)) / (math.exp(x) + math.exp(-x))


def _row_soft(x):
    return _f32(math.tanh(x))


def _row_hard(x):
    v = _f32(math.pow(math.tanh(math.pow(abs(x), 5.0)), 0.2))
    return _f32(-v) if x < 0 else v


def _row_asym(x):
    # (float)shafted_tanh(x + 0.5) - shafted_tanh(0.5)
    # the cast binds to the first term only; the subtraction result is then
    # stored into a float32 table slot.
    return _f32(_f32(_shafted_tanh(x + 0.5)) - _shafted_tanh(0.5))


_BUILDERS = {0: _row_soft, 1: _row_hard, 2: _row_asym}


def _to_q(x):
    """Quantize a float32 table value to Q2.29, round-half-up."""
    v = int(x * (1 << WS_FRAC) + 0.5) if x >= 0 else -int(-x * (1 << WS_FRAC) + 0.5)
    lo, hi = -(1 << 31), (1 << 31) - 1
    return lo if v < lo else (hi if v > hi else v)


def build_table(model_index):
    """1024 Q2.29 words for one FX model index (0/1/2 only)."""
    if model_index not in _BUILDERS:
        raise RuntimeError(
            f"waveshaper FX model index {model_index} "
            f"({FXWS_NAMES[model_index] if 0 <= model_index < 8 else '?'}) "
            "is outside the SXT-028e frozen scope: models 3..7 use the SSE "
            "quad-waveshaper path (GetQuadWaveshaper), which is a separate "
            "subsystem. Refusing (fail-closed); no generic substitute.")
    f = _BUILDERS[model_index]
    return [_to_q(f((float(i) - 512.0) * (1.0 / 32.0))) for i in range(TABLE_SIZE)]


TABLES = {m: build_table(m) for m in FROZEN_MODELS}


def table_digest():
    """Stable digest of the frozen tables (harness/ROM consistency guard)."""
    import hashlib
    h = hashlib.sha256()
    for m in FROZEN_MODELS:
        for w in TABLES[m]:
            h.update((w & 0xFFFFFFFF).to_bytes(4, "little"))
    return h.hexdigest()
