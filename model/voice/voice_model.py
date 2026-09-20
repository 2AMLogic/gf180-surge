#!/usr/bin/env python3
"""SXT-022 frozen fixed-point voice model for factory preset `Basses/Attacky.fxp`.

This module is the FROZEN reference for the SXT-022 RTL (`rtl/voice/`).
RTL-vs-model agreement must be EXACT (integer equality at every declared
checkpoint). Model-vs-pinned-engine agreement is governed by error budgets
(fidelity policy DRAFT; budgets are not frozen -- SXT-022 reports achieved
numbers only, no freeze claims).

Word lengths and operation order are normative: `model/voice/README.md`.

Structure is cited from the pinned engine (read, not copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  SurgeVoice.cpp process_block/calc_ctrldata/SetQFB    gain staging + ramps
  ClassicOscillator.cpp process_block/convolute        impulse engine
  QuadFilterChain.cpp ProcessFBQuad (fc_serial1)       per-OS-sample chain
  sst-filters FilterCoefficientMaker_Impl.h            Coeff_LP12/ToCoupledForm/
                                                       FromDirect (smooth=0.2)
  sst-filters QuadFilterUnit_Impl.h IIR12CFCquad       2-pole coupled form
  ADSRModulationSource.h (digital mode)                envelopes
  ModulationSource.h ControllerModulationSourceVector  FAST_LINE modwheel
  sst-filters HalfRateFilter.h (M=6, steep)            scene decimator
  sst-basic-blocks OscillatorDriftUnisonCharacter.h    CharacterFilter (Warm)
  SurgeStorage init_tables + lookup functions          tables recomputed

Arithmetic discipline (FROZEN, enforced throughout):
  * every value is a Python int in two's-complement Q-format;
  * Q4.27 universal sample/coef word; Q2.29 envelope phase;
    Q12.20 pitchmult_inv; 16-bit sinc lipol fraction;
  * products are exact then rounded back round-half-up:
        r = (a*b + (1 << (s-1))) >> s,  s = fa+fb-fq
    and saturated to the signed 32-bit range;
  * divisions only at coefficient (block) rate via qdiv (round-half-up);
  * sinc sub-sample position truncates toward zero like the engine's
    (unsigned int) cast;
  * no floating point at run time; no dict-iteration-order dependence.
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
    """Round-half-up arithmetic shift by s (left shift when s < 0)."""
    if s <= 0:
        return sat(x << (-s))
    return (x + (1 << (s - 1))) >> s


def qmul(a, b, fa=FQ, fb=FQ, fq=FQ):
    s = fa + fb - fq
    if s > 0:
        return (a * b + (1 << (s - 1))) >> s
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
        self.target = qdiv(cc, qint(127.0))
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
    independent 6-stage allpass cascades (coefficient sets A and B). Per
    stage and sample the engine's shift sequence evaluates
        y[n] = x[n-2] + a*(x[n] - y[n-2])
    with states (x[n], x[n-1], x[n-2]) / (y[n], y[n-1], y[n-2]); the
    decimated output is out[n] = (A[2n] + B[2n+1]) * 0.5 (n = 0..31).
    (The engine test suite notes the decimator passes the passband at
    half amplitude; the voice path compensates via its amp *0.5.)
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
                y = self.bx[j][2] + qmul(HALFBAND_B_Q[j], xb - self.by[j][2])
                self.bx[j] = [xb, self.bx[j][0], self.bx[j][1]]
                self.by[j] = [y, self.by[j][0], self.by[j][1]]
                xb = y
                y = self.ax[j][2] + qmul(HALFBAND_A_Q[j], xa - self.ay[j][2])
                self.ax[j] = [xa, self.ax[j][0], self.ax[j][1]]
                self.ay[j] = [y, self.ay[j][0], self.ay[j][1]]
                xa = y
            chain_b.append(xb)
            chain_a.append(xa)
        return [(chain_a[2 * n] + chain_b[2 * n + 1]) >> 1 for n in range(len(inp) // 2)]


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
        self.ob = [0] * (OB_LENGTH + FIRIPOL_N)
        self.dcb = [0] * (OB_LENGTH + FIRIPOL_N)
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
        self.pwidth = limit_i(self.l_pw, qint(0.001), qint(0.999))
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
        self.out_attenuation = ONE                # unison 1

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
        while self.oscstate < a_cov:
            self._convolute(pmi)
        self.oscstate -= a_cov

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

    def _convolute(self, pmi):
        wf = self.l_shape
        sub = self.l_sub
        # (unsigned int)(2^24 * oscstate * pitchmult_inv): truncate like the engine
        ipos = (self.oscstate * pmi) >> (FQ + PMI_F - 24)
        ipos &= 0xFFFFFFFF
        delay = (ipos >> 24) & 0x3F
        m = ((ipos >> 16) & 0xFF) * (FIRIPOL_N << 1)
        lipol = ipos & 0xFFFF

        t = ntpi_tuningctr(self.l_sync)           # detune = 0 (drift gate)
        t_inv = qdiv(ONE, t)

        st = self.osc_state
        one = ONE
        if st == 0:
            self.pwidth = limit_i(self.l_pw, qint(0.001), qint(0.999))
            self.pwidth2 = qmul(qint(2.0), self.l_pw2)
        pw = self.pwidth
        pw2 = self.pwidth2
        om1 = one - sub                                      # (1-sub)
        if st == 0:
            # tg = ((1+wf)*0.5 + (1-pw)*(-wf))*(1-sub) + 0.5*sub*(2-pw2)
            tg = qmul(qround(one + wf, 1) + qmul(one - pw, -wf), om1)
            tg += qmul(qround(sub, 1), qint(2.0) - pw2)
            g = tg - self.last_level
            self.last_level = tg
            self.last_level -= qmul(qmul(pw, pw2), qmul(one + wf, om1))
        elif st == 1:
            g = qmul(wf, om1) - sub
            self.last_level += g
            self.last_level -= qmul(qmul(one - pw, qint(2.0) - pw2), qmul(one + wf, om1))
        elif st == 2:
            g = om1
            self.last_level += g
            self.last_level -= qmul(qmul(pw, qint(2.0) - pw2), qmul(one + wf, om1))
        else:
            g = qmul(wf, om1) + sub
            self.last_level += g
            self.last_level -= qmul(qmul(one - pw, pw2), qmul(one + wf, om1))
        # g *= out_attenuation (1) ; mono pan (1)

        base = self.bufpos + delay
        m12 = m >> 1                     # separate tables: phase*FIRIPOL_N + k
        for k in range(FIRIPOL_N):
            term = SINC_MAIN[m12 + k] + qmul(lipol, SINC_DERIV[m12 + k], fb=16)
            self.ob[base + k] = sat(self.ob[base + k] + qmul(term, g))

        olddc = self.dc_uni
        self.dc_uni = qmul(t_inv, qmul(one + wf, om1))
        self.dcb[base + FIROFFSET] = sat(self.dcb[base + FIROFFSET]
                                         + (self.dc_uni - olddc))

        if st & 1:
            rate = qmul(t, one - pw)
        else:
            rate = qmul(t, pw)
        if (st + 1) & 2:
            rate = qmul(rate, qint(2.0) - pw2)
        else:
            rate = qmul(rate, pw2)
        self.oscstate = max(0, self.oscstate + rate)
        self.osc_state = (st + 1) & 3

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
