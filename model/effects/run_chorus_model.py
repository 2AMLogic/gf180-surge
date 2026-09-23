#!/usr/bin/env python3
"""SXT-028c: run the frozen fixed-point effect chains over fixture dry buses.

Boundary (declared, SXT-023 run_fx_model.py pattern): the model input is the
pinned engine's all-off DRY bus (stereo float32 WAV) de-amped by the
converged master amplitude A = db_to_linear(volume) and quantized to Q10.21.
The model then reproduces

    insert chain (scene A) -> scene hardclip -> scene sum
    -> per-send: send-gain ramp * sceneA -> effect -> return ramp * out
    -> per-global slot (G1..G4 order): effect
    -> master amplitude -> master hardclip

and the chain output is compared against the pinned engine's WET bus by
tools/compare_chorus_reference.py.

Reverb1 bridging (declared): the frozen Reverb1 model (SXT-024) uses an s24
I/O boundary and Q4.28 internal words; the chain converts Q10.21 -> s24
(exact <<2, saturating) at its input and Q4.28 -> Q10.21 (round-half-up
>>7) at its output. Each conversion is <= 4 LSB at the Q10.21 grid
(~-132 dB class), declared as chain-glue error and absorbed by the
[PROPOSED] budgets; the reverb1 model itself is unchanged.

Per-instance capture for the RTL: the model records, per block, the input
words and output words of EVERY chorus instance at its chain boundary, plus
state checkpoints and tap-interpolation checkpoints. The RTL testbench
replays the captured per-instance input (chorus-core scope, one algorithm
per leaf) and must reproduce the per-instance outputs and checkpoints
exactly. The chain wiring around the chorus (eq before, reverb1 after,
send/global routing) is model-side and validated against the engine
separately.

Outputs (under --out-dir):
  model__<slug>__<seq>.f32.wav   chain wet bus (stereo float32)
  trace_<slug>__<seq>.json       per-instance truth (outputs, checkpoints,
                                 tap checkpoints) + chain outputs
  rtl/<slug>__<seq>_in.hex       per-instance input stimulus (replay)
  rtl/<slug>__<seq>_ctrl.hex     per-instance control-plane words
  rtl/<slug>__<seq>_meta.json    stimulus layout description
"""

import argparse
import gzip
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-chorus"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))

import numpy as np  # noqa: E402

from model.effects.qmath import to_q, sat, qmul, qadd, FRAC, clip  # noqa: E402
from model.effects.delay.delay_model import (  # noqa: E402
    DelayModel, DelayParams, db_to_linear_d, A_FMT, G_FMT, BLOCK,
)
from model.effects.eq.eq_model import EqModel, EqParams  # noqa: E402
from model.effects.reverb1 import coefficient_plane as rcp  # noqa: E402
from model.effects.reverb1.reverb1_fixed import Reverb1Fixed  # noqa: E402
from chorus_model import ChorusModel, ChorusParams  # noqa: E402
from tools.render_fx_fixtures import write_wav_stereo_f32  # noqa: E402
from tools.run_fx_model import read_wav_stereo_f32  # noqa: E402

SETTLE_BLOCKS = 240
HARDCLIP8 = 8 << FRAC[A_FMT]
S24_MIN, S24_MAX = -(1 << 23), (1 << 23) - 1

SEQUENCES = {
    "seq-notes-coverage-v1": 1,
    "seq-poly-8-v1": 2,
}


def amp_to_linear_fixed(f):
    return to_q(max(0.0, f) ** 3, G_FMT)


def q21_to_s24(x):
    """Q10.21 -> Q1.23: exact <<2 when in range, saturating otherwise."""
    return min(S24_MAX, max(S24_MIN, x << 2))


def q428_to_q21(x):
    """Q4.28 -> Q10.21: round-half-up >>7, saturating."""
    return sat((x + (1 << 6)) >> 7, A_FMT)


