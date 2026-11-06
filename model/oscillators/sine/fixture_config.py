#!/usr/bin/env python3
"""SXT-040 declared fixture configuration (shared by the extractor and the
reference renderer).

One implementation of: preset load, parameter read, and the DECLARED fixture
overrides applied through the official surgepy parameter-change path
(setParamVal), with mandatory readback verification. Structure and override
set follow the landed SXT-033 Classic-family configuration
(`model/oscillators/classic/fixture_config.py`); the modeled slot is a Sine
oscillator (type 1) instead of Classic.

The overrides exist to ISOLATE one Sine oscillator slot so the
model-vs-reference budget checks exercise exactly the modeled arithmetic
(the Sine family slice). They are test configurations, never adapted
presets, and never count toward preset coverage. The un-modeled stages are:

  * other mixer paths (other osc slots, noise, both ring modulators)
  * both filter units (the modeled voice runs the filter-off direct path)
  * all 16 FX slots, the waveshaper, the scene lowcut, the FM routing
  * filter-block configuration pinned to fc_serial1 (the mono voice path:
    SurgeVoice calls the oscillator with stereo = (fbc == fc_wide), and the
    frozen model is mono)
  * scene mode pinned to Single (scene-B integration is #48's scope)
  * oscillator retrigger forced ON (deterministic start phase; the product
    contract requires deterministic starts for evidence, as in SXT-026)

Carriers are recovery-basis presets from the issue #74 list (or, for the
negative control, a preset that must be REFUSED).
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "oscillators"))

from refusal import Refuse  # noqa: E402,F401
import osc_fixture_core as _core  # noqa: E402

CARRIERS = {
    # name: (preset path relative to resources/data/, modeled osc slot index)
    "badnews": ("patches_3rdparty/Bluelight/Pads/Bad News.fxp", 2),
    "tentacles": ("patches_3rdparty/Lopyt/Soundscapes/Tentacles.fxp", 0),
    "popcorn2k": ("patches_3rdparty/Nick Moritz/Keys/Popcorn 2K.fxp", 0),
    # out-of-class negative controls (recovery-basis presets the extractor
    # must REFUSE for fixture use; see extract_inputs.py gates):
    #   mortsnare - scene-A playmode mono (SXT-043 scope)
    #   arp2      - playmode mono single-trigger; sine_shape_remap raw 1 -> 28
    #   alone     - live voice routes into the modeled slot / pan
    #               (keytrack->Osc1 Feedback, lfo3->Osc1 Pitch, lfo2->Pan,
    #                velocity->Osc Drift)
    #   mystery4  - live voice route velocity->Amp EG Attack
    "mortsnare": ("patches_3rdparty/Emu/Drums/Mort Snare.fxp", 1),
    "arp2": ("patches_3rdparty/Inigo Kennedy/Rhythms/Arp 2.fxp", 1),
    "alone": ("patches_3rdparty/Inigo Kennedy/Atmospheres/Alone.fxp", 0),
    "mystery4": ("patches_3rdparty/Inigo Kennedy/Atmospheres/Mystery 4.fxp", 0),
}


def carrier_overrides(slot):
    """Uniform isolation override set for the modeled slot index.

    route_slot=1 pins the modeled slot's output route to the A path of the
    serial-1 filter block (route 1 is filtered to L by fc_serial1). Presets
    may store route 2 (the post-F1 dry/B path, whose gain is the F2 mix
    min(1, 1+filter_balance)) - e.g. Bad News stores route_o3 = 2 with
    balance -0.684 (B gain 0.316); without this override the modeled voice
    would enter the bus through parameter-dependent routing outside the
    declared slice. Test configuration, verified by readback."""
    return [
        ("mute_o1", slot != 0), ("mute_o2", slot != 1), ("mute_o3", slot != 2),
        ("mute_noise", True), ("mute_ring_12", True), ("mute_ring_23", True),
        ("fu0_off", True), ("fu1_off", True), ("fx_off", True),
        ("ws_off", True), ("lc_off", True), ("fbc_serial1", True),
        ("fm_off", True), ("scenemode_single", True), ("retrigger_on", True),
        ("drift_zero", True), ("route_slot_1", True),
    ]


def preset_abs(oc, carrier):
    return _core.preset_abs(oc, CARRIERS, carrier)


def read_params(s, slot):
    sc = s.getPatch()["scene"][0]
    o = sc["osc"][slot]
    p = {k: s.getParamVal(o["p"][k]) for k in range(7)}
    return {
        "osc_type": int(s.getParamVal(o["type"])),
        "octave": int(s.getParamVal(o["octave"])),
        "scene_octave": int(s.getParamVal(sc["octave"])),
        "keytrack": bool(s.getParamVal(o["keytrack"])),
        "pitch_param": s.getParamVal(o["pitch"]),
        "pitch_extend": bool(s.getExtend(o["pitch"])),
        "retrigger": bool(s.getParamVal(o["retrigger"])),
        "shape": int(p[0]),
        "fb": p[1],
        "fmmode": int(p[2]),
        "lowcut": p[3],
        "highcut": p[4],
        "unison_detune": p[5],
        "unison": int(p[6]),
        "fb_extend": bool(s.getExtend(o["p"][1])),
        "extend_detune": bool(s.getExtend(o["p"][5])),
        "absolute_detune": bool(s.getAbsolute(o["p"][5])),
        "drift": s.getParamVal(sc["drift"]),
        "character": int(s.getParamVal(s.getPatch()["character"])),
        "o_level": s.getParamVal(sc["level_o%d" % (slot + 1)]),
        "level_pfg": s.getParamVal(sc["level_pfg"]),
        "pan": s.getParamVal(sc["pan"]),
        "width": s.getParamVal(sc["width"]),
        "scene_volume": s.getParamVal(sc["volume"]),
        "vca_db": s.getParamVal(sc["vca_level"]),
        "vca_velsense": s.getParamVal(sc["vca_velsense"]),
        "master_db": s.getParamVal(s.getPatch()["volume"]),
        "adsr": {k: s.getParamVal(sc["adsr"][0][k])
                 for k in ("a", "d", "s", "r", "a_s", "d_s", "r_s", "mode")},
        "fu0_type": int(s.getParamVal(sc["filterunit"][0]["type"])),
        "fu1_type": int(s.getParamVal(sc["filterunit"][1]["type"])),
        "ws_type": int(s.getParamVal(sc["wsunit"]["type"])),
        "filter_config": int(s.getParamVal(sc["filterblock_configuration"])),
        "fm_switch": int(s.getParamVal(sc["fm_switch"])),
        "lowcut_scene": s.getParamVal(sc["lowcut"]),
        "scenemode": int(s.getParamVal(s.getPatch()["scenemode"])),
        "polymode": int(s.getParamVal(sc["polymode"])),
        "fx_types": [int(s.getParamVal(s.getPatch()["fx"][i]["type"]))
                     for i in range(16)],
        "mutes": {k: s.getParamVal(sc["mute_" + k])
                  for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23")},
        "route_slot": int(s.getParamVal(sc["route_o%d" % (slot + 1)])),
    }


def _route_slot_1(s, sc, slot, applied):
    s.setParamVal(sc["route_o%d" % (slot + 1)], 1.0)
    applied["route_slot"] = 1


def apply_overrides(s, slot):
    """Apply the declared overrides and verify the readback (fail-closed)."""
    return _core.apply_overrides(s, slot, carrier_overrides(slot), read_params,
                                 "lowcut_scene",
                                 extra={"route_slot_1": _route_slot_1})


def build_instance(surgepy, oc, carrier):
    """Fresh engine instance: loadPatch + overrides + readback. Returns s."""
    return _core.build_instance(surgepy, oc, CARRIERS, carrier,
                                apply_overrides)
