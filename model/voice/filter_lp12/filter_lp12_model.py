#!/usr/bin/env python3
"""SXT-037 frozen fixed-point LP 12 dB filter model (all engine subtypes).

This module is the FROZEN reference for the SXT-037 filter leaf RTL
(`rtl/voice/tb_lp12.sv`). RTL-vs-model agreement must be EXACT (integer
equality at every declared checkpoint; `tools/compare_rtl_model_lp12.py`).
Model-vs-pinned-engine agreement is governed by [PROPOSED] error budgets
(PENDING-FREEZE; SXT-013 owns the fidelity policy) measured on the leaf's
carrier fixtures.

Word lengths and operation order are normative: `model/voice/README.md`
(this directory). Sample/coef words are Q10.21 signed 32-bit, the same
frozen word as the landed SXT-022 voice model (`model/voice/voice_model.py`,
imported here for its arithmetic helpers and engine-table formulas).

Structure is CITED from the pinned engine (read, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  libs/sst/sst-filters include/sst/filters/FilterCoefficientMaker_Impl.h
      Coeff_SVF, Coeff_LP12, resoscale, Map2PoleResonance, clipscale,
      boundFreq, ToCoupledForm, ToNormalizedLattice, FromDirect (smooth=0.2,
      blockSizeInv=1/64), n_cm_coeffs = 8
  libs/sst/sst-filters include/sst/filters/QuadFilterUnit_Impl.h
      SVFLP12Aquad (st_Standard), IIR12CFCquad (st_Driven), IIR12Bquad
      (st_Clean); per-sample C[i] += dC[i] reload order and the clipgain
      register update position (state multiply uses the PREVIOUS clipgain)
  libs/sst/sst-filters include/sst/filters/QuadFilterUnit.h
      GetQFPtrFilterUnit -> LP12 subtype kernel table
  src/common/dsp/SurgeVoice.cpp
      cutoff_a = cut + keytrack*kt + feg*em (process_block), per-voice
      coefficient state, CM.Reset() + FBP.FU[u] memset on type/subtype
      change, and the per-voice FBP zero-init (R[2] starts at 0: the first
      OS sample of a voice seeds no state)

Arithmetic discipline (FROZEN, same as the landed voice model):
  * every value is a Python int in two's-complement Q10.21;
  * products are exact then rounded back round-half-up:
        r = (a*b + (1 << (s-1))) >> s,  s = fa+fb-fq
    and saturated to the signed 32-bit range;
  * divisions only at coefficient (block) rate via qdiv (round-half-up);
  * frequency-domain constructions are evaluated in double precision
    against the pinned formulas and quantized once (declared deviation:
    the engine evaluates float32/double mixes; within-budget class);
  * no floating point at run time (audio path is pure integer).
"""

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

# ----------------------------------------------------------- declared scope
SUBTYPE_STANDARD = 0   # st_Standard -> SVFLP12Aquad
SUBTYPE_DRIVEN = 1     # st_Driven   -> IIR12CFCquad
SUBTYPE_CLEAN = 2      # st_Clean    -> IIR12Bquad
SUBTYPES = (SUBTYPE_STANDARD, SUBTYPE_DRIVEN, SUBTYPE_CLEAN)

TYPE_LP12 = 1          # fut_lp12 (FilterType registry, pinned)
FUT_LP12 = TYPE_LP12

# Applicability boundary (fail-closed, enforced by LP12CoeffMaker):
#   resonance is a normalized [0, 1] parameter (cited parameter range);
#   cutoff is accepted over the engine-declared cutoff parameter span
#   [-240, +240] semitones (the param itself); CoeffMaker applies the
#   pinned boundFreq clamp [-55, +75] internally.  Values outside the
#   declared spans are REFUSED, never silently clamped, so that an
#   out-of-scope fixture fails loudly instead of producing unvetted audio.
RESO_MIN, RESO_MAX = 0.0, 1.0
CUT_SCOPE_MIN, CUT_SCOPE_MAX = -240.0, 240.0

N_COEF = 8             # n_cm_coeffs
COEF_SMOOTH = qint(0.2)                    # FilterCoefficientMaker smooth
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS           # 64 OS samples per engine block

# register-state init: the per-voice FBP is zeroed on voice creation and on
# type/subtype change (SurgeVoice.cpp memset paths); R[2] (clipgain state)
# therefore starts at 0, which seeds no state on the first OS sample.
R_CLIP_INIT = 0


class Refuse(Exception):
    """Applicability boundary: out-of-scope request, refused (fail-closed)."""


# ------------------------------------------------------- coefficient maker
def _note_to_pitch_d(x_semi):
    """note_to_pitch_ignoring_tuning body (double), x in semitones rel A440."""
    return 2.0 ** (x_semi / 12.0)


