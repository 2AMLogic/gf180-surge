"""SXT-028e-sse frozen fixed-point model: Distortion, SSE quad-waveshaper
branch (FX waveshaper `Model` indices 3..7).

Structure authority (READ + cited; GPL-3.0-or-later tree pinned at
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 -- no code,
tables or assets copied):

  src/common/dsp/effects/DistortionEffect.cpp
      the `useSSEShaper = (ws >= wst_sine)` branch of
      `DistortionEffect::process`: `GetQuadWaveshaper(ws)` with the
      persistent per-instance `wsState`; the `1/dNow` pre-scale and its
      `skipDriveNorm` exception for DIGITAL; the per-oversample drive
      interpolation `dNow += dD` with
      `dD = (dE - dS) / (BLOCK_SIZE * dist_OS_bits)`; and the zero-input
      DC-offset probe on a throw-away zeroed `QuadWaveshaperState` at drive
      `dS`, subtracted from every output sample.
  src/common/FilterConfiguration.h:235
      `n_fxws = 8`, `FXWaveShapers` -- indices 3..7 are `wst_sine`,
      `wst_digital`, `wst_ojd`, `wst_fwrectify`, `wst_fuzzsoft`.
  libs/sst/sst-waveshapers@dd12f31a5a9016c9895e52d1a00eee0e1eebe6ce
      `GetQuadWaveshaper`, `QuadWaveshaperState` and the five reachable
      shapers -- reproduced in `quad_shapers.py` (see its DD-1..DD-4).

EVERYTHING ELSE IS REUSED UNCHANGED FROM SXT-028e (#57). The pre/post peak
EQ, the two instantized oversampled LP2B stages, the feedback recurrence,
the drive/outgain lipol ramps, the two-stage halfband decimation and the
ringout fade are imported directly from
`model/effects/type-distortion/distortion_model.py`; this file adds nothing
to them and re-derives none of them. That reuse is an ASSERTED, TESTED
property, not a comment: `DistortionSSEModel(..., chain_probe_shaper=...)`
runs this leaf's block schedule with the #57 table shaper substituted for
the quad shaper, and `tests/test_sxt028e_sse.py::
test_shared_chain_is_bit_identical_to_sxt028e` requires the result to be
bit-identical to `DistortionModel` at every output sample and every
checkpoint. If a future edit disturbs the shared chain, that test fails.

CLAIM DISCIPLINE. This file is the frozen reference the SXT-028e-sse RTL
must match EXACTLY (integer equality at declared checkpoints; separate
claim). Model-vs-pinned-engine agreement is a SEPARATE claim under
[PROPOSED] budgets that are NOT frozen (SXT-017, #12). Nothing here is a
preset-support or musical-quality claim.

PER-INSTANCE STATE. One `DistortionSSEState` owns an entire #57
`DistortionState` (both peak-EQ biquads, both oversampled LP biquads, both
halfband decimators, the two feedback registers, the two lipol ramps, the
`bi` counter) AND its own `QuadWaveshaperState` (4 registers x 2 lanes plus
the `init` mask). Two configured Distortion slots are two of these; nothing
is shared. The pooled mutant must FAIL (issue #121 acceptance).

DECLARED SCOPE OMISSIONS (fail-closed, never silently approximated):
  * FX model indices 0..2 (soft, hard, asym) are the SXT-028e (#57)
    `lookup_waveshape` table branch. REFUSED here, exactly as #57 refuses
    3..7 -- the two leaves are complementary, never overlapping.
  * Parameter modulation INTO distortion parameters (block-constant
    parameters only; the `ringout` counter is an explicit per-block input).
  * The engine's +-1e-8 denormal bias `a = (k & 16) ? 1e-8 : -1e-8` is
    ~0.02 LSB at Q10.21 and is therefore NOT representable: fixed point has
    no denormals, so the bias has no function here. Declared deviation
    (bounded by 1 LSB of Q10.21), identical to #57's.
  * The `rcp_ps` estimate, the indeterminate `wsState.init`, SIMD lanes 2/3
    and the Q24.43 range of the drive-normalized input: `quad_shapers.py`
    DD-1..DD-4.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_EFFECTS = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_MODEL_EFFECTS))
for _p in (_REPO, _MODEL_EFFECTS, os.path.join(_MODEL_EFFECTS,
                                               "type-distortion"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from model.effects.qmath import FRAC, to_q, clip, qmul, qadd  # noqa: E402
from model.effects.delay.delay_model import (  # noqa: E402
    db_to_linear_d, A_FMT, G_FMT, C_FMT, BLOCK,
)
# --- the frozen SXT-028e (#57) chain, imported and NOT re-derived ----------
from distortion_model import (  # noqa: E402
    DistortionState, DistortionModel, Lipol, get_extended, coeff_peak_eq,
    coeff_lp2b, calc_omega, lookup_waveshape, _f32, HalfbandD2, HB_COEFFS_Q,
    SLOWRATE, SLOWRATE_M1, DIST_OS_BITS, DISTORTION_OS, OS_BLOCK,
    RINGOUT_TIME, RINGOUT_END, SAMPLERATE,
)
import ws_tables  # noqa: E402  (the #57 table rows, used only by the probe)
from quad_shapers import (  # noqa: E402
    QuadWaveshaperState, get_quad_waveshaper, shaper_name, SKIP_DRIVE_NORM,
    REGISTER_USE, READS_INIT, FA, FC, FG, fmul_counted, fcv, fadd, fsub,
    frecip, fsat, W64, W32,
)
from sse_tables import (  # noqa: E402
    SSE_MODELS, FXWS_NAMES, TABLE_BRANCH_MODELS, table_digest,
)

MODEL_REVISION = None

# `dD = (dE - dS) / (BLOCK_SIZE * dist_OS_bits)`.
#
# READ THAT DENOMINATOR AGAIN. It is `BLOCK_SIZE * dist_OS_bits` = 32 * 2 =
# **64**, not `BLOCK_SIZE << dist_OS_bits` = 128, which is the number of
# oversampled steps the loop actually takes. The interpolation therefore
# overshoots: after 128 steps `dNow` has reached `dS + 2*(dE - dS)`, i.e.
# `2*dE - dS`, not `dE`. This is reproduced AS WRITTEN (issue #121: "note:
# `* dist_OS_bits`, i.e. /64, not /128 -- reproduce as written"); the
# `mutant-drivestep128` negative control "corrects" it to 128 and must FAIL.
DRIVE_INTERP_DIVISOR = BLOCK * DIST_OS_BITS      # 64
assert DRIVE_INTERP_DIVISOR == 64
# Q13.18 -> Q24.43 is a left shift of 25; dividing by 64 is a further right
# shift of 6, so `dD` is EXACT: (dE - dS) << 19.
_DD_SHIFT = (FC - FG) - 6
assert _DD_SHIFT == 19
_A_TO_C = FC - FA
assert _A_TO_C == 22


class DistortionSSEParams:
    """Frozen control-plane inputs for one SSE-branch Distortion instance.

    Identical key set to SXT-028e's `DistortionParams` (the parameters are
    the same twelve; only the shaper branch differs), with the model-index
    admissibility inverted: 3..7 here, 0..2 there.
    """

    KEYS = ("preeq_gain_f", "preeq_freq_f", "preeq_bw_f", "preeq_highcut_f",
            "drive_f", "feedback_f", "posteq_gain_f", "posteq_freq_f",
            "posteq_bw_f", "posteq_highcut_f", "gain_f", "model_i",
            "preeq_highcut_deactivated", "posteq_highcut_deactivated",
            "preeq_gain_extend", "posteq_gain_extend", "drive_extend")

    def __init__(self, d):
        missing = [k for k in self.KEYS if k not in d or d[k] is None]
        if missing:
            raise RuntimeError(
                "DistortionSSEParams: fail-closed — unresolved control-plane "
                f"inputs {missing}. These come from the pinned loader's "
                "normalized state (tools/extract_distortion_sse_inputs.py); "
                "they are never guessed or defaulted.")
        for k in self.KEYS:
            setattr(self, k, d[k])
        self.model_i = int(self.model_i)
        if self.model_i in TABLE_BRANCH_MODELS:
            raise RuntimeError(
                f"Distortion FX model index {self.model_i} "
                f"({FXWS_NAMES[self.model_i]}) is the SXT-028e (#57) "
                "`lookup_waveshape` table branch, NOT this leaf's "
                "`GetQuadWaveshaper` branch. Refusing — fail-closed; use "
                "model/effects/type-distortion/distortion_model.py. Running "
                "it through the quad shaper would be an ADAPTED effect.")
        if self.model_i not in SSE_MODELS:
            raise RuntimeError(
                f"Distortion FX model index {self.model_i} is outside "
                "n_fxws = 8 (FilterConfiguration.h:235). Refusing "
                "(fail-closed).")


class DistortionSSEState:
    """Per-instance state: the whole #57 chain PLUS the quad-waveshaper
    registers. Two slots = two of these, never shared."""

    def __init__(self, name="distortion-sse"):
        self.name = name
        self.chain = DistortionState(name)
        self.ws = QuadWaveshaperState()

    # READ-ONLY delegation of the #57 chain fields, so a harness can read
    # `st.fb_l` / `st.band1` / ... off one object. Writes must go through
    # `st.chain` explicitly; nothing in this leaf writes through the proxy.
    def __getattr__(self, item):
        chain = self.__dict__.get("chain")
        if chain is None:
            raise AttributeError(item)
        return getattr(chain, item)

    def checkpoint(self):
        """Declared state checkpoint (RTL/model integer equality).

        The #57 chain checkpoint verbatim, PLUS the quad-waveshaper
        registers and the per-lane `init` mask — the issue's acceptance
        requires those "among the declared state checkpoints".
        """
        d = self.chain.checkpoint()
        d.update(self.ws.checkpoint())
        d["name"] = self.name
        return d


class DistortionSSEModel:
    """One Distortion instance running the SSE quad-waveshaper branch.

    `chain_probe_shaper` is a VERIFICATION HOOK, not a feature: when set to
    a callable `(x_a) -> y_a` the quad shaper, the drive normalization, the
    drive interpolation and the DC-offset probe are all bypassed and the
    block schedule degenerates to exactly SXT-028e's. It exists so
    `tests/test_sxt028e_sse.py` can prove — bit for bit — that this leaf
    reuses the #57 chain unchanged rather than re-deriving it. Passing it
    for any other purpose would be a generic substitute under a support
    claim, which this repository refuses; the model records the fact in
    `chain_probe_mode` and the RTL has no such path at all.
    """

    def __init__(self, params: DistortionSSEParams, name="distortion-sse",
                 chain_probe_shaper=None):
        self.p = params
        self.st = DistortionSSEState(name)
        self.shaper = get_quad_waveshaper(params.model_i)
        self.shaper_name = shaper_name(params.model_i)
        self.skip_drive_norm = SKIP_DRIVE_NORM[params.model_i]
        self.chain_probe_shaper = chain_probe_shaper
        self.chain_probe_mode = chain_probe_shaper is not None
        self.ctrl = {}
        self.initialized = False

    # ------------------------------------------------------------------
    # control rate (identical to SXT-028e; reused, not re-derived)
    # ------------------------------------------------------------------
    def _pregain(self):
        return get_extended(self.p.preeq_gain_f, "ct_decibel_extendable",
                            self.p.preeq_gain_extend)

    def _postgain(self):
        return get_extended(self.p.posteq_gain_f, "ct_decibel_extendable",
                            self.p.posteq_gain_extend)

    def _drive_db(self):
        return get_extended(self.p.drive_f, "ct_decibel_narrow_extendable",
                            self.p.drive_extend)

    def _setvars_false(self):
        p, st = self.p, self.st.chain
        st.band1.new_targets(coeff_peak_eq(
            calc_omega(p.preeq_freq_f / 12.0), p.preeq_bw_f, self._pregain()))
        st.band2.new_targets(coeff_peak_eq(
            calc_omega(p.posteq_freq_f / 12.0), p.posteq_bw_f,
            self._postgain()))
        st.lp1.set_coeff(coeff_lp2b(
            calc_omega((p.preeq_highcut_f / 12.0) - _f32(2.0)), 0.707))
        st.lp2.set_coeff(coeff_lp2b(
            calc_omega((p.posteq_highcut_f / 12.0) - _f32(2.0)), 0.707))

    def initialize(self):
        """`DistortionEffect::init()` == `suspend()`.

        The #57 sequence verbatim, plus `wsState.R[i] = setzero_ps()` (the
        engine's own last four lines of `init()`). See quad_shapers DD-3 for
        why `wsState.init` is frozen here even though the engine leaves it
        indeterminate.
        """
        p, st = self.p, self.st.chain
        st.drive = Lipol()
        st.outgain = Lipol()
        st.band1.new_targets(coeff_peak_eq(
            calc_omega(p.preeq_freq_f / 12.0), p.preeq_bw_f, self._pregain()))
        st.band2.new_targets(coeff_peak_eq(
            calc_omega(p.posteq_freq_f / 12.0), p.posteq_bw_f,
            self._postgain()))
        st.drive.set_target_smoothed(to_q(db_to_linear_d(self._drive_db()),
                                          G_FMT))
        st.outgain.set_target_smoothed(to_q(db_to_linear_d(p.gain_f), G_FMT))
        st.band1.suspend()
        st.band2.suspend()
        st.lp1.suspend()
        st.lp2.suspend()
        st.hr_a.reset()
        st.hr_b.reset()
        st.bi = 0
        st.fb_l = 0
        st.fb_r = 0
        self.st.ws.engine_init()
        self.initialized = True

    @staticmethod
    def ringout_mul(ringout):
        """Reused verbatim from SXT-028e (the declared 1600/320 tail)."""
        return DistortionModel.ringout_mul(ringout)

    def dc_offset(self, d_s_c):
        """The zero-input DC-offset probe.

        `DistortionEffect::process` builds a THROW-AWAY `QuadWaveshaperState`
        (registers AND `init` explicitly zeroed), evaluates the shaper on a
        zero vector at drive `dS` — the block's START drive, not `dNow` —
        and subtracts lane 0 of the result from every output sample of the
        block. The live `wsState` is not touched by the probe; the
        `mutant-dcprobe-live` control runs the probe on the live state and
        must FAIL.
        """
        probe = self.st.ws.probe_state()
        return self.shaper(probe, 0, 0, d_s_c)

    def control_words(self):
        """The declared control-plane boundary (model -> RTL), one block.

        Identical layout to SXT-028e's so the two leaves' harnesses stay
        comparable; the flags word carries three model bits instead of two
        because this leaf's indices run 3..7.

        [0]  drive RAW lipol target dE         Q13.18 (RTL: dE, and ramp input)
        [1]  outgain RAW lipol target          Q13.18 (ringoutMul folded in)
        [2]  feedback coefficient fb           Q10.21
        [3:8]   band1 coefficient targets      Q24.43
        [8:13]  band2 coefficient targets      Q24.43
        [13:18] lp1 instantized coefficients   Q24.43
        [18:23] lp2 instantized coefficients   Q24.43
        [23] flags: bit0 lp1 active, bit1 lp2 active, bits 2..4 FX model
        """
        c = self.ctrl
        st = self.st.chain
        flags = (int(c["lp1_on"]) | (int(c["lp2_on"]) << 1)
                 | (self.p.model_i << 2))
        return ([c["drive_raw"], c["og_raw"], c["fb_q"]]
                + list(st.band1.tgt) + list(st.band2.tgt)
                + list(st.lp1.coeff) + list(st.lp2.coeff) + [flags])

    def init_words(self):
        """Plain `setvars(true)` lipol targets consumed by the RTL at reset."""
        drive, outgain = Lipol(), Lipol()
        drive.set_target_smoothed(to_q(db_to_linear_d(self._drive_db()),
                                       G_FMT))
        outgain.set_target_smoothed(to_q(db_to_linear_d(self.p.gain_f), G_FMT))
        return [drive.target, outgain.target]

    # ------------------------------------------------------------------
    # audio rate
    # ------------------------------------------------------------------
    def process_block(self, in_l, in_r, ringout=0, tap_hook=None):
        """One 32-sample block. Returns (out_l, out_r) Q10.21.

        The schedule is `DistortionEffect::process` in order; the ONLY
        difference from SXT-028e is steps 5b/5c (drive normalization, quad
        shaper, DC-offset subtraction, drive interpolation).
        """
        if not self.initialized:
            self.initialize()
        st, p, ws = self.st.chain, self.p, self.st.ws

        if st.bi == 0:
            self._setvars_false()
        st.bi = (st.bi + 1) & SLOWRATE_M1

        # 1. band1.process_block (pre-EQ, lagged TDF2, base rate)
        work_l = [0] * BLOCK
        work_r = [0] * BLOCK
        for k in range(BLOCK):
            work_l[k], work_r[k] = st.band1.process_sample(in_l[k], in_r[k])

        # 2. drive: dS = previous target, dE = the new raw value
        d_s = st.drive.target
        d_e = to_q(db_to_linear_d(self._drive_db()), G_FMT)
        st.drive.set_target_smoothed(d_e)

        # 3. outgain target with the ringout fade folded in (control rate)
        rmul = self.ringout_mul(ringout)
        og_raw = to_q(db_to_linear_d(p.gain_f) * rmul, G_FMT)
        st.outgain.set_target_smoothed(og_raw)

        fb_q = to_q(clip(p.feedback_f, -1.0, 1.0), A_FMT)
        lp1_on = not p.preeq_highcut_deactivated
        lp2_on = not p.posteq_highcut_deactivated

        # 4. the SSE-branch control quantities (see DRIVE_INTERP_DIVISOR)
        d_s_c = fsat(d_s << (FC - FG), W64)
        d_e_c = fsat(d_e << (FC - FG), W64)
        d_d = fsat((d_e - d_s) << _DD_SHIFT, W64)
        d_now = d_s_c
        dc_offset = 0 if self.chain_probe_mode else self.dc_offset(d_s_c)

        self.ctrl = {"drive_raw": d_e, "og_raw": og_raw, "fb_q": fb_q,
                     "lp1_on": lp1_on, "lp2_on": lp2_on,
                     "ringout": ringout, "ringout_mul": rmul,
                     "d_s": d_s, "d_e": d_e, "d_s_c": d_s_c, "d_e_c": d_e_c,
                     "d_d": d_d, "dc_offset": dc_offset}

        # 5. drive.multiply_2_blocks (in place, base rate)
        for k in range(BLOCK):
            g = st.drive.line_value(k)
            work_l[k] = _qmul_ga(g, work_l[k])
            work_r[k] = _qmul_ga(g, work_r[k])

        # 6. 4x oversampled feedback + quad-shaper loop
        b_l = [0] * OS_BLOCK
        b_r = [0] * OS_BLOCK
        for k in range(BLOCK):
            l_in = work_l[k]
            r_in = work_r[k]
            for s in range(DISTORTION_OS):
                st.fb_l = _qadd_a(l_in, _qmul_aa(fb_q, st.fb_l))
                st.fb_r = _qadd_a(r_in, _qmul_aa(fb_q, st.fb_r))
                if lp1_on:
                    st.fb_l, st.fb_r = st.lp1.process_sample(st.fb_l, st.fb_r)

                if self.chain_probe_mode:
                    # VERIFICATION HOOK ONLY (see the class docstring)
                    st.fb_l = self.chain_probe_shaper(st.fb_l)
                    st.fb_r = self.chain_probe_shaper(st.fb_r)
                else:
                    if self.skip_drive_norm:
                        # DIGITAL divides by drive internally; the usual
                        # `dInv` pre-scale would divide twice and make the
                        # loop gain |fb|/drive. Skipped, as written.
                        sb_l = fsat(st.fb_l << _A_TO_C, W64)
                        sb_r = fsat(st.fb_r << _A_TO_C, W64)
                    else:
                        d_inv = frecip(d_now, FC, FC, W64, ws)
                        sb_l = fmul_counted(fsat(st.fb_l << _A_TO_C, W64),
                                            d_inv, FC, FC, FC, W64, ws)
                        sb_r = fmul_counted(fsat(st.fb_r << _A_TO_C, W64),
                                            d_inv, FC, FC, FC, W64, ws)
                    o_l = self.shaper(ws, 0, sb_l, d_now)
                    o_r = self.shaper(ws, 1, sb_r, d_now)
                    st.fb_l = fcv(fsub(o_l, dc_offset, W64), FC, FA, W32)
                    st.fb_r = fcv(fsub(o_r, dc_offset, W64), FC, FA, W32)
                    d_now = fadd(d_now, d_d, W64)

                # engine denormal bias +-1e-8: below the Q10.21 LSB, declared
                if lp2_on:
                    st.fb_l, st.fb_r = st.lp2.process_sample(st.fb_l, st.fb_r)
                idx = s + (k << DIST_OS_BITS)
                b_l[idx] = st.fb_l
                b_r[idx] = st.fb_r
                if tap_hook is not None and k < 4:
                    tap_hook(k, s, st.fb_l, st.fb_r)
        self.ctrl["d_now_end"] = d_now

        # 7. two-stage halfband decimation: 128 -> 64 -> 32 (#57, unchanged)
        b_l, b_r = st.hr_a.process(b_l, b_r)
        b_l, b_r = st.hr_b.process(b_l, b_r)

        # 8. outgain.multiply_2_blocks_to + band2 (post-EQ) (#57, unchanged)
        out_l = [0] * BLOCK
        out_r = [0] * BLOCK
        for k in range(BLOCK):
            g = st.outgain.line_value(k)
            out_l[k] = _qmul_ga(g, b_l[k])
            out_r[k] = _qmul_ga(g, b_r[k])
        for k in range(BLOCK):
            out_l[k], out_r[k] = st.band2.process_sample(out_l[k], out_r[k])
        return out_l, out_r


# --- the three shared-chain audio-rate primitives, in the frozen formats ---
def _qmul_ga(g, x):
    return qmul(g, x, G_FMT, A_FMT, A_FMT)


def _qmul_aa(a, b):
    return qmul(a, b, A_FMT, A_FMT, A_FMT)


def _qadd_a(a, b):
    return qadd(a, b, A_FMT)


def table_branch_shaper(model_i=0):
    """The #57 table shaper, for the chain-equivalence verification hook."""
    tbl = ws_tables.TABLES[model_i]
    return lambda x: lookup_waveshape(tbl, x)


def model_revision():
    """sha256 of the three frozen files (revision pin for traces/harnesses)."""
    import hashlib
    global MODEL_REVISION
    if MODEL_REVISION is None:
        h = hashlib.sha256()
        for name in ("sse_tables.py", "quad_shapers.py",
                     "distortion_sse_model.py"):
            with open(os.path.join(_HERE, name), "rb") as f:
                h.update(f.read())
        MODEL_REVISION = h.hexdigest()
    return MODEL_REVISION


__all__ = ["DistortionSSEModel", "DistortionSSEParams", "DistortionSSEState",
           "QuadWaveshaperState", "table_branch_shaper", "model_revision",
           "table_digest", "HalfbandD2", "HB_COEFFS_Q", "BLOCK", "OS_BLOCK",
           "DISTORTION_OS", "RINGOUT_TIME", "RINGOUT_END", "SLOWRATE",
           "SSE_MODELS", "REGISTER_USE", "READS_INIT", "SKIP_DRIVE_NORM",
           "DRIVE_INTERP_DIVISOR", "SAMPLERATE", "FRAC",
           "A_FMT", "G_FMT", "C_FMT"]
