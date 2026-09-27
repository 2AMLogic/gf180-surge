#!/usr/bin/env python3
"""SXT-023: run the frozen fixed-point effect chains over a fixture dry bus.

Boundary (declared): the model input is the pinned engine's all-off DRY bus
(stereo float32 WAV) de-amped by the converged master amplitude
A = db_to_linear(volume) and quantized to Q10.21. The model then reproduces

    insert chain (scene A) -> scene hardclip -> scene sum
    -> per-send: send-gain ramp * sceneA -> effect -> return ramp * out
    -> master amplitude -> master hardclip

and the output is compared against the pinned engine's WET bus (the fixture
of the same preset+sequence). A = db_to_linear is a converged block-constant
after the 0.25 s settle, so the de-amp is exact up to float32 rounding
(declared input-boundary error, ~2^-24 relative).

The model runs the settle phase too (240 silent blocks) so lag/LFO/line state
at t=0 matches the engine's wet-bus state evolution.

Outputs (under --out-dir):
  model__<slug>.f32.wav      model wet bus (stereo float32)
  model_trace.json           checkpoints + every output sample (model truth)
  rtl/<slug>_in.hex          RTL stimulus: input words per block
  rtl/<slug>_ctrl.hex        RTL stimulus: per-block control-plane words
  rtl/<slug>_meta.json       RTL stimulus layout description
"""

import argparse
import json
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

import numpy as np  # noqa: E402

from model.effects.qmath import to_q, qmul, qadd, FRAC, clip  # noqa: E402
from model.effects.delay.delay_model import (  # noqa: E402
    DelayModel, DelayParams, A_FMT, G_FMT, BLOCK,
)
from model.effects.eq.eq_model import EqModel, EqParams  # noqa: E402
from tools.render_fx_fixtures import write_wav_stereo_f32  # noqa: E402

SETTLE_BLOCKS = 240
HARDCLIP8 = 8 << FRAC[A_FMT]


def read_wav_stereo_f32(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"not a RIFF/WAVE: {path}")
    pos = 12
    fmt = None
    raw = None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        sz = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + sz]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            raw = body
        pos += 8 + sz + (sz & 1)
    if fmt is None or raw is None:
        raise ValueError(f"bad WAV: {path}")
    audio_fmt, nch, sr, _brate, _align, bits = fmt
    if audio_fmt != 3 or bits != 32 or nch != 2:
        raise ValueError(f"expected stereo float32: {path} got fmt={audio_fmt} bits={bits} nch={nch}")
    a = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    return a.T.copy(), sr


def db_to_linear_d(x):
    from model.effects.delay.delay_model import db_to_linear_d as f
    return f(x)


def build_models(cfg):
    """Instantiate the chain models from an fx_inputs JSON."""
    ains = []
    for e in cfg["chain"]["ains"]:
        if e["type"] == "delay":
            ains.append(("delay", DelayModel(DelayParams(e["params"]), f"a{e['slot']}")))
        elif e["type"] == "eq":
            ains.append(("eq", EqModel(EqParams(e["params"]), f"a{e['slot']}")))
        else:
            raise ValueError(e["type"])
    sends = []
    for e in cfg["chain"]["sends"]:
        if e["type"] == "delay":
            sends.append(("delay", DelayModel(DelayParams(e["params"]), f"s{e['slot']}"),
                          e["send_slot"], e["send_gain_f"], e["return_f"]))
        elif e["type"] == "eq":
            sends.append(("eq", EqModel(EqParams(e["params"]), f"s{e['slot']}"),
                          e["send_slot"], e["send_gain_f"], e["return_f"]))
        else:
            raise ValueError(e["type"])
    return ains, sends


def amp_to_linear_fixed(f):
    return to_q(max(0.0, f) ** 3, G_FMT)


def run_chain(ains, sends, in_l, in_r, a_q):
    """One block through the declared chain; returns output block + stats."""
    wl, wr = list(in_l), list(in_r)
    for _kind, m in ains:
        wl, wr = m.process_block(wl, wr)
    # scene hardclip (asserted inactive on fixture peaks; kept structural)
    wl = [min(HARDCLIP8, max(-HARDCLIP8, x)) for x in wl]
    wr = [min(HARDCLIP8, max(-HARDCLIP8, x)) for x in wr]
    out_l, out_r = wl, wr
    send_peaks = []
    for _kind, m, _idx, sg_f, rl_f in sends:
        sg = amp_to_linear_fixed(sg_f)
        rl = amp_to_linear_fixed(rl_f)
        sl = [qmul(sg, x, G_FMT, A_FMT, A_FMT) for x in wl]
        sr = [qmul(sg, x, G_FMT, A_FMT, A_FMT) for x in wr]
        send_peaks.append(max(max(abs(v) for v in sl), max(abs(v) for v in sr)))
        fl, fr = m.process_block(sl, sr)
        out_l = [qadd(a, qmul(rl, b, G_FMT, A_FMT, A_FMT), A_FMT)
                 for a, b in zip(out_l, fl)]
        out_r = [qadd(a, qmul(rl, b, G_FMT, A_FMT, A_FMT), A_FMT)
                 for a, b in zip(out_r, fr)]
    # master amplitude + hardclip
    out_l = [min(HARDCLIP8, max(-HARDCLIP8, qmul(a_q, x, G_FMT, A_FMT, A_FMT))) for x in out_l]
    out_r = [min(HARDCLIP8, max(-HARDCLIP8, qmul(a_q, x, G_FMT, A_FMT, A_FMT))) for x in out_r]
    return out_l, out_r, send_peaks


