#!/usr/bin/env python3
"""SXT-028a: frozen fixed-point model of the Airwindows "Galactic" algorithm
(streamed Airwindows algorithm id 49).

Issue #53 (SXT-028a) · parent #21 (SXT-028) · plan section 6.

This module is the FROZEN integer model that the RTL-vs-model EXACTNESS claim
references (`rtl/effects/aw-49/`, `tools/compare_rtl_model_aw49.py`). The
model-vs-pinned-engine agreement is a SEPARATE claim governed by [PROPOSED]
error budgets (reports/sxt-028a/EVIDENCE.md, PENDING-FREEZE via #12).

Provenance / licensing (AGENTS.md; decision-records pattern 0003)
---------------------------------------------------------------
STRUCTURE ONLY is read and cited - never copied - from the pinned external
GPL-3.0-or-later tree:

* `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
  `libs/airwindows/src/GalacticProc.cpp` + `Galactic.h`
  (`processReplacing`, constructor state init; Airwindows, (c) 2016),
* `libs/airwindows/src/AirWinBaseClass_pluginRegistry.cpp` line
  `reg.emplace_back(create<Galactic::Galactic>, id++, 227, gnAmbience,
  "Galactic")` - the streamed id 49 used by Surge's `AirWindowsEffect`
  adapter (`src/common/dsp/effects/airwindows/AirWindowsEffect.{h,cpp}`),
* the shared adapter's sub-block param-lag path (declared control plane,
  see "Deviations").

The twelve delay-length multipliers below are opaque designed integers with
no construction formula in the pinned tree (the DR-0003 class): they are
quoted as data with file-level provenance and a license decision record
(decision-records/0006, PROPOSED). Every other coefficient is re-derived
from the cited formulas at run time.

Frozen scope (fail-closed)
--------------------------
* Sample rate frozen at 48 kHz: overallscale = (1.0/44100.0)*48000.0,
  cycleEnd = floor(overallscale) = 1, i.e. the reverb core runs on EVERY
  sample and the lastRef interpolation tree degenerates to lastRef[0]
  (the cycleEnd 2/3/4 branches are NOT modeled; any other rate raises).
* Static patch parameters: the adapter's float param-lag ramp is declared
  control-plane at its converged target (the ~36 ms post-load transient is
  outside the frozen model, covered by the render settle policy).
* Parameter modulation into FX params: not modeled (fail-closed) - none of
  the fixture presets routes modulation into Airwindows params.
* The float denormal flush (`fabs(iir)<1.18e-37`) is a no-op here: all
  states are integers.

Frozen word formats (model/effects/reverb1/README.md conventions)
----------------------------------------------------------------
* s32i  Q6.25 in 32-bit containers - audio, delay lines, filter/feedback
  states (sign + 5 headroom integer bits; headroom is justified
  empirically, see reports/sxt-028a/artifacts/headroom.json)
* c31   Q1.31 - regen, lowpass, (1-lowpass), wet, (1-wet), vibrato
        interpolation fraction
* c30   Q2.30 - attenuate (range +/-1.333)
* control stream words: per sample per channel the vibrato read base
  (integer) and fraction (c31)
Arithmetic: exact integer products, round-half-up `(x + 2^(f-1)) >>> f`,
saturating stores; no floating point in the audio path. Double precision
only at control rate (coefficient build + the vibrato phase stream), each
value quantized once at its declared boundary.

Control-plane boundary (model -> RTL)
-------------------------------------
Streamed per block by the runners, one word per line:
  * coefficient words (regen, attenuate, lowpass, wet, 12 delay lengths,
    flags), and
  * the per-sample vibrato read positions (base, fracq) for L and R - the
    vibrato phase `vibM` is a control-plane accumulator exactly like the
    Delay leaf's lfophase/LFOval (model/effects/README.md). `vibM` evolves
    from the constructor-time random seed pair (fpdL, fpdR) that the pinned
    engine draws from the C `rand()` stream seeded by
    `srand((unsigned)time(nullptr))` (SurgeSynthesizer.cpp constructor);
    the pair is therefore a CAPTURED control-plane input (oracle tap,
    decision-records/0006), not a derivable parameter.

External memory (per instance; never flash)
-------------------------------------------
One flat 126,354-word (32-bit) writable region, instance-relative base
address `mem_base`:
  24 delay lines (12 per channel) at the pinned Airwindows array sizes +
  two 257-word vibrato predelay lines (aML/aMR; the pinned 3111-word
  arrays use only indices 0..256 because delayM = 256).
Traffic: per output frame (48 kHz, cycleEnd=1) 28 reads + 26 writes =
54 words = 216 B/frame/instance (10.368 MB/s); see buffer_report().
"""


