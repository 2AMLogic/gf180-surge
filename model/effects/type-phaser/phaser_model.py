"""SXT-028g frozen fixed-point model of the Surge XT Phaser effect.

Structure authority (READ + cited; GPL-3.0-or-later trees pinned by
oracle/manifest.json — NO code, tables or assets copied into this
repository):

  libs/sst/sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b
      include/sst/effects/Phaser.h
          Phaser<FXConfig>: initialize / init_stages / setvars /
          processBlock / getRingoutDecay, the legacy_freq/legacy_span
          spans, the (i+1)*2/n_stages spread law and the 2/(i+1) LFO
          shift, the +-32 feedback clamp, the tone -> lp/hp cutoff map.
      include/sst/effects/EffectCore.h
          EffectTemplateBase: slowrate = 8 (setvars runs on bi == 0),
          useLinearWidth() == false for the Surge FXConfig.
      include/sst/effects-shared/WidthProvider.h
          setWidthTarget -> widthS.set_target_smoothed(dbToLinear(width));
          applyWidth -> encodeMS / widthS.multiply_block(S) / decodeMS
          (widthM is NOT applied: useLinearWidth() is false).
  libs/sst/sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96
      include/sst/basic-blocks/modulators/FXModControl.h
          FXModControl<32> (RandomBehavior rnd_dual_stereo): lfophase
          accumulate + fmod, the i*width*0.25 stereo phase spread, the
          sine (8192-entry table + lerp) / triangle / saw / ramp /
          square shapes, the depthLerp, and valueStereo().
      include/sst/basic-blocks/dsp/BlockInterpolators.h
          lipol<float,BS,true> (feedback, tone; per-sample v += dv) and
          lipol_sse<32,false> (widthS, mix; updateLine ramp,
          set_target_smoothed 0.25/0.75).
      include/sst/basic-blocks/dsp/MidSide.h  encodeMS / decodeMS.
  libs/sst/sst-filters@e92d93a92beabde03fa4ab767b285fa21c6608d6
      include/sst/filters/BiquadFilter.h
          calc_omega, coeff_APF / coeff_LP / coeff_HP, set_coef
          (a0 normalisation + first_run startValue), the per-sample
          coefficient lag d_lp = 0.004, TDF2 process_sample (MONO) and
          process_block (STEREO).
  surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71
      src/common/dsp/effects/SurgeSSTFXAdapter.h (SurgeFXConfig: no
          widthIsLinear -> useLinearWidth() false; temposyncRatio;
          envelopeRateLinear; noteToPitchIgnoringTuning)
      src/common/dsp/effects/PhaserEffect.{h,cpp} (ctrl types + the
          streaming migrations rev<=13 / <=15 / <=17 / <30).

Engine pin: 48 kHz, compiled block size 32 (oracle/manifest.json).

THREE CLAIMS, KEPT SEPARATE (AGENTS.md):
  1. RTL-vs-this-model exactness  -> tools/compare_rtl_model_phaser.py
  2. model-vs-pinned-engine budgets [PROPOSED, NOT frozen; freeze gated on
     SXT-017 / issue #12]  -> tools/compare_phaser_reference.py
  3. "sounds good"  -> listening records only (never inferred from 1 or 2).

Frozen word formats (model/effects/README.md):
  audio words, inter-stage cascade words   Q10.21 s32
  block-rate gain ramps (widthS, mix)      Q13.18 s32
  biquad coefficients / lags / TDF2 state,
  feedback + tone lipol v/dv, lfophase     Q24.43 s64
Products exact, round-half-up, saturating (model/effects/qmath.py); no
floating point at audio run time; double precision only at control rate,
quantized once.

PER-INSTANCE STATE: one PhaserState holds dL/dR, every APF biquad
(2 x n_stages MONO biquads), the stereo tone lp/hp biquads, the feedback
and tone lipols, the widthS/mix ramps, the LFO phase accumulator and the
FXModControl output lipols, and the slow-block counter bi. Two configured
Phaser slots are two PhaserState objects; nothing is shared (AGENTS.md
per-instance rule, issue #59 acceptance). Arithmetic may be shared only
observably.

EXTERNAL MEMORY: the Phaser has NO delay line. Every state word is
small on-chip state; audio-rate external traffic is ZERO words/sample.
The cost/fit accounting itself is [PENDING-SXT-016]; no number is
invented here beyond the exact state-word inventory this model owns
(tools/phaser_buffer_report.py).

Declared deviations (bounded; absorbed by the [PROPOSED] budgets):
  * engine float32 audio / lipol state -> Q10.21 / Q24.43 (<= 1 LSB-class
    per op). The engine also re-rounds the cascade value to float32
    between stages (BiquadFilter::process_sample returns float), so a
    per-stage grid round is structurally faithful; the GRID differs
    (float32 relative vs Q10.21 absolute), which is the dominant declared
    deviation of this leaf and is NOT measured here (oracle NOT_RUN).
  * lfophase held Q24.43 (engine float32), quantized once per slow block;
    the fmod wrap keeps the error bounded and non-accumulating.
  * control-rate formulas (envelope_rate_linear, note_to_pitch_ignoring_
    tuning, db_to_linear, cos/sin, powf spread law, the LFO shapes)
    evaluated in double and quantized once; the engine evaluates them in
    float32 / table lookups. The LFO sine TABLE is kept on the float32
    grid (the engine stores `float sine[8192]`).

Declared scope omissions (FAIL-CLOSED — these raise, never silently
degrade):
  * mod_wave 5 (Noise) and 6 (Sample & Hold): RNG-driven
    (FXModControl uses sst::basic_blocks::dsp::RNG). Not bit-reproducible
    against the pinned oracle without an RNG-stream pin, so this model
    REFUSES them rather than substituting a deterministic shape.
  * parameter modulation INTO phaser parameters (no fixture uses it).
  * the runtime n_stages change path (init_stages allocating new biquads
    mid-render): n_stages is block-constant in the frozen scope.
"""

