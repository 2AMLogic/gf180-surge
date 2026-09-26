#!/usr/bin/env python3
"""SXT-023 delay budget diagnosis: isolate the dominant model-vs-engine error
mechanism by ALTERNATIVE HYPOTHESIS, using diagnostic variants of the frozen
model. The frozen model file is NOT modified; variants subclass it here.

Variants
  base     : frozen model as committed (reproduces the A2 miss)
  f32lag   : the engine's SurgeLag<float> emulated honestly — the lag state,
             target and coefficient pair live in float32 and every per-sample
             lag product/sum rounds to float32 (not just the container word)
  f32table : the engine's float32 sinc table (each Q2.29 tap re-rounded to
             float32 precision)
  f32both  : float32 lag AND float32 sinc table
  tgtlag1  : time-lag targets consumed one block late (control/LFO timing
             class probe)
  lfosamedir / nowidth / nomod / slowrate / k<K> : structural and
             sensitivity probes of the LFO-to-delay-time path (nomod pairs
             with the engine probe render at depth 0; slowrate/k<K> pair
             with matched engine-probe states where noted)

Each variant renders the committed dry bus through the committed chain wiring
and is compared against the committed engine wet bus with the frozen budget
tool metrics (tools/compare_fx_reference.channel_metrics). One JSON per slug
and variant under reports/sxt-023/artifacts-followup/budget-diagnosis/.

Diagnostic tooling only — feeds the SXT-017 (#12) word-length/budget
decision; it changes no frozen model, no budget, and makes no support claim.
"""
import argparse
import json
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import numpy as np  # noqa: E402

from model.effects.run_fx_model import (  # noqa: E402
    SETTLE_BLOCKS, run_chain, read_wav_stereo_f32, db_to_linear_d,
)
from model.effects.qmath import to_q, FRAC  # noqa: E402
import model.effects.delay.delay_model as dm  # noqa: E402
import model.effects.qmath as qmath  # noqa: E402
from tools.compare_fx_reference import channel_metrics  # noqa: E402
from tools.render_fx_fixtures import write_wav_stereo_f32  # noqa: E402


def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


class F32Lag(dm.Lag):
    """SurgeLag<float>: state, target, coefficient pair and every per-sample
    product/sum round to float32. The Q24.43 word is the quantized container
    of the float32 value (keeps the frozen checkpoint interface)."""

    def process(self):
        vf = f32(self.v / float(1 << 43))
        tf = f32(self.target / float(1 << 43))
        lp = f32(self.lp / float(1 << 43))
        lpinv = f32(self.lpinv / float(1 << 43))
        self.v = to_q(f32(f32(vf * lpinv) + f32(tf * lp)), "Q24.43")


class TgtLag1(dm.Lag):
    """One-block-delayed time-lag target consumption (timing-class probe):
    during block k the lag relaxes toward the block k-1 target."""

    def set_target(self, f):
        if self.first_run:
            self.target = f
            self.v = f
            self.first_run = False
            self._held = f
            return
        self.target = self._held
        self._held = f

    def instantize(self):
        self.v = self.target


class LfoSameDir(dm.DelayModel):
    """Structural probe: LFO modulates BOTH line delays in the SAME direction
    (time_r target gets +lfoval instead of -lfoval)."""

    def _control(self, init):
        ctrl = super()._control(init)
        ctrl["time_r_tgt"] = dm.sat(ctrl["time_r_tgt"] + 2 * self.st.lfoval, "Q24.43")
        self.st.time_r.set_target(ctrl["time_r_tgt"])
        return ctrl


class NoWidth(dm.DelayModel):
    """Structural probe: width stage bypassed (ws = 1.0 exactly)."""

    def _control(self, init):
        ctrl = super()._control(init)
        ctrl["ws_tgt"] = 1 << 18
        return ctrl


class NoMod(dm.DelayModel):
    """Diagnostic: delay LFO depth forced to 0 (pairs with the engine probe
    render of the same modified preset state)."""

    def __init__(self, params, name="delay"):
        import copy
        p2 = copy.copy(params)
        p2.mod_depth_f = 0.0
        super().__init__(p2, name)


class ModRateOverride(dm.DelayModel):
    """Diagnostic: mod rate forced to a fixed value (pairs with the engine
    probe render of the same modified preset state)."""

    def __init__(self, params, name="delay", rate=0.0):
        import copy
        p2 = copy.copy(params)
        p2.mod_rate_f = rate
        super().__init__(p2, name)


VARIANTS = ("base", "f32lag", "f32table", "f32both", "tgtlag1",
            "lfosamedir", "nowidth", "nomod", "nomodf32lag", "slowrate",
           "k0.9", "k0.95", "k1.05")

MOD_RATE_OVERRIDE = -6.0


class LfoScale(dm.DelayModel):
    """Diagnostic: scale the LFO contribution to BOTH time targets by kappa."""

    KAPPA = 1.0

    def _control(self, init):
        ctrl = super()._control(init)
        k = to_q(self.KAPPA, "Q24.43")
        # time_l_tgt = q(base_l) + lfoval - off ; rebuild from parts:
        base_l = ctrl["time_l_tgt"] - self.st.lfoval + to_q(dm.FIR_OFFSET, "Q24.43")
        base_r = ctrl["time_r_tgt"] + self.st.lfoval + to_q(dm.FIR_OFFSET, "Q24.43")
        lv = qmath.qmul(self.st.lfoval, k, "Q24.43", "Q24.43", "Q24.43")
        off = to_q(dm.FIR_OFFSET, "Q24.43")
        ctrl["time_l_tgt"] = dm.sat(base_l + lv - off, "Q24.43")
        ctrl["time_r_tgt"] = dm.sat(base_r - lv - off, "Q24.43")
        self.st.time_l.set_target(ctrl["time_l_tgt"])
        self.st.time_r.set_target(ctrl["time_r_tgt"])
        return ctrl


