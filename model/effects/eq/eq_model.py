"""SXT-023 frozen fixed-point model of the Surge XT 3-band parametric EQ.

Structure authority (READ, cited; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 — no code or
tables copied):

  src/common/dsp/effects/ParametricEQ3BandEffect.{h,cpp}
      init/setvars/process (slowrate = 8 coefficient refresh, bi counter,
      band deactivation on eq3_gainN, gain lipol, mix crossfade)
  libs/sst/sst-filters/.../BiquadFilter.h
      calc_omega / coeff_peakEQ -> coeff_orfanidisEQ / set_coef /
      process_block (TDF2 in double, per-sample coefficient lag d_lp=0.004,
      shared L/R coefficients, flush_denormal)
  src/common/dsp/vembertech/lipol.h -> lipol_sse (same algorithm as the
      sst BlockInterpolators ramp used by the delay model)
  src/common/dsp/effects/SurgeSSTFXAdapter.h (floatValue semantics)

Frozen formats: audio Q10.21 s32; biquad coefficients/lags/state Q24.43 s64
(the engine is double-precision here; Q24.43 keeps 1e-13-class agreement);
gain ramps Q13.18. Rounding is round-half-up (model/effects/qmath.py).

Per-instance state: bands, registers, lags and ramps live in EqState; no
state is shared between effect instances.

Out of the frozen scope (fail-closed, not silently approximated): parameter
modulation into EQ params, graphic-EQ (11-band) and conditioner variants.
"""

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model.effects.qmath import FRAC, sat, qadd, qsub, qmul, to_q, clip  # noqa: E402
from model.effects.delay.delay_model import (  # noqa: E402
    Biquad, Lipol, db_to_linear_d, note_to_pitch_ignoring_tuning_d,
    A_FMT, G_FMT, C_FMT, BLOCK,
)

SLOWRATE = 8          # Effect.h:138 const int slowrate = 8
SLOWRATE_M1 = SLOWRATE - 1
MIN_BW = 0.0001       # BiquadFilter minBW


class EqParams:
    """Frozen control-plane inputs for one EQ instance (block-constant)."""

    def __init__(self, d):
        self.gain_f = [d["gain1_f"], d["gain2_f"], d["gain3_f"]]
        self.freq_f = [d["freq1_f"], d["freq2_f"], d["freq3_f"]]
        self.bw_f = [d["bw1_f"], d["bw2_f"], d["bw3_f"]]
        self.band_deactivated = [d["gain1_deactivated"], d["gain2_deactivated"],
                                 d["gain3_deactivated"]]
        self.gain_out_f = d["gain_f"]     # output gain (dB)
        self.mix_f = d["mix_f"]


class EqState:
    def __init__(self, name="eq"):
        self.name = name
        self.bands = [Biquad(), Biquad(), Biquad()]
        self.bi = 0
        self.gain = Lipol()
        self.mix = Lipol()
        self.initialized = False

    def checkpoint(self):
        return {
            "name": self.name,
            "bi": self.bi,
            "band_lag": [list(b.lag) for b in self.bands],
            "band_reg0": [list(b.reg0) for b in self.bands],
            "band_reg1": [list(b.reg1) for b in self.bands],
            "gain_tgt": self.gain.target,
            "mix_tgt": self.mix.target,
        }


class EqModel:
    """One EQ instance (ParametricEQ3BandEffect)."""

    def __init__(self, params: EqParams, name="eq"):
        self.p = params
        self.st = EqState(name)
        self.ctrl = {}

    # ---------------- control pass (setvars) -------------------------------
    def _coeffs(self):
        """bandN.coeff_peakEQ(calc_omega(freq/12), bw, gainN) as Q24.43."""
        for b_i in range(3):
            omega = 2 * math.pi * 440.0 * \
                note_to_pitch_ignoring_tuning_d(12.0 * (self.p.freq_f[b_i] * (1.0 / 12.0))) / 48000.0
            g = db_to_linear_d(self.p.gain_f[b_i])
            gb = db_to_linear_d(self.p.gain_f[b_i] * 0.5)
            c5 = self._orfanidis(omega, self.p.bw_f[b_i], g, gb, 1.0)
            self.st.bands[b_i].new_targets(c5)

    @staticmethod
    def _norm(a0, a1, a2, b0, b1, b2):
        inv = 1.0 / a0
        return [to_q(a1 * inv, C_FMT), to_q(a2 * inv, C_FMT), to_q(b0 * inv, C_FMT),
                to_q(b1 * inv, C_FMT), to_q(b2 * inv, C_FMT)]

    @classmethod
    def _orfanidis(cls, omega, bw, g, gb, g0):
        """BiquadFilter::coeff_orfanidisEQ in double (pinned structure)."""
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
            return cls._norm(a0, a1, a2, b0, b1, b2)
        return cls._norm(1, 0, 0, 1, 0, 0)

    def initialize(self):
        """ParametricEQ3BandEffect::init() at fx load: setvars(true) then
        band.suspend() for every band (lags zeroed, first_run set) and bi = 0.
        The first processed block re-runs setvars(false) with the real
        parameters; startValue instantizes to those targets (set_coef
        first_run path)."""
        for b in self.st.bands:
            b.suspend()
        self.st.bi = 0
        self.st.gain.set_target_instant(to_q(1.0, G_FMT))
        self.st.mix.set_target_instant(to_q(1.0, G_FMT))
        self.initialized = True

    def process_block(self, in_l, in_r):
        st = self.st
        p = self.p
        if not self.initialized:
            self.initialize()

        # bi == 0 -> refresh coefficient targets (setvars(false))
        if st.bi == 0:
            self._coeffs()
        st.bi = (st.bi + 1) & SLOWRATE_M1

        # output gain + mix targets refresh every block (process():99-102)
        st.gain.set_target_smoothed(to_q(db_to_linear_d(p.gain_out_f), G_FMT))
        st.mix.set_target_smoothed(to_q(clip(p.mix_f, -1.0, 1.0), G_FMT))

        work_l = list(in_l)
        work_r = list(in_r)
        dry_l, dry_r = in_l, in_r

        for b_i in range(3):
            if p.band_deactivated[b_i]:
                continue
            band = st.bands[b_i]
            wl = [0] * BLOCK
            wr = [0] * BLOCK
            for k in range(BLOCK):
                wl[k], wr[k] = band.process_sample(work_l[k], work_r[k])
            work_l, work_r = wl, wr

        # output gain (gain.multiply_2_blocks)
        out_l = [0] * BLOCK
        out_r = [0] * BLOCK
        for k in range(BLOCK):
            g = st.gain.line_value(k)
            out_l[k] = qmul(g, work_l[k], G_FMT, A_FMT, A_FMT)
            out_r[k] = qmul(g, work_r[k], G_FMT, A_FMT, A_FMT)

        # mix crossfade (mix.fade_2_blocks_inplace(dry, eq))
        for k in range(BLOCK):
            m = st.mix.line_value(k)
            inv = qsub((1 << FRAC[G_FMT]), m, G_FMT)
            out_l[k] = qadd(qmul(inv, dry_l[k], G_FMT, A_FMT, A_FMT),
                            qmul(m, out_l[k], G_FMT, A_FMT, A_FMT), A_FMT)
            out_r[k] = qadd(qmul(inv, dry_r[k], G_FMT, A_FMT, A_FMT),
                            qmul(m, out_r[k], G_FMT, A_FMT, A_FMT), A_FMT)
        return out_l, out_r
