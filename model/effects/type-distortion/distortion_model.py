"""SXT-028e frozen fixed-point model of the Surge XT Distortion effect.

Structure authority (READ + cited; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 — no code,
tables or assets copied):

  src/common/dsp/effects/DistortionEffect.{h,cpp}
      DistortionEffect::init / setvars / process; dist_OS_bits = 2
      (4x oversampled inner loop), the two peak-EQ bands (band1 pre,
      band2 post), the two deactivatable oversampled high-cut LP2B stages
      (lp1 pre-shaper, lp2 post-shaper), the one-pole-free feedback
      recurrence `L = Lin + fb*L`, the drive/outgain lipol ramps, the
      ringout output fade (ringout_time 1600, ringout_end 320), and the
      two-stage halfband decimation hr_a -> hr_b.
  src/common/dsp/Effect.{h,cpp}
      slowrate = 8 coefficient refresh (the `bi` counter);
      Effect::process_ringout (the `ringout` counter semantics).
  src/common/FilterConfiguration.h:235
      n_fxws = 8, FXWaveShapers = {soft, hard, asym, sine, digital, ojd,
      fwrectify, fuzzsoft}.
  libs/sst/sst-filters@e92d93a.../include/sst/filters/BiquadFilter.h
      calc_omega / coeff_peakEQ -> coeff_orfanidisEQ / coeff_LP2B /
      set_coef / coeff_instantize / process_block (TDF2, per-sample
      coefficient lag d = 0.004) / process_sample_nolag (no lag step).
  libs/sst/sst-filters@e92d93a.../include/sst/filters/HalfRateFilter.h
      HalfRateFilter(M = 3, steep)::process_block_D2 (two 3-stage allpass
      cascades per channel; y[n] = x[n-2] + a*(x[n] - y[n-2]); decimated
      output (B[2n] + A[2n+1]) * 0.5).
  src/common/dsp/vembertech/lipol.h -> lipol_sse<BLOCK_SIZE,false>
      set_target_smoothed / multiply_2_blocks / multiply_2_blocks_to.
  libs/sst/sst-waveshapers@dd12f31.../include/sst/waveshapers/
      WaveshaperTables.h + SurgeStorage::lookup_waveshape (see ws_tables.py).
  src/common/Parameter.cpp Parameter::get_extended
      (ct_decibel_extendable -> 3x, ct_decibel_narrow_extendable -> 5x).

CLAIM DISCIPLINE. This file is the frozen reference the SXT-028e RTL must
match EXACTLY (integer equality at declared checkpoints; separate claim).
Model-vs-pinned-engine agreement is a SEPARATE claim under [PROPOSED]
budgets that are not frozen (SXT-017, #12). Nothing here is a preset-support
or musical-quality claim.

Frozen word formats (model/effects/README.md family):
  Q10.21 s32  audio words, feedback registers, drive/outgain ramp products
  Q13.18 s32  block-rate gain ramps (drive, outgain)
  Q24.43 s64  biquad coefficients/lags/TDF2 state, halfband allpass
              coefficients and allpass state
  Q2.29  s32  waveshaper table words (ws_tables.py)
Products are exact and rounded round-half-up to the target format, then
saturated (model/effects/qmath.py). No floating point at audio run time;
double precision only at control (block) rate, quantized once.

PER-INSTANCE STATE. One `DistortionState` owns everything that carries
across blocks: both peak-EQ biquads, both oversampled LP biquads, both
halfband decimators, the two feedback registers L/R, the two lipol ramps,
and the `bi` slow-rate counter. Two configured Distortion slots are two
`DistortionState` objects; nothing is shared (AGENTS.md; issue #57
acceptance). Distortion owns NO delay-line-class buffer: there is no
external-memory residency at all (see tools/distortion_buffer_report.py).

DECLARED SCOPE OMISSIONS (fail-closed, never silently approximated):
  * FX model indices 3..7 (sine, digital, ojd, fwrectify, fuzzsoft) route
    through `GetQuadWaveshaper` (sst-waveshapers SSE quad path with its own
    registers, drive normalization and DC-offset probe). REFUSED here.
  * Parameter modulation INTO distortion parameters (block-constant
    parameters only; the `ringout` counter is an explicit per-block input).
  * The engine's +-1e-8 denormal bias `a = (k & 16) ? 1e-8 : -1e-8` is
    ~0.02 LSB at Q10.21 and is therefore NOT representable: fixed point has
    no denormals, so the bias has no function here. Declared deviation
    (bounded by 1 LSB of Q10.21, ~ -160 dBFS class).
"""

