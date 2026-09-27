#!/usr/bin/env python3
"""SXT-028k: frozen fixed-point model of the Airwindows "Logical" algorithm
(streamed Airwindows algorithm id 4, `Logical4`).

Issue #63 (SXT-028k) · parent #21 (SXT-028) · epic #3 · plan section 6.

This module is the FROZEN integer model that the RTL-vs-model EXACTNESS
claim references (`rtl/effects/aw-4/`, `tools/compare_rtl_model_aw4.py`).
The model-vs-pinned-engine agreement is a SEPARATE claim governed by
[PROPOSED] error budgets and is NOT_RUN here (no oracle in this
environment); see reports/SXT-028k/EVIDENCE.md. Neither claim says anything
about musical quality (AGENTS.md: three claims, never inferred from one
another).

Provenance / licensing (AGENTS.md; decision-records/0015)
---------------------------------------------------------
STRUCTURE ONLY is read and cited — never copied — from the pinned external
tree. That tree is NOT uniformly licensed, and the distinction matters here
(see decision-records/0015): the vendored `libs/airwindows/` subtree carries
its own `LICENSE` file, **MIT, Copyright (c) 2018 Chris Johnson**
(`libs/airwindows/README.md` states it explicitly), while the Surge adapter
around it is GPL-3.0-or-later like the rest of the engine:

* `surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71`
  `libs/airwindows/src/Logical4Proc.cpp` (`processReplacing`) and
  `libs/airwindows/src/Logical4.{h,cpp}` (state declaration + constructor
  init + parameter semantics), Airwindows (c) 2011/2016, MIT;
* `libs/airwindows/src/AirWinBaseClass_pluginRegistry.cpp` (MIT subtree),
  whose `id++` stream places `Logical4::Logical4` at streamed **id 4**
  (ADClip7 0, BlockParty 1, ButterComp2 2, Compresaturator 3, Logical 4) —
  the id this leaf, and only this leaf, dispatches;
* `src/common/dsp/effects/airwindows/AirWindowsEffect.{h,cpp}`
  (GPL-3.0-or-later) — the shared
  adapter: `p[0]` selects the streamed id, `p[1..5]` carry Logical's five
  `ct_airwindows_param` floats, the 32-sample block is split into 8
  sub-blocks of 4 (`subblock_factor = 3`) and each parameter is re-applied
  from a `OnePoleLag` at every sub-block boundary.

No Airwindows code, table, or asset is copied into this repository. The
handful of opaque designed literals quoted as data (the speed constants,
`intensity`, `powerSag`, the `2.42` sag depth, the `1.57079633` rectifier
clamp, the `36.0` clip, the `0.000001` leak, the `0.5` clamp floor, the
`0.001` polarity floor, the `499/1000` line geometry, the `2.99999` ratio
clamp, the golden-ratio `fpOld`) are recorded in
decision-records/0015 (DR-0003 class). Every other coefficient is
re-derived at run time from the cited formulas.

What the algorithm is
---------------------
Three cascaded, stereo-LINKED ButterComp compressor stages, each preceded by
its own Desk "Power Sag" nonlinearity, with a fractional-ratio crossfade
selecting how many stages are audible:

    ratio         = clamp(sqrt(B*B*15 + 1) - 1, 0, 2.99999)
    ratioselector = floor(ratio)           # 0, 1 or 2 -> 1, 2 or 3 stages
    ratio        -= ratioselector          # crossfade weight into the last
                                           # stage; invRatio = 1 - ratio

Per sample the pinned order is: sagA(L), sagA(R), compA(L), compA(R),
[sagB(L), sagB(R), compB(L), compB(R)], [sagC(L), sagC(R), compC(L),
compC(R)], crossfade, makeup gain, wet/dry, `fpFlip = !fpFlip`. The
stage-B/C blocks run only when `ratioselector` selects them; their state
stands still otherwise (reproduced).

Pinned quirks reproduced deliberately (each has a live negative control)
-----------------------------------------------------------------------
Q1 **Sag line mirror is one short.** `dL[gcount+499] = dL[gcount] = ...`
   mirrors at +499 while `gcount` cycles over 500 values (499..0), and the
   read is `dL[gcount + offsetA]`. The tap is therefore 2 samples old for
   498 of every 500 samples and **3 samples old** at `gcount` 498 and 499.
   The frozen model reproduces the age exactly from a 4-word ring (see
   "External memory"), and `PinnedIndexSagLine` below is a literal
   1000-word transcription used by the test suite to prove the compaction
   is bit-exact over full periods.
Q2 **Stage-C right channel updates the LEFT target.** The third compressor's
   right-channel positive side runs `targetposCL *= dynamicDivisor;
   targetposCL += inputpos*dynamicRemainder;` and then takes the reciprocal
   of `targetposCR`, which nothing ever writes. So `targetposCR` stays at
   its constructor value 1.0 forever (calcpos == 1.0 on that side) while
   `targetposCL` is updated twice per sample, once from each channel. The
   negative side is unaffected. Reproduced exactly.
Q3 **Stage-C subtracts at offsetB.** `controlCL -= (cL[gcount+offsetB] /
   offsetC);` indexes with `offsetB` and divides by `offsetC`. At 48 kHz
   both are 2, so the arithmetic is unchanged; the asymmetry is recorded
   because it is not a typo the model may "fix".
Q4 **divisorC does not scale with attack.** `divisorC = 0.000857 /
   overallscale` (no `attackspeed`), while `remainderC = divisorC *
   attackspeed`. So stage C's decay and attack constants are not a
   complementary pair, unlike stages A and B. Reproduced.

Frozen scope (fail-closed — every violation RAISES `Refuse`)
------------------------------------------------------------
* Sample rate frozen at 48 kHz: `overallscale = (1.0/44100.0)*48000.0`, so
  `offsetA = offsetB = offsetC = (int)(2.42*overallscale) = 2`. Any other
  rate changes the sag tap geometry and is refused.
* Static patch parameters: the adapter's per-sub-block `OnePoleLag` ramp is
  declared CONTROL PLANE at its converged target (`clamp01(val.f)`). The
  ~0.3 s post-load ramp from 0 is outside the frozen model and is covered by
  the render settle policy, exactly as in the sibling aw-49 leaf.
* Parameter modulation into FX params: not modeled (fail-closed) — the
  extractor refuses any carrier whose modulation graph targets this slot.
* Declared input envelope |x| <= 64.0 at the slot boundary. Beyond it the
  t64 target word is no longer provably in range, so the model refuses
  rather than silently saturating.
* `long double fpOld` in the pinned source: the reference evaluates
  `inputSample * fpOld` in x87 80-bit on i386/x86-64 and in binary64 or
  binary128 elsewhere. That is a REFERENCE-SIDE architecture dependence,
  recorded as a repeatability caveat in EVIDENCE.md; the frozen model
  quantizes fpOld/fpNew once to Q1.31 and is architecture-independent.

Frozen word formats (model/effects/README.md conventions)
---------------------------------------------------------
* `a48`  Q13.35 signed, 48-bit — audio samples, `avg*`/`nvg*` registers,
         rectifier argument. Range +-4096, resolution 2.9e-11. The bound is
         PROVED, not measured: the comp output is hard-clipped to +-36, the
         makeup path divides by `compoutgain` >= 0.1 and multiplies by
         `outputgain` <= 10, so |out| <= 36/0.1*10 = 3600 < 4096.
* `c96`  96-bit signed, 53 fraction bits — the gain/control plane: the
         twenty-four `control{A,B}{pos,neg}[stage][ch]` registers,
         `calc{pos,neg}`, `totalmultiplier`, and the sag line words.
         Magnitude bound 2^42 = 4.398e12, resolution 1.11e-16.
         **Why 96 bits and not 64.** The range bound is PROVED: `target`
         is a convex combination of values that are all >= the squared
         polarity floor 1e-6, so `calc = 1/target^2 <= 1e12` and the
         four-control sum `S <= 4e12 < 2^42`. That floor is *reachable*
         (a sustained one-polarity input drives the opposite target to it
         within ~4000 samples — measured, see EVIDENCE.md finding
         F-028k-1), so the range cannot be traded away. Meanwhile
         `totalmultiplier` is routinely ~1e-2, and a Q42.21-in-64-bit word
         puts its quantization at 4.77e-7 — a 4e-5 RELATIVE gain error,
         which dominated every other error term in the internal
         diagnostic. 13 decades of required dynamic range in one linear
         fixed-point word is 96 bits; the alternative (a log-domain or
         block-floating control path) is named as future work in the
         finding, not implemented here.
* `t64`  64-bit signed, 43 fraction bits — `target{pos,neg}[stage][ch]`,
         `inputpos`, `inputneg`, `outputpos`, `outputneg`, and the
         per-stage `remainder`/`divisor` coefficient words. Magnitude
         bound 2^20 = 1048576, resolution 1.1e-13. Bound: max `inputpos`
         = (64*10 + 1)^2 = 410881 under the declared input envelope; and
         `1/target <= 1e6`, the reciprocal's own intermediate.
* `s96`  96-bit signed, 54 fraction bits — the six per-channel sag control
         accumulators and the derived `thickness`/`out`/`clamp`. Exactly
         one fraction bit more than `c96` so the pinned `/offsetA` (= /2 at
         48 kHz) is EXACT: the accumulator adds the c96 line word
         unshifted. Magnitude bound 2^41 = 2.199e12 >= the pre-clamp
         excursion 64*(4e12*0.0033) = 8.4e11.
* `k31`  Q*.31 signed, 64-bit containers — control-plane coefficients
         quantized once at the declared boundary: `fpOld`, `fpNew`,
         `powerSag`, `ratio`, `invRatio`, `wet`, `dry`, `inputgain`,
         `inv_compoutgain`, `outputgain`.
* ROM: two 806-word Q1.31 tables (sin, 1-cos) shared by every instance
  (model/effects/aw-4/tables.py; derived, not quoted).

Arithmetic: exact integer products in wide accumulators, round-half-up
`(x + 2^(f-1)) >>> f` (arithmetic/floor shift, mirroring SV `>>>`),
saturating stores with counted saturations. No floating point in the audio
path. Double precision only at control rate, each value quantized once at
its declared boundary.

One declared arithmetic deviation from the pinned source: the pinned
`inputSample / compoutgain` division is replaced by a multiply against a
control-plane `inv_compoutgain` word quantized once to Q5.31. The relative
error is <= 2^-32 of the coefficient; it is a model-vs-reference
contributor, never a model-vs-RTL one.

External memory (per instance)
------------------------------
**None.** The pinned 1000-double sag arrays are allocation, not state: only
indices 0..501 are ever read and only taps of age 2 or 3 are ever taken
(quirk Q1). The frozen model therefore holds a 4-word ring per sag line —
3 stages x 2 channels x 4 words — and `state_inventory()` reports the exact
on-chip footprint (602 bytes/instance). `PinnedIndexSagLine` +
`tests/test_sxt028k.py::test_compacted_sag_ring_matches_pinned_indexing`
prove the compaction bit-exact over two full 500-sample periods, including
both wrap samples. Two concurrent slots are two instances with two
completely disjoint state records; nothing is pooled (AGENTS.md).
"""

