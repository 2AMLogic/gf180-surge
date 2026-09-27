"""SXT-028f frozen fixed-point model of the Surge XT "Reverb 2" tank reverb.

Structure authority (READ, cited; GPL-3.0-or-later trees pinned externally --
no code, tables or assets are copied into this repository):

  libs/sst/sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b
      include/sst/effects/Reverb2.h
          Reverb2<FXConfig>: the constants block (:63-74), the four member
          classes allpass (:76-87, :263-284), delay (:89-101, :286-319),
          predelay (:103-123) and onepole_filter (:125-134, :321-335),
          calc_size (:348-382), setvars (:384-397) and processBlock
          (:399-490).
      include/sst/effects/EffectCore.h
          EffectTemplateBase value/rate/environment accessors (floatValue,
          temposyncRatio/Inv, sampleRate, dbToLinear).
      include/sst/effects-shared/WidthProvider.h
          applyWidth (encodeMS -> widthS.multiply_block(S) -> decodeMS) and
          setWidthTarget; Surge does NOT define widthIsLinear, so
          useLinearWidth() is false and widthM is unused.
  libs/sst/sst-basic-blocks@a32b8aec14d661e415bb676bb2e2a0a4da4efc96
      include/sst/basic-blocks/dsp/BlockInterpolators.h
          lipol<float, 32, true> (the six coefficient ramps) and
          lipol_sse<32, false> (widthS / mix).
      include/sst/basic-blocks/dsp/QuadratureOscillators.h
          SurgeQuadrOsc<float> (the "magic circle" modulation LFO; set_rate
          RE-NORMALISES the (r, i) vector every block).
  surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71
      src/common/dsp/effects/SurgeSSTFXAdapter.h  (SurgeFXConfig: blockSize
          32, floatValueAt, temposyncRatio/Inv, sampleRate, dbToLinear; and
          SurgeSSTFXBase, which maps Surge's init()/process()/suspend() onto
          initialize()/processBlock()/suspendProcessing()).
      src/common/dsp/effects/Reverb2Effect.h  (Reverb2Effect is a thin
          SurgeSSTFXBase wrapper around sst::effects::reverb2::Reverb2 --
          the sst header IS the algorithm authority at this pin).
      src/common/dsp/Effect.cpp:79-80 (fxt_reverb2 -> Reverb2Effect).

Frozen engine schedule reproduced here, in order (processBlock):

  control pass, once per block
      scale = powf(2, room_size); calc_size(scale) recomputes the eight tap
      times, the twelve allpass lengths and the four delay lengths;
      decay = powf(0.001, 0.5508*scale / (4*2^decay_time));
      the six lipol<float> ramps take new targets (decay, 0.7*diffusion,
      0.7*buildup, 0.8*hf_damping, 0.2*lf_damping,
      modulation*sr*0.001*5); widthS/mix take smoothed lipol_sse targets;
      the LFO rate is re-set every block (constant omega = 2*pi*2^-2/sr)
      which also renormalises (r, i); pdt = clamp(int(sr*2^predelay*
      temposyncRatioInv), 1, 1151999).
  per sample k
      in = (L+R)*0.5 -> predelay(pdt) -> four input allpasses at diffusion.v
      x = _state
      for b in 0..3:
          x += in
          x -> allpass[b][0] -> allpass[b][1]   (coefficient buildup.v)
          x -> hf_damper[b].process_lowpass(clamp(hf.v, 0.01, 0.99))
          x -> lf_damper[b].process_highpass(clamp(lf.v, 0.01, 0.99))
          modulation = (int)(mod.v * lfos[b] * 256), lfos = [r, i, -r, -i]
          x -> delay[b].process(...), which also returns the two output taps
          outL += tapL*gainL[b];  outR += tapR*gainR[b]
          x *= decay.v
      _state = x
      decay/diffusion/buildup/hf/lfo/modulation .process()
      *** lf_damp_coefficent.process() is NOT called by the pinned engine ***
  block tail
      applyWidth(wetL, wetR, widthS)  (mid/side; S scaled by the ramp)
      mix.fade_2_blocks_inplace(dataL, wetL, dataR, wetR)

Frozen word formats (model/effects/README.md conventions, qmath.py kernel):
  audio samples and every external buffer word  Q10.21 signed 32-bit
  block-rate gain ramps (widthS, mix), tap gains Q13.18 signed 32-bit
  coefficient ramps, one-pole state, LFO state  Q24.43 signed 64-bit
Products are exact and rounded round-half-up to the target format, then
saturated; there is no floating point at audio run time; double precision
appears only at control rate and is quantised once.

Per-instance state: one Reverb2State owns the predelay ring, the twelve
allpass rings, the four delay rings, the eight one-pole registers, the tank
accumulator _state, the six coefficient ramps, the LFO and the two
lipol_sse ramps. Two configured Reverb 2 slots are two Reverb2State objects
over two disjoint external regions; nothing is shared (AGENTS.md / plan
section 3). Arithmetic may be shared only observably.

Declared control-plane boundary (model -> RTL): the block-rate quantities
are computed here in double, quantised once, and streamed one word per line
(see ctrl_words()). The RTL owns everything audio-rate: the lipol
recurrences, the predelay ring, all allpass and delay recurrences, the
one-pole filters, the modulation truncation and sub-sample interpolation,
the tap MACs, the decay multiply, the width matrix and the mix crossfade.

Declared allocation profile: the pinned engine allocates MAX_ALLPASS_LEN =
MAX_DELAY_LEN = 131072 words per line and PREDELAY_BUFFER_SIZE = 1536000
words. Those sizes are the default (ENGINE_PROFILE) and are what the
external-memory report accounts for. A smaller HARNESS_PROFILE exists so
the iverilog bench can hold two instances; it is only valid when no ring
ever wraps into a live tap, which the model asserts (profile_ok()) and
which tests/test_sxt028f.py demonstrates by running both profiles over the
same stimulus and requiring identical output. A profile that would alias is
REFUSED, never silently reduced.

Declared deviations (bounded; absorbed by the model-vs-reference budgets,
which are NOT established by this file):
  * engine float32 audio arithmetic -> Q10.21 (<= 1 LSB-class per op), the
    same class the landed Delay/EQ/Reverb1/Chorus models declare;
  * the six coefficient ramps and the one-pole/LFO state are held Q24.43
    where the engine holds float32; the per-sample increment dv is rounded
    once to Q24.43 (the engine's /32 is exact in float);
  * the four tap MACs accumulate exactly and round once, where the engine
    rounds each product to float32 before accumulating;
  * the (L+R)*0.5 input fold and the mid/side halving truncate toward zero
    (the repo's frozen halving convention, model/effects/type-chorus);
  * control-rate transcendentals (powf, cos, sin, sqrt, db_to_linear) are
    evaluated in double and quantised once, with explicit float32 rounding
    at each point where the engine stores a float;
  * parameter modulation INTO Reverb 2 parameters is outside the frozen
    scope (fail-closed: Reverb2Params refuses per-sample parameter
    trajectories).
"""

