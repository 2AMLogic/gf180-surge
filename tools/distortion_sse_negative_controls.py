#!/usr/bin/env python3
"""SXT-028e-sse model-side negative controls (each must FAIL its target).

Follows `tools/distortion_negative_controls.py` (SXT-028e) exactly, including
its grading boundary and its honesty caveats, and REUSES that file's
independent float chain primitives (`FBiquad`, `FNoLag`, `FHalfband`,
`GenericSubstitute`) so the two leaves' controls cannot drift apart. Only the
shaper step is new here.

SCOPE OF THE CHECK BEING TARGETED. The controls below are graded at the
**model boundary**: variant-vs-frozen-model, using the SXT-023 effect-slice
[PROPOSED] budget metrics (max abs diff <= 8192 LSB Q10.21; residual RMS
<= -46 dBFS; spectral correlation >= 0.98). Those budgets are PROPOSALS, not
frozen policy (freeze is gated on SXT-017, #12).

Grading at the model boundary rather than against the pinned engine is a
DELIBERATE, DECLARED limitation, not a substitute claim: the pinned oracle is
not reachable in this environment, so the reference leg of every control is
reported NOT_RUN in reports/SXT-028e-sse/EVIDENCE.md.

Baseline sanity comes FIRST and in two legs, because this leaf contains two
shapers whose closed loop is genuinely chaotic (see F-028e-sse-4):

  NC-0  OPEN-LOOP shaper agreement. Each of the five quad shapers, frozen
        fixed-point vs an INDEPENDENT float implementation written from the
        pinned sources, over a dense input/drive sweep. Must agree within a
        declared 4-LSB-Q10.21 tolerance. This isolates exactly what this
        leaf adds, with no feedback loop to amplify anything.
  NC-0b CLOSED-LOOP structural twin vs frozen model, one leg per FX model,
        graded against the SXT-023 [PROPOSED] budgets AND against a measured
        SENSITIVITY FLOOR: the same float twin compared with itself after a
        ONE-Q13.18-LSB perturbation of `dNow` (the frozen drive word's own
        resolution). FX models 3/5/6 pass the [PROPOSED] budgets outright.
        FX models 4 (`wst_digital`, a hard staircase quantizer) and 7
        (`wst_fuzzsoft`, a pseudo-random LUT) do NOT, and their divergence
        is at or below their own sensitivity floor -- i.e. the frozen model
        is no further from the twin than the twin is from ITSELF under a
        one-LSB drive nudge. That is reported as a FINDING routed to
        SXT-017 (#12), never as a pass, and never by relaxing a budget.
        SCOPE: for FX models 4 and 7 this leg is CHARACTERIZATION, not a
        gate -- the metric provably cannot discriminate there, so NC-0b's
        CONTROL-OK must not be read as "models 4 and 7 verified". The
        falsifiable weight for those two sits in NC-0 (open loop) and in
        the unconditional RTL-vs-frozen-model exactness leg.

Controls
  NC-A substitute  "convenient generic" distortion (single-rate tanh clip)
                   -> ADAPTED, must FAIL
  NC-A2 cross-leaf the SXT-028e (#57) TABLE shaper substituted for the quad
                   shaper -- the single most plausible real shortcut for
                   this leaf ("models 3..7 are just other waveshapes")
                   -> ADAPTED, must FAIL
  NC-B tail        render truncated before the declared 1600-block ringout
                   span -> must FAIL the tail check
  NC-C order       band1/band2 order swapped -> must FAIL
  NC-D wsshared    two instances pooling ONE QuadWaveshaperState (the chain
                   state stays per-instance, so this isolates exactly the
                   state this leaf adds) -> must FAIL
  NC-E stale       a stale frozen-revision pin -> must REFUSE (never PASS)
  NC-F drivestep   dD = (dE - dS)/128 "corrected" from the pinned /64
                   -> must FAIL (graded on the DIGITAL bed, the only model
                   where dNow is observable at all)
  NC-G diginorm    `skipDriveNorm` removed: DIGITAL gets the 1/dNow
                   pre-scale too -> must FAIL
  NC-H dcprobe     the zero-input DC-offset probe dropped -> must FAIL

BEDS. NC-A/NC-A2/NC-C are graded on FX model 5 (`wst_ojd`), whose measured
sensitivity floor is about -112 dBFS, so a control's margin over the floor is
unambiguous; grading them on model 7 would put the control only ~15 dB above
that model's own -31 dBFS chaos floor. NC-D/NC-B use FX model 6, the other
register-owning shaper. NC-F/NC-G/NC-H use FX model 4.

WHY SOME CONTROLS ARE GRADED ON A DIGITAL BED. For FX models 3, 5, 6 and 7
the `1/dNow` pre-scale and the shaper's own leading `x * drive` cancel
algebraically, so `dNow` -- and therefore the /64 interpolation step -- is
NOT observable at the output for those models. It IS observable for model 4
(`wst_digital`), which is exactly the model the pinned source singles out
with `skipDriveNorm`. Grading NC-F/NC-G on a non-digital bed would produce a
control that cannot fail; that would be theatre, so they are graded where the
defect is reachable and this restriction is recorded here and in the JSON.

Usage: python3 tools/distortion_sse_negative_controls.py [--out DIR]
Original to this repository (Apache-2.0).
"""

