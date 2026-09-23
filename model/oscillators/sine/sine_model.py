#!/usr/bin/env python3
"""SXT-040 frozen fixed-point SINE oscillator family model.

This module is the FROZEN reference for the SXT-040 RTL
(`rtl/oscillators/sine/`). RTL-vs-model agreement must be EXACT (integer
equality at every declared checkpoint; `tools/compare_sine_rtl_model.py`).
Model-vs-pinned-engine agreement is governed by [PROPOSED] error budgets
(fidelity policy DRAFT; nothing is frozen; `reports/SXT-040/EVIDENCE.md`
records achieved numbers only).

Scope (issue #74 / SXT-040): the Sine oscillator family BEYOND the landed
SXT-026a voice slice (which froze the legacy path, FMmode 0, shape 0,
unison 1, retrigger). This leaf extends the family over the engine's
submode selector and the unison machinery, per the submode inventory
observed in the committed normalized graphs:

  * shape ("Mode")  p[0]  ct_sineoscmode, int [0, 31] — all 32 shape modes
  * feedback        p[1]  ct_osc_feedback_negative [-1, 1], get_extended = 4*f
                    (modern behavior only; the legacy path never reads it)
  * behavior        p[2]  ct_sinefmlegacy, int {0 legacy, 1 modern}
  * low cut         p[3]  ct_freq_audible_deactivatable_hp [-60, 70]
  * high cut        p[4]  ct_freq_audible_deactivatable_lp [-60, 70]
  * unison detune   p[5]  ct_oscspread [0, 1], get_extended = 12*f
  * unison voices   p[6]  ct_osccount [1, 16]

Pinned structure (read and cited, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  SineOscillator.cpp/.h      init / prepare_unison / process_block (the
                             fmlegacy 0-vs-1 dispatch) / process_block_legacy
                             (FM and non-FM branches) / process_block_internal
                             (omega ramp, feedback lags, playramp) /
                             valueFromSinAndCosForMode<0..31> / applyFilter /
                             handleStreamingMismatches (shape wave_remap)
  OscillatorBase.h           pitch_to_omega (2*pi*MIDI_0_FREQ*ntp/sr_os)
  sst-basic-blocks QuadratureOscillators.h  SurgeQuadrOsc (legacy set_rate /
                             process / ctor state r=0, i=-1)
  sst-basic-blocks FastMath.h  fastsin/fastcos (JUCE Pade rationals) and
                             clampToPiRange
  sst-basic-blocks dsp/Lag.h SurgeLag ("lag", default rate 0.004; newValue =
                             setTarget with first-run snap; process per sample)
  sst-basic-blocks OscillatorDriftUnisonCharacter.h  UnisonSetup (attenuation,
                             detune bias/offset, LINEAR pan law), CharacterFilter
                             (Warm/Neutral/Bright; `starting` warm start)
  sst-filters BiquadFilter   coeff_HP / coeff_LP2B, TDF2 process (per-block
                             recompute from constant params == constant)
  SurgeVoice.cpp             mono voice path (stereo = (fbc == fc_wide));
                             output[k] = (outL + outR) / 2 on the mono bus

Arithmetic discipline (FROZEN, same rules as SXT-022/SXT-026/SXT-033):
  * every value is a Python int in two's-complement Q-format; no floating
    point at run time; no dict-iteration-order dependence;
  * products are exact then rounded back round-half-up:
    r = (a*b + (1 << (s-1))) >> s, saturated (vm.qmul);
  * sine phase / omega / omegaPrior / omegaStep / omegaCurr are Q3.28 radian
    words (SXT-026a family), 32-bit; phase wraps with the engine's single
    `phase -= (phase > M_PI) * 2*pi` rule (modern) or clampToPiRange (FM);
  * the shape functions evaluate the pinned SSE formulas in the same op
    order on Q10.21 words: sign compares are exact, multiplies of two
    non-trivial words are vm.qmul round-half-up, *2 / *0.5 / *(-1) are
    exact exponent ops in the engine and half-up-rounded shifts here
    (declared deviation <= 0.5 LSB per halving), abs is exact;
  * unison constants (attenuation, bias, offset, per-voice detune) and
    dplaying are computed at QUANTIZATION TIME in float32 emulation of the
    engine's exact operation order (`_f32` round-trips), then quantized
    once to Q10.21;
  * frequency-domain lookups (pitch_to_omega, filter coefficients, cos/sin
    at set_rate) evaluate the pinned construction formulas in double and
    quantize once (declared deviation: the engine lerps float32 tables /
    uses float libm).

Everything outside the declared boundaries REFUSES fail-closed (absolute
detune, drift != 0, unison outside 1..16, character Bright, analog
envelopes, decay shapes outside d_s in {0,1}, pitch outside [24, 148],
shape outside [0, 31], behavior outside {0, 1}).
"""

