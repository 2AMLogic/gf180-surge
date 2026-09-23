#!/usr/bin/env python3
"""SXT-040 model runner: render a fixture sequence through the frozen
Sine-family model and emit the RTL stimulus.

Outputs (under --out-dir):
  model.wav           int16 mono render (fixtures WAV convention)
  model_trace.json    declared checkpoints + full sample stream
  rtl/init.hex        one-time control-plane constants (see word order below)
  rtl/ctrl.hex        per-block control words (see record layout below)

Declared control-plane boundary (as landed in SXT-022/SXT-033): envelope
rate words, the per-voice omega words (Q3.28, constant per voice instance),
the fb/FM lag targets, the lowcut/highcut biquad coefficients, the character
filter words and the halfband coefficients are computed in the model and
streamed to the RTL. The RTL reproduces the envelope state machine, the
per-unison-voice sine engines (legacy quadrature recurrence AND modern
phase/feedback machine, all 32 shape modes), the shared applyFilter /
character stages, and the halfband output chain, and must match the model
trace EXACTLY at every declared checkpoint (integer equality;
tools/compare_sine_rtl_model.py).

init.hex word order (32-bit words):
  0 mode(shape)  1 legacy flag  2 n_unison  3 out_attenuation  4 dplaying
  5 fb_target  6 lag_lp  7 lag_lpinv  8 do_filter
  9..24   omega_u[16]      (Q3.28, per unison voice; probe instance)
  25..40  char/hp/lp words: char_a1, char_b0 (41 unused pads to 42)
  ... exact layout: see INIT_LAYOUT below

ctrl.hex: per block a 10-word header [b, slotmask, master_amp, 0..0], then
one record per PROCESSED slot in slot order (released voices carry their
final block's record so the stream stays aligned):
  0 key  1 flags(b0 gate, b1 checkpoint, b2 created, b3 released)
  2 lvl  3 pfg  4 gain_start  5 d_gain  6 outl
  created only (b2): 7..22 omega_u[16]
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "sine"))
sys.path.insert(0, REPO)

import sine_model as sm  # noqa: E402
from model.voice import voice_model as vm  # noqa: E402

FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
CHECKPOINT_EVERY = 64
N_SLOTS = 8
REC = 7
REC_NEW = REC + 16

# init.hex layout (indices are normative for the RTL):
#   0 mode  1 legacy  2 n_unison  3 out_attenuation  4 dplaying
#   5 fb_target  6 lag_lp  7 lag_lpinv  8 do_filter
#   9..24 omega_u[16]
#   25 char_a1  26 char_b0  27 char_b1(always 0)
#   28..37 hp b0 b1 b2 a1 a2  38..47 lp b0 b1 b2 a1 a2
#   48 aeg_a  49 aeg_d  50 aeg_r  51 aeg_s(Q2.29)  52 aeg_r_s
#   53 inst_att_aeg  54 d_s  55 aeg_d_word
#   56..61 halfband B0..B5  62..67 halfband A0..A5
#   68 total_blocks
INIT_LEN = 69


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
    inp = sm.Inputs(args.inputs)
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
    probe = sm.Slice(inp, 60, 100)   # constants for init.hex only

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
                v = sm.Slice(inp, e["note"], e.get("velocity", 100))
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
                o = v.osc
                after = {
                    "aeg": {"state": v.aeg.state, "phase": v.aeg.phase,
                            "output": v.aeg.output},
                    "gain_end": v.prev_gain,
                    "fb_v": o.fb.v, "fm_v": o.fm.v,
                    "firstblock": 1 if o.firstblock else 0,
                    "hp_r0": o.hp.reg0, "hp_r1": o.hp.reg1,
                    "lp_r0": o.lp.reg0, "lp_r1": o.lp.reg1,
                    "char_py": o.charfilt.py, "char_px": o.charfilt.px,
                }
                if o.legacy:
                    after["quad_r"] = [q.r for q in o.quad]
                    after["quad_i"] = [q.i for q in o.quad]
                    after["quad_dr"] = [q.dr for q in o.quad]
                    after["quad_di"] = [q.di for q in o.quad]
                    after["pramp"] = list(o.pramp)
                else:
                    after["phase"] = list(o.phase)
                    after["lv0"] = list(o.lv0)
                    after["lv1"] = list(o.lv1)
                    after["om_prior"] = list(o.om_prior)
                    after["prior_valid"] = 1 if o.prior_valid else 0
                rec["oscout_block"] = osout
                rec["after"] = after
            blk["voices"].append(rec)
            slotmask |= (1 << v.slot)
            if args.rtl:
                words = [
                    v.key & 0xFF,
                    (1 if v.gate else 0) | (2 if full else 0)
                    | (4 if v.slot in blk["create"] else 0)
                    | (8 if v.slot in blk["release"] else 0),
                    v.lvl, v.pfg, v.ctrl_gain_start, v.ctrl_d_gain, v.outl,
                ]
                if v.slot in blk["create"]:
                    words += _pad16(v.osc.omega_u)
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
            "format": "sxt-040-sine-trace/1",
            "sequence": seq["id"],
            "inputs": os.path.relpath(args.inputs, REPO),
            "engine_pin": ("surge-synthesizer/surge@"
                           "58914e59c608ed4384ba6002e44c3465c58b2e71"),
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q10.21", "env_phase": "Q2.29",
                          "sine_phase_omega": "Q3.28"},
            "shape_mode": inp.shape,
            "legacy": inp.fmmode == 0,
            "n_unison": inp.unison,
            "n_slots": N_SLOTS,
            "nc_markers": {
                "shape_rawvalue_confusion":
                    bool(os.environ.get("SXT040_NC_SHAPE_RAWVALUE")),
            },
            "blocks": blocks_json,
            "samples16": out_mono,
        }, f)
        f.write("\n")

    if args.rtl:
        o = probe.osc
        a = inp.adsr
        a_min_const = vm.qint(-8.0)
        inst_att = 1 if (vm.qint(a["a"]) - a_min_const) < vm.qint(0.01) else 0
        iw = {}
        iw[0] = o.mode
        iw[1] = 1 if o.legacy else 0
        iw[2] = o.n_unison
        iw[3] = o.out_attenuation
        iw[4] = sm.DPLAYING
        iw[5] = o.fb_t
        iw[6] = sm.LAG_LP
        iw[7] = sm.LAG_LPINV
        iw[8] = 1 if o.charfilt.do_filter else 0
        for i, w in enumerate(_pad16(o.omega_u)):
            iw[9 + i] = w
        iw[25], iw[26], iw[27] = o.charfilt.a1, o.charfilt.b0, o.charfilt.b1
        for i, w in enumerate((o.hp.b0, o.hp.b1, o.hp.b2, o.hp.a1, o.hp.a2)):
            iw[28 + i] = w
        for i, w in enumerate((o.lp.b0, o.lp.b1, o.lp.b2, o.lp.a1, o.lp.a2)):
            iw[38 + i] = w
        iw[48] = vm.envelope_rate_linear_nowrap(vm.qint(a["a"]))
        iw[49] = vm.envelope_rate_linear_nowrap(vm.qint(a["d"]))
        iw[50] = vm.envelope_rate_linear_nowrap(vm.qint(a["r"]))
        iw[51] = vm.qint_phase(a["s"])
        iw[52] = int(a["r_s"])
        iw[53] = inst_att
        iw[54] = int(a["d_s"])
        iw[55] = vm.qint(a["d"])
        for i, w in enumerate(vm.HALFBAND_B_Q):
            iw[56 + i] = w
        for i, w in enumerate(vm.HALFBAND_A_Q):
            iw[62 + i] = w
        iw[68] = total_blocks
        init_words = [iw.get(i, 0) for i in range(INIT_LEN)]
        assert len(init_words) == INIT_LEN, (len(init_words), INIT_LEN)
        write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
        write_hex(os.path.join(rtl_dir, "ctrl.hex"), ctrl)

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks,
        "samples": len(out_mono),
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
