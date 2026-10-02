#!/usr/bin/env python3
"""SXT-043 model runner: render a fixture sequence through the frozen model.

Outputs (under --out-dir):
  model.wav            int16 mono render (fixtures WAV convention)
  model_trace.json     declared per-block articulation checkpoints + the
                       full 48 kHz sample stream
  rtl/init.hex         one-time control-plane constants for the testbench
  rtl/ev.hex           block-quantized note events (the RTL stimulus)

DECLARED MODEL / RTL BOUNDARY
-----------------------------
The RTL (`rtl/voice/tb_pm_mono_st_fp.sv`) implements the ARTICULATION LAYER:
the pm_mono_st_fp allocation state machine, the amp-envelope state machine
including its `attackFrom(level)` and `uber_release` entries, the SLOW_EXP
velocity smoother, and the portamento ramp -- and must match this model's
per-block state vector EXACTLY (integer equality at every block, every
slot; `tools/compare_pm_rtl_model.py`).

It does NOT re-implement the audio datapath.  The oscillator, filter and
output-staging datapath is already covered, integer-exactly, by the landed
SXT-022 / SXT-026a / SXT-034 / SXT-040 RTL (`rtl/voice/tb_voice.sv`,
`rtl/oscillators/sine/`), which this leaf imports unchanged rather than
duplicating; the model's audio render exists here only to anchor the
model-vs-reference budget on the carriers.  This boundary is the leaf's
declared checkpoint list and is stated in every record it produces.

Block-rate transcendentals that are evaluated ONCE per fixture (the envelope
rate-table lookups, `db_to_linear` gains) stay on the model side and are
streamed as plain precomputed words, exactly the frozen SXT-022 convention.
The ONE transcendental that is genuinely re-evaluated every block
(`glide_phase`, while a portamento glide is in flight) is instead
reproduced in the RTL by evaluating the SAME pinned table FORMULA with
SystemVerilog real-valued math functions ($ln), round-half-up-quantized with
the same `qint_r` helper tb_voice.sv already uses for the Sine oscillator's
`$cos`/`$sin` path (SXT-026a) -- not by shipping a pre-quantized ROM and
interpolating over it, which would double-round (once building the ROM word,
once interpolating) and could differ from the model's single-rounding result
by up to 1 LSB. The three named carriers all pin a LINEAR glide curve
(`porta.options.curve == 0`), so `glide_phase`'s table branch is a declared,
not a load-bearing, equivalence for this leaf's accepted evidence; it is
still implemented and exercised by the parameter-corner probes.
"""

import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))
sys.path.insert(0, os.path.join(REPO, "model", "oscillators", "sine"))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

import voice_model as vm                                       # noqa: E402
import sine_model as sm                                        # noqa: E402
import pm_mono_st_fp as pm                                     # noqa: E402
from refusal import Refuse                                     # noqa: E402