import json
import math
import os
import struct

from model.voice import voice_model as vm
from model.oscillators.classic import classic_model as cm

FQ = vm.FQ
ONE = vm.ONE
SR = vm.SR
BLOCK_SIZE = vm.BLOCK_SIZE
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS

FQ28 = vm.FQ28
PI_Q28 = vm.PI_Q28
TWO_PI_Q28 = vm.TWO_PI_Q28

MAX_UNISON = 16                 # SurgeStorage.h MAX_UNISON
SHAPE_MIN, SHAPE_MAX = 0, 31    # ct_sineoscmode val_min/val_max at the pin
HPF_OSC = vm.OSC_OVERSAMPLING   # globals.h OSC_OVERSAMPLING = 2

# lag<double> default rate (sst/basic-blocks/dsp/Lag.h ctor setRate(0.004))
LAG_LP = vm.qint(0.004)
LAG_LPINV = vm.qint(0.996)

# SineOscillator::prepare_unison: dplaying = 1/50 * 44100/samplerate (double
# expression narrowed to the float member); retrigger ramps the non-zero
# voices up over ~55 OS samples.
def _f32x(x):
    """Round a double to the nearest float32 value (quantization time only)."""
    return struct.unpack("f", struct.pack("f", x))[0]


DPLAYING = vm.qint(_f32x(1.0 / 50.0 * 44100.0 / 48000.0))


def _sat(x):
    return vm.sat(x)


def _shl1(x):
    """Engine mul_ps(2, x): exact doubling, saturated."""
    return _sat(x << 1)


def _half(x):
    """Engine mul_ps(0.5, x): exact halving in float32; the Q10.21 word
    rounds half-up (declared deviation <= 0.5 LSB per halving)."""
    if x >= 0:
        return (x + 1) >> 1
    return -((-x + 1) >> 1)


def _sign_mul(x, sgn):
    """Engine mul_ps(+/-1, x): exact."""
    return _sat(x if sgn > 0 else -x)


def _mode1_body(a):
    """mode<1> evaluated at argument a (the c2x operand is derived from a):
    c2x = 1 - 2*a*a; uh = 0.5*(1-c2x) = a^2; lh = 0.5*(c2x-1) = -a^2,
    in the pinned op order."""
    c2x = _sat(ONE - _shl1(vm.qmul(a, a)))
    uh = _half(_sat(ONE - c2x))
    lh = _half(_sat(c2x - ONE))
    return (uh if a >= 0 else lh), c2x


def _mode3_body(a):
    """mode<3> body at argument a: the uh half of mode 1."""
    c2x = _sat(ONE - _shl1(vm.qmul(a, a)))
    uh = _half(_sat(ONE - c2x))
    return uh if a >= 0 else 0, c2x


def _mode28_body(s, c):
    """mode<28> body: triangle on the quadrants (used directly and by 30)."""
    sw = ONE if s >= 0 else -ONE
    q24 = vm.qmul(s, c) < 0
    pm = ONE if q24 else -ONE
    return _sat(sw + _sign_mul(c, 1 if q24 else -1))


