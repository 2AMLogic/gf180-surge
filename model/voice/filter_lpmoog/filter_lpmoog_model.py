#!/usr/bin/env python3
"""SXT-039 frozen fixed-point LP Legacy Ladder filter model (all subtypes).

This module is the FROZEN reference for the SXT-039 filter leaf RTL
(`rtl/voice/tb_lpmoog.sv`). RTL-vs-model agreement must be EXACT (integer
equality at every declared checkpoint; `tools/compare_rtl_model_lpmoog.py`).
Model-vs-pinned-kernel agreement is a SEPARATE claim governed by [PROPOSED]
error budgets (PENDING-FREEZE; SXT-013/#12 owns the fidelity policy),
measured by `tools/compare_lpmoog_model.py` against reference streams
rendered by the pinned kernel (`tools/render_lpmoog_reference.py`).
Neither claim says anything about how the instrument sounds.

Word lengths and operation order are normative and documented in
`model/voice/filter_lpmoog/README.md` (this directory). Sample and register
words are Q10.21 signed 32-bit, the universal word of the landed SXT-022
voice model (`model/voice/voice_model.py`, imported here for its arithmetic
helpers and engine-table formulas); the coefficient plane (C/dC/tC) is frozen
at Q2.29, the tightest signed-32-bit word covering this type's pinned
coefficient range (|C| < 4) -- see the word-length table in the README.

Structure is CITED from the pinned engine (read, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  libs/sst/sst-filters include/sst/filters/FilterConfiguration.h
      fut_lpmoog (type id 3, display name "LP Legacy Ladder"), its declared
      subtype count (4) and the subtype ids st_lpmoog_6dB/12dB/18dB/24dB
  libs/sst/sst-filters include/sst/filters/FilterCoefficientMaker_Impl.h
      MakeCoeffs (fut_lpmoog -> Coeff_LP4L), Coeff_LP4L (the gg clamp, the
      t_b1 one-pole coefficient, the q resonance mapping and its
      1/(2*t_b1^4) guard, c0 = 3/(3-q)), FromDirect (smooth = 0.2,
      blockSizeInv = 1/64, FirstRun), n_cm_coeffs = 8
  libs/sst/sst-filters include/sst/filters/QuadFilterUnit_Impl.h
      LPMOOGquad<subtype> (per-sample C[0..2] += dC[0..2] reload, the
      softclipped first stage, the three trailing one-pole stages, the
      R[3]/R[4] feedback pair and the subtype output tap), and
      GetQFPtrFilterUnit's fut_lpmoog -> LPMOOGquad<subtype> table
  libs/sst/sst-basic-blocks include/sst/basic-blocks/dsp/Clippers.h
      softclip8_ps (clamp +/-12, y = x - (4/27/8^3)*x^3, evaluated in the
      pinned op order)
  src/common/SurgeStorage.cpp / .h
      note_to_pitch_ignoring_tuning (table_pitch coarse table + the
      table_two_to_the fine interpolation) and its table construction
      formulas; dsamplerate_os = 2 * 48000 with BLOCK_SIZE_OS = 64
  src/common/dsp/SurgeVoice.cpp
      cutoffA = localcopy[cutoff] + localcopy[keytrack] * (state.pitch -
      keytrack_root) + localcopy[envmod] * filter-EG output (the leaf's
      keytrack / env-mod path), the per-voice FBP zero-init and the
      type/subtype-change reset (memset(&FBP.FU[u]) + CM[u].Reset()), and
      the per-block coefficient read-back CM[u].C[i] = FU[u].C[i]

Arithmetic discipline (FROZEN, same as the landed voice model):
  * every value is a Python int in two's-complement Q10.21;
  * products are exact then rounded back round-half-up:
        r = (a*b + (1 << (s-1))) >> s,  s = fa+fb-fq
    and saturated to the signed 32-bit range;
  * divisions only at coefficient (block) rate via qdiv (round-half-up);
  * frequency-domain constructions (note_to_pitch, exp) are evaluated in
    double precision against the pinned formulas and quantized once
    (declared deviation: the engine evaluates float32 table lerps and
    float32 exp; the difference is part of the model-vs-reference budget);
  * no floating point at run time (the audio path is pure integer).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice_model as vm  # noqa: E402

ONE = vm.ONE
FQ = vm.FQ
qint = vm.qint
qmul = vm.qmul
qdiv = vm.qdiv
sat = vm.sat
limit_i = vm.limit_i

# --------------------------------------------------------- declared scope
FUT_LPMOOG = 3                  # FilterType registry id at the pin
TYPE_LPMOOG = FUT_LPMOOG

SUBTYPE_6DB = 0                 # st_lpmoog_6dB  -> output tap R[0]
SUBTYPE_12DB = 1                # st_lpmoog_12dB -> output tap R[1]
SUBTYPE_18DB = 2                # st_lpmoog_18dB -> output tap R[2]
SUBTYPE_24DB = 3                # st_lpmoog_24dB -> output tap R[3]
SUBTYPES = (SUBTYPE_6DB, SUBTYPE_12DB, SUBTYPE_18DB, SUBTYPE_24DB)
SUBTYPE_NAMES = {0: "6 dB", 1: "12 dB", 2: "18 dB", 3: "24 dB"}

# Applicability boundary (fail-closed, enforced by LPMoogCoeffMaker):
# resonance is the normalized [0, 1] filter parameter; the cutoff argument is
# the engine's post-control-arithmetic cutoffA, accepted over the same
# declared span as the landed SXT-037 leaf ([-240, +240] semitones relative
# to A440).  Values outside the declared spans are REFUSED, never silently
# clamped, so an out-of-scope fixture fails loudly instead of producing
# unvetted audio.  (The pinned gg clamp INSIDE Coeff_LP4L is a different
# thing: it is engine behaviour and is reproduced exactly.)
RESO_MIN, RESO_MAX = 0.0, 1.0
CUT_SCOPE_MIN, CUT_SCOPE_MAX = -240.0, 240.0

N_COEF = 8                                  # n_cm_coeffs
# Coefficient plane word (FROZEN, leaf-local): Coeff_LP4L's three live
# coefficients are bounded by |C| < 4 at the pin (c0 = 3/(3-q) <= 3.53 with
# q <= 2.15; c1 = t_b1 <= 1-exp(-2*pi*0.187) = 0.6913; c2 = q <= 2.15), while
# the useful low end reaches ~1e-5 (c1 at the bottom of the cutoff span).
# Q2.29 is therefore the tightest signed-32-bit word that covers the pinned
# range, and it is frozen for C/dC/tC.  Sample and register words stay Q10.21
# (the universal SXT-022 word); see README.md for the measured effect of this
# choice and the low-cutoff dead-zone finding it does NOT remove.
COEF_FQ = 29
COEF_ONE = 1 << COEF_FQ
COEF_SMOOTH = qint(0.2)                     # FilterCoefficientMaker smooth (Q10.21)
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS            # 64 OS samples per engine block
SAMPLERATE_OS = 96000.0                     # dsamplerate_os (2 x 48 kHz)

GG_MAX = 0.187                              # pinned Coeff_LP4L clamp
Q_RESO_SCALE = 2.15                         # pinned 2.15f * clamp(reso,0,1)

# softclip8 (pinned Clippers.h): clamp to +/-12, y = x + (a * x) * x^2 with
# a = -4/27/8^3.  The cubic coefficient is held at Q0.40 and the first
# product at Q1.31 (declared intermediate words) so that the correction term
# keeps full Q10.21 significance at the +/-12 corner; the engine evaluates
# the same op order in float32 (declared deviation, in-budget class).
SOFTCLIP8_LIMIT = qint(12.0)
SOFTCLIP8_A_FRAC = 40
SOFTCLIP8_A = int(math.floor(-(4.0 / 27.0) / 512.0 * (1 << SOFTCLIP8_A_FRAC) + 0.5))
SOFTCLIP8_T_FRAC = 31

# register initialization: the per-voice FBP is zeroed at voice creation and
# re-zeroed on a type/subtype change (SurgeVoice.cpp memset + CM.Reset()), so
# all five ladder registers start at 0.
N_REG = 5


class Refuse(Exception):
    """Applicability boundary: out-of-scope request, refused (fail-closed)."""


# ------------------------------------------------------- engine table body
def ntp_ignoring_tuning_d(x_semi):
    """SurgeStorage::note_to_pitch_ignoring_tuning(x) body, evaluated in double.

    Pinned body: x = limit_range(x + 256, 1e-4, 512 - 1e-4); e = (int)x;
    a = x - e; pow2v = lerp(table_two_to_the, a * 1000);
    return table_pitch_ignoring_tuning[e] * pow2v, with the pinned table
    construction formulas table_pitch[i] = 2^((i-256)/12) and
    table_two_to_the[i] = 2^(i/12000).
    """
    xf = min(max(x_semi + 256.0, 1e-4), 512.0 - 1e-4)
    e = int(xf)
    a = xf - e
    pow2pos = a * 1000.0
    idx = int(pow2pos)
    frac = pow2pos - idx
    pow2v = (1 - frac) * (2.0 ** (idx / 12000.0)) + frac * (2.0 ** ((idx + 1) / 12000.0))
    return (2.0 ** ((e - 256) / 12.0)) * pow2v


def qintc(x):
    """Quantize a double to the frozen Q2.29 coefficient word (round-half-up)."""
    return sat(int(math.floor(x * COEF_ONE + 0.5)))


def softclip8(v):
    """pinned softclip8_ps body in the frozen fixed-point words (Q10.21)."""
    x = limit_i(v, -SOFTCLIP8_LIMIT, SOFTCLIP8_LIMIT)
    xx = qmul(x, x)
    t = qmul(x, SOFTCLIP8_A, fa=FQ, fb=SOFTCLIP8_A_FRAC, fq=SOFTCLIP8_T_FRAC)
    t = qmul(t, xx, fa=SOFTCLIP8_T_FRAC, fb=FQ, fq=FQ)
    return sat(t + x)


def cutoff_control(cut, keytrack_depth, pitch, keytrack_root, envmod, fenv):
    """SurgeVoice.cpp cutoffA arithmetic (the leaf's keytrack / env-mod path).

    Pinned body (process_block):
        keytrack = state.pitch - (float)scene->keytrack_root.val.i
        cutoffA  = localcopy[cutoff] + localcopy[keytrack] * keytrack
                                     + localcopy[envmod] * fenv
    All arguments and the result are Q10.21; `pitch` and `keytrack_root` are
    Q10.21 semitone words (MIDI note numbers), `fenv` is the filter-EG output
    word.  Saturating adds, round-half-up products (frozen op order: the two
    modulation products are formed first, then added left to right).
    """
    kt = qmul(keytrack_depth, sat(pitch - keytrack_root))
    em = qmul(envmod, fenv)
    return sat(sat(cut + kt) + em)


# ------------------------------------------------------- coefficient maker
class LPMoogCoeffMaker:
    """FilterCoefficientMaker for fut_lpmoog (Coeff_LP4L + FromDirect).

    Coeff_LP4L writes only c[0..2] (the pinned body memsets the 8-word array
    first, so c[3..7] are zero every call); FromDirect smooths all eight
    words.  `reset()` mirrors CM.Reset() (fresh voice or type/subtype
    change): the next make_coeffs() takes the FirstRun path.

    The coefficient maker is subtype-independent at the pin (Coeff_LP4L
    ignores its subtype argument); the subtype selects the output tap in the
    kernel.  The subtype is still validated here so an out-of-scope subtype
    can never reach the audio path.
    """

    def __init__(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP Legacy "
                         f"Ladder set {SUBTYPES}")
        self.subtype = subtype
        self.C = [0] * N_COEF
        self.dC = [0] * N_COEF
        self.tC = [0] * N_COEF
        self.first_run = True

    def reset(self):
        self.first_run = True

    def make_coeffs(self, freq, reso):
        """MakeCoeffs(freq, reso, fut_lpmoog, subtype); freq semitones rel A440.

        Construction (pinned Coeff_LP4L, evaluated in double and quantized
        once -- declared deviation):
            gg   = clamp(440 * note_to_pitch_ignoring_tuning(freq) / SR_os,
                         0, 0.187)
            t_b1 = 1 - exp(-2*pi*gg)
            q    = min(2.15 * clamp(reso, 0, 1), 0.5 / t_b1^4)
            c[0] = 3 / (3 - q);  c[1] = t_b1;  c[2] = q
        The 0.5/t_b1^4 guard is +inf at t_b1 == 0 in the pinned float math
        (division by zero); the model reproduces that limit explicitly rather
        than guessing a finite substitute.
        """
        if not (qint(CUT_SCOPE_MIN) <= freq <= qint(CUT_SCOPE_MAX)):
            raise Refuse(f"cutoff {freq / float(ONE):.3f} st outside the declared "
                         f"scope [{CUT_SCOPE_MIN}, {CUT_SCOPE_MAX}]")
        if not (qint(RESO_MIN) <= reso <= qint(RESO_MAX)):
            raise Refuse(f"resonance {reso / float(ONE):.4f} outside the declared "
                         f"scope [{RESO_MIN}, {RESO_MAX}]")
        freq_d = freq / float(ONE)
        reso_d = reso / float(ONE)
        gg = min(max(440.0 * ntp_ignoring_tuning_d(freq_d) / SAMPLERATE_OS, 0.0), GG_MAX)
        t_b1 = 1.0 - math.exp(-2.0 * math.pi * gg)
        guard = math.inf if t_b1 == 0.0 else 0.5 / (t_b1 ** 4)
        q = min(Q_RESO_SCALE * min(max(reso_d, 0.0), 1.0), guard)
        n = [0] * N_COEF
        n[0] = qintc(3.0 / (3.0 - q))
        n[1] = qintc(t_b1)
        n[2] = qintc(q)
        self._from_direct(n)

    def _from_direct(self, n):
        """pinned FromDirect(): smooth = 0.2, blockSizeInv = 1/64, FirstRun.

        All words are the frozen Q2.29 coefficient word; the 0.2 smoothing
        constant is a Q10.21 literal multiplied into a Q2.29 difference
        (round-half-up back to Q2.29).
        """
        if self.first_run:
            self.dC = [0] * N_COEF
            self.C = list(n)
            self.tC = list(n)
            self.first_run = False
        else:
            for i in range(N_COEF):
                self.tC[i] = sat(self.tC[i] + qmul(COEF_SMOOTH, sat(n[i] - self.tC[i]),
                                                   fa=FQ, fb=COEF_FQ, fq=COEF_FQ))
                self.dC[i] = qdiv(sat(self.tC[i] - self.C[i]), BLOCK_SIZE_OS, fb=0)


# ---------------------------------------------------------------- kernel
class LPMoogUnit:
    """One per-instance filter unit: registers + the frozen per-sample schedule.

    Per-instance state is NEVER shared: every voice/unit instance owns one
    LPMoogUnit with its own five registers (AGENTS.md state rule) even when
    the arithmetic is shared.  R[0..3] are the four ladder stages; R[4] holds
    the previous R[3] (the pinned half-sample feedback pair).
    """

    def __init__(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP Legacy "
                         f"Ladder set {SUBTYPES}")
        self.subtype = subtype
        self.r = [0] * N_REG
        self.qmul_count = 0

    def reset_state(self):
        """FBP.FU[u] memset path (voice creation / type or subtype change)."""
        self.r = [0] * N_REG

    def set_subtype(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP Legacy "
                         f"Ladder set {SUBTYPES}")
        self.subtype = subtype
        self.reset_state()

    def process_block(self, inp64, cm):
        """One 64-OS-sample block; returns (outputs, peak |state|, end C[8]).

        Frozen per-sample order (pinned LPMOOGquad):
            C[0] += dC[0]; C[1] += dC[1]; C[2] += dC[2]
            R[0]  = softclip8(R[0] + C[1] * ((in*C[0] - C[2]*(R[3]+R[4])) - R[0]))
            R[1] += C[1] * (R[0] - R[1])
            R[2] += C[1] * (R[1] - R[2])
            R[4]  = R[3]
            R[3] += C[1] * (R[2] - R[3])
            y     = R[subtype]
        Registers and samples are Q10.21; coefficients are Q2.29, so every
        coefficient product rounds back to Q10.21 in one step (fa=29, fb=21).
        The coefficient words C[3..7] carry no kernel meaning for this type
        (they are smoothed zeros); they are still streamed and checkpointed so
        the RTL holds the same eight-word coefficient plane as the engine.
        """
        c = list(cm.C)
        dc = list(cm.dC)
        r = self.r
        out = []
        peak = 0
        tap = self.subtype
        for x in inp64:
            c[0] = sat(c[0] + dc[0])
            c[1] = sat(c[1] + dc[1])
            c[2] = sat(c[2] + dc[2])
            fb = sat(r[3] + r[4])
            drive = sat(sat(qmul(x, c[0], fa=FQ, fb=COEF_FQ, fq=FQ)
                            - qmul(c[2], fb, fa=COEF_FQ, fb=FQ, fq=FQ)) - r[0])
            r[0] = softclip8(sat(r[0] + qmul(c[1], drive, fa=COEF_FQ, fb=FQ, fq=FQ)))
            r[1] = sat(r[1] + qmul(c[1], sat(r[0] - r[1]), fa=COEF_FQ, fb=FQ, fq=FQ))
            r[2] = sat(r[2] + qmul(c[1], sat(r[1] - r[2]), fa=COEF_FQ, fb=FQ, fq=FQ))
            r[4] = r[3]
            r[3] = sat(r[3] + qmul(c[1], sat(r[2] - r[3]), fa=COEF_FQ, fb=FQ, fq=FQ))
            y = r[tap]
            self.qmul_count += 9        # 6 kernel + 3 softclip8 products
            out.append(y)
            m = max(abs(y), abs(r[0]), abs(r[3]))
            if m > peak:
                peak = m
        self.r = r
        return out, peak, c


# ------------------------------------------------------ stability argument
def stability_verdict(peaks, sat_floor=1 << 30, growth_db_per_block=6.0, tail=16,
                      floor=1 << 20):
    """Post-hoc boundedness verdict over per-block state peaks (ints).

    The frozen LP Legacy Ladder is structurally bounded: the only feedback
    path re-enters stage 0, whose output is softclip8-limited to |R[0]| <= 12
    (Q10.21), and stages 1..3 are one-pole smoothers with C[1] in
    [0, 1-exp(-2*pi*0.187)] = [0, 0.6913], i.e. |1 - C[1]| <= 1: no state can
    exceed the stage-0 bound in steady state.  This monitor is the empirical
    check of that argument, not a substitute for it: reaching the saturation
    neighbourhood is UNSTABLE by definition (a recorded alarm, never a silent
    clamp).
    """
    if not peaks:
        return "STABLE"
    if max(peaks) >= sat_floor:
        return "UNSTABLE"
    if len(peaks) < tail:
        return "STABLE"
    win = peaks[-tail:]
    if max(win) < floor:
        return "STABLE"
    rising = sum(1 for a, b in zip(win, win[1:]) if b > a)
    dB = math.log10(max(win[-1], 1) / max(win[0], 1)) * 20.0
    if rising >= tail - 2 and dB > growth_db_per_block * (tail - 1):
        return "UNSTABLE"
    return "STABLE"