import hashlib
import math
import os
import struct as _struct
import sys
from array import array

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from model.effects.qmath import (  # noqa: E402
    FRAC, sat, qadd, qsub, qmul, to_q, clip,
)
from model.effects.delay.delay_model import (  # noqa: E402
    Lipol, db_to_linear_d, A_FMT, G_FMT, C_FMT, BLOCK,
)

assert array("i").itemsize == 4, "the frozen external word is 32-bit"

A_FRAC = FRAC[A_FMT]
G_FRAC = FRAC[G_FMT]
C_FRAC = FRAC[C_FMT]
ONE_C = 1 << C_FRAC
ONE_G = 1 << G_FRAC

# ---------------------------------------------------------------- constants
# Reverb2.h:63-74 (engine constants, read + cited, not copied)
NUM_BLOCKS = 4
NUM_INPUT_ALLPASSES = 4
NUM_ALLPASSES_PER_BLOCK = 2
NUM_ALLPASSES = NUM_INPUT_ALLPASSES + NUM_BLOCKS * NUM_ALLPASSES_PER_BLOCK  # 12
MAX_ALLPASS_LEN = 16384 * 8            # 131072
MAX_DELAY_LEN = 16384 * 8              # 131072
DELAY_SUBSAMPLE_BITS = 8
DELAY_SUBSAMPLE_RANGE = 1 << DELAY_SUBSAMPLE_BITS
PREDELAY_BUFFER_SIZE = 48000 * 8 * 4   # 1536000
PREDELAY_BUFFER_SIZE_LIMIT = 48000 * 8 * 3   # 1152000
DB60 = 0.001                           # Reverb2.h:243 static constexpr db60
SAMPLE_RATE = 48000.0                  # oracle/manifest.json pin

# Reverb2.h:353-360 calc_size tap times (milliseconds, engine literals)
TAP_MS_L = (80.3, 59.3, 97.7, 122.6)
TAP_MS_R = (35.5, 101.6, 73.9, 80.3)
# Reverb2.h:362-365 input allpass lengths (ms)
INPUT_AP_MS = (4.76, 6.81, 10.13, 16.72)
# Reverb2.h:367-381 per-block allpass lengths (ms) and delay lengths (ms)
BLOCK_AP_MS = ((38.2, 53.4), (44.0, 41.0), (48.3, 60.5), (38.9, 42.2))
BLOCK_DELAY_MS = (178.8, 126.5, 106.1, 139.4)


