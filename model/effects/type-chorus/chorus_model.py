"""SXT-028c frozen fixed-point model of the Surge XT Chorus effect.

Structure authority (READ, cited; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 — no code or
tables copied):

  src/common/dsp/effects/ChorusEffect.h + ChorusEffectImpl.h
      ChorusEffect<4>: init / setvars / process (the pinned engine
      instantiates v = 4 voices, Effect.cpp:86; the sst-effects
      include/sst/effects/Chorus.h at the sst-effects pin is an EMPTY
      header in this pin — the native ChorusEffect is the algorithm
      authority, as the pinned-engine loader also uses it).
  src/common/dsp/vembertech/lipol.h -> lipol_sse<BLOCK_SIZE, false>
      (same BlockInterpolators ramp as the delay model's Lipol)
  libs/sst/sst-basic-blocks/.../Lag.h  OnePoleLag<float,true>
      (time[j] lags, rate 0.001, first-run snap)
  libs/sst/sst-filters/.../BiquadFilter.h (shared with Delay/EQ models:
      TDF2 + per-sample coefficient lag d_lp = 0.004, coeff_HP /
      coeff_LP2B at Q = 0.707, calc_omega)
  libs/sst/sst-basic-blocks/.../Clippers.h hardclip_block (min/max +-1)
  src/common/dsp/Effect.h applyStereoWidth + MidSide.h encodeMS/decodeMS
  libs/sst/sst-basic-blocks/.../tables/SincTableProvider.h
      (SurgeStorage::sinctable1X IS this provider's table; the chorus
      model reuses model/effects/delay/sinc_table.py unchanged)

Engine structure (ChorusEffectImpl.h process, cited order):
  setvars(false) once per block: feedback lipol target = 0.5*amp_to_linear,
  rate = envelope_rate_linear(-rate)*(temposync ? temposyncratio : 1),
  tm = note_to_pitch_ignoring_tuning(12*time)*(temposync ? ratio_inv : 1),
  per voice j: lfophase[j] += rate (wrap >1), lfoout =
  (2*|2*lfophase-1| - 1)*depth, time[j].newValue(samplerate*tm*(1+lfoout));
  hp/lp coefficients from lowcut/highcut; mix/width lipol targets.
  Per sample k: per voice j: time[j].process(); i_dtime =
  max(BLOCK_SIZE, min((int)time[j].v, max-FIRipol_N-1)); rp =
  ((wpos-i_dtime+k)-FIRipol_N) & (max-1); 12-tap sinc interpolation from
  the MONO line (UNMASKED reads: buffer holds max+FIRipol_N words and the
  padding words buffer[max..max+11] are refreshed with buffer[0..11] only
  when wpos == 0 — the engine's wrap-read staleness is reproduced exactly,
  NOT masked away); voice output panned by fixed sqrt-law voicepanL/R
  (gainscale 1/sqrt(v)); lp (highcut gate) then hp (lowcut gate) on the
  wet block; fbblock = wetL + wetR, feedback ramp, HARDCLIP +-1, += input;
  line write at wpos (+ padding copy when wpos == 0); width (mid/side);
  mix crossfade dry*(1-t)+wet*t; wpos += BLOCK_SIZE (masked).

Frozen word formats (model/effects/README.md):
  audio/line words Q10.21 s32; sinc table Q2.29 s32 (delay/sinc_table.py);
  block-rate gain ramps + voicepan Q13.18 s32; biquad + time-lag +
  lfophase/lfo rate Q24.43 s64. Products exact, round-half-up
  (model/effects/qmath.py); no floating point at audio run time; double
  only at control rate, quantized once.

Per-instance state: one ChorusState holds the mono line, wpos, all four
voice lags/phases, both biquads and all ramps. Two configured Chorus slots
are two ChorusState objects with two disjoint lines (issue #55 acceptance;
AGENTS.md per-instance rule). Arithmetic may be shared only observably.

Declared control-plane boundary (model -> RTL): block-rate quantities are
computed here (double, quantized once) and streamed: feedback/mix/width
lipol RAW targets (the RTL applies the 0.25/0.75 smoothing recurrence),
the four per-voice time-lag targets (already including the LFO term — the
lfophase accumulators, the LFO rate and the depth are control-plane), the
10 biquad coefficient targets and the flags word. The RTL computes
everything audio-rate: per-voice lag recurrences, i_dtime/sinc phase/tap
reads, panning sums, TDF2 filters, hardclip, feedback MAC, line
write/padding copy, width, crossfade.

Declared deviations (bounded, absorbed by the model-vs-reference budgets):
  * engine float32 audio/state arithmetic -> Q10.21/Q13.18/Q24.43
    (<= 1 LSB-class per op; the delay/EQ/reverb1 models declare the same);
  * lag state held Q24.43 (engine float32 lag state);
  * lfophase held Q24.43 (engine double; quantized once at init, phase
    wrap keeps the error bounded and non-accumulating);
  * LFO rate quantized through the engine's float32 storage of `rate`
    before Q24.43 (f32(0.001)-class fidelity);
  * control-rate formulas (envelope_rate_linear, note_to_pitch,
    db_to_linear, biquad coefficient builds, voicepan sqrt law) evaluated
    in double; the engine evaluates table lookups in float32.
  * parameter modulation INTO the chorus parameters is outside the frozen
    scope (fail-closed; no fixture uses it).
"""

