"""NEGATIVE CONTROL (b) — NOT the frozen model: nearest-neighbor tap
substitution of the 12-tap sinc read. Must FAIL the model-vs-reference
budget check.

Derived from the frozen docstring:

Structure authority (READ, cited; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 — no code or
tables copied):

  libs/sst/sst-effects/include/sst/effects/Delay.h
      Delay<FXConfig>::initialize / setvars / processBlock   (structure)
      max_delay_length = 1<<18, buffer[2][max+FIRipol_N]
  libs/sst/sst-basic-blocks/.../SincTableProvider.h          (table formula)
  libs/sst/sst-basic-blocks/.../Lag.h       OnePoleLag::process (lag form)
  libs/sst/sst-basic-blocks/.../BlockInterpolators.h lipol_sse
      set_target_smoothed / updateLine / trixpan_blocks / fade / MAC
  libs/sst/sst-filters/.../BiquadFilter.h coeff_LP2B/coeff_HP/set_coef/
      process_block (TDF2, per-sample coefficient lag d_lp = 0.004)
  libs/sst/sst-basic-blocks/.../Clippers.h softclip_block
  src/common/dsp/effects/SurgeSSTFXAdapter.h (parameter access semantics)

Frozen word formats (model/effects/README.md):
  audio/line words Q10.21 s32; sinc table Q2.29 s32; block-rate gain ramps
  Q13.18 s32; biquad + delay-time + LFO state Q24.43 s64. Products are exact
  and rounded round-half-up to the target format (model/effects/qmath.py).

Per-instance state: one DelayState holds BOTH channel lines, position, LFO,
lags and filters. Two configured Delay slots are two DelayState objects; no
line or smoother state is shared between instances (issue #16 acceptance).

The declared control-plane boundary: block-rate TARGETS (gain lipol targets,
time-lag targets, LFO increment/rate, biquad coefficient targets, flags) are
computed here (double, quantized once) and streamed to the RTL. The RTL
reproduces the complete audio-rate datapath and all audio-rate state
recurrences (time lags, LFO value/phase, coefficient lags, TDF2 state, line).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model.effects.qmath import (  # noqa: E402
    FRAC, sat, qmul, qadd, qsub, to_q, clip,
)
from model.effects.delay.sinc_table import (  # noqa: E402
    TABLE_Q, FIRIPOL_M, FIRIPOL_N, FIR_OFFSET, SINC_FMT,
)

A_FMT = "Q10.21"      # audio words
G_FMT = "Q13.18"      # gain ramps
C_FMT = "Q24.43"      # coefficient/lag/LFO words

MAX_DELAY = 1 << 18                 # Delay.h max_delay_length
LINE_LEN = MAX_DELAY + FIRIPOL_N    # allocated words per channel
LINE_MASK = MAX_DELAY - 1
BLOCK = 32
MIN_DT = BLOCK                      # i_dtime lower clamp (Delay.h:348)
MAX_DT = MAX_DELAY - FIRIPOL_N - 1  # i_dtime upper clamp (Delay.h:349)

# constants (pinned from the cited sources; float32 values quantized)
CA = to_q(0.99, C_FMT)                       # Delay.h:286 const float ca = 0.99f
LFO_BIAS = to_q(1e-11, C_FMT)                # Delay.h:281 denormal-avoidance bias
# The engine's time lag is SurgeLag<float>: lp = 0.0001f, lpinv = 1 - lp computed
# in FLOAT32. The pair does not sum to exactly 1 (sum = 1 + 7.46e-11), so the
# engine's lag state drifts slightly above its constant target during long
# silent stretches, which selects sinc phase 127 rather than 128 at v = 181.5.
# The frozen model reproduces the drift with the same quantized pair.
import struct as _struct


def _f32(x):
    return _struct.unpack("f", _struct.pack("f", x))[0]


LP_TIME = to_q(_f32(0.0001), C_FMT)                    # float32 0.0001f
LPINV_TIME = to_q(_f32(1.0 - _f32(0.0001)), C_FMT)     # float32 (1 - 0.0001f)
D_LP = to_q(0.004, C_FMT)                              # BiquadFilter d_lp (double)
D_LPINV = to_q(1.0 - 0.004, C_FMT)
SOFTCLIP_A = to_q(-4.0 / 27.0, A_FMT)        # Clippers.h softclip_ps a
ONE_G = 1 << FRAC[G_FMT]
CLIP_HI = 1 << (FRAC[A_FMT] + 2)             # softclip bound 1.5 in Q10.21
CLIP_LO = -CLIP_HI
HALF_C = 1 << (FRAC[C_FMT] - 1)              # 0.5 in Q24.43 (lfophase wrap)

# clipping modes (Delay.h delay_clipping_modes); deform_type of dly_feedback
CLIP_OFF, CLIP_SOFT, CLIP_TANH, CLIP_HARD, CLIP_HARD18 = 0, 1, 2, 3, 4


class Biquad:
    """sst-filters BiquadFilter TDF2 with per-sample coefficient lag (stereo)."""

    def __init__(self):
        self.lag = [0, 0, 0, 0, 0]      # a1 a2 b0 b1 b2 (Q24.43)
        self.tgt = [0, 0, 0, 0, 0]
        self.reg0 = [0, 0]              # L, R
        self.reg1 = [0, 0]
        self.first_run = True

    def suspend(self):
        self.lag = [0, 0, 0, 0, 0]
        self.tgt = [0, 0, 0, 0, 0]
        self.reg0 = [0, 0]
        self.reg1 = [0, 0]
        self.first_run = True

    def new_targets(self, c5):
        """c5 = [a1,a2,b0,b1,b2] (Q24.43, normalized)."""
        if self.first_run:
            self.tgt = list(c5)
            self.lag = list(c5)
            self.first_run = False
            return
        self.tgt = list(c5)

    def instantize(self):
        self.lag = list(self.tgt)

    def instantize(self):
        self.lag = list(self.tgt)

    def step_lags(self):
        for i in range(5):
            self.lag[i] = qadd(qmul(self.lag[i], D_LPINV, C_FMT, C_FMT, C_FMT),
                               qmul(self.tgt[i], D_LP, C_FMT, C_FMT, C_FMT), C_FMT)

    def process_sample(self, inl, inr):
        """Return (outl, outr) Q10.21; in/out audio words."""
        self.step_lags()
        a1, a2, b0, b1, b2 = self.lag
        il = inl << (FRAC[C_FMT] - FRAC[A_FMT])
        op = qadd(qmul(il, b0, C_FMT, C_FMT, C_FMT), self.reg0[0], C_FMT)
        self.reg0[0] = qadd(qsub(qmul(il, b1, C_FMT, C_FMT, C_FMT),
                                 qmul(a1, op, C_FMT, C_FMT, C_FMT), C_FMT),
                            self.reg1[0], C_FMT)
        self.reg1[0] = qsub(qmul(il, b2, C_FMT, C_FMT, C_FMT),
                            qmul(a2, op, C_FMT, C_FMT, C_FMT), C_FMT)
        ir = inr << (FRAC[C_FMT] - FRAC[A_FMT])
        op2 = qadd(qmul(ir, b0, C_FMT, C_FMT, C_FMT), self.reg0[1], C_FMT)
        self.reg0[1] = qadd(qsub(qmul(ir, b1, C_FMT, C_FMT, C_FMT),
                                 qmul(a1, op2, C_FMT, C_FMT, C_FMT), C_FMT),
                            self.reg1[1], C_FMT)
        self.reg1[1] = qsub(qmul(ir, b2, C_FMT, C_FMT, C_FMT),
                            qmul(a2, op2, C_FMT, C_FMT, C_FMT), C_FMT)
        # engine: data[k] = op (double->float round-to-nearest); model: round-half-up
        half = 1 << (FRAC[C_FMT] - FRAC[A_FMT] - 1)
        ol = sat((op + half) >> (FRAC[C_FMT] - FRAC[A_FMT]), A_FMT)
        orr = sat((op2 + half) >> (FRAC[C_FMT] - FRAC[A_FMT]), A_FMT)
        return ol, orr


class Lag:
    """OnePoleLag<float,true> (Lag.h) in Q24.43.

    lp/lpinv are the float32 pair (lp, 1-lp) quantized; their quantized sum is
    not exactly 2^FRAC, reproducing the engine's slow lag drift. The engine
    holds v itself in FLOAT32, so the tap phase derived from v jitters on the
    float32 grid; use f32grid() before deriving i_dtime/phase."""

    def __init__(self, lp=LP_TIME, lpinv=LPINV_TIME):
        self.v = 0
        self.target = 0
        self.lp = lp
        self.lpinv = lpinv
        self.first_run = True

    def set_target(self, f):
        self.target = f
        if self.first_run:
            self.v = f
            self.first_run = False

    def instantize(self):
        self.v = self.target

    def process(self):
        self.v = qadd(qmul(self.v, self.lpinv, C_FMT, C_FMT, C_FMT),
                      qmul(self.target, self.lp, C_FMT, C_FMT, C_FMT), C_FMT)


class Lipol:
    """lipol_sse block ramp (BlockInterpolators.h) in Q13.18.

    set_target_smoothed: target = 0.25*f + 0.75*target; the per-sample line
    ramps linearly from the previous target to the new one, line[i] =
    current + (target-current)*(i+1)/32 (updateLine semantics).
    """

    def __init__(self):
        self.target = 0
        self.current = 0
        self.first_run = True

    def set_target_smoothed(self, f):
        q25 = 1 << (FRAC[G_FMT] - 2)
        q75 = 3 << (FRAC[G_FMT] - 2)
        self.current = self.target
        self.target = qadd(qmul(q25, f, G_FMT, G_FMT, G_FMT),
                           qmul(q75, self.target, G_FMT, G_FMT, G_FMT), G_FMT)
        if self.first_run:
            # lipol_sse has first_run_checks=false in Surge; the constructor
            # state is target=current=0. The effects instantize() at init().
            self.first_run = False

    def set_target_instant(self, f):
        self.target = f
        self.current = f

    def instantize(self):
        self.current = self.target

    def line_value(self, i):
        d = self.target - self.current
        return self.current + ((d * (i + 1) + (1 << 4)) >> 5) if d >= 0 \
            else self.current - ((-d * (i + 1) + (1 << 4)) >> 5)

    def mul_sample(self, g, x):
        return qmul(g, x, G_FMT, A_FMT, A_FMT)


class DelayState:
    """Per-instance delay state: two slots = two of these, never shared."""

    def __init__(self, name="delay"):
        self.name = name
        self.line = [[0] * LINE_LEN, [0] * LINE_LEN]   # [ch][word] Q10.21
        self.wpos = 0
        self.lfophase = 0            # Q24.43 (engine: double)
        self.lfoval = 0              # Q24.43
        self.lfo_dir = True
        self.fb_sign = False
        self.time_l = Lag()
        self.time_r = Lag()
        self.lp = Biquad()
        self.hp = Biquad()
        self.feedback = Lipol()
        self.crossfeed = Lipol()
        self.mix = Lipol()
        self.pan = Lipol()
        self.width_s = Lipol()
        self.line_hash = 0           # additive per-instance line integrity sum
        self.ext_reads = 0           # traffic counters (ext-mem interface)
        self.ext_writes = 0
        self.initialized = False

    # ---- state checkpoint -------------------------------------------------
    def checkpoint(self):
        return {
            "name": self.name,
            "wpos": self.wpos,
            "lfophase": self.lfophase,
            "lfoval": self.lfoval,
            "lfo_dir": int(self.lfo_dir),
            "fb_sign": int(self.fb_sign),
            "time_l_v": self.time_l.v, "time_l_tgt": self.time_l.target,
            "time_r_v": self.time_r.v, "time_r_tgt": self.time_r.target,
            "lp_lag": list(self.lp.lag), "hp_lag": list(self.hp.lag),
            "lp_reg0": list(self.lp.reg0), "lp_reg1": list(self.lp.reg1),
            "hp_reg0": list(self.hp.reg0), "hp_reg1": list(self.hp.reg1),
            "fb_tgt": self.feedback.target, "cf_tgt": self.crossfeed.target,
            "mix_tgt": self.mix.target, "pan_tgt": self.pan.target,
            "ws_tgt": self.width_s.target,
            "line_hash": self.line_hash & ((1 << 64) - 1),
            "ext_reads": self.ext_reads,
            "ext_writes": self.ext_writes,
        }


def softclip(x):
    """Clippers.h softclip_ps in fixed point: x - (4/27)x^3 on [-1.5, 1.5]."""
    if x > CLIP_HI:
        return CLIP_HI
    if x < CLIP_LO:
        return CLIP_LO
    xx = qmul(x, x, A_FMT, A_FMT, A_FMT)
    t = qmul(qmul(x, SOFTCLIP_A, A_FMT, A_FMT, A_FMT), xx, A_FMT, A_FMT, A_FMT)
    return qadd(x, t, A_FMT)


class DelayParams:
    """Frozen control-plane inputs for one delay instance (block-constant for
    a render; modulation into these parameters is out of the chosen fixtures'
    scope and declared unsupported by this model run)."""

    def __init__(self, d):
        # float32 parameter values as read from the engine (post-load)
        self.time_l_f = d["time_l_f"]
        self.time_r_f = d["time_r_f"]
        self.feedback_f = d["feedback_f"]
        self.crossfeed_f = d["crossfeed_f"]
        self.lowcut_f = d["lowcut_f"]
        self.highcut_f = d["highcut_f"]
        self.mod_rate_f = d["mod_rate_f"]
        self.mod_depth_f = d["mod_depth_f"]
        self.input_ch_f = d["input_ch_f"]
        self.mix_f = d["mix_f"]
        self.width_f = d["width_f"]
        self.time_r_deactivated = d["time_r_deactivated"]
        self.lowcut_deactivated = d["lowcut_deactivated"]
        self.highcut_deactivated = d["highcut_deactivated"]
        self.feedback_extend = d["feedback_extend"]
        self.crossfeed_extend = d["crossfeed_extend"]
        self.mod_depth_extend = d["mod_depth_extend"]
        self.ts_ratio = d.get("ts_ratio", 1.0)       # temposyncratio_inv applied
        self.ts_ratio_mod = d.get("ts_ratio_mod", 1.0)  # temposyncRatio for rate
        self.clipping_mode = d.get("clipping_mode", CLIP_SOFT)


# --- double-precision control-rate helpers (pinned formulas; quantized once) --

def db_to_linear_d(x):
    """SurgeStorage::db_to_linear table-lerp formula in double."""
    fx = x + 384.0
    e = int(fx)
    a = fx - e
    lo = 10.0 ** (0.05 * (e - 384))
    hi = 10.0 ** (0.05 * (e + 1 - 384))
    return (1 - a) * lo + a * hi


def note_to_pitch_ignoring_tuning_d(x):
    """SurgeStorage::note_to_pitch_ignoring_tuning formula in double.

    The engine shifts FIRST: xs = limit(x + 256, 0, 511-1e-4); e=(int)xs;
    a = xs-e (a >= 0 always); table_pitch_ignoring_tuning[e] * lerp of
    table_two_to_the at a*1000; i.e. 2^((e-256)/12) * 2^(a) with the
    thousandths-step lerp.
    """
    xs = clip(x + 256.0, 0.0, 511 - 1e-4)
    e = int(xs)
    a = xs - e
    pow2pos = a * 1000.0
    p2i = int(pow2pos)
    p2f = pow2pos - p2i
    # table_two_to_the[i] = 2^(i/12000): the fraction is interpolated in
    # SEMITONE twelfths (SurgeStorage.cpp init_tables), not octave thousandths
    t_lo = 2.0 ** (p2i / 12000.0)
    t_hi = 2.0 ** ((p2i + 1) / 12000.0)
    return (2.0 ** ((e - 256) / 12.0)) * ((1 - p2f) * t_lo + p2f * t_hi)

def envelope_rate_linear_d(x):
    """SurgeStorage::envelope_rate_linear formula in double.

    table_envrate_linear[i] = 1/(dsamplerate_os * 2^((i-256)/16) / BLOCK_SIZE_OS)
    with dsamplerate_os = samplerate * OSC_OVERSAMPLING = 96000 and
    BLOCK_SIZE_OS = 64 at the pinned build (globals.h OSC_OVERSAMPLING = 2)."""
    x = x * 16.0 + 256.0
    e = int(x)
    a = x - e
    dsamplerate_os = 96000.0
    block_os = 64.0

    def rate2(i):
        return 1.0 / (dsamplerate_os * (2.0 ** ((i - 256.0) / 16.0)) / block_os)
    e0, e1 = e & 0x1FF, (e + 1) & 0x1FF
    return (1 - a) * rate2(e0) + a * rate2(e1)


class DelayModel:
    """One delay instance; audio-rate datapath + block control pass."""

    def __init__(self, params: DelayParams, name="delay"):
        self.p = params
        self.st = DelayState(name)
        # control-plane words recomputed per block (streamed to RTL)
        self.ctrl = {}

    # ---------------- control pass (Delay.h setvars) -----------------------
    def _control(self, init):
        p, st = self.p, self.st
        fbp = p.feedback_f
        fb_sign = False
        if p.feedback_extend:
            fbp = 2.0 * fbp - 1.0
            if fbp < 0.0:
                fb_sign = True
        fb = max(0.0, abs(fbp)) ** 3                      # amp_to_linear
        cfv = p.crossfeed_f
        if p.crossfeed_extend:
            cfv = 4.0 * cfv - 2.0                          # extend factors 2, -1
            cfv = clip(cfv, -1.0, 1.0)
        cf = max(0.0, cfv) ** 3
        st.fb_sign = fb_sign

        # feedback/crossfeed targets first (Delay.h:268-269)
        st.feedback.set_target_smoothed(to_q(fb, G_FMT))
        st.crossfeed.set_target_smoothed(to_q(cf, G_FMT))

        # lfophase / LFOval advance BEFORE the time targets (Delay.h:271-291)
        lforate = envelope_rate_linear_d(-p.mod_rate_f) * p.ts_ratio_mod
        st.lfophase = qadd(st.lfophase, to_q(lforate, C_FMT), C_FMT)
        if st.lfophase > HALF_C:
            st.lfophase = qsub(st.lfophase, 1 << FRAC[C_FMT], C_FMT)
            st.lfo_dir = not st.lfo_dir
        lfo_inc = (1e-11 + 2.0 ** (self._depth_extended() * (1.0 / 12.0)) - 1.0) * BLOCK
        lfo_inc_q = to_q(lfo_inc, C_FMT)
        if st.lfo_dir:
            st.lfoval = qadd(qmul(st.lfoval, CA, C_FMT, C_FMT, C_FMT), lfo_inc_q, C_FMT)
        else:
            st.lfoval = qsub(qmul(st.lfoval, CA, C_FMT, C_FMT, C_FMT), lfo_inc_q, C_FMT)

        is_linked = p.time_r_deactivated
        t_src_l = p.time_l_f
        t_src_r = p.time_r_f if not is_linked else p.time_l_f
        base_l = 48000.0 * p.ts_ratio * note_to_pitch_ignoring_tuning_d(12.0 * t_src_l)
        base_r = 48000.0 * p.ts_ratio * note_to_pitch_ignoring_tuning_d(12.0 * t_src_r)

        ctrl = {
            "fb_tgt": to_q(fb, G_FMT),
            "cf_tgt": to_q(cf, G_FMT),
            "mix_tgt": to_q(p.mix_f, G_FMT),
            "pan_tgt": to_q(clip(p.input_ch_f, -1.0, 1.0), G_FMT),
            "ws_tgt": to_q(db_to_linear_d(p.width_f), G_FMT),
            "lfo_rate": to_q(lforate, C_FMT),
            "lfo_inc": lfo_inc_q,
            "time_l_tgt": sat(to_q(base_l, C_FMT) + st.lfoval - to_q(FIR_OFFSET, C_FMT), C_FMT),
            "time_r_tgt": sat(to_q(base_r, C_FMT) - st.lfoval - to_q(FIR_OFFSET, C_FMT), C_FMT),
            "lp_on": not p.highcut_deactivated,
            "hp_on": not p.lowcut_deactivated,
            "fb_sign": fb_sign,
            "clip_mode": p.clipping_mode,
        }
        st.time_l.set_target(ctrl["time_l_tgt"])
        st.time_r.set_target(ctrl["time_r_tgt"])
        st.mix.set_target_smoothed(ctrl["mix_tgt"])
        st.pan.set_target_smoothed(ctrl["pan_tgt"])
        st.width_s.set_target_smoothed(ctrl["ws_tgt"])
        self._coeffs()

        if init:
            st.time_l.instantize()
            st.time_r.instantize()
            st.feedback.instantize()
            st.crossfeed.instantize()
            st.mix.instantize()
            st.pan.instantize()
            st.width_s.instantize()
            st.lp.instantize()
            st.hp.instantize()
        self.ctrl = ctrl
        return ctrl

    def _depth_extended(self):
        p = self.p
        return 6.0 * p.mod_depth_f if p.mod_depth_extend else p.mod_depth_f

    def _coeffs(self):
        """lp (highcut LP2B) + hp (lowcut HP), Q=0.707 (Delay.h:314-315)."""
        p = self.p
        omega_lp = 2 * 3.14159265358979323846 * 440.0 * \
            note_to_pitch_ignoring_tuning_d(p.highcut_f) / 48000.0
        omega_hp = 2 * 3.14159265358979323846 * 440.0 * \
            note_to_pitch_ignoring_tuning_d(p.lowcut_f) / 48000.0
        self.st.lp.new_targets(self._lp2b(omega_lp, 0.707))
        self.st.hp.new_targets(self._hp(omega_hp, 0.707))

    @staticmethod
    def _norm(a0, a1, a2, b0, b1, b2):
        inv = 1.0 / a0
        return [to_q(a1 * inv, C_FMT), to_q(a2 * inv, C_FMT), to_q(b0 * inv, C_FMT),
                to_q(b1 * inv, C_FMT), to_q(b2 * inv, C_FMT)]

    @classmethod
    def _lp2b(cls, omega, q):
        import math
        if omega > math.pi:
            return cls._norm(1, 0, 0, 1, 0, 0)
        w2 = omega * omega
        den = w2 * w2 + math.pi ** 4 + w2 * math.pi ** 2 * (1 / q - 2)
        g1 = min(1.0, (math.sqrt(w2 * w2 / den)) * 0.5)
        cosi, sinu = math.cos(omega), math.sin(omega)
        alpha = sinu / (2 * q)
        a_amp = 2 * math.sqrt(g1) * math.sqrt(2 - g1)
        return cls._norm(1 + alpha, -2 * cosi, 1 - alpha,
                         (1 - cosi + g1 * (1 + cosi) + a_amp * sinu) * 0.5,
                         (1 - cosi - g1 * (1 + cosi)),
                         (1 - cosi + g1 * (1 + cosi) - a_amp * sinu) * 0.5)

    @classmethod
    def _hp(cls, omega, q):
        import math
        if omega > math.pi:
            return cls._norm(1, 0, 0, 0, 0, 0)
        cosi, sinu = math.cos(omega), math.sin(omega)
        alpha = sinu / (2 * q)
        return cls._norm(1 + alpha, -2 * cosi, 1 - alpha,
                         (1 + cosi) * 0.5, -(1 + cosi), (1 + cosi) * 0.5)

    # ---------------- public API -------------------------------------------
    def initialize(self):
        """Delay.h initialize(): fresh-instance state (fx load)."""
        st = self.st
        st.line = [[0] * LINE_LEN, [0] * LINE_LEN]
        st.line_hash = 0
        st.wpos = 0
        st.lfophase = 0
        st.lfoval = 0
        st.lfo_dir = True
        st.fb_sign = False
        st.lp.suspend()
        st.hp.suspend()
        st.ext_reads = 0
        st.ext_writes = 0
        self._pending_inithadtempo = True
        self.initialized = True

    def process_block(self, in_l, in_r):
        """One 32-sample block (Delay.h processBlock). in/out: Q10.21 lists."""
        st = self.st
        p = self.p
        if not self.initialized:
            self.initialize()

        init = False
        if getattr(self, "_pending_inithadtempo", False):
            # inithadtempo=false on a fresh standalone instance; the first
            # control pass sees temposyncInitialized() true -> instantize
            init = True
            self._pending_inithadtempo = False

        ctrl = self._control(init)

        tb_l = [0] * BLOCK
        tb_r = [0] * BLOCK
        for k in range(BLOCK):
            st.time_l.process()
            st.time_r.process()
            vl, vr = st.time_l.v, st.time_r.v
            i_dt_l = clip(vl >> FRAC[C_FMT] if vl >= 0 else -((-vl) >> FRAC[C_FMT]), MIN_DT, MAX_DT)
            i_dt_r = clip(vr >> FRAC[C_FMT] if vr >= 0 else -((-vr) >> FRAC[C_FMT]), MIN_DT, MAX_DT)
            rp_l = ((st.wpos - i_dt_l + k) - FIRIPOL_N) & LINE_MASK
            rp_r = ((st.wpos - i_dt_r + k) - FIRIPOL_N) & LINE_MASK
            # sinc phase: (int)(FIRipol_M * (float(i_dtime+1) - time.v)) clamp
            def sinc_phase(i_dt, v):
                diff = ((i_dt + 1) << FRAC[C_FMT]) - v
                ph = (diff * FIRIPOL_M) >> FRAC[C_FMT] if diff >= 0 else \
                    -(((-diff) * FIRIPOL_M) >> FRAC[C_FMT])
                return clip(ph, 0, FIRIPOL_M - 1)
            sp_l = sinc_phase(i_dt_l, vl)
            sp_r = sinc_phase(i_dt_r, vr)
            base_l = sp_l * FIRIPOL_N
            base_r = sp_r * FIRIPOL_N
            # MUTANT (b): nearest-neighbor tap — no sinc interpolation
            acc_l = st.line[0][(base_l + FIR_OFFSET) & LINE_MASK]
            acc_r = st.line[1][(base_r + FIR_OFFSET) & LINE_MASK]
            st.ext_reads += 2
            tb_l[k] = sat(acc_l, A_FMT)
            tb_r[k] = sat(acc_r, A_FMT)

        # negative feedback (Delay.h:384-389)
        if ctrl["fb_sign"]:
            tb_l = [sat(-x, A_FMT) for x in tb_l]
            tb_r = [sat(-x, A_FMT) for x in tb_r]

        # feedback path clipping mode (Delay.h:391-413)
        mode = ctrl["clip_mode"]
        if mode == CLIP_SOFT:
            tb_l = [softclip(x) for x in tb_l]
            tb_r = [softclip(x) for x in tb_r]
        elif mode == CLIP_HARD:
            tb_l = [clip(x, -(1 << FRAC[A_FMT]), 1 << FRAC[A_FMT]) for x in tb_l]
            tb_r = [clip(x, -(1 << FRAC[A_FMT]), 1 << FRAC[A_FMT]) for x in tb_r]
        elif mode == CLIP_HARD18:
            tb_l = [clip(x, -(8 << FRAC[A_FMT]), 8 << FRAC[A_FMT]) for x in tb_l]
            tb_r = [clip(x, -(8 << FRAC[A_FMT]), 8 << FRAC[A_FMT]) for x in tb_r]
        elif mode == CLIP_TANH:
            raise NotImplementedError("tanh7 clipping mode not in frozen scope;"
                                      " chosen presets use soft clip (deform=1)")

        # highcut LP / lowcut HP (Delay.h:415-423)
        if ctrl["lp_on"]:
            for k in range(BLOCK):
                tb_l[k], tb_r[k] = st.lp.process_sample(tb_l[k], tb_r[k])
        if ctrl["hp_on"]:
            for k in range(BLOCK):
                tb_l[k], tb_r[k] = st.hp.process_sample(tb_l[k], tb_r[k])

        # write buffer: trixpan + feedback MAC + crossfeed MAC (Delay.h:425-428)
        wb_l = [0] * BLOCK
        wb_r = [0] * BLOCK
        for k in range(BLOCK):
            a = max(st.pan.line_value(k), 0)
            b = min(st.pan.line_value(k), 0)
            l_in = in_l[k]
            r_in = in_r[k]
            one_minus_a = qsub(ONE_G, a, G_FMT)
            one_plus_b = qadd(ONE_G, b, G_FMT)
            wb_l[k] = qsub(qmul(one_minus_a, l_in, G_FMT, A_FMT, A_FMT),
                           qmul(b, r_in, G_FMT, A_FMT, A_FMT), A_FMT)
            wb_r[k] = qadd(qmul(a, l_in, G_FMT, A_FMT, A_FMT),
                           qmul(one_plus_b, r_in, G_FMT, A_FMT, A_FMT), A_FMT)
        for k in range(BLOCK):
            wb_l[k] = qadd(wb_l[k], st.feedback.mul_sample(st.feedback.line_value(k), tb_l[k]), A_FMT)
            wb_r[k] = qadd(wb_r[k], st.feedback.mul_sample(st.feedback.line_value(k), tb_r[k]), A_FMT)
            wb_r[k] = qadd(wb_r[k], st.crossfeed.mul_sample(st.crossfeed.line_value(k), tb_l[k]), A_FMT)
            wb_l[k] = qadd(wb_l[k], st.crossfeed.mul_sample(st.crossfeed.line_value(k), tb_r[k]), A_FMT)

        # line write (per-instance, per-channel) + traffic + running hash
        for k in range(BLOCK):
            w0 = (st.wpos + k) & LINE_MASK
            old0 = st.line[0][w0]
            st.line[0][w0] = wb_l[k]
            st.line_hash += wb_l[k] - old0
            old1 = st.line[1][w0]
            st.line[1][w0] = wb_r[k]
            st.line_hash += wb_r[k] - old1
        st.ext_writes += BLOCK * 2

        # width (Delay.h:455 + WidthProvider/applyWidth: S scaled, M intact)
        for k in range(BLOCK):
            l_v, r_v = tb_l[k], tb_r[k]
            m = (l_v + r_v)
            m = m >> 1 if m >= 0 else -((-m) >> 1)
            m = sat(m, A_FMT)
            s = (l_v - r_v)
            s = s >> 1 if s >= 0 else -((-s) >> 1)
            s = sat(s, A_FMT)
            ss = st.width_s.mul_sample(st.width_s.line_value(k), s)
            tb_l[k] = qadd(m, ss, A_FMT)
            tb_r[k] = qsub(m, ss, A_FMT)

        # mix crossfade (Delay.h:457): out = dry*(1-t) + wet*t
        out_l = [0] * BLOCK
        out_r = [0] * BLOCK
        for k in range(BLOCK):
            m = st.mix.line_value(k)
            inv = qsub(ONE_G, m, G_FMT)
            out_l[k] = qadd(qmul(inv, in_l[k], G_FMT, A_FMT, A_FMT),
                            qmul(m, tb_l[k], G_FMT, A_FMT, A_FMT), A_FMT)
            out_r[k] = qadd(qmul(inv, in_r[k], G_FMT, A_FMT, A_FMT),
                            qmul(m, tb_r[k], G_FMT, A_FMT, A_FMT), A_FMT)

        st.wpos = (st.wpos + BLOCK) & LINE_MASK
        return out_l, out_r
