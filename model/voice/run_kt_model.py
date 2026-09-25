#!/usr/bin/env python3
"""SXT-042 model runner: render a fixture sequence through the frozen voice
model (SXT-022 / SXT-026a) with the keytrack (ms_keytrack, id 2) route table
made explicit, and emit the keytrack control-plane stimulus + trace that
`rtl/voice/tb_kt.sv` must reproduce EXACTLY (integer equality).

The audio path is the landed one: with no control flag the render is
byte-identical to `model/voice/run_model.py` on the same inputs/sequence
(asserted by tests/test_sxt042_keytrack.py).  What this runner adds is the
declared observation of the keytrack modsource:

  * `kt_word` per voice instance = (state.pitch - keytrack_root)/12 (Q10.21),
    set at voice creation and refreshed AFTER the control pass's route
    application (the declared 1-control-pass lag),
  * the per-destination sums of that voice's keytrack route terms
    (cutoff / reso / feg-mod), and
  * the resulting localcopy words (mod_cutoff / mod_reso / mod_envmod /
    mod_vca_db) after the full md-ordered voice-route pass.

Outputs (under --out-dir):
  model.wav             int16 mono render (fixtures WAV convention)
  model_trace.json      kt control-plane trace (block -> per-voice records)
  rtl/kt_init.hex       [total_blocks, keytrack_root, scene_octave,
                         cutoff_q, reso_q, envmod_q, vca_q, n_routes]
  rtl/kt_routes.hex     (src_code, dest_code, depth_q21) x n_routes, md order
  rtl/kt_ctrl.hex       per block: [b] + per slot [active, key, vel]

Negative-control flags (each must demonstrably fail its check; see
tools/kt_negative_controls.py):
  --zero-dest {cutoff,reso,fegmod}  force one keytrack destination's depths
                                    to 0 (routing-zeroed control)
  --shared-kt                       ONE keytrack word shared by the whole
                                    voice pool instead of per-instance
  --source-swap {velocity,modwheel} bind the keytrack routes to another
                                    landed source (issue #76 names modwheel;
                                    velocity is the non-degenerate swap on a
                                    fixture with no CC events)
  --ignore-root                     keytrack word = pitch/12 (root dropped)
  --refresh-before                  refresh the modsource BEFORE the route
                                    application (declared lag inverted) --
                                    an inertness probe on constant-pitch
                                    voices, recorded as such
  --out-of-class-route              inject keytrack -> 'A Pan' (265); the
                                    runner MUST refuse (exit 2)
  --synthetic-routes                add declared keytrack routes to Filter 1
                                    Resonance (309) and FEG Mod (310) so the
                                    RTL exactness fixture covers the whole
                                    frozen destination class. Exactness-only:
                                    the pinned engine never rendered this
                                    configuration, so NO reference/fidelity
                                    claim may be made from it.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402

V2_INPUTS = os.path.join(REPO, "model", "voice", "bells_inputs.json")
KT_INPUTS = os.path.join(REPO, "model", "voice", "bells_kt_inputs.json")
BLOCK_SIZE = vm.BLOCK_SIZE
FQ = vm.FQ
N_SLOTS = 8

# stimulus encodings
SRC_CODE = {vm.VELOCITY_SRC: 0, vm.KEYTRACK_SRC: 1}
DEST_CODE = {vm.DEST_FU1_CUTOFF: 0, vm.DEST_FU1_RESO: 1,
             vm.DEST_FU1_FEGMOD: 2, vm.DEST_VCA_GAIN: 3,
             vm.DEST_FU2_CUTOFF: 4, vm.DEST_FU2_RESO: 5,
             vm.DEST_FU2_FEGMOD: 6}
DEST_NAME = {308: "A Filter 1 Cutoff", 309: "A Filter 1 Resonance",
             310: "A Filter 1 FEG Mod Amount", 298: "A VCA Gain",
             314: "A Filter 2 Cutoff", 315: "A Filter 2 Resonance",
             318: "A Filter 2 FEG Mod Amount"}
OUT_OF_CLASS_DEST = 265                    # 'A Pan' (a real corpus keytrack
                                           # destination, outside this leaf)
SYNTHETIC_ROUTES = [(vm.DEST_FU1_RESO, 0.125), (vm.DEST_FU1_FEGMOD, 8.0)]


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


class KtVoice(vm.VoiceV2):
    """Voice with the keytrack SOURCE isolated for the negative controls.

    The route application, the word formats and the schedule are the frozen
    ones (`vm.VoiceV2`); only `keytrack_value()` -- the quantity this leaf
    freezes -- is mutable, so a control can never accidentally also change
    the plumbing it is supposed to hold fixed.
    """

    MODE = "normal"
    SHARED_WORD = None
    REFRESH_BEFORE = False

    def __init__(self, inp, key, velocity):
        super().__init__(inp, key, velocity)
        if type(self).MODE == "shared":
            # ONE global keytrack instance for the whole pool: each note-on
            # overwrites the word every sounding voice reads (the classic
            # shared-instead-of-per-instance state error).
            type(self).SHARED_WORD = vm.keytrack_word(self.pitch_voice,
                                                      inp.keytrack_root)

    def keytrack_value(self):
        cls = type(self)
        if cls.MODE == "shared":
            if cls.SHARED_WORD is None:
                cls.SHARED_WORD = self.kt_word     # first voice of the run
            return cls.SHARED_WORD
        if cls.MODE == "swap_velocity":
            return self.fvel
        if cls.MODE == "swap_modwheel":
            return self.inp.modwheel.value
        if cls.MODE == "ignore_root":
            return vm.qint(self.pitch_voice / float(
                vm.KEYTRACK_SEMITONES_PER_UNIT))
        return self.kt_word

    def _apply_voice_routes(self):
        if type(self).REFRESH_BEFORE:
            # declared lag inverted (control): refresh the modsource BEFORE
            # the route application instead of after it
            self.kt_word = vm.keytrack_word(self.pitch_voice,
                                            self.inp.keytrack_root)
        super()._apply_voice_routes()


def build_route_table(inp, kt_in, zero_dest, synthetic, out_of_class,
                      zero_velocity_cutoff=False):
    """Ordered md voice-route table, cross-checked against the kt sidecar."""
    # The sidecar keeps the FULL md-ordered row list (including the unit-2
    # rows that are inert in this class); `InputsV2` drops the inert rows at
    # parse time.  Dropping them from the sidecar must reproduce the parse
    # exactly -- that is the cross-check.
    sidecar = [(r["source_id"], r["dest_id"], r["depth_raw"])
               for r in kt_in["voice_routes"]]
    sidecar_live = [r for r in sidecar if r[1] not in vm.KEYTRACK_DEST_INERT]
    if sidecar_live != [(s, d, dep) for s, d, dep in inp.voice_routes]:
        raise vm.Refuse("kt sidecar voice_routes != InputsV2 parse of the "
                        "same preset (sidecar/graph drift)")
    if int(kt_in["keytrack_root"]) != int(inp.keytrack_root):
        raise vm.Refuse("kt sidecar keytrack_root != v2 sidecar")
    if int(kt_in["scene_octave"]) != int(inp.scene_octave):
        raise vm.Refuse("kt sidecar scene_octave != v2 sidecar")

    table = list(sidecar)
    if synthetic:
        table += [(vm.KEYTRACK_SRC, dst, dep) for dst, dep in SYNTHETIC_ROUTES]
    if zero_dest is not None:
        code = {"cutoff": vm.DEST_FU1_CUTOFF, "reso": vm.DEST_FU1_RESO,
                "fegmod": vm.DEST_FU1_FEGMOD}[zero_dest]
        table = [(s, d, 0.0 if (s == vm.KEYTRACK_SRC and d == code) else dep)
                 for s, d, dep in table]
    if out_of_class:
        table.append((vm.KEYTRACK_SRC, OUT_OF_CLASS_DEST, 12.0))
    if zero_velocity_cutoff:
        # control-VALIDITY probe (not a leaf control): zero the VELOCITY route
        # into the same destination the keytrack route feeds, to test whether
        # the reference check on this carrier can discriminate the presence of
        # a cutoff modulation term at all.
        table = [(s, d, 0.0 if (s == vm.VELOCITY_SRC and
                                d == vm.DEST_FU1_CUTOFF) else dep)
                 for s, d, dep in table]
    live_kt = [r for r in table
               if r[0] == vm.KEYTRACK_SRC and r[1] in vm.KEYTRACK_DEST_LIVE]
    if not live_kt:
        raise vm.Refuse("no live keytrack route in the table: nothing to "
                        "verify (a zeroed-depth control keeps its route)")
    for src, dst, _ in table:
        if src == vm.KEYTRACK_SRC and dst not in (
                tuple(vm.KEYTRACK_DEST_LIVE) + tuple(vm.KEYTRACK_DEST_INERT)):
            raise vm.Refuse(
                f"keytrack route -> {dst} ({DEST_NAME.get(dst, 'unnamed')}) "
                "outside the declared SXT-042 destination class "
                "{308, 309, 310} (+ inert unit-2 {314, 315, 318})")
    return table


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", default=V2_INPUTS)
    ap.add_argument("--kt-inputs", default=KT_INPUTS)
    ap.add_argument("--sequence", required=True, help="sequence id or JSON path")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--zero-dest", choices=("cutoff", "reso", "fegmod"))
    ap.add_argument("--shared-kt", action="store_true")
    ap.add_argument("--source-swap", choices=("velocity", "modwheel"))
    ap.add_argument("--ignore-root", action="store_true")
    ap.add_argument("--refresh-before", action="store_true")
    ap.add_argument("--out-of-class-route", action="store_true")
    ap.add_argument("--synthetic-routes", action="store_true")
    ap.add_argument("--diagnostic-zero-velocity-cutoff", action="store_true",
                    help="control-VALIDITY probe: zero the VELOCITY route into "
                         "Filter 1 Cutoff (not a keytrack control)")
    args = ap.parse_args()

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences",
                                seq_path + ".json")
    seq = vm.load_sequence(seq_path)

    inp = vm.InputsV2(args.inputs)
    inp.check_sequence(seq)
    with open(args.kt_inputs, encoding="utf-8") as f:
        kt_in = json.load(f)

    table = build_route_table(inp, kt_in, args.zero_dest,
                              args.synthetic_routes, args.out_of_class_route,
                              args.diagnostic_zero_velocity_cutoff)
    inp.voice_routes = table

    KtVoice.MODE = "normal"
    KtVoice.SHARED_WORD = None
    KtVoice.REFRESH_BEFORE = bool(args.refresh_before)
    if args.shared_kt:
        KtVoice.MODE = "shared"
    if args.source_swap:
        KtVoice.MODE = "swap_" + args.source_swap
    if args.ignore_root:
        KtVoice.MODE = "ignore_root"

    notes = [e for e in seq["events"] if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_samples = last_t + int(seq.get("tail_s", 2.5) * vm.SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)

    master_amp = vm.db_to_linear(vm.qint(inp.master_db))

    kt_init = [total_blocks, int(inp.keytrack_root), int(inp.scene_octave),
               vm.qint(inp.cutoff), vm.qint(inp.reso), vm.qint(inp.envmod),
               vm.qint(inp.vca_db), len(table)]
    kt_routes = []
    for src, dst, depth in table:
        kt_routes += [SRC_CODE[src], DEST_CODE[dst], vm.qint(depth)]

    voices = []
    events = list(seq["events"])
    ei = 0
    bs = BLOCK_SIZE
    halfband = vm.HalfbandD2()
    out_mono = []
    blocks_json = []
    kt_ctrl = []

    for b in range(total_blocks):
        created, released = [], []
        while ei < len(events) and -(-events[ei]["t"] // bs) <= b:
            e = events[ei]
            if e["type"] == "note_on":
                slot = next(i for i in range(N_SLOTS)
                            if all(v.slot != i for v in voices))
                v = KtVoice(inp, e["note"], e.get("velocity", 0))
                v.slot = slot
                voices.append(v)
                created.append(slot)
            elif e["type"] == "note_off":
                for v in reversed(voices):
                    if v.key == e["note"] and v.gate:
                        v.aeg.release()
                        v.feg.release()
                        v.gate = False
                        released.append(v.slot)
                        break
            elif e["type"] == "cc":
                if e["channel"] == 0 and e["controller"] == 1:
                    inp.modwheel.set_target(e["value"])
            ei += 1

        scene_l, scene_r = [0] * vm.BLOCK_SIZE_OS, [0] * vm.BLOCK_SIZE_OS
        alive, recs = [], []
        slot_state = {}
        for v in voices:
            keep = v.process_block(b, scene_l, scene_r, None)
            slot_state[v.slot] = (v.key, v.fvel)
            recs.append({
                "slot": v.slot, "key": v.key, "gate": v.gate,
                "pitch": v.pitch_voice,
                "kt_word": v.kt_word,
                "kt_source_value": v.keytrack_value(),
                "kt_route_sums": list(v.kt_route_sums),
                "mod_cutoff": v.mod_cutoff, "mod_reso": v.mod_reso,
                "mod_envmod": v.mod_envmod, "mod_vca_db": v.mod_vca_db,
            })
            if keep:
                alive.append(v)
        voices = alive
        inp.modwheel.process_block()

        kt_ctrl.append(b)
        for slot in range(N_SLOTS):
            if slot in slot_state:
                key, vel = slot_state[slot]
                kt_ctrl += [1, key, vel]
            else:
                kt_ctrl += [0, 0, 0]

        blocks_json.append({"b": b, "create": created, "release": released,
                            "voices": recs})

        # output stage: identical to run_model.py (mono bus, R lane == L lane)
        scene_l = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in scene_l]
        bl = halfband.process(scene_l)
        br = bl
        for k in range(bs):
            lw = vm.limit_i(vm.qmul(bl[k], master_amp),
                            vm.qint(-8.0), vm.qint(8.0))
            rw = vm.limit_i(vm.qmul(br[k], master_amp),
                            vm.qint(-8.0), vm.qint(8.0))
            m = vm.limit_i((lw + rw) >> 1, -vm.ONE, vm.ONE)
            out_mono.append((m * 32767) >> FQ if m >= 0
                            else -((-m * 32767) >> FQ))

    os.makedirs(args.out_dir, exist_ok=True)
    rtl_dir = os.path.join(args.out_dir, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)
    vm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono, vm.SR)
    write_hex(os.path.join(rtl_dir, "kt_init.hex"), kt_init)
    write_hex(os.path.join(rtl_dir, "kt_routes.hex"), kt_routes)
    write_hex(os.path.join(rtl_dir, "kt_ctrl.hex"), kt_ctrl)

    with open(os.path.join(args.out_dir, "model_trace.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "format": "sxt-042-kt-control-trace/1",
            "issue": "SXT-042",
            "sequence": seq["id"],
            "preset": inp.preset_path,
            "engine_pin":
                "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71",
            "q_formats": {"keytrack": "Q10.21", "params": "Q10.21"},
            "keytrack_root": int(inp.keytrack_root),
            "scene_octave": int(inp.scene_octave),
            "control_mode": KtVoice.MODE,
            "refresh_before": bool(KtVoice.REFRESH_BEFORE),
            "route_table": [{"source_id": s, "dest_id": d,
                             "dest": DEST_NAME.get(d, "unnamed"),
                             "depth_raw": dep} for s, d, dep in table],
            "kt_sum_order": list(vm.KEYTRACK_SUM_ORDER),
            "slots": N_SLOTS,
            "blocks": blocks_json,
        }, f)
        f.write("\n")

    print(json.dumps({
        "sequence": seq["id"], "blocks": total_blocks,
        "samples": len(out_mono),
        "control_mode": KtVoice.MODE,
        "refresh_before": bool(KtVoice.REFRESH_BEFORE),
        "routes": [{"source": "keytrack" if s == vm.KEYTRACK_SRC
                    else "velocity", "dest": DEST_NAME.get(d, "unnamed"),
                    "depth": dep} for s, d, dep in table],
        "model_wav": os.path.join(args.out_dir, "model.wav"),
        "trace": os.path.join(args.out_dir, "model_trace.json"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except vm.Refuse as e:
        print(f"REFUSED (outside declared SXT-042 class): {e}", file=sys.stderr)
        sys.exit(2)