import math
import struct as _struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model.effects.qmath import (  # noqa: E402
    FRAC, sat, qadd, qsub, qmul, to_q, clip,
)
from model.effects.delay.sinc_table import (  # noqa: E402
    TABLE_Q, FIRIPOL_M, FIRIPOL_N,
)
from model.effects.delay.delay_model import (  # noqa: E402
    Biquad, Lipol, db_to_linear_d, note_to_pitch_ignoring_tuning_d,
    envelope_rate_linear_d, A_FMT, G_FMT, C_FMT, BLOCK,
)

A_FRAC = FRAC[A_FMT]
G_FRAC = FRAC[G_FMT]
C_FRAC = FRAC[C_FMT]

MAX_DELAY = 1 << 18                 # Effect.h max_delay_length
LINE_LEN = MAX_DELAY + FIRIPOL_N    # allocated words per instance (mono)
LINE_MASK = MAX_DELAY - 1
MIN_DT = BLOCK                      # i_dtime lower clamp
MAX_DT = MAX_DELAY - FIRIPOL_N - 1  # i_dtime upper clamp
VOICES = 4                          # Effect.cpp:86 ChorusEffect<4>
HARD_CLIP = 1 << A_FRAC             # hardclip_block +-1.0 in Q10.21
ONE_C = 1 << C_FRAC                 # 1.0 in Q24.43 (lfophase wrap: > 1 -> -= 1)
ONE_G = 1 << G_FRAC
HALF_A = 1 << (A_FRAC - 1)
# tap MAC word: sinc(Q2.29) x line(Q10.21) = Q50, then x voicepan(Q13.18)
# = Q68 linear-magnitude accumulator; the Q10.21 word is value x 2^21,
# i.e. shift 68-21 = 47, rounded half-up once
SINC_SHIFT = 29 + G_FRAC                     # 68 - 21
HALF_AC = 1 << (SINC_SHIFT - 1)

# engine lag pair is float32 (ChorusEffect init: time[i].setRate(0.001))
def _f32(x):
    return _struct.unpack("f", _struct.pack("f", x))[0]


LP_TIME = to_q(_f32(0.001), C_FMT)                    # float32 0.001f
LPINV_TIME = to_q(_f32(1.0 - _f32(0.001)), C_FMT)     # float32 (1 - 0.001f)

# frozen-revision pin: sha256 of this file, embedded in every trace and
# checked by the RTL comparator (stale harnesses refuse to report PASS)
MODEL_REVISION = None  # set at import bottom


def voice_pan_q():
    """ChorusEffect<4>::init voicepan law, quantized once (Q13.18).

    x = i/(v-1); lfophase[i] = x; x = 2x-1; gainscale = 1/sqrt(v);
    voicepan[i] = (sqrt(0.5-0.5x), sqrt(0.5+0.5x)) * gainscale.
    """
    gainscale = 1.0 / math.sqrt(VOICES)
    pans = []
    for i in range(VOICES):
        x = float(i) / float(VOICES - 1)
        x = 2.0 * x - 1.0
        pans.append((to_q(math.sqrt(0.5 - 0.5 * x) * gainscale, G_FMT),
                     to_q(math.sqrt(0.5 + 0.5 * x) * gainscale, G_FMT)))
    return pans


VOICE_PAN = voice_pan_q()


