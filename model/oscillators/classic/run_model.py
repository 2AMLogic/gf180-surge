#!/usr/bin/env python3
"""SXT-033 model runner: render a fixture sequence through the frozen
Classic-family model and emit the RTL stimulus.

Outputs (under --out-dir):
  model.wav           int16 mono render (fixtures WAV convention)
  model_trace.json    declared checkpoints + full sample stream
  rtl/init.hex        one-time control-plane constants (see word order below)
  rtl/ctrl.hex        per-block control words (see record layout below)
  rtl/sinc_main.hex   sinctable ROM (main taps), 32-bit hex words
  rtl/sinc_deriv.hex  sinctable ROM (derivative taps)

Declared control-plane boundary (as landed in SXT-022): rate-table /
note-to-pitch words, pitchmult/a_cov, the hpf ramp endpoints, gain ramp
targets, and the sinc ROM are computed in the model and streamed to the RTL.
The per-voice unison rate words (t_u / t_sync_u / t_inv_u — constant per
voice instance) are streamed on voice creation (record flag b2). The RTL
reproduces the envelope state machine, the per-unison-voice impulse engines
(including the hard-sync restart machine), the shared extraction /
character-filter stage, and the halfband output chain, and must match the
model trace EXACTLY at every declared checkpoint (integer equality;
tools/compare_classic_rtl_model.py).

init.hex word order (32-bit words):
  0 n_unison   1 out_attenuation
  2..17   t_u[16]        (Q10.21 impulse rate, per unison voice; probe instance)
  18..33  t_sync_u[16]   (Q10.21 sync restart period)
  34..49  t_inv_u[16]    (Q10.21 1/t, exact division)
  50 t_shape  51 t_pw  52 t_pw2  53 t_sub  54 t_sync  55 lag_rate
  56 char_a1  57 char_b0  58 char_b1
  59 hpf_init  60 integrator_hpf  61 total_blocks
  62 aeg_a  63 aeg_d  64 aeg_r  65 aeg_s(Q2.29)  66 aeg_r_s
  67 inst_att_aeg
  68..73 halfband B0..B5  74..79 halfband A0..A5

ctrl.hex: per block a 10-word header [b, slotmask, master_amp, 0..0], then
one record per PROCESSED slot in slot order (released voices carry their
final block's record so the stream stays aligned):
  0 key  1 flags(b0 gate, b1 checkpoint, b2 created, b3 released)
  2 pmi(Q13.18)  3 pitchmult(Q10.21)  4 a_cov(Q10.21)
  5 hpf_start  6 hpf_d  7 lvl  8 pfg  9 gain_start  10 d_gain  11 outl
  created only (b2): 12..59 t_u[16] ++ t_sync_u[16] ++ t_inv_u[16]
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "classic"))
sys.path.insert(0, REPO)

import classic_model as cm  # noqa: E402
from model.voice import voice_model as vm  # noqa: E402

FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
CHECKPOINT_EVERY = 64
N_SLOTS = 8
REC = 12
REC_NEW = REC + 48


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


def _pad16(xs):
    return list(xs) + [0] * (16 - len(xs))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", required=True,
                    help="inputs/<name>.json (extract_inputs.py output)")
    ap.add_argument("--sequence", required=True,
                    help="sequence id or JSON path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--rtl", action="store_true",
                    help="emit the RTL stimulus files")
    ap.add_argument("--max-blocks", type=int, default=None,
                    help="cap the render at N blocks (smoke runs)")
    args = ap.parse_args()

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences", seq_path + ".json")
    seq = vm.load_sequence(seq_path)
    inp = cm.Inputs(args.inputs)
    if not inp.retrigger:
        raise RuntimeError("retrigger off is outside the declared fixture "
                           "configuration (deterministic starts required)")

    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    if not notes:
        raise RuntimeError("sequence has no notes")
    last_t = max(e["t"] for e in notes)
    total_samples = last_t + int(float(seq.get("tail_s", 1.5)) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)
    if args.max_blocks:
        total_blocks = min(total_blocks, args.max_blocks)
        total_samples = total_blocks * BLOCK_SIZE

    master = vm.db_to_linear(vm.qint(inp.master_db))
    halfband = vm.HalfbandD2()
    probe = cm.Slice(inp, 60, 100)   # constants for init.hex only

    voices = []
    events = list(seq["events"])
    ei = 0
    out_mono = []
    blocks_json = []
    ctrl = []

    for b in range(total_blocks):
        blk = {"b": b, "create": [], "release": [], "voices": []}
        while ei < len(events) and -(-events[ei]["t"] // BLOCK_SIZE) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS)
                            if all(v.slot != i for v in voices))
                v = cm.Slice(inp, e["note"], e.get("velocity", 100))
                v.slot = slot
                voices.append(v)
                blk["create"].append(slot)
            elif e["type"] == "note_off":
                for v in reversed(voices):
                    if v.key == e["note"] and v.gate:
                        v.aeg.release()
                        v.gate = False
                        blk["release"].append(v.slot)
                        break
            ei += 1

        scene = [0] * vm.BLOCK_SIZE_OS
        alive = []
        slotmask = 0
        recs = []
        for v in voices:
            osout, keep = v.process_block(b, scene)
            full = (b % CHECKPOINT_EVERY == 0) or (not v.gate) or b < 2
            rec = {"slot": v.slot, "key": v.key, "gate": v.gate}
            if full and keep:
                rec["oscout_block"] = osout
                rec["after"] = {
                    "aeg": {"state": v.aeg.state, "phase": v.aeg.phase,
                            "output": v.aeg.output},
                    "oscstate": [st["oscstate"] for st in v.osc.voices],
                    "syncstate": [st["syncstate"] for st in v.osc.voices],
                    "state": [st["state"] for st in v.osc.voices],
                    "last_level": [st["last_level"] for st in v.osc.voices],
                    "pwidth": [st["pwidth"] for st in v.osc.voices],
                    "pwidth2": [st["pwidth2"] for st in v.osc.voices],
                    "dc_uni": [st["dc_uni"] for st in v.osc.voices],
                    "l_shape": v.osc.l_shape, "l_pw": v.osc.l_pw,
                    "l_pw2": v.osc.l_pw2, "l_sub": v.osc.l_sub,
                    "l_sync": v.osc.l_sync,
                    "dc": v.osc.dc, "osc_out": v.osc.osc_out,
                    "osc_out2": v.osc.osc_out2, "bufpos": v.osc.bufpos,
                    "hpf_prev": v.osc.hpf_prev,
                    "gain_end": v.prev_gain,
                }
            blk["voices"].append(rec)
            slotmask |= (1 << v.slot)
            if args.rtl:
                words = [
                    v.key & 0xFF,
                    (1 if v.gate else 0) | (2 if full else 0)
                    | (4 if v.slot in blk["create"] else 0)
                    | (8 if v.slot in blk["release"] else 0),
                    v.osc.ctrl_pmi, v.pitchmult, v.ctrl_a_cov,
                    v.ctrl_hpf_start, v.ctrl_hpf_d,
                    v.lvl, v.pfg, v.ctrl_gain_start, v.ctrl_d_gain, v.outl,
                ]
                if v.slot in blk["create"]:
                    words += (_pad16(v.osc.t_u) + _pad16(v.osc.t_sync_u)
                              + _pad16(v.osc.t_inv_u))
                recs.append((v.slot, words))
            if keep:
                alive.append(v)
        voices = alive

        scene = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene]
        bl = halfband.process(scene)
        mono_block = []
        for k in range(BLOCK_SIZE):
            l = vm.qmul(bl[k], master)
            l = vm.limit_i(l, vm.qint(-8.0), vm.qint(8.0))
            m = vm.limit_i(l, -vm.ONE, vm.ONE)
            mono_block.append(m)
            s = (m * 32767) >> FQ if m >= 0 else -((-m * 32767) >> FQ)
            out_mono.append(s)
        blk["mono_block"] = mono_block
        blocks_json.append(blk)

        if args.rtl:
            ctrl.extend([b, slotmask, master, 0, 0, 0, 0, 0, 0, 0])
            for slot, words in sorted(recs, key=lambda t: t[0]):
                ctrl.extend(words)

    os.makedirs(args.out_dir, exist_ok=True)
    rtl_dir = os.path.join(args.out_dir, "rtl")
    if args.rtl:
        os.makedirs(rtl_dir, exist_ok=True)

    vm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono, vm.SR)

    with open(os.path.join(args.out_dir, "model_trace.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "format": "sxt-033-classic-trace/1",
            "sequence": seq["id"],
            "inputs": os.path.relpath(args.inputs, REPO),
            "engine_pin": ("surge-synthesizer/surge@"
                           "58914e59c608ed4384ba6002e44c3465c58b2e71"),
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q10.21", "env_phase": "Q2.29",
                          "pitchmult_inv": "Q13.18"},
            "n_unison": inp.unison,
            "n_slots": N_SLOTS,
            "blocks": blocks_json,
            "samples16": out_mono,
        }, f)
        f.write("\n")

    if args.rtl:
        o = probe.osc
        a = inp.adsr
        a_min_const = vm.qint(-8.0)
        inst_att = 1 if (vm.qint(a["a"]) - a_min_const) < vm.qint(0.01) else 0
        init_words = ([o.n_unison, o.out_attenuation]
                      + _pad16(o.t_u) + _pad16(o.t_sync_u) + _pad16(o.t_inv_u)
                      + [o.t_shape, o.t_pw, o.t_pw2, o.t_sub, o.t_sync,
                         cm.LAG_RATE, o.char_a1, o.char_b0, o.char_b1,
                         o.hpf_prev, cm.INTEGRATOR_HPF, total_blocks,
                         vm.envelope_rate_linear_nowrap(vm.qint(a["a"])),
                         vm.envelope_rate_linear_nowrap(vm.qint(a["d"])),
                         vm.envelope_rate_linear_nowrap(vm.qint(a["r"])),
                         vm.qint_phase(a["s"]), int(a["r_s"]),
                         inst_att,
                         *vm.HALFBAND_B_Q, *vm.HALFBAND_A_Q,
                         int(a["d_s"]), vm.qint(a["d"])])
        write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
        write_hex(os.path.join(rtl_dir, "ctrl.hex"), ctrl)
        write_hex(os.path.join(rtl_dir, "sinc_main.hex"), vm.SINC_MAIN)
        write_hex(os.path.join(rtl_dir, "sinc_deriv.hex"), vm.SINC_DERIV)

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks,
        "samples": len(out_mono),
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