import math
import os
import struct as _struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from model.effects.qmath import (  # noqa: E402
    FRAC, sat, qadd, qsub, qmul, to_q, clip,
)
from model.effects.delay.delay_model import (  # noqa: E402
    Biquad, Lipol, db_to_linear_d, note_to_pitch_ignoring_tuning_d,
    envelope_rate_linear_d, A_FMT, G_FMT, C_FMT, BLOCK, D_LP, D_LPINV,
)

A_FRAC = FRAC[A_FMT]
G_FRAC = FRAC[G_FMT]
C_FRAC = FRAC[C_FMT]

SLOWRATE = 8                  # EffectCore.h EffectTemplateBase::slowrate
SLOWRATE_M1 = SLOWRATE - 1
MAX_STAGES = 16               # Phaser.h max_stages
DEFAULT_STAGES = 4            # Phaser.h default_stages
CLAMP_A = 32 << A_FRAC        # Phaser.h std::clamp(dL, -32.f, 32.f)
ONE_G = 1 << G_FRAC
ONE_C = 1 << C_FRAC
LFO_TABLE_SIZE = 8192         # FXModControl.h LFO_TABLE_SIZE
LFO_TABLE_MASK = LFO_TABLE_SIZE - 1
SAW_CUT = 0.98                # FXModControl.h sawCutSSE
SQUARE_CUT = 0.01             # FXModControl.h squareCutSSE
SAMPLE_RATE = 48000.0

# Phaser.h phaser_params
(PH_CENTER, PH_FEEDBACK, PH_SHARPNESS, PH_MOD_RATE, PH_MOD_DEPTH, PH_STEREO,
 PH_MIX, PH_WIDTH, PH_STAGES, PH_SPREAD, PH_MOD_WAVE, PH_TONE) = range(12)

# FXModControl.h mod_waves
MOD_SINE, MOD_TRI, MOD_SAW, MOD_RAMP, MOD_SQUARE, MOD_NOISE, MOD_SNH = range(7)
DETERMINISTIC_WAVES = (MOD_SINE, MOD_TRI, MOD_SAW, MOD_RAMP, MOD_SQUARE)

# Phaser.h legacy_freq / legacy_span (n_stages < 2 branch)
LEGACY_FREQ = (1.5 / 12, 19.5 / 12, 35 / 12, 50 / 12)
LEGACY_SPAN = (2.0, 1.5, 1.0, 0.5)

# Phaser.h setvars tone->cutoff map
TONE_CLO, TONE_CMID, TONE_CHI = -12.0, 67.0, -33.0

# Phaser.h setvars: the deactivated-rate static phase window
RATE_MIN, RATE_MAX = -7.0, 9.0


def _f32(x):
    """Round a double through the engine's float32 storage."""
    return _struct.unpack("f", _struct.pack("f", x))[0]


