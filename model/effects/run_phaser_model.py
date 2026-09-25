#!/usr/bin/env python3
"""SXT-028g: run the frozen effect chain of a Phaser fixture over its dry bus.

ORACLE-GATED. The model input is the pinned engine's all-off DRY bus
(stereo float32 WAV, SXT-012 policies) de-amped by the converged master
amplitude and quantized to Q10.21; the chain output is compared against the
pinned engine's WET bus by tools/compare_phaser_reference.py. Without those
fixture buses this tool REFUSES (exit 2, NOT_RUN) — it never fabricates a
stimulus and calls the result a reference render.

Chain reproduced (identical to the SXT-023 / SXT-028c runners):

    insert chain (scene A) -> scene hardclip -> scene sum
    -> per-send: send-gain ramp * sceneA -> effect -> return ramp * out
    -> per-global slot (G1..G4 order): effect
    -> master amplitude -> master hardclip

Per-instance capture for the RTL: the runner records, per block, the input
and output words of EVERY phaser instance at its chain boundary, plus state
and cascade checkpoints, and writes the RTL replay stimulus. The chain
wiring around the phaser (sibling FX classes, send/global routing) is
model-side and is validated against the engine separately.

Outputs (under --out-dir):
  model__<slug>__<seq>.f32.wav   chain wet bus (stereo float32)
  trace_<slug>__<seq>.json.gz    per-instance truth + chain outputs
  rtl/<slug>__<seq>_in.hex       per-instance input stimulus (replay)
  rtl/<slug>__<seq>_ctrl.hex     per-instance control-plane words
  rtl/<slug>__<seq>_meta.json    stimulus layout description

Original to this repository (Apache-2.0).
"""

import argparse
import gzip
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-phaser"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-chorus"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))

import numpy as np  # noqa: E402

from model.effects.qmath import to_q, FRAC  # noqa: E402
from model.effects.delay.delay_model import (  # noqa: E402
    DelayModel, DelayParams, db_to_linear_d, A_FMT, G_FMT, BLOCK,
)
from model.effects.eq.eq_model import EqModel, EqParams  # noqa: E402
from phaser_model import PhaserModel, PhaserParams, model_revision  # noqa: E402
# one mechanism per behaviour: the chain wiring, the Reverb1 Q10.21 bridging
# and the WAV I/O are the SXT-028c runner's, reused unchanged
from run_chorus_model import (  # noqa: E402
    Reverb1Adapter, run_chain, read_wav_stereo_f32, write_wav_stereo_f32,
    SETTLE_BLOCKS, checkpoint_set, qhex,
)

TAP_CHECKPOINT_STRIDE = 16
STAGE_SAMPLES = 4


class Refuse(Exception):
    pass


def build_models(cfg):
    def make(e):
        if e["type"] == "phaser":
            return PhaserModel(PhaserParams(e["params"]), f"p{e['slot']}")
        if e["type"] == "eq":
            return EqModel(EqParams(e["params"]), f"e{e['slot']}")
        if e["type"] == "delay":
            return DelayModel(DelayParams(e["params"]), f"d{e['slot']}")
        if e["type"] == "reverb1":
            return Reverb1Adapter(e["params"], f"r{e['slot']}")
        raise Refuse(f"unlanded FX class in chain: {e['type']}")

    ains = [(e["type"], make(e)) for e in cfg["chain"]["ains"]]
    sends = [(e["type"], make(e), e["send_slot"], e["send_gain_f"],
              e["return_f"]) for e in cfg["chain"]["sends"]]
    globals_ = [(e["type"], make(e)) for e in sorted(
        cfg["chain"].get("globals", []), key=lambda x: x["slot"])]
    return ains, sends, globals_


def phaser_instances(ains, sends, globals_):
    out = [("ains", m) for k, m in ains if k == "phaser"]
    out += [("sends", m) for k, m, _i, _s, _r in sends if k == "phaser"]
    out += [("globals", m) for k, m in globals_ if k == "phaser"]
    return out


def n_units(n_stages):
    return 4 if n_stages < 2 else 2 * n_stages


def ctrl_words(m):
    st, p, c = m.st, m.p, m.ctrl
    flags = (int(bool(c["setvars"])) | (int(not p.tone_deactivated) << 1)
             | (st.n_stages << 4))
    w = [flags, c["mix_raw"], c["ws_raw"], st.feedback.new_v, st.tone.new_v]
    w += list(st.lp.tgt) + list(st.hp.tgt)
    for u in range(n_units(st.n_stages)):
        w += list(st.apf[u].tgt)
    return [qhex(v, 64) for v in w]