class Reverb1Adapter:
    """Reverb1Fixed at the chain's Q10.21 boundary (declared bridging)."""

    def __init__(self, params_entry, name):
        p = params_entry["params"]
        deact = {
            "lowcut": bool(params_entry.get("lowcut_deactivated_raw") or False),
            "highcut": bool(params_entry.get("highcut_deactivated_raw") or False),
        }
        cp = rcp.build(p, deactivated=deact)
        self.m = Reverb1Fixed(cp)
        self.st = self.m
        self.name = name
        self.initialized = True

    def initialize(self):
        self.m.reset()

    def process_block(self, in_l, in_r):
        l24 = [q21_to_s24(x) for x in in_l]
        r24 = [q21_to_s24(x) for x in in_r]
        ol, orr = self.m.process_block(l24, r24)   # s32i out (Q4.28)
        return ([q428_to_q21(x) for x in ol],
                [q428_to_q21(x) for x in orr])

    def process_block_captured(self, in_l, in_r):
        return self.process_block(in_l, in_r)


def build_models(cfg):
    def make(e):
        if e["type"] == "chorus":
            return ChorusModel(ChorusParams(e["params"]), f"c{e['slot']}")
        if e["type"] == "eq":
            return EqModel(EqParams(e["params"]), f"e{e['slot']}")
        if e["type"] == "delay":
            return DelayModel(DelayParams(e["params"]), f"d{e['slot']}")
        if e["type"] == "reverb1":
            return Reverb1Adapter(e["params"], f"r{e['slot']}")
        raise ValueError(e["type"])

    ains = [(e["type"], make(e)) for e in cfg["chain"]["ains"]]
    sends = [(e["type"], make(e), e["send_slot"], e["send_gain_f"], e["return_f"])
             for e in cfg["chain"]["sends"]]
    globals_ = [(e["type"], make(e)) for e in sorted(
        cfg["chain"].get("globals", []), key=lambda x: x["slot"])]
    return ains, sends, globals_


def run_chain(ains, sends, globals_, in_l, in_r, a_q):
    """One block through the declared chain; returns output block."""
    wl, wr = list(in_l), list(in_r)
    for _kind, m in ains:
        wl, wr = m.process_block(wl, wr)
    wl = [min(HARDCLIP8, max(-HARDCLIP8, x)) for x in wl]
    wr = [min(HARDCLIP8, max(-HARDCLIP8, x)) for x in wr]
    out_l, out_r = wl, wr
    for _kind, m, _idx, sg_f, rl_f in sends:
        sg = amp_to_linear_fixed(sg_f)
        rl = amp_to_linear_fixed(rl_f)
        sl = [qmul(sg, x, G_FMT, A_FMT, A_FMT) for x in wl]
        sr = [qmul(sg, x, G_FMT, A_FMT, A_FMT) for x in wr]
        fl, fr = m.process_block(sl, sr)
        out_l = [qadd(a, qmul(rl, b, G_FMT, A_FMT, A_FMT), A_FMT)
                 for a, b in zip(out_l, fl)]
        out_r = [qadd(a, qmul(rl, b, G_FMT, A_FMT, A_FMT), A_FMT)
                 for a, b in zip(out_r, fr)]
    for _kind, m in globals_:
        out_l, out_r = m.process_block(out_l, out_r)
    out_l = [min(HARDCLIP8, max(-HARDCLIP8, qmul(a_q, x, G_FMT, A_FMT, A_FMT))) for x in out_l]
    out_r = [min(HARDCLIP8, max(-HARDCLIP8, qmul(a_q, x, G_FMT, A_FMT, A_FMT))) for x in out_r]
    return out_l, out_r


def chorus_instances(ains, sends, globals_):
    """All chorus models in processing order with their chain position."""
    out = [("ains", m) for k, m in ains if k == "chorus"]
    out += [("sends", m) for k, m, _i, _s, _r in sends if k == "chorus"]
    out += [("globals", m) for k, m in globals_ if k == "chorus"]
    return out


def checkpoint_set(n_total):
    cps = {SETTLE_BLOCKS - 1, SETTLE_BLOCKS, SETTLE_BLOCKS + 1, n_total - 1}
    b = SETTLE_BLOCKS
    while b < n_total:
        cps.add(b)
        b += 64
    return cps


TAP_CHECKPOINT_STRIDE = 16
TAP_SAMPLES = 4


def qhex(v, bits):
    m = (1 << bits) - 1
    x = v & m
    return f"{x:0{bits // 4}x}"


