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

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

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


class Refuse(Exception):
    pass


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
    rel, _slot = CARRIERS[carrier]
    return os.path.join(oc.engine_dir(), "resources", "data", rel)


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
    sc = s.getPatch()["scene"][0]
    applied = {}
    for key, val in carrier_overrides(slot):
        if key.startswith("mute_"):
            s.setParamVal(sc[key], 1.0 if val else 0.0)
            applied[key] = 1.0 if val else 0.0
        elif key in ("fu0_off", "fu1_off"):
            idx = 0 if key == "fu0_off" else 1
            s.setParamVal(sc["filterunit"][idx]["type"], 0.0)
            applied["fu%d_type" % idx] = 0
        elif key == "fx_off":
            import surgepy.constants as C

            for i in range(16):
                s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)
            # the loadFx swap happens at the next control pass (SXT-012
            # dry-bypass): run one settle block before any readback
            sbuf = s.createMultiBlock(1)
            s.processMultiBlock(sbuf)
            applied["fx_types"] = [0] * 16
        elif key == "ws_off":
            s.setParamVal(sc["wsunit"]["type"], 0.0)
            applied["ws_type"] = 0
        elif key == "lc_off":
            s.setParamVal(sc["lowcut"], -72.0)
            applied["lowcut"] = -72.0
        elif key == "fbc_serial1":
            s.setParamVal(sc["filterblock_configuration"], 0.0)
            applied["filter_config"] = 0
        elif key == "fm_off":
            s.setParamVal(sc["fm_switch"], 0.0)
            applied["fm_switch"] = 0
        elif key == "scenemode_single":
            s.setParamVal(s.getPatch()["scenemode"], 0.0)
            applied["scenemode"] = 0
        elif key == "retrigger_on":
            s.setParamVal(sc["osc"][slot]["retrigger"], 1.0)
            applied["retrigger"] = 1.0
        elif key == "drift_zero":
            s.setParamVal(sc["drift"], 0.0)
            applied["drift"] = 0.0
        else:
            raise Refuse("unknown override %r" % key)
    d = read_params(s, slot)
    for k, v in applied.items():
        got = d["mutes"][k[5:]] if k.startswith("mute_") else d[k]
        if isinstance(v, list):
            if got != v:
                raise Refuse("override readback failed: %s = %r" % (k, got))
        elif isinstance(v, float) and isinstance(got, bool):
            if float(got) != v:
                raise Refuse("override readback failed: %s = %r" % (k, got))
        elif abs(float(got) - float(v)) > 1e-6:
            raise Refuse("override readback failed: %s = %r (want %r)"
                         % (k, got, v))
    return d


def build_instance(surgepy, oc, carrier):
    """Fresh engine instance: loadPatch + overrides + readback. Returns s."""
    s = surgepy.createSurge(48000.0)
    _rel, slot = CARRIERS[carrier]
    if not s.loadPatch(preset_abs(oc, carrier)):
        raise Refuse("loadPatch failed: %s" % carrier)
    apply_overrides(s, slot)
    return s