def shape_out(mode, s, c):
    """valueFromSinAndCosForMode<mode>(s, c) on Q10.21 words, pinned op order.

    The engine evaluates these as SSE selects (and_ps/andnot_ps over
    compare masks); on integer words every compare is exact and every
    select is a branch. Products of two non-trivial words go through
    vm.qmul (round-half-up); *2 / *0.5 are exact in float32 and half-up
    shifts here (see _shl1/_half). Divisions by the quadrant (modes 25/27)
    are float32 divisions in the engine and exact-then-round-half-up Q
    divisions here (declared deviation).
    """
    if mode == 0:                                   # pure sine
        return s
    if mode == 1:                                   # S^2 hump (full)
        v, _ = _mode1_body(s)
        return v
    if mode == 2:                                   # first half of sine
        return s if s >= 0 else 0
    if mode == 3:                                   # S^2 hump (first half)
        v, _ = _mode3_body(s)
        return v
    if mode == 4:                                   # sin 2x in first half
        s2x = _shl1(vm.qmul(s, c))
        return s2x if s >= 0 else 0
    if mode in (5, 7):                              # double-freq mode 1
        s2x = _shl1(vm.qmul(s, c))
        v1, _ = _mode1_body(s2x)
        v = v1 if s >= 0 else 0
        return abs(v) if mode == 7 else v
    if mode == 6:                                   # abs sin 2x, first half
        s2x = _shl1(vm.qmul(s, c))
        return abs(s2x if s >= 0 else 0)
    if mode == 8:                                   # 2*first-half-sine - 1
        return _sat(_shl1(s if s >= 0 else 0) - ONE)
    if mode == 9:                                   # zero quadrants 1 and 3
        css = vm.qmul(s, c)
        return s if css <= 0 else 0
    if mode == 10:                                  # zero quadrants 2 and 4
        css = vm.qmul(s, c)
        return s if css >= 0 else 0
    if mode == 11:                                  # 2*mode3 - 1
        q = _mode3_body(s)[0]
        return _sat(_shl1(q) - ONE)
    if mode == 12:                                  # s2x, sign flip on c < 0
        s2x = _shl1(vm.qmul(s, c))
        return _sign_mul(s2x, 1 if c >= 0 else -1)
    if mode == 13:                                  # flip s2x sign on s<=0, q13
        s2x = _shl1(vm.qmul(s, c))
        v = _sign_mul(s2x, -1 if s <= 0 else 1)
        return v if s2x >= 0 else 0
    if mode == 14:                                  # abs(cos 2x) in first half
        c2x = _sat(ONE - _shl1(vm.qmul(s, s)))
        return abs(c2x) if s >= 0 else 0
    if mode == 15:                                  # 1-s / -1-s on q14
        sig = _sat(ONE - s) if s >= 0 else _sat(-ONE - s)
        return sig if c >= 0 else 0
    if mode == 16:                                  # 1-s / c-1 on q14
        sig = _sat(ONE - s) if s >= 0 else _sat(c - ONE)
        return sig if c >= 0 else 0
    if mode == 17:                                  # +1-s / -1-s
        sw = ONE if s >= 0 else -ONE
        return _sat(sw - s)
    if mode == 18:                                  # s2x q1, c q23, -s2x q4
        s2x = _shl1(vm.qmul(s, c))
        if c <= 0:
            return c
        return _sign_mul(s2x, 1 if s >= 0 else -1)
    if mode == 19:                                  # double-freq shape-0 hybrid
        s2x = _shl1(vm.qmul(s, c))
        c2x = _sat(ONE - _shl1(vm.qmul(s, s)))
        s4x = _shl1(vm.qmul(s2x, c2x))
        fh = _sat((s2x if c >= 0 else 0) - (0 if c >= 0 else s4x))
        return fh if s >= 0 else s
    if mode == 20:                                  # sine in q2/q4, +/-1 q1/q3
        sbc = vm.qmul(s, c)
        q13 = sbc >= 0
        mv = ONE if s >= 0 else -ONE
        return s if q13 else mv
    if mode == 21:                                  # sine in q1/q3, +/-1 q2/q4
        sbc = vm.qmul(s, c)
        q13 = sbc >= 0
        mv = ONE if s >= 0 else -ONE
        return mv if q13 else s
    if mode == 22:                                  # sine on c >= 0
        return s if c >= 0 else 0
    if mode == 23:                                  # sine on c <= 0
        return s if c <= 0 else 0
    if mode == 24:                                  # 1-s first half, s second
        return _sat(ONE - s) if s >= 0 else s
    if mode == 25:                                  # s2x / quadrant, first half
        s2x = _shl1(vm.qmul(s, c))
        qv = _calcquadrant(s, c)
        return vm.qdiv(s2x, qv, fb=0) if s >= 0 else 0
    if mode == 26:                                  # zero quadrant 3
        return 0 if (s <= 0 and c <= 0) else s
    if mode == 27:                                  # s2x / quadrant
        s2x = _shl1(vm.qmul(s, c))
        return vm.qdiv(s2x, _calcquadrant(s, c), fb=0)
    if mode == 28:                                  # triangle on quadrants
        return _mode28_body(s, c)
    if mode == 29:                                  # 1-/+ c in first half
        fh = ONE if s >= 0 else 0
        q2 = s >= 0 and c <= 0
        cx = _sign_mul(c, 1 if q2 else -1) if s >= 0 else 0
        return _sat(fh + cx)
    if mode == 30 or mode == 31:                    # corrected 5 / 7
        s2x = _shl1(vm.qmul(s, c))
        c2x = _sat(ONE - _shl1(vm.qmul(s, s)))
        v1 = _mode28_body(s2x, c2x)
        r = v1 if s >= 0 else 0
        return abs(r) if mode == 31 else r
    raise RuntimeError("shape mode %r outside declared [0, 31]" % (mode,))