def _resoscale(reso, subtype):
    """pinned resoscale(): per-subtype output-gain scale, Q10.21."""
    if subtype == SUBTYPE_DRIVEN:
        return qint(1.0) - qmul(qmul(reso, reso), qint(0.5))
    if subtype == SUBTYPE_CLEAN:
        return qint(1.0) - qmul(qmul(reso, reso), qint(0.25))
    return qint(1.0)   # st_Standard (and any unused id): 1.0


def _map2pole_resonance(reso, freq, subtype):
    """pinned Map2PoleResonance() for the 2-pole types, Q10.21.

    reso/freq are Q10.21; returns Q10.21.  cl and (1-reso)^2 evaluated with
    the frozen op order (multiply then limit), matching the landed Driven
    path of the SXT-022 model and extending it per subtype.
    """
    if subtype == SUBTYPE_DRIVEN:
        atten = ONE - qmul(max(0, freq - qint(58.0)), qint(0.05))
        reso = qmul(reso, max(0, atten))
        t = ONE - qmul(ONE - reso, ONE - reso)
        t = limit_i(t, qint(0.001), ONE)
        return ONE - qmul(qint(1.05), t)
    if subtype == SUBTYPE_CLEAN:
        t = ONE - qmul(ONE - reso, ONE - reso)
        t = limit_i(t, 0, ONE)
        return qint(2.5) - qmul(qint(2.45), t)
    # st_Standard: Coeff_SVF does not call this (its own Q1 mapping below);
    # reaching here with Standard is an internal error.
    raise Refuse("Map2PoleResonance not defined for st_Standard")


def _clipscale(freq, subtype):
    """pinned clipscale(): clipgain coefficient, Q10.21."""
    if subtype == SUBTYPE_DRIVEN:
        return qdiv(vm.db_to_linear(qmul(freq, qint(0.55))), qint(64.0))
    if subtype == SUBTYPE_CLEAN:
        return qdiv(ONE, qint(1024.0))
    return 0


