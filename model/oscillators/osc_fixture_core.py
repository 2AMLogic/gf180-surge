#!/usr/bin/env python3
"""Shared override-and-readback core for the Classic and Sine oscillator
fixture configurations (#495).

Used by ``classic/fixture_config.py`` and ``sine/fixture_config.py``, which
keep their public names (CARRIERS, carrier_overrides, read_params,
apply_overrides, build_instance, preset_abs, Refuse) as thin wrappers. The
per-family differences are parameters here, not dropped:

  * ``read_params``  -- family-specific, passed in (keys differ per family)
  * ``carrier_overrides`` -- family-specific override list, passed in
  * ``lowcut_key``   -- readback key for the lc_off override
                        (Classic "lowcut", Sine "lowcut_scene")
  * ``extra``        -- optional {override key: handler(s, sc, slot, applied)}
                        for family-only branches (Sine route_slot_1)

Readback is fail-closed exactly as before. This module is deliberately named
uniquely: a bare ``import fixture_config`` can resolve to the wrong sibling
(see model/voice/playmode/run_model.py). Wavetable and playmode fixtures do
not use it.
"""

import os

from refusal import Refuse


def preset_abs(oc, carriers, carrier):
    rel, _slot = carriers[carrier]
    return os.path.join(oc.engine_dir(), "resources", "data", rel)


def apply_overrides(s, slot, overrides, read_params, lowcut_key, extra=None):
    """Apply the declared overrides and verify the readback (fail-closed)."""
    extra = extra or {}
    sc = s.getPatch()["scene"][0]
    applied = {}
    for key, val in overrides:
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
            applied[lowcut_key] = -72.0
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
        elif key in extra:
            extra[key](s, sc, slot, applied)
        else:
            raise Refuse("unknown override %r" % key)
    d = read_params(s, slot)
    for k, v in applied.items():
        if k.startswith("mute_"):
            got = d["mutes"][k[5:]]
        else:
            got = d[k]
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


def build_instance(surgepy, oc, carriers, carrier, apply_fn):
    """Fresh engine instance: loadPatch + overrides + readback. Returns s."""
    s = surgepy.createSurge(48000.0)
    _rel, slot = carriers[carrier]
    if not s.loadPatch(preset_abs(oc, carriers, carrier)):
        raise Refuse("loadPatch failed: %s" % carrier)
    apply_fn(s, slot)
    return s