# lipol<float, BS, true>::bs_inv after setBlockSize(): feedback ramps over
# blockSize * slowrate = 256 samples, tone over blockSize = 32 samples
# (Phaser ctor). Both are exact powers of two in Q24.43.
FB_BS_INV = to_q(1.0 / (BLOCK * SLOWRATE), C_FMT)
TONE_BS_INV = to_q(1.0 / BLOCK, C_FMT)

# FXModControl sine table on the engine's float32 grid (sin(2*pi*i/8192)),
# re-derived from the cited formula; nothing copied.
SINE_TABLE = tuple(_f32(math.sin(2.0 * math.pi * i / LFO_TABLE_SIZE))
                   for i in range(LFO_TABLE_SIZE))

MODEL_REVISION = None  # set lazily by model_revision()


class Refuse(Exception):
    """Fail-closed refusal: a declared scope omission was requested."""


# --------------------------------------------------------------------------
# small frozen primitives
# --------------------------------------------------------------------------

class MonoBiquad:
    """sst-filters BiquadFilter used through process_sample(float) — a MONO
    TDF2 with the per-sample coefficient lag d_lp = 0.004 (Q24.43).

    The Phaser allocates 2 x n_stages of these: even index = left channel,
    odd index = right channel, each with its OWN coefficient target (the
    two channels see different LFO values).
    """

    def __init__(self):
        self.lag = [0] * 5          # a1 a2 b0 b1 b2 (Q24.43, a0-normalised)
        self.tgt = [0] * 5
        self.reg0 = 0
        self.reg1 = 0
        self.first_run = True

    def suspend(self):
        self.lag = [0] * 5
        self.tgt = [0] * 5
        self.reg0 = 0
        self.reg1 = 0
        self.first_run = True

    def new_targets(self, c5):
        """BiquadFilter::set_coef: first_run startValue then newValue."""
        if self.first_run:
            self.tgt = list(c5)
            self.lag = list(c5)
            self.first_run = False
            return
        self.tgt = list(c5)

    def step_lags(self):
        for i in range(5):
            self.lag[i] = qadd(qmul(self.lag[i], D_LPINV, C_FMT, C_FMT, C_FMT),
                               qmul(self.tgt[i], D_LP, C_FMT, C_FMT, C_FMT),
                               C_FMT)

    def process_sample(self, x):
        """One Q10.21 sample in, one Q10.21 sample out."""
        self.step_lags()
        a1, a2, b0, b1, b2 = self.lag
        xi = x << (C_FRAC - A_FRAC)
        op = qadd(qmul(xi, b0, C_FMT, C_FMT, C_FMT), self.reg0, C_FMT)
        self.reg0 = qadd(qsub(qmul(xi, b1, C_FMT, C_FMT, C_FMT),
                              qmul(a1, op, C_FMT, C_FMT, C_FMT), C_FMT),
                         self.reg1, C_FMT)
        self.reg1 = qsub(qmul(xi, b2, C_FMT, C_FMT, C_FMT),
                         qmul(a2, op, C_FMT, C_FMT, C_FMT), C_FMT)
        half = 1 << (C_FRAC - A_FRAC - 1)
        return sat((op + half) >> (C_FRAC - A_FRAC), A_FMT)


class SampleLipol:
    """BlockInterpolators.h lipol<float, BS, true> (feedback, tone).

    newValue: v = new_v; new_v = f; first_run snaps v = f;
    dv = (new_v - v) * bs_inv.  process(): v += dv.  Held in Q24.43.
    """

    def __init__(self, bs_inv):
        self.v = 0
        self.new_v = 0
        self.dv = 0
        self.bs_inv = bs_inv
        self.first_run = True

    def new_value(self, f):
        self.v = self.new_v
        self.new_v = f
        if self.first_run:
            self.v = f
            self.first_run = False
        self.dv = qmul(qsub(self.new_v, self.v, C_FMT), self.bs_inv,
                       C_FMT, C_FMT, C_FMT)

    def instantize(self):
        self.v = self.new_v
        self.dv = 0

    def process(self):
        self.v = qadd(self.v, self.dv, C_FMT)


class PlainLipol(Lipol):
    """lipol_sse<32,false>: first_run_checks is FALSE for the Phaser, so
    set_target never snaps. Adds the plain (non-smoothed) set_target used by
    Phaser::initialize (mix.set_target(1.f))."""

    def set_target_plain(self, f):
        self.current = self.target
        self.target = f