def _f32(x):
    """Round a Python float through IEEE binary32 (an engine float store)."""
    return _struct.unpack("f", _struct.pack("f", x))[0]


# Reverb2.h:387-394 setvars tap gains (float literals / 4.f), quantised once
TAP_GAIN_L = tuple(to_q(_f32(_f32(v) / 4.0), G_FMT) for v in (1.5, 1.2, 1.0, 0.8))
TAP_GAIN_R = tuple(to_q(_f32(_f32(v) / 4.0), G_FMT) for v in (1.5, 1.2, 1.0, 0.8))


def _trunc_shift(v, s):
    """Arithmetic shift with C truncation toward zero (the (int) cast)."""
    if s <= 0:
        return v << (-s)
    return v >> s if v >= 0 else -((-v) >> s)


def _floor_shift(v, s):
    """C++20 signed >> : arithmetic (floor) shift."""
    return v >> s


def _round_shift(v, s):
    """Round-half-up shift -- the frozen qmath rounding rule, applied with
    the same arithmetic (not symmetric) semantics qmath.qmul uses for
    negative operands."""
    if s <= 0:
        return v << (-s)
    return (v + (1 << (s - 1))) >> s


def ms_to_samples(ms, scale, sr=SAMPLE_RATE):
    """Reverb2.h:233-241 msToSamples: float a = sr*ms*0.001f; b = a*scale;
    return (int)b (truncation toward zero)."""
    a = _f32(sr * ms * _f32(0.001))
    b = _f32(a * scale)
    return int(b)


# ------------------------------------------------------------ alloc profiles
class AllocProfile:
    """Allocated words per buffer class, per instance.

    ENGINE_PROFILE mirrors the pinned allocation exactly and is what the
    SXT-015 external-memory accounting reports. HARNESS_PROFILE is a
    declared reduction used ONLY by the RTL exactness bench; it is legal
    only while every ring stays larger than its longest live tap, which
    profile_ok() checks and which the profile-equivalence test demonstrates.
    """

    def __init__(self, name, allpass_len, delay_len, predelay_len):
        assert delay_len & (delay_len - 1) == 0, "delay ring must be 2^n"
        self.name = name
        self.allpass_len = allpass_len
        self.delay_len = delay_len
        self.delay_mask = delay_len - 1
        self.predelay_len = predelay_len

    # external region layout (word offsets inside one instance's region)
    @property
    def predelay_off(self):
        return 0

    def allpass_off(self, idx):
        return self.predelay_len + idx * self.allpass_len

    def delay_off(self, b):
        return (self.predelay_len + NUM_ALLPASSES * self.allpass_len
                + b * self.delay_len)

    @property
    def words(self):
        return (self.predelay_len + NUM_ALLPASSES * self.allpass_len
                + NUM_BLOCKS * self.delay_len)

    def as_dict(self):
        return {"profile": self.name, "allpass_len": self.allpass_len,
                "delay_len": self.delay_len,
                "predelay_len": self.predelay_len, "words": self.words,
                "bytes": self.words * 4}


ENGINE_PROFILE = AllocProfile("engine", MAX_ALLPASS_LEN, MAX_DELAY_LEN,
                              PREDELAY_BUFFER_SIZE)
# 16384 + 12*4096 + 4*16384 = 131072 words/instance (the bench profile)
HARNESS_PROFILE = AllocProfile("harness", 4096, 16384, 16384)


class ProfileRefusal(Exception):
    """Raised when an allocation profile cannot hold the configured lines."""


# ------------------------------------------------------------------ ramps
class LipolF:
    """sdsp::lipol<float, 32, true> (BlockInterpolators.h:35-80) in Q24.43.

    newValue: v = new_v; new_v = f; if first_run { v = f; first_run = 0 }
              dv = (new_v - v)/32        (rounded once to Q24.43)
    process:  v += dv
    """

    def __init__(self):
        self.v = 0
        self.new_v = 0
        self.dv = 0
        self.first_run = True

    def new_value(self, f_q):
        self.v = self.new_v
        self.new_v = f_q
        if self.first_run:
            self.v = f_q
            self.first_run = False
        self.dv = _round_shift(self.new_v - self.v, 5)   # * bs_inv = /32

    def process(self):
        self.v = qadd(self.v, self.dv, C_FMT)