import hashlib
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

# --------------------------------------------------------------------------
# Frozen constants
# --------------------------------------------------------------------------

SAMPLE_RATE = 48000
BLOCK = 32

S32_MIN = -(1 << 31)
S32_MAX = (1 << 31) - 1
FRAC_S32I = 25          # Q6.25 (headroom: measured internal peaks reach
                         # beyond +/-8 at hot send gains, see README)
FRAC_C31 = 31
FRAC_C30 = 30

# Quoted designed constants (pinned GalacticProc.cpp processReplacing;
# GPL-3.0-or-later; decision-records/0006): delay lengths scale with
# `size = (D*1.77)+0.1` and truncate to int.
DELAY_MULT = {  # line -> (array_size, multiplier)
    "I": (6480, 3407.0),
    "J": (3660, 1823.0),
    "K": (1720, 859.0),
    "L": (680, 331.0),
    "A": (9700, 4801.0),
    "B": (6000, 2909.0),
    "C": (2320, 1153.0),
    "D": (940, 461.0),
    "E": (15220, 7607.0),
    "F": (8460, 4217.0),
    "G": (4540, 2269.0),
    "H": (3200, 1597.0),
}
STAGE1 = ["I", "J", "K", "L"]
STAGE2 = ["A", "B", "C", "D"]
STAGE3 = ["E", "F", "G", "H"]
DELAY_M = 256                        # pinned: delayM = 256 (vibrato line)
AM_WORDS = DELAY_M + 1               # used words of each aML/aMR array

TWO_PI = 2.0 * 3.141592653589793238
OLD_FPD0 = 429496.7295               # pinned oldfpd constructor value
OLD_FPD_SCALE = 0.0000000000618      # pinned wrap: oldfpd = 0.4294967295 + fpdL*scale

# External-memory layout, instance-relative (words)
REGIONS = []  # (name, base, words) built below
_base = 0
for _half in ("L", "R"):
    for _n in STAGE1 + STAGE2 + STAGE3:
        _w = DELAY_MULT[_n][0]
        REGIONS.append((f"a{_n}{_half}", _base, _w))
        _base += _w
REGIONS.append(("aML", _base, AM_WORDS)); _base += AM_WORDS
REGIONS.append(("aMR", _base, AM_WORDS)); _base += AM_WORDS
EXT_WORDS = _base                     # 126,354 words per instance
REGION_BASE = {name: base for name, base, _w in REGIONS}


def frozen_revision():
    """SHA-256 of this file's bytes (the frozen-model revision the RTL
    harness pins; a stale harness must refuse to report PASS)."""
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# --------------------------------------------------------------------------
# Fixed-point helpers (round-half-up, saturating; qmath.py conventions)
# --------------------------------------------------------------------------

def sat32(x):
    if x > S32_MAX:
        return S32_MAX
    if x < S32_MIN:
        return S32_MIN
    return x


def rnd(x, f):
    """(x + 2^(f-1)) >>> f, arithmetic (floor) shift - mirrors SV >>>."""
    return (x + (1 << (f - 1))) >> f


def rnd_sat32(x, f):
    return sat32(rnd(x, f))


def to_c31(x):
    v = int(x * (1 << FRAC_C31) + 0.5) if x >= 0 else \
        -int(-x * (1 << FRAC_C31) + 0.5)
    return sat32(v)


def to_c30(x):
    v = int(x * (1 << FRAC_C30) + 0.5) if x >= 0 else \
        -int(-x * (1 << FRAC_C30) + 0.5)
    return sat32(v)


