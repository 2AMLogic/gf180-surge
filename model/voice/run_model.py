#!/usr/bin/env python3
"""SXT-022 model runner: render a fixture sequence through the frozen model.

Outputs (under --out-dir):
  model.wav             int16 mono render (fixtures WAV convention)
  model_trace.json      declared state checkpoints + full sample stream
  rtl/init.hex          one-time control-plane constants for the RTL testbench
  rtl/ctrl.hex          per-block control words for the RTL testbench
  rtl/sinc_main.hex     sinctable ROM (main taps), 32-bit hex words
  rtl/sinc_deriv.hex    sinctable ROM (derivative taps), 32-bit hex words

Declared control-plane boundary: block-rate coefficient generation (rate
tables, note_to_pitch, coupled-form transform incl. sqrt and division)
lives in the model and is streamed to the RTL. The RTL reproduces the
envelope state machines and the complete audio-rate datapath and must
match the model trace EXACTLY at every declared checkpoint (integer
equality; enforced by tools/compare_rtl_model.py).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402

PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
N_SLOTS = 8
CHECKPOINT_EVERY = 64


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", default=os.path.join(REPO, "model", "voice", "attacky_inputs.json"))
    ap.add_argument("--graphs", default=os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"))
    ap.add_argument("--sequence", required=True, help="sequence id or JSON path")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences", seq_path + ".json")
    seq = vm.load_sequence(seq_path)

    inp = vm.Inputs(args.inputs, args.graphs, PRESET_REL)
    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_samples = last_t + int(seq.get("tail_s", 2.5) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)

    master_amp = vm.db_to_linear(vm.qint(inp.master_db))
    a_min_const = vm.qint_phase(-8.0)
    eps01 = vm.qint_phase(0.01)
    inst_att_aeg = 1 if (vm.qint_phase(inp.adsr["a"]) - a_min_const) < eps01 else 0
    inst_att_feg = 1 if (vm.qint_phase(inp.fadsr["a"]) - a_min_const) < eps01 else 0

    init_words = [
        vm.qint_phase(inp.adsr["a"]), vm.qint_phase(inp.adsr["d"]),
        vm.qint_phase(inp.adsr["r"]), vm.qint_phase(inp.adsr["s"]),
        int(inp.adsr["a_s"]), int(inp.adsr["r_s"]),
        vm.qint_phase(inp.fadsr["a"]), vm.qint_phase(inp.fadsr["d"]),
        vm.qint_phase(inp.fadsr["r"]), vm.qint_phase(inp.fadsr["s"]),
        int(inp.fadsr["a_s"]), int(inp.fadsr["r_s"]),
        limit_or(qint_p(inp.shape), -1, 1), limit_or(qint_p(inp.pw1), 0.001, 0.999),
        limit_or(qint_p(inp.pw2), 0.001, 0.999), limit_or(qint_p(inp.submix), 0.0, 1.0),
        qint_p(max(0.0, inp.sync)),
        0, 0, 0, 0, 0, 0,          # placeholder, replaced below (probe voice)
        master_amp, total_blocks, last_t,
        vm.qint(inp.envmod),
        inst_att_aeg, inst_att_feg, a_min_const, eps01,
    ]
    probe = vm.Voice(inp, 60, 100)
    init_words[17] = probe.char_a1
    init_words[18] = probe.char_b0
    init_words[19] = probe.char_b1
    init_words[20] = vm.amp_to_linear(vm.qint(inp.o1_level))
    init_words[21] = probe.integrator_hpf

    voices = []
    events = list(seq["events"])
    ei = 0
    bs = BLOCK_SIZE
    halfband = vm.HalfbandD2()
    out_mono = []
    blocks_json = []
    ctrl = []

    for b in range(total_blocks):
        blk = {"b": b, "create": [], "release": [], "voices": []}
        while ei < len(events) and -(-events[ei]["t"] // bs) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS) if all(v.slot != i for v in voices))
                v = vm.Voice(inp, e["note"], e.get("velocity", 0))
                v.slot = slot
                voices.append(v)
                blk["create"].append(slot)
            elif e["type"] == "note_off":
                for v in reversed(voices):
                    if v.key == e["note"] and v.gate:
                        v.aeg.release()
                        v.feg.release()
                        v.gate = False
                        blk["release"].append(v.slot)
                        break
            elif e["type"] == "cc":
                if e["channel"] == 0 and e["controller"] == 1:
                    inp.modwheel.set_target(e["value"])
            ei += 1
        inp.modwheel.process_block()

        scene_l, scene_r = [0] * vm.BLOCK_SIZE_OS, [0] * vm.BLOCK_SIZE_OS
        alive = []
        for v in voices:
            keep = v.process_block(b, scene_l, scene_r, None)
            if keep:
                alive.append(v)
        voices = alive

        # control words: header + one 32-word record per slot (post-block state)
        ctrl.extend([b, len(blk["create"]), inp.modwheel.value, master_amp])
        for slot in range(N_SLOTS):
            v = next((x for x in voices if x.slot == slot), None)
            if v is None:
                ctrl.extend([0] * 32)
                continue
            full = (b % CHECKPOINT_EVERY == 0) or (not v.gate) or (b < 2)
            flags = 1 | (2 if full else 0) | (4 if slot in blk["create"] else 0) \
                    | (8 if slot in blk["release"] else 0)
            ctrl.extend([
                flags,
                v.key, v.gate,
                v.aeg.state, v.feg.state,
                v.ctrl_pmi, v.ctrl_pitchmult, v.ctrl_a_cov, v.ctrl_hpf_target,
                *v.ctrl_C, *v.ctrl_dC,
                v.fbp_gain, v.fbp_outl,
                v.aeg.phase, v.aeg.output, v.feg.phase, v.feg.output,
                0,
            ])
            rec = {"slot": slot, "key": v.key, "gate": v.gate}
            if full:
                rec["oscout_block"] = v.last_oscout
                rec["after"] = {
                    "aeg": {"state": v.aeg.state, "phase": v.aeg.phase,
                            "output": v.aeg.output},
                    "feg": {"state": v.feg.state, "phase": v.feg.phase,
                            "output": v.feg.output},
                    "oscstate": v.oscstate, "osc_state": v.osc_state,
                    "last_level": v.last_level,
                    "pwidth": v.pwidth, "pwidth2": v.pwidth2,
                    "dc_uni": v.dc_uni, "dc": v.dc,
                    "osc_out": v.osc_out, "osc_out2": v.osc_out2,
                    "bufpos": v.bufpos,
                    "f_r0": v.f_r0, "f_r1": v.f_r1, "f_clip": v.f_clip,
                    "C_end": list(v.cmu.C),
                    "fbp_gain": v.fbp_gain, "fbp_outl": v.fbp_outl,
                }
            blk["voices"].append(rec)

        scene_l = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene_l]
        scene_r = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene_r]
        bl = halfband.process(scene_l)
        br = halfband.process(scene_r)
        mono = []
        for k in range(bs):
            l = vm.qmul(bl[k], master_amp)
            r = vm.qmul(br[k], master_amp)
            l = vm.limit_i(l, vm.qint(-8.0), vm.qint(8.0))
            r = vm.limit_i(r, vm.qint(-8.0), vm.qint(8.0))
            m = (l + r) >> 1
            m = vm.limit_i(m, -vm.ONE, vm.ONE)
            s = (m * 32767) >> FQ if m >= 0 else -((-m * 32767) >> FQ)
            out_mono.append(s)
            mono.append(m)
        blk["mono_block"] = mono
        blocks_json.append(blk)

    os.makedirs(args.out_dir, exist_ok=True)
    rtl_dir = os.path.join(args.out_dir, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)

    vm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono, vm.SR)

    with open(os.path.join(args.out_dir, "model_trace.json"), "w", encoding="utf-8") as f:
        json.dump({
            "format": "sxt-022-voice-trace/1",
            "sequence": seq["id"],
            "preset": PRESET_REL,
            "engine_pin": "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71",
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q4.27", "env_phase": "Q2.29",
                          "pitchmult_inv": "Q13.18"},
            "slots": N_SLOTS,
            "init_words_order": [
                "aeg_a", "aeg_d", "aeg_r", "aeg_s", "aeg_a_s", "aeg_r_s",
                "feg_a", "feg_d", "feg_r", "feg_s", "feg_a_s", "feg_r_s",
                "l_shape", "l_pw", "l_pw2", "l_sub", "l_sync",
                "char_a1", "char_b0", "char_b1",
                "o1_level", "integrator_hpf", "(unused)",
                "master_amp", "total_blocks", "last_event_t",
                "envmod_q",
                "inst_att_aeg", "inst_att_feg", "a_min_const", "eps01_const",
            ],
            "init": init_words,
            "ctrl_words_per_slot": 32,
            "ctrl_slot_word_order": [
                "flags(b0 active,b1 checkpoint,b2 created,b3 released)", "key", "gate",
                "aeg_state", "feg_state",
                "pmi_q20", "pitchmult_q27", "a_cov_q27", "hpf_target",
                "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7",
                "dC0", "dC1", "dC2", "dC3", "dC4", "dC5", "dC6", "dC7",
                "fbp_gain", "fbp_outl",
                "aeg_phase", "aeg_output", "feg_phase", "feg_output",
                "(reserved)",
            ],
            "blocks": blocks_json,
            "samples16": out_mono,
        }, f)
        f.write("\n")

    write_hex(os.path.join(rtl_dir, "ctrl.hex"), ctrl)
    write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
    write_hex(os.path.join(rtl_dir, "sinc_main.hex"), vm.SINC_MAIN)
    write_hex(os.path.join(rtl_dir, "sinc_deriv.hex"), vm.SINC_DERIV)

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks, "samples": len(out_mono),
        "trace": os.path.join(args.out_dir, "model_trace.json"),
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


def qint_p(x):
    return vm.qint(x)


def limit_or(x, lo, hi):
    return vm.limit_i(x, vm.qint(lo), vm.qint(hi))


if __name__ == "__main__":
    sys.exit(main())