def chorus_ctrl_words(m):
    ctrl = m.ctrl
    w = [qhex(ctrl["fb_raw"], 32), qhex(ctrl["mix_raw"], 32), qhex(ctrl["ws_raw"], 32)]
    w += [qhex(t, 64) for t in ctrl["time_tgts"]]
    w += [qhex(c, 64) for c in m.st.lp.tgt]
    w += [qhex(c, 64) for c in m.st.hp.tgt]
    flags = int(ctrl["lp_on"]) | (int(ctrl["hp_on"]) << 1)
    w.append(qhex(flags, 32))
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", default="seq-notes-coverage-v1")
    ap.add_argument("--fixtures-dir",
                    default=os.path.join(REPO, "reports", "SXT-028c", "fixtures"))
    ap.add_argument("--inputs-dir",
                    default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "SXT-028c", "artifacts"))
    args = ap.parse_args()

    slug, seq = args.slug, args.seq
    cfg = json.load(open(os.path.join(args.inputs_dir, f"type-chorus-{slug}.json")))
    dry, _sr = read_wav_stereo_f32(os.path.join(
        args.fixtures_dir, f"{slug}__{seq}-dry.f32.wav"))
    frames = dry.shape[1]
    n_total = SETTLE_BLOCKS + (-(-frames // BLOCK))
    frames_padded = n_total * BLOCK

    a_q = to_q(db_to_linear_d(cfg["volume_f"]), G_FMT)
    a_d = db_to_linear_d(cfg["volume_f"])

    in_l_f = (dry[0] / a_d)
    in_r_f = (dry[1] / a_d)
    peak_in = float(max(np.max(np.abs(in_l_f)), np.max(np.abs(in_r_f))))
    if peak_in >= 7.9:
        raise ValueError(f"input peak {peak_in} too close to scene hardclip; "
                         "declared inactive-clip boundary violated")

    def q21(x):
        return to_q(float(x), A_FMT)

    zeros = [0] * (SETTLE_BLOCKS * BLOCK)
    in_l = zeros + [q21(x) for x in in_l_f] + [0] * (
        frames_padded - SETTLE_BLOCKS * BLOCK - frames)
    in_r = zeros + [q21(x) for x in in_r_f] + [0] * (
        frames_padded - SETTLE_BLOCKS * BLOCK - frames)

    ains, sends, globals_ = build_models(cfg)
    for _k, m in ains:
        m.initialize()
    for _k, m, _i, _s, _r in sends:
        m.initialize()
    for _k, m in globals_:
        m.initialize()
    chors = chorus_instances(ains, sends, globals_)
    if not chors:
        raise ValueError(f"no chorus instance in chain: {slug}")

    # per-instance boundary capture: wrap each chorus model's process_block
    # to record its input/output words (and optional tap checkpoints)
    def make_tap_hook(store):
        def hook(k, taps):
            if k < TAP_SAMPLES:
                store.append([(i, p, r) for i, p, r in taps])
        return hook

    for _pos, m in chors:
        orig_pb = m.process_block

        def capturing_pb(inl, inr, _m=m, _op=orig_pb):
            if _m._cap_in is None:
                _m._cap_in = (list(inl), list(inr))
            if _m._cap_taps is not None:
                _m._cap_tap_store = []
                out = _op(inl, inr, tap_hook=make_tap_hook(_m._cap_tap_store))
            else:
                out = _op(inl, inr)
            _m._cap_out = out
            return out

        m.process_block = capturing_pb

    cps = checkpoint_set(n_total)
    trace_blocks = []
    blocks_in = []           # per chorus instance: (32 L, 32 R) input words
    ctrl_words_per_block = []
    model_out = np.zeros((2, frames_padded), dtype=np.float32)

    for b in range(n_total):
        il = in_l[b * BLOCK:(b + 1) * BLOCK]
        ir = in_r[b * BLOCK:(b + 1) * BLOCK]

        want_taps = ((b in cps)
                     or (b >= SETTLE_BLOCKS
                         and ((b - SETTLE_BLOCKS) % TAP_CHECKPOINT_STRIDE == 0
                              or b == n_total - 1)))
        for _pos, m in chors:
            m._cap_in = None
            m._cap_out = None
            m._cap_taps = want_taps
            m._cap_tap_store = None

        ol, orr = run_chain(ains, sends, globals_, il, ir, a_q)

        blocks_in.append([m._cap_in for _pos, m in chors])
        words = []
        for _pos, m in chors:
            words += chorus_ctrl_words(m)
        ctrl_words_per_block.append(" ".join(words))

        model_out[0, b * BLOCK:(b + 1) * BLOCK] = [v / float(1 << FRAC[A_FMT]) for v in ol]
        model_out[1, b * BLOCK:(b + 1) * BLOCK] = [v / float(1 << FRAC[A_FMT]) for v in orr]

        if b in cps or b >= SETTLE_BLOCKS:
            rec = {
                "b": b,
                "chain_out": {"L": ol, "R": orr},
                "instances": [],
            }
            for _pos, m in chors:
                irec = {"kind": "chorus", **m.st.checkpoint()}
                if m._cap_out is not None:
                    irec["out"] = {"L": m._cap_out[0], "R": m._cap_out[1]}
                if m._cap_tap_store is not None:
                    irec["taps"] = m._cap_tap_store
                rec["instances"].append(irec)
            trace_blocks.append(rec)

    os.makedirs(args.out_dir, exist_ok=True)
    wav_path = os.path.join(args.out_dir, f"model__{slug}__{seq}.f32.wav")
    write_wav_stereo_f32(wav_path, model_out[:, SETTLE_BLOCKS * BLOCK:
                                            SETTLE_BLOCKS * BLOCK + frames])

    trace = {
        "schema_version": 1,
        "leaf": "SXT-028c",
        "slug": slug,
        "sequence": seq,
        "settle_blocks": SETTLE_BLOCKS,
        "n_blocks_total": n_total,
        "render_frames": frames,
        "n_chorus_instances": len(chors),
        "a_fixed": a_q,
        "input_peak_post_deamp": peak_in,
        "checkpoint_blocks": sorted(cps),
        "tap_checkpoint_stride": TAP_CHECKPOINT_STRIDE,
        "tap_samples_per_block": TAP_SAMPLES,
        "model_revision": __import__("chorus_model").model_revision(),
        "blocks": trace_blocks,
    }
    tpath = os.path.join(args.out_dir, f"trace_{slug}__{seq}.json.gz")
    with gzip.open(tpath, "wt") as f:
        json.dump(trace, f)

    rtl_dir = os.path.join(args.out_dir, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)
    in_path = os.path.join(rtl_dir, f"{slug}__{seq}_in.hex")
    ctrl_path = os.path.join(rtl_dir, f"{slug}__{seq}_ctrl.hex")
    with open(in_path, "w") as fi:
        for insts in blocks_in:
            for inl, inr in insts:
                for v in inl:
                    fi.write(qhex(v, 32) + "\n")
                for v in inr:
                    fi.write(qhex(v, 32) + "\n")
    with open(ctrl_path, "w") as fc:
        for line in ctrl_words_per_block:
            for wtext in line.split():
                fc.write(wtext + "\n")
    meta = {
        "slug": slug,
        "sequence": seq,
        "blocks": n_total,
        "n_chorus_instances": len(chors),
        "per_block_input": "per chorus instance in processing order: "
                           "32 x Q10.21 L words then 32 x Q10.21 R words "
                           "(8-hex each) — the chorus-boundary replay input",
        "per_block_control": "per chorus instance in processing order: "
                             "fb/mix/width RAW lipol targets (3 x Q13.18), "
                             "4 x per-voice time-lag targets (Q24.43), "
                             "lp coeffs x5 + hp coeffs x5 (Q24.43), flags "
                             "(bit0 lp_on, bit1 hp_on)",
    }
    with open(os.path.join(rtl_dir, f"{slug}__{seq}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(json.dumps({
        "slug": slug, "seq": seq,
        "model_wav": os.path.relpath(wav_path, REPO),
        "trace": os.path.relpath(tpath, REPO),
        "blocks_total": n_total,
        "chorus_instances": len(chors),
        "checkpoints": len(cps),
        "input_peak": peak_in,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