def _calcquadrant(s, c):
    """calcquadrantSSE: 3*(s<=0) + (c<=0) - 2*(s<=0)*(c<=0) + 1."""
    sxl0 = 1 if s <= 0 else 0
    cxl0 = 1 if c <= 0 else 0
    return 3 * sxl0 + cxl0 - 2 * sxl0 * cxl0 + 1


def pitch_to_omega_q28(pitch, detune_f, samplerate=SR * HPF_OSC):
    """OscillatorBase pitch_to_omega(min M_PI): double formula, Q3.28 once.

    omega = min(pi, 2*pi*MIDI_0_FREQ*note_to_pitch(pitch + detune)/sr_os);
    note_to_pitch from the pinned construction formula (declared deviation:
    the engine lerps a float32 table). `detune_f` is the float32 per-voice
    detune promoted to double, exactly as the engine's `pitch + detune`.
    """
    w = (float(pitch) + float(detune_f)) / 12.0
    freq = vm.MIDI_0_FREQ * (2.0 ** w)
    omega = 2.0 * math.pi * freq / samplerate
    if omega > math.pi:
        omega = math.pi
    return vm.qint28(omega)


def _rdiv64(d):
    """omegaStep = (omega - omegaPrior) * (1/64), exact in double; the Q3.28
    word rounds half-up (declared deviation; inert at constant pitch)."""
    if d >= 0:
        return (d + 32) >> 6
    return -((-d + 32) >> 6)


def _rhalf(x):
    if x >= 0:
        return (x + 1) >> 1
    return -((-x + 1) >> 1)


class QuadrVoice:
    """SurgeQuadrOsc<float> (legacy non-FM path), per unison voice.

    Ctor state r = 0, i = -1 (retrigger); set_rate: dr = cos w, di = sin w
    (double math on the float-narrowed omega, quantized once - declared
    deviation), then normalize (r, i) with the double 1/sqrt exactly as the
    landed SXT-026a SineCore.set_rate.
    """

    def __init__(self):
        self.r = 0
        self.i = -ONE
        self.dr = 0
        self.di = 0

    def set_rate(self, omega_q28):
        w = omega_q28 / float(1 << FQ28)
        self.dr = vm.qint(math.cos(w))
        self.di = vm.qint(math.sin(w))
        rd = self.r / float(ONE)
        idd = self.i / float(ONE)
        n = 1.0 / math.sqrt(rd * rd + idd * idd)
        self.r = vm.qint(rd * n)
        self.i = vm.qint(idd * n)

    def process(self):
        lr, li = self.r, self.i
        self.r = _sat(vm.qmul(self.dr, lr) - vm.qmul(self.di, li))
        self.i = _sat(vm.qmul(self.dr, li) + vm.qmul(self.di, lr))


class Lag:
    """sst-basic-blocks SurgeLag ("lag<double>") at the default rate 0.004.

    newValue = setTarget (first-run snap); process(): v = v*lpinv + t*lp,
    once per OS sample. Double in the engine, Q10.21 words here (declared
    deviation; constant targets converge to the target word).
    """

    def __init__(self):
        self.v = 0
        self.t = 0
        self.first = True

    def new_value(self, f):
        if self.first:
            self.v = f
            self.first = False
        self.t = f

    def process(self):
        self.v = _sat(vm.qmul(self.v, LAG_LPINV) + vm.qmul(self.t, LAG_LP))


