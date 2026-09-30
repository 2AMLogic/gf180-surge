#!/usr/bin/env python3
"""SXT-036 model runner: render a fixture sequence through the frozen voice
model (SXT-022/SXT-026a/SXT-034 merged layout) with the per-voice VELOCITY
and RELEASE-VELOCITY modulation route table (this leaf; pinned modsource ids
1 = ms_velocity, 30 = ms_releasevelocity).

Frozen semantics (cited from surge@58914e59, read not copied; see the SXT-036
section of model/voice/README.md):
  * velocity word  = qint(velocity/127)   latched at voice construction
    (SurgeVoice.cpp: state.fvel = velocity/127.f; velocitySource.init(0,
    fvel); SLOW_EXP smoothing with value == target is the identity every
    block -- calc_ctrldata process_block());
  * release-velocity word = 0 at construction (state.freleasevel = 0;
    releaseVelocitySource.set_output(0, 0)), set to qint(relvel/127) when
    the voice is released (SurgeVoice::release(): set_output(0,
    state.releasevelocity/127.0f); SurgeSynthesizer::releaseNote stamps
    state.releasevelocity before release);
  * both words are PER VOICE INSTANCE (one ControllerModulationSource /
    ModulationSource member per SurgeVoice); never shared across voices or
    scenes;
  * route application (SurgeVoice::applyModulationToLocalcopy, voice list,
    md order): localcopy[dst] += depth * source, AFTER the scene-level
    modulations were applied to scenedata (SurgeSynthesizer processControl
    copy_scenedata + scene modulation, then the voice memcpy) -- so the
    landed scene-modwheel terms enter first, then the voice terms.
  Frozen destination classes: Filter 1 Cutoff (308), Filter 1 Resonance
  (309), Filter 1 FEG mod amount (310), VCA Gain (298). Anything else is
  refused (exit 2).

Outputs (under --out-dir):
  model.wav             int16 mono render (fixtures WAV convention)
  model_trace.json      SXT-034 voice trace schema (tools/compare_rtl_model.py)
                        + per-voice `vel_words` [vel_q, relvel_q] and
                        `vel_route_sums` [cutoff, reso, fegmod, vca] per block
  rtl/init.hex, rtl/ctrl.hex, rtl/sinc_*.hex   frozen tb_voice.sv stimulus
                        (run_model.py merged layout; tb_voice.sv UNCHANGED)
  rtl/vel_init.hex      [total_blocks]
  rtl/vel_routes.hex    [n_routes, (src_code, dest_code, depth_q21)*]
  rtl/vel_ctrl.hex      per block: [b] + per slot [run, create, vel_midi,
                        release, relvel_midi]   (tb_vel.sv)

Negative-control flags (see tools/vel_negative_controls.py; each must
demonstrably fail its check):
  --zero-route SRC:DEST     force the depth of every SRC->DEST route to 0
                            (SRC in {vel, relvel}; DEST in {cutoff, reso,
                            fegmod, vca})
  --source-swap-mw          bind the velocity AND release-velocity routes to
                            the landed scene modwheel (SXT-022/SXT-035
                            FAST_LINE source) instead of this leaf's sources
  --shared-state            ONE scene-wide velocity / release-velocity
                            register (last note-on / last note-off wins)
                            instead of per-voice instances
  --stale-slot-relvel       voice construction does NOT clear the slot's
                            release-velocity register, so a REUSED slot
                            inherits the previous voice's release velocity
                            (violates the cited ctor fact
                            releaseVelocitySource.set_output(0, 0))
  --out-of-class-route      inject velocity -> 'A Highpass' (303); the runner
                            must REFUSE (exit 2)
  --cross-scene-route       inject the scene-B route the named carrier
                            'House Of Chords.fxp' actually carries
                            (velocity -> 'B Osc 1 Sync' 502); the runner must
                            REFUSE (exit 2) -- the frozen destination class is
                            scene A only and scene-B routes are never folded
                            into it
  --strip-vel-routes        drop every velocity/release-velocity route (the
                            invariance check: must reproduce the landed
                            SXT-022 model render bit-identically)
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402

PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
VEL_INPUTS = os.path.join(REPO, "model", "voice", "attacky_vel_inputs.json")
LOCAL_SEQ_DIR = os.path.join(REPO, "model", "voice", "sequences")
FQ = vm.FQ
BLOCK_SIZE = vm.BLOCK_SIZE
N_SLOTS = 8
CHECKPOINT_EVERY = 64
CTRL_WORDS_PER_SLOT = 40     # merged v2 stimulus (run_model.py layout)
VEL_WORDS_PER_SLOT = 5

VELOCITY_SRC = vm.VELOCITY_SRC           # 1  ms_velocity
RELEASEVELOCITY_SRC = 30                 # 30 ms_releasevelocity (pinned enum)
SRC_CODE = {VELOCITY_SRC: 0, RELEASEVELOCITY_SRC: 1}
SRC_NAME = {VELOCITY_SRC: "ms_velocity", RELEASEVELOCITY_SRC: "ms_releasevelocity"}
SRC_FLAG = {"vel": VELOCITY_SRC, "relvel": RELEASEVELOCITY_SRC}

DEST_CODE = {vm.DEST_FU1_CUTOFF: 0, vm.DEST_FU1_RESO: 1,
             vm.DEST_FU1_FEGMOD: 2, vm.DEST_VCA_GAIN: 3}
DEST_NAME = {vm.DEST_FU1_CUTOFF: "A Filter 1 Cutoff",
             vm.DEST_FU1_RESO: "A Filter 1 Resonance",
             vm.DEST_FU1_FEGMOD: "A Filter 1 FEG Mod Amount",
             vm.DEST_VCA_GAIN: "A VCA Gain"}
DEST_FLAG = {"cutoff": vm.DEST_FU1_CUTOFF, "reso": vm.DEST_FU1_RESO,
             "fegmod": vm.DEST_FU1_FEGMOD, "vca": vm.DEST_VCA_GAIN}
SCENE_MW_DESTS = (vm.DEST_FU1_CUTOFF, vm.DEST_FU1_RESO, vm.DEST_VCA_GAIN)


def vel_q(midi):
    """qint(midi/127) as an exact integer: floor(midi*2^21/127 + 1/2).

    127 is odd, so midi*2^21/127 never has fractional part exactly 1/2 and
    the integer form (midi*2^22 + 127) // 254 equals the round-half-up
    quantization of the double quotient for every midi in 0..127 (asserted
    at import). The RTL evaluates the same integer expression.
    """
    return (int(midi) * (1 << (FQ + 1)) + 127) // 254


for _m in range(128):
    assert vel_q(_m) == vm.qint(_m / 127.0), _m


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


class SharedVelRegister:
    """Negative-control state: ONE scene-wide register (per-instance rule
    violated on purpose)."""

    def __init__(self):
        self.vel = 0
        self.relvel = 0


class VelVoice(vm.VoiceV2):
    """SXT-036 voice: per-instance velocity / release-velocity sources and
    the voice route table, on top of the landed classic voice path (and the
    landed scene-modwheel route table, applied first -- scene data)."""

    # normal | source_swap_mw | shared_state | stale_slot
    CONTROL_MODE = "normal"
    SHARED = None                    # SharedVelRegister in shared_state mode
    SLOT_RELVEL = {}                 # slot -> last relvel word (stale_slot)

    def __init__(self, inp, key, velocity, slot=None):
        # per-instance modulator state (set BEFORE the ctor control pass)
        self.midi_vel = int(velocity)
        self.vel_word = vel_q(velocity)
        self.relvel_word = 0
        self.midi_relvel = 0
        if type(self).CONTROL_MODE == "stale_slot" and slot is not None:
            # negative control: the ctor's releaseVelocitySource.set_output(
            # 0, 0) is omitted, so a reused slot keeps the previous voice's
            # release-velocity word instead of starting at 0
            self.relvel_word = type(self).SLOT_RELVEL.get(slot, 0)
        if type(self).CONTROL_MODE == "shared_state":
            type(self).SHARED.vel = self.vel_word
            type(self).SHARED.relvel = 0
        self.last_vel_sums = [0, 0, 0, 0]
        super().__init__(inp, key, velocity)
        # SetQFB(0,0) gain anchor after the constructor control pass: per
        # voice once velocity routes reach VCA Gain (streamed to tb_voice.sv
        # as slot word 37 under flags bit 4)
        self.ctor_gain_anchor = self.prev_gain

    # --------------------------------------------------------- sources ---
    def release_velocity(self, midi_relvel):
        """SurgeVoice::release(): releaseVelocitySource.set_output(relvel/127)."""
        self.midi_relvel = int(midi_relvel)
        self.relvel_word = vel_q(midi_relvel)
        if type(self).CONTROL_MODE == "shared_state":
            type(self).SHARED.relvel = self.relvel_word
        if type(self).CONTROL_MODE == "stale_slot":
            slot = getattr(self, "slot", None)
            if slot is not None:
                type(self).SLOT_RELVEL[slot] = self.relvel_word

    def _source_value(self, src):
        mode = type(self).CONTROL_MODE
        if mode == "source_swap_mw":
            return self.inp.modwheel.value
        if mode == "shared_state":
            sh = type(self).SHARED
            return sh.vel if src == VELOCITY_SRC else sh.relvel
        return self.vel_word if src == VELOCITY_SRC else self.relvel_word

    # --------------------------------------------------------- control ---
    def _calc_ctrldata(self):
        if self.kind != "classic":
            raise vm.Refuse("SXT-036 fixture class is the classic voice path")
        inp = self.inp
        self.aeg.process_block()
        self.feg.process_block()
        cut = vm.qint(inp.cutoff)
        reso = vm.qint(inp.reso)
        emod = vm.qint(inp.envmod)
        vca = vm.qint(inp.vca_db)
        # 1) scene data: landed scene-modwheel route table (md order)
        mw = inp.modwheel.value
        for dst, depth in inp.scene_routes_mw:
            term = vm.qmul(vm.qint(depth), mw)
            if dst == vm.DEST_FU1_CUTOFF:
                cut = vm.sat(cut + term)
            elif dst == vm.DEST_FU1_RESO:
                reso = vm.sat(reso + term)
            elif dst == vm.DEST_VCA_GAIN:
                vca = vm.sat(vca + term)
            else:
                raise vm.Refuse(f"scene route modwheel->{dst} outside class")
        # 2) voice list: velocity / release-velocity routes (md order)
        sums = [0, 0, 0, 0]
        for src, dst, depth in inp.vel_routes:
            term = vm.qmul(vm.qint(depth), self._source_value(src))
            if dst == vm.DEST_FU1_CUTOFF:
                cut = vm.sat(cut + term)
            elif dst == vm.DEST_FU1_RESO:
                reso = vm.sat(reso + term)
            elif dst == vm.DEST_FU1_FEGMOD:
                emod = vm.sat(emod + term)
            elif dst == vm.DEST_VCA_GAIN:
                vca = vm.sat(vca + term)
            else:
                raise vm.Refuse(
                    f"voice route {SRC_NAME.get(src, src)}->{dst} outside the "
                    "declared SXT-036 destination class {308, 309, 310, 298}")
            sums[DEST_CODE[dst]] += term
        self.mod_vca_db = vca
        self.mod_envmod = emod
        self.cutoff_a = cut + vm.qmul(emod, self.feg.output)
        self.reso_a = reso
        self.last_vel_sums = sums
        if self.aeg.is_idle():
            self.keep_playing = False


def graph_row(graphs_path, rel):
    with open(graphs_path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("p") == rel:
                return row
    raise vm.Refuse(f"preset not found in graphs.jsonl: {rel}")


def build_tables(inp, vel_in, graphs_path, zero_routes, strip, out_of_class,
                 cross_scene=False):
    """Scene modwheel table (landed, preset md 's') + voice velocity table
    (preset md 'v' rows for ids 1/30, then the runtime fixture routes)."""
    row = graph_row(graphs_path, inp.preset_path)
    scene = row["g"]["md"]["s"][0]
    mw_table = []
    for r in scene["s"]:
        if r[0] != vm.MODWHEEL_SRC or r[3] not in SCENE_MW_DESTS:
            raise vm.Refuse(f"preset scene route {r[0]}->{r[3]} ({r[4]!r}) "
                            "outside the landed scene class")
        mw_table.append((r[3], r[5]))
    vel_table = []
    for r in scene["v"]:
        if r[0] not in SRC_CODE or r[3] not in DEST_CODE:
            raise vm.Refuse(f"preset voice route {r[0]}->{r[3]} ({r[4]!r}) "
                            "outside the declared SXT-036 class")
        vel_table.append((r[0], r[3], r[5]))
    for r in vel_in["fixture_routes"]:
        if r["modsource_id"] not in SRC_CODE:
            raise vm.Refuse(f"fixture route source {r['modsource_id']}")
        if r["dest_id"] not in DEST_CODE:
            raise vm.Refuse(f"fixture route dest {r['dest_id']} "
                            f"({r.get('dest_name')}) outside declared class")
        vel_table.append((r["modsource_id"], r["dest_id"], r["depth_raw"]))
    if out_of_class:
        vel_table.append((VELOCITY_SRC, 303, 21.86507))   # 'A Highpass'
    if cross_scene:
        # the real scene-B route carried by the named carrier
        # 'Damon Armani/Pads/House Of Chords.fxp' (graphs.jsonl: scene index
        # 1, ms_velocity -> 502 'B Osc 1 Sync', depth_raw -12.192568). The
        # frozen destination class is scene A only; per-instance state is
        # never shared across scenes, so this must be REFUSED, not folded
        # into a scene-A destination.
        vel_table.append((VELOCITY_SRC, 502, -12.192568))
    if strip:
        vel_table = []
    for zr in zero_routes:
        s, d = zr.split(":")
        s, d = SRC_FLAG[s], DEST_FLAG[d]
        if not any(x[0] == s and x[1] == d for x in vel_table):
            raise vm.Refuse(f"--zero-route {zr}: no such route in the table")
        vel_table = [(x[0], x[1], 0.0 if (x[0] == s and x[1] == d) else x[2])
                     for x in vel_table]
    return mw_table, vel_table


def resolve_sequence(ref):
    if os.path.sep in ref or ref.endswith(".json"):
        return ref
    for d in (os.path.join(REPO, "fixtures", "sequences"), LOCAL_SEQ_DIR):
        p = os.path.join(d, ref + ".json")
        if os.path.exists(p):
            return p
    raise vm.Refuse(f"sequence not found: {ref}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", default=os.path.join(REPO, "model", "voice",
                                                     "attacky_inputs.json"))
    ap.add_argument("--vel-inputs", default=VEL_INPUTS)
    ap.add_argument("--graphs", default=os.path.join(REPO, "corpus",
                                                     "normalized", "graphs.jsonl"))
    ap.add_argument("--sequence", required=True, help="sequence id or JSON path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--zero-route", action="append", default=[],
                    metavar="SRC:DEST")
    ap.add_argument("--source-swap-mw", action="store_true")
    ap.add_argument("--shared-state", action="store_true")
    ap.add_argument("--stale-slot-relvel", action="store_true")
    ap.add_argument("--out-of-class-route", action="store_true")
    ap.add_argument("--cross-scene-route", action="store_true")
    ap.add_argument("--strip-vel-routes", action="store_true")
    args = ap.parse_args()

    seq_path = resolve_sequence(args.sequence)
    seq = vm.load_sequence(seq_path)

    with open(args.vel_inputs, encoding="utf-8") as f:
        vel_in = json.load(f)
    if vel_in["preset"]["path"] != PRESET_REL:
        raise vm.Refuse("velocity sidecar is for a different carrier")

    # the declared fixture carrier is the SXT-022 v1 inputs sidecar
    inp = vm.Inputs(args.inputs, args.graphs, PRESET_REL)
    inp.preset_path = PRESET_REL
    # v2-runner adapter for the frozen v1 class (all inert, v1-exact;
    # identical to run_model.load_inputs)
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

    mw_table, vel_table = build_tables(inp, vel_in, args.graphs,
                                       args.zero_route, args.strip_vel_routes,
                                       args.out_of_class_route,
                                       args.cross_scene_route)
    inp.scene_routes_mw = mw_table
    inp.vel_routes = vel_table

    VelVoice.CONTROL_MODE = "normal"
    VelVoice.SLOT_RELVEL = {}
    if args.source_swap_mw:
        VelVoice.CONTROL_MODE = "source_swap_mw"
    if args.shared_state:
        VelVoice.CONTROL_MODE = "shared_state"
        VelVoice.SHARED = SharedVelRegister()
    if args.stale_slot_relvel:
        VelVoice.CONTROL_MODE = "stale_slot"

    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_samples = last_t + int(seq.get("tail_s", 2.5) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)

    master_amp = vm.db_to_linear(vm.qint(inp.master_db))
    a_min_const = vm.qint(-8.0)
    eps01 = vm.qint(0.01)
    inst_att_aeg = 1 if (vm.qint(inp.adsr["a"]) - a_min_const) < eps01 else 0
    inst_att_feg = 1 if (vm.qint(inp.fadsr["a"]) - a_min_const) < eps01 else 0
    probe = VelVoice(inp, 60, 100)
    inp.reset_draws()
    if VelVoice.SHARED is not None:
        VelVoice.SHARED.vel = VelVoice.SHARED.relvel = 0
    VelVoice.SLOT_RELVEL = {}

    def envrate(p):
        return vm.envelope_rate_linear_nowrap(vm.qint(p))

    # ---- frozen tb_voice.sv init words (run_model.py merged layout) ------
    uni_n = max(1, int(inp.n_unison))
    uni_words = [uni_n, probe.out_attenuation]
    for u in probe.u:
        uni_words += [u["t"], u["t_inv"], u["oscstate"]]
    uni_words += [0] * (3 * 16 - 3 * len(probe.u))
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
        0, probe.fu_poles, probe.fm_depth, 0, inp.mix1,        # 40..44
        inp.osc_pitch_offsets[0], inp.osc_pitch_offsets[1],
        inp.osc_pitch_offsets[2],                               # 45..47
    ] + [0] * 30                                                # 48..77
    init_words += uni_words                                     # 78..127

    # ---- tb_vel.sv words -------------------------------------------------
    vel_init = [total_blocks]
    vel_routes_words = [len(vel_table)]
    for src, dst, depth in vel_table:
        vel_routes_words.extend([SRC_CODE[src], DEST_CODE[dst], vm.qint(depth)])

    voices = []
    draw_sets = []
    events = list(seq["events"])
    ei = 0
    bs = BLOCK_SIZE
    halfband = vm.HalfbandD2()
    out_mono = []
    blocks_json = []
    ctrl = []
    vel_ctrl = []

    def draw_set_index_of(v):
        key = tuple(v.init_oscstate_set)
        if key not in draw_set_index_of.table:
            draw_set_index_of.table[key] = len(draw_sets)
            draw_sets.append(list(v.init_oscstate_set))
        return draw_set_index_of.table[key]

    draw_set_index_of.table = {}

    for b in range(total_blocks):
        blk = {"b": b, "create": [], "release": [], "voices": []}
        created = {}      # slot -> midi velocity
        released = {}     # slot -> midi release velocity
        while ei < len(events) and -(-events[ei]["t"] // bs) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS)
                            if all(v.slot != i for v in voices))
                v = VelVoice(inp, e["note"], e.get("velocity", 0), slot=slot)
                v.slot = slot
                v.draw_set_index = draw_set_index_of(v)
                voices.append(v)
                blk["create"].append(slot)
                created[slot] = int(e.get("velocity", 0))
            elif e["type"] == "note_off":
                for v in reversed(voices):
                    if v.key == e["note"] and v.gate:
                        v.aeg.release()
                        v.feg.release()
                        v.release_velocity(e.get("velocity", 0))
                        v.gate = False
                        blk["release"].append(v.slot)
                        released[v.slot] = int(e.get("velocity", 0))
                        break
            elif e["type"] == "cc":
                if e["channel"] == 0 and e["controller"] == 1:
                    inp.modwheel.set_target(e["value"])
            ei += 1
        scene_l, scene_r = [0] * vm.BLOCK_SIZE_OS, [0] * vm.BLOCK_SIZE_OS
        ran = []
        alive = []
        for v in voices:
            keep = v.process_block(b, scene_l, scene_r, None)
            ran.append(v)
            if keep:
                alive.append(v)
        voices = alive
        inp.modwheel.process_block()        # declared SXT-022 order

        ctrl.extend([b, len(blk["create"]), inp.modwheel.value, master_amp])
        vel_ctrl.append(b)
        ran_by_slot = {v.slot: v for v in ran}
        for slot in range(N_SLOTS):
            rv = ran_by_slot.get(slot)
            vel_ctrl.extend([1 if rv is not None else 0,
                             1 if slot in created else 0, created.get(slot, 0),
                             1 if slot in released else 0,
                             released.get(slot, 0)])
            v = next((x for x in voices if x.slot == slot), None)
            if v is None:
                ctrl.extend([0] * CTRL_WORDS_PER_SLOT)
            else:
                full = (b % CHECKPOINT_EVERY == 0) or (not v.gate) or (b < 2)
                created_here = slot in blk["create"]
                flags = 1 | (2 if full else 0) \
                    | (4 if created_here else 0) \
                    | (8 if slot in blk["release"] else 0) \
                    | (16 if created_here else 0)     # SXT-036 anchor word
                ctrl.extend([
                    flags, v.key, v.gate,
                    v.aeg.state, v.feg.state,
                    v.ctrl_pmi, v.ctrl_pitchmult, v.ctrl_a_cov,
                    v.ctrl_hpf_target,
                    *v.ctrl_C, *v.ctrl_dC,
                    v.fbp_gain, v.fbp_outl,
                    v.aeg.phase, v.aeg.output, v.feg.phase, v.feg.output,
                    v.draw_set_index,
                    0, 0, 0, 0, 0,             # SXT-026a appendix (classic)
                    v.ctor_gain_anchor if created_here else 0,   # word 37
                    0, 0,
                ])
            if rv is None:
                continue
            rec = {"slot": slot, "key": rv.key, "gate": rv.gate,
                   "vel_words": [rv.vel_word, rv.relvel_word],
                   "vel_route_sums": list(rv.last_vel_sums)}
            if v is not None and ((b % CHECKPOINT_EVERY == 0) or
                                  (not v.gate) or (b < 2)):
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
                    "uni": [{"oscstate": x["oscstate"], "state": x["state"],
                             "last_level": x["last_level"],
                             "pwidth": x["pwidth"], "pwidth2": x["pwidth2"],
                             "dc_uni": x["dc_uni"]} for x in v.u],
                }
            blk["voices"].append(rec)

        scene_l = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene_l]
        bl = halfband.process(scene_l)
        br = bl   # mono bus: the R lane is identical
        mono = []
        for k in range(bs):
            l = vm.limit_i(vm.qmul(bl[k], master_amp), vm.qint(-8.0), vm.qint(8.0))
            r = vm.limit_i(vm.qmul(br[k], master_amp), vm.qint(-8.0), vm.qint(8.0))
            m = vm.limit_i((l + r) >> 1, -vm.ONE, vm.ONE)
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
            "format": "sxt-036-vel-voice-trace/1 (extends sxt-034-voice-trace/2 "
                      "with per-voice vel_words/vel_route_sums)",
            "sequence": seq["id"],
            "preset": PRESET_REL,
            "engine_pin":
                "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71",
            "checkpoint_every": CHECKPOINT_EVERY,
            "q_formats": {"samples": "Q10.21", "env_phase": "Q2.29",
                          "pitchmult_inv": "Q13.18", "velocity": "Q10.21",
                          "release_velocity": "Q10.21"},
            "slots": N_SLOTS,
            "scene_mw_routes": [{"dest": DEST_NAME[d], "dest_id": d,
                                 "depth_raw": dep} for d, dep in mw_table],
            "vel_routes": [{"source": SRC_NAME[s], "source_id": s,
                            "dest": DEST_NAME.get(d, str(d)), "dest_id": d,
                            "depth_raw": dep} for s, d, dep in vel_table],
            "vel_route_sums_word_order": ["cutoff", "reso", "fegmod", "vca"],
            "control_mode": VelVoice.CONTROL_MODE,
            "zero_routes": args.zero_route,
            "init": init_words,
            "ctrl_words_per_slot": CTRL_WORDS_PER_SLOT,
            "blocks": blocks_json,
            "samples16": out_mono,
        }, f)
        f.write("\n")

    write_hex(os.path.join(rtl_dir, "ctrl.hex"), ctrl)
    write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
    write_hex(os.path.join(rtl_dir, "sinc_main.hex"), vm.SINC_MAIN)
    write_hex(os.path.join(rtl_dir, "sinc_deriv.hex"), vm.SINC_DERIV)
    write_hex(os.path.join(rtl_dir, "vel_init.hex"), vel_init)
    write_hex(os.path.join(rtl_dir, "vel_routes.hex"), vel_routes_words)
    write_hex(os.path.join(rtl_dir, "vel_ctrl.hex"), vel_ctrl)

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks,
        "samples": len(out_mono), "control_mode": VelVoice.CONTROL_MODE,
        "vel_routes": [{"source": SRC_NAME[s], "dest": DEST_NAME.get(d, d),
                        "depth": dep} for s, d, dep in vel_table],
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except vm.Refuse as e:
        print(f"REFUSED (outside declared SXT-036 class): {e}", file=sys.stderr)
        sys.exit(2)
