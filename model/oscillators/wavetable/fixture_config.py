#!/usr/bin/env python3
"""SXT-026 declared fixture configuration (shared by the extractor and the
reference renderer).

One implementation of: preset load, parameter read, and the DECLARED fixture
overrides applied through the official surgepy parameter-change path
(setParamVal, the same mechanism as the SXT-012 dry-bypass), with mandatory
readback verification. The overrides exist to isolate the wavetable slice
for model-vs-reference budget checks; they are test configurations, never
adapted presets, and never count toward preset coverage.
"""

import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

PRESET_REL = "resources/data/patches_3rdparty/Argitoth/Drums/Kick.fxp"
PRESET_MF_REL = "resources/data/patches_3rdparty/Argitoth/FX/Monster Feedback.fxp"

WT_FIX = [("mute_o1", 1), ("mute_noise", 1), ("fu1_off", 1)]

# Monster Feedback declared fixture config: WT osc only. Mute the Classic
# osc + noise, set both filter units Off, turn the four FX instances Off
# (the declared SXT-012 dry-bypass mechanism), and force retrigger ON
# (the patch stores retrigger OFF for the WT osc -> free-running start
# phase; the product contract requires deterministic starts for evidence).
MF_FIX = [("mute_o1", 1), ("mute_noise", 1), ("fu0_off", 1), ("fu1_off", 1),
          ("fx_off", 1), ("retrigger_on", 1), ("scene_volume", 0.6)]


class Refuse(Exception):
    pass


def preset_abs(oc, preset_rel=PRESET_REL):
    return os.path.join(oc.engine_dir(), preset_rel)


def read_params(s):
    sc = s.getPatch()["scene"][0]
    o = sc["osc"][1]
    p = {k: s.getParamVal(o["p"][k]) for k in range(7)}
    return {
        "osc_type": s.getParamVal(o["type"]),
        "octave": s.getParamVal(o["octave"]),
        "scene_octave": s.getParamVal(sc["octave"]),
        "keytrack": s.getParamVal(o["keytrack"]),
        "pitch_param": s.getParamVal(o["pitch"]),
        "retrigger": s.getParamVal(o["retrigger"]),
        "morph": p[0], "skewv": p[1], "saturate": p[2], "formant": p[3],
        "skewh": p[4], "unison_detune": p[5], "unison": p[6],
        "o1_level": s.getParamVal(sc["level_o1"]),
        "o2_level": s.getParamVal(sc["level_o2"]),
        "mute_o1": s.getParamVal(sc["mute_o1"]),
        "mute_o2": s.getParamVal(sc["mute_o2"]),
        "mute_o3": s.getParamVal(sc["mute_o3"]),
        "mute_noise": s.getParamVal(sc["mute_noise"]),
        "level_noise": s.getParamVal(sc["level_noise"]),
        "fu0_type": s.getParamVal(sc["filterunit"][0]["type"]),
        "fu1_type": s.getParamVal(sc["filterunit"][1]["type"]),
        "filter_config": s.getParamVal(sc["filterblock_configuration"]),
        "width": s.getParamVal(sc["width"]),
        "pan": s.getParamVal(sc["pan"]),
        "playmode": s.getParamVal(sc["polymode"]),
        "drift": s.getParamVal(sc["drift"]),
        "scene_volume": s.getParamVal(sc["volume"]),
        "vca_db": s.getParamVal(sc["vca_level"]),
        "vca_velsense": s.getParamVal(sc["vca_velsense"]),
        "master_db": s.getParamVal(s.getPatch()["volume"]),
        "adsr": {k: s.getParamVal(sc["adsr"][0][k])
                 for k in ("a", "d", "s", "r", "a_s", "d_s", "r_s", "mode")},
    }


def apply_overrides(s, overrides):
    """Apply declared overrides and verify the readback (fail-closed)."""
    sc = s.getPatch()["scene"][0]
    applied = {}
    for key, val in overrides:
        if key == "mute_o1":
            s.setParamVal(sc["mute_o1"], 1.0)
            applied["mute_o1"] = 1.0
        elif key == "mute_noise":
            s.setParamVal(sc["mute_noise"], 1.0)
            applied["mute_noise"] = 1.0
        elif key == "fu0_off":
            # filter unit Off == fut_none == 0
            s.setParamVal(sc["filterunit"][0]["type"], 0.0)
            applied["fu0_type"] = 0.0
        elif key == "fu1_off":
            s.setParamVal(sc["filterunit"][1]["type"], 0.0)
            applied["fu1_type"] = 0.0
        elif key == "fx_off":
            import surgepy.constants as C

            for i in range(16):
                s.setParamVal(s.getPatch()["fx"][i]["type"], C.fxt_off)
            # the loadFx swap happens at the next control pass (SXT-012
            # dry-bypass): run one settle block before any readback
            sbuf = s.createMultiBlock(1)
            s.processMultiBlock(sbuf)
            applied["fx_all_off"] = 1.0
        elif key == "retrigger_on":
            s.setParamVal(sc["osc"][1]["retrigger"], 1.0)
            applied["retrigger"] = 1.0
        elif key == "scene_volume":
            s.setParamVal(sc["volume"], float(val))
            applied["scene_volume"] = float(val)
        elif key == "unison":
            s.setParamVal(sc["osc"][1]["p"][6], float(val))
            applied["unison"] = float(val)
        elif key == "morph":
            s.setParamVal(sc["osc"][1]["p"][0], float(val))
            applied["morph"] = float(val)
        elif key == "octave":
            s.setParamVal(sc["osc"][1]["octave"], float(val))
            applied["octave"] = float(val)
        elif key == "keytrack":
            s.setParamVal(sc["osc"][1]["keytrack"], float(val))
            applied["keytrack"] = float(val)
        else:
            raise Refuse("unknown override %r" % key)
    d = read_params(s)
    for k, v in applied.items():
        if k == "fx_all_off":
            types = [s.getParamVal(s.getPatch()["fx"][i]["type"])
                     for i in range(16)]
            if any(abs(t) > 1e-6 for t in types):
                raise Refuse("override readback failed: fx types %r" % types)
            continue
        if abs(d[k] - v) > 1e-6:
            raise Refuse("override readback failed: %s = %r" % (k, d[k]))
    return d


def build_instance(surgepy, oc, overrides, preset_rel=PRESET_REL):
    """Fresh engine instance: loadPatch + overrides + readback. Returns s."""
    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(preset_abs(oc, preset_rel)):
        raise Refuse("loadPatch failed")
    apply_overrides(s, overrides)
    return s