import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from model.effects.qmath import (  # noqa: E402
    FRAC, sat, qmul, qadd, qsub, to_q, clip,
)
from model.effects.delay.delay_model import (  # noqa: E402
    Biquad, Lipol, db_to_linear_d, note_to_pitch_ignoring_tuning_d,
    A_FMT, G_FMT, C_FMT, BLOCK, D_LP, D_LPINV,
)
from ws_tables import TABLES, WS_FMT, FROZEN_MODELS, FXWS_NAMES  # noqa: E402

MODEL_REVISION = None

SLOWRATE = 8                      # Effect.h:138
SLOWRATE_M1 = SLOWRATE - 1
DIST_OS_BITS = 2                  # DistortionEffect.cpp:27
DISTORTION_OS = 1 << DIST_OS_BITS
OS_BLOCK = BLOCK * DISTORTION_OS  # 128 oversampled samples per block
RINGOUT_TIME = 1600               # DistortionEffect.h:48
RINGOUT_END = 320
SAMPLERATE = 48000.0
MIN_BW = 0.0001                   # BiquadFilter minBW

ONE_A = 1 << FRAC[A_FMT]

# ---------------------------------------------------------------------------
# Halfband decimator coefficients (order 6 == M 3).
#
# QUOTED OPAQUE CONSTANTS. Unlike the waveshaper tables (re-derived from
# construction formulas) these twelve scalars have no construction formula in
# the pinned tree. They are quoted as data from
# libs/sst/sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6
# include/sst/filters/HalfRateFilter.h `load_coefficients()`
# (order == 6 branches), license GPL-3.0-or-later, under decision record
# decision-records/0012-distortion-halfband-and-waveshaper-tables.md, which
# is the SXT-028e successor to the ratified DR-0002 (the M = 6 steep set).
# Per DR-0002 clause 1 the RTL carries no independent copy: the quantized
# words are streamed to the testbench through its init file.
# ---------------------------------------------------------------------------
# hr_a = HalfRateFilter(3, false)  -- "softer slopes", rejection 80 dB
HB_A_SOFT = [0.06029739095712437, 0.4125907203610563, 0.7727156537429234]
HB_B_SOFT = [0.21597144456092948, 0.6043586264658363, 0.9238861386532906]
# hr_b = HalfRateFilter(3, true)   -- "steep", rejection 51 dB
HB_A_STEEP = [0.1271414136264853, 0.6528245886369117, 0.9176942834328115]
HB_B_STEEP = [0.40056789819445626, 0.8204163891923343, 0.9763114515836773]

HB_COEFFS_Q = [to_q(v, C_FMT) for v in
               (HB_A_SOFT + HB_B_SOFT + HB_A_STEEP + HB_B_STEEP)]


def _f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def get_extended(value, ctrltype, extend):
    """Parameter::get_extended for the two ctrltypes this effect uses."""
    if not extend:
        return value
    if ctrltype == "ct_decibel_extendable":
        return _f32(3.0) * value
    if ctrltype == "ct_decibel_narrow_extendable":
        return _f32(5.0) * value
    raise RuntimeError(f"get_extended: unhandled ctrltype {ctrltype}")


def calc_omega(scfreq):
    """BiquadFilter::calc_omega (double), sample rate 48 kHz."""
    return (2 * 3.14159265358979323846) * 440.0 * \
        note_to_pitch_ignoring_tuning_d(12.0 * scfreq) / SAMPLERATE


def _norm(a0, a1, a2, b0, b1, b2):
    inv = 1.0 / a0
    return [to_q(a1 * inv, C_FMT), to_q(a2 * inv, C_FMT), to_q(b0 * inv, C_FMT),
            to_q(b1 * inv, C_FMT), to_q(b2 * inv, C_FMT)]


