#!/usr/bin/env python3
"""SXT-033 declared fixture configuration (shared by the extractor and the
reference renderer).

One implementation of: preset load, parameter read, and the DECLARED fixture
overrides applied through the official surgepy parameter-change path
(setParamVal, the same mechanism as the SXT-012 dry-bypass and the SXT-026
fixture configurations), with mandatory readback verification.

The overrides exist to ISOLATE one Classic oscillator slot so the
model-vs-reference budget checks exercise exactly the modeled arithmetic
(the Classic family slice). They are test configurations, never adapted
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
    "edges": ("patches_3rdparty/Argitoth/Rhythms/Edges Rhythm.fxp", 1),
    "horn": ("patches_3rdparty/Emu/Plucks/Horn Ring Boops.fxp", 1),
    "tentacles": ("patches_3rdparty/Lopyt/Soundscapes/Tentacles.fxp", 2),
    "crush": ("patches_factory/Basses/Crush Bass.fxp", 0),
    # out-of-class negative control: a recovery-basis preset whose Classic
    # slots live only in scene B (split scene mode) — the extractor must
    # refuse it for fixture use (scene-B/voice-graph integration is #48)
    "house": ("patches_3rdparty/Damon Armani/Pads/House Of Chords.fxp", 0),
}


def carrier_overrides(slot):
    """Uniform isolation override set for the modeled slot index."""
    return [
        ("mute_o1", slot != 0), ("mute_o2", slot != 1), ("mute_o3", slot != 2),
        ("mute_noise", True), ("mute_ring_12", True), ("mute_ring_23", True),
        ("fu0_off", True), ("fu1_off", True), ("fx_off", True),
        ("ws_off", True), ("lc_off", True), ("fbc_serial1", True),
        ("fm_off", True), ("scenemode_single", True), ("retrigger_on", True),
        ("drift_zero", True),
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
        "retrigger": bool(s.getParamVal(o["retrigger"])),
        "shape": p[0], "pw": p[1], "pw2": p[2], "submix": p[3], "sync": p[4],
        "unison_detune": p[5], "unison": int(p[6]),
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
        "lowcut": s.getParamVal(sc["lowcut"]),
        "scenemode": int(s.getParamVal(s.getPatch()["scenemode"])),
        "polymode": int(s.getParamVal(sc["polymode"])),
        "fx_types": [int(s.getParamVal(s.getPatch()["fx"][i]["type"]))
                     for i in range(16)],
        "mutes": {k: s.getParamVal(sc["mute_" + k])
                  for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23")},
    }


def apply_overrides(s, slot):
    """Apply the declared overrides and verify the readback (fail-closed)."""
    return _core.apply_overrides(s, slot, carrier_overrides(slot), read_params,
                                 "lowcut")


def build_instance(surgepy, oc, carrier):
    """Fresh engine instance: loadPatch + overrides + readback. Returns s."""
    return _core.build_instance(surgepy, oc, CARRIERS, carrier,
                                apply_overrides)