class FXModLfo:
    """FXModControl<32, rnd_dual_stereo> restricted to the deterministic
    shapes, in the Phaser's usage: processStartOfBlock() is called once per
    SLOW block and valueStereo() is read immediately after.

    NOTE (engine behaviour, reproduced exactly, not a model choice): the
    Phaser NEVER calls modLFO.process(). The lfoVals/depthLerp lipols
    therefore never advance, so valueStereo() returns the value `newValue`
    pushed into `v` — i.e. the PREVIOUS slow block's waveform sample scaled
    by the PREVIOUS slow block's depth — except on the first call, where
    the lipol first_run snap makes it the current one. This one-slow-block
    LFO latency is load-bearing and is covered by a checkpoint.
    """

    def __init__(self):
        self.lfophase = 0.0          # FXModControl ctor: lfophase = 0.0f
        self.vals = [SampleLipol(TONE_BS_INV) for _ in range(4)]
        self.depth = SampleLipol(TONE_BS_INV)
        self.last_phases = [0.0] * 4

    def process_start_of_block(self, mwave, rate, depth, phase_offset, width):
        if mwave not in DETERMINISTIC_WAVES:
            raise Refuse(
                f"mod_wave {mwave} (Noise/S&H) is RNG-driven and outside the "
                "frozen scope: no pinned RNG stream (declared omission)")
        thisrate = max(0.0, rate)
        thiswidth = min(1.0, max(0.0, width))
        if thisrate > 0:
            self.lfophase = math.fmod(self.lfophase + thisrate, 1.0)
            p0 = self.lfophase + phase_offset
        else:
            p0 = phase_offset
        phases = [math.fmod(p0 + i * thiswidth * 0.25, 1.0) for i in range(4)]
        self.last_phases = list(phases)
        for i in range(4):
            self.vals[i].new_value(to_q(self._shape(mwave, phases[i]), C_FMT))
        self.depth.new_value(to_q(depth, C_FMT))

    @staticmethod
    def _shape(mwave, phase):
        if mwave == MOD_SINE:
            ps = phase * LFO_TABLE_SIZE
            psi = int(ps)                       # cvttps: truncate toward zero
            psn = (psi + 1) & LFO_TABLE_MASK
            psf = ps - psi
            return SINE_TABLE[psi & LFO_TABLE_MASK] * (1.0 - psf) \
                + psf * SINE_TABLE[psn]
        if mwave == MOD_TRI:
            return 2.0 * abs(2.0 * phase - 1.0) - 1.0
        if mwave in (MOD_SAW, MOD_RAMP):
            rise = (phase / SAW_CUT) * 2.0 - 1.0
            fall = (1.0 - (phase - SAW_CUT) / (1.0 - SAW_CUT)) * 2.0 - 1.0
            v = fall if phase > SAW_CUT else rise
            return v if mwave == MOD_SAW else -v
        # MOD_SQUARE: four segments, m = 1/0.01
        m = 1.0 / SQUARE_CUT
        before_half = 0.5 - SQUARE_CUT
        before_one = 1.0 - SQUARE_CUT
        if phase < before_half:
            return 1.0
        if phase <= 0.5:
            return -m * phase + m / 2.0
        if phase < before_one:
            return -1.0
        return m * phase - m + 1.0

    def value_stereo(self):
        """{lfoVals[0].v * depthLerp.v, lfoVals[1].v * depthLerp.v} as
        doubles (the Phaser consumes them at control rate only)."""
        d = self.depth.v / float(1 << C_FRAC)
        return [self.vals[0].v / float(1 << C_FRAC) * d,
                self.vals[1].v / float(1 << C_FRAC) * d]


# --------------------------------------------------------------------------
# parameters + state
# --------------------------------------------------------------------------

class PhaserParams:
    """Frozen control-plane inputs for ONE phaser instance (block-constant;
    modulation into these values is outside the frozen scope)."""

    def __init__(self, d):
        self.center_f = float(d["center_f"])
        self.feedback_f = float(d["feedback_f"])
        self.sharpness_f = float(d["sharpness_f"])
        self.mod_rate_f = float(d["mod_rate_f"])
        self.mod_depth_f = float(d["mod_depth_f"])
        self.stereo_f = float(d["stereo_f"])
        self.mix_f = float(d["mix_f"])
        self.width_f = float(d["width_f"])
        self.stages_i = int(d["stages_i"])
        self.spread_f = float(d["spread_f"])
        self.mod_wave_i = int(d["mod_wave_i"])
        self.tone_f = float(d["tone_f"])
        self.tone_deactivated = bool(d.get("tone_deactivated", False))
        self.mod_rate_deactivated = bool(d.get("mod_rate_deactivated", False))
        self.ts_rate = bool(d.get("ts_rate", False))
        self.ts_ratio_mod = float(d.get("ts_ratio_mod", 1.0))  # temposyncratio
        if not 1 <= self.stages_i <= MAX_STAGES:
            raise Refuse(f"stages {self.stages_i} outside Phaser.h range 1..16")
        if self.mod_wave_i not in DETERMINISTIC_WAVES:
            raise Refuse(
                f"mod_wave {self.mod_wave_i} outside the frozen deterministic "
                "scope (Noise/S&H are RNG-driven)")