class QuadrOsc:
    """SurgeQuadrOsc<float> (QuadratureOscillators.h) in Q24.43.

    Constructor: r = 0, i = -1. set_rate(w) stores dr = cos(w), di = sin(w)
    AND renormalises (r, i) by 1/sqrt(r*r + i*i) -- the renormalisation is a
    control-rate state mutation, so the model computes the reciprocal norm
    in double, quantises it once and streams it (see ctrl_words()); the
    per-sample recurrence itself is audio-rate.
    """

    def __init__(self):
        self.r = 0
        self.i = -ONE_C
        self.dr = 0
        self.di = 0

    def norm_q(self):
        rd = self.r / float(ONE_C)
        idd = self.i / float(ONE_C)
        mag = math.sqrt(rd * rd + idd * idd)
        if mag == 0.0:
            return 0
        return to_q(1.0 / mag, C_FMT)

    def set_rate(self, w):
        """Returns (dr, di, n) as Q24.43 so the caller can stream them."""
        wf = _f32(w)
        self.dr = to_q(_f32(math.cos(wf)), C_FMT)
        self.di = to_q(_f32(math.sin(wf)), C_FMT)
        n = self.norm_q()
        self.apply_norm(n)
        return self.dr, self.di, n

    def apply_norm(self, n):
        self.r = qmul(self.r, n, C_FMT, C_FMT, C_FMT)
        self.i = qmul(self.i, n, C_FMT, C_FMT, C_FMT)

    def process(self):
        lr, li = self.r, self.i
        self.r = qsub(qmul(self.dr, lr, C_FMT, C_FMT, C_FMT),
                      qmul(self.di, li, C_FMT, C_FMT, C_FMT), C_FMT)
        self.i = qadd(qmul(self.dr, li, C_FMT, C_FMT, C_FMT),
                      qmul(self.di, lr, C_FMT, C_FMT, C_FMT), C_FMT)


# ------------------------------------------------------------------ params
class Reverb2Params:
    """Block-constant control inputs for one Reverb 2 instance.

    Parameter modulation INTO these values is outside the frozen scope: the
    constructor refuses any list/tuple value (fail-closed) rather than
    silently flattening a trajectory to its first sample.
    """

    NAMES = ("predelay_f", "room_size_f", "decay_time_f", "diffusion_f",
             "buildup_f", "modulation_f", "lf_damping_f", "hf_damping_f",
             "width_f", "mix_f")

    def __init__(self, d):
        for n in self.NAMES:
            v = d[n]
            if isinstance(v, (list, tuple)):
                raise ValueError(
                    "parameter modulation into Reverb 2 parameters is out of "
                    "frozen scope (fail-closed): %s" % n)
            setattr(self, n, float(v))
        # temposync is fail-closed: an UNRESOLVED flag (null, as the
        # SXT-028f extraction emits when the oracle host is unavailable)
        # must refuse, never default silently to "not synced".
        if "ts_predelay" in d and d["ts_predelay"] is None:
            raise ValueError(
                "rev2_predelay temposync flag is UNRESOLVED (null): refusing "
                "to assume a value (fail-closed)")
        if "ts_ratio_inv" in d and d["ts_ratio_inv"] is None:
            if d.get("ts_predelay"):
                raise ValueError(
                    "temposync ratio is UNRESOLVED (null) while predelay is "
                    "tempo-synced: refusing (fail-closed)")
            d = dict(d, ts_ratio_inv=1.0)
        self.ts_predelay = bool(d.get("ts_predelay", False))
        self.ts_ratio_inv = float(d.get("ts_ratio_inv", 1.0))

    def as_dict(self):
        out = {n: getattr(self, n) for n in self.NAMES}
        out["ts_predelay"] = self.ts_predelay
        out["ts_ratio_inv"] = self.ts_ratio_inv
        return out