import hashlib
import math
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))

import sys  # noqa: E402

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import tables as T  # noqa: E402


class Refuse(Exception):
    """Fail-closed refusal: the frozen scope does not cover this input."""


# --------------------------------------------------------------------------
# Frozen geometry and word formats
# --------------------------------------------------------------------------

SAMPLE_RATE = 48000
BLOCK = 32
SUBBLOCK = 4                 # adapter: BLOCK_SIZE >> subblock_factor(3)
N_PARAMS = 5                 # Logical4 kNumParameters
AW_STREAMED_ID = 4           # AirWinBaseClass_pluginRegistry id++ stream

F_A = 35                     # a48  48-bit signed, 35 frac  (|v| < 2^12)
F_C = 53                     # c96  96-bit signed, 53 frac  (|v| < 2^42)
F_T = 43                     # t64  64-bit signed, 43 frac  (|v| < 2^20)
F_S = 54                     # s96  96-bit signed, 54 frac  (|v| < 2^41)
F_K = 31                     # k31  64-bit signed, 31 frac  (|v| < 2^32)

A48_MIN, A48_MAX = -(1 << 47), (1 << 47) - 1
I64_MIN, I64_MAX = -(1 << 63), (1 << 63) - 1
I96_MIN, I96_MAX = -(1 << 95), (1 << 95) - 1