def _load_sibling(name):
    """Import a sibling module BY PATH under a distinct name.

    `model/oscillators/sine/` also contains a `fixture_config.py`, and
    importing `sine_model` leaves that directory ahead of this one on
    `sys.path`, so a bare `import fixture_config` can resolve to the wrong
    leaf's configuration.  Loading by explicit path makes the binding
    unambiguous.
    """
    spec = importlib.util.spec_from_file_location(
        "sxt043_" + name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


FQ = vm.FQ
ONE = vm.ONE
BLOCK_SIZE = vm.BLOCK_SIZE
BLOCK_SIZE_OS = vm.BLOCK_SIZE_OS
SR = vm.SR
TRACE_FORMAT = "sxt-043-playmode-trace/1"

INIT_WORD_ORDER = [
    "porta_rate_q29", "porta_curve_code", "porta_gliss", "porta_constrate",
    "porta_retrigger", "fingered", "porta_active", "priority_mode",
    "envelope_mode", "aeg_a_rate_q29", "aeg_d_rate_q29", "aeg_r_rate_q29",
    "aeg_uber_rate_q29", "aeg_sustain_q29", "aeg_a_s", "aeg_r_s",
    "aeg_inst_attack", "vel_coeff_q21", "vel_sigma_q21", "one_twelfth_q21",
    "const_rate_eps_q21", "scene_octave_term_q21", "total_blocks",
    "n_events", "pool",
]
CURVE_CODE = {pm.PORTA_LOG: 1, pm.PORTA_LIN: 0, pm.PORTA_EXP: 2}


class PmInputs(sm.Inputs):
    """The landed SXT-040 Sine inputs + this leaf's articulation fields."""

    def __init__(self, path):
        super().__init__(path)
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("schema") != "sxt-043-playmode-inputs/1":
            raise Refuse("inputs sidecar is not sxt-043-playmode-inputs/1")
        self.carrier = d["carrier"]
        self.play_mode = d["play_mode"]
        self.porta = d["portamento"]
        self.priority_mode = int(d["mono_voice_priority_mode"])
        self.envelope_mode = int(d["mono_voice_envelope_mode"])
        self.modulation_routes = d["modulation_routes"]
        self.engine_pin = d["engine_pin"]
        self.cut_activation = d["osc_cut_activation_probe"]
        if self.play_mode["id"] != pm.PLAY_MODE_ID:
            raise Refuse("inputs declare play_mode %r, not pm_mono_st_fp"
                         % (self.play_mode,))
        # Declared live route vocabulary: {Velocity, Keytrack} -> A VCA Gain
        # (the SXT-035 / SXT-042 destination class).  Order is the engine's
        # own `getAllModRoutings` order, which is the md array order the
        # pinned `applyModulationToLocalcopy` walks.
        self.vca_gain_routes = []
        for r in self.modulation_routes.get("live") or []:
            if r["dest"] != "A VCA Gain" or r["src"] not in ("Velocity",
                                                             "Keytrack"):
                raise Refuse(
                    "live modulation route %r -> %r is outside the declared "
                    "SXT-043 vocabulary {Velocity, Keytrack} -> A VCA Gain"
                    % (r["src"], r["dest"]))
            self.vca_gain_routes.append((r["src"], r["depth"]))


def write_hex(path, values, bits=32):
    mask = (1 << bits) - 1
    with open(path, "w", encoding="utf-8") as f:
        for v in values:
            f.write(f"{int(v) & mask:08x}\n")


def build_porta_config(inp, force_mode=None):
    opts = inp.porta["options"]
    fingered = (force_mode if force_mode is not None
                else inp.play_mode["id"]) == pm.PLAY_MODE_ID
    return pm.PortamentoConfig(
        porta_val=inp.porta["value"],
        curve=opts["curve"],
        gliss=opts["glissando"],
        constrate=opts["constantRate"],
        porta_retrigger=opts["retrigger"],
        fingered=fingered,
        porta_val_min=inp.porta["val_min"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--nc-share-portamento-state", action="store_true",
                    help="NEGATIVE CONTROL: share one portamento state across "
                         "voices instead of keeping it per instance")
    ap.add_argument("--nc-reset-osc-on-reclaim", action="store_true",
                    help="NEGATIVE CONTROL: re-init the oscillator on a mono "
                         "reclaim (the pinned engine does not, for Sine)")
    ap.add_argument("--nc-anchor-last-key", action="store_true",
                    help="NEGATIVE CONTROL: drop the pm_mono_st_fp fingered "
                         "special case and anchor the glide at last_key")
    args = ap.parse_args()

    seq_path = args.sequence
    if os.path.sep not in seq_path:
        seq_path = os.path.join(REPO, "fixtures", "sequences",
                                seq_path + ".json")
    seq = vm.load_sequence(seq_path)
    inp = PmInputs(args.inputs)

    fc = _load_sibling("fixture_config")
    fc.assert_sequence_sources_inert(
        seq, inp.modulation_routes.get("inert") or [])

    porta_cfg = build_porta_config(inp)
    if args.nc_anchor_last_key:
        porta_cfg.fingered = False      # NEGATIVE CONTROL

    scene = pm.MonoStFpScene(inp, porta_cfg, inp.priority_mode,
                             inp.envelope_mode)
    scene.nc_reset_osc_on_reclaim = args.nc_reset_osc_on_reclaim
    if args.nc_share_portamento_state:
        scene.shared_portamento = pm.Portamento(porta_cfg)

    events = list(seq["events"])
    notes = [e for e in events if e["type"] in ("note_on", "note_off")]
    last_t = max(e["t"] for e in notes) if notes else 0
    total_samples = last_t + int(float(seq.get("tail_s", 2.5)) * SR)
    total_blocks = -(-total_samples // BLOCK_SIZE)

    aeg = inp.adsr
    init_words = [
        porta_cfg.rate_q29,
        CURVE_CODE[porta_cfg.curve],
        1 if porta_cfg.gliss else 0,
        1 if porta_cfg.constrate else 0,
        1 if porta_cfg.porta_retrigger else 0,
        1 if porta_cfg.fingered else 0,
        1 if porta_cfg.porta_val > porta_cfg.porta_val_min else 0,
        scene.priority_mode,
        scene.envelope_mode,
        vm.envelope_rate_linear_nowrap(vm.qint(aeg["a"])),
        vm.envelope_rate_linear_nowrap(vm.qint(aeg["d"])),
        vm.envelope_rate_linear_nowrap(vm.qint(aeg["r"])),
        vm.envelope_rate_linear_nowrap(vm.qint(pm.UBER_RELEASE_RATE_PARAM)),
        vm.qint_phase(aeg["s"]),
        int(aeg["a_s"]),
        int(aeg["r_s"]),
        1 if (vm.qint(aeg["a"]) - vm.qint(-8.0)) < vm.qint(0.01) else 0,
        vm.qint(0.9 * 44100.0 / float(SR)),
        vm.qint(pm.SLOW_EXP_SIGMA),
        vm.qint(1.0 / 12.0),
        vm.qint(0.00001),
        vm.qint(12.0 * inp.scene_octave),
        total_blocks,
        len(notes),
        pm.MonoStFpScene.POOL,
    ]

    ev_words = []
    for e in notes:
        ev_words += [-(-e["t"] // BLOCK_SIZE),
                     1 if e["type"] == "note_on" else 2,
                     int(e["note"]),
                     int(e.get("velocity", 0))]

    halfband = vm.HalfbandD2()
    master_amp = vm.db_to_linear(vm.qint(inp.master_db))
    out_mono = []
    blocks_json = []
    ei = 0
    for b in range(total_blocks):
        while ei < len(notes) and -(-notes[ei]["t"] // BLOCK_SIZE) <= b:
            e = notes[ei]
            if e["type"] == "note_on":
                scene.note_on(b, int(e["note"]), int(e.get("velocity", 100)))
            else:
                scene.note_off(b, int(e["note"]), int(e.get("velocity", 0)))
            ei += 1
        bus = [0] * BLOCK_SIZE_OS
        scene.process_block(b, bus)
        rec = {"b": b, "slots": []}
        for slot in range(pm.MonoStFpScene.POOL):
            v = next((x for x in scene.voices if x.slot == slot), None)
            if v is None:
                rec["slots"].append([0] + [0] * pm.N_STATE_WORDS)
            else:
                rec["slots"].append([1] + v.state_words())
        bus = [vm.limit_i(x, vm.qint(-8.0), vm.qint(8.0)) for x in bus]
        bl = halfband.process(bus)
        mono = []
        for k in range(BLOCK_SIZE):
            lv = vm.qmul(bl[k], master_amp)
            lv = vm.limit_i(lv, vm.qint(-8.0), vm.qint(8.0))
            # mono bus: L and R are identical end-to-end (pan law folded into
            # outl, width structurally inert at fc_serial1), so (L+R)/2 == L
            m = vm.limit_i(lv, -ONE, ONE)
            s16 = (m * 32767) >> FQ if m >= 0 else -((-m * 32767) >> FQ)
            out_mono.append(s16)
            mono.append(m)
        rec["mono_block"] = mono
        blocks_json.append(rec)

    os.makedirs(args.out_dir, exist_ok=True)
    rtl_dir = os.path.join(args.out_dir, "rtl")
    os.makedirs(rtl_dir, exist_ok=True)
    vm.write_wav16(os.path.join(args.out_dir, "model.wav"), out_mono, SR)
    write_hex(os.path.join(rtl_dir, "init.hex"), init_words)
    write_hex(os.path.join(rtl_dir, "ev.hex"), ev_words)

    trace = {
        "format": TRACE_FORMAT,
        "leaf": "SXT-043",
        "issue": 77,
        "carrier": inp.carrier,
        "preset": inp.preset_path,
        "sequence": seq["id"],
        "engine_pin": inp.engine_pin,
        "play_mode": inp.play_mode,
        "portamento": inp.porta,
        "mono_voice_priority_mode": scene.priority_mode,
        "mono_voice_envelope_mode": scene.envelope_mode,
        "negative_controls_active": {
            "share_portamento_state": bool(args.nc_share_portamento_state),
            "reset_osc_on_reclaim": bool(args.nc_reset_osc_on_reclaim),
            "anchor_last_key": bool(args.nc_anchor_last_key),
        },
        "q_formats": {
            "key_pitch_pkey_portasrc": "Q10.21",
            "portaphase_env_phase": "Q2.29",
            "osc_omega_phase": "Q3.28",
            "samples_gains": "Q10.21",
        },
        "rtl_boundary": (
            "articulation layer only: allocation state machine, amp-envelope "
            "state machine (incl. attackFrom(level) and uber_release), "
            "SLOW_EXP velocity smoother, portamento ramp. The audio datapath "
            "is the landed SXT-022/026a/034/040 RTL and is NOT re-checked "
            "here."),
        "init_word_order": INIT_WORD_ORDER,
        "init": init_words,
        "ev_word_order": ["block", "kind(1=note_on,2=note_off)", "key",
                          "velocity"],
        "state_word_order": ["active"] + pm.STATE_WORD_ORDER,
        "pool": pm.MonoStFpScene.POOL,
        "total_blocks": total_blocks,
        "articulation_events": scene.events,
        "blocks": blocks_json,
        "samples16": out_mono,
    }
    with open(os.path.join(args.out_dir, "model_trace.json"), "w",
              encoding="utf-8") as f:
        json.dump(trace, f)
        f.write("\n")

    print(json.dumps({
        "carrier": inp.carrier,
        "sequence": seq["id"],
        "blocks": total_blocks,
        "samples": len(out_mono),
        "articulation_events": len(scene.events),
        "event_kinds": sorted({e["event"] for e in scene.events}),
        "model_wav": os.path.join(args.out_dir, "model.wav"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSED (outside declared SXT-043 class): {e}",
              file=sys.stderr)
        sys.exit(2)