class CharFilter:
    """Surge::Oscillator::CharacterFilter<float> (Warm/Neutral declared).

    Warm (character 0): one-pole (1-2*5000/sr)^2 with B0 = 1-filt, B1 = 0;
    Neutral (1): identity, doFilter false; Bright (2) refuses. The `starting`
    warm start (first block initializes priors from output[0]) is modeled.
    """

    def __init__(self, character):
        if character == 0:
            filt = vm.qint(_f32x(_f32x(1.0 - 2.0 * 5000.0 / 48000.0)
                                 * _f32x(1.0 - 2.0 * 5000.0 / 48000.0)))
            self.b0 = _sat(ONE - filt)
            self.b1 = 0
            self.a1 = filt
            self.do_filter = True
        elif character == 1:
            self.b0, self.b1, self.a1 = ONE, 0, 0
            self.do_filter = False
        else:
            raise RuntimeError("character Bright not in SXT-040 slice")
        self.py = 0
        self.px = 0
        self.starting = True

    def process_block(self, out):
        if not self.do_filter:
            return
        if self.starting:
            self.py = out[0]
            self.px = out[0]
            self.starting = False
        for k in range(len(out)):
            pf = _sat(vm.qmul(self.a1, self.py) + vm.qmul(self.b0, out[k])
                      + vm.qmul(self.b1, self.px))
            self.py = pf
            self.px = out[k]
            out[k] = pf


class AdsrSine(cm.AdsrClassic):
    """SXT-022 digital-mode ADSR extended with decay shape d_s = 2 and
    attack shapes a_s in {0, 2} (the landed slice declares a_s = 1 only).

    Pinned ADSRModulationSource.h:
      decay case 2 (cube-root two-limits form):
        sx = phase^(1/3)
        l_lo = phase - 3*sx*sx*rate + 3*sx*rate*rate - rate*rate*rate
        l_hi = phase + 3*sx*sx*rate + 3*sx*rate*rate + rate*rate*rate
        (no case-1 sustain/rate gates - those are inside `case 1:` only)
      attack case 0: output = sqrt(phase); case 2: output = phase*phase
    Evaluated in double at the pinned op order like the SXT-026 sqrt path;
    the engine evaluates float32 per op (declared deviation). The frozen
    SXT-033 file is imported unchanged; the sqrt decay (d_s = 1) and the
    linear attack (a_s = 1) are the landed super forms.
    """

    def __init__(self, prm, name):
        if int(prm["d_s"]) not in (0, 1, 2):
            raise RuntimeError(
                f"{name}: decay shape {prm['d_s']} not in slice (0, 1 or 2)")
        if int(prm["a_s"]) not in (0, 1, 2):
            raise RuntimeError(
                f"{name}: attack shape {prm['a_s']} not in slice (0, 1 or 2)")
        super().__init__({**prm, "d_s": 0}, name)
        self.d_s = int(prm["d_s"])

    def process_block(self):
        if self.state == self.S_ATTACK and self.a_s in (0, 2):
            # attack shapes 0/2 (pinned): sqrt(phase) / phase*phase; the
            # landed vm.Adsr attack branch is a_s == 1 (linear) only
            self.phase += vm.envelope_rate_linear_nowrap(self.a)
            if self.phase >= (1 << vm.F_PHASE):
                self.phase = 1 << vm.F_PHASE
                self.state = self.S_DECAY
                self.s_lvl = self.s
            ph = self.phase >> (vm.F_PHASE - vm.FQ)
            if self.a_s == 0:
                self.output = int(math.floor(
                    math.sqrt(ph / float(vm.ONE)) * vm.ONE + 0.5))
            else:
                self.output = vm.qmul(ph, ph)
        elif self.state == self.S_DECAY and self.d_s == 2:
            FP = vm.F_PHASE
            rate = vm.envelope_rate_linear_nowrap(self.d)
            sx = int(math.floor((self.phase / float(1 << FP))
                                ** (1.0 / 3.0) * (1 << FP) + 0.5))
            q29 = dict(fa=FP, fb=FP, fq=FP)
            three_sx = vm.qmul(vm.qint_phase(3.0), sx, **q29)
            t = vm.qmul(three_sx, sx, **q29)          # 3*sx*sx
            t = vm.qmul(t, rate, **q29)               # *rate
            u = vm.qmul(three_sx, rate, **q29)        # 3*sx*rate
            u = vm.qmul(u, rate, **q29)               # *rate
            v = vm.qmul(vm.qmul(rate, rate, **q29), rate, **q29)
            l_lo = self.phase - t + u - v
            l_hi = self.phase + t + u + v
            self.phase = vm.limit_i(self.s, l_lo, l_hi)
            self.output = self.phase >> (FP - vm.FQ)
        else:
            super().process_block()
        self.output = vm.limit_i(self.output, 0, ONE)


