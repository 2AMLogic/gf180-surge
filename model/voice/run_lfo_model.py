#!/usr/bin/env python3
"""SXT-032 model runner: render a fixture sequence through the frozen voice
model (SXT-022) extended with the frozen LFO modulator slice (SXT-032).

Outputs (under --out-dir):
  model.wav             int16 mono render (fixtures WAV convention)
  model_trace.json      SXT-022 voice trace schema + per-voice LFO records
  rtl/*.hex             SXT-022 voice RTL stimulus (byte-format identical to
                        model/voice/run_model.py; the frozen tb_voice.sv runs
                        UNCHANGED against it — the LFO's audio effect rides
                        the streamed C/dC/gain control words)
  rtl/lfo_init.hex      per-instance LFO control-plane words (6 x 14)
  rtl/lfo_ctrl.hex      per-block LFO event/control words
  rtl/lfo_wssine.hex    wst_sine table ROM (1024 x 32-bit)

Declared control-plane boundary: block-rate LFO parameter quantization
(rate-table words, sustain, magnitude, deform, instant-envelope flags) stays
in the model and is streamed to the RTL; the RTL reproduces the LFO phase
accumulator, EG state machine, waveform evaluation and output scaling, and
must equal the model trace EXACTLY at every declared checkpoint (integer
equality; enforced by tools/compare_lfo_rtl_model.py).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402
import lfo_model as lm  # noqa: E402

PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
N_SLOTS = 8
CHECKPOINT_EVERY = 64
N_LFO = 6
LFO_CKPT_INSTANCES = (0,)     # routed instances are checkpointed every block


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


class LfoVoice(vm.Voice):
    """SXT-022 voice + six per-instance scene voice LFOs (never merged).

    Control-pass order mirrors SurgeVoice::calc_ctrldata: LFO1 always
    processes, routed LFOs 2..6 process (prepareModsourceDoProcess semantics:
    routed == has at least one routing), then AEG, then FEG; voice-level
    routes apply afterwards (applyModulationToLocalcopy; the constructor's
    first pass skips LFO-sourced routes). The control pass body below mirrors
    model/voice/voice_model.py Voice._calc_ctrldata word-for-word plus the
    declared LFO route additions (SXT-032 control pass).

    CONTROL_MODE "source_swap" (negative control only) rebinds every LFO
    route to the landed modwheel source: term = depth * modwheel.value.
    """

    CONTROL_MODE = "normal"

    def __init__(self, inp, key, velocity, lfo_params, lfo_routes):
        self.lfos = [lm.Lfo(p, i) for i, p in enumerate(lfo_params)]
        self.lfo_routes = lfo_routes       # [(instance_index, dest, depth_q21)]
        self.routed_instances = sorted({i for i, _d, _dp in lfo_routes})
        self.first_call = True
        self.last_route_sums = [0, 0]
        for lfo in self.lfos:
            lfo.attack()                   # SurgeVoice ctor: lfo[i].attack()
        super().__init__(inp, key, velocity)

    def release_all_lfos(self):
        for lfo in self.lfos:
            lfo.release()

    def _lfo_process(self):
        # LFO1 always processes; others only when routed
        for lfo in self.lfos:
            if lfo.index == 0 or lfo.index in self.routed_instances:
                lfo.process_block()

    def _calc_ctrldata(self):
        self._lfo_process()
        first = self.first_call
        self.first_call = False
        routes = [] if first else self.lfo_routes
        self.aeg.process_block()
        self.feg.process_block()
        cutoff = vm.qint(self.inp.cutoff) + vm.qmul(
            vm.qint(self.inp.mod_cutoff_depth), self.inp.modwheel.value)
        reso = vm.qint(self.inp.reso) + vm.qmul(
            vm.qint(self.inp.mod_reso_depth), self.inp.modwheel.value)
        cut_sum = 0
        reso_sum = 0
        for idx, dest, depth in routes:
            if self.CONTROL_MODE == "source_swap":
                source_value = self.inp.modwheel.value
            else:
                source_value = self.lfos[idx].output
            term = vm.qmul(depth, source_value)
            if dest == "cutoff":
                cutoff = vm.sat(cutoff + term)
                cut_sum += term
            elif dest == "reso":
                reso = vm.sat(reso + term)
                reso_sum += term
            else:
                raise RuntimeError(f"destination {dest} outside the frozen "
                                   "destination classes")
        self.cutoff_a = cutoff + vm.qmul(vm.qint(self.inp.envmod),
                                         self.feg.output)
        self.reso_a = reso
        self.last_route_sums = [cut_sum, reso_sum]
        if self.aeg.is_idle():
            self.keep_playing = False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", default=os.path.join(REPO, "model", "voice",
                                                     "attacky_inputs.json"))
    ap.add_argument("--lfo-inputs", default=os.path.join(REPO, "model", "voice",
                                                         "attacky_lfo_inputs.json"))
    ap.add_argument("--graphs", default=os.path.join(REPO, "corpus",
                                                     "normalized", "graphs.jsonl"))
    ap.add_argument("--sequence", required=True, help="sequence id or JSON path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--zero-routes", action="store_true",
                    help="negative control: force all LFO route depths to 0")
    ap.add_argument("--zero-dest", choices=("cutoff", "reso"),
                    help="negative control: zero only one destination class")
    ap.add_argument("--source-swap", action="store_true",
                    help="negative control: bind routes to the landed "
                         "modwheel source instead of the LFO")
    ap.add_argument("--free-running", action="store_true",
                    help="negative control: skip the trigger-mode phase "
                         "restart in LFO attack (free-running confusion)")
    args = ap.parse_args()

    if args.free_running:
        lm.MUTANT_FREE_RUNNING = True
    if args.source_swap:
        LfoVoice.CONTROL_MODE = "source_swap"

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences", seq_path + ".json")
    seq = vm.load_sequence(seq_path)

    with open(args.lfo_inputs, encoding="utf-8") as f:
        lfo_in = json.load(f)
    lfo_params = [lm.LfoParams(d) for d in lfo_in["lfo_defs"]]
    routes = []
    for r in lfo_in["fixture_routes"]:
        dest = "cutoff" if r["dest"].endswith("cutoff") else "reso"
        zero = args.zero_routes or (args.zero_dest == dest)
        routes.append((0, dest, 0 if zero else vm.qint(r["depth_raw"])))

    inp = vm.Inputs(args.inputs, args.graphs, PRESET_REL)
    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_samples = last_t + int(seq.get("tail_s", 2.5) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)

    master_amp = vm.db_to_linear(vm.qint(inp.master_db))

    # ---------------------------------------------------------- voice init
    probe = LfoVoice(inp, 60, 100, lfo_params, routes)

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
    ]

    # LFO init words: 6 instances x 14 words (LFO_INIT_ORDER, see tb_lfo.sv)
    eg_min_word = lm.qint_21(lm.ENVTIME_MIN)
    lfo_init = []
    for p in lfo_params:
        inst_flags = 0
        if p.unipolar:
            inst_flags |= 1
        if p.trigmode == lm.LM_KEYTRIGGER:
            inst_flags |= 2
        if p.env["delay"] == eg_min_word:
            inst_flags |= 4
        if p.env["attack"] == eg_min_word:
            inst_flags |= 8
        if p.env["hold"] == eg_min_word:
            inst_flags |= 16
        if p.release_active():
            inst_flags |= 32
        lfo_init.extend([
            p.shape,
            p.rate_word,
            p.start_phase_q29,
            p.magnitude_q27,
            p.deform_q27,
            inst_flags,
            p.eg_rate["delay"], p.eg_rate["attack"], p.eg_rate["hold"],
            p.eg_rate["decay"], p.eg_rate["release"],
            p.env["sustain"],
            eg_min_word,
            int(p.release_active()),
        ])

    # ------------------------------------------------------------- render
    voices = []
    events = list(seq["events"])
    ei = 0
    bs = BLOCK_SIZE
    halfband = vm.HalfbandD2()
    out_mono = []
    blocks_json = []
    ctrl = []
    lfo_ctrl = []

    for b in range(total_blocks):
        blk = {"b": b, "create": [], "release": [], "voices": []}
        while ei < len(events) and -(-events[ei]["t"] // bs) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS)
                            if all(v.slot != i for v in voices))
                v = LfoVoice(inp, e["note"], e.get("velocity", 0),
                             lfo_params, routes)
                v.slot = slot
                voices.append(v)
                blk["create"].append(slot)
            elif e["type"] == "note_off":
                for v in reversed(voices):
                    if v.key == e["note"] and v.gate:
                        v.aeg.release()
                        v.feg.release()
                        v.release_all_lfos()
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
        inp.modwheel.process_block()

        # voice ctrl words (frozen tb_voice format, LFO-influenced C/dC)
        ctrl.extend([b, len(blk["create"]), inp.modwheel.value, master_amp])
        lfo_ctrl.extend([b])
        for slot in range(N_SLOTS):
            v = next((x for x in voices if x.slot == slot), None)
            if v is None:
                ctrl.extend([0] * 32)
                lfo_ctrl.extend([0] * N_LFO)
                continue
            full = (b % CHECKPOINT_EVERY == 0) or (not v.gate) or (b < 2)
            created = slot in blk["create"]
            released = slot in blk["release"]
            flags = 1 | (2 if full else 0) | (4 if created else 0) \
                | (8 if released else 0)
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
            # per-instance LFO event words: b0 attack, b1 release, b2 process
            for lfo in v.lfos:
                enable = (lfo.index == 0) or (lfo.index in v.routed_instances)
                lfo_ctrl.extend([(1 if created else 0)
                                 | (2 if released else 0)
                                 | (4 if enable else 0)])
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
            # LFO trace records: routed instances every block, all six on the
            # creation block (per-instance state separation evidence)
            lfo_recs = []
            for lfo in v.lfos:
                ckpt = (lfo.index in v.routed_instances) or \
                       (lfo.index in LFO_CKPT_INSTANCES) or created
                if not ckpt:
                    continue
                lfo_recs.append({
                    "index": lfo.index,
                    "phase": lfo.phase,
                    "env_state": lfo.env_state,
                    "env_phase": lfo.env_phase,
                    "env_val": lfo.env_val,
                    "output": lfo.output,
                })
            if full or lfo_recs:
                rec["lfo"] = lfo_recs
                rec["lfo_route_sums"] = v.last_route_sums
            blk["voices"].append(rec)
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

    vm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono, vm.SR)

    with open(os.path.join(args.out_dir, "model_trace.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "format": "sxt-032-lfo-voice-trace/1",
            "sequence": seq["id"],
            "preset": PRESET_REL,
            "engine_pin":
                "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71",
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q4.27", "env_phase": "Q2.29",
                          "pitchmult_inv": "Q13.18", "lfo_phase": "Q2.29",
                          "lfo_wave": "Q4.27", "lfo_out": "Q10.21"},
            "slots": N_SLOTS,
            "lfo_instances": N_LFO,
            "lfo_route_sums_word_order": ["cutoff_sum", "reso_sum"],
            "init": init_words,
            "lfo_init_word_order": [
                "shape", "rate_word(Q2.29)", "start_phase(Q2.29)",
                "magnitude(Q4.27)", "deform(Q4.27)",
                "flags(b0 uni,b1 keytrig,b2 dly==min,b3 att==min,b4 hold==min,"
                "b5 release_active)",
                "eg_rate_delay", "eg_rate_attack", "eg_rate_hold",
                "eg_rate_decay", "eg_rate_release", "sustain(Q2.29)",
                "eg_min_word", "release_active",
            ],
            "lfo_init": lfo_init,
            "blocks": blocks_json,
            "samples16": out_mono,
        }, f)
        f.write("\n")

    write_hex(os.path.join(rtl_dir, "ctrl.hex"), ctrl)
    write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
    write_hex(os.path.join(rtl_dir, "sinc_main.hex"), vm.SINC_MAIN)
    write_hex(os.path.join(rtl_dir, "sinc_deriv.hex"), vm.SINC_DERIV)
    write_hex(os.path.join(rtl_dir, "lfo_init.hex"), lfo_init)
    write_hex(os.path.join(rtl_dir, "lfo_ctrl.hex"), lfo_ctrl)
    write_hex(os.path.join(rtl_dir, "lfo_wssine.hex"), lm.WS_SINE)
    # route table for tb_lfo.sv: [n_routes, (instance, dest 0=cutoff/1=reso,
    # depth Q10.21) ...] — fixture-constant, identical for every voice
    route_hex = [len(routes)]
    for idx, dest, depth in routes:
        route_hex.extend([idx, 0 if dest == "cutoff" else 1, depth])
    write_hex(os.path.join(rtl_dir, "lfo_routes.hex"), route_hex)

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks,
        "samples": len(out_mono),
        "trace": os.path.join(args.out_dir, "model_trace.json"),
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