def f32_to_s32i(x):
    """float32 -> Q6.25 (round-half-up); exact for |x| >= 2^-1, <= 1 LSB
    error below (declared input-boundary quantization)."""
    v = x * float(1 << FRAC_S32I)
    return sat32(int(v + 0.5) if v >= 0 else -int(-v + 0.5))


def s32i_to_f32(v):
    """Q6.25 -> float32, round-to-nearest-even (the engine's double->float
    output store)."""
    import numpy as np
    return float(np.float32(v * 2.0 ** -FRAC_S32I))


# --------------------------------------------------------------------------
# Control plane (double precision, quantized once at the declared boundary)
# --------------------------------------------------------------------------

def build_control(params, fpd):
    """Coefficient plane + vibrato stream inputs.

    params: dict with float keys a, b, c, d, e (the engine's post-lag float32
        parameter values, read back from the engine at load).
    fpd: dict {"fpdL": uint32, "fpdR": uint32} - the captured constructor
        random seeds (oracle tap; DR-0006). The vibrato wrap re-draws
        oldfpd from fpdL only (pinned source); fpdR is captured for
        completeness/verification.
    """
    a = float(np_f32(params["a"]))
    b = float(np_f32(params["b"]))
    c = float(np_f32(params["c"]))
    d = float(np_f32(params["d"]))
    e = float(np_f32(params["e"]))

    overallscale = (1.0 / 44100.0) * float(SAMPLE_RATE)
    cycle_end = int(math.floor(overallscale))
    if cycle_end < 1:
        cycle_end = 1
    if cycle_end > 4:
        cycle_end = 4
    if cycle_end != 1:
        raise NotImplementedError(
            f"frozen scope is 48 kHz (cycleEnd=1); got {cycle_end} - "
            "refusing (fail-closed)")

    regen = 0.0625 + ((1.0 - a) * 0.0625)
    attenuate = (1.0 - (regen / 0.125)) * 1.333
    lowpass = math.pow(1.00001 - (1.0 - b), 2.0) / math.sqrt(overallscale)
    drift = math.pow(c, 3) * 0.001
    size = (d * 1.77) + 0.1
    wet = 1.0 - (math.pow(1.0 - e, 3))

    delays = {}
    for n, (_arr, mult) in DELAY_MULT.items():
        delays[n] = int(mult * size)      # pinned double->int truncation
        if delays[n] + 1 > _arr:
            raise ValueError(f"delay {n} length {delays[n]} exceeds array")

    fpdL = int(fpd["fpdL"]) & 0xFFFFFFFF
    fpdR = int(fpd["fpdR"]) & 0xFFFFFFFF

    return {
        "params_f32": {"a": a, "b": b, "c": c, "d": d, "e": e},
        "overallscale": overallscale,
        "cycle_end": cycle_end,
        "regen_d": regen, "attenuate_d": attenuate, "lowpass_d": lowpass,
        "drift_d": drift, "size_d": size, "wet_d": wet,
        "regen": to_c31(regen),
        "attenuate": to_c30(attenuate),
        "lowpass": to_c31(lowpass),
        "lowpass_m1": (1 << FRAC_C31) - to_c31(lowpass),
        "wet_active": wet < 1.0,
        "wet": to_c31(wet),
        "wet_m1": (1 << FRAC_C31) - to_c31(wet),
        "delays": delays,
        "fpdL": fpdL, "fpdR": fpdR,
        "oldfpd0": OLD_FPD0,
    }


def np_f32(x):
    import numpy as np
    return float(np.float32(x))


class VibratoStream:
    """Per-sample control-plane vibrato positions.

    Mirrors the pinned order: vibM advance/wrap happens once per sample
    BEFORE the aML/aMR writes; the wrap re-draws oldfpd from fpdL. The
    quantized (base, frac) pair per channel is the frozen control word pair
    the RTL consumes; the doubles are bit-reproduced here (same libm on the
    oracle host; cross-platform libm variance is a declared deviation).
    """

    def __init__(self, ctrl):
        self.vibM = 3.0                      # pinned constructor value
        self.oldfpd = OLD_FPD0
        self.drift = ctrl["drift_d"]
        self.fpdL = ctrl["fpdL"]

    def advance(self):
        self.vibM += (self.oldfpd * self.drift)
        if self.vibM > TWO_PI:
            self.vibM = 0.0
            self.oldfpd = 0.4294967295 + (self.fpdL * OLD_FPD_SCALE)

    def positions(self):
        """(baseL, fracqL, baseR, fracqR) quantized for the RTL; the double
        offsets are the pinned (sin(vibM)+1)*127 pair with the R channel in
        quadrature (+pi/2)."""
        offL = (math.sin(self.vibM) + 1.0) * 127
        offR = (math.sin(self.vibM + (3.141592653589793238 / 2.0)) + 1.0) * 127
        baseL = int(offL)
        baseR = int(offR)
        fracL = offL - baseL
        fracR = offR - baseR
        return baseL, to_c31(fracL), baseR, to_c31(fracR)