class LP12CoeffMaker:
    """FilterCoefficientMaker for fut_lp12, all three engine subtypes.

    FromDirect smoothing (tC += 0.2*(N - tC); dC = (tC - C)/64; FirstRun:
    C = tC = N, dC = 0) is shared by every subtype, exactly as in the
    pinned base class.  `reset()` mirrors CM.Reset() (type/subtype change
    or fresh voice): the next make_coeffs() takes the FirstRun path.
    """

    def __init__(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP12 set {SUBTYPES}")
        self.subtype = subtype
        self.C = [0] * N_COEF
        self.dC = [0] * N_COEF
        self.tC = [0] * N_COEF
        self.first_run = True

    def reset(self):
        self.first_run = True

    def make_coeffs(self, freq, reso):
        """makeCoeffs(freq, reso, fut_lp12, subtype); freq semitones rel A440."""
        if not (qint(CUT_SCOPE_MIN) <= freq <= qint(CUT_SCOPE_MAX)):
            raise Refuse(f"cutoff {freq / float(ONE):.3f} st outside the declared "
                         f"scope [{CUT_SCOPE_MIN}, {CUT_SCOPE_MAX}]")
        if not (qint(RESO_MIN) <= reso <= qint(RESO_MAX)):
            raise Refuse(f"resonance {reso / float(ONE):.4f} outside the declared "
                         f"scope [{RESO_MIN}, {RESO_MAX}]")
        if self.subtype == SUBTYPE_STANDARD:
            self._coeff_svf(freq / float(ONE), reso)
        else:
            self._coeff_lp12(freq, reso)

    # -- st_Standard: Coeff_SVF(Freq, Reso, FourPole=false) -----------------
    def _coeff_svf(self, freq_semi, reso):
        import math
        f = 440.0 * _note_to_pitch_d(freq_semi)
        f1 = 2.0 * math.sin(math.pi * min(0.11, f * (0.5 / 48000.0)))
        reso_d = max(0.0, min(1.0, reso / float(ONE))) ** 0.5
        overshoot = 0.15
        q1 = 2.0 - reso_d * (2.0 + overshoot) + f1 * f1 * overshoot * 0.9
        q1 = min(q1, min(2.00, 2.00 - 1.52 * f1))
        clip_damp = 0.1 * reso_d * f1
        gain = 1.0 - 0.65 * reso_d
        n = [0] * N_COEF
        n[0] = qint(f1)
        n[1] = qint(q1)
        n[2] = qint(clip_damp)
        n[3] = qint(gain)
        self._from_direct(n)

    # -- st_Driven / st_Clean: Coeff_LP12 ------------------------------------
    def _coeff_lp12(self, freq, reso):
        gain = _resoscale(reso, self.subtype)
        freq = limit_i(freq, qint(-55.0), qint(75.0))          # boundFreq
        sinu, cosi = vm.note_to_omega(freq)
        alpha = qmul(sinu, _map2pole_resonance(reso, freq, self.subtype))
        if self.subtype != SUBTYPE_CLEAN:
            # self-osc guard: alpha <= sqrt(1 - cosi^2) - 1e-4
            lim = qint(max(0.0, (1.0 - (cosi / float(ONE)) ** 2) ** 0.5) - 0.0001)
            alpha = min(alpha, lim)
        a0 = ONE + alpha
        a0inv = qdiv(ONE, a0)
        a1 = qmul(qint(-2.0), cosi)
        a2 = ONE - alpha
        b0h = (ONE - cosi) >> 1                                 # (1-cosi)*0.5
        b0 = qmul(b0h, gain)
        b1 = qmul(ONE - cosi, gain)
        b2 = b0
        cs = _clipscale(freq, self.subtype)
        if self.subtype == SUBTYPE_CLEAN:
            self._to_normalized_lattice(a0inv, a1, a2, b0, b1, b2, cs)
        else:
            self._to_coupled_form(a0inv, a1, a2, b0, b1, b2, cs)

    def _to_coupled_form(self, a0inv, a1, a2, b0, b1, b2, g):
        """pinned ToCoupledForm() with the frozen op order (SXT-022 order)."""
        b0 = qmul(b0, a0inv)
        b1 = qmul(b1, a0inv)
        b2 = qmul(b2, a0inv)
        a1 = qmul(a1, a0inv)
        a2 = qmul(a2, a0inv)
        ar = -(a1 >> 1)                                         # 0.5*-a1
        sq = min(0, a1 * a1 - ((4 * a2) << FQ))                 # Q(2*FQ) domain
        import math
        ai = qint(0.5 * math.sqrt(-sq / float(1 << (2 * FQ))))
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

    def _to_normalized_lattice(self, a0inv, a1, a2, b0, b1, b2, g):
        """pinned ToNormalizedLattice() (st_Clean coefficient form)."""
        b0 = qmul(b0, a0inv)
        b1 = qmul(b1, a0inv)
        b2 = qmul(b2, a0inv)
        a1 = qmul(a1, a0inv)
        a2 = qmul(a2, a0inv)
        k1 = qdiv(a1, ONE + a2)
        k2 = a2
        import math
        q1 = qint(math.sqrt(abs(1.0 - (k1 / float(ONE)) ** 2)))
        q2 = qint(math.sqrt(abs(1.0 - (k2 / float(ONE)) ** 2)))
        v3 = b2
        v2 = qdiv(b1 - qmul(a1, v3), q2)
        v1 = qdiv(b0 - qmul(qmul(k1, v2), q2) - qmul(k2, v3), qmul(q1, q2))
        n = [0] * N_COEF
        n[0] = k1
        n[1] = k2
        n[2] = q1
        n[3] = q2
        n[4] = v1
        n[5] = v2
        n[6] = v3
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


# ---------------------------------------------------------------- kernels
class LP12Unit:
    """One per-instance filter unit: registers + per-sample frozen schedule.

    Per-instance state is never shared: every voice/unit instance owns one
    LP12Unit (AGENTS.md state rule).  The per-sample C[i] += dC[i] reload,
    the kernel arithmetic and the clipgain register position follow the
    pinned QuadFilterUnit_Impl.h bodies cited in the module docstring.
    """

    def __init__(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP12 set {SUBTYPES}")
        self.subtype = subtype
        self.r0 = 0
        self.r1 = 0
        self.r_clip = R_CLIP_INIT
        self.qmul_count = 0

    def reset_state(self):
        """FBP.FU[u] memset path (voice creation / type or subtype change)."""
        self.r0 = 0
        self.r1 = 0
        self.r_clip = R_CLIP_INIT

    def set_subtype(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP12 set {SUBTYPES}")
        self.subtype = subtype
        self.reset_state()

    # -- per-sample kernels (Q10.21; frozen op order): see process_block ----
    def _iir12b(self, x, c):
        raise NotImplementedError("Clean kernel lives inline in process_block")

    # -- block processor ------------------------------------------------------
    def process_block(self, inp64, cm):
        """One 64-OS-sample block: per-sample C reload + kernel.

        cm: LP12CoeffMaker providing the block-start C (copied) and dC.
        Returns (outputs, per-block peak |state| for the monitor, the
        end-of-block coefficient word C[8] the RTL must hold).

        Driven reload order (pinned IIR12CFCquad): C[0,1,2,4,5,6] += dC
        BEFORE the sample, C[7] (clipgain) AFTER the state update.  Clean
        and Standard interleave their reloads exactly as pinned.
        """
        c = list(cm.C)
        dc = list(cm.dC)
        out = []
        peak = 0
        for x in inp64:
            if self.subtype == SUBTYPE_DRIVEN:
                for i in (0, 1, 2, 4, 5, 6):
                    c[i] = sat(c[i] + dc[i])
                y = qmul(c[4], self.r0) + qmul(c[6], x) + qmul(c[5], self.r1)
                s1 = qmul(x, c[2]) + qmul(c[0], self.r0) - qmul(c[1], self.r1)
                s2 = qmul(c[1], self.r0) + qmul(c[0], self.r1)
                self.r0 = qmul(s1, self.r_clip)
                self.r1 = qmul(s2, self.r_clip)
                c[7] = sat(c[7] + dc[7])
                self.r_clip = max(qint(0.1), ONE - qmul(c[7], qmul(y, y)))
            elif self.subtype == SUBTYPE_CLEAN:
                f2 = qmul(c[3], x) - qmul(c[1], self.r1)      # Q2*x - K2*R1
                c[1] = sat(c[1] + dc[1])                      # K2
                c[3] = sat(c[3] + dc[3])                      # Q2
                g2 = qmul(c[1], x) + qmul(c[3], self.r1)      # K2*x + Q2*R1
                f1 = qmul(c[2], f2) - qmul(c[0], self.r0)     # Q1*f2 - K1*R0
                c[0] = sat(c[0] + dc[0])                      # K1
                c[2] = sat(c[2] + dc[2])                      # Q1
                g1 = qmul(c[0], f2) + qmul(c[2], self.r0)     # K1*f2 + Q1*R0
                c[4] = sat(c[4] + dc[4])                      # V1
                c[5] = sat(c[5] + dc[5])                      # V2
                c[6] = sat(c[6] + dc[6])                      # V3
                y = qmul(c[6], g2) + qmul(c[5], g1) + qmul(c[4], f1)
                self.r0 = qmul(f1, self.r_clip)
                self.r1 = qmul(g1, self.r_clip)
                c[7] = sat(c[7] + dc[7])
                self.r_clip = max(qint(0.1), ONE - qmul(c[7], qmul(y, y)))
            else:   # SUBTYPE_STANDARD (pinned SVFLP12Aquad)
                c[0] = sat(c[0] + dc[0])                      # F1
                c[1] = sat(c[1] + dc[1])                      # Q1
                low = self.r1 + qmul(c[0], self.r0)
                high = x - low - qmul(c[1], self.r0)
                band = self.r0 + qmul(c[0], high)
                low2 = low + qmul(c[0], band)
                high2 = x - low2 - qmul(c[1], band)
                band2 = band + qmul(c[0], high2)
                self.r0 = qmul(band2, self.r_clip)
                self.r1 = qmul(low2, self.r_clip)
                c[2] = sat(c[2] + dc[2])                      # ClipDamp
                self.r_clip = max(qint(0.1), ONE - qmul(c[2], qmul(band, band)))
                c[3] = sat(c[3] + dc[3])                      # Gain
                y = qmul(low2, c[3])
            self.qmul_count += 8
            out.append(y)
            m = max(abs(y), abs(self.r0), abs(self.r1))
            if m > peak:
                peak = m
        return out, peak, c


# --------------------------------------------------------- stability monitor
def stability_verdict(peaks, growth_db_per_block=6.0, tail=16, floor=1 << 20,
                      sat_floor=1 << 30):
    """Post-hoc boundedness verdict over per-block state peaks (ints).

    Returns 'STABLE' when the peak envelope does not exhibit sustained
    exponential growth into the headroom floor; 'UNSTABLE' otherwise.
    Reaching the saturation neighborhood (>= sat_floor, the s32 bound) is
    UNSTABLE by definition: unbounded growth that hit the word limit is a
    recorded alarm, never a silent clamp.
    """
    if not peaks:
        return "STABLE"
    if max(peaks) >= sat_floor:
        return "UNSTABLE"
    if len(peaks) < tail:
        return "STABLE" if max(peaks) < (1 << 31) else "UNSTABLE"
    win = peaks[-tail:]
    if max(win) < floor:
        return "STABLE"
    import math
    rising = 0
    for a, b in zip(win, win[1:]):
        if b > a:
            rising += 1
    dB = math.log(max(win[-1], 1) / max(win[0], 1), 10) * 20.0
    if rising >= tail - 2 and dB > growth_db_per_block * (tail - 1):
        return "UNSTABLE"
    return "STABLE"
