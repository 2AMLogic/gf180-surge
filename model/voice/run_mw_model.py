#!/usr/bin/env python3
"""SXT-035 model runner: render a fixture sequence through the frozen voice
model (SXT-022/SXT-026a) with the generalized scene-modwheel route table
(this leaf). The landed FAST_LINE smoother (`voice_model.Modwheel`) is reused
unchanged; the route vocabulary is Filter 1 Cutoff (308), Filter 1 Resonance
(309), VCA Gain (298), applied in `md` order per control pass.

Outputs (under --out-dir):
  model.wav             int16 mono render (fixtures WAV convention)
  model_trace.json      SXT-022 voice trace schema + per-block modwheel
                        records (pre-step value, post-step value, per-voice
                        route sums)
  rtl/init.hex          voice control-plane constants (run_model.py layout)
  rtl/ctrl.hex          per-block voice control words (run_model.py layout;
                        the frozen tb_voice.sv runs UNCHANGED against it)
  rtl/sinc_main.hex / rtl/sinc_deriv.hex   sinctable ROM
  rtl/mw_init.hex       [total_blocks, inv_q21]
  rtl/mw_ctrl.hex       per block: [b, set_flag, cc_value] + 8 slot-run words
  rtl/mw_routes.hex     [n_routes, (dest_code, depth_q21)]* (fixture-constant)

Negative-control flags (each must demonstrably fail its check; see
tools/mw_negative_controls.py):
  --zero-dest {cutoff,reso,vca}   force one destination class's depths to 0
  --no-smoothing                  bypass FAST_LINE (value jumps to target)
  --source-swap-lfo               bind the routes to the landed SXT-032 LFO1
                                  source instead of the modwheel
  --out-of-class-route            inject a route to 'A Highpass' (303);
                                  the runner must REFUSE (exit 2)
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
MW_INPUTS = os.path.join(REPO, "model", "voice", "attacky_mw_inputs.json")
FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
N_SLOTS = 8
CHECKPOINT_EVERY = 64
CTRL_WORDS_PER_SLOT = 40     # v2 stimulus: 32 x v1 + fvel/kt/omega1..3

DEST_CODE = {vm.DEST_FU1_CUTOFF: 0, vm.DEST_FU1_RESO: 1, vm.DEST_VCA_GAIN: 2}
DEST_NAME = {vm.DEST_FU1_CUTOFF: "A Filter 1 Cutoff",
             vm.DEST_FU1_RESO: "A Filter 1 Resonance",
             vm.DEST_VCA_GAIN: "A VCA Gain"}


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


class NoSmoothingModwheel(vm.Modwheel):
    """Negative-control mutant: FAST_LINE bypassed (jump to target)."""

    def set_target(self, cc):
        self.target = vm.qint(cc / 127.0)
        self.value = self.target
        self.startingpoint = self.value

    def process_block(self):
        pass


class MwVoice(vm.VoiceV2):
    """SXT-035 voice: generalized scene-modwheel route table.

    Mirrors `VoiceV2._calc_ctrldata` word-for-word, replacing the scalar
    modwheel reads with the declared route table (cutoff/reso/vca, applied
    in md order, both osc kinds). The smoothing algorithm is the landed
    `vm.Modwheel` — not reimplemented here. CONTROL_MODE "source_swap_lfo"
    (negative control only) binds the routes to the landed SXT-032 LFO1
    output instead of the modwheel value.
    """

    CONTROL_MODE = "normal"
    SWAP_LFO_PARAMS = None        # lfo_defs[0] when CONTROL_MODE = source_swap

    def __init__(self, inp, key, velocity):
        self.swap_lfo = None
        if type(self).CONTROL_MODE == "source_swap_lfo":
            # per-voice LFO instance (engine: every voice owns its modsources)
            self.swap_lfo = lm.Lfo(lm.LfoParams(type(self).SWAP_LFO_PARAMS), 0)
            self.swap_lfo.attack()     # SurgeVoice ctor: lfo[i].attack()
        self.last_mw_sums = [0, 0, 0]
        super().__init__(inp, key, velocity)

    def release_lfo(self):
        if self.swap_lfo is not None:
            self.swap_lfo.release()

    def _source_value(self):
        if type(self).CONTROL_MODE == "source_swap_lfo":
            return self.swap_lfo.output
        return self.inp.modwheel.value

    def _calc_ctrldata(self):
        inp = self.inp
        if type(self).CONTROL_MODE == "source_swap_lfo":
            self.swap_lfo.process_block()   # LFO1 always processes
        if self.kind == "classic":
            self.aeg.process_block()
            self.feg.process_block()
            mw = self._source_value()
            cut = vm.qint(inp.cutoff)
            reso = vm.qint(inp.reso)
            vca = vm.qint(inp.vca_db)
            sums = [0, 0, 0]
            for dst, depth in inp.scene_routes_mw:
                d = vm.qint(depth)
                term = vm.qmul(d, mw)
                if dst == vm.DEST_FU1_CUTOFF:
                    cut = vm.sat(cut + term)
                    sums[0] += term
                elif dst == vm.DEST_FU1_RESO:
                    reso = vm.sat(reso + term)
                    sums[1] += term
                elif dst == vm.DEST_VCA_GAIN:
                    vca = vm.sat(vca + term)
                    sums[2] += term
                else:
                    raise vm.Refuse(
                        f"scene route modwheel->{dst} "
                        f"({DEST_NAME.get(dst, 'unknown')}) outside the "
                        "declared SXT-035 destination class {308, 309, 298}")
            self.mod_vca_db = vca
            self.cutoff_a = cut + vm.qmul(vm.qint(inp.envmod),
                                          self.feg.output)
            self.reso_a = reso
            self.last_mw_sums = sums
            if self.aeg.is_idle():
                self.keep_playing = False
            return
        # sine kind: voice routes, then the scene-modwheel route table
        self.aeg.process_block()
        self.feg.process_block()
        self._apply_voice_routes()
        mw = self._source_value()
        cut = self.mod_cutoff
        reso = self.mod_reso
        vca = self.mod_vca_db
        sums = [0, 0, 0]
        for dst, depth in inp.scene_routes_mw:
            d = vm.qint(depth)
            term = vm.qmul(d, mw)
            if dst == vm.DEST_FU1_CUTOFF:
                cut = vm.sat(cut + term)
                sums[0] += term
            elif dst == vm.DEST_FU1_RESO:
                reso = vm.sat(reso + term)
                sums[1] += term
            elif dst == vm.DEST_VCA_GAIN:
                vca = vm.sat(vca + term)
                sums[2] += term
            else:
                raise vm.Refuse(
                    f"scene route modwheel->{dst} outside the declared "
                    "SXT-035 destination class {308, 309, 298}")
        self.mod_vca_db = vca
        kt_semitones = vm.qint(float(self.pitch_voice - inp.keytrack_root))
        self.cutoff_a = cut + vm.qmul(vm.qint(inp.fu_kta), kt_semitones) \
            + vm.qmul(self.mod_envmod, self.feg.output)
        self.reso_a = reso
        self.ctrl_pmi = 0
        self.ctrl_pitchmult = 0
        self.ctrl_a_cov = 0
        self.ctrl_hpf_target = 0
        self.last_mw_sums = sums
        if self.aeg.is_idle():
            self.keep_playing = False


def build_route_table(inp, mw_in, graphs_path, zero_dest):
    """Preset md routes (ordered) + runtime fixture routes; fail-closed."""
    table = []
    with open(graphs_path, encoding="utf-8") as f:
        found = False
        for line in f:
            row = json.loads(line)
            if row.get("p") == inp.preset_path:
                found = True
                for r in row["g"]["md"]["s"][0]["s"]:
                    if r[0] != vm.MODWHEEL_SRC:
                        continue
                    if r[3] not in DEST_NAME:
                        raise vm.Refuse(
                            f"preset scene route modwheel->{r[3]} "
                            f"({r[4]!r}) outside the declared SXT-035 "
                            "destination class {308, 309, 298}")
                    table.append((r[3], r[5]))
                break
    if not found:
        raise vm.Refuse("preset not found in graphs.jsonl")
    # cross-check the ordered preset rows against the v1 inputs scalars
    scalars = {vm.DEST_FU1_CUTOFF: inp.mod_cutoff_depth,
               vm.DEST_FU1_RESO: inp.mod_reso_depth}
    for dst, depth in table:
        if dst in scalars and abs(depth - scalars[dst]) > 1e-9:
            raise vm.Refuse(f"graphs depth {depth} != inputs scalar "
                            f"{scalars[dst]} for dest {dst}")
    # runtime fixture routes (engine readbacks; sidecar committed)
    for r in mw_in["fixture_routes"]:
        if r["dest_id"] not in DEST_NAME:
            raise vm.Refuse(f"fixture route dest {r['dest_id']} "
                            f"({r.get('dest_name')}) outside declared class")
        if r["modsource_id"] != vm.MODWHEEL_SRC:
            raise vm.Refuse(f"fixture route source {r['modsource_id']}")
        table.append((r["dest_id"], r["depth_raw"]))
    if zero_dest is not None:
        code = {"cutoff": vm.DEST_FU1_CUTOFF, "reso": vm.DEST_FU1_RESO,
                "vca": vm.DEST_VCA_GAIN}[zero_dest]
        table = [(dst, 0.0 if dst == code else depth) for dst, depth in table]
    if not table:
        raise vm.Refuse("empty modwheel route table: nothing to verify")
    return table


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", default=os.path.join(REPO, "model", "voice",
                                                     "attacky_inputs.json"))
    ap.add_argument("--mw-inputs", default=MW_INPUTS)
    ap.add_argument("--graphs", default=os.path.join(REPO, "corpus",
                                                     "normalized",
                                                     "graphs.jsonl"))
    ap.add_argument("--lfo-inputs", default=os.path.join(REPO, "model",
                                                         "voice",
                                                         "attacky_lfo_inputs.json"))
    ap.add_argument("--sequence", required=True, help="sequence id or JSON path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--zero-dest", choices=("cutoff", "reso", "vca"))
    ap.add_argument("--no-smoothing", action="store_true")
    ap.add_argument("--source-swap-lfo", action="store_true")
    ap.add_argument("--out-of-class-route", action="store_true")
    ap.add_argument("--ckpt-every", type=int, default=CHECKPOINT_EVERY,
                    help="checkpoint cadence (diagnostic aid)")
    args = ap.parse_args()

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences", seq_path + ".json")
    seq = vm.load_sequence(seq_path)

    with open(args.mw_inputs, encoding="utf-8") as f:
        mw_in = json.load(f)

    # the declared fixture carrier is the SXT-022 v1 inputs sidecar
    inp = vm.Inputs(args.inputs, args.graphs, PRESET_REL)
    inp.preset_path = PRESET_REL
    # v2-runner adapter for the frozen v1 class (all inert, v1-exact)
    inp.osc_kind = "classic"
    inp.fu_poles = 12
    inp.mix1 = vm.ONE
    inp.voice_routes = []
    inp.scene_routes_fm = False
    inp.fm_depth = 0
    inp.sine_lowcut = inp.sine_highcut = 0.0
    inp.osc_pitch_offsets = [12 * inp.octave, 0, 0]
    inp.scene_octave = 0
    inp.keytrack_root = 60
    if args.no_smoothing:
        inp.modwheel = NoSmoothingModwheel()

    table = build_route_table(inp, mw_in, args.graphs, args.zero_dest)
    inp.scene_routes_mw = table      # consumed by MwVoice._calc_ctrldata
    if args.out_of_class_route:
        table.append((303, 21.86507))          # 'A Highpass': MUST be refused

    if args.source_swap_lfo:
        MwVoice.CONTROL_MODE = "source_swap_lfo"
        with open(args.lfo_inputs, encoding="utf-8") as f:
            lfo_in = json.load(f)
        MwVoice.SWAP_LFO_PARAMS = lfo_in["lfo_defs"][0]

    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_samples = last_t + int(seq.get("tail_s", 2.5) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)

    ckpt_every = args.ckpt_every

    master_amp = vm.db_to_linear(vm.qint(inp.master_db))
    a_min_const = vm.qint(-8.0)
    eps01 = vm.qint(0.01)
    inst_att_aeg = 1 if (vm.qint(inp.adsr["a"]) - a_min_const) < eps01 else 0
    inst_att_feg = 1 if (vm.qint(inp.fadsr["a"]) - a_min_const) < eps01 else 0

    def envrate(p):
        return vm.envelope_rate_linear_nowrap(vm.qint(p))

    probe = MwVoice(inp, 60, 100)
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
        inst_att_aeg, inst_att_feg,
        *vm.HALFBAND_B_Q, *vm.HALFBAND_A_Q,
        # ---- SXT-026a appendix (classic fixture: identity words) ----------
        0, 12, 0, 0, inp.mix1,
        inp.osc_pitch_offsets[0], inp.osc_pitch_offsets[1],
        inp.osc_pitch_offsets[2],
    ] + [0] * 30

    # mw init + route words for tb_mw.sv
    mw_init = [total_blocks, vm.Modwheel().inv]
    mw_routes = [len(table)]
    for dst, depth in table:
        mw_routes.extend([DEST_CODE[dst], vm.qint(depth)])

    voices = []
    events = list(seq["events"])
    ei = 0
    bs = BLOCK_SIZE
    halfband = vm.HalfbandD2()
    out_mono = []
    blocks_json = []
    ctrl = []
    mw_ctrl = []

    for b in range(total_blocks):
        blk = {"b": b, "create": [], "release": [], "voices": []}
        set_flag = 0
        set_cc = 0
        while ei < len(events) and -(-events[ei]["t"] // bs) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS)
                            if all(v.slot != i for v in voices))
                v = MwVoice(inp, e["note"], e.get("velocity", 0))
                v.slot = slot
                voices.append(v)
                blk["create"].append(slot)
            elif e["type"] == "note_off":
                for v in reversed(voices):
                    if v.key == e["note"] and v.gate:
                        v.aeg.release()
                        v.feg.release()
                        v.release_lfo()
                        v.gate = False
                        blk["release"].append(v.slot)
                        break
            elif e["type"] == "cc":
                if e["channel"] == 0 and e["controller"] == 1:
                    inp.modwheel.set_target(e["value"])
                    set_flag = 1
                    set_cc = e["value"]
            ei += 1
        scene_l, scene_r = [0] * vm.BLOCK_SIZE_OS, [0] * vm.BLOCK_SIZE_OS
        ran_slots = []
        alive = []
        for v in voices:
            keep = v.process_block(b, scene_l, scene_r, None)
            ran_slots.append(v.slot)
            if keep:
                alive.append(v)
        voices = alive
        # modsource step at the END of the control pass (declared, SXT-022)
        mw_pre = inp.modwheel.value
        inp.modwheel.process_block()
        blk["mw_pre"] = mw_pre
        blk["mw_value"] = inp.modwheel.value

        # voice ctrl words (frozen tb_voice format, mw-influenced C/dC/gain)
        ctrl.extend([b, len(blk["create"]), inp.modwheel.value, master_amp])
        mw_ctrl.extend([b, set_flag, set_cc])
        for slot in range(N_SLOTS):
            v = next((x for x in voices if x.slot == slot), None)
            mw_ctrl.append(1 if (v is not None or slot in ran_slots) else 0)
            if v is None:
                ctrl.extend([0] * CTRL_WORDS_PER_SLOT)
                continue
            full = (b % ckpt_every == 0) or (not v.gate) or (b < 2)
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
                0, 0, 0, 0, 0, 0, 0, 0,       # SXT-026a appendix (classic)
            ])
            rec = {"slot": slot, "key": v.key, "gate": v.gate,
                   "mw_route_sums": list(v.last_mw_sums)}
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

    vm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono, vm.SR)

    with open(os.path.join(args.out_dir, "model_trace.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "format": "sxt-035-mw-voice-trace/1",
            "sequence": seq["id"],
            "preset": PRESET_REL,
            "engine_pin":
                "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71",
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q10.21", "env_phase": "Q2.29",
                          "pitchmult_inv": "Q13.18", "modwheel": "Q10.21"},
            "slots": N_SLOTS,
            "route_table": [{"dest": DEST_NAME[dst], "dest_id": dst,
                             "depth_raw": depth}
                            for dst, depth in table],
            "route_sums_word_order": ["cutoff_sum", "reso_sum", "vca_sum"],
            "control_mode": MwVoice.CONTROL_MODE,
            "init": init_words,
            "blocks": blocks_json,
            "samples16": out_mono,
        }, f)
        f.write("\n")

    write_hex(os.path.join(rtl_dir, "ctrl.hex"), ctrl)
    write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
    write_hex(os.path.join(rtl_dir, "sinc_main.hex"), vm.SINC_MAIN)
    write_hex(os.path.join(rtl_dir, "sinc_deriv.hex"), vm.SINC_DERIV)
    write_hex(os.path.join(rtl_dir, "mw_init.hex"), mw_init)
    write_hex(os.path.join(rtl_dir, "mw_ctrl.hex"), mw_ctrl)
    write_hex(os.path.join(rtl_dir, "mw_routes.hex"), mw_routes)

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks,
        "samples": len(out_mono),
        "routes": [{"dest": DEST_NAME[dst], "depth": d} for dst, d in table],
        "trace": os.path.join(args.out_dir, "model_trace.json"),
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except vm.Refuse as e:
        print(f"REFUSED (outside declared SXT-035 class): {e}", file=sys.stderr)
        sys.exit(2)
