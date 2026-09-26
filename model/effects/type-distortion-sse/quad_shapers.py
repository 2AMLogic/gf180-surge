"""SXT-028e-sse frozen fixed-point quad waveshapers (`GetQuadWaveshaper`).

Structure authority (READ + cited; GPL-3.0-or-later tree, submodule pin
`libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce`; no
code, tables or assets copied):

  include/sst/waveshapers/QuadWaveshaper.h
      `n_waveshaper_registers = 4`; `QuadWaveshaperState { SIMD_M128
      R[4]; SIMD_M128 init; }`; `QuadWaveshaperPtr(state, in, drive)`.
  include/sst/waveshapers/QuadWaveshaper_Impl.h
      `GetQuadWaveshaper` dispatch. The five entries reachable from
      `FXWaveShapers[3..7]` are:
        3 wst_sine      -> SINUS_SSE2<false>                 (Effects.h)
        4 wst_digital   -> DIGI_SSE2                         (Effects.h)
        5 wst_ojd       -> OJD                               (Saturators.h)
        6 wst_fwrectify -> ADAA_FULL_WAVE                    (Rectifiers.h)
        7 wst_fuzzsoft  -> TableEval<FuzzTable<1>,1024,TANH> (WaveshaperLUT.h)
  include/sst/waveshapers/{Effects,Saturators,Rectifiers,ADAA,DCBlocker,
      WaveshaperLUT}.h -- the kernels reproduced below, op for op.

CLAIM DISCIPLINE. This file is part of the frozen reference the SXT-028e-sse
RTL must match EXACTLY (integer equality at declared checkpoints; separate
claim). Model-vs-pinned-engine agreement is a SEPARATE claim under
[PROPOSED] budgets that are not frozen (SXT-017, #12). Nothing here is a
preset-support or musical-quality claim.

FROZEN WORD FORMATS (this leaf's additions to the model/effects/README.md
family; the shared Distortion chain keeps SXT-028e's formats unchanged):

  Q10.21 s32   audio words in/out of the shaper (as SXT-028e)
  Q24.43 s64   `C`: shaper input/output words, every shaper intermediate,
               the four quad-waveshaper registers, `dNow`/`dD`, `dcOffset`
  Q40.23 s64   `S`: the TANH numerator/denominator only -- the one place
               where the pinned expression `x*(27 + x*x)` exceeds Q24.43's
               +-8.39e6 range (|x| may reach the Q10.21 rail, 1024)
  Q2.29  s32   `W`: table ROM words (sse_tables.py)

Products are exact and rounded round-half-up to the target format, then
saturated. No floating point at audio run time; double precision only at
control (block) rate, quantized once.

DECLARED DEVIATIONS (bounded, stated, never silently absorbed):

  DD-1  SIMD LANES. `DistortionEffect::process` loads only `sb[0] = L` and
        `sb[1] = R` into the 4-lane vector; lanes 2 and 3 are whatever was
        on the engine's stack (`float sb alignas(16)[4];` is uninitialised).
        Every operation in every reachable shaper -- including `rcp_ps`,
        the compare/select masks, and the per-lane table gathers -- is
        lane-wise, so lanes 2/3 provably cannot influence lanes 0/1 or the
        registers of lanes 0/1. This model carries TWO lanes and declares
        the other two out of scope rather than modelling stack garbage.

  DD-2  `rcp_ps` IS AN APPROXIMATION, AND AN IMPLEMENTATION-DEFINED ONE.
        `DIGI_SSE2` (`rcp_ps(drive)`) and `TANH` (`rcp_ps(denom)`) use the
        SSE reciprocal *estimate*, specified only to ~12 bits of relative
        accuracy (|rel err| <= 1.5 * 2^-12 ~ 3.7e-4) and NOT bit-identical
        between x86 implementations, nor between x86 and simde-on-ARM
        (the pinned evidence host is arm64 macOS -- `oracle/manifest.json`).
        This model uses the EXACT reciprocal, rounded once. Consequence:
        for FX models 4 and 7 the model-vs-reference leg carries an extra
        term bounded by the rcp estimate error; it does NOT affect the
        RTL-vs-model leg (both sides use the exact reciprocal). Recorded as
        finding F-028e-sse-1 and routed to SXT-017 (#12); the reference
        budgets are [PROPOSED] and are NOT frozen here.

  DD-3  `QuadWaveshaperState::init` IS INDETERMINATE IN THE ENGINE.
        `DistortionEffect::init()` zeroes `wsState.R[i]` but does NOT touch
        `wsState.init`, and `QuadWaveshaperState` has no constructor, so on
        a freshly spawned effect that mask holds whatever the allocation
        left there. Only `ADAA_FULL_WAVE` (FX model 6) READS it. This model
        freezes it to ALL-ONES ("this is the first sample") at construction
        and at every `init()`/`suspend()`, which is the documented intent of
        the field (`ADAA.h`: "Set updateInit to false if you are going to
        wrap this in a dcBlocker ... which resets init itself"). Bound: the
        choice can change at most the FIRST oversampled sample after each
        reset, for FX model 6 only -- the ADAA registers themselves are
        written unconditionally, so no divergence persists. Recorded as
        finding F-028e-sse-2.

  DD-4  RANGE SATURATION OF THE DRIVE-NORMALIZED INPUT. The engine's
        `sb = L * (1.f/dNow)` is unbounded in float. Here it is a Q24.43
        word (+-8.39e6). With the drive ramp's own Q13.18 word this
        saturates only for `dNow` below ~1.2e-4 (about -78 dBFS of drive,
        already only ~32 LSB of the Q13.18 drive word) combined with a
        near-rail input. The model COUNTS saturation events per instance
        (`QuadWaveshaperState.sat_events`) so a harness can report them
        instead of assuming they did not happen; every committed case in
        `reports/SXT-028e-sse/rtl-exactness.json` records the count.
        `dNow == 0` (reachable: Q13.18 quantizes ~-120 dB of drive to 0)
        yields the saturated reciprocal, matching the engine's `inf` only in
        sign and magnitude order, not value -- also counted.

Every deviation above is a MODEL-vs-REFERENCE term. None of them affects the
RTL-vs-model claim, which is integer equality on both sides of the same
frozen arithmetic.
"""

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sse_tables import (  # noqa: E402
    TABLES, SSE_MODELS, SSE_SHAPER_OF, FXWS_NAMES, TABLE_BRANCH_MODELS,
    SINE_SIZE, FUZZ_N,
)