ONE_C = 1 << F_C
ONE_T = 1 << F_T
ONE_S = 1 << F_S
ONE_K = 1 << F_K

# ---- quoted designed constants (pinned Logical4Proc.cpp / Logical4.cpp;
# MIT (c) Chris Johnson, libs/airwindows/LICENSE; decision-records/0015)
FP_OLD = 0.618033988749894848204586       # "golden ratio!"
FP_NEW = 1.0 - FP_OLD
INTENSITY = 0.0445556
POWER_SAG = 0.003300223685324102874217
SAG_DEPTH = 2.42
SAG_LEAK = 0.000001
CLAMP_FLOOR = 0.5
POS_FLOOR = 0.001
BR_MAX = 1.57079633
HARD_CLIP = 36.0
SPEED_A = 0.000782
SPEED_B = 0.000819
SPEED_C = 0.000857
ATTACK_SPAN = 99.0
ATTACK_BASE = 10.0
RATIO_SPAN = 15.0
RATIO_CLAMP = 2.99999
GAIN_SPAN = 40.0
GAIN_OFFSET = 20.0
LINE_WORDS = 1000            # pinned dL[1000]
LINE_MIRROR = 499            # pinned mirror offset (see quirk Q1)
GCOUNT_MAX = 499
OFFSET_MIN, OFFSET_MAX = 1, 498

# ---- frozen derived geometry (48 kHz only)
OVERALLSCALE = (1.0 / 44100.0) * float(SAMPLE_RATE)
SAG_OFFSET = int(SAG_DEPTH * OVERALLSCALE)                 # 2
if SAG_OFFSET < OFFSET_MIN:
    SAG_OFFSET = OFFSET_MIN
if SAG_OFFSET > OFFSET_MAX:
    SAG_OFFSET = OFFSET_MAX
RING = 4                     # taps of age 2 and 3 -> 4-word ring
N_STAGES = 3
N_CH = 2

INPUT_ENVELOPE = 64.0        # declared |x| bound at the slot boundary
A48_ENVELOPE = int(INPUT_ENVELOPE * (1 << F_A))
CLIP_A = int(HARD_CLIP * (1 << F_A))
BRMAX_A = int(BR_MAX * (1 << F_A) + 0.5)
POS_FLOOR_T = int(POS_FLOOR * (1 << F_T) + 0.5)
LEAK_S = int(SAG_LEAK * (1 << F_S) + 0.5)
HALF_S = 1 << (F_S - 1)
INTENSITY_C = int(INTENSITY * (1 << F_C) + 0.5)
POWER_SAG_K = int(POWER_SAG * (1 << F_K) + 0.5)
FP_OLD_K = int(FP_OLD * (1 << F_K) + 0.5)
FP_NEW_K = int(FP_NEW * (1 << F_K) + 0.5)

# reciprocal stage: inv = 2^(2*F_T) / target (t64, the 1/target word), then
# calc = round(inv^2 >> (2*F_T - F_C)) in c96
RECIP_NUM = 1 << (2 * F_T)
CALC_SHIFT = 2 * F_T - F_C   # 33


def model_revision():
    """SHA-256 over the frozen model source + the frozen tables source.

    The RTL harness pins this word; a harness whose pin does not match the
    tree it is comparing against must REFUSE to report PASS (AGENTS.md
    stale-stub control).
    """
    h = hashlib.sha256()
    for p in (os.path.join(_HERE, "logical4_model.py"),
              os.path.join(_HERE, "tables.py")):
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def revision_word():
    """The low 32 bits of model_revision(), the word the RTL trace echoes."""
    return int(model_revision()[:8], 16)