def coeff_orfanidis_eq(omega, bw, g, gb, g0):
    """BiquadFilter::coeff_orfanidisEQ in double (pinned structure).

    Identical formula family to the landed SXT-023 EQ model
    (model/effects/eq/eq_model.py::_orfanidis); kept local so this leaf's
    frozen file is self-contained.
    """
    w0 = omega
    bw = max(MIN_BW, bw)
    dww = 2 * w0 * math.sinh((math.log(2.0) / 2.0) * bw)
    if abs(g - g0) > 0.00001:
        def sq(x):
            return x * x
        f = abs(g * g - gb * gb)
        g00 = abs(g * g - g0 * g0)
        f00 = abs(gb * gb - g0 * g0)
        num = g0 * g0 * sq(w0 * w0 - (math.pi * math.pi)) + \
            g * g * f00 * (math.pi * math.pi) * dww * dww / f
        den = sq(w0 * w0 - math.pi * math.pi) + f00 * math.pi * math.pi * dww * dww / f
        g1 = math.sqrt(num / den)
        g01 = abs(g * g - g0 * g1)
        g11 = abs(g * g - g1 * g1)
        f01 = abs(gb * gb - g0 * g1)
        f11 = abs(gb * gb - g1 * g1)
        w2 = math.sqrt(g11 / g00) * sq(math.tan(w0 / 2))
        w_lower = w0 * (2.0 ** (-0.5 * bw))
        w_upper = 2 * math.atan(math.sqrt(f00 / f11) * math.sqrt(g11 / g00) *
                                sq(math.tan(w0 / 2)) / math.tan(w_lower / 2))
        dw = abs(w_upper - w_lower)
        big_dw = (1 + math.sqrt(f00 / f11) * w2) * math.tan(dw / 2)
        c = f11 * big_dw * big_dw - 2 * w2 * (f01 - math.sqrt(f00 * f11))
        dd = 2 * w2 * (g01 - math.sqrt(g00 * g11))
        a = math.sqrt((c + dd) / f)
        b = math.sqrt((g * g * c + gb * gb * dd) / f)
        a0 = 1 + w2 + a
        a1 = -2 * (1 - w2)
        a2 = 1 + w2 - a
        b0 = g1 + g0 * w2 + b
        b1 = -2 * (g1 - g0 * w2)
        b2 = g1 - b + g0 * w2
        return _norm(a0, a1, a2, b0, b1, b2)
    return _norm(1, 0, 0, 1, 0, 0)


def coeff_peak_eq(omega, bw, gain_db):
    """BiquadFilter::coeff_peakEQ -> coeff_orfanidisEQ(.., G, GB, 1)."""
    return coeff_orfanidis_eq(omega, bw, db_to_linear_d(gain_db),
                              db_to_linear_d(gain_db * 0.5), 1.0)


def coeff_lp2b(omega, q):
    """BiquadFilter::coeff_LP2B in double (pinned structure)."""
    if omega > math.pi:
        return _norm(1, 0, 0, 1, 0, 0)
    w_sq = omega * omega
    den = (w_sq * w_sq) + (math.pi ** 4) + w_sq * (math.pi ** 2) * (1 / q - 2)
    g1 = min(1.0, math.sqrt((w_sq * w_sq) / den) * 0.5)
    cosi = math.cos(omega)
    sinu = math.sin(omega)
    alpha = sinu / (2 * q)
    a = 2 * math.sqrt(g1) * math.sqrt(2 - g1)
    b0 = (1 - cosi + g1 * (1 + cosi) + a * sinu) * 0.5
    b1 = (1 - cosi - g1 * (1 + cosi))
    b2 = (1 - cosi + g1 * (1 + cosi) - a * sinu) * 0.5
    a0 = (1 + alpha)
    a1 = -2 * cosi
    a2 = 1 - alpha
    return _norm(a0, a1, a2, b0, b1, b2)