class PhaserState:
    """Per-instance phaser state: two slots = two of these, never shared."""

    def __init__(self, name="phaser", n_stages=DEFAULT_STAGES):
        self.name = name
        self.n_stages = n_stages
        self.dl = 0
        self.dr = 0
        self.bi = 0
        self.apf = [MonoBiquad() for _ in range(2 * MAX_STAGES)]
        self.lp = Biquad()          # stereo (process_block semantics)
        self.hp = Biquad()
        self.feedback = SampleLipol(FB_BS_INV)
        self.tone = SampleLipol(TONE_BS_INV)
        self.width_s = PlainLipol()
        self.mix = PlainLipol()
        self.lfo = FXModLfo()
        self.ext_reads = 0          # the Phaser owns NO external memory
        self.ext_writes = 0
        # observation-only coverage counter (NOT part of the traced state and
        # NOT mirrored by the RTL): how often the +-32 recursive-node clamp
        # actually engaged. A negative control that targets the clamp must be
        # scored on a stimulus where this is non-zero.
        self.clamp_hits = 0

    def apf_hash(self):
        """Order-sensitive 64-bit mix over every live APF state word.

        Canonical order: stage 0..n-1, channel L then R, lag[0..4],
        tgt[0..4], reg0, reg1. Mirrored bit-for-bit by the RTL bench so a
        single wrong word in any stage is caught at a checkpoint.
        """
        h = 0
        mask = (1 << 64) - 1
        for u in range(2 * self.n_stages):
            b = self.apf[u]
            for w in list(b.lag) + list(b.tgt) + [b.reg0, b.reg1]:
                h = (h * 1000003 + (w & mask)) & mask
        return h

    def checkpoint(self):
        return {
            "name": self.name,
            "bi": self.bi,
            "dl": self.dl, "dr": self.dr,
            "fb_v": self.feedback.v, "fb_dv": self.feedback.dv,
            "fb_new": self.feedback.new_v,
            "tone_v": self.tone.v, "tone_dv": self.tone.dv,
            "tone_new": self.tone.new_v,
            "mix_cur": self.mix.current, "mix_tgt": self.mix.target,
            "ws_cur": self.width_s.current, "ws_tgt": self.width_s.target,
            "lp_lag": list(self.lp.lag), "hp_lag": list(self.hp.lag),
            "lp_reg0": list(self.lp.reg0), "lp_reg1": list(self.lp.reg1),
            "hp_reg0": list(self.hp.reg0), "hp_reg1": list(self.hp.reg1),
            "apfhash": self.apf_hash(),
            "ext_reads": self.ext_reads,
            "ext_writes": self.ext_writes,
        }


# --------------------------------------------------------------------------
# control-rate coefficient builders (double, quantized once)
# --------------------------------------------------------------------------

def calc_omega_d(scfreq):
    """BiquadFilter::calc_omega — note the engine casts 12*scfreq to float."""
    return (2.0 * math.pi) * 440.0 * \
        note_to_pitch_ignoring_tuning_d(_f32(12.0 * scfreq)) / SAMPLE_RATE


def _norm(a0, a1, a2, b0, b1, b2):
    """BiquadFilter::set_coef a0 normalisation, quantized once to Q24.43."""
    inv = 1.0 / a0
    return [to_q(a1 * inv, C_FMT), to_q(a2 * inv, C_FMT),
            to_q(b0 * inv, C_FMT), to_q(b1 * inv, C_FMT), to_q(b2 * inv, C_FMT)]


def coeff_apf(omega, q):
    """BiquadFilter::coeff_APF."""
    if omega < 0.0 or omega > math.pi:
        return _norm(1, 0, 0, 1, 0, 0)
    cosi, sinu = math.cos(omega), math.sin(omega)
    alpha = sinu / (2.0 * q)
    return _norm(1.0 + alpha, -2.0 * cosi, 1.0 - alpha,
                 1.0 - alpha, -2.0 * cosi, 1.0 + alpha)