# --------------------------------------------------------------------------
# Frozen fixed-point model
# --------------------------------------------------------------------------

class TappedVibratoStream(VibratoStream):
    """Vibrato phase consumed from a captured control-plane trajectory.

    The engine's vibM advance uses the adapter's LAGGED float parameter
    (OnePoleLag ramping from 0 at load), so the early trajectory is NOT
    derivable from static patch parameters. The frozen control-plane
    boundary therefore consumes the per-sample vibM doubles captured by the
    oracle tap (decision-records/0006); sin() is evaluated in-model on the
    identical inputs (same platform libm on the oracle host).
    """

    def __init__(self, ctrl, vibM):
        if ctrl is not None:
            super().__init__(ctrl)
        import numpy as np
        self.traj = [float(v) for v in np.asarray(vibM).ravel()]
        self.k = 0

    def advance(self):
        self.vibM = self.traj[self.k]
        self.k += 1


class Galactic49Fixed:
    """One Galactic instance (independent histories; two slots = two
    instances with separate memory regions behind mem_base)."""

    instance_kind = "aw-49"

    def __init__(self, ctrl, mem_base=0, assert_width=True, label="aw49",
                 vib=None, record=False, wide=False):
        self.c = ctrl
        self.mem_base = mem_base
        self.assert_width = assert_width
        self.label = label
        self._vib_override = vib
        self.wide = wide
        self.peak_state = 0
        self.log_ctrl = None  # list to append per-sample control words to
        self.hist = {"iir_a": [], "fb_AR": []} if record else None
        self.ext_reads = 0
        self.ext_writes = 0
        self.saturations = 0
        self._ext_read_fn = None
        self._ext_write_fn = None
        self.mem = [0] * EXT_WORDS
        self.reset()

    # ---------------------------------------------------------------- state
    def reset(self):
        """Constructor state (pinned Galactic() init; all-zero histories,
        counters start at 1, cycle 0, vibM 3.0, oldfpd 429496.7295)."""
        for i in range(EXT_WORDS):
            self.mem[i] = 0
        self.counts = {n: 1 for n in
                       STAGE1 + STAGE2 + STAGE3 + ["M"]}
        self.cycle = 0
        self.iir_a = {"L": 0, "R": 0}
        self.iir_b = {"L": 0, "R": 0}
        self.fb = {"AL": 0, "BL": 0, "CL": 0, "DL": 0,
                   "AR": 0, "BR": 0, "CR": 0, "DR": 0}
        self.vib = self._vib_override if self._vib_override is not None \
            else VibratoStream(self.c)
        self.ext_reads = 0
        self.ext_writes = 0
        self.saturations = 0

    def attach_ext_memory(self, read_fn, write_fn):
        """Transaction-accurate hooks: read_fn(abs_addr) -> int,
        write_fn(abs_addr, value)."""
        self._ext_read_fn = read_fn
        self._ext_write_fn = write_fn

    def _clip(self, v):
        if self.wide:
            a = v if v >= 0 else -v
            if a > self.peak_state:
                self.peak_state = a
            return v
        return sat32(v)

    def _rd(self, region, off):
        addr = self.mem_base + REGION_BASE[region] + off
        self.ext_reads += 1
        if self._ext_read_fn is not None:
            return self._ext_read_fn(addr)
        return self.mem[addr - self.mem_base]

    def _wr(self, region, off, val):
        if self.assert_width and not (S32_MIN <= val <= S32_MAX):
            self.saturations += 1
        val = self._clip(val)
        addr = self.mem_base + REGION_BASE[region] + off
        self.ext_writes += 1
        if self._ext_write_fn is not None:
            self._ext_write_fn(addr, val)
        else:
            self.mem[addr - self.mem_base] = val

    # ---------------------------------------------------------------- core
    def _advance(self, line):
        """count++ (wrap at > delay) - ONE increment per line pair per
        sample: the pinned counters are shared across channels
        ("all these ints are shared across channels, not duplicated")."""
        delay = self.c["delays"][line]
        c = self.counts[line] + 1
        if c > delay:
            c = 0
        self.counts[line] = c
        # pinned read-back: idx = count - ((count > delay) ? delay+1 : 0);
        # count never exceeds delay after the wrap, so idx == count
        return c

    def process_block(self, in_l, in_r):
        """One 32-sample block of s32i words -> (out_l, out_r) s32i."""
        c = self.c
        out_l = []
        out_r = []
        for k in range(BLOCK):
            ol, orr = self._sample(in_l[k], in_r[k])
            out_l.append(ol)
            out_r.append(orr)
        return out_l, out_r

    def _sample(self, in_l, in_r):
        c = self.c
        dry_l, dry_r = in_l, in_r

        # ---- control plane: vibrato advance (once per sample, before the
        # aML/aMR writes, pinned order)
        self.vib.advance()
        baseL, fracL, baseR, fracR = self.vib.positions()
        if self.log_ctrl is not None:
            self.log_ctrl.append((baseL, fracL, baseR, fracR))
        rs = (lambda v, f: v) if self.wide else rnd_sat32
        cl = (lambda v: v) if self.wide else sat32

        # ---- vibrato predelay: aML/aMR writes (pinned order L then R)
        self._wr("aML", self.counts["M"],
                 rs(c["attenuate"] * in_l, FRAC_C30))
        self._wr("aMR", self.counts["M"],
                 rs(c["attenuate"] * in_r, FRAC_C30))
        cm = self.counts["M"] + 1
        if cm > DELAY_M:
            cm = 0
        self.counts["M"] = cm

        # ---- vibrato reads: two taps per channel + one-rounding interp
        def interp(prefix, base, fracq):
            w0 = base
            i0 = cm + w0 - ((cm + w0) > DELAY_M and (DELAY_M + 1) or 0)
            i1 = cm + w0 + 1 - ((cm + w0 + 1) > DELAY_M and (DELAY_M + 1) or 0)
            a0 = self._rd(prefix, i0)
            a1 = self._rd(prefix, i1)
            w1 = (1 << FRAC_C31) - fracq
            return rs(a0 * w1 + a1 * fracq, FRAC_C31)

        x_l = interp("aML", baseL, fracL)
        x_r = interp("aMR", baseR, fracR)

        # ---- input one-pole lowpass (iirA)
        self.iir_a["L"] = y = rs(
            self.iir_a["L"] * c["lowpass_m1"] + x_l * c["lowpass"],
            FRAC_C31)
        x_l = y
        self.iir_a["R"] = y = rs(
            self.iir_a["R"] * c["lowpass_m1"] + x_r * c["lowpass"],
            FRAC_C31)
        x_r = y

        # ---- reverb core (cycleEnd == 1: every sample; pinned order)
        regen = c["regen"]
        # stage-1 line writes (L lines first, pinned) + advance + reads
        self._wr("aIL", self.counts["I"],
                 cl(x_l + rs(self.fb["AR"] * regen, FRAC_C31)))
        self._wr("aJL", self.counts["J"],
                 cl(x_l + rs(self.fb["BR"] * regen, FRAC_C31)))
        self._wr("aKL", self.counts["K"],
                 cl(x_l + rs(self.fb["CR"] * regen, FRAC_C31)))
        self._wr("aLL", self.counts["L"],
                 cl(x_l + rs(self.fb["DR"] * regen, FRAC_C31)))
        self._wr("aIR", self.counts["I"],
                 cl(x_r + rs(self.fb["AL"] * regen, FRAC_C31)))
        self._wr("aJR", self.counts["J"],
                 cl(x_r + rs(self.fb["BL"] * regen, FRAC_C31)))
        self._wr("aKR", self.counts["K"],
                 cl(x_r + rs(self.fb["CL"] * regen, FRAC_C31)))
        self._wr("aLR", self.counts["L"],
                 cl(x_r + rs(self.fb["DL"] * regen, FRAC_C31)))
        # one shared counter advance per line pair, then both channel reads
        # at the same index (pinned order: L lines then R lines)
        iI = self._advance("I")
        iJ = self._advance("J")
        iK = self._advance("K")
        iL = self._advance("L")
        out_i_l = self._rd("aIL", iI)
        out_j_l = self._rd("aJL", iJ)
        out_k_l = self._rd("aKL", iK)
        out_l_l = self._rd("aLL", iL)
        out_i_r = self._rd("aIR", iI)
        out_j_r = self._rd("aJR", iJ)
        out_k_r = self._rd("aKR", iK)
        out_l_r = self._rd("aLR", iL)

        # stage-2 writes (exact Hadamard-row sums, saturated at store)
        self._wr("aAL", self.counts["A"],
                 cl(out_i_l - (out_j_l + out_k_l + out_l_l)))
        self._wr("aBL", self.counts["B"],
                 cl(out_j_l - (out_i_l + out_k_l + out_l_l)))
        self._wr("aCL", self.counts["C"],
                 cl(out_k_l - (out_i_l + out_j_l + out_l_l)))
        self._wr("aDL", self.counts["D"],
                 cl(out_l_l - (out_i_l + out_j_l + out_k_l)))
        self._wr("aAR", self.counts["A"],
                 cl(out_i_r - (out_j_r + out_k_r + out_l_r)))
        self._wr("aBR", self.counts["B"],
                 cl(out_j_r - (out_i_r + out_k_r + out_l_r)))
        self._wr("aCR", self.counts["C"],
                 cl(out_k_r - (out_i_r + out_j_r + out_l_r)))
        self._wr("aDR", self.counts["D"],
                 cl(out_l_r - (out_i_r + out_j_r + out_k_r)))
        iA = self._advance("A")
        iB = self._advance("B")
        iC = self._advance("C")
        iD = self._advance("D")
        out_a_l = self._rd("aAL", iA)
        out_b_l = self._rd("aBL", iB)
        out_c_l = self._rd("aCL", iC)
        out_d_l = self._rd("aDL", iD)
        out_a_r = self._rd("aAR", iA)
        out_b_r = self._rd("aBR", iB)
        out_c_r = self._rd("aCR", iC)
        out_d_r = self._rd("aDR", iD)

        # stage-3 writes + reads
        self._wr("aEL", self.counts["E"],
                 cl(out_a_l - (out_b_l + out_c_l + out_d_l)))
        self._wr("aFL", self.counts["F"],
                 cl(out_b_l - (out_a_l + out_c_l + out_d_l)))
        self._wr("aGL", self.counts["G"],
                 cl(out_c_l - (out_a_l + out_b_l + out_d_l)))
        self._wr("aHL", self.counts["H"],
                 cl(out_d_l - (out_a_l + out_b_l + out_c_l)))
        self._wr("aER", self.counts["E"],
                 cl(out_a_r - (out_b_r + out_c_r + out_d_r)))
        self._wr("aFR", self.counts["F"],
                 cl(out_b_r - (out_a_r + out_c_r + out_d_r)))
        self._wr("aGR", self.counts["G"],
                 cl(out_c_r - (out_a_r + out_b_r + out_d_r)))
        self._wr("aHR", self.counts["H"],
                 cl(out_d_r - (out_a_r + out_b_r + out_c_r)))
        iE = self._advance("E")
        iF = self._advance("F")
        iG = self._advance("G")
        iH = self._advance("H")
        out_e_l = self._rd("aEL", iE)
        out_f_l = self._rd("aFL", iF)
        out_g_l = self._rd("aGL", iG)
        out_h_l = self._rd("aHL", iH)
        out_e_r = self._rd("aER", iE)
        out_f_r = self._rd("aFR", iF)
        out_g_r = self._rd("aGR", iG)
        out_h_r = self._rd("aHR", iH)

        # feedback registers (never stored to memory)
        def _fb(k, v):
            if not (S32_MIN <= v <= S32_MAX):
                self.saturations += 1
            self.fb[k] = self._clip(v)

        _fb("AL", out_e_l - (out_f_l + out_g_l + out_h_l))
        _fb("BL", out_f_l - (out_e_l + out_g_l + out_h_l))
        _fb("CL", out_g_l - (out_e_l + out_f_l + out_h_l))
        _fb("DL", out_h_l - (out_e_l + out_f_l + out_g_l))
        _fb("AR", out_e_r - (out_f_r + out_g_r + out_h_r))
        _fb("BR", out_f_r - (out_e_r + out_g_r + out_h_r))
        _fb("CR", out_g_r - (out_e_r + out_f_r + out_h_r))
        _fb("DR", out_h_r - (out_e_r + out_f_r + out_g_r))

        # final combined sum (exact /8 -> arithmetic shift)
        core_l = (out_e_l + out_f_l + out_g_l + out_h_l) >> 3
        core_r = (out_e_r + out_f_r + out_g_r + out_h_r) >> 3

        # cycleEnd == 1: lastRef[0] passthrough (no interpolation state)
        x_l, x_r = core_l, core_r
        self.cycle = 0

        # ---- output one-pole lowpass (iirB)
        self.iir_b["L"] = y = rs(
            self.iir_b["L"] * c["lowpass_m1"] + x_l * c["lowpass"],
            FRAC_C31)
        self.iir_b["R"] = y = rs(
            self.iir_b["R"] * c["lowpass_m1"] + x_r * c["lowpass"],
            FRAC_C31)

        # ---- wet/dry mix (control-plane branch on the double wet)
        if c["wet_active"]:
            ol = rs(self.iir_b["L"] * c["wet"] + dry_l * c["wet_m1"],
                           FRAC_C31)
            orr = rs(self.iir_b["R"] * c["wet"] + dry_r * c["wet_m1"],
                            FRAC_C31)
        else:
            ol, orr = self.iir_b["L"], self.iir_b["R"]
        if self.hist is not None:
            self.hist["iir_a"].append(self.iir_a["L"])
            self.hist["fb_AR"].append(self.fb["AR"])
        return ol, orr

    # ------------------------------------------------------------ reporting
    def checkpoint(self):
        """Integer state checkpoint (RTL-compared). The control-plane
        vibrato doubles are NOT here: they stream in as control words."""
        return {
            "counts": dict(self.counts),
            "iir_a": dict(self.iir_a),
            "iir_b": dict(self.iir_b),
            "fb": dict(self.fb),
            "cycle": self.cycle,
        }

    def buffer_digest(self):
        h = hashlib.sha256()
        for v in self.mem:
            h.update((v & 0xFFFFFFFF).to_bytes(4, "little"))
        return h.hexdigest()