# --------------------------------------------------------------------------
# Fixed-point helpers (round-half-up, arithmetic shift; qmath.py convention)
# --------------------------------------------------------------------------

def rnd(x, f):
    """(x + 2^(f-1)) >>> f — arithmetic (floor) shift, mirrors SV `>>>`."""
    if f == 0:
        return x
    return (x + (1 << (f - 1))) >> f


def mulr(a, b, fa, fb, fout):
    """Exact product then a single round-half-up to `fout` fraction bits."""
    return rnd(a * b, fa + fb - fout)


def q(x, f):
    """Quantize a double to `f` fraction bits, round-half-away-from-zero."""
    v = x * float(1 << f)
    return int(v + 0.5) if v >= 0 else -int(-v + 0.5)


def _f32(x):
    import numpy as np
    return float(np.float32(x))


# --------------------------------------------------------------------------
# Control plane (double precision, quantized once at declared boundaries)
# --------------------------------------------------------------------------

PARAM_NAMES = ("A_threshold", "B_ratio", "C_attack", "D_makeup", "E_mix")


def build_control(params, sample_rate=SAMPLE_RATE):
    """Coefficient plane from the five converged adapter parameters.

    `params`: mapping with keys A_threshold, B_ratio, C_attack, D_makeup,
    E_mix — the post-lag float32 values the adapter hands `setParameter`,
    i.e. `clamp01(fxdata->p[i+1].val.f)`.
    """
    if int(sample_rate) != SAMPLE_RATE:
        raise Refuse(
            "frozen scope is 48 kHz (sag tap geometry depends on it); got %r"
            % (sample_rate,))

    vals = {}
    for name in PARAM_NAMES:
        if name not in params:
            raise Refuse("missing parameter %s (fail-closed)" % name)
        v = params[name]
        if v is None:
            raise Refuse("parameter %s is null (fail-closed)" % name)
        v = _f32(v)
        if not (0.0 <= v <= 1.0):
            raise Refuse(
                "parameter %s = %r outside the adapter's clamp01 range"
                % (name, v))
        vals[name] = v

    A, B, C, D, E = (vals["A_threshold"], vals["B_ratio"], vals["C_attack"],
                     vals["D_makeup"], vals["E_mix"])

    overallscale = OVERALLSCALE
    offsets = []
    for _ in range(N_STAGES):
        o = int(SAG_DEPTH * overallscale)
        o = OFFSET_MIN if o < OFFSET_MIN else (OFFSET_MAX if o > OFFSET_MAX
                                               else o)
        offsets.append(o)
    if set(offsets) != {SAG_OFFSET} or SAG_OFFSET != 2:
        raise Refuse("frozen sag tap geometry is offset == 2; got %r"
                     % (offsets,))

    inputgain = math.pow(10.0, (-((A * GAIN_SPAN) - GAIN_OFFSET)) / 20.0)
    compoutgain = inputgain

    attackspeed = ((C * C) * ATTACK_SPAN) + 1.0
    attackspeed = ATTACK_BASE / math.sqrt(attackspeed)

    divisor = SPEED_A * attackspeed / overallscale
    remainder = divisor
    divisor = 1.0 - divisor

    divisor_b = SPEED_B * attackspeed / overallscale
    remainder_b = divisor_b
    divisor_b = 1.0 - divisor_b

    divisor_c = SPEED_C / overallscale
    remainder_c = divisor_c * attackspeed       # quirk Q4
    divisor_c = 1.0 - divisor_c

    ratio = math.sqrt(((B * B) * RATIO_SPAN) + 1.0) - 1.0
    if ratio > RATIO_CLAMP:
        ratio = RATIO_CLAMP
    if ratio < 0.0:
        ratio = 0.0
    ratioselector = int(math.floor(ratio))
    ratio -= ratioselector
    inv_ratio = 1.0 - ratio

    outputgain = math.pow(10.0, ((D * GAIN_SPAN) - GAIN_OFFSET) / 20.0)
    wet = E
    dry = 1.0 - wet

    ctrl = {
        "params_f32": dict(vals),
        "sample_rate": SAMPLE_RATE,
        "overallscale": overallscale,
        "sag_offset": SAG_OFFSET,
        "ratioselector": ratioselector,
        "n_active_stages": ratioselector + 1,
        # doubles retained for the record / EVIDENCE only
        "d": {
            "inputgain": inputgain, "compoutgain": compoutgain,
            "attackspeed": attackspeed,
            "remainder": [remainder, remainder_b, remainder_c],
            "divisor": [divisor, divisor_b, divisor_c],
            "ratio": ratio, "inv_ratio": inv_ratio,
            "outputgain": outputgain, "wet": wet, "dry": dry,
        },
        # frozen words
        "inputgain_k": q(inputgain, F_K),
        "inv_compoutgain_k": q(1.0 / compoutgain, F_K),
        "outputgain_k": q(outputgain, F_K),
        "ratio_k": q(ratio, F_K),
        "inv_ratio_k": q(inv_ratio, F_K),
        "wet_k": q(wet, F_K),
        "dry_k": q(dry, F_K),
        "remainder_t": [q(remainder, F_T), q(remainder_b, F_T),
                        q(remainder_c, F_T)],
        "divisor_t": [q(divisor, F_T), q(divisor_b, F_T), q(divisor_c, F_T)],
        "inputgain_is_one": inputgain == 1.0,
        "outputgain_is_one": outputgain == 1.0,
        "wet_is_one": wet == 1.0,
    }
    for name in ("inputgain_k", "inv_compoutgain_k", "outputgain_k"):
        if abs(ctrl[name]) >= (1 << (F_K + 5)):
            raise Refuse("%s out of the declared Q5.31 range" % name)
    return ctrl