def coeff_lp(omega, q):
    """BiquadFilter::coeff_LP."""
    if omega > math.pi:
        return _norm(1, 0, 0, 1, 0, 0)
    cosi, sinu = math.cos(omega), math.sin(omega)
    alpha = sinu / (2.0 * q)
    return _norm(1.0 + alpha, -2.0 * cosi, 1.0 - alpha,
                 (1.0 - cosi) * 0.5, 1.0 - cosi, (1.0 - cosi) * 0.5)


def coeff_hp(omega, q):
    """BiquadFilter::coeff_HP."""
    if omega > math.pi:
        return _norm(1, 0, 0, 0, 0, 0)
    cosi, sinu = math.cos(omega), math.sin(omega)
    alpha = sinu / (2.0 * q)
    return _norm(1.0 + alpha, -2.0 * cosi, 1.0 - alpha,
                 (1.0 + cosi) * 0.5, -(1.0 + cosi), (1.0 + cosi) * 0.5)


def ringout_blocks(feedback_f):
    """Phaser::getRingoutDecay (BLOCKS; -1 = never rings out).

    The declared tail span of this leaf is exactly this many blocks after
    the input goes silent; a render truncated before it FAILS the tail
    check (issue #59 acceptance, dropped-tail negative control).
    """
    fb = feedback_f
    if fb > 1.0 or fb < -1.0:
        return -1
    if fb > 0.9 or fb < -0.9:
        return 5000
    if fb > 0.5 or fb < -0.5:
        return 3000
    return 1000


# --------------------------------------------------------------------------
# the model
# --------------------------------------------------------------------------

