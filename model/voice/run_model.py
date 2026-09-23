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
CTRL_WORDS_PER_SLOT = 40     # v2 stimulus: 32 x v1 + fvel/kt/omega1..3


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


def load_inputs(path):
    """Schema-1 (SXT-022 v1) or schema-2 (SXT-026a v2) inputs + adapter."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if raw.get("schema_version") == 2:
        inp = vm.InputsV2(path)
        inp.check_sequence_required = True
        return inp, raw["preset"]["path"], True
    inp = vm.Inputs(path, os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
                    PRESET_REL)
    # v2-runner adapter for the frozen v1 class (all inert, v1-exact)
    inp.osc_kind = "classic"
    inp.fu_poles = 12
    inp.mix1 = vm.ONE
    inp.scene_octave = 0
    inp.keytrack_root = 60
    inp.voice_routes = []
    inp.scene_routes_fm = False
    inp.fm_depth = 0
    inp.sine_lowcut = inp.sine_highcut = 0.0
    inp.osc_pitch_offsets = [12 * inp.octave, 0, 0]
    return inp, PRESET_REL, False


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

    inp, preset_rel, is_v2 = load_inputs(args.inputs)
    if is_v2:
        inp.check_sequence(seq)
    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_samples = last_t + int(seq.get("tail_s", 2.5) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)

    master_amp = vm.db_to_linear(vm.qint(inp.master_db))
    a_min_const = vm.qint(-8.0)
    eps01 = vm.qint(0.01)
    inst_att_aeg = 1 if (vm.qint(inp.adsr["a"]) - a_min_const) < eps01 else 0
    inst_att_feg = 1 if (vm.qint(inp.fadsr["a"]) - a_min_const) < eps01 else 0
    probe = vm.VoiceV2(inp, 60, 100)
    # the probe voice is discarded (character-filter/attenuation words only);
    # reset the declared draw cursor so the rendered voices consume the
    # committed init_phase_draws list from its start
    inp.reset_draws()

    def envrate(p):
        return vm.envelope_rate_linear_nowrap(vm.qint(p))

    # UNI block (see tb_voice.sv cfg map, words 78+): unison stack constants
    # (per-voice detune tables precomputed in the model's control plane)
    uni_n = max(1, int(inp.n_unison))
    uni_words = [uni_n, probe.out_attenuation]
    for u in probe.u:
        uni_words += [u["t"], u["t_inv"], u["oscstate"]]
    uni_words += [0] * (3 * 16 - 3 * len(probe.u))

    # INIT_ORDER (see tb_voice.sv cfg map); words 0..39 are the frozen v1
    # layout, 40..77 the SXT-026a parameterization appendix, 78.. the SXT-034
    # unison appendix.
    sine = probe.kind == "sine"
    init_words = [
        envrate(inp.adsr["a"]), envrate(inp.adsr["d"]), envrate(inp.adsr["r"]),
        vm.qint_phase(inp.adsr["s"]), int(inp.adsr["r_s"]),
        envrate(inp.fadsr["a"]), envrate(inp.fadsr["d"]), envrate(inp.fadsr["r"]),
        vm.qint_phase(inp.fadsr["s"]), int(inp.fadsr["r_s"]),
        vm.limit_i(vm.qint(inp.shape), vm.qint(-1.0), vm.qint(1.0)),
        vm.limit_i(vm.qint(inp.pw1), vm.qint(0.001), vm.qint(0.999)),
        vm.limit_i(vm.qint(inp.pw2), vm.qint(0.001), vm.qint(0.999)),
        vm.limit_i(vm.qint(inp.submix), 0, vm.ONE),
        vm.qint(max(0.0, inp.sync)),
        probe.char_a1, probe.char_b0, probe.char_b1,
        vm.amp_to_linear(vm.qint(inp.o1_level)),
        vm.db_to_linear(vm.qint(inp.vca_db)),                    # vca_gain
        vm.amp_to_linear(vm.qint(inp.scene_volume)) >> 1,        # outl_word
        master_amp, total_blocks,
        vm.ntpi_tuningctr(0),                                    # t_const
        vm.qdiv(vm.ONE, vm.ntpi_tuningctr(0)),                   # t_inv
        vm.qint(0.05),                                           # lag rate
        inst_att_aeg, inst_att_feg,
        *vm.HALFBAND_B_Q, *vm.HALFBAND_A_Q,
        # ---- SXT-026a appendix (words 40..47) -----------------------------
        1 if sine else 0,                                        # 40 osc_kind
        probe.fu_poles,                                          # 41 fu_poles
        probe.fm_depth,                                          # 42 fm_depth
        getattr(inp, 'fm_mode', 0),                              # 43 fm_mode
        inp.mix1,                                                # 44 mix1
        inp.osc_pitch_offsets[0],                                # 45 pitch_off1
        inp.osc_pitch_offsets[1],                                # 46 pitch_off2
        inp.osc_pitch_offsets[2],                                # 47 pitch_off3
    ]
    if sine:
        for core in probe.sine:               # 48..77 hp, lp coeffs (x3 oscs)
            init_words += [core.hp.b0, core.hp.b1, core.hp.b2,
                           core.hp.a1, core.hp.a2]
            init_words += [core.lp.b0, core.lp.b1, core.lp.b2,
                           core.lp.a1, core.lp.a2]
    else:
        init_words += [0] * 30
    # ---- SXT-034 unison appendix (words 78..127) --------------------------
    init_words += uni_words

    voices = []
    draw_sets = []          # distinct per-creation init oscstate sets
    events = list(seq["events"])
    ei = 0
    bs = BLOCK_SIZE
    halfband = vm.HalfbandD2()
    out_mono = []
    blocks_json = []
    ctrl = []

    def draw_set_index_of(v):
        key = tuple(v.init_oscstate_set)
        if key not in draw_set_index_of.table:
            draw_set_index_of.table[key] = len(draw_sets)
            draw_sets.append(list(v.init_oscstate_set))
        return draw_set_index_of.table[key]

    draw_set_index_of.table = {}

    for b in range(total_blocks):
        blk = {"b": b, "create": [], "release": [], "voices": []}
        while ei < len(events) and -(-events[ei]["t"] // bs) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS) if all(v.slot != i for v in voices))
                v = vm.VoiceV2(inp, e["note"], e.get("velocity", 0))
                v.slot = slot
                v.draw_set_index = draw_set_index_of(v)
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
        scene_l, scene_r = [0] * vm.BLOCK_SIZE_OS, [0] * vm.BLOCK_SIZE_OS
        alive = []
        for v in voices:
            keep = v.process_block(b, scene_l, scene_r, None)
            if keep:
                alive.append(v)
        voices = alive
        # modsource step at the END of the control pass (declared): matches
        # the engine's FAST_LINE smoothing order for this fixture set
        inp.modwheel.process_block()

        # control words: header + one CTRL_WORDS_PER_SLOT-word record per slot
        ctrl.extend([b, len(blk["create"]), inp.modwheel.value, master_amp])
        for slot in range(N_SLOTS):
            v = next((x for x in voices if x.slot == slot), None)
            if v is None:
                ctrl.extend([0] * CTRL_WORDS_PER_SLOT)
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
                v.draw_set_index,          # word 31: init-draw set index
            ])
            # SXT-026a appendix (words 32..36)
            if sine:
                ctrl.extend([v.fvel, v.kt_word,
                             v.sine_omega[0], v.sine_omega[1], v.sine_omega[2],
                             0, 0, 0])            # 37..39 reserved
            else:
                ctrl.extend([0, 0, 0, 0, 0, 0, 0, 0])
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
                    "f4_r0": getattr(v, "f4_r0", 0),
                    "f4_r1": getattr(v, "f4_r1", 0),
                    "C_end": list(v.cmu.C),
                    "fbp_gain": v.fbp_gain, "fbp_outl": v.fbp_outl,
                    # per-unison-voice impulse state (voice 0 mirrors the
                    # legacy scalar fields above)
                    "uni": [{"oscstate": x["oscstate"], "state": x["state"],
                             "last_level": x["last_level"], "pwidth": x["pwidth"],
                             "pwidth2": x["pwidth2"], "dc_uni": x["dc_uni"]}
                            for x in v.u],
                }
            blk["voices"].append(rec)

        scene_l = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene_l]
        scene_r = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene_r]
        bl = halfband.process(scene_l)
        br = bl   # mono bus: the R lane is identical (scene_r == scene_l)
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

    # SXT-034 draw table (cfg words 128+, after the SXT-026a and unison
    # appendices): n_sets, then each 16-word set. Only distinct sets are
    # stored; ctrl word 31 indexes them at creation.
    padded_sets = [s + [0] * (16 - len(s)) for s in draw_sets]
    init_words += [len(padded_sets)] + [w for s in padded_sets for w in s]

    vm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono, vm.SR)

    with open(os.path.join(args.out_dir, "model_trace.json"), "w", encoding="utf-8") as f:
        json.dump({
            "format": "sxt-034-voice-trace/2 (extends sxt-022-voice-trace/2 "
                      "with per-unison-voice state)",
            "sequence": seq["id"],
            "preset": preset_rel,
            "voice_class": getattr(inp, "voice_class", "classic-lp12-v1"),
            "engine_pin": "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71",
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q10.21", "env_phase": "Q2.29",
                          "pitchmult_inv": "Q13.18", "sine_phase": "Q3.28"},
            "slots": N_SLOTS,
            "unison": {"voices": uni_n,
                       "out_attenuation": probe.out_attenuation,
                       "per_voice_detune": [u["detune"] for u in probe.u],
                       "retrigger": bool(inp.retrigger)},
            "init_words_order": [
                "aeg_a", "aeg_d", "aeg_r", "aeg_s", "aeg_a_s", "aeg_r_s",
                "feg_a", "feg_d", "feg_r", "feg_s", "feg_a_s", "feg_r_s",
                "l_shape", "l_pw", "l_pw2", "l_sub", "l_sync",
                "char_a1", "char_b0", "char_b1",
                "o1_level", "integrator_hpf", "(unused)",
                "master_amp", "total_blocks", "last_event_t",
                "envmod_q",
                "inst_att_aeg", "inst_att_feg", "a_min_const", "eps01_const",
                "halfband B0..B5", "halfband A0..A5",
                "sxt026a: osc_kind", "fu_poles", "fm_depth", "fm_mode", "mix1",
                "pitch_off1", "pitch_off2", "pitch_off3",
                "hp1 b0,b1,b2,a1,a2", "lp1 b0,b1,b2,a1,a2",
                "hp2 b0,b1,b2,a1,a2", "lp2 b0,b1,b2,a1,a2",
                "hp3 b0,b1,b2,a1,a2", "lp3 b0,b1,b2,a1,a2",
                "uni_voices", "uni_out_attenuation",
                "uni_t[0..15]", "uni_t_inv[0..16)", "uni_init_oscstate[0..16)",
                "draw_set_count", "draw_table[set][0..15] (word 128+)",
            ],
            "init": init_words,
            "ctrl_words_per_slot": CTRL_WORDS_PER_SLOT,
            "ctrl_slot_word_order": [
                "flags(b0 active,b1 checkpoint,b2 created,b3 released)", "key", "gate",
                "aeg_state", "feg_state",
                "pmi_q20", "pitchmult_q27", "a_cov_q27", "hpf_target",
                "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7",
                "dC0", "dC1", "dC2", "dC3", "dC4", "dC5", "dC6", "dC7",
                "fbp_gain", "fbp_outl",
                "aeg_phase", "aeg_output", "feg_phase", "feg_output",
                "draw_set_index",                  # word 31 (was reserved)
                "sxt026a: fvel", "kt_word", "sine_omega1_q28",
                "sine_omega2_q28", "sine_omega3_q28",
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
    try:
        sys.exit(main())
    except vm.Refuse as e:
        print(f"REFUSED (outside declared SXT-026a class): {e}", file=sys.stderr)
        sys.exit(2)
