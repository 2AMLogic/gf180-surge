#!/usr/bin/env python3
"""SXT-022 frozen fixed-point voice model for factory preset `Basses/Attacky.fxp`.

This module is the FROZEN reference for the SXT-022 RTL (`rtl/voice/`).
RTL-vs-model agreement must be EXACT (integer equality at every declared
checkpoint). Model-vs-pinned-engine agreement is governed by error budgets
(fidelity policy DRAFT; budgets are not frozen -- SXT-022 reports achieved
numbers only, no freeze claims).

Word lengths and operation order are normative: `model/voice/README.md`.

SXT-026a extension (issue #48): the voice class is generalized beyond the
Attacky slice -- Sine oscillator (legacy path, incl. the fm_3to2to1 muted
FM-source chain), LP 24 dB/Driven (IIR24CFC two-section coupled form),
serial-1 Mix1 filter-balance blend, and velocity/keytrack modulation routes.
The v1 (Classic/LP12) arithmetic is unchanged: class-v1 fixtures render
bit-identically to the SXT-022 model. The extension is frozen in
`model/voice/README.md` (sections "SXT-026a extension").

Structure is cited from the pinned engine (read, not copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  SurgeVoice.cpp process_block/calc_ctrldata/SetQFB    gain staging + ramps
  ClassicOscillator.cpp init/prepare_unison/process_block/convolute
                                                       impulse engine +
                                                       unison stack (SXT-034)
  OscillatorCommonFunctions.h prepare_unison           unison setup
  sst-basic-blocks OscillatorDriftUnisonCharacter.h    UnisonSetup (attenuation,
                                                       detune bias/offset, pan law)
  SineOscillator.cpp process_block_legacy/applyFilter  Sine (legacy, FM 3>2>1)
  sst-basic-blocks QuadratureOscillators.h SurgeQuadrOsc  sine recurrence
  sst-basic-blocks FastMath.h fastsin/fastcos/clampToPiRange  FM sine math
  sst-filters BiquadFilter.h coeff_HP/coeff_LP2B/TDF2  osc low/high cut
  QuadFilterChain.cpp ProcessFBQuad (fc_serial1)       per-OS-sample chain
  sst-filters FilterCoefficientMaker_Impl.h            Coeff_LP12/24 +
                                                       ToCoupledForm/FromDirect
  sst-filters QuadFilterUnit_Impl.h IIR12CFC/IIR24CFC  coupled forms
  ADSRModulationSource.h (digital mode)                envelopes
  ModulationSource.h ControllerModulationSourceVector  FAST_LINE modwheel
  sst-filters HalfRateFilter.h (M=6, steep)            scene decimator
  sst-basic-blocks OscillatorDriftUnisonCharacter.h    CharacterFilter (Warm)
  SurgeStorage init_tables + lookup functions          tables recomputed

Arithmetic discipline (FROZEN, enforced throughout):
  * every value is a Python int in two's-complement Q-format;
  * Q10.21 universal sample/coef word; Q2.29 envelope phase;
    Q13.18 pitchmult_inv; 16-bit sinc lipol fraction;
    Q3.28 radian phase/omega words (SXT-026a Sine path);
  * products are exact then rounded back round-half-up:
        r = (a*b + (1 << (s-1))) >> s,  s = fa+fb-fq
    and saturated to the signed 32-bit range;
  * divisions at coefficient (block) rate via qdiv (round-half-up);
    DECLARED EXCEPTION (SXT-026a): the Sine FM path evaluates the pinned
    fastsin/fastcos rational (an audio-rate division) with exact integer
    arithmetic and ONE final round-half-up to Q10.21 -- diverges from cost
    assumption A-ALU-2 and is recorded for SXT-016;
  * sinc sub-sample position truncates toward zero like the engine's
    (unsigned int) cast;
  * no floating point at run time (coefficient/quantization-time only);
    no dict-iteration-order dependence.
"""

import json
import math
import os
import struct

SR = 48000
BLOCK_SIZE = 32
BLOCK_SIZE_OS = 64
OB_LENGTH = 128          # globals.h: BLOCK_SIZE_OS << 1
FIRIPOL_M = 256          # SurgeStorage.h
FIRIPOL_N = 12
FIROFFSET = FIRIPOL_N >> 1
MAX_UNISON = 16          # SurgeStorage.h (unison cap; profile-v1 cap too)

FQ = 21                    # universal Q10.21 sample/coef word (32-bit)
QMAX = (1 << 31) - 1
QMIN = -(1 << 31)
F_PHASE = 29               # envelope phase Q2.29
PMI_F = 18                 # pitchmult_inv Q13.18 (pitch >= 24 declared)
ONE = 1 << FQ

MIDI_0_FREQ = 8.175798915  # Tunings::MIDI_0_FREQ
TUNING_PITCH = 32.0        # SurgeStorage tuningPitch for 12-TET (2^(60/12))


# ---------------------------------------------------------------- Q helpers
def sat(x):
    return QMIN if x < QMIN else (QMAX if x > QMAX else x)


def qround(x, s):
    """Round-half-up arithmetic shift by s (left shift when s < 0), saturated."""
    if s <= 0:
        return sat(x << (-s))
    return sat((x + (1 << (s - 1))) >> s)


def qmul(a, b, fa=FQ, fb=FQ, fq=FQ):
    s = fa + fb - fq
    if s > 0:
        return sat((a * b + (1 << (s - 1))) >> s)
    return sat(a * b << (-s))


def qdiv(a, b, fa=FQ, fb=FQ, fq=FQ):
    """Round-half-up signed division; coefficient rate only."""
    assert b != 0, "qdiv by zero"
    sh = fb - fa + fq
    num = a << sh if sh >= 0 else a >> (-sh)
    half = abs(b) >> 1
    if b > 0:
        q = (num + half) // b if num >= 0 else -((-num + half) // b)
    else:
        q = (num - half) // b if num >= 0 else -((-num - half) // b)
    return sat(q)


def qint(x):
    """Quantize a double to Q4.27, round-half-up (quantization-time only)."""
    return sat(int(math.floor(x * ONE + 0.5)))


def qint_phase(x):
    return sat(int(math.floor(x * (1 << F_PHASE) + 0.5)))