class PhaserModel:
    """One Phaser instance: block-rate control pass + audio-rate datapath."""

    def __init__(self, params: PhaserParams, name="phaser"):
        self.p = params
        self.st = PhaserState(name, params.stages_i)
        self.ctrl = {}
        self.initialized = False

    # ---- lifecycle --------------------------------------------------------
    def initialize(self):
        """Phaser ctor + initialize(): fresh-instance state (fx load, and the
        reset/panic path — suspendProcessing() calls initialize())."""
        st = self.st
        st.n_stages = self.p.stages_i
        st.bi = 0
        st.dl = 0
        st.dr = 0
        for b in st.apf:
            b.suspend()
        st.lp.suspend()
        st.hp.suspend()
        st.lp.instantize()            # lp.coeff_instantize() (targets are 0)
        st.hp.instantize()
        st.feedback = SampleLipol(FB_BS_INV)
        st.tone = SampleLipol(TONE_BS_INV)
        st.tone.instantize()          # tone.instantize(): v = new_v, dv = 0
        st.width_s = PlainLipol()
        st.width_s.instantize()       # widthS.instantize()
        st.mix = PlainLipol()
        st.mix.set_target_plain(ONE_G)   # mix.set_target(1.f)
        st.mix.instantize()              # mix.instantize()
        st.lfo = FXModLfo()
        st.ext_reads = 0
        st.ext_writes = 0
        st.clamp_hits = 0
        self.initialized = True

    def reset(self):
        """suspendProcessing() / panic: Phaser.h routes both to initialize()."""
        self.initialize()

    def set_params(self, params: PhaserParams):
        """Mid-tail patch change (declared semantics).

        The engine mutates the FxStorage values in place; the running
        Phaser instance keeps dL/dR, every biquad register and every ramp,
        and only picks the new values up at the NEXT setvars (bi == 0)
        boundary. The tail therefore continues rather than restarting.
        A stage-count change is refused here: it is the init_stages
        allocation path, outside the frozen scope.
        """
        if params.stages_i != self.p.stages_i:
            raise Refuse("mid-render stage-count change is outside the frozen "
                         "scope (init_stages allocation path)")
        self.p = params

    def ringout_blocks(self):
        return ringout_blocks(self.p.feedback_f)

    # ---- control pass (Phaser::setvars, runs when bi == 0) ----------------
    def _setvars(self):
        p, st = self.p, self.st

        rate = envelope_rate_linear_d(-p.mod_rate_f)
        if p.ts_rate:
            rate = rate * p.ts_ratio_mod
        rate = rate * float(SLOWRATE)          # rate *= (float)slowrate

        depth = min(2.0, max(0.0, p.mod_depth_f))
        stereo = min(1.0, max(0.0, p.stereo_f))

        if p.mod_rate_deactivated:
            phase = min(1.0, max(0.0, (p.mod_rate_f - RATE_MIN) /
                                 (RATE_MAX - RATE_MIN)))
            st.lfo.process_start_of_block(p.mod_wave_i, 0.0, depth, phase,
                                          stereo)
        else:
            st.lfo.process_start_of_block(p.mod_wave_i, rate, depth, 0.0,
                                          stereo)
        lfo = st.lfo.value_stereo()

        q = 1.0 + 0.8 * p.sharpness_f
        n = st.n_stages
        if n < 2:
            # Phaser.h legacy branch: `for (int i = 0; i < 2; i++)` writes
            # biquads 0..3 while processBlock runs only stage 0 (biquads
            # 0/1). Reproduced exactly as pinned; NOT a model simplification.
            for i in range(2):
                for ch in range(2):
                    sc = 2.0 * p.center_f + LEGACY_FREQ[i] + \
                        LEGACY_SPAN[i] * lfo[ch]
                    st.apf[2 * i + ch].new_targets(coeff_apf(calc_omega_d(sc), q))
        else:
            for i in range(n):
                center = _f32(2.0 ** ((i + 1.0) * 2.0 / n))   # powf
                for ch in range(2):
                    sc = 2.0 * p.center_f + p.spread_f * center + \
                        (2.0 / (i + 1)) * lfo[ch]
                    st.apf[2 * i + ch].new_targets(coeff_apf(calc_omega_d(sc), q))

        st.feedback.new_value(to_q(_f32(0.95) * p.feedback_f, C_FMT))
        st.tone.new_value(to_q(min(1.0, max(-1.0, p.tone_f)), C_FMT))
        st.width_s.set_target_smoothed(to_q(db_to_linear_d(p.width_f), G_FMT))

        # tone -> lp/hp cutoffs; the engine reads tone.v AFTER tone.newValue,
        # i.e. the PREVIOUS slow block's converged tone value
        tone_v = st.tone.v / float(1 << C_FRAC)
        hp_cut, lp_cut = TONE_CHI, TONE_CMID
        if tone_v > 0:
            hp_cut = tone_v * (TONE_CMID - TONE_CHI) + TONE_CHI
        else:
            lp_cut = (-tone_v) * (TONE_CLO - TONE_CMID) + TONE_CMID
        st.lp.new_targets(coeff_lp(calc_omega_d(lp_cut / 12.0 - 2.0), 0.707))
        st.hp.new_targets(coeff_hp(calc_omega_d(hp_cut / 12.0 - 2.0), 0.707))

        self.ctrl = {
            "setvars": True,
            "n_stages": n,
            "tone_on": not p.tone_deactivated,
            "fb_new": st.feedback.new_v,
            "tone_new": st.tone.new_v,
            "ws_raw": to_q(db_to_linear_d(p.width_f), G_FMT),
            "lp_tgt": list(st.lp.tgt),
            "hp_tgt": list(st.hp.tgt),
            "apf_tgt": [list(st.apf[u].tgt) for u in range(2 * max(n, 2))],
            "lfo_stereo": lfo,
        }

    # ---- audio-rate block -------------------------------------------------
    def process_block(self, in_l, in_r, stage_hook=None):
        """One 32-sample block (Phaser::processBlock). in/out Q10.21 lists.

        stage_hook(k, [(dl, dr) after each stage]) is observation only.
        """
        st, p = self.st, self.p
        if not self.initialized:
            self.initialize()

        if st.bi == 0:
            self._setvars()
        else:
            self.ctrl = dict(self.ctrl or {})
            self.ctrl["setvars"] = False
        st.bi = (st.bi + 1) & SLOWRATE_M1

        # mix target is refreshed EVERY block (processBlock, not setvars)
        mix_raw = to_q(min(1.0, max(0.0, p.mix_f)), G_FMT)
        st.mix.set_target_smoothed(mix_raw)
        self.ctrl["mix_raw"] = mix_raw

        n = st.n_stages
        wl = [0] * BLOCK
        wr = [0] * BLOCK
        for k in range(BLOCK):
            st.feedback.process()
            st.tone.process()
            fbv = st.feedback.v
            dl = qadd(in_l[k], qmul(st.dl, fbv, A_FMT, C_FMT, A_FMT), A_FMT)
            dr = qadd(in_r[k], qmul(st.dr, fbv, A_FMT, C_FMT, A_FMT), A_FMT)
            if dl > CLAMP_A or dl < -CLAMP_A or dr > CLAMP_A or dr < -CLAMP_A:
                st.clamp_hits += 1
            dl = clip(dl, -CLAMP_A, CLAMP_A)
            dr = clip(dr, -CLAMP_A, CLAMP_A)
            trace = []
            for s in range(n):
                dl = st.apf[2 * s].process_sample(dl)
                dr = st.apf[2 * s + 1].process_sample(dr)
                if stage_hook is not None:
                    trace.append((dl, dr))
            if stage_hook is not None:
                stage_hook(k, trace)
            st.dl, st.dr = dl, dr
            wl[k] = dl
            wr[k] = dr

        if not p.tone_deactivated:
            for k in range(BLOCK):
                wl[k], wr[k] = st.lp.process_sample(wl[k], wr[k])
            for k in range(BLOCK):
                wl[k], wr[k] = st.hp.process_sample(wl[k], wr[k])

        # applyWidth: encodeMS, widthS.multiply_block(S), decodeMS
        # (widthM is NOT applied — useLinearWidth() is false for Surge)
        for k in range(BLOCK):
            l_v, r_v = wl[k], wr[k]
            m = l_v + r_v
            m = m >> 1 if m >= 0 else -((-m) >> 1)
            s = l_v - r_v
            s = s >> 1 if s >= 0 else -((-s) >> 1)
            ss = st.width_s.mul_sample(st.width_s.line_value(k), s)
            wl[k] = qadd(m, ss, A_FMT)
            wr[k] = qsub(m, ss, A_FMT)

        out_l = [0] * BLOCK
        out_r = [0] * BLOCK
        for k in range(BLOCK):
            g = st.mix.line_value(k)
            inv = qsub(ONE_G, g, G_FMT)
            out_l[k] = qadd(qmul(inv, in_l[k], G_FMT, A_FMT, A_FMT),
                            qmul(g, wl[k], G_FMT, A_FMT, A_FMT), A_FMT)
            out_r[k] = qadd(qmul(inv, in_r[k], G_FMT, A_FMT, A_FMT),
                            qmul(g, wr[k], G_FMT, A_FMT, A_FMT), A_FMT)
        return out_l, out_r