class BiquadNoLag:
    """TDF2 stereo biquad with INSTANTIZED coefficients.

    `lp1`/`lp2` run `coeff_instantize()` on every coefficient refresh and
    then `process_sample_nolag` (no per-sample lag step), so the coefficient
    lag is always exactly the target. Reproduced here as a plain constant
    coefficient set + TDF2 registers (Q24.43).
    """

    def __init__(self):
        self.coeff = [0, 0, 0, 0, 0]     # a1 a2 b0 b1 b2 (Q24.43)
        self.reg0 = [0, 0]
        self.reg1 = [0, 0]

    def suspend(self):
        self.reg0 = [0, 0]
        self.reg1 = [0, 0]

    def set_coeff(self, c5):
        self.coeff = list(c5)

    def process_sample(self, inl, inr):
        a1, a2, b0, b1, b2 = self.coeff
        sh = FRAC[C_FMT] - FRAC[A_FMT]
        il = inl << sh
        op = qadd(qmul(il, b0, C_FMT, C_FMT, C_FMT), self.reg0[0], C_FMT)
        self.reg0[0] = qadd(qsub(qmul(il, b1, C_FMT, C_FMT, C_FMT),
                                 qmul(a1, op, C_FMT, C_FMT, C_FMT), C_FMT),
                            self.reg1[0], C_FMT)
        self.reg1[0] = qsub(qmul(il, b2, C_FMT, C_FMT, C_FMT),
                            qmul(a2, op, C_FMT, C_FMT, C_FMT), C_FMT)
        ir = inr << sh
        op2 = qadd(qmul(ir, b0, C_FMT, C_FMT, C_FMT), self.reg0[1], C_FMT)
        self.reg0[1] = qadd(qsub(qmul(ir, b1, C_FMT, C_FMT, C_FMT),
                                 qmul(a1, op2, C_FMT, C_FMT, C_FMT), C_FMT),
                            self.reg1[1], C_FMT)
        self.reg1[1] = qsub(qmul(ir, b2, C_FMT, C_FMT, C_FMT),
                            qmul(a2, op2, C_FMT, C_FMT, C_FMT), C_FMT)
        half = 1 << (sh - 1)
        return (sat((op + half) >> sh, A_FMT), sat((op2 + half) >> sh, A_FMT))


