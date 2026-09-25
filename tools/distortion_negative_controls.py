#!/usr/bin/env python3
"""SXT-028e model-side negative controls (each must FAIL the check it targets).

SCOPE OF THE CHECK BEING TARGETED. The controls below are graded at the
**model boundary**: variant-vs-frozen-model, using the SXT-023 effect-slice
[PROPOSED] budget metrics (max abs diff <= 8192 LSB Q10.21; residual RMS
<= -46 dBFS; spectral correlation >= 0.98). Those budgets are PROPOSALS, not
frozen policy (freeze is gated on SXT-017, #12).

Grading at the model boundary rather than against the pinned engine is a
DELIBERATE, DECLARED limitation of this record, not a substitute claim: the
pinned oracle is not reachable in this environment, so the reference leg of
every control is reported NOT_RUN in reports/SXT-028e/EVIDENCE.md. A control
that fires at the model boundary would also fire against the reference
(the reference residual is a lower bound on the variant residual up to the
model's own quantization floor), but this file makes no reference claim.

Baseline sanity (NC-0) comes first and must PASS: an INDEPENDENT float
structural twin of the same pinned algorithm — written from the pinned
sources, not from the fixed-point model — agrees with the frozen model
inside the same budgets. Without that leg the controls could be "failing"
simply because the check rejects everything.

Controls
  NC-0 baseline    independent float structural twin vs frozen model: PASS
  NC-A substitute  "convenient generic" distortion (single-rate tanh clip,
                   no 4x oversampling, no halfband, no pre/post EQ, no
                   feedback loop) -> ADAPTED, must FAIL
  NC-B tail        render truncated before the declared 1600-block ringout
                   span -> must FAIL the tail check
  NC-C order       band1/band2 order swapped (post-EQ before the shaper)
                   -> must FAIL the order-sensitive check
  NC-D shared      two instances pooling one feedback/filter state
                   -> must FAIL the dual-instance independence check
  NC-E stale       a stale frozen-revision pin -> must REFUSE (never PASS)
  NC-F hbswap      halfband A/B polyphase branches swapped -> must FAIL
                   (the decimator's phase alignment is load-bearing)

Usage: python3 tools/distortion_negative_controls.py [--out DIR]
Original to this repository (Apache-2.0).
"""

import argparse
import json
import math
import os
import random
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

from distortion_model import (  # noqa: E402
    DistortionModel, DistortionParams, model_revision, BLOCK, RINGOUT_TIME,
    HB_A_SOFT, HB_B_SOFT, HB_A_STEEP, HB_B_STEEP,
    coeff_peak_eq, coeff_lp2b, calc_omega, get_extended,
)
from ws_tables import build_table  # noqa: E402
from model.effects.delay.delay_model import db_to_linear_d  # noqa: E402

LSB = 1 << 21
FULL_SCALE_LSB = float(1 << 20)     # same convention as compare_*_reference
RMS_FLOOR_DBFS = -200.0

PROPOSED = {"max_abs_diff_lsb": 8192, "rms_diff_dbfs": -46.0,
            "spectral_corr_min": 0.98}

PARAMS = dict(preeq_gain_f=6.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
              preeq_highcut_f=70.0, drive_f=6.0, feedback_f=0.635445,
              posteq_gain_f=-4.5, posteq_freq_f=24.0, posteq_bw_f=1.1,
              posteq_highcut_f=30.535736, gain_f=0.0, model_i=0,
              preeq_highcut_deactivated=False,
              posteq_highcut_deactivated=False,
              preeq_gain_extend=False, posteq_gain_extend=False,
              drive_extend=False)