def coefficient_words(ctrl):
    """The frozen control-plane word vector streamed to the RTL (cfg.hex).

    Order is part of the frozen interface; `tools/compare_rtl_model_aw4.py`
    and `rtl/effects/aw-4/tb_logical4.sv` both index it positionally.
    """
    w = [
        ctrl["ratioselector"],
        1 if ctrl["inputgain_is_one"] else 0,
        1 if ctrl["outputgain_is_one"] else 0,
        1 if ctrl["wet_is_one"] else 0,
        ctrl["inputgain_k"], ctrl["inv_compoutgain_k"], ctrl["outputgain_k"],
        ctrl["ratio_k"], ctrl["inv_ratio_k"], ctrl["wet_k"], ctrl["dry_k"],
    ]
    w += ctrl["remainder_t"] + ctrl["divisor_t"]
    return w


# --------------------------------------------------------------------------
# The pinned-index sag line (verification reference for the 4-word ring)
# --------------------------------------------------------------------------

class PinnedIndexSagLine:
    """Literal transcription of the pinned 1000-word sag array indexing.

    Used ONLY by the test suite to prove the frozen model's 4-word ring is
    bit-exact. It is deliberately NOT the implementation: a 1000-word line
    per stage per channel would be 6000 words of state this effect does not
    need, and claiming that footprint would misstate the cost.
    """

    def __init__(self):
        self.mem = [0] * LINE_WORDS

    def step(self, gcount, value, offset=SAG_OFFSET):
        """Pinned order: write primary + mirror, then read at gcount+offset.
        Returns (written_value, tapped_value)."""
        self.mem[gcount] = value
        self.mem[gcount + LINE_MIRROR] = value
        return value, self.mem[gcount + offset]


def pinned_tap_age(gcount, offset=SAG_OFFSET):
    """Age (in samples) of the word the pinned indexing taps at `gcount`.

    Derivation (quirk Q1): index `gcount+offset` is written either as a
    primary write at `gcount+offset` (age `offset`) or as a mirror write at
    `gcount + offset - 499` (age `offset + 1`, because gcount's period is
    500, not 499). The primary write wins whenever `gcount+offset <= 499`.
    """
    idx = gcount + offset
    return offset if idx <= GCOUNT_MAX else offset + 1


# --------------------------------------------------------------------------
# Per-instance state
# --------------------------------------------------------------------------

class LogicalState:
    """One Logical instance's complete history. Two concurrent slots hold
    two of these; nothing is shared (AGENTS.md per-instance rule)."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Pinned Logical4() constructor state."""
        self.gcount = 0
        self.fp_flip = True
        # control{A,B}{pos,neg}[stage][ch], c64, init 1.0
        self.c_apos = [[ONE_C] * N_CH for _ in range(N_STAGES)]
        self.c_aneg = [[ONE_C] * N_CH for _ in range(N_STAGES)]
        self.c_bpos = [[ONE_C] * N_CH for _ in range(N_STAGES)]
        self.c_bneg = [[ONE_C] * N_CH for _ in range(N_STAGES)]
        # target{pos,neg}[stage][ch], t64, init 1.0
        self.t_pos = [[ONE_T] * N_CH for _ in range(N_STAGES)]
        self.t_neg = [[ONE_T] * N_CH for _ in range(N_STAGES)]
        # avg/nvg[stage][ch], a48, init 0
        self.avg = [[0] * N_CH for _ in range(N_STAGES)]
        self.nvg = [[0] * N_CH for _ in range(N_STAGES)]
        # sag accumulators[stage][ch], s64, init 0
        self.sag_ctrl = [[0] * N_CH for _ in range(N_STAGES)]
        # sag line rings[stage][ch][RING], c64, init 0
        self.sag_line = [[[0] * RING for _ in range(N_CH)]
                         for _ in range(N_STAGES)]
        self.saturations = 0
        self.recip_saturations = 0
        self.clip_hits = 0
        self.sag_clamp_hits = 0
        self.tap_age3_hits = 0
        self.ext_reads = 0
        self.ext_writes = 0

    # ------------------------------------------------------------ checkpoint
    def checkpoint(self):
        """Integer state checkpoint — the fields the RTL trace dumps and
        `tools/compare_rtl_model_aw4.py` compares for integer equality."""
        return {
            "gcount": self.gcount,
            "fp_flip": 1 if self.fp_flip else 0,
            "c_apos": [list(r) for r in self.c_apos],
            "c_aneg": [list(r) for r in self.c_aneg],
            "c_bpos": [list(r) for r in self.c_bpos],
            "c_bneg": [list(r) for r in self.c_bneg],
            "t_pos": [list(r) for r in self.t_pos],
            "t_neg": [list(r) for r in self.t_neg],
            "avg": [list(r) for r in self.avg],
            "nvg": [list(r) for r in self.nvg],
            "sag_ctrl": [list(r) for r in self.sag_ctrl],
            "sag_line": [[list(c) for c in s] for s in self.sag_line],
        }

    def digest(self):
        h = hashlib.sha256()
        cp = self.checkpoint()
        h.update(repr(sorted(cp.items())).encode())
        return h.hexdigest()