class SineOsc:
    """SineOscillator slice: mono output (fbc serial-1), drift 0 (asserted),
    FM routing off (fixture override), per-unison-voice state over the
    declared shape modes and both behaviors."""

    def __init__(self, inp, key):
        self.inp = inp
        n = inp.unison
        if not 1 <= n <= MAX_UNISON:
            raise RuntimeError(
                "unison %d outside 1..MAX_UNISON(%d): explicitly rejected"
                % (n, MAX_UNISON))
        self.n_unison = n
        if inp.absolute_detune:
            raise RuntimeError("absolute detune mode not in SXT-040 slice")
        if inp.drift != 0.0:
            raise RuntimeError("scene drift not 0 (determinism gate)")
        if not isinstance(inp.shape, int) or not SHAPE_MIN <= inp.shape <= SHAPE_MAX:
            raise RuntimeError("shape %r outside declared [%d, %d]"
                               % (inp.shape, SHAPE_MIN, SHAPE_MAX))
        self.mode = inp.shape
        if inp.fmmode not in (0, 1):
            raise RuntimeError("behavior %r outside declared {0, 1}"
                               % (inp.fmmode,))
        self.legacy = (inp.fmmode == 0)

        # SurgeVoice noteShiftFromPitchParam + scene/osc octaves: the osc
        # pitch param enters as f*(12 when its extend_range flag is set,
        # else f) - the flag is engine-read at extraction (SXT-033 pinned
        # the extended form only; its carriers all had pitch_param 0).
        # The sine osc has no pitchmult machine, so pitch stays float.
        base = float(key) if inp.keytrack else 60.0
        pitch_off = inp.pitch_param * (12.0 if inp.pitch_extend else 1.0)
        self.pitch = min(148.0, base + 12.0 * (inp.scene_octave + inp.octave)
                         + pitch_off)
        if not 24 <= self.pitch <= 148:
            raise RuntimeError("declared slice osc pitch range is [24, 148]")

        # prepare_unison / UnisonSetup (float32 op order at quantization time)
        att_inv = _f32x(math.sqrt(1.0 * n))
        self.out_attenuation = vm.qint(_f32x(1.0 / att_inv))
        udet_f = _f32x(12.0 * inp.udet) if inp.extend_detune else _f32x(inp.udet)
        self.voice_detune = []          # float32 semitones, per voice
        self.omega_u = []               # Q3.28 omega, per voice
        for v in range(n):
            if n == 1:
                detune_f = 0.0
            else:
                bias = 2.0 / (n - 1)    # double in the UnisonSetup ctor
                inner = _f32x(_f32x(bias * float(v)) + -1.0)
                detune_f = _f32x(udet_f * inner)
            self.voice_detune.append(detune_f)
            self.omega_u.append(pitch_to_omega_q28(self.pitch, detune_f))

        # feedback (modern path only): fb_val = get_extended(localcopy) with
        # extendFactor 4 for ct_osc_feedback_negative (extend flag engine-read)
        self.fb_t = 0
        if not self.legacy:
            fb_f = _f32x(4.0 * float(inp.fb)) if inp.fb_extend \
                else _f32x(float(inp.fb))
            self.fb_t = vm.qint(fb_f)

        # per-voice state
        if self.legacy:
            # SurgeQuadrOsc ctor (r=0, i=-1) + prepare_unison playingramp
            self.quad = [QuadrVoice() for _ in range(n)]
            self.pramp = [ONE] + [0] * (n - 1)
            self.phase = [0] * n
            self.lv0 = [0] * n
            self.lv1 = [0] * n
            self.om_prior = [0] * n
        else:
            self.quad = None
            self.pramp = None
            # retrigger: phase 0 (init); omega ramp machine
            self.phase = [0] * n
            self.lv0 = [0] * n
            self.lv1 = [0] * n
            self.om_prior = [0] * n
            self.prior_valid = False
        self.firstblock = True          # init: retrigger -> true

        # FMdepth / FB lags (FM depth declared inert under the fixture
        # fm_switch=0 override: fv target 0, never multiplied into audio)
        self.fm = Lag()
        self.fb = Lag()
        self.fm.new_value(0)
        self.fb.new_value(self.fb_t)

        # applyFilter biquads (coeff_HP / coeff_LP2B from the constant param
        # values; per-block recompute of constant coefficients == constant)
        self.hp = vm.TDFBiquad(vm.biquad_hp_coeffs(inp.lowcut / 12.0))
        self.lp = vm.TDFBiquad(vm.biquad_lp2b_coeffs(inp.highcut / 12.0))

        # character filter (patch character; inside the osc instance)
        self.charfilt = CharFilter(inp.character)

    # -------------------------------------------------------------- block
    def process_block(self):
        """One 64-OS-sample block; returns the post-filter output block."""
        n = self.n_unison
        out = []
        if self.legacy:
            # legacy: omega per voice + SurgeQuadrOsc set_rate per block
            for u in range(n):
                self.quad[u].set_rate(self.omega_u[u])
            dp = DPLAYING
            for k in range(BLOCK_SIZE_OS):
                acc = 0
                for u in range(n):
                    q = self.quad[u]
                    q.process()
                    v = shape_out(self.mode, q.r, q.i)
                    # (panL*out)*atten*ramp; the linear UnisonSetup pan law
                    # makes (panL+panR)/2 = 1 exactly: mono-inert (declared)
                    t = vm.qmul(vm.qmul(v, self.out_attenuation), self.pramp[u])
                    acc += t
                    if self.pramp[u] < ONE:
                        self.pramp[u] = min(ONE, self.pramp[u] + dp)
                out.append(_sat(acc))
        else:
            fbv = abs(self.fb.v)
            fbneg = self.fb.v < 0
            # omega ramp (omegaPrior machinery): first block anchors, then
            # step/curr; constant pitch keeps both at 0/omega (declared)
            if not self.prior_valid:
                for u in range(n):
                    self.om_prior[u] = self.omega_u[u]
                self.prior_valid = True
            om_step = [0] * n
            om_curr = [0] * n
            for u in range(n):
                om_step[u] = _rdiv64(self.omega_u[u] - self.om_prior[u])
                om_curr[u] = self.omega_u[u] - _rhalf(63 * om_step[u])
                self.om_prior[u] = self.omega_u[u]
            first = self.firstblock
            dstep = ONE >> 6                    # BLOCK_SIZE_OS_INV = 1/64
            for k in range(BLOCK_SIZE_OS):
                acc = 0
                for u in range(n):
                    lv = self.lv1[u]            # fb_mode 0 (type_1): lv = lv1
                    fba = vm.qmul(lv, fbv) if not fbneg else \
                        vm.qmul(vm.qmul(lv, lv), fbv)
                    x = vm.clamp_to_pi(self.phase[u] + fba)
                    s = vm.fastsin_ratio(x)
                    c = vm.fastcos_ratio(x)
                    v = shape_out(self.mode, s, c)
                    ramp = ONE if (u == 0 or not first) else (k * dstep)
                    t = vm.qmul(vm.qmul(v, ramp), self.out_attenuation)
                    acc += t
                    self.lv0[u] = self.lv1[u]
                    self.lv1[u] = v
                    self.phase[u] += om_curr[u]
                    if self.phase[u] > PI_Q28:
                        self.phase[u] -= TWO_PI_Q28
                self.fm.process()
                self.fb.process()
                out.append(_sat(acc))
            self.firstblock = False
        # applyFilter (lowcut then highcut), then the character filter
        self.hp.process_block(out)
        self.lp.process_block(out)
        self.charfilt.process_block(out)
        return out