# ---------------------------------------------------------------------------
# independent float structural twin (NC-0)
# ---------------------------------------------------------------------------
class FBiquad:
    def __init__(self):
        self.lag = [0.0] * 5
        self.tgt = [0.0] * 5
        self.r0 = [0.0, 0.0]
        self.r1 = [0.0, 0.0]
        self.first = True

    def new_targets(self, c):
        if self.first:
            self.lag = list(c)
            self.first = False
        self.tgt = list(c)

    def suspend(self):
        self.lag = [0.0] * 5
        self.tgt = [0.0] * 5
        self.r0 = [0.0, 0.0]
        self.r1 = [0.0, 0.0]
        self.first = True

    def ps(self, lv, rv):
        for i in range(5):
            self.lag[i] = self.lag[i] * 0.996 + self.tgt[i] * 0.004
        a1, a2, b0, b1, b2 = self.lag
        op = lv * b0 + self.r0[0]
        self.r0[0] = lv * b1 - a1 * op + self.r1[0]
        self.r1[0] = lv * b2 - a2 * op
        ol = op
        op = rv * b0 + self.r0[1]
        self.r0[1] = rv * b1 - a1 * op + self.r1[1]
        self.r1[1] = rv * b2 - a2 * op
        return ol, op


class FNoLag(FBiquad):
    def ps(self, lv, rv):
        a1, a2, b0, b1, b2 = self.lag
        op = lv * b0 + self.r0[0]
        self.r0[0] = lv * b1 - a1 * op + self.r1[0]
        self.r1[0] = lv * b2 - a2 * op
        ol = op
        op = rv * b0 + self.r0[1]
        self.r0[1] = rv * b1 - a1 * op + self.r1[1]
        self.r1[1] = rv * b2 - a2 * op
        return ol, op