import argparse
import importlib.util
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

from distortion_sse_model import (  # noqa: E402
    DistortionSSEModel, DistortionSSEParams, model_revision, BLOCK,
    RINGOUT_TIME, DRIVE_INTERP_DIVISOR,
)
from distortion_model import (  # noqa: E402
    DistortionModel, HB_A_SOFT, HB_B_SOFT, HB_A_STEEP, HB_B_STEEP,
    coeff_peak_eq, coeff_lp2b, calc_omega, get_extended,
)
import sse_tables  # noqa: E402
import ws_tables  # noqa: E402
from model.effects.delay.delay_model import db_to_linear_d  # noqa: E402


def _load_sxt028e_controls():
    """Reuse SXT-028e's float chain primitives rather than re-deriving them."""
    path = os.path.join(REPO, "tools", "distortion_negative_controls.py")
    spec = importlib.util.spec_from_file_location("sxt028e_controls", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NC57 = _load_sxt028e_controls()
FBiquad = NC57.FBiquad
FNoLag = NC57.FNoLag
FHalfband = NC57.FHalfband
GenericSubstitute = NC57.GenericSubstitute
metrics = NC57.metrics
verdict = NC57.verdict
stimulus = NC57.stimulus
PROPOSED = NC57.PROPOSED
RMS_FLOOR_DBFS = NC57.RMS_FLOOR_DBFS

LSB = 1 << 21

BASE = dict(preeq_gain_f=6.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
            preeq_highcut_f=70.0, drive_f=6.0, feedback_f=0.635445,
            posteq_gain_f=-4.5, posteq_freq_f=24.0, posteq_bw_f=1.1,
            posteq_highcut_f=30.535736, gain_f=0.0, model_i=5,
            preeq_highcut_deactivated=False,
            posteq_highcut_deactivated=False,
            preeq_gain_extend=False, posteq_gain_extend=False,
            drive_extend=False)
# Primary bed: FX model 5 (wst_ojd) -- smooth, measured sensitivity floor
# about -112 dBFS, so a control's margin over the floor is unambiguous.
PARAMS = dict(BASE)
# Register-owning bed: FX model 6 (wst_fwrectify), ADAA registers + `init`.
REG_PARAMS = dict(BASE, model_i=6)
# The DIGITAL bed (see the module docstring): the only model where dNow is
# observable, so the only one on which NC-F / NC-G can fail at all.
DIGI_PARAMS = dict(BASE, model_i=4, drive_f=12.0, feedback_f=0.35,
                   gain_f=-6.0)
# The chaotic bed: FX model 7 (wst_fuzzsoft), kept for the NC-0b
# characterization and for NC-H's second leg.
FUZZ_PARAMS = dict(BASE, model_i=7)

# NC-0 open-loop tolerance: 4 LSB of Q10.21 expressed in the shaper's own
# value domain. Declared here, not tuned to the result.
OPEN_LOOP_TOL = 4.0 / (1 << 21)
# NC-0b: how far above its own measured sensitivity floor a model-vs-twin
# residual may sit and still count as "at the floor". Declared, not tuned.
FLOOR_MARGIN_DB = 3.0
# One Q13.18 LSB -- the frozen drive-ramp word's own resolution. Perturbing
# `dNow` by exactly this measures the algorithm's sensitivity to a difference
# the frozen word cannot even represent.
DRIVE_LSB = 1.0 / (1 << 18)

SINE_ROW = [v / (1 << 29) for v in sse_tables.TABLES["sine"]]
FUZZ_ROW = [v / (1 << 29) for v in sse_tables.TABLES["fuzz1"]]


# ---------------------------------------------------------------------------
# independent float quad waveshapers (NC-0's twin)
# ---------------------------------------------------------------------------
def _rne(x):
    """`_mm_cvtps_epi32`: round half to even (the default MXCSR mode)."""
    return int(round(x))


def _packs16(e):
    return 32767 if e > 32767 else (-32768 if e < -32768 else e)


class FQuadState:
    def __init__(self):
        self.R = [[0.0, 0.0] for _ in range(4)]
        self.init = [True, True]


def f_sinus(st, lane, x, drive):
    x = x * drive
    x = x * 256.0 + 512.0
    e_raw = _rne(x)
    a = x - float(e_raw)
    e = _packs16(e_raw)
    e = 0 if e < 0 else (0x3fe if e > 0x3fe else e)
    return (1 - a) * SINE_ROW[e & 0x3ff] + a * SINE_ROW[(e + 1) & 0x3ff]


def f_digi(st, lane, x, drive):
    invdrive = (1.0 / drive) if drive != 0 else float(1 << 20)
    a = _rne(0.5 + invdrive * (16.0 * x))
    return drive * (0.0625 * (float(a) - 0.5))


_OJD_DENLOW = 1.0 / (4 * (1 - 0.3))
_OJD_DENHIGH = 1.0 / (4 * (1 - 0.9))


def f_ojd(st, lane, x, drive):
    x = x * drive
    if x <= -1.7:
        return -1.0
    if x >= 1.1:
        return 1.0
    if x < -0.3:
        xl = x + 0.3
        return (xl + _OJD_DENLOW * xl * xl) - 0.3
    if x > 0.9:
        xh = x - 0.9
        return (xh - _OJD_DENHIGH * xh * xh) + 0.9
    return x


def f_clip(x, drive):
    return max(-1.0, min(1.0, x * drive))


def f_tanh(x, drive):
    x = x * drive
    xx = x * x
    return max(-1.0, min(1.0, x * (27.0 + xx) / (27.0 + 9.0 * xx)))


def f_fwrect(st, lane, x, drive):
    x = f_clip(x, drive)
    f_val = abs(x)
    adf = f_val * (x * 0.5)
    dx = x - st.R[0][lane]
    dad = adf - st.R[1][lane]
    ltt = (-1e-4 < dx < 1e-4) or st.init[lane]
    den = 1e-4 if ltt else dx
    r = f_val if ltt else dad * (1.0 / den)
    st.R[0][lane] = x
    st.R[1][lane] = adf
    st.init[lane] = False
    return r


def f_fuzzsoft(st, lane, x, drive):
    c = f_tanh(x, drive)
    xx = c * 512.0 + 512.0
    xc = max(0.0, min(1023.0, xx))
    e = _packs16(_rne(xc))
    frac = xx - float(e)
    v = (1 - frac) * FUZZ_ROW[e] + frac * FUZZ_ROW[e + 1]
    dx = v - st.R[0][lane]
    filtval = dx + 0.9999 * st.R[1][lane]
    st.R[0][lane] = v
    st.R[1][lane] = filtval
    st.init[lane] = False
    return filtval


F_SHAPERS = {3: f_sinus, 4: f_digi, 5: f_ojd, 6: f_fwrect, 7: f_fuzzsoft}


class FloatSSETwin:
    """Independent float implementation of the pinned SSE Distortion branch.

    The chain primitives come from SXT-028e's own float twin (reuse, not
    re-derivation); only the shaper step is written here, from the pinned
    sst-waveshapers sources. Every negative control is ONE switch on this
    same twin, so a control differs from the baseline in exactly one
    structural respect.
    """

    def __init__(self, p, swap_bands=False, drive_div=None,
                 force_drive_norm=False, drop_dc_probe=False,
                 table_shaper=None):
        self.p = p
        self.swap_bands = swap_bands
        self.drive_div = drive_div or DRIVE_INTERP_DIVISOR
        self.force_drive_norm = force_drive_norm
        self.drop_dc_probe = drop_dc_probe
        self.table_shaper = table_shaper
        self.model_i = int(p["model_i"])
        self.shaper = F_SHAPERS[self.model_i]
        self.skip_norm = (self.model_i == 4) and not force_drive_norm
        self.b1, self.b2 = FBiquad(), FBiquad()
        self.l1, self.l2 = FNoLag(), FNoLag()
        self.ha = FHalfband(HB_A_SOFT, HB_B_SOFT)
        self.hb = FHalfband(HB_A_STEEP, HB_B_STEEP)
        self.ws = FQuadState()
        self.dr_t = self.dr_c = 0.0
        self.og_t = self.og_c = 0.0
        self.L = self.R = 0.0
        self.bi = 0
        self.init()

    def _pre(self):
        return get_extended(self.p["preeq_gain_f"], "ct_decibel_extendable",
                            self.p["preeq_gain_extend"])

    def _post(self):
        return get_extended(self.p["posteq_gain_f"], "ct_decibel_extendable",
                            self.p["posteq_gain_extend"])

    def _drv(self):
        return get_extended(self.p["drive_f"],
                            "ct_decibel_narrow_extendable",
                            self.p["drive_extend"])

    def _c1(self):
        return [v / (1 << 43) for v in coeff_peak_eq(
            calc_omega(self.p["preeq_freq_f"] / 12.0), self.p["preeq_bw_f"],
            self._pre())]

    def _c2(self):
        return [v / (1 << 43) for v in coeff_peak_eq(
            calc_omega(self.p["posteq_freq_f"] / 12.0), self.p["posteq_bw_f"],
            self._post())]

    def init(self):
        self.b1.new_targets(self._c1())
        self.b2.new_targets(self._c2())
        self.dr_t = 0.25 * db_to_linear_d(self._drv())
        self.og_t = 0.25 * db_to_linear_d(self.p["gain_f"])
        self.b1.suspend()
        self.b2.suspend()
        self.l1.suspend()
        self.l2.suspend()

    def _dc_offset(self, d_s):
        if self.drop_dc_probe:
            return 0.0
        probe = FQuadState()
        probe.init = [False, False]
        return self.shaper(probe, 0, 0.0, d_s)

    def block(self, il, ir, ringout=0):
        p = self.p
        if self.bi == 0:
            self.b1.new_targets(self._c1())
            self.b2.new_targets(self._c2())
            self.l1.lag = [v / (1 << 43) for v in coeff_lp2b(
                calc_omega(p["preeq_highcut_f"] / 12.0 - 2.0), 0.707)]
            self.l2.lag = [v / (1 << 43) for v in coeff_lp2b(
                calc_omega(p["posteq_highcut_f"] / 12.0 - 2.0), 0.707)]
        self.bi = (self.bi + 1) & 7

        pre, post = (self.b2, self.b1) if self.swap_bands else (self.b1, self.b2)
        w = [pre.ps(il[k], ir[k]) for k in range(BLOCK)]
        wl = [x[0] for x in w]
        wr = [x[1] for x in w]

        d_s = self.dr_t
        d_e = db_to_linear_d(self._drv())
        self.dr_c = self.dr_t
        self.dr_t = 0.25 * d_e + 0.75 * self.dr_t
        rmul = DistortionModel.ringout_mul(ringout)
        self.og_c = self.og_t
        self.og_t = 0.25 * db_to_linear_d(p["gain_f"]) * rmul + 0.75 * self.og_t

        d_d = (d_e - d_s) / self.drive_div
        d_now = d_s
        dc = self._dc_offset(d_s)

        for k in range(BLOCK):
            g = self.dr_c + (self.dr_t - self.dr_c) * (k + 1) / 32.0
            wl[k] *= g
            wr[k] *= g

        fb = max(-1.0, min(1.0, p["feedback_f"]))
        bl = [0.0] * 128
        br = [0.0] * 128
        for k in range(BLOCK):
            for s in range(4):
                self.L = wl[k] + fb * self.L
                self.R = wr[k] + fb * self.R
                if not p["preeq_highcut_deactivated"]:
                    self.L, self.R = self.l1.ps(self.L, self.R)
                if self.table_shaper is not None:
                    self.L = self.table_shaper(self.L)
                    self.R = self.table_shaper(self.R)
                else:
                    if self.skip_norm:
                        sl, sr = self.L, self.R
                    else:
                        dinv = (1.0 / d_now) if d_now != 0 else float(1 << 20)
                        sl, sr = self.L * dinv, self.R * dinv
                    self.L = self.shaper(self.ws, 0, sl, d_now) - dc
                    self.R = self.shaper(self.ws, 1, sr, d_now) - dc
                    d_now += d_d
                if not p["posteq_highcut_deactivated"]:
                    self.L, self.R = self.l2.ps(self.L, self.R)
                bl[s + (k << 2)] = self.L
                br[s + (k << 2)] = self.R
        bl, br = self.ha.process(bl, br)
        bl, br = self.hb.process(bl, br)
        ol = [0.0] * BLOCK
        orr = [0.0] * BLOCK
        for k in range(BLOCK):
            g = self.og_c + (self.og_t - self.og_c) * (k + 1) / 32.0
            ol[k] = bl[k] * g
            orr[k] = br[k] * g
        out = [post.ps(ol[k], orr[k]) for k in range(BLOCK)]
        return [x[0] for x in out], [x[1] for x in out]


def table_shaper_float(model_i=0):
    """NC-A2: the SXT-028e (#57) `lookup_waveshape` shaper, in float."""
    tbl = [v / (1 << 29) for v in ws_tables.TABLES[model_i]]

    def f(x):
        y = x * 32.0 + 512.0
        e = int(y)
        a = y - e
        if e > 0x3fd:
            return 1.0
        if e < 1:
            return -1.0
        return (1 - a) * tbl[e & 0x3ff] + a * tbl[(e + 1) & 0x3ff]
    return f


def open_loop_probe(model_i, n=20000, seed=3):
    """NC-0: frozen fixed-point shaper vs the independent float shaper.

    Open loop, so nothing can amplify a difference: a dense pseudo-random
    input sweep at several drives, straight through `GetQuadWaveshaper`'s
    fixed-point and float implementations of the SAME pinned kernel. The
    per-instance registers advance on both sides, so the stateful shapers
    (6, 7) are exercised as recurrences, not as memoryless maps.
    """
    import random
    import quad_shapers as qs
    rs = random.Random(seed)
    fx = qs.SHAPERS[model_i]
    ff = F_SHAPERS[model_i]
    stq = qs.QuadWaveshaperState()
    stf = FQuadState()
    worst = 0.0
    total = 0.0
    for i in range(n):
        drive_f = (0.25, 1.0, 2.0, 8.0)[i & 3]
        drive_c = qs.fq(drive_f, qs.FC)
        x = rs.uniform(-1.5, 1.5)
        xc = qs.fq(x, qs.FC)
        a = fx(stq, i & 1, xc, drive_c) / float(1 << qs.FC)
        b = ff(stf, i & 1, x, drive_f)
        d = abs(a - b)
        worst = max(worst, d)
        total += d * d
    return {"samples": n, "max_abs_diff": worst,
            "max_abs_diff_lsb_q10_21": worst * (1 << 21),
            "rms_abs_diff_lsb_q10_21": math.sqrt(total / n) * (1 << 21),
            "tolerance_lsb_q10_21": OPEN_LOOP_TOL * (1 << 21),
            "model": model_i, "shaper": sse_tables.SSE_SHAPER_OF[model_i],
            "within_tolerance": worst <= OPEN_LOOP_TOL}


def sensitivity_floor(p, blocks):
    """The float twin compared with ITSELF after a one-Q13.18-LSB nudge of
    `dNow` -- a difference the frozen drive word cannot even represent.

    This measures how much of a model-vs-twin residual is the ALGORITHM's
    own sensitivity rather than the translation's error. It is a
    measurement, not a budget: the [PROPOSED] budgets are reported
    unchanged alongside it.
    """
    a = run_float(FloatSSETwin(p), blocks)
    pert = FloatSSETwin(p)
    base_shaper = pert.shaper
    pert.shaper = (lambda st, lane, x, d, _s=base_shaper:
                   _s(st, lane, x, d + DRIVE_LSB))
    b = run_float(pert, blocks)
    return metrics(a, b)


def run_frozen(p, blocks, name="frozen"):
    m = DistortionSSEModel(DistortionSSEParams(p), name)
    m.initialize()
    out = []
    for il, ir, ring in blocks:
        ol, orr = m.process_block([int(round(v * LSB)) for v in il],
                                  [int(round(v * LSB)) for v in ir],
                                  ringout=ring)
        out += ol + orr
    return [float(v) for v in out]


def run_float(twin, blocks):
    out = []
    for il, ir, ring in blocks:
        ol, orr = twin.block(il, ir, ringout=ring)
        out += [v * LSB for v in ol] + [v * LSB for v in orr]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "reports",
                                                  "SXT-028e-sse",
                                                  "negative-controls"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    nb = 96
    blocks = stimulus(nb)
    frozen = run_frozen(PARAMS, blocks)                 # FX model 5 bed
    digi_blocks = stimulus(nb, seed=41)
    frozen_digi = run_frozen(DIGI_PARAMS, digi_blocks, "frozen-digital")
    fuzz_blocks = stimulus(nb, seed=53)
    frozen_fuzz = run_frozen(FUZZ_PARAMS, fuzz_blocks, "frozen-fuzz")

    results = []

    # NC-0 OPEN-LOOP shaper agreement (the tight baseline)
    probes = {mi: open_loop_probe(mi) for mi in sse_tables.SSE_MODELS}
    open_ok = all(v["within_tolerance"] for v in probes.values())
    results.append({
        "id": "NC-0", "kind": "baseline-sanity-open-loop",
        "what": "each quad shaper, frozen fixed-point vs an INDEPENDENT "
                "float implementation of the same pinned kernel, open loop "
                "over a dense input x drive sweep (registers advancing)",
        "must": "PASS",
        "verdict": "PASS" if open_ok else "FAIL",
        "ok": open_ok,
        "tolerance_lsb_q10_21": OPEN_LOOP_TOL * (1 << 21),
        "per_model": {str(k): v for k, v in probes.items()},
        "note": "establishes the check has resolving power on exactly what "
                "this leaf adds; NOT a reference claim -- the pinned-oracle "
                "leg is NOT_RUN (F-028e-sse-3)"})

    # NC-0b CLOSED-LOOP twin vs frozen model, per FX model, with the measured
    # sensitivity floor alongside the [PROPOSED] budgets.
    legs = {}
    for mi in sse_tables.SSE_MODELS:
        p = dict(BASE, model_i=mi)
        bl = stimulus(96, seed=17)
        m = metrics(run_frozen(p, bl, f"f{mi}"), run_float(FloatSSETwin(p), bl))
        floor = sensitivity_floor(p, bl)
        at_floor = m["rms_diff_dbfs"] <= floor["rms_diff_dbfs"] + FLOOR_MARGIN_DB
        legs[mi] = {
            "verdict_vs_proposed_budgets": verdict(m),
            "metrics": m,
            "sensitivity_floor": floor,
            "at_or_below_sensitivity_floor": at_floor,
            "status": ("PASS" if verdict(m) == "PASS" else
                       ("AT-SENSITIVITY-FLOOR (budget NOT met; "
                        "finding F-028e-sse-4)" if at_floor
                        else "FAIL (above the sensitivity floor)"))}
    smooth_ok = all(legs[mi]["verdict_vs_proposed_budgets"] == "PASS"
                    for mi in (3, 5, 6))
    chaotic_ok = all(legs[mi]["at_or_below_sensitivity_floor"]
                     for mi in (4, 7))
    budget_met = all(legs[mi]["verdict_vs_proposed_budgets"] == "PASS"
                     for mi in sse_tables.SSE_MODELS)
    results.append({
        "id": "NC-0b", "kind": "baseline-sanity-closed-loop",
        "what": "independent float structural twin vs frozen fixed model "
                "through the whole chain, one leg per reachable FX model",
        "must": "PASS for FX models 3/5/6; CHARACTERIZE (NOT a gate) for 4 "
                "and 7",
        "gate_scope": {
            "gated_models": [3, 5, 6],
            "characterized_models": [4, 7],
            "note": "For FX models 4 and 7 this leg is CHARACTERIZATION, not "
                    "a pass/fail gate: the [PROPOSED] sample-domain metric "
                    "cannot discriminate below the measured sensitivity "
                    "floor (F-028e-sse-4), so the 'at or below the floor' "
                    "clause cannot fail in a way that would indicate a "
                    "defect. CONTROL-OK on NC-0b therefore must NOT be read "
                    "as 'FX models 4 and 7 verified'. What does carry "
                    "falsifiable weight for those two: NC-0's open-loop "
                    "shaper probe, and the unconditional RTL-vs-frozen-model "
                    "exactness leg (rtl-exactness.json)."},
        "verdict": "PASS" if budget_met else
                   "PARTIAL (models 4 and 7 do NOT meet the [PROPOSED] "
                   "sample-domain budgets -- finding F-028e-sse-4)",
        "ok": smooth_ok and chaotic_ok and open_ok,
        "proposed_budgets_met_for_all_models": budget_met,
        "per_model_legs": {str(k): v for k, v in legs.items()},
        "finding": {
            "id": "F-028e-sse-4",
            "routed_to": "#12 (SXT-017 budget freeze)",
            "statement":
                "FX models 4 (wst_digital, a hard staircase quantizer) and 7 "
                "(wst_fuzzsoft, a pseudo-random LUT) sit inside the "
                "Distortion feedback loop, so an arbitrarily small "
                "arithmetic difference can flip a quantizer/LUT decision and "
                "produce a full-step output change. Measured: the frozen "
                "model is no further from the independent float twin than "
                "that twin is from ITSELF under a one-Q13.18-LSB nudge of "
                "dNow -- a difference the frozen drive word cannot even "
                "represent. The SXT-023 sample-domain [PROPOSED] budgets are "
                "therefore not an attainable instrument for these two "
                "models; choosing the right one is SXT-017's decision, not "
                "this leaf's. NO BUDGET IS RELAXED HERE and no leg is "
                "reported as a pass that did not pass.",
            "open_loop_evidence":
                "NC-0 shows the shaper translation itself agrees with the "
                "independent float implementation within "
                f"{OPEN_LOOP_TOL * (1 << 21):.0f} LSB Q10.21 open loop, so "
                "the closed-loop divergence is not a translation error."}})

    # NC-A generic substitute -> ADAPTED
    mA = metrics(frozen, run_float(GenericSubstitute(PARAMS), blocks))
    results.append({
        "id": "NC-A", "kind": "generic-substitute",
        "what": "single-rate tanh clip (no oversampling / halfband / EQ / "
                "feedback / quad-waveshaper state)",
        "must": "FAIL", "verdict": verdict(mA), "metrics": mA,
        "ok": verdict(mA) == "FAIL",
        "label": "ADAPTED — refused from original-preset coverage"})

    # NC-A2 cross-leaf substitute: #57's table shaper in this leaf's chain
    mA2 = metrics(frozen, run_float(
        FloatSSETwin(PARAMS, table_shaper=table_shaper_float(0)), blocks))
    results.append({
        "id": "NC-A2", "kind": "cross-leaf-substitute",
        "what": "the SXT-028e (#57) lookup_waveshape table shaper "
                "(wst_soft) substituted for GetQuadWaveshaper, with the "
                "rest of the chain untouched",
        "must": "FAIL", "verdict": verdict(mA2), "metrics": mA2,
        "ok": verdict(mA2) == "FAIL",
        "label": "ADAPTED — 'models 3..7 are just other waveshapes' is the "
                 "shortcut this leaf exists to refuse; the frozen model "
                 "REFUSES indices 0..2 and #57 REFUSES 3..7"})

    # NC-C wrong order (band1/band2 swapped)
    mC = metrics(frozen, run_float(FloatSSETwin(PARAMS, swap_bands=True),
                                   blocks))
    results.append({
        "id": "NC-C", "kind": "wrong-order",
        "what": "pre-EQ and post-EQ bands swapped around the shaper",
        "must": "FAIL", "verdict": verdict(mC), "metrics": mC,
        "ok": verdict(mC) == "FAIL"})

    # NC-F drive-interpolation step "corrected" to /128 (DIGITAL bed)
    mF = metrics(frozen_digi, run_float(
        FloatSSETwin(DIGI_PARAMS, drive_div=128), digi_blocks))
    mF_benign = metrics(frozen_fuzz, run_float(
        FloatSSETwin(FUZZ_PARAMS, drive_div=128), fuzz_blocks))
    results.append({
        "id": "NC-F", "kind": "drive-interpolation-step",
        "what": "dD = (dE - dS)/128 instead of the pinned "
                "/(BLOCK_SIZE * dist_OS_bits) = /64",
        "must": "FAIL", "verdict": verdict(mF), "metrics": mF,
        "ok": verdict(mF) == "FAIL",
        "graded_on": "FX model 4 (wst_digital)",
        "benign_model_leg": {
            "model": 7, "verdict": verdict(mF_benign), "metrics": mF_benign,
            "note": "for models 3/5/6/7 the 1/dNow pre-scale and the "
                    "shaper's leading x*drive cancel, so dNow is NOT "
                    "observable and the /128 variant is indistinguishable. "
                    "Recorded as a REACHABILITY property of the defect, not "
                    "as evidence that /128 is acceptable — the RTL "
                    "exactness check rejects it unconditionally "
                    "(rtl-exactness.json mutant_controls[mutant-drivestep128], "
                    "graded on the digital bed)."}})

    # NC-G skipDriveNorm removed (DIGITAL bed)
    mG = metrics(frozen_digi, run_float(
        FloatSSETwin(DIGI_PARAMS, force_drive_norm=True), digi_blocks))
    results.append({
        "id": "NC-G", "kind": "digital-drive-normalization",
        "what": "`skipDriveNorm` removed: wst_digital receives the 1/dNow "
                "pre-scale as well, so the signal is divided by drive twice "
                "and the feedback loop gain becomes |fb|/drive",
        "must": "FAIL", "verdict": verdict(mG), "metrics": mG,
        "ok": verdict(mG) == "FAIL",
        "graded_on": "FX model 4 (wst_digital)"})

    # NC-H DC-offset probe dropped (DIGITAL bed: dcOffset != 0 there)
    mH = metrics(frozen_digi, run_float(
        FloatSSETwin(DIGI_PARAMS, drop_dc_probe=True), digi_blocks))
    mH7 = metrics(frozen_fuzz, run_float(
        FloatSSETwin(FUZZ_PARAMS, drop_dc_probe=True), fuzz_blocks))
    results.append({
        "id": "NC-H", "kind": "dc-offset-probe",
        "what": "the zero-input DC-offset probe dropped (dcOffset forced 0)",
        "must": "FAIL", "verdict": verdict(mH), "metrics": mH,
        "ok": verdict(mH) == "FAIL",
        "graded_on": "FX model 4 (wst_digital)",
        "model7_leg": {"verdict": verdict(mH7), "metrics": mH7,
                       "note": "wst_fuzzsoft also has a non-zero zero-input "
                               "offset (its fuzz table is non-zero at x = 0)"}})

    # NC-D shared QuadWaveshaperState (the state THIS leaf adds)
    pa = dict(REG_PARAMS)
    pb = dict(BASE, model_i=7, drive_f=-3.0, feedback_f=0.2,
              posteq_gain_f=2.0)
    m_a = DistortionSSEModel(DistortionSSEParams(pa), "a")
    m_b = DistortionSSEModel(DistortionSSEParams(pb), "b")
    m_a.initialize()
    m_b.initialize()
    indep_a, indep_b = [], []
    for il, ir, ring in blocks:
        qi = [int(round(v * LSB)) for v in il]
        qr = [int(round(v * LSB)) for v in ir]
        oa = m_a.process_block(qi, qr, ringout=ring)
        ob = m_b.process_block(qi, qr, ringout=ring)
        indep_a += list(oa[0]) + list(oa[1])
        indep_b += list(ob[0]) + list(ob[1])
    m_a2 = DistortionSSEModel(DistortionSSEParams(pa), "a2")
    m_b2 = DistortionSSEModel(DistortionSSEParams(pb), "b2")
    m_a2.initialize()
    m_b2.initialize()
    m_b2.st.ws = m_a2.st.ws        # THE DEFECT: pooled QuadWaveshaperState
    pooled_a, pooled_b = [], []
    for il, ir, ring in blocks:
        qi = [int(round(v * LSB)) for v in il]
        qr = [int(round(v * LSB)) for v in ir]
        oa = m_a2.process_block(qi, qr, ringout=ring)
        ob = m_b2.process_block(qi, qr, ringout=ring)
        pooled_a += list(oa[0]) + list(oa[1])
        pooled_b += list(ob[0]) + list(ob[1])
    exact_a = pooled_a == indep_a
    exact_b = pooled_b == indep_b
    results.append({
        "id": "NC-D", "kind": "shared-state",
        "what": "two concurrent instances pooled onto ONE "
                "QuadWaveshaperState (chain state left per-instance, so the "
                "control isolates exactly the state this leaf adds)",
        "must": "FAIL",
        "verdict": "PASS" if (exact_a and exact_b) else "FAIL",
        "ok": not (exact_a and exact_b),
        "metrics": {"instance_a_exact": exact_a, "instance_b_exact": exact_b,
                    "a": metrics([float(v) for v in indep_a],
                                 [float(v) for v in pooled_a]),
                    "b": metrics([float(v) for v in indep_b],
                                 [float(v) for v in pooled_b])}})

    # NC-B dropped tail
    tail_p = dict(REG_PARAMS, feedback_f=0.99, drive_f=9.0,
                  drive_extend=True)
    silence_at = 32
    tail_blocks = stimulus(silence_at + RINGOUT_TIME, seed=23,
                           ringout_from=silence_at)
    full = run_frozen(tail_p, tail_blocks, "tail")
    per_block = BLOCK * 2

    live_until = silence_at
    for b in range(silence_at, silence_at + RINGOUT_TIME):
        seg = full[b * per_block:(b + 1) * per_block]
        if max(abs(v) for v in seg) > 1.0:
            live_until = b
    decay_blocks = live_until - silence_at + 1

    def tail_gate(trunc_at, region_first):
        region = full[region_first * per_block:]
        trunc = (full[:trunc_at * per_block]
                 + [0.0] * (len(full) - trunc_at * per_block))
        treg = trunc[region_first * per_block:]
        rms_ref = math.sqrt(sum(v * v for v in region) / len(region))
        resid = [region[i] - treg[i] for i in range(len(region))]
        rms_res = math.sqrt(sum(v * v for v in resid) / len(resid))
        rel = (20 * math.log10(rms_res / rms_ref)
               if rms_ref > 0 and rms_res > 0 else RMS_FLOOR_DBFS)
        return rel, rms_ref, rms_res

    rel_db, ref_rms, res_rms = tail_gate(silence_at + 1, silence_at)
    tail_pass = rel_db <= -20.0
    results.append({
        "id": "NC-B", "kind": "dropped-tail",
        "what": f"render truncated 1 block into the declared "
                f"{RINGOUT_TIME}-block ringout span (inside the measured "
                f"{decay_blocks}-block live decay)",
        "must": "FAIL",
        "verdict": "PASS" if tail_pass else "FAIL", "ok": not tail_pass,
        "metrics": {"declared_tail_blocks": RINGOUT_TIME,
                    "declared_tail_seconds": RINGOUT_TIME * BLOCK / 48000.0,
                    "ringout_end_fade_blocks": 320,
                    "measured_live_decay_blocks": decay_blocks,
                    "measured_live_decay_ms":
                        decay_blocks * BLOCK / 48000.0 * 1000.0,
                    "reference_tail_rms_lsb": ref_rms,
                    "residual_rms_lsb": res_rms,
                    "tail_residual_rel_db": rel_db,
                    "gate_rel_db": -20.0}})

    late_rel, _, _ = tail_gate(silence_at + 800, silence_at)
    late_seg = full[(silence_at + 800) * per_block:
                    (silence_at + 801) * per_block]
    results.append({
        "id": "KG-1", "kind": "known-gap-probe",
        "what": "late truncation (800 blocks into the ringout) is NOT "
                "detected by the whole-region residual gate",
        "must": "n/a (probe, not a control)",
        "verdict": "PASS (gap confirmed)", "ok": True,
        "metrics": {"tail_residual_rel_db": late_rel, "gate_rel_db": -20.0,
                    "signal_peak_lsb_at_truncation":
                        max(abs(v) for v in late_seg),
                    "measured_live_decay_blocks": decay_blocks,
                    "why": "the tail-region RMS is dominated by the early "
                           "high-energy part of the decay, so removing the "
                           "quiet remainder stays inside the gate",
                    "covered_instead_by":
                        "reports/SXT-028e-sse/rtl-exactness.json cases"
                        "[ringout-tail-*] (integer equality over the whole "
                        "declared span, fade included)",
                    "same_gap_as": "reports/SXT-028e KG-1 (#57) and "
                                   "reports/stereo-comparator-tail-gate "
                                   "(#111)"}})

    # NC-E stale stub: the frozen-revision pin must refuse
    rev = model_revision()
    stale_ok = rev[:8] != "deadbeef"
    results.append({
        "id": "NC-E", "kind": "stale-stub",
        "what": "harness pinned to a stale frozen-model revision",
        "must": "FAIL (refuse to report PASS)",
        "verdict": "REFUSED" if stale_ok else "PASS", "ok": stale_ok,
        "metrics": {"model_revision": rev,
                    "stale_pin_checked_in_rtl_harness":
                        "reports/SXT-028e-sse/rtl-exactness.json "
                        "mutant_controls[stale-revision-pin]"}})

    out = {"schema_version": 1, "leaf": "SXT-028e-sse",
           "model_revision": rev,
           "budget_class": "SXT-023 effect-slice [PROPOSED] (freeze gated on #12)",
           "budgets": PROPOSED,
           "grading_boundary": "model-vs-model (pinned-oracle leg NOT_RUN)",
           "drive_interpolation_divisor": DRIVE_INTERP_DIVISOR,
           "beds": {"primary": "FX model 5 (wst_ojd)",
                    "register_owning": "FX model 6 (wst_fwrectify)",
                    "digital": "FX model 4 (wst_digital)",
                    "chaotic": "FX model 7 (wst_fuzzsoft)"},
           "controls": results,
           "status": "ALL-CONTROLS-OK" if all(r["ok"] for r in results)
                     else "CONTROL-BROKEN"}
    with open(os.path.join(args.out, "negative-controls.json"), "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    lines = [f"SXT-028e-sse negative controls — {out['status']}",
             f"model revision {rev}",
             f"budgets (PROPOSED, not frozen): {PROPOSED}",
             "grading boundary: model-vs-model; pinned-oracle leg NOT_RUN", ""]
    for r in results:
        lines.append(f"{r['id']:5s} {r['kind']:28s} must={r['must']:28s} "
                     f"verdict={r['verdict']:8s} "
                     f"-> {'CONTROL-OK' if r['ok'] else 'CONTROL-BROKEN'}")
        lines.append(f"      {r['what']}")
        if "metrics" in r and "max_abs_diff_lsb" in r["metrics"]:
            m = r["metrics"]
            lines.append(f"      max {m['max_abs_diff_lsb']:.1f} LSB  "
                         f"rms {m['rms_diff_dbfs']:.2f} dBFS  "
                         f"corr {m['spectral_corr']:.6f}")
    with open(os.path.join(args.out, "negative-controls.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if out["status"] == "ALL-CONTROLS-OK" else 1


if __name__ == "__main__":
    sys.exit(main())