class ChorusParams:
    """Frozen control-plane inputs for one chorus instance (block-constant;
    parameter modulation into these values is out of frozen scope)."""

    def __init__(self, d):
        self.time_f = d["time_f"]
        self.rate_f = d["rate_f"]
        self.depth_f = d["depth_f"]
        self.feedback_f = d["feedback_f"]
        self.lowcut_f = d["lowcut_f"]
        self.highcut_f = d["highcut_f"]
        self.mix_f = d["mix_f"]
        self.width_f = d["width_f"]
        self.lowcut_deactivated = d.get("lowcut_deactivated", False)
        self.highcut_deactivated = d.get("highcut_deactivated", False)
        self.ts_time = d.get("ts_time", False)
        self.ts_rate = d.get("ts_rate", False)
        self.ts_ratio = d.get("ts_ratio", 1.0)        # temposyncratio_inv
        self.ts_ratio_mod = d.get("ts_ratio_mod", 1.0)  # temposyncratio


class ChorusLipol(Lipol):
    """lipol_sse with the plain (non-smoothed) set_target of the engine's
    ChorusEffect init path: current = old target; target = f."""

    def set_target_plain(self, f):
        self.current = self.target
        self.target = f


class ChorusState:
    """Per-instance chorus state: two slots = two of these, never shared."""

    def __init__(self, name="chorus"):
        self.name = name
        self.line = [0] * LINE_LEN            # MONO line incl. padding words
        self.wpos = 0
        self.lfophase = [0] * VOICES          # Q24.43 (engine: double)
        self.time = [Lag() for _ in range(VOICES)]
        self.lp = Biquad()
        self.hp = Biquad()
        self.feedback = ChorusLipol()
        self.mix = ChorusLipol()
        self.width_s = ChorusLipol()
        self.line_hash = 0                    # additive per-instance integrity
        self.ext_reads = 0
        self.ext_writes = 0
        self.initialized = False

    def checkpoint(self):
        return {
            "name": self.name,
            "wpos": self.wpos,
            "lfophase": list(self.lfophase),
            "time_v": [t.v for t in self.time],
            "time_tgt": [t.target for t in self.time],
            "lp_lag": list(self.lp.lag), "hp_lag": list(self.hp.lag),
            "lp_reg0": list(self.lp.reg0), "lp_reg1": list(self.lp.reg1),
            "hp_reg0": list(self.hp.reg0), "hp_reg1": list(self.hp.reg1),
            "fb_tgt": self.feedback.target, "mix_tgt": self.mix.target,
            "ws_tgt": self.width_s.target,
            "line_hash": self.line_hash & ((1 << 64) - 1),
            "ext_reads": self.ext_reads,
            "ext_writes": self.ext_writes,
        }


class Lag:
    """OnePoleLag<float,true> at rate 0.001 (ChorusEffect init), Q24.43.

    Same class as the delay model's time lag; lp/lpinv are the float32
    pair quantized. first_run semantics: the first set_target snaps v.
    """

    def __init__(self):
        self.v = 0
        self.target = 0
        self.lp = LP_TIME
        self.lpinv = LPINV_TIME
        self.first_run = True

    def set_target(self, f):
        self.target = f
        if self.first_run:
            self.v = f
            self.first_run = False

    def process(self):
        self.v = qadd(qmul(self.v, self.lpinv, C_FMT, C_FMT, C_FMT),
                      qmul(self.target, self.lp, C_FMT, C_FMT, C_FMT), C_FMT)


def hardclip(x):
    """Clippers.h hardclip_block: min(max(x,-1),1) in Q10.21."""
    return clip(x, -HARD_CLIP, HARD_CLIP)