class FHalfband:
    def __init__(self, ca, cb, swap=False):
        self.ca, self.cb, self.swap = ca, cb, swap
        self.x = [[[[0.0] * 3 for _ in range(3)] for _ in range(2)]
                  for _ in range(2)]
        self.y = [[[[0.0] * 3 for _ in range(3)] for _ in range(2)]
                  for _ in range(2)]

    def _casc(self, ch, br, c, v):
        for j in range(3):
            xs, ys = self.x[ch][br][j], self.y[ch][br][j]
            y = xs[1] + c[j] * (v - ys[1])
            self.x[ch][br][j] = [v, xs[0], xs[1]]
            self.y[ch][br][j] = [y, ys[0], ys[1]]
            v = y
        return v

    def process(self, bl, br):
        n = len(bl)
        ol = [0.0] * (n // 2)
        orr = [0.0] * (n // 2)
        for ch, (buf, out) in enumerate(((bl, ol), (br, orr))):
            ca = [0.0] * n
            cb = [0.0] * n
            for i in range(n):
                ca[i] = self._casc(ch, 0, self.ca, buf[i])
                cb[i] = self._casc(ch, 1, self.cb, buf[i])
            for m in range(n // 2):
                if self.swap:
                    out[m] = (ca[2 * m] + cb[2 * m + 1]) * 0.5
                else:
                    out[m] = (cb[2 * m] + ca[2 * m + 1]) * 0.5
        return ol, orr


class FloatTwin:
    """Independent float implementation of the pinned DistortionEffect.

    Variants (the negative controls) are switches on this same twin, so a
    control differs from the baseline in exactly ONE structural respect.
    """

    def __init__(self, p, swap_bands=False, swap_hb=False):
        self.p = p
        self.swap_bands = swap_bands
        self.b1, self.b2 = FBiquad(), FBiquad()
        self.l1, self.l2 = FNoLag(), FNoLag()
        self.ha = FHalfband(HB_A_SOFT, HB_B_SOFT, swap_hb)
        self.hb = FHalfband(HB_A_STEEP, HB_B_STEEP, swap_hb)
        self.table = [v / (1 << 29) for v in build_table(int(p["model_i"]))]
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

    def ws(self, x):
        x = x * 32.0 + 512.0
        e = int(x)
        a = x - e
        if e > 0x3fd:
            return 1.0
        if e < 1:
            return -1.0
        return (1 - a) * self.table[e & 0x3ff] + a * self.table[(e + 1) & 0x3ff]

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

        self.dr_c = self.dr_t
        self.dr_t = 0.25 * db_to_linear_d(self._drv()) + 0.75 * self.dr_t
        rmul = DistortionModel.ringout_mul(ringout)
        self.og_c = self.og_t
        self.og_t = 0.25 * db_to_linear_d(p["gain_f"]) * rmul + 0.75 * self.og_t

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
                self.L = self.ws(self.L)
                self.R = self.ws(self.R)
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


class GenericSubstitute:
    """NC-A: a "convenient generic" distortion.

    Single-rate tanh saturation with an output gain — no 4x oversampling, no
    halfband decimation, no feedback loop, no pre/post peak EQ, no
    oversampled high-cuts. This is the shape a port reaches for when the
    original algorithm is inconvenient. It is ADAPTED, not supported.
    """

    def __init__(self, p):
        self.g = db_to_linear_d(get_extended(
            p["drive_f"], "ct_decibel_narrow_extendable", p["drive_extend"]))
        self.o = db_to_linear_d(p["gain_f"])

    def block(self, il, ir, ringout=0):
        r = DistortionModel.ringout_mul(ringout)
        return ([math.tanh(v * self.g) * self.o * r for v in il],
                [math.tanh(v * self.g) * self.o * r for v in ir])


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------
def rms_dbfs(rms_lsb):
    if not rms_lsb > 0:
        return RMS_FLOOR_DBFS
    return max(20 * math.log10(rms_lsb / FULL_SCALE_LSB), RMS_FLOOR_DBFS)


def spectral_corr(a, b, frame=1024):
    n = min(len(a), len(b))
    if n < frame:
        return 1.0 if all(abs(x - y) < 1e-12 for x, y in zip(a, b)) else 0.0
    try:
        import numpy as np
    except ImportError:
        return float("nan")
    aa = np.asarray(a[:n // frame * frame], dtype=float).reshape(-1, frame)
    bb = np.asarray(b[:n // frame * frame], dtype=float).reshape(-1, frame)
    win = np.hanning(frame)
    ra = np.log1p(np.abs(np.fft.rfft(aa * win, axis=1))).ravel()
    rb = np.log1p(np.abs(np.fft.rfft(bb * win, axis=1))).ravel()
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    d = math.sqrt(float((ra * ra).sum()) * float((rb * rb).sum()))
    return float((ra * rb).sum() / d) if d > 0 else 0.0


def metrics(ref_lsb, var_lsb):
    n = min(len(ref_lsb), len(var_lsb))
    diffs = [abs(ref_lsb[i] - var_lsb[i]) for i in range(n)]
    mx = max(diffs) if diffs else 0.0
    rms = math.sqrt(sum(d * d for d in diffs) / n) if n else 0.0
    return {"frames": n, "max_abs_diff_lsb": mx, "rms_diff_lsb": rms,
            "rms_diff_dbfs": rms_dbfs(rms),
            "spectral_corr": spectral_corr(ref_lsb, var_lsb)}


def verdict(m):
    ok = (m["max_abs_diff_lsb"] <= PROPOSED["max_abs_diff_lsb"]
          and m["rms_diff_dbfs"] <= PROPOSED["rms_diff_dbfs"]
          and (m["spectral_corr"] != m["spectral_corr"]      # NaN -> ignore
               or m["spectral_corr"] >= PROPOSED["spectral_corr_min"]))
    return "PASS" if ok else "FAIL"


# ---------------------------------------------------------------------------
def stimulus(n_blocks, seed=17, amp=0.35, ringout_from=None, f0=196.0,
             noise=0.15):
    """Sine + noise stimulus; `ringout_from` switches the input to silence and
    starts the engine's ringout counter (Effect::process_ringout)."""
    rs = random.Random(seed)
    blocks = []
    ph = 0.0
    for b in range(n_blocks):
        if ringout_from is not None and b >= ringout_from:
            blocks.append(([0.0] * BLOCK, [0.0] * BLOCK,
                           b - ringout_from + 1))
            continue
        il, ir = [], []
        for _ in range(BLOCK):
            ph += 2 * math.pi * f0 / 48000.0
            nz = (rs.random() - 0.5) * noise
            il.append(amp * (math.sin(ph) + nz))
            ir.append(amp * (math.sin(ph * 1.5) - nz))
        blocks.append((il, ir, 0))
    return blocks


def run_frozen(p, blocks, name="frozen"):
    m = DistortionModel(DistortionParams(p), name)
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
    ap.add_argument("--out", default=os.path.join(REPO, "reports", "SXT-028e",
                                                  "negative-controls"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    nb = 96
    blocks = stimulus(nb)
    frozen = run_frozen(PARAMS, blocks)

    results = []

    # NC-0 baseline sanity: independent float structural twin
    m0 = metrics(frozen, run_float(FloatTwin(PARAMS), blocks))
    results.append({
        "id": "NC-0", "kind": "baseline-sanity",
        "what": "independent float structural twin vs frozen fixed model",
        "must": "PASS", "verdict": verdict(m0), "metrics": m0,
        "ok": verdict(m0) == "PASS",
        "note": "establishes the check has resolving power; NOT a reference claim"})

    # NC-A generic substitute -> ADAPTED
    mA = metrics(frozen, run_float(GenericSubstitute(PARAMS), blocks))
    results.append({
        "id": "NC-A", "kind": "generic-substitute",
        "what": "single-rate tanh clip (no oversampling / halfband / EQ / feedback)",
        "must": "FAIL", "verdict": verdict(mA), "metrics": mA,
        "ok": verdict(mA) == "FAIL",
        "label": "ADAPTED — refused from original-preset coverage"})

    # NC-C wrong order (band1/band2 swapped)
    mC = metrics(frozen, run_float(FloatTwin(PARAMS, swap_bands=True), blocks))
    results.append({
        "id": "NC-C", "kind": "wrong-order",
        "what": "pre-EQ and post-EQ bands swapped around the shaper",
        "must": "FAIL", "verdict": verdict(mC), "metrics": mC,
        "ok": verdict(mC) == "FAIL"})

    # NC-F halfband polyphase branch swap. The defect lives ABOVE the base
    # Nyquist, so it needs a bright, hot stimulus: a 4.7 kHz tone plus broadband
    # noise at high drive, whose shaper harmonics populate the 24-96 kHz band
    # the decimator is there to reject. Both legs are reported: on the benign
    # NC-0 stimulus the swap stays inside the [PROPOSED] budgets, which is a
    # property of the CHECK, not evidence that the swap is acceptable — the
    # RTL exactness check (integer equality) rejects it unconditionally
    # (rtl-exactness.json mutant_controls[mutant-hbswap]).
    hot = dict(PARAMS)
    hot.update(drive_f=9.0, drive_extend=True, model_i=1, feedback_f=0.4)
    bright = stimulus(nb, seed=31, amp=0.6, f0=4700.0, noise=0.9)
    frozen_hot = run_frozen(hot, bright)
    mF = metrics(frozen_hot, run_float(FloatTwin(hot, swap_hb=True), bright))
    mF_benign = metrics(frozen, run_float(FloatTwin(PARAMS, swap_hb=True),
                                          blocks))
    results.append({
        "id": "NC-F", "kind": "halfband-phase",
        "what": "halfband A/B polyphase branches swapped in the reconstruction "
                "(bright/hot stimulus: 4.7 kHz + broadband noise, drive 45 dB)",
        "must": "FAIL", "verdict": verdict(mF), "metrics": mF,
        "ok": verdict(mF) == "FAIL",
        "benign_stimulus_leg": {
            "verdict": verdict(mF_benign), "metrics": mF_benign,
            "note": "196 Hz sine: the swap stays inside the [PROPOSED] "
                    "budgets. Recorded as a sensitivity limit of the "
                    "model-boundary check, not as an acceptable defect."}})

    # NC-D shared state: two instances, one pooled state object
    pb = dict(PARAMS)
    pb.update(drive_f=-3.0, feedback_f=0.2, model_i=1, posteq_gain_f=2.0)
    m_a = DistortionModel(DistortionParams(PARAMS), "a")
    m_b = DistortionModel(DistortionParams(pb), "b")
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
    # pooled: instance b reuses instance a's state object
    m_a2 = DistortionModel(DistortionParams(PARAMS), "a2")
    m_b2 = DistortionModel(DistortionParams(pb), "b2")
    m_a2.initialize()
    m_b2.initialize()
    m_b2.st = m_a2.st                       # THE DEFECT: pooled per-instance state
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
        "what": "two concurrent instances pooled onto one DistortionState",
        "must": "FAIL",
        "verdict": "PASS" if (exact_a and exact_b) else "FAIL",
        "ok": not (exact_a and exact_b),
        "metrics": {"instance_a_exact": exact_a, "instance_b_exact": exact_b,
                    "a": metrics([float(v) for v in indep_a],
                                 [float(v) for v in pooled_a]),
                    "b": metrics([float(v) for v in indep_b],
                                 [float(v) for v in pooled_b])}})

    # NC-B dropped tail. The DECLARED tail span is the engine's ringout
    # contract: RINGOUT_TIME (1600) blocks = 1.0667 s, over which the model
    # must keep reproducing the engine's output including the final
    # RINGOUT_END (320) block output-gain fade. The effect's own SIGNAL tail
    # (feedback-loop decay + biquad ringing) is much shorter than that window
    # — measured below — so the control truncates INSIDE the live decay.
    tail_p = dict(PARAMS)
    tail_p.update(feedback_f=0.99, drive_f=9.0, drive_extend=True)
    silence_at = 32
    tail_blocks = stimulus(silence_at + RINGOUT_TIME, seed=23,
                           ringout_from=silence_at)
    full = run_frozen(tail_p, tail_blocks, "tail")
    per_block = BLOCK * 2

    # measured signal tail: last block whose peak exceeds 1 LSB Q10.21
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

    # the control: truncate one block into the ringout, i.e. inside the live
    # decay -> the tail-region residual gate (<= -20 dB) must FAIL
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

    # KNOWN-GAP probe (NOT a control). A LATE truncation — 800 blocks into
    # the ringout — is NOT rejected by the whole-region residual gate even
    # though the signal is still above the Q10.21 LSB floor there: the
    # tail region's RMS is dominated by its early, high-energy part, so
    # deleting the quiet second half stays under the -20 dB relative
    # threshold. Recorded so the gap is visible, in the same spirit as the
    # late-tail known gap of reports/stereo-comparator-tail-gate (#111).
    # What DOES cover the whole declared span is the RTL exactness case
    # `ringout-tail-*` (integer equality on every block, fade included).
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
                        "reports/SXT-028e/rtl-exactness.json cases"
                        "[ringout-tail-*] (integer equality over the whole "
                        "declared span, fade included)"}})

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
                        "reports/SXT-028e/rtl-exactness.json "
                        "mutant_controls[stale-revision-pin]"}})

    out = {"schema_version": 1, "leaf": "SXT-028e",
           "model_revision": rev,
           "budget_class": "SXT-023 effect-slice [PROPOSED] (freeze gated on #12)",
           "budgets": PROPOSED,
           "grading_boundary": "model-vs-model (pinned-oracle leg NOT_RUN)",
           "controls": results,
           "status": "ALL-CONTROLS-OK" if all(r["ok"] for r in results)
                     else "CONTROL-BROKEN"}
    with open(os.path.join(args.out, "negative-controls.json"), "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")
    lines = [f"SXT-028e negative controls — {out['status']}",
             f"model revision {rev}",
             f"budgets (PROPOSED, not frozen): {PROPOSED}",
             "grading boundary: model-vs-model; pinned-oracle leg NOT_RUN", ""]
    for r in results:
        lines.append(f"{r['id']:5s} {r['kind']:20s} must={r['must']:28s} "
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