class Slice:
    """Voice slice: Sine osc -> o-level -> pfg -> AEG gain ramp -> scene out
    (accumulated into the shared scene bus). Staging mirrors the frozen
    SXT-033 classic Slice (`classic_model.Slice`); the scene decimator,
    master gain and output clips live in the runner. All other mixer paths
    (oscs/noise/ring modulators) and both filter units are muted/off by the
    declared fixture configuration (see fixture_config.py) - test
    configurations, never adapted presets, never coverage."""

    def __init__(self, inp, key, velocity):
        self.inp = inp
        self.key = key
        self.gate = True
        self.osc = SineOsc(inp, key)
        self.aeg = AdsrSine(inp.adsr, "aeg")
        self.aeg.attack_from(0)
        self.lvl = vm.amp_to_linear(vm.qint(inp.o_level))
        self.pfg = vm.db_to_linear(vm.qint(inp.level_pfg))
        vca_db_eff = inp.vca_db + inp.vca_vs * (1.0 - velocity / 127.0)
        self.vca = vm.db_to_linear(vm.qint(vca_db_eff))
        # mono pan law (SXT-033 convention): (megapanL+megapanR)/2 = 1-0.25p^2
        pan_f = max(-1.0, min(1.0, inp.pan))
        mono_law = vm.qint(1.0 - 0.25 * pan_f * pan_f)
        self.outl = vm.qmul(vm.amp_to_linear(vm.qint(inp.scene_volume)) >> 1,
                            mono_law)
        self.gain = vm.qmul(self.vca, self.aeg.output)
        self.prev_gain = self.gain
        self.keep_playing = True

    def process_block(self, b, scene):
        """One 32-sample block: envelope step, osc block, gain-ramped
        accumulation into `scene` (64 OS samples). Returns (osc_out, keep)."""
        self.aeg.process_block()
        if self.aeg.is_idle():
            self.keep_playing = False
        osout = self.osc.process_block()
        target = vm.qmul(self.vca, self.aeg.output)
        d_gain = target - self.prev_gain
        gain_start = self.prev_gain
        self.prev_gain = target
        for k in range(BLOCK_SIZE_OS):
            x = vm.qmul(vm.qmul(osout[k], self.lvl), self.pfg)
            scene[k] += vm.qmul(vm.qmul(x, gain_start + vm.qround(d_gain * (k + 1), 6)),
                                self.outl)
        # control-plane words for the RTL record (post-block state)
        self.ctrl_gain_start = gain_start
        self.ctrl_d_gain = d_gain
        return osout, self.keep_playing