def state_inventory(n_stages):
    """EXACT per-instance state inventory of this frozen model, in bits.

    The Phaser owns NO delay line, so none of this is external memory and
    the audio-rate external traffic is zero words/sample. The COST/FIT
    closure over this inventory (cycles, schedule, whether a bundle fits a
    profile) is NOT decided here: that is SXT-015 accounting consumed by
    SXT-016, marked [PENDING-SXT-016].
    """
    if not 1 <= n_stages <= MAX_STAGES:
        raise Refuse(f"stages {n_stages} outside Phaser.h range 1..16")
    # Phaser::setvars configures 4 biquad units in the legacy branch even
    # though processBlock runs only stage 0 — the allocation is what resides.
    units = 4 if n_stages < 2 else 2 * n_stages
    bits = {
        # per MONO APF biquad: 5 coefficient lags + 5 targets + 2 TDF2 regs
        "apf_biquads": units * 12 * 64,
        # tone lp + hp (STEREO): 5 lags + 5 targets + 4 TDF2 regs each
        "tone_biquads": 2 * 14 * 64,
        # feedback + tone lipol<float,BS,true>: v, new_v, dv
        "sample_lipols": 2 * 3 * 64,
        # the recursive node dL / dR (Q10.21)
        "recursive_node": 2 * 32,
        # widthS + mix lipol_sse: current + target (Q13.18)
        "block_ramps": 2 * 2 * 32,
        # FXModControl: lfophase + 4 output lipols (v,new_v,dv) + depth lipol
        "lfo": 64 + 4 * 3 * 64 + 3 * 64,
        # slow-block counter bi
        "counters": 32,
    }
    total = sum(bits.values())
    return {"n_stages": n_stages, "biquad_units": units,
            "bits": bits, "bits_total": total,
            "bytes_total": total // 8}


def model_revision():
    """sha256 of this file — the frozen-revision pin carried in every trace
    and checked by the RTL comparator (a stale harness refuses to PASS)."""
    import hashlib
    global MODEL_REVISION
    if MODEL_REVISION is None:
        with open(os.path.abspath(__file__), "rb") as f:
            MODEL_REVISION = hashlib.sha256(f.read()).hexdigest()
    return MODEL_REVISION