def checkpoint_set(n_total):
    """Declared checkpoints: last settle block, render blocks 0/1, every 64th,
    and the final block (absolute block indices)."""
    cps = {SETTLE_BLOCKS - 1, SETTLE_BLOCKS, SETTLE_BLOCKS + 1, n_total - 1}
    b = SETTLE_BLOCKS
    while b < n_total:
        cps.add(b)
        b += 64
    return cps


def qhex(v, bits):
    m = (1 << bits) - 1
    x = v & m
    return f"{x:0{bits // 4}x}"


def emit_rtl_stimulus(cfg, blocks_in, ctrl_lines, out_dir, slug, n_blocks):
    """Write stimulus hex files: ONE WORD PER LINE ($fscanf-friendly).

    in.hex: 64 Q10.21 words per block (32 L then 32 R).
    ctrl.hex: the per-block control words in instance order (layout in meta)."""
    os.makedirs(out_dir, exist_ok=True)
    in_path = os.path.join(out_dir, f"{slug}_in.hex")
    ctrl_path = os.path.join(out_dir, f"{slug}_ctrl.hex")
    with open(in_path, "w") as fi:
        for il, ir in blocks_in:
            for v in il:
                fi.write(qhex(v, 32) + "\n")
            for v in ir:
                fi.write(qhex(v, 32) + "\n")
    with open(ctrl_path, "w") as fc:
        for line in ctrl_lines:
            for wtext in line.split():
                fc.write(wtext + "\n")
    meta = {
        "slug": slug,
        "blocks": n_blocks,
        "per_block_input": "32 x Q10.21 L words then 32 x Q10.21 R words (8-hex each)",
        "per_block_control": "FIRST word = master amplitude a_q (Q13.18); then "
                             "instance order: scene-A insert models then send models; "
                             "delay instance: fb,cf,mix,pan,ws lipol targets (5 x Q13.18), timeL/timeR lag targets (2 x Q24.43), lp coeffs x5, hp coeffs x5 (Q24.43), flags word (bit0 lp_on, bit1 hp_on, bit2 fb_sign, bits3+ clip_mode); eq instance: 3 bands x 5 coefficient targets (Q24.43), gain target, mix target (Q13.18); send entry: send gain, return gain (Q13.18); "
    }
    with open(os.path.join(out_dir, f"{slug}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


def delay_ctrl_words(ctrl):
    # NOTE: lfophase/LFOval are control-plane accumulators in the frozen
    # boundary: the streamed time targets already include the LFOval
    # contribution, so no LFO words are streamed.
    w = [qhex(ctrl["fb_tgt"], 32), qhex(ctrl["cf_tgt"], 32), qhex(ctrl["mix_tgt"], 32),
         qhex(ctrl["pan_tgt"], 32), qhex(ctrl["ws_tgt"], 32)]
    w += [qhex(ctrl["time_l_tgt"], 64), qhex(ctrl["time_r_tgt"], 64)]
    w += [qhex(c, 64) for c in ctrl["lp_coeffs"]]
    w += [qhex(c, 64) for c in ctrl["hp_coeffs"]]
    flags = (int(ctrl["lp_on"]) | (int(ctrl["hp_on"]) << 1) | (int(ctrl["fb_sign"]) << 2))
    w.append(qhex(flags | (ctrl["clip_mode"] << 3), 32))
    return w


def eq_ctrl_words(ctrl, m):
    w = []
    for band in m.st.bands:
        w += [qhex(c, 64) for c in band.tgt]
    w.append(qhex(ctrl["gain_tgt"], 32))
    w.append(qhex(ctrl["mix_tgt"], 32))
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--fixtures-dir", default=os.path.join(REPO, "reports", "sxt-023", "fixtures"))
    ap.add_argument("--inputs-dir", default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    ap.add_argument("--out-dir", default=os.path.join(REPO, "reports", "sxt-023", "artifacts"))
    args = ap.parse_args()

    slug = args.slug
    cfg = json.load(open(os.path.join(args.inputs_dir, f"{slug}.json")))
    dry, _sr = read_wav_stereo_f32(os.path.join(
        args.fixtures_dir, f"{slug}__seq-notes-coverage-v1-dry.f32.wav"))
    frames = dry.shape[1]
    n_total = SETTLE_BLOCKS + (-(-frames // BLOCK))
    frames_padded = n_total * BLOCK

    a_q = to_q(db_to_linear_d(cfg["volume_f"]), G_FMT)
    a_d = db_to_linear_d(cfg["volume_f"])

    # quantized model input: dry / A
    in_l_f = (dry[0] / a_d)
    in_r_f = (dry[1] / a_d)
    peak_in = float(max(np.max(np.abs(in_l_f)), np.max(np.abs(in_r_f))))
    if peak_in >= 7.9:
        raise ValueError(f"input peak {peak_in} too close to scene hardclip; "
                         "declared inactive-clip boundary violated")

    def q21(x):
        return to_q(float(x), A_FMT)

    # The fixture dry WAV starts at engine block 240 (the harness discards the
    # 0.25 s settle). The model must reproduce the engine's settle first: 240
    # blocks of SILENT input (FX state: LFO phase/value, lags, line, bi counter
    # evolve exactly as in the engine's wet instance), then the dry content.
    zeros = [0] * (SETTLE_BLOCKS * BLOCK)
    in_l = zeros + [q21(x) for x in in_l_f] + [0] * (frames_padded - SETTLE_BLOCKS * BLOCK - frames)
    in_r = zeros + [q21(x) for x in in_r_f] + [0] * (frames_padded - SETTLE_BLOCKS * BLOCK - frames)

    ains, sends = build_models(cfg)
    for _k, m in ains:
        m.initialize()
    for _k, m, _i, _s, _r in sends:
        m.initialize()

    # expose coefficient targets in ctrl for RTL emission
    def snapshot_ctrl(kind, m):
        if kind == "delay":
            m.ctrl["lp_coeffs"] = list(m.st.lp.tgt)
            m.ctrl["hp_coeffs"] = list(m.st.hp.tgt)
        else:
            m.ctrl["gain_tgt"] = to_q(db_to_linear_d(m.p.gain_out_f), G_FMT)
            m.ctrl["mix_tgt"] = to_q(clip(m.p.mix_f, -1.0, 1.0), G_FMT)

    cps = checkpoint_set(n_total)
    trace_blocks = []
    blocks_in = []
    ctrl_words_per_block = []
    model_out = np.zeros((2, frames_padded), dtype=np.float32)
    for b in range(n_total):
        il = in_l[b * BLOCK:(b + 1) * BLOCK]
        ir = in_r[b * BLOCK:(b + 1) * BLOCK]
        blocks_in.append((il, ir))
        ol, orr, _sp = run_chain(ains, sends, il, ir, a_q)
        # capture each block's OWN control plane (computed inside process_block)
        words = [qhex(a_q, 32)]
        for kind, m in ains:
            snapshot_ctrl(kind, m)
            words += delay_ctrl_words(m.ctrl) if kind == "delay" else eq_ctrl_words(m.ctrl, m)
        for kind, m, _i, sg_f, rl_f in sends:
            snapshot_ctrl(kind, m)
            words += delay_ctrl_words(m.ctrl) if kind == "delay" else eq_ctrl_words(m.ctrl, m)
            words.append(qhex(amp_to_linear_fixed(sg_f), 32))
            words.append(qhex(amp_to_linear_fixed(rl_f), 32))
        ctrl_words_per_block.append(" ".join(words))
        model_out[0, b * BLOCK:(b + 1) * BLOCK] = [v / float(1 << FRAC[A_FMT]) for v in ol]
        model_out[1, b * BLOCK:(b + 1) * BLOCK] = [v / float(1 << FRAC[A_FMT]) for v in orr]
        if b in cps or b >= SETTLE_BLOCKS:
            rec = {
                "b": b,
                "out": {"L": ol, "R": orr},
                "instances": [],
            }
            for kind, m in ains:
                rec["instances"].append({"kind": kind, **m.st.checkpoint()})
            for kind, m, _i, _s, _r in sends:
                rec["instances"].append({"kind": kind, **m.st.checkpoint()})
            trace_blocks.append(rec)

    os.makedirs(args.out_dir, exist_ok=True)
    wav_path = os.path.join(args.out_dir, f"model__{slug}__seq-notes-coverage-v1.f32.wav")
    write_wav_stereo_f32(wav_path, model_out[:, SETTLE_BLOCKS * BLOCK:SETTLE_BLOCKS * BLOCK + frames])

    trace = {
        "schema_version": 1,
        "slug": slug,
        "sequence": "seq-notes-coverage-v1",
        "settle_blocks": SETTLE_BLOCKS,
        "n_blocks_total": n_total,
        "render_frames": frames,
        "a_fixed": a_q,
        "input_peak_post_deamp": peak_in,
        "checkpoint_blocks": sorted(cps),
        "blocks": trace_blocks,
    }
    tpath = os.path.join(args.out_dir, f"model_trace_{slug}.json")
    with open(tpath, "w") as f:
        json.dump(trace, f)
    rtl_dir = os.path.join(args.out_dir, "rtl")
    emit_rtl_stimulus(cfg, blocks_in, ctrl_words_per_block, rtl_dir, slug, n_total)
    print(json.dumps({
        "slug": slug,
        "model_wav": os.path.relpath(wav_path, REPO),
        "trace": os.path.relpath(tpath, REPO),
        "blocks_total": n_total,
        "checkpoints": len(cps),
        "input_peak": peak_in,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