def buffer_report():
    """Per-instance state residency + external traffic (SXT-015 accounting
    conventions; cycleEnd=1 at 48 kHz)."""
    lines = []
    for name, base, words in REGIONS:
        lines.append({"region": name, "base": base, "words": words,
                      "bits": words * 32})
    reads = 28   # 4 vibrato + 8 + 8 + 8 line reads
    writes = 26  # 2 vibrato + 8 + 8 + 8 line writes
    return {
        "instance": "aw-49 (Airwindows Galactic, id 49)",
        "sample_rate": SAMPLE_RATE,
        "cycle_end": 1,
        "external_writable_memory": {
            "words_total": EXT_WORDS,
            "bytes_total_32bit": EXT_WORDS * 4,
            "regions": lines,
        },
        "external_traffic_per_frame": {
            "reads": reads, "writes": writes, "words": reads + writes,
            "bytes": (reads + writes) * 4,
            "MB_per_s_per_instance": round((reads + writes) * 4
                                           * SAMPLE_RATE / 1e6, 6),
        },
        "notes": [
            "vibrato phase (vibM/oldfpd from captured fpdL/fpdR) and the "
            "per-sample read positions are control plane: +4 words/sample "
            "on-chip control bandwidth, not external-memory traffic",
            "flash is never a substitute: the whole region is writable "
            "state",
            "two concurrent slots = two instances = two regions (never "
            "shared)",
        ],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(buffer_report(), indent=2))
