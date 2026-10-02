#!/usr/bin/env python3
"""SXT-041 model runner: render a fixture sequence through the frozen voice
model (SXT-022) extended with the frozen SCENE-LFO slice (SXT-041).

Outputs (under --out-dir):
  model.wav             int16 mono render (fixtures WAV convention)
  model_trace.json      SXT-022 voice trace schema + the per-block scene-LFO
                        bank records (all six instances, every block)
  rtl/*.hex             SXT-022 voice RTL stimulus (byte-format identical to
                        model/voice/run_model.py; the frozen tb_voice.sv runs
                        UNCHANGED against it — the scene LFO's audio effect
                        rides the streamed C/dC/gain control words)
  rtl/slfo_init.hex     per-instance scene-LFO control-plane words (6 x 14)
  rtl/slfo_ctrl.hex     per-block scene-LFO event words (attack/release)
  rtl/slfo_routes.hex   n_routes, then (instance, dest, depth Q10.21)
  rtl/slfo_wssine.hex   wst_sine table ROM (1024 x 32-bit)

Scene scope (the subject of this leaf; see model/voice/slfo_model.py):
  * ONE bank of six instances for the whole scene, shared by every voice;
  * attack/release gated on the engine's own `getNonReleasedVoices(scene)
    == 0` predicate (gated-voice count), not on per-note events;
  * the scene route sums are applied to cutoff/resonance from the PREVIOUS
    block's instance outputs, and are block-constant across voices;
  * all six instances advance on EVERY block — including the reference
    renderer's settle blocks, which this runner replays before t=0, and
    including blocks with no voices at all.

Declared control-plane boundary: block-rate scene-LFO parameter quantization
(rate-table words, sustain, magnitude, deform, instant-envelope flags) stays
in the model and is streamed to the RTL; the RTL reproduces the phase
accumulator, EG state machine, waveform evaluation, output scaling, the
one-block route latch and the route sums, and must equal the model trace
EXACTLY at every declared checkpoint (integer equality; enforced by
tools/compare_slfo_rtl_model.py).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402
import lfo_model as lm  # noqa: E402
import slfo_model as sm  # noqa: E402

PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
N_SLOTS = 8
CHECKPOINT_EVERY = 64
CTRL_WORDS_PER_SLOT = 40     # v2 stimulus: 32 x v1 + draw_set_index/appendix
N_SLFO = sm.N_SCENE_LFOS
SEQ_DIRS = (os.path.join(REPO, "fixtures", "sequences"),
            os.path.join(REPO, "model", "voice", "sequences"))


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


def resolve_sequence(ref):
    if os.path.sep in ref or ref.endswith(".json"):
        return ref
    for d in SEQ_DIRS:
        cand = os.path.join(d, ref + ".json")
        if os.path.exists(cand):
            return cand
    raise SystemExit(f"sequence {ref!r} not found under {SEQ_DIRS}")


class SceneBus:
    """Block-constant scene-modulation sums shared by every voice.

    Holding them here (rather than inside each voice) is the structural
    encoding of "the scene LFO route is applied once per block to scenedata,
    before the voices run" — a per-voice copy would be the wrong semantic and
    is what the `--per-voice-bank` negative control builds.
    """

    def __init__(self):
        self.sums = [0, 0]          # [cutoff_sum, reso_sum] in Q10.21


class SlfoVoice(vm.Voice):
    """SXT-022 voice reading the scene bus (shared scene-LFO route sums).

    The control pass body mirrors `voice_model.Voice._calc_ctrldata`
    word-for-word plus the scene-route additions. Summation order follows the
    engine's `modulation_scene` list order: the preset's own modwheel routes
    were loaded first, the declared scene-LFO routes were appended after.

    Unlike the SXT-032 voice-LFO slice there is NO constructor-pass route
    skip: the scene route is already summed into `scenedata` before the voice
    is constructed (`applyModulationToLocalcopy`'s LFO skip applies to
    `modulation_voice` sources only). The constructor therefore sees the
    PREVIOUS block's sums, which is exactly what the engine's voice
    constructor reads at `playNote` time — the runner updates the bus after
    voice creation and before the block's voice pass.

    CONTROL_MODE "source_swap" (negative control only) rebinds the scene
    route to the landed modwheel source instead of the scene LFO.
    """

    CONTROL_MODE = "normal"

    def __init__(self, inp, key, velocity, bus):
        self.bus = bus
        super().__init__(inp, key, velocity)

    def _calc_ctrldata(self):
        self.aeg.process_block()
        self.feg.process_block()
        cutoff = vm.qint(self.inp.cutoff) + vm.qmul(
            vm.qint(self.inp.mod_cutoff_depth), self.inp.modwheel.value)
        reso = vm.qint(self.inp.reso) + vm.qmul(
            vm.qint(self.inp.mod_reso_depth), self.inp.modwheel.value)
        cut_sum, reso_sum = self.bus.sums
        cutoff = vm.sat(cutoff + cut_sum)
        reso = vm.sat(reso + reso_sum)
        self.cutoff_a = cutoff + vm.qmul(vm.qint(self.inp.envmod),
                                         self.feg.output)
        self.reso_a = reso
        self.last_scene_sums = [cut_sum, reso_sum]
        if self.aeg.is_idle():
            self.keep_playing = False


def build_slfo_init(params):
    """6 instances x 14 words (SLFO_INIT_ORDER, see rtl/voice/tb_slfo.sv)."""
    eg_min_word = lm.qint_21(lm.ENVTIME_MIN)
    words = []
    for p in params:
        flags = 0
        if p.unipolar:
            flags |= 1
        if p.trigmode == lm.LM_KEYTRIGGER:
            flags |= 2
        if p.env["delay"] == eg_min_word:
            flags |= 4
        if p.env["attack"] == eg_min_word:
            flags |= 8
        if p.env["hold"] == eg_min_word:
            flags |= 16
        if p.release_active():
            flags |= 32
        words.extend([
            p.shape,
            p.rate_word,
            p.start_phase_q29,
            p.magnitude_q27,
            p.deform_q27,
            flags,
            p.eg_rate["delay"], p.eg_rate["attack"], p.eg_rate["hold"],
            p.eg_rate["decay"], p.eg_rate["release"],
            p.env["sustain"],
            eg_min_word,
            int(p.release_active()),
        ])
    return words


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", default=os.path.join(REPO, "model", "voice",
                                                     "attacky_inputs.json"))
    ap.add_argument("--slfo-inputs",
                    default=os.path.join(REPO, "model", "voice",
                                         "attacky_slfo_inputs.json"))
    ap.add_argument("--graphs", default=os.path.join(REPO, "corpus",
                                                     "normalized", "graphs.jsonl"))
    ap.add_argument("--sequence", required=True, help="sequence id or JSON path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--zero-routes", action="store_true",
                    help="negative control: force all scene-LFO route depths "
                         "to 0")
    ap.add_argument("--zero-dest", choices=("cutoff", "reso"),
                    help="negative control: zero only one destination class")
    ap.add_argument("--source-swap", action="store_true",
                    help="negative control: bind the scene routes to the "
                         "landed modwheel source instead of the scene LFO")
    ap.add_argument("--per-note-retrigger", action="store_true",
                    help="negative control: attack/release the scene LFOs on "
                         "EVERY note-on/note-off (voice-LFO semantics)")
    ap.add_argument("--zero-delay-route", action="store_true",
                    help="negative control: apply the scene route from the "
                         "CURRENT block's output (drops the one-block delay)")
    ap.add_argument("--shared-instance", action="store_true",
                    help="negative control: collapse all six instances onto "
                         "one shared state set")
    ap.add_argument("--gated-process", action="store_true",
                    help="negative control: advance the scene LFOs only while "
                         "a gated voice exists (voice-LFO residency)")
    ap.add_argument("--no-settle", action="store_true",
                    help="negative control: skip the reference renderer's "
                         "settle blocks for the scene-LFO bank")
    args = ap.parse_args()

    sm.MUTANT_PER_NOTE_RETRIGGER = bool(args.per_note_retrigger)
    sm.MUTANT_ZERO_DELAY_ROUTE = bool(args.zero_delay_route)
    sm.MUTANT_SHARED_INSTANCE = bool(args.shared_instance)
    sm.MUTANT_GATED_PROCESS = bool(args.gated_process)
    if args.source_swap:
        SlfoVoice.CONTROL_MODE = "source_swap"

    seq_path = resolve_sequence(args.sequence)
    seq = vm.load_sequence(seq_path)

    with open(args.slfo_inputs, encoding="utf-8") as f:
        slfo_in = json.load(f)
    slfo_params = [sm.SlfoParams(d) for d in slfo_in["slfo_defs"]]
    if len(slfo_params) != N_SLFO:
        raise SystemExit(f"expected {N_SLFO} scene-LFO definitions, got "
                         f"{len(slfo_params)}")
    routes = []
    for r in slfo_in["fixture_routes"]:
        dest = sm.DEST_CUTOFF if r["dest_param"] == "cutoff" else sm.DEST_RESO
        zero = args.zero_routes or (args.zero_dest == dest)
        routes.append((int(r["slfo_instance"]), dest,
                       0 if zero else vm.qint(r["depth_raw"])))

    inp = vm.Inputs(args.inputs, args.graphs, PRESET_REL)
    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_samples = last_t + int(seq.get("tail_s", 2.5) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)
    settle_blocks = int(seq.get("settle_s", 0.25) * vm.SR) // BLOCK_SIZE

    master_amp = vm.db_to_linear(vm.qint(inp.master_db))

    bus = SceneBus()
    bank = sm.SceneLfoBank(slfo_params)

    # ---------------------------------------------------------- voice init
    probe = SlfoVoice(inp, 60, 100, bus)
    # the probe voice is discarded (character-filter/attenuation words only);
    # reset the declared draw cursor so the rendered voices consume the
    # committed init_phase_draws list from its start (matches run_model.py)
    inp.reset_draws()

    uni_n = max(1, int(inp.n_unison))
    uni_words = [uni_n, probe.out_attenuation]
    for u in probe.u:
        uni_words += [u["t"], u["t_inv"], u["oscstate"]]
    uni_words += [0] * (3 * 16 - 3 * len(probe.u))

    def envrate(p):
        return vm.envelope_rate_linear_nowrap(vm.qint(p))

    # INIT_ORDER (see tb_voice.sv cfg map) — identical to run_model.py
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
        vm.db_to_linear(vm.qint(inp.vca_db)),
        vm.amp_to_linear(vm.qint(inp.scene_volume)) >> 1,
        master_amp, total_blocks,
        vm.ntpi_tuningctr(0),
        vm.qdiv(vm.ONE, vm.ntpi_tuningctr(0)),
        vm.qint(0.05),
        1 if (vm.qint(inp.adsr["a"]) - vm.qint(-8.0)) < vm.qint(0.01) else 0,
        1 if (vm.qint(inp.fadsr["a"]) - vm.qint(-8.0)) < vm.qint(0.01) else 0,
        *vm.HALFBAND_B_Q, *vm.HALFBAND_A_Q,
        # ---- SXT-026a appendix (classic fixture: identity words) ----------
        0, 12, 0, 0, vm.ONE,
        12 * inp.octave, 0, 0,
    ] + [0] * 30
    # ---- SXT-034 unison appendix (words 78..127) --------------------------
    init_words += uni_words

    slfo_init = build_slfo_init(slfo_params)

    # ------------------------------------------- settle (pre-t=0) bank pass
    # The reference renderer discards `settle_blocks` engine blocks before
    # t=0; the scene LFOs advance through them (processControl processes all
    # six every block while the scene plays). Replay them here so the bank
    # state at block 0 matches the engine's.
    settle_records = []
    if not args.no_settle:
        for _ in range(settle_blocks):
            bank.block_pass(routes, gated_voices=0)
    settle_records = {"settle_blocks": 0 if args.no_settle else settle_blocks,
                      "bank_route_out_at_t0": list(bank.route_out),
                      "bank_attacks": bank.attacks,
                      "bank_releases": bank.releases}

    # ------------------------------------------------------------- render
    voices = []
    draw_sets = []
    events = list(seq["events"])
    ei = 0
    bs = BLOCK_SIZE
    halfband = vm.HalfbandD2()
    out_mono = []
    blocks_json = []
    ctrl = []
    slfo_ctrl = []
    bank_events = []

    def draw_set_index_of(v):
        key = tuple(v.init_oscstate_set)
        if key not in draw_set_index_of.table:
            draw_set_index_of.table[key] = len(draw_sets)
            draw_sets.append(list(v.init_oscstate_set))
        return draw_set_index_of.table[key]

    draw_set_index_of.table = {}

    def gated_count():
        return sum(1 for v in voices if v.gate)

    for b in range(total_blocks):
        lm.BLOCK_CLOCK = b
        blk = {"b": b, "create": [], "release": [], "voices": []}
        attacked = False
        released = False
        while ei < len(events) and -(-events[ei]["t"] // bs) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                # engine order: the SLFO attack gate is evaluated in
                # playVoice BEFORE the new voice exists
                if bank.note_on(gated_count()):
                    attacked = True
                slot = next(i for i in range(N_SLOTS)
                            if all(v.slot != i for v in voices))
                v = SlfoVoice(inp, e["note"], e.get("velocity", 0), bus)
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
                # engine order: releaseNote tests the gate count AFTER the
                # released voice's gate has been cleared
                if bank.note_off(gated_count()):
                    released = True
            elif e["type"] == "cc":
                if e["channel"] == 0 and e["controller"] == 1:
                    inp.modwheel.set_target(e["value"])
            ei += 1

        if attacked or released:
            bank_events.append({"b": b, "attack": attacked,
                                "release": released,
                                "gated_after": gated_count()})

        # processControl: scene route application (previous block's outputs)
        # then the unconditional six-instance advance
        bus.sums = bank.block_pass(routes, gated_voices=gated_count())
        if SlfoVoice.CONTROL_MODE == "source_swap":
            # CONTROL ONLY: the same depths driven by the landed modwheel
            swapped = [0, 0]
            for idx, dest, depth in routes:
                term = vm.qmul(depth, inp.modwheel.value)
                swapped[0 if dest == sm.DEST_CUTOFF else 1] += term
            bus.sums = [vm.sat(swapped[0]), vm.sat(swapped[1])]

        scene_l, scene_r = [0] * vm.BLOCK_SIZE_OS, [0] * vm.BLOCK_SIZE_OS
        alive = []
        for v in voices:
            keep = v.process_block(b, scene_l, scene_r, None)
            if keep:
                alive.append(v)
        voices = alive
        inp.modwheel.process_block()

        # ---- RTL stimulus ------------------------------------------------
        ctrl.extend([b, len(blk["create"]), inp.modwheel.value, master_amp])
        slfo_ctrl.extend([b, (1 if attacked else 0) | (2 if released else 0)])
        for slot in range(N_SLOTS):
            v = next((x for x in voices if x.slot == slot), None)
            if v is None:
                ctrl.extend([0] * CTRL_WORDS_PER_SLOT)
                continue
            full = (b % CHECKPOINT_EVERY == 0) or (not v.gate) or (b < 2)
            created = slot in blk["create"]
            rel = slot in blk["release"]
            flags = 1 | (2 if full else 0) | (4 if created else 0) \
                | (8 if rel else 0)
            ctrl.extend([
                flags,
                v.key, v.gate,
                v.aeg.state, v.feg.state,
                v.ctrl_pmi, v.ctrl_pitchmult, v.ctrl_a_cov, v.ctrl_hpf_target,
                *v.ctrl_C, *v.ctrl_dC,
                v.fbp_gain, v.fbp_outl,
                v.aeg.phase, v.aeg.output, v.feg.phase, v.feg.output,
                v.draw_set_index,
                0, 0, 0, 0, 0, 0, 0, 0,    # SXT-026a appendix (classic)
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
            rec["scene_sums"] = list(v.last_scene_sums)
            blk["voices"].append(rec)

        # ---- declared scene-LFO checkpoint (bank scope, every block) -----
        blk["slfo"] = bank.checkpoint()
        blk["slfo_route_sums"] = list(bus.sums)
        blk["slfo_route_out"] = list(bank.route_out)
        blk["gated_voices"] = gated_count()

        scene_l = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene_l]
        scene_r = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene_r]
        bl = halfband.process(scene_l)
        br = bl
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

    padded_sets = [s + [0] * (16 - len(s)) for s in draw_sets]
    init_words += [len(padded_sets)] + [w for s in padded_sets for w in s]

    vm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono, vm.SR)

    with open(os.path.join(args.out_dir, "model_trace.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "format": "sxt-041-slfo-voice-trace/1",
            "sequence": seq["id"],
            "preset": PRESET_REL,
            "engine_pin":
                "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71",
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q4.27", "env_phase": "Q2.29",
                          "pitchmult_inv": "Q13.18", "slfo_phase": "Q2.29",
                          "slfo_wave": "Q4.27", "slfo_out": "Q10.21"},
            "slots": N_SLOTS,
            "slfo_instances": N_SLFO,
            "slfo_route_sums_word_order": ["cutoff_sum", "reso_sum"],
            "scene_scope": {
                "instances_per_scene": N_SLFO,
                "shared_by_every_voice": True,
                "route_list": "modulation_scene",
                "route_latency_blocks": 1,
                "attack_gate": "getNonReleasedVoices(scene) == 0 (note-on, "
                               "before the new voice exists)",
                "release_gate": "getNonReleasedVoices(scene) == 0 (note-off, "
                                "after the voice gate is cleared)",
                "process_gate": "unconditional, every block the scene plays",
            },
            "settle": settle_records,
            "bank_events": bank_events,
            "init": init_words,
            "slfo_init_word_order": [
                "shape", "rate_word(Q2.29)", "start_phase(Q2.29)",
                "magnitude(Q4.27)", "deform(Q4.27)",
                "flags(b0 uni,b1 keytrig,b2 dly==min,b3 att==min,b4 hold==min,"
                "b5 release_active)",
                "eg_rate_delay", "eg_rate_attack", "eg_rate_hold",
                "eg_rate_decay", "eg_rate_release", "sustain(Q2.29)",
                "eg_min_word", "release_active",
            ],
            "slfo_init": slfo_init,
            "slfo_state_bits": bank.state_bits(),
            "blocks": blocks_json,
            "samples16": out_mono,
        }, f)
        f.write("\n")

    write_hex(os.path.join(rtl_dir, "ctrl.hex"), ctrl)
    write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
    write_hex(os.path.join(rtl_dir, "sinc_main.hex"), vm.SINC_MAIN)
    write_hex(os.path.join(rtl_dir, "sinc_deriv.hex"), vm.SINC_DERIV)
    write_hex(os.path.join(rtl_dir, "slfo_init.hex"), slfo_init)
    write_hex(os.path.join(rtl_dir, "slfo_ctrl.hex"), slfo_ctrl)
    write_hex(os.path.join(rtl_dir, "slfo_wssine.hex"), lm.WS_SINE)
    # route table for tb_slfo.sv: [n_routes, settle_blocks,
    #   (instance, dest 0=cutoff/1=reso, depth Q10.21) ...]
    route_hex = [len(routes), 0 if args.no_settle else settle_blocks]
    for idx, dest, depth in routes:
        route_hex.extend([idx, 0 if dest == sm.DEST_CUTOFF else 1, depth])
    write_hex(os.path.join(rtl_dir, "slfo_routes.hex"), route_hex)

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks,
        "settle_blocks": settle_records["settle_blocks"],
        "bank_attacks": bank.attacks, "bank_releases": bank.releases,
        "samples": len(out_mono),
        "trace": os.path.join(args.out_dir, "model_trace.json"),
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