def make_delay(variant, params):
    p = dm.DelayParams(params)
    cls = {"lfosamedir": LfoSameDir, "nowidth": NoWidth,
           "nomod": NoMod, "nomodf32lag": NoMod}.get(variant, dm.DelayModel)
    if variant == "slowrate":
        m = ModRateOverride(dm.DelayParams(params), rate=MOD_RATE_OVERRIDE)
    if variant.startswith("k"):
        LfoScale.KAPPA = float(variant[1:])
        cls = LfoScale
    m = cls(p)
    if variant in ("f32lag", "f32both", "nomodf32lag"):
        m.st.time_l.__class__ = F32Lag
        m.st.time_r.__class__ = F32Lag
    elif variant == "tgtlag1":
        m.st.time_l.__class__ = TgtLag1
        m.st.time_r.__class__ = TgtLag1
        m.st.time_l._held = 0
        m.st.time_r._held = 0
    return m


def build_variant(variant, cfg):
    ains = [("delay", make_delay(variant, e["params"]))
            for e in cfg["chain"]["ains"] if e["type"] == "delay"]
    sends = [("delay", make_delay(variant, e["params"]),
              e["send_slot"], e["send_gain_f"], e["return_f"])
             for e in cfg["chain"]["sends"] if e["type"] == "delay"]
    return ains, sends


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--variant", required=True, choices=VARIANTS)
    ap.add_argument("--ref", default=None,
                    help="override reference WAV (e.g. the engine probe render)")
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "sxt-023",
                                         "artifacts-followup", "budget-diagnosis"))
    args = ap.parse_args()
    slug, variant = args.slug, args.variant

    cfg = json.load(open(os.path.join(REPO, "model/effects/fx_inputs", slug + ".json")))
    dry, _ = read_wav_stereo_f32(os.path.join(
        REPO, "reports/sxt-023/fixtures", f"{slug}__seq-notes-coverage-v1-dry.f32.wav"))
    frames = dry.shape[1]
    n_total = SETTLE_BLOCKS + (-(-frames // 32))
    frames_padded = n_total * 32

    a_q = to_q(db_to_linear_d(cfg["volume_f"]), "Q13.18")
    a_d = db_to_linear_d(cfg["volume_f"])
    zeros = [0] * (SETTLE_BLOCKS * 32)
    in_l = zeros + [to_q(float(x) / a_d, "Q10.21") for x in dry[0]] \
        + [0] * (frames_padded - SETTLE_BLOCKS * 32 - frames)
    in_r = zeros + [to_q(float(x) / a_d, "Q10.21") for x in dry[1]] \
        + [0] * (frames_padded - SETTLE_BLOCKS * 32 - frames)

    if variant in ("f32table", "f32both"):
        dm.TABLE_Q[:] = [to_q(f32(v / float(1 << 29)), "Q2.29") for v in dm.TABLE_Q]

    ains, sends = build_variant(variant, cfg)
    for _k, m in ains:
        m.initialize()
    for _k, m, _i, _s, _r in sends:
        m.initialize()

    out = np.zeros((2, frames_padded), dtype=np.float32)
    for b in range(n_total):
        ol, orr, _sp = run_chain(ains, sends,
                                 in_l[b * 32:(b + 1) * 32],
                                 in_r[b * 32:(b + 1) * 32], a_q)
        out[0, b * 32:(b + 1) * 32] = [v / float(1 << FRAC["Q10.21"]) for v in ol]
        out[1, b * 32:(b + 1) * 32] = [v / float(1 << FRAC["Q10.21"]) for v in orr]

    os.makedirs(args.out_dir, exist_ok=True)
    wav_path = os.path.join(args.out_dir,
                            f"diag__{variant}__{slug}__seq-notes-coverage-v1.f32.wav")
    write_wav_stereo_f32(wav_path,
                         out[:, SETTLE_BLOCKS * 32:SETTLE_BLOCKS * 32 + frames])

    ref_path = args.ref or os.path.join(
        REPO, "reports/sxt-023/fixtures", f"{slug}__seq-notes-coverage-v1-wet.f32.wav")
    ref, _sr = read_wav_stereo_f32(ref_path)
    mod, _sr2 = read_wav_stereo_f32(wav_path)
    chs = {}
    for nm, idx in (("L", 0), ("R", 1)):
        chs[nm] = channel_metrics(ref[idx], mod[idx])
    chs["mono"] = channel_metrics(0.5 * (ref[0] + ref[1]), 0.5 * (mod[0] + mod[1]))
    keep = ("max_abs_diff_lsb", "rms_diff_lsb", "rms_diff_dbfs",
            "rms_diff_at_best_shift_lsb", "best_shift", "spectral_corr")
    res = {
        "schema_version": 1,
        "kind": "sxt-023 delay budget diagnosis variant",
        "slug": slug,
        "variant": variant,
        "mono": {k: chs["mono"][k] for k in keep},
        "L": {k: chs["L"][k] for k in keep},
        "R": {k: chs["R"][k] for k in keep},
        "render": os.path.relpath(wav_path, REPO),
        "ref": os.path.relpath(ref_path, REPO),
    }
    out_path = os.path.join(args.out_dir, f"diag-{variant}-{slug}.json")
    with open(out_path, "w") as f:
        json.dump(res, f, indent=2)
        f.write("\n")
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