# ------------------------------------------------------------------- state
class Reverb2State:
    """Per-instance state. Two slots = two of these, never shared."""

    def __init__(self, name="reverb2", profile=ENGINE_PROFILE):
        self.name = name
        self.profile = profile
        # one flat external region per instance (Q10.21 words)
        self.mem = array("i", bytes(4 * profile.words))
        self.pd_k = 0
        self.ap_k = [0] * NUM_ALLPASSES
        self.ap_len = [1] * NUM_ALLPASSES
        self.dl_k = [0] * NUM_BLOCKS
        self.dl_len = [1] * NUM_BLOCKS
        self.tap_l = [0] * NUM_BLOCKS
        self.tap_r = [0] * NUM_BLOCKS
        self.hf_a0 = [0] * NUM_BLOCKS
        self.lf_a0 = [0] * NUM_BLOCKS
        self.tank = 0                       # _state (Q10.21)
        self.decay = LipolF()
        self.diffusion = LipolF()
        self.buildup = LipolF()
        self.hf_damp = LipolF()
        self.lf_damp = LipolF()
        self.modulation = LipolF()
        self.lfo = QuadrOsc()
        self.width_s = Lipol()
        self.mix = Lipol()
        self.pdt = 1
        # per-region additive integrity hashes + external transaction counters
        self.pd_hash = 0
        self.ap_hash = 0
        self.dl_hash = 0
        self.ext_reads = 0
        self.ext_writes = 0

    def checkpoint(self):
        m64 = (1 << 64) - 1
        return {
            "name": self.name,
            "pd_k": self.pd_k,
            "ap_k": list(self.ap_k),
            "dl_k": list(self.dl_k),
            "ap_len": list(self.ap_len),
            "dl_len": list(self.dl_len),
            "tap_l": list(self.tap_l), "tap_r": list(self.tap_r),
            "hf_a0": list(self.hf_a0), "lf_a0": list(self.lf_a0),
            "tank": self.tank,
            "decay_v": self.decay.v, "decay_t": self.decay.new_v,
            "diff_v": self.diffusion.v, "diff_t": self.diffusion.new_v,
            "bu_v": self.buildup.v, "bu_t": self.buildup.new_v,
            "hf_v": self.hf_damp.v, "hf_t": self.hf_damp.new_v,
            "lf_v": self.lf_damp.v, "lf_t": self.lf_damp.new_v,
            "mod_v": self.modulation.v, "mod_t": self.modulation.new_v,
            "lfo_r": self.lfo.r, "lfo_i": self.lfo.i,
            "ws_tgt": self.width_s.target, "mix_tgt": self.mix.target,
            "pdt": self.pdt,
            "pd_hash": self.pd_hash & m64,
            "ap_hash": self.ap_hash & m64,
            "dl_hash": self.dl_hash & m64,
            "ext_reads": self.ext_reads,
            "ext_writes": self.ext_writes,
        }


