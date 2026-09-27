"""SXT-028e-sse waveshaper lookup tables for the SSE quad-waveshaper branch.

Formula re-derivation, nothing copied. Structure authority (READ + cited;
GPL-3.0-or-later tree, submodule pin
`libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce` per
`oracle/manifest.json`):

  include/sst/waveshapers/WaveshaperTables.h
      `WaveshaperTables::WaveshaperTables()` row `wst_sine`:
      `(float)std::sin((double)((double)i - 512.0) * M_PI / 512.0)`
      over i = 0..1023.  `SINUS_SSE2<false>` (Effects.h) reads that same
      1024-entry row, but with the SSE index convention
      (round-to-nearest int, 16-bit saturating pack, clamp to [0, 0x3fe]),
      NOT the `lookup_waveshape` truncating convention used by SXT-028e.
  include/sst/waveshapers/WaveshaperLUT.h
      `LUTBase<NP, F>`: `dx = 2.0 / N`, `data[i] = F(i * dx - 1.0)` for
      i = 0..N (N + 1 entries); `WS_PM1_LUT<N>` interpolates it.
  include/sst/waveshapers/Fuzzes.h
      `FuzzTable<1>`: `range = 0.1 * scale`;
      `xadj = x * (1 - range) + dist(gen)` with a function-static
      `portable_minstd_rand(2112)` and a function-static
      `std::uniform_real_distribution<float>(-range, range)`.
      `portable_minstd_rand` is the header's OWN de-typedef of
      `std::minstd_rand` — `linear_congruential_engine<uint_fast32_t,
      48271, 0, 2147483647>` — introduced there precisely so the fuzz
      tables are identical across platforms and compilers.

**No opaque designed *table* constants.** Every word below is recomputed
from the pinned construction formula, in the same double/float32 sequence
the engine uses, and quantized once to Q2.29. This is the DR-0012 clause
(b) class of constant (re-derivation from a cited formula), NOT the
DR-0002/DR-0012(a) class (quoted opaque data). The *scalar* designed
constants of the five shapers themselves (OJD's breakpoints, the TANH
rational, the DC blocker pole, the ADAA tolerance, the fuzz range/seed) are
inventoried in `decision-records/0014-distortion-sse-quad-waveshaper-constants.md`.

THE ONE IMPLEMENTATION-DEFINED STEP, AND HOW IT IS PINNED. `FuzzTable`'s
`std::uniform_real_distribution<float>` is *not* specified bit-for-bit by
the C++ standard, so the header's `portable_minstd_rand` only pins half the
pipeline. Both major standard libraries reduce, for this engine and this
type, to exactly the same three float operations:

    u_k    = float(lcg_k - 1) / 2147483648.0f      # generate_canonical<float,24>
    draw_k = u_k * (b - a) + a                     # uniform_real_distribution

(libstdc++ `std::generate_canonical` with `__b = 24`, `__log2r = 31`,
`__m = 1`, `__tmp = float(2147483646.0L) = 2147483648.0f`; libc++ with
`__logR = 30`, `__k = 1`, `__base = float(2147483645) + 1 = 2147483648.0f`.)
`_generate_canonical_f32` below implements exactly that. It is validated
byte-for-byte against a build of the pinned header's own expression with
libstdc++ (see `reports/SXT-028e-sse/EVIDENCE.md` §2 and
`tools/check_fuzz_table_rederivation.py`); the libc++ equivalence is
derived by reading its `generate_canonical`, and is recorded as
UNVERIFIED-BY-BUILD rather than asserted.

Frozen scope: only the two rows reachable from the Distortion FX path's SSE
branch are built — `wst_sine` (FX models 3, via `SINUS_SSE2<false>`) and
`FuzzTable<1>` at N = 1024 (FX model 7, via
`TableEval<FuzzTable<1>, 1024, TANH>`). FX models 0/1/2 are the SXT-028e
(#57) table branch and are REFUSED here, fail-closed, exactly as #57
refuses 3..7.
"""

import math
import struct

SINE_SIZE = 1024          # WaveshaperTables::tableSize
FUZZ_N = 1024             # TableEval<FuzzTable<1>, 1024, TANH>
FUZZ_SIZE = FUZZ_N + 1    # LUTBase stores N + 1 entries
WS_FMT = "Q2.29"          # table words: |value| <= 1
WS_FRAC = 29

# FXWaveShapers[] index -> pinned WaveshaperType name
# (src/common/FilterConfiguration.h:236, n_fxws = 8)
FXWS_NAMES = ["wst_soft", "wst_hard", "wst_asym", "wst_sine", "wst_digital",
              "wst_ojd", "wst_fwrectify", "wst_fuzzsoft"]
# The five routed through GetQuadWaveshaper (ws >= wst_sine).
SSE_MODELS = (3, 4, 5, 6, 7)
# FX model index -> the GetQuadWaveshaper entry point (QuadWaveshaper_Impl.h)
SSE_SHAPER_OF = {
    3: "SINUS_SSE2<false>",
    4: "DIGI_SSE2",
    5: "OJD",
    6: "ADAA_FULL_WAVE",
    7: "TableEval<FuzzTable<1>, 1024, TANH>",
}
# Which of the five reach a table row (the other three are closed-form).
SSE_TABLE_OF = {3: "sine", 7: "fuzz1"}
# FX models frozen by the SXT-028e (#57) table branch; refused here.
TABLE_BRANCH_MODELS = (0, 1, 2)


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def _u32_of_f32(x):
    return struct.unpack("I", struct.pack("f", _f32(x)))[0]