# ---------------------------------------------------------------- formats
FA = 21          # Q10.21 audio
FG = 18          # Q13.18 gain ramps
FC = 43          # Q24.43 shaper words / registers / dNow
FS = 23          # Q40.23 TANH numerator + denominator
FW = 29          # Q2.29 table ROM words
W32 = 32
W64 = 64

INT32_MIN = -2147483648
INT32_MAX = 2147483647


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def fsat(v, w):
    lo = -(1 << (w - 1))
    hi = (1 << (w - 1)) - 1
    return lo if v < lo else (hi if v > hi else v)


def fq(x, f, w=W64):
    """Quantize a double to Q·f, round-half-up on magnitude, saturating."""
    v = int(x * (1 << f) + 0.5) if x >= 0 else -int(-x * (1 << f) + 0.5)
    return fsat(v, w)


def fmul(a, b, fa, fb, fq_, w):
    """Exact product, round-half-up to Q·fq_, saturated to w bits."""
    s = fa + fb - fq_
    p = a * b
    if s > 0:
        p = (p + (1 << (s - 1))) >> s
    elif s < 0:
        p <<= -s
    return fsat(p, w)


def fmul_counted(a, b, fa, fb, fq_, w, state):
    """`fmul` that RECORDS range saturation instead of hiding it (DD-4)."""
    s = fa + fb - fq_
    p = a * b
    if s > 0:
        p = (p + (1 << (s - 1))) >> s
    elif s < 0:
        p <<= -s
    out = fsat(p, w)
    if out != p and state is not None:
        state.sat_events += 1
    return out


def fcv(v, ffrom, fto, w):
    """Re-quantize between formats, round-half-up, saturating."""
    s = ffrom - fto
    if s > 0:
        v = (v + (1 << (s - 1))) >> s
    elif s < 0:
        v <<= -s
    return fsat(v, w)