def state_inventory():
    """Exact per-instance on-chip state footprint (SXT-015 accounting).

    No external writable memory is required by this algorithm; the pinned
    1000-word sag arrays are allocation, not reachable state (quirk Q1).
    """
    fields = [
        ("gcount", 1, 9),
        ("fp_flip", 1, 1),
        ("control{A,B}{pos,neg} (c96)", 4 * N_STAGES * N_CH, 96),
        ("target{pos,neg} (t64)", 2 * N_STAGES * N_CH, 64),
        ("avg/nvg (a48)", 2 * N_STAGES * N_CH, 48),
        ("sag control accumulators (s96)", N_STAGES * N_CH, 96),
        ("sag line rings (c96)", N_STAGES * N_CH * RING, 96),
    ]
    bits = sum(n * w for _f, n, w in fields)
    return {
        "instance": "aw-4 (Airwindows Logical, streamed id 4)",
        "fields": [{"field": f, "count": n, "bits_each": w,
                    "bits": n * w} for f, n, w in fields],
        "bits_total": bits,
        "bytes_total": (bits + 7) // 8,
        "external_writable_memory_bytes": 0,
        "rom_shared": {
            "tables": ["sin_q31 (806 x 33b)", "omc_q31 (806 x 33b)"],
            "bits": 2 * T.TABLE_WORDS * 33,
            "bytes": (2 * T.TABLE_WORDS * 33 + 7) // 8,
            "note": "read-only, shared by every concurrent instance; never "
                    "a substitute for writable state",
        },
    }


def buffer_report():
    inv = state_inventory()
    return {
        "leaf": "SXT-028k",
        "instance": inv["instance"],
        "sample_rate": SAMPLE_RATE,
        "external_writable_memory": {
            "bytes_total": 0,
            "regions": [],
            "why": "the pinned dL/bL/cL[1000] arrays are allocation, not "
                   "reachable state: only taps of age 2 and 3 are ever "
                   "read (quirk Q1), so a 4-word ring per line is "
                   "bit-exact (proved in tests/test_sxt028k.py)",
        },
        "external_traffic": {
            "reads_per_frame": 0,
            "writes_per_frame": 0,
            "bytes_per_s_per_instance": 0,
        },
        "on_chip_state_exact": {
            "bits_total": inv["bits_total"],
            "bytes_total": inv["bytes_total"],
            "fields": inv["fields"],
        },
        "rom_shared": inv["rom_shared"],
        "flash_note": "no delay/reverb-class buffer exists in this "
                      "algorithm; flash is not involved and could not "
                      "substitute for writable state if it were",
        "cost_closure": {
            "status": "[PENDING-SXT-016]",
            "note": "state residency and (zero) external traffic are "
                    "reported from the frozen model; the fit verdict "
                    "against a profile budget is SXT-016/SXT-017 work and "
                    "is NOT claimed here",
        },
        "arithmetic_cost_finding": {
            "status": "RECORDED",
            "text": "each active stage needs two 128/64 reciprocal "
                    "evaluations per sample per channel (calcpos/calcneg = "
                    "1/target^2). At ratioselector 2 that is 12 "
                    "reciprocals per frame per instance plus the "
                    "table-interpolated sin/1-cos pair per stage per "
                    "channel. Routed to SXT-017 (#12) as a cost input; NOT "
                    "a fit or infeasibility claim",
        },
    }


# --------------------------------------------------------------------------
# The frozen fixed-point model
# --------------------------------------------------------------------------