class Inputs:
    """Frozen model inputs (inputs/<name>.json, extracted by
    extract_inputs.py from the pinned engine - never guessed)."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.preset_path = d["preset_path"]
        self.preset_census_blob_sha1 = d["preset_census_blob_sha1"]
        self.slot = int(d["slot"])
        self.octave = int(d["octave"])
        self.scene_octave = int(d.get("scene_octave", 0))
        self.keytrack = bool(d.get("keytrack", True))
        self.pitch_param = d.get("pitch_param", 0.0)
        self.pitch_extend = bool(d.get("pitch_extend", False))
        shape = int(d["shape"])
        if os.environ.get("SXT040_NC_SHAPE_RAWVALUE"):
            # NEGATIVE CONTROL (issue #74): force the PRE-MIGRATION raw
            # shape value (the sine_shape_remap confusion) against the
            # normalized reference render - the budget check must FAIL.
            # Never set for real runs.
            shape = int(os.environ["SXT040_NC_SHAPE_RAWVALUE"])
        self.shape = shape
        self.fb = d["fb"]
        self.fb_extend = bool(d.get("fb_extend", False))
        self.fmmode = int(d["fmmode"])
        self.lowcut = d["lowcut"]
        self.highcut = d["highcut"]
        self.udet = d["unison_detune"]
        self.extend_detune = bool(d.get("extend_detune", False))
        self.absolute_detune = bool(d.get("absolute_detune", False))
        self.unison = int(d["unison"])
        self.retrigger = bool(d["retrigger"])
        self.character = int(d["character"])
        self.drift = d.get("drift", 0.0)
        self.o_level = d["o_level"]
        self.level_pfg = d.get("level_pfg", 0.0)
        self.pan = d.get("pan", 0.0)
        self.scene_volume = d["scene_volume"]
        self.vca_db = d["vca_db"]
        self.vca_vs = d.get("vca_velsense", 0.0)
        self.master_db = d["master_db"]
        self.adsr = d["adsr"]
        self.declared_overrides = d.get("declared_overrides", [])