# ---------------------------------------------------------------------------
# wst_sine row (WaveshaperTables.h)
# ---------------------------------------------------------------------------
def build_sine_row():
    """1024 Q2.29 words: (float)sin((i - 512) * M_PI / 512), i = 0..1023."""
    return [_to_q(_f32(math.sin((float(i) - 512.0) * math.pi / 512.0)))
            for i in range(SINE_SIZE)]


# ---------------------------------------------------------------------------
# FuzzTable<1> row (Fuzzes.h + WaveshaperLUT.h LUTBase)
# ---------------------------------------------------------------------------
class PortableMinstdRand:
    """`portable_minstd_rand` = linear_congruential_engine<·, 48271, 0, 2^31-1>.

    The pinned header de-typedefs `std::minstd_rand` on purpose ("to make
    the fuzzes the same on all platforms and compiler choices"), so the
    engine, the multiplier and the seed are all pinned data, not an
    implementation detail.
    """

    A = 48271
    M = 2147483647

    MIN = 1
    MAX = 2147483646

    def __init__(self, seed=2112):
        s = seed % self.M
        self.x = s if s else 1

    def __call__(self):
        self.x = (self.A * self.x) % self.M
        return self.x


def _generate_canonical_f32(gen):
    """std::generate_canonical<float, 24, portable_minstd_rand>.

    Both libstdc++ and libc++ collapse to a single draw here (see the module
    docstring): `float(g() - g.min()) / 2147483648.0f`, with the documented
    `>= 1` guard clamping to nextafter(1, 0).
    """
    denom = _f32(float(PortableMinstdRand.MAX - PortableMinstdRand.MIN + 1))
    num = _f32(float(gen() - PortableMinstdRand.MIN))
    ret = _f32(num / denom)
    if ret >= 1.0:
        ret = struct.unpack("f", struct.pack("I", 0x3F7FFFFF))[0]
    return ret


def _fuzz_table_scale1_sequence(count):
    """`FuzzTable<1>` evaluated `count` times in construction order.

    The generator and the distribution are FUNCTION-STATIC in the pinned
    header, so the draws form one deterministic sequence consumed in
    LUTBase's construction order. Returns the float32 draw for each call.
    """
    gen = PortableMinstdRand(2112)
    rng_range = _f32(0.1 * 1)        # const float range = 0.1 * scale
    lo, hi = _f32(-rng_range), _f32(rng_range)
    span = _f32(hi - lo)
    return [_f32(_f32(_generate_canonical_f32(gen) * span) + lo)
            for _ in range(count)]


def build_fuzz1_row():
    """1025 Q2.29 words: LUTBase<1024, FuzzTable<1>>::data."""
    draws = _fuzz_table_scale1_sequence(FUZZ_SIZE)
    dx = _f32(2.0 / FUZZ_N)                      # static constexpr float dx
    rng_range = _f32(0.1 * 1)
    one_minus_range = _f32(1 - rng_range)        # int 1 - float range -> float
    out = []
    for i in range(FUZZ_SIZE):
        # LUTBase: `float x = i * dx - 1.0;` (float product, double subtract,
        # narrowed back to float -- exact here because i*dx == i/512)
        x = _f32(_f32(i * dx) - 1.0)
        out.append(_to_q(_f32(_f32(x * one_minus_range) + draws[i])))
    return out


def _to_q(x):
    """Quantize a float32 table value to Q2.29, round-half-up (magnitude)."""
    v = int(x * (1 << WS_FRAC) + 0.5) if x >= 0 else -int(-x * (1 << WS_FRAC) + 0.5)
    lo, hi = -(1 << 31), (1 << 31) - 1
    return lo if v < lo else (hi if v > hi else v)


def build_table(model_index):
    """The Q2.29 row for one FX model index, or a fail-closed refusal."""
    if model_index in TABLE_BRANCH_MODELS:
        raise RuntimeError(
            f"waveshaper FX model index {model_index} "
            f"({FXWS_NAMES[model_index]}) is the SXT-028e (#57) "
            "`SurgeStorage::lookup_waveshape` table branch, NOT this leaf's "
            "`GetQuadWaveshaper` branch. Refusing (fail-closed); use "
            "model/effects/type-distortion/ for models 0..2.")
    if model_index == 3:
        return build_sine_row()
    if model_index == 7:
        return build_fuzz1_row()
    raise RuntimeError(
        f"waveshaper FX model index {model_index} "
        f"({FXWS_NAMES[model_index] if 0 <= model_index < 8 else '?'}) has no "
        "lookup table: "
        f"{SSE_SHAPER_OF.get(model_index, '(out of range)')} is closed form. "
        "Refusing (fail-closed) rather than inventing a row.")


TABLES = {"sine": build_sine_row(), "fuzz1": build_fuzz1_row()}

# ROM layout streamed to the RTL (rtl/effects/type-distortion-sse/ws_sse_q29.hex):
#   [0    .. 1023]  wst_sine row          (1024 words)
#   [1024 .. 2048]  FuzzTable<1> row      (1025 words)
ROM_ORDER = ("sine", "fuzz1")
ROM_BASE = {"sine": 0, "fuzz1": SINE_SIZE}
ROM_WORDS = SINE_SIZE + FUZZ_SIZE


def rom_words():
    out = []
    for key in ROM_ORDER:
        out += TABLES[key]
    assert len(out) == ROM_WORDS
    return out


def table_digest():
    """Stable digest of the frozen tables (harness/ROM consistency guard)."""
    import hashlib
    h = hashlib.sha256()
    for w in rom_words():
        h.update((w & 0xFFFFFFFF).to_bytes(4, "little"))
    return h.hexdigest()