class Logical4Fixed:
    """One Airwindows Logical (id 4) instance."""

    instance_kind = "aw-4"
    streamed_id = AW_STREAMED_ID

    def __init__(self, ctrl, label="aw4", pinned_lines=False):
        self.c = ctrl
        self.label = label
        self.st = LogicalState()
        # optional literal 1000-word lines, for the equivalence proof only
        self.pinned = ([[PinnedIndexSagLine() for _ in range(N_CH)]
                        for _ in range(N_STAGES)] if pinned_lines else None)
        self.pinned_mismatch = 0

    # ----------------------------------------------------------------- admin
    def reset(self):
        """Panic / voice reset: the constructor state, tail discarded."""
        self.st.reset()
        if self.pinned is not None:
            self.pinned = [[PinnedIndexSagLine() for _ in range(N_CH)]
                           for _ in range(N_STAGES)]

    def set_control(self, ctrl):
        """Mid-tail patch change: the engine mutates FxStorage in place and
        the instance keeps every history (no re-construction)."""
        self.c = ctrl

    # -------------------------------------------------------------- guards
    @staticmethod
    def _sat_c96(v, st):
        if v > I96_MAX or v < I96_MIN:
            st.saturations += 1
            return I96_MAX if v > 0 else I96_MIN
        return v

    def _check_input(self, v):
        if v > A48_ENVELOPE or v < -A48_ENVELOPE:
            raise Refuse(
                "input %r exceeds the declared |x| <= %g envelope; the t64 "
                "target word is not provably in range beyond it"
                % (v / float(1 << F_A), INPUT_ENVELOPE))

    # ------------------------------------------------------------------ sag
    def _sag(self, stage, ch, x):
        """Desk "Power Sag" stage. Returns the reshaped a48 sample."""
        st = self.st
        # d = |x| * (intensity - (sum of the four comp controls) * powerSag)
        s = (st.c_apos[stage][ch] + st.c_bpos[stage][ch]
             + st.c_aneg[stage][ch] + st.c_bneg[stage][ch])
        k = INTENSITY_C - mulr(s, POWER_SAG_K, F_C, F_K, F_C)
        ax = x if x >= 0 else -x
        d = self._sat_c96(mulr(ax, k, F_A, F_C, F_C), st)

        ridx = (-st.gcount) & (RING - 1)
        age = pinned_tap_age(st.gcount, self.c["sag_offset"])
        if age != SAG_OFFSET:
            st.tap_age3_hits += 1
        st.sag_line[stage][ch][ridx] = d
        d_old = st.sag_line[stage][ch][(ridx - age) & (RING - 1)]

        if self.pinned is not None:
            _w, tapped = self.pinned[stage][ch].step(st.gcount, d)
            if tapped != d_old:
                self.pinned_mismatch += 1

        # control += d/offset - d_old/offset - leak, EXACT at F_S = F_C + 1
        ctl = st.sag_ctrl[stage][ch] + d - d_old - LEAK_S
        clamp = ONE_S
        if ctl < 0:
            ctl = 0
        if ctl > ONE_S:
            clamp -= (ctl - ONE_S)
            ctl = ONE_S
        if clamp < HALF_S:
            clamp = HALF_S
        st.sag_ctrl[stage][ch] = ctl
        if clamp != ONE_S:
            st.sag_clamp_hits += 1

        thickness = ONE_S - 2 * ctl          # ((1-control)*2)-1, exact
        out = thickness if thickness >= 0 else -thickness

        br = ax if ax <= BRMAX_A else BRMAX_A
        if thickness > 0:
            bq = T.lookup(T.SIN_Q31, br)
        else:
            bq = T.lookup(T.OMC_Q31, br)
        br_a = bq << (F_A - F_K)             # Q1.31 -> a48, exact

        blended = mulr(x, ONE_S - out, F_A, F_S, F_A)
        shaped = mulr(br_a, out, F_A, F_S, F_A)
        x = blended + shaped if x > 0 else blended - shaped
        if clamp != ONE_S:
            x = mulr(x, clamp, F_A, F_S, F_A)
        return x

    # ----------------------------------------------------------------- comp
    def _comp(self, stage, ch, x):
        """One ButterComp stage. Returns (inputSample, outSample) in a48."""
        st = self.st
        c = self.c
        rem = c["remainder_t"][stage]
        div = c["divisor_t"][stage]

        if stage == 0 and not c["inputgain_is_one"]:
            x = mulr(x, c["inputgain_k"], F_A, F_K, F_A)

        # ---- positive side
        ipos = (mulr(x, FP_OLD_K, F_A, F_K, F_T)
                + mulr(st.avg[stage][ch], FP_NEW_K, F_A, F_K, F_T) + ONE_T)
        st.avg[stage][ch] = x
        if ipos < POS_FLOOR_T:
            ipos = POS_FLOOR_T
        opos = rnd(ipos, 1)
        if opos > ONE_T:
            opos = ONE_T
        sq_pos = rnd(ipos * ipos, F_T)
        dr = rnd(rem * (sq_pos + ONE_T), F_T)
        if dr > ONE_T:
            dr = ONE_T
        dd = ONE_T - dr
        # quirk Q2: stage C's right channel updates the LEFT positive target
        tgt_ch = 0 if (stage == 2 and ch == 1) else ch
        st.t_pos[stage][tgt_ch] = (rnd(st.t_pos[stage][tgt_ch] * dd, F_T)
                                   + rnd(sq_pos * dr, F_T))
        calc_pos = self._recip_sq(st.t_pos[stage][ch])

        # ---- negative side
        ineg = (mulr(-x, FP_OLD_K, F_A, F_K, F_T)
                + mulr(st.nvg[stage][ch], FP_NEW_K, F_A, F_K, F_T) + ONE_T)
        st.nvg[stage][ch] = -x
        if ineg < POS_FLOOR_T:
            ineg = POS_FLOOR_T
        oneg = rnd(ineg, 1)
        if oneg > ONE_T:
            oneg = ONE_T
        sq_neg = rnd(ineg * ineg, F_T)
        dr = rnd(rem * (sq_neg + ONE_T), F_T)
        if dr > ONE_T:
            dr = ONE_T
        dd = ONE_T - dr
        st.t_neg[stage][ch] = (rnd(st.t_neg[stage][ch] * dd, F_T)
                               + rnd(sq_neg * dr, F_T))
        calc_neg = self._recip_sq(st.t_neg[stage][ch])

        # ---- control bank update + stereo link
        other = 1 - ch
        if x > 0:
            bank = st.c_apos if st.fp_flip else st.c_bpos
            calc = calc_pos
        else:
            bank = st.c_aneg if st.fp_flip else st.c_bneg
            calc = calc_neg
        bank[stage][ch] = (rnd(bank[stage][ch] * div, F_T)
                           + rnd(calc * rem, F_T))
        if bank[stage][other] > bank[stage][ch]:
            bank[stage][other] = rnd(bank[stage][other] + bank[stage][ch], 1)

        if st.fp_flip:
            tot = (mulr(st.c_apos[stage][ch], opos, F_C, F_T, F_C)
                   + mulr(st.c_aneg[stage][ch], oneg, F_C, F_T, F_C))
        else:
            tot = (mulr(st.c_bpos[stage][ch], opos, F_C, F_T, F_C)
                   + mulr(st.c_bneg[stage][ch], oneg, F_C, F_T, F_C))

        if tot != ONE_C:
            x = mulr(x, tot, F_A, F_C, F_A)
        if x > CLIP_A:
            x = CLIP_A
            st.clip_hits += 1
        elif x < -CLIP_A:
            x = -CLIP_A
            st.clip_hits += 1
        out = mulr(x, c["inv_compoutgain_k"], F_A, F_K, F_A)
        return x, out

    def _recip_sq(self, target_t):
        """calc = (1/target)^2 as a c64 word. Two exact integer steps:
        `inv = round(2^86 / target)` in t64, then `calc = round(inv^2 >> 33)`.

        `target >= 0.001^2` is a property of the pinned math (a convex
        combination of values that are all >= the squared polarity floor),
        so `inv <= 1e6` and the int64 saturation below is unreachable in
        the declared scope — it is a counted fail-closed guard, asserted
        zero by the test suite, not a routine path.
        """
        st = self.st
        if target_t <= 0:
            raise Refuse(
                "target word %r is non-positive; the pinned math keeps it "
                ">= 0.001^2 so this indicates a frozen-scope violation"
                % (target_t,))
        inv = (RECIP_NUM + (target_t >> 1)) // target_t
        if inv > I64_MAX:
            st.recip_saturations += 1
            inv = I64_MAX
        return self._sat_c96(rnd(inv * inv, CALC_SHIFT), st)

    # --------------------------------------------------------------- sample
    def _sample(self, in_l, in_r):
        st = self.st
        c = self.c
        sel = c["ratioselector"]
        dry = (in_l, in_r)
        x = [in_l, in_r]
        self._check_input(in_l)
        self._check_input(in_r)

        st.gcount -= 1
        if st.gcount < 0 or st.gcount > GCOUNT_MAX:
            st.gcount = GCOUNT_MAX

        out_a = [0, 0]
        out_b = [0, 0]
        out_c = [0, 0]

        x[0] = self._sag(0, 0, x[0])
        x[1] = self._sag(0, 1, x[1])
        x[0], out_a[0] = self._comp(0, 0, x[0])
        x[1], out_a[1] = self._comp(0, 1, x[1])

        if sel > 0:
            x[0] = self._sag(1, 0, x[0])
            x[1] = self._sag(1, 1, x[1])
            x[0], out_b[0] = self._comp(1, 0, x[0])
            x[1], out_b[1] = self._comp(1, 1, x[1])
            if sel > 1:
                x[0] = self._sag(2, 0, x[0])
                x[1] = self._sag(2, 1, x[1])
                x[0], out_c[0] = self._comp(2, 0, x[0])
                x[1], out_c[1] = self._comp(2, 1, x[1])

        res = [0, 0]
        for ch in (0, 1):
            if sel == 0:
                lo, hi = dry[ch], out_a[ch]
            elif sel == 1:
                lo, hi = out_a[ch], out_b[ch]
            else:
                lo, hi = out_b[ch], out_c[ch]
            v = (mulr(lo, c["inv_ratio_k"], F_A, F_K, F_A)
                 + mulr(hi, c["ratio_k"], F_A, F_K, F_A))
            if not c["outputgain_is_one"]:
                v = mulr(v, c["outputgain_k"], F_A, F_K, F_A)
            if not c["wet_is_one"]:
                v = (mulr(v, c["wet_k"], F_A, F_K, F_A)
                     + mulr(dry[ch], c["dry_k"], F_A, F_K, F_A))
            if v > A48_MAX or v < A48_MIN:
                st.saturations += 1
                v = A48_MAX if v > 0 else A48_MIN
            res[ch] = v

        st.fp_flip = not st.fp_flip
        return res[0], res[1]

    # ---------------------------------------------------------------- block
    def process_block(self, in_l, in_r):
        """One 32-sample block of a48 words -> (out_l, out_r) a48 words."""
        if len(in_l) != BLOCK or len(in_r) != BLOCK:
            raise Refuse("block size is frozen at %d" % BLOCK)
        ol, orr = [], []
        for k in range(BLOCK):
            a, b = self._sample(in_l[k], in_r[k])
            ol.append(a)
            orr.append(b)
        return ol, orr


