#!/usr/bin/env python3
"""SXT-038 frozen fixed-point LP 24 dB filter model (all engine subtypes).

This module is the FROZEN reference for the SXT-038 filter leaf RTL
(`rtl/voice/tb_lp24.sv`).  RTL-vs-model agreement must be EXACT (integer
equality at every declared checkpoint; `tools/compare_rtl_model_lp24.py`).
Model-vs-pinned-code agreement is a SEPARATE claim governed by [PROPOSED]
error budgets (PENDING-FREEZE; SXT-013 owns the fidelity policy), measured
against the pinned filter submodule by `tools/compare_lp24_model.py`.

Word lengths and operation order are normative and documented in
`model/voice/filter_lp24/README.md`.  Sample/coefficient words are Q10.21
signed 32-bit — the same universal word as the landed SXT-022 voice model
(`model/voice/voice_model.py`, imported for its arithmetic helpers).

Structure is CITED from the pinned engine (read, never copied):
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71

  libs/sst/sst-filters@e92d93a9 include/sst/filters/FilterCoefficientMaker_Impl.h
      MakeCoeffs (fut_lp24 dispatch: st_Standard -> Coeff_SVF(FourPole=true),
      else Coeff_LP24), Coeff_LP24, Coeff_SVF, Map4PoleResonance, resoscale,
      clipscale, boundFreq, ToCoupledForm, ToNormalizedLattice, FromDirect
      (smooth = 0.2, blockSizeInv = 1/blockSize), db_to_linear (EXACT
      pow(10, 0.05 x) in sst-filters, not the Surge dB LUT), n_cm_coeffs = 8
  libs/sst/sst-filters@e92d93a9 include/sst/filters/QuadFilterUnit_Impl.h
      SVFLP24Aquad (st_Standard), IIR24CFCquad (st_Driven), IIR24Bquad
      (st_Clean); per-sample C[i] += dC[i] reload order, the two cascaded
      sections' register indices, and the clipgain register position
  libs/sst/sst-filters@e92d93a9 include/sst/filters/QuadFilterUnit.h
      GetQFPtrFilterUnit -> fut_lp24 subtype kernel table
  libs/sst/sst-filters@e92d93a9 include/sst/filters/FilterConfiguration.h
      fut_lp24 = 2; fut_subcount[fut_lp24] = 3; st_Standard/Driven/Clean
  src/common/dsp/SurgeVoice.cpp
      SetQFB(): cutoffA = cfa + kta*(state.pitch - keytrack_root) +
      emoda*filter-EG; CM[u].MakeCoeffs(...); CM[u].updateState(Q->FU[u], e)
      GetQFB(): FBP.FU[u].R[i] read-back and CM[u].C[i] copy-back
      sampleRateReset(): CM configured with (dsamplerate_os, BLOCK_SIZE_OS)
      = (96000, 64); CM[u].Reset() + FBP zero on type/subtype change
  src/common/SurgeStorage.cpp
      init_tables() construction formulas and note_to_pitch_ignoring_tuning /
      note_to_omega_ignoring_tuning lookup semantics (the engine's tuning
      provider; reproduced here by construction, no table payload copied)

Arithmetic discipline (FROZEN, same universal word as the landed models):
  * every value is a Python int in two's-complement Q10.21;
  * products are exact then rounded back round-half-up
        r = (a*b + (1 << (s-1))) >> s,  s = fa + fb - fq
    and saturated to the signed 32-bit range (`vm.qmul`);
  * every SUM in the audio path is saturated to signed 32-bit as well
    (`sadd`), so overflow behaviour is defined and the RTL can match it bit
    for bit (declared divergence from the pinned float path, which has no
    32-bit wrap and would instead grow toward inf);
  * divisions only at coefficient (block) rate via `vm.qdiv`
    (round-half-up);
  * coefficient-construction formulas are evaluated in double precision
    against the pinned bodies and quantized once (declared deviation: the
    engine evaluates a float32/double mix);
  * no floating point at run time — the audio path is pure integer.
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

# ----------------------------------------------------------- declared scope
SUBTYPE_STANDARD = 0   # st_Standard -> SVFLP24Aquad
SUBTYPE_DRIVEN = 1     # st_Driven   -> IIR24CFCquad
SUBTYPE_CLEAN = 2      # st_Clean    -> IIR24Bquad
SUBTYPES = (SUBTYPE_STANDARD, SUBTYPE_DRIVEN, SUBTYPE_CLEAN)

TYPE_LP24 = 2          # fut_lp24 (pinned FilterType registry)
FUT_LP24 = TYPE_LP24

# Applicability boundary (fail-closed, enforced by LP24CoeffMaker):
# resonance is the engine's normalized [0, 1] parameter; cutoff is accepted
# over the engine-declared cutoff parameter span [-240, +240] semitones.
# Coeff_LP24 applies the pinned boundFreq clamp [-55, +75] internally;
# Coeff_SVF (st_Standard) is NOT boundFreq-clamped at the pin and is left
# unclamped here too.  Values outside the declared spans are REFUSED, never
# silently clamped, so an out-of-scope fixture fails loudly.
RESO_MIN, RESO_MAX = 0.0, 1.0
CUT_SCOPE_MIN, CUT_SCOPE_MAX = -240.0, 240.0

N_COEF = 8                                  # n_cm_coeffs
N_REG = 5                                   # R[0..4] used by the LP24 kernels
COEF_SMOOTH = qint(0.2)                     # FilterCoefficientMaker `smooth`
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS            # 64 OS samples per engine block
SR_OS = 96000.0                             # dsamplerate_os (CM sample rate)

# Register initialization: the per-voice FBP is zeroed on voice creation and
# on a type/subtype change (SurgeVoice.cpp memset paths), clipgain register
# included -- so the first OS sample of an instance seeds no state.
R_INIT = [0] * N_REG

CLIP_FLOOR = qint(0.1)                      # pinned max(0.1, ...) clipgain floor


class Refuse(Exception):
    """Applicability boundary: out-of-scope request, refused (fail-closed)."""


def sadd(*terms):
    """Saturating signed-32 sum (frozen; the RTL implements the same)."""
    return sat(sum(terms))


# ------------------------------------------------ engine tuning-provider LUTs
# Constructed from the pinned SurgeStorage::init_tables() formulas.  The
# engine's tables are float32 and are looked up with linear interpolation on
# the integer-semitone grid; reproducing that here matters: at the top of the
# cutoff range linear interpolation of sin()/cos() differs from exact sin/cos
# by ~1e-3 (thousands of Q10.21 LSB), so an "exact" model would NOT be the
# engine.
def _f32(x):
    """Round a double to float32 (the engine stores these tables as float)."""
    import struct
    return struct.unpack("<f", struct.pack("<f", x))[0]


_TABLE = 512
_T_PITCH = [_f32(2.0 ** ((i - 256) / 12.0)) for i in range(_TABLE)]
_T_SIN = [_f32(math.sin(2 * math.pi * min(0.5, 440.0 * _T_PITCH[i] / SR_OS)))
          for i in range(_TABLE)]
_T_COS = [_f32(math.cos(2 * math.pi * min(0.5, 440.0 * _T_PITCH[i] / SR_OS)))
          for i in range(_TABLE)]
_T_TWO = [_f32(2.0 ** (i / 12.0 / 1000.0)) for i in range(1002)]


def note_to_pitch_ignoring_tuning_d(x_semi):
    """SurgeStorage::note_to_pitch_ignoring_tuning body (double result)."""
    x = min(max(x_semi + 256.0, 1.0e-4), _TABLE - 1.0e-4)
    e = int(x)
    a = x - e
    pow2pos = a * 1000.0
    pow2idx = int(pow2pos)
    pow2frac = pow2pos - pow2idx
    pow2v = (1 - pow2frac) * _T_TWO[pow2idx] + pow2frac * _T_TWO[pow2idx + 1]
    return _T_PITCH[e] * pow2v


def note_to_omega_d(x_semi):
    """SurgeStorage::note_to_omega_ignoring_tuning body -> (sinu, cosi)."""
    x = min(max(x_semi + 256.0, 0.0), _TABLE - 1.0e-4)
    e = int(x)
    a = x - e
    sinu = (1 - a) * _T_SIN[e] + a * _T_SIN[(e + 1) & 0x1FF]
    cosi = (1 - a) * _T_COS[e] + a * _T_COS[(e + 1) & 0x1FF]
    return sinu, cosi


def db_to_linear_d(x_db):
    """sst-filters db_to_linear: EXACT pow(10, 0.05*x) (not the Surge LUT)."""
    return 10.0 ** (0.05 * x_db)


# ------------------------------------------------------- coefficient helpers
def _resoscale_d(reso_d, subtype):
    """pinned resoscale() -- Coeff_LP24 uses the 2-pole variant at the pin."""
    if subtype == SUBTYPE_DRIVEN:
        return 1.0 - 0.5 * reso_d * reso_d
    if subtype == SUBTYPE_CLEAN:
        return 1.0 - 0.25 * reso_d * reso_d
    return 1.0


def _map4pole_resonance_d(reso_d, freq_d, subtype):
    """pinned Map4PoleResonance() for the 4-pole types."""
    if subtype == SUBTYPE_DRIVEN:
        reso_d = reso_d * max(0.0, 1.0 - max(0.0, (freq_d - 58.0) * 0.05))
        return 1.0 - 1.05 * min(max(reso_d, 0.001), 1.0)
    if subtype == SUBTYPE_CLEAN:
        return 2.5 - 2.3 * min(max(reso_d, 0.0), 1.0)
    raise Refuse("Map4PoleResonance is not reached for st_Standard (Coeff_SVF)")


def _clipscale_d(freq_d, subtype):
    """pinned clipscale()."""
    if subtype == SUBTYPE_DRIVEN:
        return (1.0 / 64.0) * db_to_linear_d(freq_d * 0.55)
    if subtype == SUBTYPE_CLEAN:
        return 1.0 / 1024.0
    return 0.0


class LP24CoeffMaker:
    """FilterCoefficientMaker for fut_lp24, all three engine subtypes.

    FromDirect smoothing (tC = (1-smooth)*tC + smooth*N; dC = (tC - C)*
    blockSizeInv; FirstRun: C = tC = N, dC = 0) is shared by every subtype,
    exactly as the pinned base class spells it.  `reset()` mirrors
    CM.Reset() (fresh voice / type or subtype change): the next
    make_coeffs() takes the FirstRun path.
    """

    def __init__(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP24 set {SUBTYPES}")
        self.subtype = subtype
        self.C = [0] * N_COEF
        self.dC = [0] * N_COEF
        self.tC = [0] * N_COEF
        self.first_run = True

    def reset(self):
        """CM.Reset(): zero the planes and take the FirstRun path next call."""
        self.C = [0] * N_COEF
        self.dC = [0] * N_COEF
        self.tC = [0] * N_COEF
        self.first_run = True

    def make_coeffs(self, freq, reso):
        """MakeCoeffs(freq, reso, fut_lp24, subtype); freq in semitones vs A440."""
        if not (qint(CUT_SCOPE_MIN) <= freq <= qint(CUT_SCOPE_MAX)):
            raise Refuse(f"cutoff {freq / float(ONE):.3f} st outside the declared "
                         f"scope [{CUT_SCOPE_MIN}, {CUT_SCOPE_MAX}]")
        if not (qint(RESO_MIN) <= reso <= qint(RESO_MAX)):
            raise Refuse(f"resonance {reso / float(ONE):.4f} outside the declared "
                         f"scope [{RESO_MIN}, {RESO_MAX}]")
        if self.subtype == SUBTYPE_STANDARD:
            self._coeff_svf(freq, reso)
        else:
            self._coeff_lp24(freq, reso)

    # -- st_Standard: Coeff_SVF(Freq, Reso, FourPole=true) -------------------
    def _coeff_svf(self, freq, reso):
        freq_d = freq / float(ONE)
        reso_d = reso / float(ONE)
        f = 440.0 * note_to_pitch_ignoring_tuning_d(freq_d)
        f1 = 2.0 * math.sin(math.pi * min(0.11, f * (0.5 / SR_OS)))
        r = math.sqrt(min(max(reso_d, 0.0), 1.0))
        overshoot = 0.1                          # FourPole
        q1 = 2.0 - r * (2.0 + overshoot) + f1 * f1 * overshoot * 0.9
        q1 = min(q1, min(2.00, 2.00 - 1.52 * f1))
        clip_damp = 0.1 * r * f1
        gain = 1.0 - 0.65 * r
        n = [0] * N_COEF
        n[0] = qint(f1)
        n[1] = qint(q1)
        n[2] = qint(clip_damp)
        n[3] = qint(gain)
        self._from_direct(n)

    # -- st_Driven / st_Clean: Coeff_LP24 ------------------------------------
    def _coeff_lp24(self, freq, reso):
        reso_d = reso / float(ONE)
        gain = _resoscale_d(reso_d, self.subtype)
        freq_d = min(max(freq / float(ONE), -55.0), 75.0)          # boundFreq
        sinu, cosi = note_to_omega_d(freq_d)
        alpha = sinu * _map4pole_resonance_d(reso_d, freq_d, self.subtype)
        if self.subtype != SUBTYPE_CLEAN:
            alpha = min(alpha, math.sqrt(max(0.0, 1.0 - cosi * cosi)) - 0.0001)
        a0inv = 1.0 / (1.0 + alpha)
        a1 = -2.0 * cosi
        a2 = 1.0 - alpha
        b0 = (1.0 - cosi) * 0.5
        b1 = 1.0 - cosi
        b2 = (1.0 - cosi) * 0.5
        g = _clipscale_d(freq_d, self.subtype)
        if self.subtype == SUBTYPE_CLEAN:
            self._to_normalized_lattice(a0inv, a1, a2, b0 * gain, b1 * gain, b2 * gain, g)
        else:
            self._to_coupled_form(a0inv, a1, a2, b0 * gain, b1 * gain, b2 * gain, g)

    def _to_coupled_form(self, a0inv, a1, a2, b0, b1, b2, g):
        """pinned ToCoupledForm() (double, quantized once at the boundary)."""
        b0 *= a0inv
        b1 *= a0inv
        b2 *= a0inv
        a1 *= a0inv
        a2 *= a0inv
        sq = min(0.0, a1 * a1 - 4.0 * a2)
        ar = 0.5 * -a1
        ai = max(0.5 * math.sqrt(-sq), 8.0 * 1.192092896e-07)
        bb1 = b1 - a1 * b0
        bb2 = b2 - a2 * b0
        n = [0] * N_COEF
        n[0] = qint(ar)
        n[1] = qint(ai)
        n[2] = ONE
        n[4] = qint(bb1)
        n[5] = qint((bb1 * ar + bb2) / ai)
        n[6] = qint(b0)
        n[7] = qint(g)
        self._from_direct(n)

    def _to_normalized_lattice(self, a0inv, a1, a2, b0, b1, b2, g):
        """pinned ToNormalizedLattice() (st_Clean coefficient form)."""
        b0 *= a0inv
        b1 *= a0inv
        b2 *= a0inv
        a1 *= a0inv
        a2 *= a0inv
        k1 = a1 / (1.0 + a2)
        k2 = a2
        q1 = math.sqrt(abs(1.0 - k1 * k1))
        q2 = math.sqrt(abs(1.0 - k2 * k2))
        v3 = b2
        v2 = (b1 - a1 * v3) / q2
        v1 = (b0 - k1 * v2 * q2 - k2 * v3) / (q1 * q2)
        n = [0] * N_COEF
        n[0] = qint(k1)
        n[1] = qint(k2)
        n[2] = qint(q1)
        n[3] = qint(q2)
        n[4] = qint(v1)
        n[5] = qint(v2)
        n[6] = qint(v3)
        n[7] = qint(g)
        self._from_direct(n)

    def _from_direct(self, n):
        """pinned FromDirect(): tC = (1-smooth)*tC + smooth*N; dC = (tC-C)/bs."""
        if self.first_run:
            self.dC = [0] * N_COEF
            self.C = list(n)
            self.tC = list(n)
            self.first_run = False
        else:
            for i in range(N_COEF):
                self.tC[i] = sadd(qmul(ONE - COEF_SMOOTH, self.tC[i]),
                                  qmul(COEF_SMOOTH, n[i]))
                self.dC[i] = qdiv(sadd(self.tC[i], -self.C[i]), BLOCK_SIZE_OS, fb=0)


# ---------------------------------------------------------------- kernels
class LP24Unit:
    """One per-instance filter unit: registers + the frozen per-sample schedule.

    Per-instance state is NEVER shared: every voice/unit instance owns one
    LP24Unit (AGENTS.md state rule).  Register indices mirror the pinned
    kernels exactly, including which R slot each subtype uses for clipgain:
    R[2] for SVFLP24Aquad/IIR24CFCquad, R[4] for IIR24Bquad.
    """

    def __init__(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP24 set {SUBTYPES}")
        self.subtype = subtype
        self.r = list(R_INIT)
        self.qmul_count = 0

    def reset_state(self):
        """FBP.FU[u] memset path (voice creation / type or subtype change)."""
        self.r = list(R_INIT)

    def set_subtype(self, subtype):
        if subtype not in SUBTYPES:
            raise Refuse(f"subtype {subtype} outside the declared LP24 set {SUBTYPES}")
        self.subtype = subtype
        self.reset_state()

    def process_block(self, inp, cm):
        """One block of len(inp) OS samples: per-sample C reload + kernel.

        `cm` supplies the block-start C (copied) and dC.  Returns
        (outputs, per-block peak |state|, the advanced coefficient word C[8]
        that the voice path copies back into the coefficient maker).
        """
        c = list(cm.C)
        dc = list(cm.dC)
        r = self.r
        out = []
        peak = 0
        sub = self.subtype
        for x in inp:
            if sub == SUBTYPE_DRIVEN:
                # IIR24CFCquad: two cascaded coupled-form sections sharing
                # one coefficient set and one clipgain register (R[2]).
                for i in (0, 1, 2, 4, 5, 6):
                    c[i] = sadd(c[i], dc[i])
                y = sadd(qmul(c[4], r[0]), qmul(c[6], x), qmul(c[5], r[1]))
                s1 = sadd(qmul(x, c[2]), qmul(c[0], r[0]), -qmul(c[1], r[1]))
                s2 = sadd(qmul(c[1], r[0]), qmul(c[0], r[1]))
                r[0] = qmul(s1, r[2])
                r[1] = qmul(s2, r[2])
                y2 = sadd(qmul(c[4], r[3]), qmul(c[6], y), qmul(c[5], r[4]))
                s3 = sadd(qmul(y, c[2]), qmul(c[0], r[3]), -qmul(c[1], r[4]))
                s4 = sadd(qmul(c[1], r[3]), qmul(c[0], r[4]))
                r[3] = qmul(s3, r[2])
                r[4] = qmul(s4, r[2])
                c[7] = sadd(c[7], dc[7])
                r[2] = max(CLIP_FLOOR, sadd(ONE, -qmul(c[7], qmul(y2, y2))))
                yout = y2
                self.qmul_count += 22
            elif sub == SUBTYPE_CLEAN:
                # IIR24Bquad: two cascaded normalized-lattice sections; the
                # clipgain register is R[4] and BOTH sections multiply by its
                # PREVIOUS value.
                for i in (1, 3, 0, 2, 4, 5, 6):
                    c[i] = sadd(c[i], dc[i])
                f2 = sadd(qmul(c[3], x), -qmul(c[1], r[1]))
                g2 = sadd(qmul(c[1], x), qmul(c[3], r[1]))
                f1 = sadd(qmul(c[2], f2), -qmul(c[0], r[0]))
                g1 = sadd(qmul(c[0], f2), qmul(c[2], r[0]))
                r[0] = qmul(f1, r[4])
                r[1] = qmul(g1, r[4])
                y1 = sadd(qmul(c[6], g2), qmul(c[5], g1), qmul(c[4], f1))
                f2 = sadd(qmul(c[3], y1), -qmul(c[1], r[3]))
                g2 = sadd(qmul(c[1], y1), qmul(c[3], r[3]))
                f1 = sadd(qmul(c[2], f2), -qmul(c[0], r[2]))
                g1 = sadd(qmul(c[0], f2), qmul(c[2], r[2]))
                r[2] = qmul(f1, r[4])
                r[3] = qmul(g1, r[4])
                y2 = sadd(qmul(c[6], g2), qmul(c[5], g1), qmul(c[4], f1))
                c[7] = sadd(c[7], dc[7])
                r[4] = max(CLIP_FLOOR, sadd(ONE, -qmul(c[7], qmul(y2, y2))))
                yout = y2
                self.qmul_count += 28
            else:
                # SVFLP24Aquad: two cascaded zero-delay-feedback SVF sections;
                # the clipgain register is R[2] and is updated from the SECOND
                # section's band signal.
                c[0] = sadd(c[0], dc[0])
                c[1] = sadd(c[1], dc[1])
                low = sadd(r[1], qmul(c[0], r[0]))
                high = sadd(x, -low, -qmul(c[1], r[0]))
                band = sadd(r[0], qmul(c[0], high))
                low = sadd(low, qmul(c[0], band))
                high = sadd(x, -low, -qmul(c[1], band))
                band = sadd(band, qmul(c[0], high))
                r[0] = qmul(band, r[2])
                r[1] = qmul(low, r[2])
                xin = low
                low = sadd(r[4], qmul(c[0], r[3]))
                high = sadd(xin, -low, -qmul(c[1], r[3]))
                band = sadd(r[3], qmul(c[0], high))
                low = sadd(low, qmul(c[0], band))
                high = sadd(xin, -low, -qmul(c[1], band))
                band = sadd(band, qmul(c[0], high))
                r[3] = qmul(band, r[2])
                r[4] = qmul(low, r[2])
                c[2] = sadd(c[2], dc[2])
                r[2] = max(CLIP_FLOOR, sadd(ONE, -qmul(c[2], qmul(band, band))))
                c[3] = sadd(c[3], dc[3])
                yout = qmul(low, c[3])
                self.qmul_count += 19
            out.append(yout)
            m = max(abs(yout), abs(r[0]), abs(r[1]), abs(r[3]), abs(r[4]))
            if m > peak:
                peak = m
        self.r = r
        return out, peak, c


# --------------------------------------------------------- stability monitor
def stability_verdict(peaks, growth_db_per_block=6.0, tail=16, floor=1 << 20,
                      sat_floor=1 << 30):
    """Post-hoc boundedness verdict over per-block state peaks (ints).

    Returns 'STABLE' when the peak envelope does not exhibit sustained
    exponential growth into the headroom floor; 'UNSTABLE' otherwise.
    Reaching the saturation neighbourhood (>= sat_floor) is UNSTABLE by
    definition: growth that hit the word limit is a recorded alarm, never a
    silent clamp.
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
    rising = sum(1 for a, b in zip(win, win[1:]) if b > a)
    db = math.log10(max(win[-1], 1) / max(win[0], 1)) * 20.0
    if rising >= tail - 2 and db > growth_db_per_block * (tail - 1):
        return "UNSTABLE"
    return "STABLE"