def limit_i(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


# ------------------------------------------------- engine tables (formulas)
# Frequency-domain conversions (note_to_pitch family, envelope rate table,
# dB table) are evaluated in double precision against the pinned table
# FORMULAS and quantized once to the target Q word. Declared deviation: the
# engine lerps float32 tables; the model evaluates the construction formulas
# directly (agreement within one float32 ulp, folded into the error budget).

def _envrate_lerp(x):
    """storage::envelope_rate_linear_nowrap body (float32 table eval)."""
    x *= 16.0
    x += 256.0
    e = limit_i(int(x), 0, (1 << 9) - 2)
    a = x - float(e)
    lo = 1.0 / (96000.0 * (2.0 ** ((e - 256) / 16.0)) / 64.0)
    hi = 1.0 / (96000.0 * (2.0 ** ((e + 1 - 256) / 16.0)) / 64.0)
    return (1 - a) * lo + a * hi


def _dbl_dB(e):
    return 10.0 ** (0.05 * (e - 384.0))


def _dbl_pitch(e):
    return 2.0 ** ((e - 256) / 12.0)


def ntpi_ignoring_tuning(x):
    """note_to_pitch_inv_ignoring_tuning(x); x Q10.21 -> Q10.21."""
    xf = x / float(1 << FQ)
    xf = min(max(xf + 256.0, 1e-4), 511.0 - 1e-4)
    e = int(xf)
    a = xf - e
    pow2pos = a * 1000.0
    idx = int(pow2pos)
    frac = pow2pos - idx
    pow2v = (1 - frac) * (2.0 ** (idx / 1000.0)) + frac * (2.0 ** ((idx + 1) / 1000.0))
    return qint(_dbl_pitch(e) ** -1.0 * pow2v)


def ntp_tuningctr(x):
    """note_to_pitch_tuningctr(x) = note_to_pitch(x+60) * (1/32)."""
    xf = x / float(1 << FQ)
    xf = min(max(xf + 256.0 + 60.0, 0.0), 513.0)
    e = int(xf)
    a = xf - e
    v = (1 - a) * _dbl_pitch(e) + a * _dbl_pitch(e + 1)
    return qint(v / TUNING_PITCH)


def ntpi_tuningctr(x):
    """note_to_pitch_inv_tuningctr(x) = note_to_pitch_inv(x+60) * 32."""
    xf = x / float(1 << FQ)
    xf = min(max(xf + 256.0 + 60.0, 1e-4), 511.0 - 1e-4)
    e = int(xf)
    a = xf - e
    pow2pos = a * 1000.0
    idx = int(pow2pos)
    frac = pow2pos - idx
    pow2v = (1 - frac) * (2.0 ** (idx / 1000.0)) + frac * (2.0 ** ((idx + 1) / 1000.0))
    return qint(TUNING_PITCH / _dbl_pitch(e) * pow2v)


def note_to_omega(x):
    """storage::note_to_omega_ignoring_tuning -> (sinu, cosi) Q10.21."""
    xf = x / float(1 << FQ)
    xf = min(max(xf + 256.0, 0.0), 513.0)
    e = int(xf)
    a = xf - e
    p = (1 - a) * _dbl_pitch(e) + a * _dbl_pitch(e + 1)
    ph = min(0.5, 440.0 * p / 96000.0)
    return qint(math.sin(2 * math.pi * ph)), qint(math.cos(2 * math.pi * ph))


def envelope_rate_linear_nowrap(x):
    """Envelope phase increment per 32-sample block, Q2.29."""
    return qint_phase(_envrate_lerp(x / float(1 << FQ)))


def db_to_linear(x):
    xf = x / float(1 << FQ) + 384.0
    e = int(xf)
    a = xf - float(e)
    return qint((1 - a) * _dbl_dB(e & 511) + a * _dbl_dB((e + 1) & 511))


def amp_to_linear(x):
    """max(0,x)^3 with declared per-multiply rounding (engine float x*x*x)."""
    x = max(0, x)
    return qmul(qmul(x, x), x)


# ------------------------------------------------------------- sinc tables
def _f32(x):
    """Round a double to the nearest float32 value (struct round-trip)."""
    return struct.unpack("f", struct.pack("f", x))[0]


def build_sinctable():
    """Windowed-sinc table from the pinned construction formulas.

    sst-basic-blocks tables/SincTableProvider.h (SurgeSincTableProvider):
        t = -i + FIRIPOL_N/2 + j/FIRIPOL_M - 1
        val = symmetric_blackman(t, FIRIPOL_N) * 0.455 * sincf(0.455*t)
        sinctable[j*2N + i]      = val
        sinctable[j*2N + N + i]  = (val_f32(j+1,i) - val_f32(j,i)) / 65536
    The engine stores float32 values; the derivative slot is the difference
    of the FLOAT32 main values divided by 65536 (float32), then quantized
    once to Q10.21 for the fixed-point model. Provenance: construction
    formulas cited; no table bytes are copied from any repository.
    """
    main = []
    for j in range(FIRIPOL_M + 1):
        for i in range(FIRIPOL_N):
            t = -float(i) + float(FIRIPOL_N / 2.0) + float(j) / float(FIRIPOL_M) - 1.0
            n = FIRIPOL_N
            tt = t - (n / 2)
            win = (0.42 - 0.5 * math.cos(2 * math.pi * tt / n)
                   + 0.08 * math.cos(4 * math.pi * tt / n))
            xc = 0.455 * t
            sc = 1.0 if xc == 0 else math.sin(math.pi * xc) / (math.pi * xc)
            main.append(_f32(win * 0.455 * sc))
    tab = [qint(v) for v in main]
    deriv = []
    for j in range(FIRIPOL_M):
        for i in range(FIRIPOL_N):
            d = _f32((main[(j + 1) * FIRIPOL_N + i] - main[j * FIRIPOL_N + i]) / 65536.0)
            deriv.append(qint(d))
    return tab, deriv


SINC_MAIN, SINC_DERIV = build_sinctable()

# Halfband (order 12, steep) coefficients: quoted scalar constants from the
# pinned sst-filters HalfRateFilter.h; provenance in decision-records/DR-0001.
HALFBAND_A = [0.036681502163648017, 0.2746317593794541, 0.56109896978791948,
              0.769741833862266, 0.8922608180038789, 0.962094548378084]
HALFBAND_B = [0.13654762463195771, 0.42313861743656667, 0.6775400499741616,
              0.839889624849638, 0.9315419599631839, 0.9878163707328971]
HALFBAND_A_Q = [qint(v) for v in HALFBAND_A]
HALFBAND_B_Q = [qint(v) for v in HALFBAND_B]


# --------------------------------------------------------------- envelopes
class Adsr:
    """ADSRModulationSource, digital mode (fail-closed on analog/shapes != 0)."""

    S_ATTACK, S_DECAY, S_SUSTAIN, S_RELEASE, S_UBER, S_IDLE_WAIT1, S_IDLE = range(7)

    def __init__(self, prm, name):
        if int(prm["mode"]) != 0:
            raise RuntimeError(f"{name}: analog envelope mode not in SXT-022 slice")
        if int(prm["d_s"]) != 0:
            raise RuntimeError(f"{name}: decay shape {prm['d_s']} not in slice")
        self.name = name
        self.a = qint(prm["a"])          # rate-domain params in Q10.21
        self.d = qint(prm["d"])
        self.s = qint_phase(prm["s"])    # sustain is a level: Q2.29
        self.r = qint(prm["r"])
        self.a_s = int(prm["a_s"])
        self.r_s = int(prm["r_s"])
        self.A_MIN = qint(-8.0)
        self.phase = 0
        self.output = 0
        self.idlecount = 0
        self.state = self.S_ATTACK
        self.scalestage = ONE

    def attack_from(self, start):
        """attackFrom(start); only start==0 exercised in this slice."""
        assert start == 0, "attackFrom(start>0) not in slice"
        self.phase = 0
        self.output = 0
        self.idlecount = 0
        self.scalestage = ONE
        self.state = self.S_ATTACK
        if (self.a - self.A_MIN) < qint(0.01):
            self.state = self.S_DECAY
            self.output = ONE
            self.phase = 1 << F_PHASE

    def release(self):
        self.scalestage = self.output
        self.phase = 1 << F_PHASE
        self.state = self.S_RELEASE

    def process_block(self):
        if self.state == self.S_ATTACK:
            self.phase += envelope_rate_linear_nowrap(self.a)
            if self.phase >= (1 << F_PHASE):
                self.phase = 1 << F_PHASE
                self.state = self.S_DECAY
                self.s_lvl = self.s
            ph = self.phase >> (F_PHASE - FQ)
            if self.a_s == 1:                       # linear (Attacky uses this;
                self.output = ph                    # instant attack skips it)
            else:
                raise RuntimeError(f"{self.name}: attack shape {self.a_s} not in slice")
        elif self.state == self.S_DECAY:
            rate = envelope_rate_linear_nowrap(self.d)
            l_lo = self.phase - rate
            l_hi = self.phase + rate
            self.phase = limit_i(self.s, l_lo, l_hi)
            self.output = self.phase >> (F_PHASE - FQ)
        elif self.state == self.S_RELEASE:
            self.phase -= envelope_rate_linear_nowrap(self.r)
            out = self.phase >> (F_PHASE - FQ)
            for _ in range(self.r_s):
                out = qmul(out, self.phase >> (F_PHASE - FQ))
            self.output = qmul(out, self.scalestage)
            if self.phase < 0:
                self.state = self.S_IDLE
                self.output = 0
        elif self.state == self.S_IDLE:
            self.idlecount += 1
        self.output = limit_i(self.output, 0, ONE)

    def is_idle(self):
        return self.state == self.S_IDLE and self.idlecount > 0


class Modwheel:
    """ControllerModulationSourceVector (NDX=1), FAST_LINE smoothing."""

    def __init__(self):
        self.target = 0
        self.value = 0
        self.startingpoint = 0
        self.inv = qint(1.0 / (50.0 * (48000.0 / 44100.0)))

    def set_target(self, cc):
        self.target = qint(cc / 127.0)
        self.startingpoint = self.value

    def process_block(self):
        da = qmul(self.target - self.startingpoint, self.inv)
        b = self.target - self.value
        if abs(b) < abs(da):
            self.value = self.target
        else:
            self.value += da


# --------------------------------------------------------- coefficient maker
COEF_SMOOTH = qint(0.2)
N_COEF = 8


class CoefMaker:
    """FilterCoefficientMaker for fut_lp12 / st_Driven (CoupledForm biquad)."""

    def __init__(self):
        self.C = [0] * N_COEF
        self.dC = [0] * N_COEF
        self.tC = [0] * N_COEF
        self.first_run = True

    def make_coeffs(self, freq, reso):
        """Coeff_LP12(freq, reso, st_Driven); freq semitones relative A440."""
        gain = qint(1.0) - (qmul(qmul(reso, reso), qint(0.5)))   # resoscale(Driven)
        freq = limit_i(freq, qint(-55.0), qint(75.0))            # boundFreq
        sinu, cosi = note_to_omega(freq)
        # Map2PoleResonance(st_Driven): reso *= max(0, 1 - max(0, (f-58)*0.05))
        atten = ONE - qmul(max(0, freq - qint(58.0)), qint(0.05))
        reso = qmul(reso, max(0, atten))
        t = ONE - qmul(ONE - reso, ONE - reso)                    # 1-(1-reso)^2
        t = limit_i(t, qint(0.001), ONE)
        q2inv = qint(1.0) - qmul(qint(1.05), t)
        alpha = qmul(sinu, q2inv)
        lim = qint(math.sqrt(max(0.0, 1.0 - (cosi / float(ONE)) ** 2)) - 0.0001)
        alpha = min(alpha, lim)
        a0 = ONE + alpha
        a0inv = qdiv(ONE, a0)
        a1 = qmul(qint(-2.0), cosi)
        a2 = ONE - alpha
        b0h = (ONE - cosi) >> 1                                   # (1-cosi)*0.5 exact
        b0 = qmul(b0h, gain)
        b1 = qmul(ONE - cosi, gain)
        b2 = b0
        cs = qdiv(db_to_linear(qmul(freq, qint(0.55))), qint(64.0))   # clipscale
        self._to_coupled_form(a0inv, a1, a2, b0, b1, b2, cs)

    def _to_coupled_form(self, a0inv, a1, a2, b0, b1, b2, g):
        b0 = qmul(b0, a0inv)
        b1 = qmul(b1, a0inv)
        b2 = qmul(b2, a0inv)
        a1 = qmul(a1, a0inv)
        a2 = qmul(a2, a0inv)
        ar = -(a1 >> 1)                                            # 0.5*-a1 (even)
        sq = min(0, a1 * a1 - ((4 * a2) << FQ))                    # Q(2*FQ) domain
        ai = qint(0.5 * math.sqrt(-sq / float(1 << (2 * FQ))))     # 0.5*sqrt(-sq)
        ai = max(ai, qint(8.0 * 1.192092896e-07))
        bb1 = b1 - qmul(a1, b0)
        bb2 = b2 - qmul(a2, b0)
        n = [0] * N_COEF
        n[0] = ar
        n[1] = ai
        n[2] = ONE
        n[4] = bb1
        n[5] = qdiv(qmul(bb1, ar) + bb2, ai)
        n[6] = b0
        n[7] = g
        self._from_direct(n)

    def _from_direct(self, n):
        if self.first_run:
            self.dC = [0] * N_COEF
            self.C = list(n)
            self.tC = list(n)
            self.first_run = False
        else:
            for i in range(N_COEF):
                self.tC[i] = self.tC[i] + qmul(COEF_SMOOTH, n[i] - self.tC[i])
                self.dC[i] = qdiv(self.tC[i] - self.C[i], BLOCK_SIZE_OS, fb=0)


# ------------------------------------------------------------- halfband D2
class HalfbandD2:
    """HalfRateFilter(M=6, steep)::process_block_D2, scalar per channel.

    The SIMD lane structure of the engine resolves, per channel, to two
    independent 6-stage allpass cascades: lane 0/2 carry coefficient set A,
    lane 1/3 carry coefficient set B (`set_coefficients`:
    `va[i] = set_ps(cB[i], cA[i], cB[i], cA[i])`, and `_mm_set_ps(e3,e2,e1,e0)`
    puts its LAST argument in lane 0, so lane0 = cA). Per stage and sample
    the engine's shift sequence evaluates
        y[n] = x[n-2] + a*(x[n] - y[n-2])
    with states (x[n], x[n-1], x[n-2]) / (y[n], y[n-1], y[n-2]), and the
    reconstruction stage computes, for output index n,
        out[n] = (B[2n] + A[2n+1]) * 0.5   (n = 0..31)
    (`tL0 = broadcast(o[k][1])` = the B lane at the even sample, added to
    `o[k+1][0]` = the A lane at the odd sample; this matches the original
    `output = (filter_a.process(input) + oldout) * 0.5` comment the pinned
    header preserves above that code, and the SXT-028e sibling
    `model/effects/type-distortion/distortion_model.py::HalfbandD2`).
    (The engine test suite notes the decimator passes the passband at
    half amplitude; the voice path compensates via its amp *0.5.)

    NOTE (#123): the pinned header's own PROSE comment above the
    reconstruction loop asserts the opposite, `L[i] = A_L[2i] + B_L[2i+1]`,
    and its author flags the confusion in-line ("which looks a lot to me
    like I have a bit flip somewhere wrong in my comments"). The CODE is
    authoritative; `tools/halfband_d2_ordering_probe.py` settles it by
    executing the pinned kernel (evidence:
    `reports/halfband-branch-order/`). The A-even ordering this
    class carried before #123 destroys the decimator's stopband rejection
    (-0.4 dB instead of -110 dB at 0.30 of the input rate).
    """

    def __init__(self):
        self.bx = [[0, 0, 0] for _ in range(6)]
        self.by = [[0, 0, 0] for _ in range(6)]
        self.ax = [[0, 0, 0] for _ in range(6)]
        self.ay = [[0, 0, 0] for _ in range(6)]

    def process(self, inp):
        chain_b, chain_a = [], []
        for x_in in inp:
            xb, xa = x_in, x_in
            for j in range(6):
                # engine shift: tx2<-tx1; tx1<-tx0; tx0<-x; ty2<-ty1; ty1<-ty0
                # then y = tx2 + a*(tx0 - ty2): y[n] = x[n-2] + a*(x[n]-y[n-2])
                y = self.bx[j][1] + qmul(HALFBAND_B_Q[j], xb - self.by[j][1])
                self.bx[j] = [xb, self.bx[j][0], self.bx[j][1]]
                self.by[j] = [y, self.by[j][0], self.by[j][1]]
                xb = y
                y = self.ax[j][1] + qmul(HALFBAND_A_Q[j], xa - self.ay[j][1])
                self.ax[j] = [xa, self.ax[j][0], self.ax[j][1]]
                self.ay[j] = [y, self.ay[j][0], self.ay[j][1]]
                xa = y
            chain_b.append(xb)
            chain_a.append(xa)
        # B branch at the EVEN sample, A branch at the ODD sample (#123).
        return [qround(chain_b[2 * n] + chain_a[2 * n + 1], 1) for n in range(len(inp) // 2)]


# -------------------------------------------------------------- voice model
def limit_f(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


class Voice:
    """One SurgeVoice-equivalent instance (Attacky slice, mono bus)."""

    def __init__(self, inp, key, velocity):
        self.inp = inp
        self.key = key
        self.gate = True
        self.keep_playing = True

        self.aeg = Adsr(inp.adsr, "aeg")
        self.feg = Adsr(inp.fadsr, "feg")
        self.aeg.attack_from(0)
        self.feg.attack_from(0)
        self._calc_ctrldata()

        # SetQFB(0,0) ramp anchors
        self.fbp_gain = self._gain_target()
        self.fbp_outl = self._ampl_target()
        self.prev_gain = self.fbp_gain
        self.prev_outl = self.fbp_outl

        self._osc_init()

        self.cmu = CoefMaker()
        self.f_r0 = 0
        self.f_r1 = 0
        self.f_clip = ONE
        self._sync_uni_mirror()

    def _sync_uni_mirror(self):
        """Scalar mirrors of unison-voice 0 (trace/back-compat fields; the
        per-voice dicts in self.u are the state of record)."""
        u0 = self.u[0]
        self.oscstate = u0["oscstate"]
        self.osc_state = u0["state"]
        self.last_level = u0["last_level"]
        self.pwidth = u0["pwidth"]
        self.pwidth2 = u0["pwidth2"]
        self.dc_uni = u0["dc_uni"]

    # ----------------------------------------------------------- control ---
    def _gain_target(self):
        g = db_to_linear(qint(self.inp.vca_db))
        return qmul(g, self.aeg.output)          # vs == 0: velocity term absent

    def _ampl_target(self):
        vol = amp_to_linear(qint(self.inp.scene_volume))
        return vol >> 1                          # *0.5 exact; megapan(0) = 1

    def _calc_ctrldata(self):
        self.aeg.process_block()
        self.feg.process_block()
        cutoff = qint(self.inp.cutoff) + qmul(qint(self.inp.mod_cutoff_depth),
                                              self.inp.modwheel.value)
        reso = qint(self.inp.reso) + qmul(qint(self.inp.mod_reso_depth),
                                          self.inp.modwheel.value)
        self.cutoff_a = cutoff + qmul(qint(self.inp.envmod), self.feg.output)
        self.reso_a = reso
        if self.aeg.is_idle():
            self.keep_playing = False

    # --------------------------------------------------------------- osc ---
    def _osc_init(self):
        inp = self.inp
        # --- unison stack (SXT-034) ---------------------------------------
        # n_unison from the normalized osc state (override-readback-verified
        # for the uni>1 fixtures). Engine: n_unison = limit(p[uni], 1,
        # MAX_UNISON) (ClassicOscillator.cpp init) -- the engine silently
        # clamps (SXT-015 flagged 58 corpus presets); this product contract
        # REJECTS beyond-cap unison at load (never a silent clamp).
        n = int(inp.n_unison)
        if n < 1 or n > MAX_UNISON:
            raise RuntimeError(
                "unison %d outside 1..MAX_UNISON(%d): explicitly rejected "
                "(no clamp)" % (n, MAX_UNISON))
        self.uni_n = n
        # prepare_unison -> UnisonSetup (OscillatorDriftUnisonCharacter.h):
        #   attenuation = 1/sqrt(n); detuneBias = 1 (n==1) else 2/(n-1);
        #   detuneOffset = 0 (n==1) else -1
        self.out_attenuation = qint(1.0 / math.sqrt(n))
        self.detune_bias = qint(1.0 if n == 1 else 2.0 / (n - 1))
        self.detune_offset = 0 if n == 1 else -ONE
        # per-voice detune (semitones, Q10.21): spread_ext * (bias*v + offset)
        # with spread_ext = qint(12*f) (ct_oscspread); voice pan spread is
        # inert on this slice's mono bus (osc stereo flag = is_wide =
        # (fbc == fc_wide), SurgeVoice.cpp:1044; fbc = Serial 1 here).
        spread_ext_q = qint(12.0 * inp.spread)

        self.pitch = min(148, self.key + 12 * inp.octave)
        self.osc_state = 0
        self.oscstate = 0
        self.last_level = 0
        self.dc_uni = 0
        self.dc = 0
        self.osc_out = 0
        self.osc_out2 = 0
        self.bufpos = 0
        self.pwidth = 0
        self.pwidth2 = 0
        self.ob = [0] * (OB_LENGTH + FIRIPOL_N)     # shared impulse buffer
        self.dcb = [0] * (OB_LENGTH + FIRIPOL_N)    # shared DC buffer
        # lag targets (constant params); instantize v = target (update_lagvals<true>)
        self.t_shape = limit_i(qint(inp.shape), qint(-1.0), qint(1.0))
        self.t_pw = limit_i(qint(inp.pw1), qint(0.001), qint(0.999))
        self.t_pw2 = limit_i(qint(inp.pw2), qint(0.001), qint(0.999))
        self.t_sub = limit_i(qint(inp.submix), 0, ONE)
        self.t_sync = qint(max(0.0, inp.sync))
        self.l_shape = self.t_shape
        self.l_pw = self.t_pw
        self.l_pw2 = self.t_pw2
        self.l_sub = self.t_sub
        self.l_sync = self.t_sync
        # integrator hpf: (1 - 2*20/48000)^2, and per-block target
        self.integrator_hpf = qint((1.0 - 40.0 / 48000.0) ** 2)
        self.hpf_target = self._hpf_calc()
        self.hpf_prev = self.hpf_target           # instantize (first block constant)
        # character filter (Warm=0): filt = (1 - 2*5000/48000)^2
        filt = (1.0 - 2.0 * 5000.0 / 48000.0) ** 2
        if inp.character == 0:
            self.char_b0 = qint(1.0 - filt)
            self.char_b1 = 0
            self.char_a1 = qint(filt)
        elif inp.character == 1:
            self.char_b0, self.char_b1, self.char_a1 = ONE, 0, 0
        else:
            raise RuntimeError("character Bright not in slice")

        # per-unison-voice state (ClassicOscillator.cpp init loop):
        #   retrigger on -> oscstate[i] = syncstate[i] = 0; else
        #   oscstate[i] = syncstate[i] = 0.5*rand_01()*ntpi(detune_i) with
        #   detune_i = spread*(bias*i + offset) (the wall-clock-random draw
        #   is a declared input word here; the engine's own draws are not
        #   reproducible -- SXT-012 quantified-variation class).
        # The impulse buffers (ob/dcb) are SHARED by all unison voices
        # (single oscbuffer/dcbuffer in the engine); the impulse state
        # machines are per-voice.
        pw_init = limit_i(self.l_pw, qint(0.001), qint(0.999))
        self.u = []
        for v in range(n):
            detune = 0
            if n > 1:
                detune = qmul(spread_ext_q,
                              qmul(self.detune_bias, qint(float(v))) + self.detune_offset)
            t = ntpi_tuningctr(detune + self.l_sync)   # l_sync instantized 0
            t_inv = qdiv(ONE, t)
            if inp.retrigger:
                st = 0
            else:
                drand = inp.next_draw()
                st = qmul(drand, t) >> 1               # 0.5*drand*ntpi(detune)
            self.u.append({
                "oscstate": st, "syncstate": st, "state": 0,
                "last_level": 0, "pwidth": pw_init, "pwidth2": 0,
                "dc_uni": 0, "detune": detune, "t": t, "t_inv": t_inv,
            })
        # declared init-phase oscstate set consumed by THIS voice creation
        # (control-plane word group for the RTL; see run_model draw table)
        self.init_oscstate_set = [x["oscstate"] for x in self.u]
        self.draw_set_index = 0
        self._sync_uni_mirror()

    def _hpf_calc(self):
        pp = ntp_tuningctr(self.pitch_q())        # pitch + l_sync(=0)
        invt = qmul(qint(4.0), min(ONE, qmul(qint(MIDI_0_FREQ), qmul(pp, qint(1.0 / 96000.0)))))
        return min(self.integrator_hpf, qint(0.995 ** (invt / float(ONE))))

    def pitch_q(self):
        return qint(float(min(148, self.key + 12 * self.inp.octave)))

    def osc_process_block(self, block_index):
        inp = self.inp
        pitch = min(148, self.key + 12 * inp.octave)
        pmi_d = 96000.0 * (1.0 / MIDI_0_FREQ) * (2.0 ** (-pitch / 12.0))
        assert pitch >= 24, 'declared slice pitch range is [24, 148]'
        pmi_d = max(1.0, pmi_d)
        pmi = sat(int(math.floor(pmi_d * (1 << PMI_F) + 0.5)))   # Q13.18
        pitchmult = qdiv(1 << PMI_F, pmi, fa=PMI_F, fb=PMI_F)   # Q4.27

        # update_lagvals<false> then one lag step per block
        self.l_shape += qmul(qint(0.05), self.t_shape - self.l_shape)
        self.l_pw += qmul(qint(0.05), self.t_pw - self.l_pw)
        self.l_pw2 += qmul(qint(0.05), self.t_pw2 - self.l_pw2)
        self.l_sub += qmul(qint(0.05), self.t_sub - self.l_sub)
        self.l_sync += qmul(qint(0.05), self.t_sync - self.l_sync)
        hpf_new = self._hpf_calc()
        hpf_start = self.hpf_prev
        hpf_d = hpf_new - hpf_start
        self.hpf_prev = hpf_new

        a_cov = qmul(BLOCK_SIZE_OS << FQ, pitchmult)
        self.ctrl_pmi = pmi
        self.ctrl_pitchmult = pitchmult
        self.ctrl_a_cov = a_cov
        self.ctrl_hpf_target = hpf_new
        # ClassicOscillator.cpp process_block: voice-major fill loop -- each
        # unison voice fills its own phase space to a_cov into the SHARED
        # impulse buffer (impulse count scales with the stack; the buffer
        # does not).
        for v in range(self.uni_n):
            uv = self.u[v]
            while uv["oscstate"] < a_cov:
                self._convolute(v, pmi)
            uv["oscstate"] -= a_cov
        self._sync_uni_mirror()

        oa = qmul(self.out_attenuation, pitchmult)
        mdc = self.dc
        bp = self.bufpos
        out = []
        for k in range(BLOCK_SIZE_OS):
            hpf = hpf_start + qround(hpf_d * (k + 1), 6)
            acc = qmul(self.osc_out, hpf)
            mdc += self.dcb[bp + k]
            ob = self.ob[bp + k] - qmul(mdc, oa)
            last_osc_out = self.osc_out
            self.osc_out = sat(acc + ob)
            self.osc_out2 = (qmul(self.osc_out2, self.char_a1)
                             + qmul(self.osc_out, self.char_b0)
                             + qmul(last_osc_out, self.char_b1))
            out.append(self.osc_out2)
        self.dc = mdc
        for k in range(BLOCK_SIZE_OS):
            self.ob[bp + k] = 0
            self.dcb[bp + k] = 0
        self.bufpos = (bp + BLOCK_SIZE_OS) & (OB_LENGTH - 1)
        if self.bufpos == 0:
            for k in range(FIRIPOL_N):
                self.ob[k] = self.ob[OB_LENGTH + k]
                self.ob[OB_LENGTH + k] = 0
                self.dcb[k] = self.dcb[OB_LENGTH + k]
                self.dcb[OB_LENGTH + k] = 0
        return out

    def _convolute(self, v, pmi):
        uv = self.u[v]
        wf = self.l_shape
        sub = self.l_sub
        # (unsigned int)(2^24 * oscstate * pitchmult_inv): truncate like the engine
        ipos = (uv["oscstate"] * pmi) >> (FQ + PMI_F - 24)
        ipos &= 0xFFFFFFFF
        delay = (ipos >> 24) & 0x3F
        m = ((ipos >> 16) & 0xFF) * (FIRIPOL_N << 1)
        lipol = ipos & 0xFFFF

        # detune spread for this unison voice: t/t_inv are per-voice constants
        # (drift asserted 0; sync inert at 0). Engine convolute recomputes
        # t = ntpi_tuningctr(detune + sync) per call; the value is constant
        # in this slice (no detune/sync modulation routed), so it is
        # precomputed at init and declared in the control plane.
        t = uv["t"]
        t_inv = uv["t_inv"]

        st = uv["state"]
        one = ONE
        if st == 0:
            uv["pwidth"] = limit_i(self.l_pw, qint(0.001), qint(0.999))
            uv["pwidth2"] = qmul(qint(2.0), self.l_pw2)
        pw = uv["pwidth"]
        pw2 = uv["pwidth2"]
        om1 = one - sub                                      # (1-sub)
        if st == 0:
            # tg = ((1+wf)*0.5 + (1-pw)*(-wf))*(1-sub) + 0.5*sub*(2-pw2)
            tg = qmul(qround(one + wf, 1) + qmul(one - pw, -wf), om1)
            tg += qmul(qround(sub, 1), qint(2.0) - pw2)
            g = tg - uv["last_level"]
            uv["last_level"] = tg
            uv["last_level"] -= qmul(qmul(pw, pw2), qmul(one + wf, om1))
        elif st == 1:
            g = qmul(wf, om1) - sub
            uv["last_level"] += g
            uv["last_level"] -= qmul(qmul(one - pw, qint(2.0) - pw2), qmul(one + wf, om1))
        elif st == 2:
            g = om1
            uv["last_level"] += g
            uv["last_level"] -= qmul(qmul(pw, qint(2.0) - pw2), qmul(one + wf, om1))
        else:
            g = qmul(wf, om1) + sub
            uv["last_level"] += g
            uv["last_level"] -= qmul(qmul(one - pw, pw2), qmul(one + wf, om1))
        # g *= out_attenuation (UnisonSetup attenuation = 1/sqrt(n));
        # stereo pan inert on this slice's mono bus
        g = qmul(g, self.out_attenuation)

        base = self.bufpos + delay
        m12 = m >> 1                     # separate tables: phase*FIRIPOL_N + k
        for k in range(FIRIPOL_N):
            term = SINC_MAIN[m12 + k] + qmul(lipol, SINC_DERIV[m12 + k], fb=16)
            self.ob[base + k] = sat(self.ob[base + k] + qmul(term, g))

        olddc = uv["dc_uni"]
        uv["dc_uni"] = qmul(t_inv, qmul(one + wf, om1))
        self.dcb[base + FIROFFSET] = sat(self.dcb[base + FIROFFSET]
                                         + (uv["dc_uni"] - olddc))

        if st & 1:
            rate = qmul(t, one - pw)
        else:
            rate = qmul(t, pw)
        if (st + 1) & 2:
            rate = qmul(rate, qint(2.0) - pw2)
        else:
            rate = qmul(rate, pw2)
        uv["oscstate"] = max(0, uv["oscstate"] + rate)
        uv["state"] = (st + 1) & 3

    # --------------------------------------------------------- audio rate --
    def process_block(self, block_index, sceneout_l, sceneout_r, trace):
        """One 32-sample block: control pass, osc block, filter chain."""
        self._calc_ctrldata()
        osc_out = self.osc_process_block(block_index)
        self.cmu.make_coeffs(self.cutoff_a, self.reso_a)
        self.ctrl_C = list(self.cmu.C)          # block-start coefficients
        self.ctrl_dC = list(self.cmu.dC)
        self.last_oscout = list(osc_out)

        lvl = amp_to_linear(qint(self.inp.o1_level))     # mixer lipol line (const)
        gain_start = self.prev_gain
        outl_start = self.prev_outl
        # SetQFB for this block: new ramp targets from the stepped envelopes
        self.fbp_gain = self._gain_target()
        self.fbp_outl = self._ampl_target()
        d_gain = self.fbp_gain - gain_start
        d_outl = self.fbp_outl - outl_start

        c = self.cmu.C
        one = ONE
        for k in range(BLOCK_SIZE_OS):
            for i in range(N_COEF):
                c[i] = sat(c[i] + self.cmu.dC[i])
            x = qmul(osc_out[k], lvl)
            y = qmul(c[4], self.f_r0) + qmul(c[6], x) + qmul(c[5], self.f_r1)
            s1 = qmul(x, c[2]) + qmul(c[0], self.f_r0) - qmul(c[1], self.f_r1)
            s2 = qmul(c[1], self.f_r0) + qmul(c[0], self.f_r1)
            self.f_r0 = qmul(s1, self.f_clip)
            self.f_r1 = qmul(s2, self.f_clip)
            self.f_clip = max(qint(0.1), one - qmul(c[7], qmul(y, y)))
            outv = qmul(y, gain_start + qround(d_gain * (k + 1), 6))
            ol = outl_start + qround(d_outl * (k + 1), 6)
            sceneout_l[k] += qmul(outv, ol)
            sceneout_r[k] += qmul(outv, ol)
        self.prev_gain = self.fbp_gain
        self.prev_outl = self.fbp_outl

        if trace is not None:
            trace.checkpoint_voice(block_index, self)
        return self.keep_playing


# ---------------------------------------------------------------- scheduler
class Inputs:
    """Frozen model inputs (attacky_inputs.json + graphs.jsonl md routes)."""

    def __init__(self, inputs_path, graphs_path, preset_path):
        with open(inputs_path, encoding="utf-8") as f:
            d = json.load(f)
        n = d["not_in_graphs"]
        g = d["graph_echo"]
        self.scene_volume = n["scene_volume"]
        self.vca_db = n["vca_level"]
        self.master_db = n["master_volume"]
        self.o1_level = n["level_o1"]
        self.octave = int(n["osc1_octave"])
        self.character = int(n["character"])
        self.adsr = n["adsr"]
        self.fadsr = n["fadsr"]
        self.osc1 = g["osc1"]
        p = self.osc1["p"]
        self.shape, self.pw1, self.pw2, self.submix, self.sync = p[0], p[1], p[2], p[3], p[4]
        # unison stack inputs (SXT-034): normalized osc uni/spread/retrigger,
        # override-readback-verified for the uni>1 fixtures; declared
        # init-phase draws for the non-retrigger path (engine rand_01 is
        # wall-clock seeded and not reproducible -- SXT-012 class).
        self.n_unison = int(self.osc1.get("uni", 1))
        self.spread = float(self.osc1.get("udet", 0.0))
        self.retrigger = bool(self.osc1.get("rt", 1))
        draws = d.get("init_phase_draws",
                      d.get("unison_override", {}).get("init_phase_draws_declared", []))
        self._draws = [qint(float(x)) for x in draws]
        self._draw_i = 0
        self.cutoff = n["fu0"]["cutoff"]
        self.reso = n["fu0"]["resonance"]
        self.envmod = n["fu0"]["envmod"]
        self.mod_cutoff_depth = 0.0
        self.mod_reso_depth = 0.0
        found = False
        with open(graphs_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row.get("p") != preset_path:
                    continue
                for r in row["g"]["md"]["s"][0]["s"]:
                    if r[4] == "A Filter 1 Cutoff":
                        self.mod_cutoff_depth = r[5]
                    elif r[4] == "A Filter 1 Resonance":
                        self.mod_reso_depth = r[5]
                found = True
                break
        if not found:
            raise RuntimeError("preset not found in graphs.jsonl")
        self.modwheel = Modwheel()

    def next_draw(self):
        """Consume one declared init-phase draw (voice-creation order,
        unison-voice order within a voice). Fail-closed: a fixture that needs
        more draws than declared refuses rather than guessing."""
        if self._draw_i >= len(self._draws):
            raise RuntimeError(
                "init_phase_draws exhausted: non-retrigger voice creation "
                "needs a declared draw per unison voice")
        v = self._draws[self._draw_i]
        self._draw_i += 1
        return v

    def reset_draws(self):
        """Restart the declared draw list (runner probe discard)."""
        self._draw_i = 0


def load_sequence(path):
    with open(path, encoding="utf-8") as f:
        seq = json.load(f)
    assert seq["schema_version"] == 1
    return seq


def write_wav16(path, samples, sample_rate):
    frames = bytearray()
    for s in samples:
        frames += struct.pack("<h", s)
    import wave

    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))


# ===========================================================================
# SXT-026a extension (issue #48): generalized voice class, frozen below.
# v1 behavior above is untouched; class-v1 fixtures render bit-identically.
# ===========================================================================

FQ28 = 28                                   # Sine phase/omega: Q3.28 radians
PI_Q28 = 843314856                          # round(pi * 2^28)
TWO_PI_Q28 = 1686629713                     # round(2*pi * 2^28)
OSC_OVERSAMPLING = 2                        # globals.h OSC_OVERSAMPLING

SINE_SHAPE_MAX = 0                          # frozen class: shape mode 0 only
VELOCITY_SRC = 1                            # ms_velocity
KEYTRACK_SRC = 2                            # ms_keytrack
MODWHEEL_SRC = 6                            # ms_modwheel
DEST_VCA_GAIN = 298                         # scene param ids (md rows)
DEST_FU1_CUTOFF = 308
DEST_FU1_RESO = 309
DEST_FU1_FEGMOD = 310
DEST_FU2_CUTOFF = 314
DEST_FU2_RESO = 315
DEST_FU2_FEGMOD = 318
DEST_FM_DEPTH = 260
VOICE_ROUTE_VOCAB = {
    VELOCITY_SRC: {DEST_VCA_GAIN, DEST_FU1_CUTOFF, DEST_FU1_RESO,
                   DEST_FU1_FEGMOD, DEST_FU2_CUTOFF, DEST_FU2_RESO,
                   DEST_FU2_FEGMOD},
    KEYTRACK_SRC: {DEST_FU1_CUTOFF, DEST_FU1_RESO, DEST_FU1_FEGMOD,
                   DEST_FU2_CUTOFF, DEST_FU2_RESO, DEST_FU2_FEGMOD},
}
SCENE_ROUTE_VOCAB = {
    MODWHEEL_SRC: {DEST_FU1_CUTOFF, DEST_FU1_RESO, DEST_FM_DEPTH,
                   DEST_VCA_GAIN},      # SXT-035: VCA Gain destination class
}

# ---------------------------------------------------------------------------
# SXT-042 (issue #76): the keytrack modsource (ms_keytrack, pinned id 2),
# frozen as its own leaf on top of the #48 plumbing.  No arithmetic changes:
# the word below is the expression #48 already computed inline, given a name,
# a declared destination class and a declared refresh point so the RTL slice
# (rtl/voice/tb_kt.sv) can be held to it exactly.
#
# Pinned citations (read, never copied): src/common/ModulationSource.h
# (`modsources` enum, ms_keytrack = 2), src/common/dsp/SurgeVoice.cpp
# (`ctrl.keytrack`/`state.pitch` setup in the voice ctor, the
# `applyModulationToLocalcopy` pass, and the modsource refresh at the END of
# the per-voice control pass).
# ---------------------------------------------------------------------------
KEYTRACK_SEMITONES_PER_UNIT = 12        # engine divisor: one unit == one octave
KEYTRACK_DEST_LIVE = (DEST_FU1_CUTOFF, DEST_FU1_RESO, DEST_FU1_FEGMOD)
KEYTRACK_DEST_INERT = (DEST_FU2_CUTOFF, DEST_FU2_RESO, DEST_FU2_FEGMOD)
KEYTRACK_SUM_ORDER = ("cutoff_sum", "reso_sum", "fegmod_sum")


def keytrack_word(pitch_voice, keytrack_root):
    """ms_keytrack output word, Q10.21 (SXT-042 frozen).

    `(state.pitch - keytrack_root) / 12`, quantized round-half-up ONCE at
    quantization time (the divisor is exact in the engine's double domain;
    `pitch_voice` and `keytrack_root` are integers in this class, so the
    quotient's fractional part is always 0, 1/3 or 2/3 and never a rounding
    tie -- see README "SXT-042 keytrack modsource" for the integer-exact
    RTL equivalent).
    """
    return qint((pitch_voice - keytrack_root)
                / float(KEYTRACK_SEMITONES_PER_UNIT))


class Refuse(Exception):
    """Fail-closed applicability refusal (exit 2 at the runner boundary)."""


def qint28(x):
    """Quantize a double to Q3.28 radians, round-half-up (quantization time)."""
    return sat(int(math.floor(x * (1 << FQ28) + 0.5)))


def clamp_to_pi(p):
    """sst FastMath.h clampToPiRange on the Q3.28 phase word (integer-exact).

    Engine: y = x + pi; p = y - 2pi*(int)(y/(2pi)); if p<0 p += 2pi;
    return p - pi.  For y >= 0 the (int) cast is floor; for y < 0 the
    engine's p<0 fixup makes it floor again, so one floor division is
    equivalent for every input.
    """
    y = p + PI_Q28
    k = y // TWO_PI_Q28
    return y - TWO_PI_Q28 * k - PI_Q28


def _ratio_q_scaled(num, den, fnum, fden, fq=FQ):
    """Round-half-up (num/2^fnum)/(den/2^fden) into Qfq (den > 0), saturated."""
    assert den > 0
    sh = fden - fnum + fq
    n = num << sh if sh >= 0 else num >> (-sh)
    half = den >> 1
    if n >= 0:
        return sat((n + half) // den)
    return sat(-((-n + half) // den))


def _pade_sin_parts(x_q28):
    """Numerator/denominator ints of the pinned fastsin rational.

    sst FastMath.h (JUCE Pade, valid -pi..pi):
        num = -x * (-11511339840 + x^2*(1640635920 + x^2*(-52785432
              + x^2*479249)))
        den = 11511339840 + x^2*(277920720 + x^2*(3177720 + x^2*18361))
    Exact integer evaluation; x at 2^28 -> num at 2^196, den at 2^168.
    """
    x = x_q28
    x2 = x * x                                 # 2^56
    g = 479249 * x2                            # (C3*x^2)  << 56
    g = g - (52785432 << 56)                   # t2 << 56
    g = x2 * g + (1640635920 << 112)           # t1 << 112
    g = x2 * g - (11511339840 << 168)          # t0 << 168
    num = -x * g                               # 2^196
    h = 18361 * x2
    h = h + (3177720 << 56)
    h = x2 * h + (277920720 << 112)
    h = x2 * h + (11511339840 << 168)          # 2^168
    return num, h


def _pade_cos_parts(x_q28):
    """Numerator/denominator ints of the pinned fastcos rational (2^168)."""
    x = x_q28
    x2 = x * x
    g = 14615 * x2
    g = g - (1075032 << 56)
    g = x2 * g + (18471600 << 112)
    g = x2 * g - (39251520 << 168)
    num = -g                                   # 2^168
    h = 127 * x2
    h = h + (16632 << 56)
    h = x2 * h + (1154160 << 112)
    h = x2 * h + (39251520 << 168)
    return num, h


def fastsin_ratio(x_q28):
    """fastsin(x) -> Q10.21 (exact rational, ONE final round-half-up)."""
    num, den = _pade_sin_parts(x_q28)
    return _ratio_q_scaled(num, den, 196, 168)


def fastcos_ratio(x_q28):
    """fastcos(x) -> Q10.21 (exact rational, ONE final round-half-up)."""
    num, den = _pade_cos_parts(x_q28)
    return _ratio_q_scaled(num, den, 168, 168)


def pitch_to_omega_q(pitch, samplerate=SR * OSC_OVERSAMPLING):
    """OscillatorBase.h pitch_to_omega -> Q3.28 word.

    omega = 2*pi*MIDI_0_FREQ*note_to_pitch(pitch)/samplerate; note_to_pitch
    from the pinned construction formula (declared deviation: the engine
    lerps a float32 table), quantized once.
    """
    freq = MIDI_0_FREQ * (2.0 ** (pitch / 12.0))
    return qint28(2.0 * math.pi * freq / samplerate)


def _calc_omega_q(scfreq, Q=0.707):
    """sst-filters BiquadFilter calc_omega(scfreq)/OSC_OVERSAMPLING (double)."""
    omega = 2.0 * math.pi * 440.0 * _dbl_pitch(256.0 + 12.0 * scfreq) / SR
    return omega / OSC_OVERSAMPLING


def biquad_hp_coeffs(scfreq, Q=0.707):
    """coeff_HP(calc_omega(scfreq)/OSC_OVERSAMPLING, Q) -> Q10.21 words."""
    omega = _calc_omega_q(scfreq)
    if omega > math.pi:
        return (qint(1.0), 0, 0, 0, 0)
    cosi = math.cos(omega)
    sinu = math.sin(omega)
    alpha = sinu / (2.0 * Q)
    a0 = 1.0 + alpha
    return (qint(((1.0 + cosi) * 0.5) / a0), qint((-(1.0 + cosi)) / a0),
            qint(((1.0 + cosi) * 0.5) / a0), qint((-2.0 * cosi) / a0),
            qint((1.0 - alpha) / a0))


def biquad_lp2b_coeffs(scfreq, Q=0.707):
    """coeff_LP2B(calc_omega(scfreq)/OSC_OVERSAMPLING, Q) -> Q10.21 words."""
    omega = _calc_omega_q(scfreq)
    if omega > math.pi:
        return (qint(1.0), 0, 0, 0, 0)
    w_sq = omega * omega
    den = (w_sq * w_sq) + (math.pi ** 4) + w_sq * (math.pi ** 2) * (1.0 / Q - 2.0)
    G1 = min(1.0, math.sqrt((w_sq * w_sq) / den) * 0.5)
    cosi = math.cos(omega)
    sinu = math.sin(omega)
    alpha = sinu / (2.0 * Q)
    A = 2.0 * math.sqrt(G1) * math.sqrt(2.0 - G1)
    a0 = 1.0 + alpha
    return (qint(((1.0 - cosi + G1 * (1.0 + cosi) + A * sinu) * 0.5) / a0),
            qint((1.0 - cosi - G1 * (1.0 + cosi)) / a0),
            qint(((1.0 - cosi + G1 * (1.0 + cosi) - A * sinu) * 0.5) / a0),
            qint((-2.0 * cosi) / a0),
            qint((1.0 - alpha) / a0))


class TDFBiquad:
    """sst-filters BiquadFilter TDF2 (engine: double eval; model: Q10.21/qmul)."""

    def __init__(self, coeffs):
        self.b0, self.b1, self.b2, self.a1, self.a2 = coeffs
        self.reg0 = 0
        self.reg1 = 0

    def process_block(self, data):
        for k in range(len(data)):
            x = data[k]
            op = sat(qmul(self.b0, x) + self.reg0)
            self.reg0 = sat(qmul(self.b1, x) - qmul(self.a1, op) + self.reg1)
            self.reg1 = sat(qmul(self.b2, x) - qmul(self.a2, op))
            data[k] = op


class SineCore:
    """SineOscillator (legacy path, FMmode 0), unison 1, retrigger, mono.

    Non-FM blocks: SurgeQuadrOsc recurrence (set_rate per block: dr=cos, di=sin,
    normalize (r,i); 4 products per sample).  FM blocks: Q3.28 phase
    accumulator with the pinned clampToPiRange wrap and fastsin/fastcos
    (mode 0 value = the sin component).  applyFilter = lowcut TDF biquad,
    then highcut TDF biquad, then the shared CharacterFilter.
    """

    def __init__(self, char_coeffs, lowcut, highcut, character):
        self.hp = TDFBiquad(biquad_hp_coeffs(lowcut / 12.0))
        self.lp = TDFBiquad(biquad_lp2b_coeffs(highcut / 12.0))
        self.char_a1, self.char_b0, self.char_b1 = char_coeffs
        self.r = 0                                  # SurgeQuadrOsc ctor state
        self.i = -ONE
        self.dr = 0
        self.di = 0
        self.phase = 0                              # Q3.28 (retrigger: 0)

    def set_rate(self, omega_q28):
        """set_rate(w): dr=cos w, di=sin w; normalize (r,i).

        Engine computes cos/sin in double, narrows to float32; the model
        quantizes to Q10.21 once (declared deviation, same error class).
        """
        w = omega_q28 / float(1 << FQ28)
        self.dr = qint(math.cos(w))
        self.di = qint(math.sin(w))
        rd = self.r / float(ONE)
        idd = self.i / float(ONE)
        n = 1.0 / math.sqrt(rd * rd + idd * idd)
        self.r = qint(rd * n)
        self.i = qint(idd * n)

    def quad_step(self):
        lr, li = self.r, self.i
        self.r = sat(qmul(self.dr, lr) - qmul(self.di, li))
        self.i = sat(qmul(self.dr, li) + qmul(self.di, lr))

    def block(self, omega_q28, fm_depth, master):
        """One 64-OS-sample block; master = FM source block (None: no FM)."""
        out = []
        if master is None:
            self.set_rate(omega_q28)
            for _ in range(BLOCK_SIZE_OS):
                self.quad_step()
                out.append(self.r)
        else:
            for _ in range(BLOCK_SIZE_OS):
                fm = qmul(fm_depth, master[_])
                self.phase = clamp_to_pi(self.phase + omega_q28
                                         + (fm << (FQ28 - FQ)))
                out.append(fastsin_ratio(self.phase))
        self.hp.process_block(out)                  # applyFilter: lowcut,
        self.lp.process_block(out)                  # then highcut
        o1 = 0                                      # CharacterFilter (shared)
        o2 = 0
        for k in range(BLOCK_SIZE_OS):
            last = o1
            o1 = sat(qmul(o2, self.char_a1) + qmul(out[k], self.char_b0)
                     + qmul(last, self.char_b1))
            o2 = o1
            out[k] = o1
        return out


class CoefMakerLP24(CoefMaker):
    """FilterCoefficientMaker for fut_lp24 / st_Driven (IIR24CFC).

    Same resoscale/boundFreq/clipscale/ToCoupledForm/FromDirect as the 2-pole
    maker; the resonance map is Map4PoleResonance (clamps RESO, not t).
    """

    def make_coeffs(self, freq, reso):
        gain = qint(1.0) - (qmul(qmul(reso, reso), qint(0.5)))   # resoscale(Driven)
        freq = limit_i(freq, qint(-55.0), qint(75.0))            # boundFreq
        sinu, cosi = note_to_omega(freq)
        atten = ONE - qmul(max(0, freq - qint(58.0)), qint(0.05))
        reso = qmul(reso, max(0, atten))
        reso = limit_i(reso, qint(0.001), ONE)                   # clamp(reso)
        q2inv = qint(1.0) - qmul(qint(1.05), reso)
        alpha = qmul(sinu, q2inv)
        lim = qint(math.sqrt(max(0.0, 1.0 - (cosi / float(ONE)) ** 2)) - 0.0001)
        alpha = min(alpha, lim)
        a0 = ONE + alpha
        a0inv = qdiv(ONE, a0)
        a1 = qmul(qint(-2.0), cosi)
        a2 = ONE - alpha
        b0h = (ONE - cosi) >> 1
        b0 = qmul(b0h, gain)
        b1 = qmul(ONE - cosi, gain)
        b2 = b0
        cs = qdiv(db_to_linear(qmul(freq, qint(0.55))), qint(64.0))   # clipscale
        self._to_coupled_form(a0inv, a1, a2, b0, b1, b2, cs)


class VoiceV2(Voice):
    """Generalized voice (SXT-026a): Classic-or-Sine osc, LP12/LP24 Driven.

    v1 exactness: with kind='classic', fu_poles=12, mix1=ONE and no v2 routes,
    every frozen v1 operation is unchanged (mix1 blend degenerates to
    qmul(y, ONE) + 0).  `inp` must be an InputsV2.
    """

    def __init__(self, inp, key, velocity):
        self.kind = inp.osc_kind                 # 'classic' | 'sine'
        self.fu_poles = inp.fu_poles             # 12 | 24
        self.pitch_voice = key + 12 * inp.scene_octave
        # modulator words (engine: fvel = vel/127 constant; keytrack set at
        # ctor, refreshed after each control pass -- the declared 1-pass lag)
        self.fvel = qint(velocity / 127.0)
        # SXT-042 correction (finding F-042-1): the engine initialises the
        # keytrack modsource to ZERO in the voice constructor
        # (SurgeVoice.cpp: `keytrackSource.set_output(0, 0.f);`, before the
        # ctor's applyModulationToLocalcopy<true>() and calc_ctrldata<true>()),
        # and only installs (state.pitch - keytrack_root)/12 at the END of a
        # control pass.  The voice's FIRST control pass therefore applies
        # keytrack = 0 -- unlike velocity, which the ctor initialises to
        # state.fvel.  #48 documented the 1-control-pass lag but seeded the
        # word with the pitch-derived value, which made the first block of
        # every voice carry a keytrack term the engine does not apply.
        self.kt_word = 0
        # SXT-042 checkpoint words: per-destination sum of this voice's
        # keytrack route terms for the current control pass (cutoff, reso,
        # feg-mod), in KEYTRACK_SUM_ORDER.  Observation only -- recording
        # them changes no arithmetic.
        self.kt_route_sums = [0, 0, 0]
        super().__init__(inp, key, velocity)
        self.f4_r0 = 0
        self.f4_r1 = 0
        if self.fu_poles == 24:
            self.cmu = CoefMakerLP24()
        self.fm_depth = inp.fm_depth
        if self.kind == "sine":
            self._sine_init()

    def _sine_init(self):
        inp = self.inp
        self.sine_omega = []
        self.sine = []
        for i in range(3):
            p = self.pitch_voice + inp.osc_pitch_offsets[i]
            if not (24 <= p <= 148):
                raise Refuse(f"osc{i + 1} pitch {p} outside declared [24,148]")
            self.sine_omega.append(pitch_to_omega_q(p))
            self.sine.append(SineCore(
                (self.char_a1, self.char_b0, self.char_b1),
                inp.sine_lowcut, inp.sine_highcut, inp.character))
        self.osc_state = 0
        self.oscstate = 0

    def pitch_q(self):
        if self.kind == "sine":
            return qint(float(self.pitch_voice))
        return super().pitch_q()

    # ------------------------------------------------------------ control
    def _apply_voice_routes(self):
        """applyModulationToLocalcopy for the frozen route vocabulary."""
        inp = self.inp
        cut = qint(inp.cutoff)
        reso = qint(inp.reso)
        emod = qint(inp.envmod)
        vg = qint(inp.vca_db)
        kt_sums = [0, 0, 0]              # SXT-042 checkpoint words only
        for src, dst, depth in inp.voice_routes:
            val = self.fvel if src == VELOCITY_SRC else self.keytrack_value()
            d = qint(depth)
            term = qmul(d, val)
            if dst == DEST_FU1_CUTOFF:
                cut = sat(cut + term)
                if src == KEYTRACK_SRC:
                    kt_sums[0] += term
            elif dst == DEST_FU1_RESO:
                reso = sat(reso + term)
                if src == KEYTRACK_SRC:
                    kt_sums[1] += term
            elif dst == DEST_FU1_FEGMOD:
                emod = sat(emod + term)
                if src == KEYTRACK_SRC:
                    kt_sums[2] += term
            elif dst == DEST_VCA_GAIN:
                vg = sat(vg + term)
            elif dst in KEYTRACK_DEST_INERT:
                pass       # unit-2 destinations: inert (unit off) per the gate
            else:
                # SXT-042: the route pass is fail-closed in its own right, not
                # only at parse time -- an unrecognized destination must never
                # be silently dropped here.
                raise Refuse(
                    f"voice route {src}->{dst} reached the route pass outside "
                    "the declared destination class {298, 308, 309, 310} "
                    "(+ inert unit-2 {314, 315, 318})")
        self.mod_cutoff = cut
        self.mod_reso = reso
        self.mod_envmod = emod
        self.mod_vca_db = vg
        self.kt_route_sums = kt_sums
        # keytrack modsource refresh AFTER route application (declared lag;
        # pitch is constant per voice, so the value equals the ctor value)
        self.kt_word = keytrack_word(self.pitch_voice, inp.keytrack_root)

    def keytrack_value(self):
        """The ms_keytrack word read by this control pass (SXT-042).

        Split out from the route loop so the negative controls can mutate
        the SOURCE without touching the route application, and so the RTL
        slice has a named quantity to match.  Per-instance by construction:
        every voice owns its own word.
        """
        return self.kt_word

    def _calc_ctrldata(self):
        if self.kind == "classic":
            inp = self.inp
            table = getattr(self.inp, "scene_routes_mw", None)
            if not table and not getattr(inp, "voice_routes", None):
                super()._calc_ctrldata()
                return
            # SXT-035 table-driven scene-modwheel pass (cutoff/reso/vca, md
            # order) + SXT-042: the voice-route pass (velocity/keytrack) now
            # runs on the classic kind too.  Before SXT-042 this branch read
            # the raw parameters, so a classic-kind fixture carrying voice
            # routes DROPPED them silently (finding F-042-2); no landed
            # fixture had any, so every landed render is unchanged.
            self.aeg.process_block()
            self.feg.process_block()
            self._apply_voice_routes()
            mw = inp.modwheel.value
            cut = self.mod_cutoff
            reso = self.mod_reso
            vca = self.mod_vca_db
            for dst, depth in (table or []):
                d = qint(depth)
                if dst == DEST_FU1_CUTOFF:
                    cut = sat(cut + qmul(d, mw))
                elif dst == DEST_FU1_RESO:
                    reso = sat(reso + qmul(d, mw))
                elif dst == DEST_VCA_GAIN:
                    vca = sat(vca + qmul(d, mw))
                else:
                    raise Refuse(f"scene route {dst} outside declared class")
            self.mod_vca_db = vca
            self.cutoff_a = cut + qmul(self.mod_envmod, self.feg.output)
            self.reso_a = reso
            if self.aeg.is_idle():
                self.keep_playing = False
            return
        inp = self.inp
        self.aeg.process_block()
        self.feg.process_block()
        self._apply_voice_routes()
        mw = inp.modwheel.value
        cut = self.mod_cutoff
        reso = self.mod_reso
        vca = self.mod_vca_db
        for dst, depth in inp.scene_routes_mw:
            d = qint(depth)
            if dst == DEST_FU1_CUTOFF:
                cut = sat(cut + qmul(d, mw))
            elif dst == DEST_FU1_RESO:
                reso = sat(reso + qmul(d, mw))
            elif dst == DEST_VCA_GAIN:               # SXT-035 destination class
                vca = sat(vca + qmul(d, mw))
            else:
                raise Refuse(f"scene route {dst} outside declared class")
        self.mod_vca_db = vca
        kt_semitones = qint(float(self.pitch_voice - inp.keytrack_root))
        self.cutoff_a = cut + qmul(qint(inp.fu_kta), kt_semitones) \
            + qmul(self.mod_envmod, self.feg.output)
        self.reso_a = reso
        # v1 control-plane words are classic-path only; sine streams zeros
        self.ctrl_pmi = 0
        self.ctrl_pitchmult = 0
        self.ctrl_a_cov = 0
        self.ctrl_hpf_target = 0
        if self.aeg.is_idle():
            self.keep_playing = False

    def _gain_target(self):
        # SXT-035: mod_vca_db carries the accumulated velocity + modwheel VCA
        # route terms (== qint(vca_db) when no VCA routes exist, so v1
        # fixtures are word-identical)
        g = db_to_linear(getattr(self, "mod_vca_db", qint(self.inp.vca_db)))
        return qmul(g, self.aeg.output)

    # ---------------------------------------------------------------- osc
    def osc_process_block(self, block_index):
        if self.kind == "classic":
            return super().osc_process_block(block_index)
        if self.inp.fm_mode == 2:
            blk3 = self.sine[2].block(self.sine_omega[2], 0, None)
            blk2 = self.sine[1].block(self.sine_omega[1], self.fm_depth, blk3)
            blk1 = self.sine[0].block(self.sine_omega[0], self.fm_depth, blk2)
        else:
            # fm_switch 0: muted oscs 2/3 are not processed at all (engine
            # process_block conditions); osc1 runs the quad recurrence
            blk1 = self.sine[0].block(self.sine_omega[0], 0, None)
        # osclevels[le_osc1] lag: level 1.0 constant (first-run snap) -> x1
        self.last_oscout = list(blk1)
        return blk1

    # ----------------------------------------------------------- filter
    def process_block(self, block_index, sceneout_l, sceneout_r, trace):
        self._calc_ctrldata()
        osc_out = self.osc_process_block(block_index)
        self.cmu.make_coeffs(self.cutoff_a, self.reso_a)
        self.ctrl_C = list(self.cmu.C)
        self.ctrl_dC = list(self.cmu.dC)
        self.last_oscout = list(osc_out)

        lvl = amp_to_linear(qint(self.inp.o1_level))
        gain_start = self.prev_gain
        outl_start = self.prev_outl
        self.fbp_gain = self._gain_target()
        self.fbp_outl = self._ampl_target()
        d_gain = self.fbp_gain - gain_start
        d_outl = self.fbp_outl - outl_start

        c = self.cmu.C
        one = ONE
        mix1 = self.inp.mix1
        one_minus_mix1 = ONE - mix1
        poles = self.fu_poles
        f2_r0, f2_r1, f_clip = self.f_r0, self.f_r1, self.f_clip
        f4_r0, f4_r1 = self.f4_r0, self.f4_r1
        for k in range(BLOCK_SIZE_OS):
            for i in range(N_COEF):
                c[i] = sat(c[i] + self.cmu.dC[i])
            dl = qmul(osc_out[k], lvl)
            if poles == 12:
                y = qmul(c[4], f2_r0) + qmul(c[6], dl) + qmul(c[5], f2_r1)
                s1 = qmul(dl, c[2]) + qmul(c[0], f2_r0) - qmul(c[1], f2_r1)
                s2 = qmul(c[1], f2_r0) + qmul(c[0], f2_r1)
                f2_r0 = qmul(s1, f_clip)
                f2_r1 = qmul(s2, f_clip)
                f_clip = max(qint(0.1), one - qmul(c[7], qmul(y, y)))
                yb = y
            else:
                # IIR24CFCquad: two coupled-form sections, shared C, one clip
                y = qmul(c[4], f2_r0) + qmul(c[6], dl) + qmul(c[5], f2_r1)
                s1 = qmul(dl, c[2]) + qmul(c[0], f2_r0) - qmul(c[1], f2_r1)
                s2 = qmul(c[1], f2_r0) + qmul(c[0], f2_r1)
                f2_r0 = qmul(s1, f_clip)
                f2_r1 = qmul(s2, f_clip)
                y2 = qmul(c[4], f4_r0) + qmul(c[6], y) + qmul(c[5], f4_r1)
                s3 = qmul(y, c[2]) + qmul(c[0], f4_r0) - qmul(c[1], f4_r1)
                s4 = qmul(c[1], f4_r0) + qmul(c[0], f4_r1)
                f4_r0 = qmul(s3, f_clip)
                f4_r1 = qmul(s4, f_clip)
                f_clip = max(qint(0.1), one - qmul(c[7], qmul(y2, y2)))
                yb = y2
            # fc_serial1 Mix1 blend (ProcessFBQuad): x = in*(1-mix1) + FU1*mix1
            xb = sat(qmul(dl, one_minus_mix1) + qmul(yb, mix1))
            outv = qmul(xb, gain_start + qround(d_gain * (k + 1), 6))
            ol = outl_start + qround(d_outl * (k + 1), 6)
            sceneout_l[k] += qmul(outv, ol)
            sceneout_r[k] += qmul(outv, ol)
        self.f_r0, self.f_r1, self.f_clip = f2_r0, f2_r1, f_clip
        self.f4_r0, self.f4_r1 = f4_r0, f4_r1
        self.prev_gain = self.fbp_gain
        self.prev_outl = self.fbp_outl

        if trace is not None:
            trace.checkpoint_voice(block_index, self)
        return self.keep_playing


class InputsV2:
    """Schema-2 voice inputs (quickspit/bells sidecars) + applicability gate.

    Fail-closed: any graph property outside the declared SXT-026a class
    raises Refuse (the runner exits 2).  The class is frozen in
    model/voice/README.md ("SXT-026a extension").
    """

    def __init__(self, inputs_path):
        with open(inputs_path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("schema_version") != 2:
            raise Refuse(f"{inputs_path}: expected schema_version 2")
        n = d["not_in_graphs"]
        g = d["graph_echo"]
        self.preset_path = d["preset"]["path"]
        self.voice_class = d["voice_class"]
        self.scene_volume = n["scene_volume"]
        self.vca_db = n["vca_level"]
        self.master_db = n["master_volume"]
        self.o1_level = n["level_o1"]
        self.octave = int(g["osc1"]["oct"])
        self.character = int(n["character"])
        self.adsr = n["adsr"]
        self.fadsr = n["fadsr"]
        self.scene_octave = int(n.get("scene_octave", 0.0))
        self.keytrack_root = int(n["keytrack_root"])
        self.cutoff = n["fu0"]["cutoff"]
        self.reso = n["fu0"]["resonance"]
        self.envmod = n["fu0"]["envmod"]
        self.fu_kta = n["fu0"]["keytrack"]
        if int(n["fu0"]["type"]) not in (1, 2):
            raise Refuse("filter unit 1 type not LP12/LP24")
        self.fu_poles = {1: 12, 2: 24}[int(n["fu0"]["type"])]
        self.mix1 = qint(min(1.0, 1.0 - g["bal"]))       # SetQFB FMix1
        self.modwheel = Modwheel()
        self._gate(n, g)

        o1 = g["osc1"]
        self.osc_kind = "classic" if o1["t"] == 0 else "sine"
        if self.osc_kind == "sine":
            self.sine_lowcut = o1["p"][3]
            self.sine_highcut = o1["p"][4]
            fm = g["fm"]
            self.fm_mode = int(fm["sw"])         # 0: quad-only; 2: 3>2>1 chain
            if fm["sw"] == 2:
                self.fm_depth = db_to_linear(qint(fm["dep"]))
            elif fm["sw"] == 0:
                self.fm_depth = 0
            else:
                raise Refuse(f"fm_switch {fm['sw']} not in declared class {{0,2}}")
            self._gate_sine_osc(g["osc2"], "osc2")
            self._gate_sine_osc(g["osc3"], "osc3")
            self.osc_pitch_offsets = [12 * int(o1["oct"]),
                                      12 * int(g["osc2"]["oct"]),
                                      12 * int(g["osc3"]["oct"])]
            self.shape, self.pw1, self.pw2 = 0.0, 0.5, 0.5
            self.submix, self.sync = 0.0, 0.0
        else:
            if g["fm"]["sw"] != 0:
                raise Refuse("classic-kind fixture with FM routing: not in class")
            if self.scene_octave != 0:
                raise Refuse("classic-kind fixture with scene octave: not in class")
            p = o1["p"]
            self.shape, self.pw1, self.pw2 = p[0], p[1], p[2]
            self.submix, self.sync = p[3], p[4]
            self.sine_lowcut = self.sine_highcut = 0.0
            self.fm_depth = 0
            self.osc_pitch_offsets = [12 * int(o1["oct"]), 0, 0]

        # SXT-034 unison inputs at the declared v2-class identity: the class
        # gate above refuses uni != 1 / rt != 1, so Voice.__init__'s unison
        # stack degenerates to the uni=1 identity (per-voice declared draws
        # are a v1-class override mechanism, never present here).
        self.n_unison = int(o1.get("uni", 1))
        self.spread = float(o1.get("udet", 0.0))
        self.retrigger = bool(o1.get("rt", 1))
        self._draws = []
        self._draw_i = 0

        # modulation routes (order = md arrays = engine application order)
        self.voice_routes = []
        for r in g["md_scene_A"]["v"]:
            src, dst = r[0], r[3]
            if src not in VOICE_ROUTE_VOCAB or dst not in VOICE_ROUTE_VOCAB[src]:
                raise Refuse(f"voice route {src}->{dst} outside declared class")
            if dst in (DEST_FU2_CUTOFF, DEST_FU2_RESO, DEST_FU2_FEGMOD):
                continue                         # unit 2 off: inert, unmodeled
            self.voice_routes.append((src, dst, r[5]))
        self.scene_routes_mw = []
        self.scene_routes_fm = False
        self.mod_cutoff_depth = 0.0
        self.mod_reso_depth = 0.0
        for r in g["md_scene_A"]["s"]:
            src, dst = r[0], r[3]
            if src not in SCENE_ROUTE_VOCAB or dst not in SCENE_ROUTE_VOCAB[src]:
                raise Refuse(f"scene route {src}->{dst} outside declared class")
            if dst == DEST_FM_DEPTH:
                self.scene_routes_fm = True      # modwheel -> FM Depth
            elif dst == DEST_FU1_CUTOFF:
                self.mod_cutoff_depth = r[5]
                self.scene_routes_mw.append((dst, r[5]))
            elif dst == DEST_FU1_RESO:
                self.mod_reso_depth = r[5]
                self.scene_routes_mw.append((dst, r[5]))
            elif dst == DEST_VCA_GAIN:           # SXT-035 destination class
                self.scene_routes_mw.append((dst, r[5]))

    def next_draw(self):
        """Consume one declared init-phase draw (SXT-034 interface parity
        with the v1 Inputs class; the v2 class gates retrigger=on, so no
        draw is ever consumed -- a call here is a contract bug, fail loud)."""
        raise RuntimeError("InputsV2 carries no declared init-phase draws")

    def reset_draws(self):
        self._draw_i = 0

    # ------------------------------------------------------------- gates
    def _gate(self, n, g):
        if abs(n["scene_drift"]) > 0:
            raise Refuse(f"scene drift {n['scene_drift']} != 0 (determinism gate)")
        if abs(n["vca_velsense"]) > 0:
            raise Refuse("vca_velsense != 0")
        if abs(n["pan"]) > 0:
            raise Refuse("scene pan != 0 (mono-bus class)")
        if abs(n["level_pfg"]) > 0:
            raise Refuse("pfg != 0")
        if n["portamento"] != -8.0:
            raise Refuse("portamento active")
        if int(n["adsr"]["mode"]) != 0 or int(n["fadsr"]["mode"]) != 0:
            raise Refuse("analog envelopes not in class")
        if int(n["fadsr"]["d_s"]) != 0:
            raise Refuse("filter env decay shape not in class")
        if g.get("fbc") != 0:
            raise Refuse("filter config not serial1")
        if g.get("lc") != -72.0:
            raise Refuse("lowcut not at off value")
        if g.get("ws", {}).get("t", 0) != 0:
            raise Refuse("waveshaper not off")
        mix = g["mix"]
        act = [k for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23")
               if mix.get(k, [1, 1])[1] == 0]
        if act != ["o1"]:
            raise Refuse(f"active mixer paths {act} != ['o1']")
        if g["fu1"]["t"] != 0:
            raise Refuse("filter unit 2 not Off")
        if self.fu_kta != 0.0:
            raise Refuse("filter unit 1 keytrack param != 0")
        if int(g["osc1"]["kt"]) != 1:
            raise Refuse("osc1 keytrack not on")
        if abs(g["osc1"]["pit"]) > 0:
            raise Refuse("osc1 pitch offset != 0")
        if g["osc1"]["uni"] != 1 or g["osc1"]["rt"] != 1:
            raise Refuse("osc1 not unison-1/retrigger")
        if self.character not in (0, 1):
            raise Refuse("character Bright not in class")
        if g["osc1"]["t"] == 1:
            self._gate_sine_osc(g["osc1"], "osc1")
        else:
            if abs(g["osc1"]["p"][4]) > 0:
                raise Refuse("classic sync param p[4] not 0")

    def _gate_sine_osc(self, o, name):
        if o["t"] != 1:
            raise Refuse(f"{name} not Sine (the fm_3to2to1 chain requires Sine)")
        if o["uni"] != 1 or o["rt"] != 1:
            raise Refuse(f"{name} not unison-1/retrigger")
        p = o["p"]
        if int(p[0]) != SINE_SHAPE_MAX:
            raise Refuse(f"{name} sine shape {p[0]} != 0 (frozen class)")
        if int(p[2]) != 0:
            raise Refuse(f"{name} sine FMmode {p[2]} != 0 (legacy path only)")
        if not (-60.0 <= p[3] <= 70.0) or not (-60.0 <= p[4] <= 70.0):
            raise Refuse(f"{name} lowcut/highcut outside param range")

    # ------------------------------------------------------------ events
    def check_sequence(self, seq):
        if self.osc_kind == "sine":
            for e in seq["events"]:
                if e["type"] not in ("note_on", "note_off"):
                    raise Refuse(
                        f"event type {e['type']} refused for Sine-class preset "
                        f"{self.preset_path}: FM depth must stay constant "
                        "(the modwheel targets FM Depth in this class)")
        for e in seq["events"]:
            if e["type"] == "note_on":
                p = e["note"] + 12 * self.scene_octave + self.osc_pitch_offsets[0]
                if not (24 <= p <= 148):
                    raise Refuse(f"note {e['note']} renders pitch {p} "
                                 "outside declared [24,148]")