class HalfbandD2:
    """HalfRateFilter(M = 3, steep)::process_block_D2, scalar, stereo.

    The SIMD lane structure resolves, per channel, to two independent
    3-stage allpass cascades: lane 0/2 carry coefficient set A, lane 1/3
    carry coefficient set B (`set_coefficients`:
    `va[i] = set_ps(cB[i], cA[i], cB[i], cA[i])`, i.e. lane0 = cA).
    Per stage and sample the engine's shift sequence evaluates
        y[n] = x[n-2] + a * (x[n] - y[n-2])
    and the reconstruction stage computes, for output index n,
        out[n] = (B_cascade[2n] + A_cascade[2n+1]) * 0.5
    (`tL0 = broadcast(o[k][1])` = the B lane at the even sample, added to
    `o[k+1][0]` = the A lane at the odd sample; this matches the original
    `output = (filter_a.process(input) + oldout) * 0.5` comment the pinned
    header preserves above that code).

    Allpass state and coefficients are Q24.43; input/output words are
    Q10.21 rounded round-half-up at the cascade boundary.
    """

    STAGES = 3

    def __init__(self, ca_q, cb_q):
        self.ca = list(ca_q)
        self.cb = list(cb_q)
        # [channel][branch][stage] -> [x0,x1,x2] / [y0,y1,y2]  (Q24.43)
        self.x = [[[[0, 0, 0] for _ in range(self.STAGES)] for _ in range(2)]
                  for _ in range(2)]
        self.y = [[[[0, 0, 0] for _ in range(self.STAGES)] for _ in range(2)]
                  for _ in range(2)]

    def reset(self):
        for ch in range(2):
            for br in range(2):
                for j in range(self.STAGES):
                    self.x[ch][br][j] = [0, 0, 0]
                    self.y[ch][br][j] = [0, 0, 0]

    def _cascade(self, ch, br, coeffs, x_in):
        v = x_in
        for j in range(self.STAGES):
            xs = self.x[ch][br][j]
            ys = self.y[ch][br][j]
            y = qadd(xs[1], qmul(coeffs[j], qsub(v, ys[1], C_FMT),
                                 C_FMT, C_FMT, C_FMT), C_FMT)
            self.x[ch][br][j] = [v, xs[0], xs[1]]
            self.y[ch][br][j] = [y, ys[0], ys[1]]
            v = y
        return v

    def process(self, buf_l, buf_r):
        """n input Q10.21 words per channel -> n//2 output Q10.21 words."""
        sh = FRAC[C_FMT] - FRAC[A_FMT]
        half = 1 << (sh - 1)
        n = len(buf_l)
        out_l = [0] * (n // 2)
        out_r = [0] * (n // 2)
        # branch index 0 == coefficient set A (lane 0/2), 1 == set B (lane 1/3)
        for ch, (buf, out) in enumerate(((buf_l, out_l), (buf_r, out_r))):
            a_chain = [0] * n
            b_chain = [0] * n
            for i in range(n):
                xw = buf[i] << sh
                a_chain[i] = self._cascade(ch, 0, self.ca, xw)
                b_chain[i] = self._cascade(ch, 1, self.cb, xw)
            for m in range(n // 2):
                s = qadd(b_chain[2 * m], a_chain[2 * m + 1], C_FMT)
                s = s >> 1 if s >= 0 else -((-s) >> 1)   # * 0.5, exact
                out[m] = sat((s + half) >> sh, A_FMT)
        return out_l, out_r


def lookup_waveshape(table, x_a):
    """SurgeStorage::lookup_waveshape in fixed point.

    x_a is Q10.21; the table row is Q2.29; the result is Q10.21.
    Engine: `x *= 32; x += 512; e = (int)x; a = x - e;
             if (e > 0x3fd) return 1; if (e < 1) return -1;
             return (1-a)*T[e & 0x3ff] + a*T[(e+1) & 0x3ff];`
    Only e in [1, 0x3fd] reaches the table, so C truncation and floor
    coincide there; below 1 the rail fires first either way.
    """
    xs = (x_a << 5) + (512 << FRAC[A_FMT])        # Q21, exact (Python int)
    e = xs >> FRAC[A_FMT]                          # floor == trunc where used
    if e > 0x3fd:
        return ONE_A
    if e < 1:
        return -ONE_A
    frac = xs - (e << FRAC[A_FMT])                 # Q21 in [0, 1)
    t0 = table[e & 0x3ff]
    t1 = table[(e + 1) & 0x3ff]
    d = t1 - t0                                    # Q2.29
    # t0 + frac * d, frac as Q10.21 -> result Q2.29, then round to Q10.21
    res29 = qadd(t0, qmul(frac, d, A_FMT, WS_FMT, WS_FMT), WS_FMT)
    sh = FRAC[WS_FMT] - FRAC[A_FMT]
    return sat((res29 + (1 << (sh - 1))) >> sh, A_FMT)


class DistortionParams:
    """Frozen control-plane inputs for one Distortion instance.

    Values are the pinned loader's normalized float parameter values
    (`getParamVal`), the `deactivated` flags of the two high-cut params, and
    the three `extend_range` flags. Block-constant for a render: parameter
    modulation into distortion parameters is a declared scope omission.
    """

    KEYS = ("preeq_gain_f", "preeq_freq_f", "preeq_bw_f", "preeq_highcut_f",
            "drive_f", "feedback_f", "posteq_gain_f", "posteq_freq_f",
            "posteq_bw_f", "posteq_highcut_f", "gain_f", "model_i",
            "preeq_highcut_deactivated", "posteq_highcut_deactivated",
            "preeq_gain_extend", "posteq_gain_extend", "drive_extend")

    def __init__(self, d):
        missing = [k for k in self.KEYS if k not in d or d[k] is None]
        if missing:
            raise RuntimeError(
                "DistortionParams: fail-closed — unresolved control-plane "
                f"inputs {missing}. These come from the pinned loader's "
                "normalized state (tools/extract_distortion_inputs.py); they "
                "are never guessed or defaulted.")
        for k in self.KEYS:
            setattr(self, k, d[k])
        self.model_i = int(self.model_i)
        if self.model_i not in FROZEN_MODELS:
            raise RuntimeError(
                f"Distortion FX model index {self.model_i} "
                f"({FXWS_NAMES[self.model_i] if 0 <= self.model_i < 8 else '?'}) "
                "is outside the SXT-028e frozen scope (models 3..7 use the "
                "SSE quad-waveshaper path). Refusing — fail-closed; using a "
                "different shaper would be an ADAPTED effect, not this one.")


class DistortionState:
    """Per-instance distortion state. Two slots = two of these, never shared."""

    def __init__(self, name="distortion"):
        self.name = name
        self.band1 = Biquad()
        self.band2 = Biquad()
        self.lp1 = BiquadNoLag()
        self.lp2 = BiquadNoLag()
        self.hr_a = HalfbandD2(HB_COEFFS_Q[0:3], HB_COEFFS_Q[3:6])
        self.hr_b = HalfbandD2(HB_COEFFS_Q[6:9], HB_COEFFS_Q[9:12])
        self.drive = Lipol()
        self.outgain = Lipol()
        self.fb_l = 0          # DistortionEffect::L (Q10.21)
        self.fb_r = 0          # DistortionEffect::R
        self.bi = 0
        self.ext_reads = 0     # Distortion has NO external-memory state
        self.ext_writes = 0

    def checkpoint(self):
        """Declared state checkpoint (RTL/model integer equality)."""
        d = {
            "name": self.name,
            "bi": self.bi,
            "fb_l": self.fb_l, "fb_r": self.fb_r,
            "drive_tgt": self.drive.target, "og_tgt": self.outgain.target,
            "b1_lag": list(self.band1.lag), "b2_lag": list(self.band2.lag),
            "b1_reg0": list(self.band1.reg0), "b1_reg1": list(self.band1.reg1),
            "b2_reg0": list(self.band2.reg0), "b2_reg1": list(self.band2.reg1),
            "lp1_reg0": list(self.lp1.reg0), "lp1_reg1": list(self.lp1.reg1),
            "lp2_reg0": list(self.lp2.reg0), "lp2_reg1": list(self.lp2.reg1),
            "ext_reads": self.ext_reads, "ext_writes": self.ext_writes,
        }
        for tag, hb in (("hra", self.hr_a), ("hrb", self.hr_b)):
            for ch in range(2):
                for br in range(2):
                    for j in range(HalfbandD2.STAGES):
                        d[f"{tag}x{ch}{br}{j}"] = list(hb.x[ch][br][j])
                        d[f"{tag}y{ch}{br}{j}"] = list(hb.y[ch][br][j])
        return d


class DistortionModel:
    """One Distortion instance (DistortionEffect)."""

    def __init__(self, params: DistortionParams, name="distortion"):
        self.p = params
        self.st = DistortionState(name)
        self.table = TABLES[params.model_i]
        self.ctrl = {}
        self.initialized = False

    # ------------------------------------------------------------------
    # control rate
    # ------------------------------------------------------------------
    def _pregain(self):
        return get_extended(self.p.preeq_gain_f, "ct_decibel_extendable",
                            self.p.preeq_gain_extend)

    def _postgain(self):
        return get_extended(self.p.posteq_gain_f, "ct_decibel_extendable",
                            self.p.posteq_gain_extend)

    def _drive_db(self):
        return get_extended(self.p.drive_f, "ct_decibel_narrow_extendable",
                            self.p.drive_extend)

    def _setvars_false(self):
        """DistortionEffect::setvars(false) — the bi == 0 coefficient pass."""
        p = self.p
        self.st.band1.new_targets(coeff_peak_eq(
            calc_omega(p.preeq_freq_f / 12.0), p.preeq_bw_f, self._pregain()))
        self.st.band2.new_targets(coeff_peak_eq(
            calc_omega(p.posteq_freq_f / 12.0), p.posteq_bw_f, self._postgain()))
        # lp1/lp2 run at 4x: the engine compensates by shifting the scaled
        # frequency down two octaves while keeping the base-rate sampleRateInv.
        self.st.lp1.set_coeff(coeff_lp2b(
            calc_omega((p.preeq_highcut_f / 12.0) - _f32(2.0)), 0.707))
        self.st.lp2.set_coeff(coeff_lp2b(
            calc_omega((p.posteq_highcut_f / 12.0) - _f32(2.0)), 0.707))

    def initialize(self):
        """DistortionEffect::init() == suspend().

        setvars(true) first (band1/band2 coefficient targets from the stored
        parameter values; drive/outgain lipol targets smoothed from the
        constructor's zero target), then band1/band2/lp1/lp2 suspend() —
        which zeroes the TDF2 registers and re-arms first_run, so the first
        processed block's setvars(false) start-values the band coefficients.
        bi, L and R are zeroed. `initialize()` models the CONSTRUCTOR + init
        pair (the engine's fx-rebuild / suspend path: `spawn_effect` builds a
        fresh DistortionEffect and calls init()), so the halfband states and
        both lipol ramps start from their constructor state here — the
        halfband filters and lipols are not otherwise touched by init().
        """
        p = self.p
        self.st.drive = Lipol()
        self.st.outgain = Lipol()
        self.st.band1.new_targets(coeff_peak_eq(
            calc_omega(p.preeq_freq_f / 12.0), p.preeq_bw_f, self._pregain()))
        self.st.band2.new_targets(coeff_peak_eq(
            calc_omega(p.posteq_freq_f / 12.0), p.posteq_bw_f, self._postgain()))
        self.st.drive.set_target_smoothed(to_q(db_to_linear_d(self._drive_db()),
                                               G_FMT))
        self.st.outgain.set_target_smoothed(to_q(db_to_linear_d(p.gain_f),
                                                 G_FMT))
        self.st.band1.suspend()
        self.st.band2.suspend()
        self.st.lp1.suspend()
        self.st.lp2.suspend()
        self.st.hr_a.reset()
        self.st.hr_b.reset()
        self.st.bi = 0
        self.st.fb_l = 0
        self.st.fb_r = 0
        self.initialized = True

    @staticmethod
    def ringout_mul(ringout):
        """DistortionEffect::process ringout fade (double, control rate)."""
        if ringout > RINGOUT_TIME - RINGOUT_END:
            v = 1.0 * (RINGOUT_TIME - ringout - 1) / RINGOUT_END
            return clip(v, 0.0, 1.0)
        return 1.0

    def control_words(self):
        """The declared control-plane boundary (model -> RTL), one block.

        [0]  drive RAW lipol target            Q13.18 (RTL applies 0.25/0.75)
        [1]  outgain RAW lipol target          Q13.18 (ringoutMul folded in)
        [2]  feedback coefficient fb           Q10.21
        [3:8]   band1 coefficient targets      Q24.43
        [8:13]  band2 coefficient targets      Q24.43
        [13:18] lp1 instantized coefficients   Q24.43
        [18:23] lp2 instantized coefficients   Q24.43
        [23] flags: bit0 lp1 active, bit1 lp2 active
        """
        c = self.ctrl
        return ([c["drive_raw"], c["og_raw"], c["fb_q"]]
                + list(self.st.band1.tgt) + list(self.st.band2.tgt)
                + list(self.st.lp1.coeff) + list(self.st.lp2.coeff)
                + [int(c["lp1_on"]) | (int(c["lp2_on"]) << 1)])

    def init_words(self):
        """Plain setvars(true) lipol targets consumed by the RTL at reset."""
        st = DistortionState("probe")
        st.drive.set_target_smoothed(to_q(db_to_linear_d(self._drive_db()),
                                          G_FMT))
        st.outgain.set_target_smoothed(to_q(db_to_linear_d(self.p.gain_f),
                                            G_FMT))
        return [st.drive.target, st.outgain.target]

    # ------------------------------------------------------------------
    # audio rate
    # ------------------------------------------------------------------
    def process_block(self, in_l, in_r, ringout=0, tap_hook=None):
        """One 32-sample block. Returns (out_l, out_r) Q10.21.

        `ringout` is the engine's Effect::ringout counter for THIS block
        (0 while input is present; incremented by the host once the FX bus
        goes silent). The caller owns that counter; the declared tail span
        is RINGOUT_TIME (1600) blocks == 1.0667 s at 48 kHz.
        """
        if not self.initialized:
            self.initialize()
        st, p = self.st, self.p

        if st.bi == 0:
            self._setvars_false()
        st.bi = (st.bi + 1) & SLOWRATE_M1

        # 1. band1.process_block (pre-EQ, lagged TDF2, base rate)
        work_l = [0] * BLOCK
        work_r = [0] * BLOCK
        for k in range(BLOCK):
            work_l[k], work_r[k] = st.band1.process_sample(in_l[k], in_r[k])

        # 2. drive: dS = previous target, dE = the new raw value
        d_s = st.drive.target
        d_e = to_q(db_to_linear_d(self._drive_db()), G_FMT)
        st.drive.set_target_smoothed(d_e)

        # 3. outgain target with the ringout fade folded in (control rate)
        rmul = self.ringout_mul(ringout)
        og_raw = to_q(db_to_linear_d(p.gain_f) * rmul, G_FMT)
        st.outgain.set_target_smoothed(og_raw)

        fb_q = to_q(clip(p.feedback_f, -1.0, 1.0), A_FMT)
        lp1_on = not p.preeq_highcut_deactivated
        lp2_on = not p.posteq_highcut_deactivated
        self.ctrl = {"drive_raw": d_e, "og_raw": og_raw, "fb_q": fb_q,
                     "lp1_on": lp1_on, "lp2_on": lp2_on,
                     "ringout": ringout, "ringout_mul": rmul, "d_s": d_s}

        # 4. drive.multiply_2_blocks (in place, base rate)
        for k in range(BLOCK):
            g = st.drive.line_value(k)
            work_l[k] = qmul(g, work_l[k], G_FMT, A_FMT, A_FMT)
            work_r[k] = qmul(g, work_r[k], G_FMT, A_FMT, A_FMT)

        # 5. 4x oversampled feedback + shaper loop
        b_l = [0] * OS_BLOCK
        b_r = [0] * OS_BLOCK
        for k in range(BLOCK):
            l_in = work_l[k]
            r_in = work_r[k]
            for s in range(DISTORTION_OS):
                st.fb_l = qadd(l_in, qmul(fb_q, st.fb_l, A_FMT, A_FMT, A_FMT),
                               A_FMT)
                st.fb_r = qadd(r_in, qmul(fb_q, st.fb_r, A_FMT, A_FMT, A_FMT),
                               A_FMT)
                if lp1_on:
                    st.fb_l, st.fb_r = st.lp1.process_sample(st.fb_l, st.fb_r)
                st.fb_l = lookup_waveshape(self.table, st.fb_l)
                st.fb_r = lookup_waveshape(self.table, st.fb_r)
                # engine denormal bias +-1e-8: below the Q10.21 LSB, declared
                if lp2_on:
                    st.fb_l, st.fb_r = st.lp2.process_sample(st.fb_l, st.fb_r)
                idx = s + (k << DIST_OS_BITS)
                b_l[idx] = st.fb_l
                b_r[idx] = st.fb_r
                if tap_hook is not None and k < 4:
                    tap_hook(k, s, st.fb_l, st.fb_r)

        # 6. two-stage halfband decimation: 128 -> 64 -> 32
        b_l, b_r = st.hr_a.process(b_l, b_r)
        b_l, b_r = st.hr_b.process(b_l, b_r)

        # 7. outgain.multiply_2_blocks_to + band2 (post-EQ)
        out_l = [0] * BLOCK
        out_r = [0] * BLOCK
        for k in range(BLOCK):
            g = st.outgain.line_value(k)
            out_l[k] = qmul(g, b_l[k], G_FMT, A_FMT, A_FMT)
            out_r[k] = qmul(g, b_r[k], G_FMT, A_FMT, A_FMT)
        for k in range(BLOCK):
            out_l[k], out_r[k] = st.band2.process_sample(out_l[k], out_r[k])
        return out_l, out_r


def model_revision():
    """sha256 of this file (frozen-revision pin for traces/harnesses)."""
    import hashlib
    global MODEL_REVISION
    if MODEL_REVISION is None:
        with open(os.path.abspath(__file__), "rb") as f:
            MODEL_REVISION = hashlib.sha256(f.read()).hexdigest()
    return MODEL_REVISION


__all__ = ["DistortionModel", "DistortionParams", "DistortionState",
           "HalfbandD2", "BiquadNoLag", "lookup_waveshape", "model_revision",
           "HB_COEFFS_Q", "RINGOUT_TIME", "RINGOUT_END", "BLOCK", "OS_BLOCK",
           "A_FMT", "G_FMT", "C_FMT", "SLOWRATE"]