def fadd(a, b, w):
    return fsat(a + b, w)


def fsub(a, b, w):
    return fsat(a - b, w)


def fshl(v, n, w):
    """Exact power-of-two scale-up (the engine's *16 / *256 multiplies)."""
    return fsat(v << n, w)


def frecip(b, fb, fq_, w, state=None):
    """1 / b, round-half-up on magnitude, saturating (see DD-2 and DD-4)."""
    if b == 0:
        if state is not None:
            state.sat_events += 1
        return (1 << (w - 1)) - 1
    num = 1 << (fb + fq_)
    if b > 0:
        v = (2 * num + b) // (2 * b)
    else:
        nb = -b
        v = -((2 * num + nb) // (2 * nb))
    out = fsat(v, w)
    if state is not None and out != v:
        state.sat_events += 1
    return out


def cvt_i32(v, f):
    """`_mm_cvtps_epi32` on a Q·f word: round-half-to-EVEN, then the SSE
    out-of-range rule (result is the "integer indefinite" value INT32_MIN).

    Round-to-nearest-even is the default MXCSR mode and the one Surge runs
    under; it is NOT truncation, so the SSE shapers' interpolation remainder
    is signed (in [-0.5, 0.5]) unlike the `lookup_waveshape` branch's.
    """
    q = 1 << f
    n = v >> f                      # floor
    r = v - (n << f)                # [0, q)
    half = q >> 1
    if r > half:
        n += 1
    elif r == half and (n & 1):
        n += 1
    if n < INT32_MIN or n > INT32_MAX:
        return INT32_MIN
    return n


def packs16(e):
    """`_mm_packs_epi32`: saturating int32 -> int16."""
    if e > 32767:
        return 32767
    if e < -32768:
        return -32768
    return e


# ------------------------------------------------------- frozen constants
# Every scalar below is quoted from the pinned shaper sources and
# inventoried in decision-records/0014-distortion-sse-quad-waveshaper-constants.md.
ONE_C = 1 << FC
HALF_C = fq(0.5, FC)
C256_SHIFT = 8                                   # SINUS m256 = 256.f
C512_C = fq(512.0, FC)                           # SINUS m512
C16_SHIFT = 4                                    # DIGI m16 = 16.f
C16INV_C = fq(0.0625, FC)                        # DIGI m16inv
OJD_M17_C = fq(_f32(-1.7), FC)
OJD_P11_C = fq(_f32(1.1), FC)
OJD_M03_C = fq(_f32(-0.3), FC)
OJD_P09_C = fq(_f32(0.9), FC)
# `1.f / (4 * (1 - 0.3f))` and `1.f / (4 * (1 - 0.9f))` in float32, as written
OJD_DENLOW_C = fq(_f32(1.0 / _f32(4 * _f32(1 - _f32(0.3)))), FC)
OJD_DENHIGH_C = fq(_f32(1.0 / _f32(4 * _f32(1 - _f32(0.9)))), FC)
TANH_9_C = fq(9.0, FC)
TANH_27_C = fq(27.0, FC)
TANH_9_S = fq(9.0, FS)
TANH_27_S = fq(27.0, FS)
ADAA_TOL_C = fq(_f32(0.0001), FC)                # set1_ps((double)0.0001)
DCBLOCK_FAC_C = fq(_f32(0.9999), FC)             # set1_ps(0.9999)
PM1_DX_C = fq(float(FUZZ_N // 2), FC)            # WS_PM1_LUT dx = ctr = N/2
PM1_UB_C = fq(float(FUZZ_N - 1), FC)             # UB = N - 1

# The DESIGNED shaper scalars, in the order the RTL's INITFILE expects them
# (indices 16..26). Per DR-0002 clause 1 / DR-0012 clause 1 the RTL carries no
# independent copy of engine data: these are streamed, exactly like the twelve
# halfband allpass coefficients. Structural powers of two (1.0, 0.5, 512.0,
# 0.0625, N/2, N-1) are NOT engine data and stay localparams in the RTL.
SHAPER_INIT_WORDS = [
    OJD_M17_C,        # 16  OJD  -1.7f
    OJD_P11_C,        # 17  OJD   1.1f
    OJD_M03_C,        # 18  OJD  -0.3f
    OJD_P09_C,        # 19  OJD   0.9f
    OJD_DENLOW_C,     # 20  OJD  1/(4*(1-0.3f))
    OJD_DENHIGH_C,    # 21  OJD  1/(4*(1-0.9f))
    TANH_9_C,         # 22  TANH 9   (Q24.43)
    TANH_27_C,        # 23  TANH 27  (Q24.43)
    TANH_27_S,        # 24  TANH 27  (Q40.23)
    ADAA_TOL_C,       # 25  ADAA tolerance 1e-4f
    DCBLOCK_FAC_C,    # 26  dcBlock pole 0.9999f
]
SHAPER_INIT_BASE = 16

_SINE_ROM = [w << (FC - FW) for w in TABLES["sine"]]
_FUZZ_ROM = [w << (FC - FW) for w in TABLES["fuzz1"]]


class QuadWaveshaperState:
    """`sst::waveshapers::QuadWaveshaperState`, per Distortion instance.

    Four registers x two modelled lanes (DD-1) plus the per-lane `init`
    mask. This is the state the SXT-028e (#57) table branch does not have,
    and the reason this is a sibling leaf rather than a parameter: two
    Distortion slots are two of these, never pooled.
    """

    N_REGISTERS = 4        # sst::waveshapers::n_waveshaper_registers
    LANES = 2              # DD-1

    def __init__(self):
        self.R = [[0, 0] for _ in range(self.N_REGISTERS)]   # Q24.43
        self.init = [True, True]                             # DD-3
        self.sat_events = 0                                  # DD-4

    def engine_init(self):
        """`DistortionEffect::init()`: zero R[i]; freeze `init` per DD-3."""
        self.R = [[0, 0] for _ in range(self.N_REGISTERS)]
        self.init = [True, True]

    def probe_state(self):
        """The throw-away state of the DC-offset probe.

        `DistortionEffect::process` zeroes BOTH `probeState.R[i]` and
        `probeState.init` explicitly, so unlike DD-3 this one is specified
        by the pinned source.
        """
        s = QuadWaveshaperState()
        s.init = [False, False]
        return s

    def checkpoint(self, prefix="ws"):
        d = {}
        for i in range(self.N_REGISTERS):
            for lane in range(self.LANES):
                d[f"{prefix}R{i}{lane}"] = self.R[i][lane]
        for lane in range(self.LANES):
            d[f"{prefix}I{lane}"] = 1 if self.init[lane] else 0
        return d


# ------------------------------------------------------------- the shapers
# Each takes (state, lane, x_c, drive_c) in Q24.43 and returns Q24.43,
# exactly mirroring `SIMD_M128 wsop(QuadWaveshaperState*, in, drive)`.

def sinus_sse2(st, lane, x_c, drive_c):
    """`SINUS_SSE2<false>` (Effects.h) -- FX model 3, wst_sine."""
    x = fmul(x_c, drive_c, FC, FC, FC, W64)
    x = fadd(fshl(x, C256_SHIFT, W64), C512_C, W64)
    e_raw = cvt_i32(x, FC)
    a = fsub(x, fsat(e_raw << FC, W64), W64)          # remainder, signed
    e = packs16(e_raw)
    # DO_FOLD == false: clip to the table edges instead of wrapping
    e = 0 if e < 0 else (0x3fe if e > 0x3fe else e)
    t0 = _SINE_ROM[e & 0x3ff]
    t1 = _SINE_ROM[(e + 1) & 0x3ff]
    return fadd(fmul(fsub(ONE_C, a, W64), t0, FC, FC, FC, W64),
                fmul(a, t1, FC, FC, FC, W64), W64)


def digi_sse2(st, lane, x_c, drive_c):
    """`DIGI_SSE2` (Effects.h) -- FX model 4, wst_digital.

    The only reachable shaper that divides by drive internally; that is
    exactly why `DistortionEffect::process` sets `skipDriveNorm` for it.
    """
    invdrive = frecip(drive_c, FC, FC, W64, st)       # rcp_ps -- DD-2
    u = fshl(x_c, C16_SHIFT, W64)                     # m16 * in
    u = fmul_counted(invdrive, u, FC, FC, FC, W64, st)
    u = fadd(u, HALF_C, W64)                          # + mofs
    a = cvt_i32(u, FC)
    w = fsub(fsat(a << FC, W64), HALF_C, W64)         # cvtepi32_ps(a) - mofs
    w = fmul(C16INV_C, w, FC, FC, FC, W64)
    return fmul(drive_c, w, FC, FC, FC, W64)


def ojd(st, lane, x_c, drive_c):
    """`OJD` (Saturators.h) -- FX model 5, wst_ojd.

    The five pinned masks are disjoint and exhaustive
    (x <= -1.7 | -1.7 < x < -0.3 | -0.3 <= x <= 0.9 | 0.9 < x < 1.1 |
    x >= 1.1), so the engine's masked SUM is a select and is reproduced here
    as one.
    """
    x = fmul(x_c, drive_c, FC, FC, FC, W64)
    if x <= OJD_M17_C:
        return -ONE_C
    if x >= OJD_P11_C:
        return ONE_C
    if x < OJD_M03_C:
        xlow = fsub(x, OJD_M03_C, W64)
        v = fadd(xlow, fmul(OJD_DENLOW_C, fmul(xlow, xlow, FC, FC, FC, W64),
                            FC, FC, FC, W64), W64)
        return fadd(v, OJD_M03_C, W64)
    if x > OJD_P09_C:
        xhi = fsub(x, OJD_P09_C, W64)
        v = fsub(xhi, fmul(OJD_DENHIGH_C, fmul(xhi, xhi, FC, FC, FC, W64),
                           FC, FC, FC, W64), W64)
        return fadd(v, OJD_P09_C, W64)
    return x


def _clip(x_c, drive_c):
    """`CLIP` (Saturators.h): max(min(in*drive, 1), -1)."""
    x = fmul(x_c, drive_c, FC, FC, FC, W64)
    if x > ONE_C:
        return ONE_C
    if x < -ONE_C:
        return -ONE_C
    return x


def _tanh(st, x_c, drive_c):
    """`TANH` (Saturators.h): clip(x*(27 + x^2) / (27 + 9x^2))."""
    x = fmul(x_c, drive_c, FC, FC, FC, W64)
    xx = fmul(x, x, FC, FC, FC, W64)
    num = fmul(x, fadd(TANH_27_C, xx, W64), FC, FC, FS, W64)
    den = fadd(TANH_27_S, fmul(TANH_9_C, xx, FC, FC, FS, W64), W64)
    inv = frecip(den, FS, FC, W64, st)                # rcp_ps -- DD-2
    y = fmul(num, inv, FS, FC, FC, W64)
    if y > ONE_C:
        return ONE_C
    if y < -ONE_C:
        return -ONE_C
    return y


def _adaa_fwrect(st, lane, x):
    """`ADAA<fwrect_kernel, 0, 1, true>` (ADAA.h + Rectifiers.h)."""
    x_prior = st.R[0][lane]
    ad_prior = st.R[1][lane]
    # fwrect_kernel: F = sgn(x)*x = |x| ; adF = F * (x * 0.5)
    f_val = -x if x < 0 else x
    adf = fmul(f_val, fmul(x, HALF_C, FC, FC, FC, W64), FC, FC, FC, W64)
    dx = fsub(x, x_prior, W64)
    dad = fsub(adf, ad_prior, W64)
    ltt = (dx < ADAA_TOL_C and dx > -ADAA_TOL_C) or st.init[lane]
    denom = ADAA_TOL_C if ltt else dx
    dx_div = frecip(denom, FC, FC, W64, st)           # rcp_ps -- DD-2
    from_ad = fmul(dad, dx_div, FC, FC, FC, W64)
    r = f_val if ltt else from_ad
    st.R[0][lane] = x
    st.R[1][lane] = adf
    st.init[lane] = False                             # updateInit == true
    return r


def adaa_full_wave(st, lane, x_c, drive_c):
    """`ADAA_FULL_WAVE` (Rectifiers.h) -- FX model 6, wst_fwrectify."""
    return _adaa_fwrect(st, lane, _clip(x_c, drive_c))


def _ws_pm1_lut(table_c, x_c):
    """`WS_PM1_LUT<N>` (WaveshaperLUT.h) over an N+1-entry table."""
    x = fadd(fmul(x_c, PM1_DX_C, FC, FC, FC, W64), PM1_DX_C, W64)
    xc = x
    if xc > PM1_UB_C:
        xc = PM1_UB_C
    if xc < 0:
        xc = 0
    e = cvt_i32(xc, FC)
    frac = fsub(x, fsat(e << FC, W64), W64)           # NOTE: unclamped x
    e = packs16(e)
    t0 = table_c[e]
    t1 = table_c[e + 1]
    return fadd(fmul(fsub(ONE_C, frac, W64), t0, FC, FC, FC, W64),
                fmul(frac, t1, FC, FC, FC, W64), W64)


def _dc_block(st, lane, r1, r2, x):
    """`dcBlock<R1, R2>` (DCBlocker.h): y = x - x[-1] + 0.9999*y[-1]."""
    dx = fsub(x, st.R[r1][lane], W64)
    filtval = fadd(dx, fmul(DCBLOCK_FAC_C, st.R[r2][lane], FC, FC, FC, W64),
                   W64)
    st.R[r1][lane] = x
    st.R[r2][lane] = filtval
    st.init[lane] = False
    return filtval


def fuzzsoft(st, lane, x_c, drive_c):
    """`TableEval<FuzzTable<1>, 1024, TANH>` -- FX model 7, wst_fuzzsoft."""
    c = _tanh(st, x_c, drive_c)
    v = _ws_pm1_lut(_FUZZ_ROM, c)
    return _dc_block(st, lane, 0, 1, v)


SHAPERS = {3: sinus_sse2, 4: digi_sse2, 5: ojd, 6: adaa_full_wave,
           7: fuzzsoft}

# `skipDriveNorm` in DistortionEffect::process: DIGITAL only.
SKIP_DRIVE_NORM = {3: False, 4: True, 5: False, 6: False, 7: False}

# Which registers each reachable shaper actually touches (state inventory).
REGISTER_USE = {3: (), 4: (), 5: (), 6: (0, 1), 7: (0, 1)}
READS_INIT = {3: False, 4: False, 5: False, 6: True, 7: False}


def get_quad_waveshaper(model_i):
    """`GetQuadWaveshaper(FXWaveShapers[model_i])`, fail-closed."""
    model_i = int(model_i)
    if model_i in TABLE_BRANCH_MODELS:
        raise RuntimeError(
            f"FX waveshaper model index {model_i} ({FXWS_NAMES[model_i]}) is "
            "the SXT-028e (#57) `SurgeStorage::lookup_waveshape` table "
            "branch, not this leaf's `GetQuadWaveshaper` branch. Refusing "
            "(fail-closed): use model/effects/type-distortion/ for 0..2. "
            "Routing one branch's model through the other's shaper would be "
            "an ADAPTED effect, not this one.")
    if model_i not in SHAPERS:
        raise RuntimeError(
            f"FX waveshaper model index {model_i} is outside n_fxws = 8 "
            "(FilterConfiguration.h:235). Refusing (fail-closed).")
    return SHAPERS[model_i]


def shaper_name(model_i):
    return SSE_SHAPER_OF[int(model_i)]


__all__ = [
    "QuadWaveshaperState", "get_quad_waveshaper", "shaper_name",
    "SHAPERS", "SKIP_DRIVE_NORM", "REGISTER_USE", "READS_INIT", "SSE_MODELS",
    "FA", "FG", "FC", "FS", "FW", "W32", "W64",
    "fsat", "fq", "fmul", "fmul_counted", "fcv", "fadd", "fsub", "fshl",
    "frecip",
    "cvt_i32", "packs16", "ONE_C", "HALF_C", "ADAA_TOL_C", "DCBLOCK_FAC_C",
    "OJD_M17_C", "OJD_P11_C", "OJD_M03_C", "OJD_P09_C",
    "OJD_DENLOW_C", "OJD_DENHIGH_C", "TANH_9_C", "TANH_27_C",
    "SINE_SIZE", "FUZZ_N", "SHAPER_INIT_WORDS", "SHAPER_INIT_BASE",
]