# --------------------------------------------------------------------------
# Tail semantics (a dynamics processor has a STATE tail, not a ringout)
# --------------------------------------------------------------------------

def tail_window_samples(ctrl, decades=5.0):
    """Declared tail span, in samples.

    Logical emits no audio into silence — with a zero input every stage
    output is zero, so an amplitude ringout measurement would read "no
    tail" and be WRONG. The tail that exists is the gain-control recovery:
    the four `control*` banks are exponential averages with per-sample
    retention `divisor[stage]`, so they relax with time constant
    `1/remainder[stage]` samples. The declared span is `decades` natural
    time constants of the SLOWEST active stage — the point after which a
    fresh burst is processed with a gain state indistinguishable (to within
    the c64 LSB) from a freshly-reset instance.

    Truncating a render before this span leaves the instance's gain state
    hot; `tools/aw4_negative_controls.py` NC-D drives exactly that and it
    must FAIL.
    """
    sel = ctrl["ratioselector"]
    rems = ctrl["d"]["remainder"][:sel + 1]
    slowest = min(rems)
    return int(math.ceil(decades / slowest))


def tail_window_blocks(ctrl, decades=5.0):
    n = tail_window_samples(ctrl, decades)
    return (n + BLOCK - 1) // BLOCK


if __name__ == "__main__":
    import json
    print(json.dumps(buffer_report(), indent=2))
    print("model_revision", model_revision())