class ChorusModel:
    """One chorus instance; audio-rate datapath + block control pass."""

    def __init__(self, params: ChorusParams, name="chorus"):
        self.p = params
        self.st = ChorusState(name)
        self.ctrl = {}

    # ---------------- control pass (ChorusEffect setvars) ------------------
    def _control_init(self):
        """setvars(true) (ChorusEffect init): plain lipol targets and
        biquad coefficients; the time lags are NOT touched here (their
        first newValue happens in the first process block, where the
        first-run snap applies)."""
        p, st = self.p, self.st
        fb = 0.5 * max(0.0, p.feedback_f) ** 3          # 0.5*amp_to_linear
        st.feedback.set_target_plain(to_q(fb, G_FMT))
        st.mix.set_target_plain(to_q(p.mix_f, G_FMT))
        st.width_s.set_target_plain(to_q(db_to_linear_d(p.width_f), G_FMT))
        self._coeffs()
        self.ctrl = {
            "fb_raw": to_q(fb, G_FMT),
            "mix_raw": to_q(p.mix_f, G_FMT),
            "ws_raw": to_q(db_to_linear_d(p.width_f), G_FMT),
            "time_tgts": [st.time[j].target for j in range(VOICES)],
            "lp_on": not p.highcut_deactivated,
            "hp_on": not p.lowcut_deactivated,
        }

    def _control(self):
        """setvars(false), once per process block."""
        p, st = self.p, self.st
        fb = 0.5 * max(0.0, p.feedback_f) ** 3          # 0.5*amp_to_linear
        st.feedback.set_target_smoothed(to_q(fb, G_FMT))

        rate = envelope_rate_linear_d(-p.rate_f)
        if p.ts_rate:
            rate = rate * p.ts_ratio_mod
        rate_q = to_q(_f32(rate), C_FMT)                # engine stores float32

        tm = note_to_pitch_ignoring_tuning_d(12.0 * p.time_f)
        if p.ts_time:
            tm = tm * p.ts_ratio

        for j in range(VOICES):
            st.lfophase[j] = qadd(st.lfophase[j], rate_q, C_FMT)
            if st.lfophase[j] > ONE_C:
                st.lfophase[j] = qsub(st.lfophase[j], ONE_C, C_FMT)
            # lfoout = (2*|2*phi-1| - 1) * depth, double at control rate
            a = 2.0 * (st.lfophase[j] / float(1 << C_FRAC)) - 1.0
            lfoout = (2.0 * abs(a) - 1.0) * p.depth_f
            tgt = sat(to_q(48000.0 * tm * (1.0 + lfoout), C_FMT), C_FMT)
            st.time[j].set_target(tgt)

        st.mix.set_target_smoothed(to_q(p.mix_f, G_FMT))
        st.width_s.set_target_smoothed(to_q(db_to_linear_d(p.width_f), G_FMT))
        self._coeffs()

        ctrl = {
            "fb_raw": to_q(fb, G_FMT),
            "mix_raw": to_q(p.mix_f, G_FMT),
            "ws_raw": to_q(db_to_linear_d(p.width_f), G_FMT),
            "time_tgts": [st.time[j].target for j in range(VOICES)],
            "lp_on": not p.highcut_deactivated,
            "hp_on": not p.lowcut_deactivated,
        }
        self.ctrl = ctrl
        return ctrl

    def _coeffs(self):
        """hp (lowcut, coeff_HP) + lp (highcut, coeff_LP2B), Q=0.707."""
        p = self.p
        omega_lp = 2 * math.pi * 440.0 * \
            note_to_pitch_ignoring_tuning_d(p.highcut_f) / 48000.0
        omega_hp = 2 * math.pi * 440.0 * \
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
        if omega > math.pi:
            return cls._norm(1, 0, 0, 0, 0, 0)
        cosi, sinu = math.cos(omega), math.sin(omega)
        alpha = sinu / (2 * q)
        return cls._norm(1 + alpha, -2 * cosi, 1 - alpha,
                         (1 + cosi) * 0.5, -(1 + cosi), (1 + cosi) * 0.5)

    # ---------------- public API -------------------------------------------
    def initialize(self):
        """ChorusEffect ctor+init(): fresh-instance state (fx load).
        No instantize: the engine's chorus never instantizes its ramps or
        lags; the first block ramps from the zero constructor state."""
        st = self.st
        st.line = [0] * LINE_LEN
        st.line_hash = 0
        st.wpos = 0
        st.lfophase = [to_q(float(i) / float(VOICES - 1), C_FMT)
                       for i in range(VOICES)]
        st.time = [Lag() for _ in range(VOICES)]
        st.lp.suspend()
        st.hp.suspend()
        st.ext_reads = 0
        st.ext_writes = 0
        self._control_init()
        self.initialized = True

    def process_block(self, in_l, in_r, tap_hook=None, wet_hook=None):
        """One 32-sample block (ChorusEffect process). in/out Q10.21 lists.

        tap_hook(k, [(i_dtime, phase, rp) per voice]) is called per sample
        when set (RTL tap-interpolation checkpoint capture). wet_hook(tb_l,
        tb_r) is called once after the voice-sum loop and before the
        lp/hp filters (observation only; neither hook affects arithmetic).
        """
        st = self.st
        if not self.initialized:
            self.initialize()
        ctrl = self._control()

        tb_l = [0] * BLOCK
        tb_r = [0] * BLOCK
        for k in range(BLOCK):
            acc_l = 0
            acc_r = 0
            taps = []
            for j in range(VOICES):
                t = st.time[j]
                t.process()
                v = t.v
                i_dt = clip(v >> C_FRAC if v >= 0 else -((-v) >> C_FRAC),
                            MIN_DT, MAX_DT)
                rp = ((st.wpos - i_dt + k) - FIRIPOL_N) & LINE_MASK
                diff = ((i_dt + 1) << C_FRAC) - v
                if diff >= 0:
                    ph = (diff * FIRIPOL_M) >> C_FRAC
                else:
                    ph = -(((-diff) * FIRIPOL_M) >> C_FRAC)
                ph = clip(ph, 0, FIRIPOL_M - 1)
                taps.append((i_dt, ph, rp))
                base = ph * FIRIPOL_N
                vo = 0
                for tt in range(FIRIPOL_N):
                    vo += TABLE_Q[base + tt] * st.line[rp + tt]  # UNMASKED
                st.ext_reads += FIRIPOL_N
                acc_l += VOICE_PAN[j][0] * vo
                acc_r += VOICE_PAN[j][1] * vo
            if tap_hook is not None:
                tap_hook(k, taps)
            tb_l[k] = sat((acc_l + HALF_AC) >> SINC_SHIFT, A_FMT)
            tb_r[k] = sat((acc_r + HALF_AC) >> SINC_SHIFT, A_FMT)

        if wet_hook is not None:
            wet_hook(tb_l, tb_r)

        # highcut gate -> lp, then lowcut gate -> hp (process order)
        if ctrl["lp_on"]:
            for k in range(BLOCK):
                tb_l[k], tb_r[k] = st.lp.process_sample(tb_l[k], tb_r[k])
        if ctrl["hp_on"]:
            for k in range(BLOCK):
                tb_l[k], tb_r[k] = st.hp.process_sample(tb_l[k], tb_r[k])

        # feedback path: ONE mono fbblock = (wetL + wetR) -> feedback ramp ->
        # hardclip -> += dataL -> += dataR (ChorusEffectImpl.h writes the
        # same fbblock array; it is not a stereo pair)
        fbblock = [0] * BLOCK
        for k in range(BLOCK):
            fb = qadd(tb_l[k], tb_r[k], A_FMT)
            fb = hardclip(st.feedback.mul_sample(st.feedback.line_value(k), fb))
            fb = qadd(fb, in_l[k], A_FMT)
            fb = qadd(fb, in_r[k], A_FMT)
            fbblock[k] = fb

        # line write + padding copy when wpos == 0 (engine semantics)
        for k in range(BLOCK):
            w0 = (st.wpos + k) & LINE_MASK
            old = st.line[w0]
            st.line[w0] = fbblock[k]
            st.line_hash += fbblock[k] - old
        st.ext_writes += BLOCK
        if st.wpos == 0:
            for t in range(FIRIPOL_N):
                old = st.line[MAX_DELAY + t]
                st.line[MAX_DELAY + t] = st.line[t]
                st.line_hash += st.line[t] - old
                st.ext_writes += 1

        # width (applyStereoWidth: M/S halving exact, side ramped)
        for k in range(BLOCK):
            l_v, r_v = tb_l[k], tb_r[k]
            m = l_v + r_v
            m = m >> 1 if m >= 0 else -((-m) >> 1)
            s = l_v - r_v
            s = s >> 1 if s >= 0 else -((-s) >> 1)
            ss = st.width_s.mul_sample(st.width_s.line_value(k), s)
            tb_l[k] = qadd(m, ss, A_FMT)
            tb_r[k] = qsub(m, ss, A_FMT)

        # mix crossfade (fade_2_blocks_inplace: dry*(1-t) + wet*t)
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


def model_revision():
    """sha256 of this file (frozen-revision pin for traces/harnesses)."""
    import hashlib
    global MODEL_REVISION
    if MODEL_REVISION is None:
        path = os.path.abspath(__file__)
        with open(path, "rb") as f:
            MODEL_REVISION = hashlib.sha256(f.read()).hexdigest()
    return MODEL_REVISION