# ------------------------------------------------------------------- model
class Reverb2Model:
    """One Reverb 2 instance: audio-rate datapath + block control pass."""

    def __init__(self, params, name="reverb2", profile=ENGINE_PROFILE):
        self.p = params
        self.profile = profile
        self.st = Reverb2State(name, profile)
        self.ctrl = {}
        self.initialized = False

    # ------------------------------------------------------ control pass
    def _calc_size(self, scale):
        """Reverb2.h:348-382 calc_size, plus the setLen clamps (:270-273,
        :293-296). Refuses (fail-closed) when a line does not fit the
        declared allocation profile."""
        st, pr = self.st, self.profile
        for b in range(NUM_BLOCKS):
            st.tap_l[b] = ms_to_samples(TAP_MS_L[b], scale)
            st.tap_r[b] = ms_to_samples(TAP_MS_R[b], scale)
        lens = [ms_to_samples(v, scale) for v in INPUT_AP_MS]
        for b in range(NUM_BLOCKS):
            lens.append(ms_to_samples(BLOCK_AP_MS[b][0], scale))
            lens.append(ms_to_samples(BLOCK_AP_MS[b][1], scale))
        for i, v in enumerate(lens):
            st.ap_len[i] = clip(v, 0, MAX_ALLPASS_LEN - 1)
        for b in range(NUM_BLOCKS):
            st.dl_len[b] = clip(ms_to_samples(BLOCK_DELAY_MS[b], scale), 0,
                                MAX_DELAY_LEN - 1)
        # declared-profile bound check (fail-closed, never a silent reduction)
        worst_ap = max(st.ap_len)
        if worst_ap >= pr.allpass_len:
            raise ProfileRefusal(
                "allpass length %d does not fit profile %s (%d words)"
                % (worst_ap, pr.name, pr.allpass_len))
        worst_dl = max(max(st.dl_len), max(st.tap_l), max(st.tap_r))
        if worst_dl >= pr.delay_len:
            raise ProfileRefusal(
                "delay tap %d does not fit profile %s (%d words)"
                % (worst_dl, pr.name, pr.delay_len))

    def _control(self):
        """processBlock's block-rate head (Reverb2.h:401-429)."""
        p, st = self.p, self.st
        scale = _f32(2.0 ** _f32(1.0 * p.room_size_f))
        self._calc_size(scale)

        loop_time_s = _f32(0.5508 * scale)
        denom = _f32(4.0 * _f32(2.0 ** p.decay_time_f))
        decay = _f32(_f32(0.001) ** _f32(loop_time_s / denom))

        st.decay.new_value(to_q(decay, C_FMT))
        st.diffusion.new_value(to_q(_f32(_f32(0.7) * p.diffusion_f), C_FMT))
        st.buildup.new_value(to_q(_f32(_f32(0.7) * p.buildup_f), C_FMT))
        st.hf_damp.new_value(to_q(_f32(0.8 * p.hf_damping_f), C_FMT))
        st.lf_damp.new_value(to_q(_f32(0.2 * p.lf_damping_f), C_FMT))
        st.modulation.new_value(
            to_q(_f32(p.modulation_f * SAMPLE_RATE * _f32(0.001) * 5.0), C_FMT))

        st.width_s.set_target_smoothed(to_q(db_to_linear_d(p.width_f), G_FMT))
        st.mix.set_target_smoothed(to_q(p.mix_f, G_FMT))

        dr, di, norm = st.lfo.set_rate(2.0 * math.pi * (2.0 ** -2.0)
                                       / SAMPLE_RATE)

        ratio_inv = p.ts_ratio_inv if p.ts_predelay else 1.0
        st.pdt = clip(int(SAMPLE_RATE * _f32(2.0 ** p.predelay_f) * ratio_inv),
                      1, PREDELAY_BUFFER_SIZE_LIMIT - 1)
        if st.pdt >= self.profile.predelay_len:
            raise ProfileRefusal(
                "predelay tap %d does not fit profile %s (%d words)"
                % (st.pdt, self.profile.name, self.profile.predelay_len))

        self.ctrl = {
            "decay_t": st.decay.new_v, "diff_t": st.diffusion.new_v,
            "bu_t": st.buildup.new_v, "hf_t": st.hf_damp.new_v,
            "lf_t": st.lf_damp.new_v, "mod_t": st.modulation.new_v,
            "lfo_dr": dr, "lfo_di": di, "lfo_n": norm,
            "ws_raw": to_q(db_to_linear_d(p.width_f), G_FMT),
            "mix_raw": to_q(p.mix_f, G_FMT),
            "tap_l": list(st.tap_l), "tap_r": list(st.tap_r),
            "ap_len": list(st.ap_len), "dl_len": list(st.dl_len),
            "pdt": st.pdt,
        }
        return self.ctrl

    def ctrl_words(self):
        """The declared control-plane stream for one block (order frozen)."""
        c = self.ctrl
        w64 = [c["decay_t"], c["diff_t"], c["bu_t"], c["hf_t"], c["lf_t"],
               c["mod_t"], c["lfo_dr"], c["lfo_di"], c["lfo_n"]]
        w32 = [c["ws_raw"], c["mix_raw"]]
        wint = list(c["tap_l"]) + list(c["tap_r"]) + list(c["ap_len"]) \
            + list(c["dl_len"]) + [c["pdt"]]
        return w64, w32, wint

    # ----------------------------------------------------- lifecycle
    def initialize(self):
        """Reverb2Effect construction + init() (SurgeSSTFXBase::init ->
        Reverb2::initialize -> setvars(true)).

        The constructor zeroes every buffer, resets every ramp and sets
        _state = 0; setvars itself only rebuilds the tap gains and calls
        calc_size(1.f) -- it does NOT clear anything and does NOT instantize
        any ramp.
        """
        st = self.st
        st.mem = array("i", bytes(4 * self.profile.words))
        st.pd_k = 0
        st.ap_k = [0] * NUM_ALLPASSES
        st.dl_k = [0] * NUM_BLOCKS
        st.hf_a0 = [0] * NUM_BLOCKS
        st.lf_a0 = [0] * NUM_BLOCKS
        st.tank = 0
        st.decay = LipolF()
        st.diffusion = LipolF()
        st.buildup = LipolF()
        st.hf_damp = LipolF()
        st.lf_damp = LipolF()
        st.modulation = LipolF()
        st.lfo = QuadrOsc()
        st.width_s = Lipol()
        st.mix = Lipol()
        st.pd_hash = 0
        st.ap_hash = 0
        st.dl_hash = 0
        st.ext_reads = 0
        st.ext_writes = 0
        self._setvars_only()
        self.initialized = True

    def _setvars_only(self):
        """setvars(true) proper: tap gains (frozen constants) + calc_size(1)."""
        self._calc_size(_f32(1.0))

    def suspend(self):
        """Reverb2::suspendProcessing() == initialize() == setvars(true).

        DECLARED, and deliberately NOT a clear: the pinned engine's Reverb 2
        does not zero its tank, predelay, one-pole registers or ramps on
        suspend -- only the constructor does. A mutant that clears the tank
        here is a negative control, not a fix.
        """
        self._setvars_only()

    # ----------------------------------------------------- memory helpers
    def _rd(self, addr):
        self.st.ext_reads += 1
        return self.st.mem[addr]

    def _wr_pd(self, addr, value):
        st = self.st
        st.pd_hash += value - st.mem[addr]
        st.mem[addr] = value
        st.ext_writes += 1

    def _wr_ap(self, addr, value):
        st = self.st
        st.ap_hash += value - st.mem[addr]
        st.mem[addr] = value
        st.ext_writes += 1

    def _wr_dl(self, addr, value):
        st = self.st
        st.dl_hash += value - st.mem[addr]
        st.mem[addr] = value
        st.ext_writes += 1

    # ----------------------------------------------------- audio datapath
    def process_block(self, in_l, in_r, sample_hook=None):
        """One 32-sample block (Reverb2::processBlock). in/out Q10.21 lists.

        sample_hook(k, dict) is observation-only (RTL checkpoint capture);
        it never affects arithmetic.
        """
        if not self.initialized:
            self.initialize()
        st = self.st
        pr = self.profile
        self._control()

        pd_off = pr.predelay_off
        pd_len = pr.predelay_len
        ap_off = [pr.allpass_off(i) for i in range(NUM_ALLPASSES)]
        dl_off = [pr.delay_off(b) for b in range(NUM_BLOCKS)]
        dmask = pr.delay_mask

        wet_l = [0] * BLOCK
        wet_r = [0] * BLOCK

        for k in range(BLOCK):
            # in = (L+R) * 0.5 (halving truncates toward zero: frozen rule)
            s = qadd(in_l[k], in_r[k], A_FMT)
            x_in = s >> 1 if s >= 0 else -((-s) >> 1)

            # ---- predelay ring (Reverb2.h:107-118)
            st.pd_k += 1
            if st.pd_k == pd_len:
                st.pd_k = 0
            p_rd = st.pd_k - st.pdt
            while p_rd < 0:
                p_rd += pd_len
            res = self._rd(pd_off + p_rd)
            self._wr_pd(pd_off + st.pd_k, x_in)
            x_in = res

            # ---- four input allpasses at diffusion.v
            diff_v = st.diffusion.v
            for i in range(NUM_INPUT_ALLPASSES):
                x_in = self._allpass(i, ap_off[i], x_in, diff_v)

            x = st.tank
            out_l = 0
            out_r = 0
            hdc = clip(st.hf_damp.v, to_q(0.01, C_FMT), to_q(0.99, C_FMT))
            ldc = clip(st.lf_damp.v, to_q(0.01, C_FMT), to_q(0.99, C_FMT))
            hdc_m1 = qsub(ONE_C, hdc, C_FMT)
            ldc_m1 = qsub(ONE_C, ldc, C_FMT)
            lfos = (st.lfo.r, st.lfo.i, -st.lfo.r, -st.lfo.i)
            bu_v = st.buildup.v
            mod_v = st.modulation.v
            dec_v = st.decay.v
            taps = []

            for b in range(NUM_BLOCKS):
                x = qadd(x, x_in, A_FMT)
                ai = NUM_INPUT_ALLPASSES + b * NUM_ALLPASSES_PER_BLOCK
                x = self._allpass(ai, ap_off[ai], x, bu_v)
                x = self._allpass(ai + 1, ap_off[ai + 1], x, bu_v)

                # one-pole lowpass: a0 = a0*c0 + x*(1-c0); y = a0
                xc = x << (C_FRAC - A_FRAC)
                a0 = qadd(qmul(st.hf_a0[b], hdc, C_FMT, C_FMT, C_FMT),
                          qmul(xc, hdc_m1, C_FMT, C_FMT, C_FMT), C_FMT)
                st.hf_a0[b] = a0
                x = sat(_round_shift(a0, C_FRAC - A_FRAC), A_FMT)

                # one-pole highpass: a0 = a0*(1-c0) + x*c0; y = x - a0
                xc = x << (C_FRAC - A_FRAC)
                a0 = qadd(qmul(st.lf_a0[b], ldc_m1, C_FMT, C_FMT, C_FMT),
                          qmul(xc, ldc, C_FMT, C_FMT, C_FMT), C_FMT)
                st.lf_a0[b] = a0
                x = qsub(x, sat(_round_shift(a0, C_FRAC - A_FRAC), A_FMT),
                         A_FMT)

                # modulation = (int)(mod.v * lfos[b] * 256)
                modulation = _trunc_shift(mod_v * lfos[b],
                                          2 * C_FRAC - DELAY_SUBSAMPLE_BITS)
                x, tl, tr = self._delay(b, dl_off[b], dmask, x,
                                        st.tap_l[b], st.tap_r[b], modulation)
                out_l = qadd(out_l, qmul(TAP_GAIN_L[b], tl, G_FMT, A_FMT,
                                         A_FMT), A_FMT)
                out_r = qadd(out_r, qmul(TAP_GAIN_R[b], tr, G_FMT, A_FMT,
                                         A_FMT), A_FMT)
                if sample_hook is not None:
                    taps.append((modulation, tl, tr))
                x = qmul(dec_v, x, C_FMT, A_FMT, A_FMT)

            wet_l[k] = out_l
            wet_r[k] = out_r
            st.tank = x
            if sample_hook is not None:
                sample_hook(k, {"in": x_in, "taps": taps,
                                "out": (out_l, out_r), "tank": x})

            st.decay.process()
            st.diffusion.process()
            st.buildup.process()
            st.hf_damp.process()
            # *** lf_damp.process() is deliberately absent: the pinned engine
            # never ramps the LF damping coefficient (Reverb2.h:478-483). ***
            st.lfo.process()
            st.modulation.process()

        # ---- applyWidth: encodeMS -> S *= widthS ramp -> decodeMS
        for k in range(BLOCK):
            l_v, r_v = wet_l[k], wet_r[k]
            m = l_v + r_v
            m = m >> 1 if m >= 0 else -((-m) >> 1)
            sv = l_v - r_v
            sv = sv >> 1 if sv >= 0 else -((-sv) >> 1)
            ss = st.width_s.mul_sample(st.width_s.line_value(k), sv)
            wet_l[k] = qadd(m, ss, A_FMT)
            wet_r[k] = qsub(m, ss, A_FMT)

        # ---- mix crossfade: dry*(1-t) + wet*t
        out_lb = [0] * BLOCK
        out_rb = [0] * BLOCK
        for k in range(BLOCK):
            t = st.mix.line_value(k)
            inv = qsub(ONE_G, t, G_FMT)
            out_lb[k] = qadd(qmul(inv, in_l[k], G_FMT, A_FMT, A_FMT),
                             qmul(t, wet_l[k], G_FMT, A_FMT, A_FMT), A_FMT)
            out_rb[k] = qadd(qmul(inv, in_r[k], G_FMT, A_FMT, A_FMT),
                             qmul(t, wet_r[k], G_FMT, A_FMT, A_FMT), A_FMT)
        return out_lb, out_rb

    # ------------------------------------------------------------ kernels
    def _allpass(self, idx, off, x, coeff):
        """Reverb2.h:275-284 allpass::process (1 external read, 1 write)."""
        st = self.st
        st.ap_k[idx] += 1
        if st.ap_k[idx] >= st.ap_len[idx]:
            st.ap_k[idx] = 0
        addr = off + st.ap_k[idx]
        d = self._rd(addr)
        delay_in = qsub(x, qmul(coeff, d, C_FMT, A_FMT, A_FMT), A_FMT)
        result = qadd(d, qmul(coeff, delay_in, C_FMT, A_FMT, A_FMT), A_FMT)
        self._wr_ap(addr, delay_in)
        return result

    def _delay(self, b, off, mask, x, tap1, tap2, modulation):
        """Reverb2.h:298-319 delay::process (4 external reads, 1 write)."""
        st = self.st
        st.dl_k[b] = (st.dl_k[b] + 1) & mask
        k = st.dl_k[b]
        t1 = self._rd(off + ((k - tap1) & mask))
        t2 = self._rd(off + ((k - tap2) & mask))
        mi = _floor_shift(modulation, DELAY_SUBSAMPLE_BITS)
        f1 = modulation & (DELAY_SUBSAMPLE_RANGE - 1)
        f2 = DELAY_SUBSAMPLE_RANGE - f1
        d1 = self._rd(off + ((k - st.dl_len[b] + mi + 1) & mask))
        d2 = self._rd(off + ((k - st.dl_len[b] + mi) & mask))
        acc = d1 * f1 + d2 * f2
        result = sat(_round_shift(acc, DELAY_SUBSAMPLE_BITS), A_FMT)
        self._wr_dl(off + k, x)
        return result, t1, t2


# --------------------------------------------------------------- revision
MODEL_REVISION = None


def model_revision():
    """sha256 of this file (frozen-revision pin for traces/harnesses)."""
    global MODEL_REVISION
    if MODEL_REVISION is None:
        with open(os.path.abspath(__file__), "rb") as f:
            MODEL_REVISION = hashlib.sha256(f.read()).hexdigest()
    return MODEL_REVISION


def per_sample_transactions():
    """Declared per-sample external transactions for ONE instance.

    Derived from the pinned structure, verified against the model's own
    counters by tools/reverb2_buffer_report.py:
      reads  = 1 predelay + 12 allpass + 4 delays x 4 = 29
      writes = 1 predelay + 12 allpass + 4 delays x 1 = 17
    """
    return {"reads": 1 + NUM_ALLPASSES + NUM_BLOCKS * 4,
            "writes": 1 + NUM_ALLPASSES + NUM_BLOCKS * 1}