def state_map(st):
    return {
        "dl": st.dl, "dr": st.dr,
        "fbv": st.feedback.v, "fbdv": st.feedback.dv,
        "fbnew": st.feedback.new_v,
        "tonev": st.tone.v, "tonedv": st.tone.dv, "tonenew": st.tone.new_v,
        "mixc": st.mix.current, "mixt": st.mix.target,
        "wsc": st.width_s.current, "wst": st.width_s.target,
        "lp_lag": list(st.lp.lag), "hp_lag": list(st.hp.lag),
        "lp_reg0": list(st.lp.reg0), "lp_reg1": list(st.lp.reg1),
        "hp_reg0": list(st.hp.reg0), "hp_reg1": list(st.hp.reg1),
        "apfhash": st.apf_hash(),
        "ext_reads": st.ext_reads, "ext_writes": st.ext_writes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--seq", default="seq-notes-coverage-v1")
    ap.add_argument("--fixtures-dir",
                    default=os.path.join(REPO, "reports", "SXT-028g",
                                         "fixtures"))
    ap.add_argument("--inputs-dir",
                    default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "reports", "SXT-028g",
                                         "artifacts"))
    args = ap.parse_args()

    cfg_path = os.path.join(args.inputs_dir, f"type-phaser-{args.slug}.json")
    if not os.path.exists(cfg_path):
        raise Refuse(f"no extracted input for slug {args.slug}: {cfg_path} — "
                     "run tools/extract_phaser_inputs.py on the oracle host")
    cfg = json.load(open(cfg_path))
    if cfg.get("source") != "oracle-extraction":
        raise Refuse(
            f"{cfg_path} is a {cfg.get('source')!r} record, not an oracle "
            "extraction: a reference render may only be driven by a "
            "census-verified preset extraction (fail-closed)")
    dry_path = os.path.join(args.fixtures_dir,
                            f"{args.slug}__{args.seq}-dry.f32.wav")
    if not os.path.exists(dry_path):
        raise Refuse(f"no fixture dry bus: {dry_path} — render it from the "
                     "pinned oracle first (tools/render_phaser_fixtures.py)")

    dry, _sr = read_wav_stereo_f32(dry_path)
    frames = dry.shape[1]
    n_total = SETTLE_BLOCKS + (-(-frames // BLOCK))
    frames_padded = n_total * BLOCK

    a_d = db_to_linear_d(cfg["volume_f"])
    a_q = to_q(a_d, G_FMT)
    in_l_f = dry[0] / a_d
    in_r_f = dry[1] / a_d
    peak_in = float(max(np.max(np.abs(in_l_f)), np.max(np.abs(in_r_f))))
    if peak_in >= 7.9:
        raise Refuse(f"input peak {peak_in} too close to the scene hardclip; "
                     "declared inactive-clip boundary violated")

    zeros = [0] * (SETTLE_BLOCKS * BLOCK)
    pad = frames_padded - SETTLE_BLOCKS * BLOCK - frames
    in_l = zeros + [to_q(float(x), A_FMT) for x in in_l_f] + [0] * pad
    in_r = zeros + [to_q(float(x), A_FMT) for x in in_r_f] + [0] * pad

    ains, sends, globals_ = build_models(cfg)
    for _k, m in ains:
        m.initialize()
    for _k, m, _i, _s, _r in sends:
        m.initialize()
    for _k, m in globals_:
        m.initialize()
    phs = phaser_instances(ains, sends, globals_)
    if not phs:
        raise Refuse(f"no phaser instance in chain: {args.slug}")

    for _pos, m in phs:
        orig = m.process_block

        def capturing(inl, inr, _m=m, _op=orig, stage_hook=None):
            if _m._cap_in is None:
                _m._cap_in = (list(inl), list(inr))
            if _m._cap_stages:
                _m._cap_store = []

                def hook(k, tr, _s=_m._cap_store):
                    if k < STAGE_SAMPLES:
                        _s.append(list(tr))
                out = _op(inl, inr, stage_hook=hook)
            else:
                out = _op(inl, inr)
            _m._cap_out = out
            return out

        m.process_block = capturing

    cps = checkpoint_set(n_total)
    trace_blocks = []
    blocks_in = []
    ctrl_lines = []
    model_out = np.zeros((2, frames_padded), dtype=np.float32)

    for b in range(n_total):
        il = in_l[b * BLOCK:(b + 1) * BLOCK]
        ir = in_r[b * BLOCK:(b + 1) * BLOCK]
        want = (b in cps) or (b >= SETTLE_BLOCKS
                              and ((b - SETTLE_BLOCKS) % TAP_CHECKPOINT_STRIDE
                                   == 0 or b == n_total - 1))
        for _pos, m in phs:
            m._cap_in = None
            m._cap_out = None
            m._cap_stages = want
            m._cap_store = None

        ol, orr = run_chain(ains, sends, globals_, il, ir, a_q)

        blocks_in.append([m._cap_in for _pos, m in phs])
        words = []
        for _pos, m in phs:
            words += ctrl_words(m)
        ctrl_lines.append(words)

        model_out[0, b * BLOCK:(b + 1) * BLOCK] = \
            [v / float(1 << FRAC[A_FMT]) for v in ol]
        model_out[1, b * BLOCK:(b + 1) * BLOCK] = \
            [v / float(1 << FRAC[A_FMT]) for v in orr]

        if b in cps or b >= SETTLE_BLOCKS:
            rec = {"b": b, "chain_out": {"L": ol, "R": orr}, "instances": []}
            for _pos, m in phs:
                irec = {"kind": "phaser", "name": m.st.name, **state_map(m.st)}
                if m._cap_out is not None:
                    irec["out"] = {"L": m._cap_out[0], "R": m._cap_out[1]}
                if m._cap_store is not None:
                    irec["stages"] = m._cap_store
                rec["instances"].append(irec)
            trace_blocks.append(rec)

    os.makedirs(args.out_dir, exist_ok=True)
    wav_path = os.path.join(args.out_dir,
                            f"model__{args.slug}__{args.seq}.f32.wav")
    write_wav_stereo_f32(wav_path, model_out[:, SETTLE_BLOCKS * BLOCK:
                                             SETTLE_BLOCKS * BLOCK + frames])

    trace = {"schema_version": 1, "leaf": "SXT-028g", "slug": args.slug,
             "sequence": args.seq, "settle_blocks": SETTLE_BLOCKS,
             "n_blocks_total": n_total, "render_frames": frames,
             "n_phaser_instances": len(phs), "a_fixed": a_q,
             "input_peak_post_deamp": peak_in,
             "checkpoint_blocks": sorted(cps),
             "stage_samples_per_block": STAGE_SAMPLES,
             "model_revision": model_revision(),
             "blocks": trace_blocks}
    tpath = os.path.join(args.out_dir,
                         f"trace_{args.slug}__{args.seq}.json.gz")
    with gzip.open(tpath, "wt") as f:
        json.dump(trace, f)

    rtl_dir = os.path.join(args.out_dir, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)
    with open(os.path.join(rtl_dir,
                           f"{args.slug}__{args.seq}_in.hex"), "w") as fi:
        for insts in blocks_in:
            for inl, inr in insts:
                for v in inl:
                    fi.write(qhex(v, 32) + "\n")
                for v in inr:
                    fi.write(qhex(v, 32) + "\n")
    with open(os.path.join(rtl_dir,
                           f"{args.slug}__{args.seq}_ctrl.hex"), "w") as fc:
        for words in ctrl_lines:
            for w in words:
                fc.write(w + "\n")
    meta = {"slug": args.slug, "sequence": args.seq, "blocks": n_total,
            "n_phaser_instances": len(phs),
            "per_block_input": "per phaser instance in processing order: "
                               "32 x Q10.21 L words then 32 x Q10.21 R words",
            "per_block_control": "per phaser instance in processing order: "
                                 "flags, mix raw, widthS raw, feedback "
                                 "newValue, tone newValue, lp x5, hp x5, then "
                                 "5 coefficient targets per configured APF "
                                 "biquad unit (see rtl/effects/type-phaser/"
                                 "tb_phaser.sv)"}
    with open(os.path.join(rtl_dir,
                           f"{args.slug}__{args.seq}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(json.dumps({"slug": args.slug, "seq": args.seq,
                      "model_wav": os.path.relpath(wav_path, REPO),
                      "trace": os.path.relpath(tpath, REPO),
                      "blocks_total": n_total,
                      "phaser_instances": len(phs),
                      "input_peak": peak_in}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING (NOT_RUN, never a pass): {e}", file=sys.stderr)
        sys.exit(2)
