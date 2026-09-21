#!/usr/bin/env python3
"""SXT-025: fail-closed extraction of the chosen preset's control-plane inputs.

Loads the census-blob-verified preset in a fresh surgepy instance (48 kHz),
reads the normalized effect state post-load, and writes
`model/integration/bells_inputs.json` -- the frozen control-plane input of
the integrated model, cross-checked against the committed compiled patch
image (SXT-020). Extraction rules follow model/effects/extract_fx_inputs.py
(SXT-023) and are declared there and in model/integration/README.md:

  * float params: engine getters (post-load normalized state; authoritative
    per AGENTS.md); each value is cross-checked against the image's verbatim
    `p` entry at the SXT-011 6-decimal export rounding (fail-closed);
  * `deactivated` flags: raw .fxp XML attribute (surgepy exposure gap;
    documented bridge, cross-checked by the fidelity budget);
  * send/return levels: engine getters, cross-checked against the image;
  * determinism gate: scene drift == 0 and every non-muted oscillator of a
    voicing scene has retrigger on (SXT-012 bit-identical class);
  * fx types, fx_bypass, fx_disable, census blob: equal to the image
    (fail-closed).

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only.
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

REL_PATH = "resources/data/patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp"
IMAGE_JSON = os.path.join(REPO, "model", "integration", "preset",
                          "Hell_s_Bells__e499f78d.image.json")
OUT_PATH = os.path.join(REPO, "model", "integration", "bells_inputs.json")

REVERB1_TYPE = 2
REVERB1_PARAMS = 12
PARAM_NAMES = ["predelay", "shape", "roomsize", "decaytime", "damping",
               "lowcut", "freq1", "gain1", "highcut", "mix", "width", "unused12"]


class Refuse(Exception):
    pass


def census_blob(rel_path):
    import csv

    csv_path = os.path.join(REPO, "corpus", "census-v0.1", "results",
                            "per-preset.csv")
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel_path:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel_path}")


def raw_xml_reverb_flags(rel_path, slot):
    """Per-param attributes of one FX slot from the raw .fxp XML (1-based
    field names, N = slot+1, as in SXT-023's extractor)."""
    data = open(os.path.join(oc.engine_dir(), rel_path), "rb").read().decode("latin-1")
    flags = {}
    for j in range(REVERB1_PARAMS):
        m = re.search(r"<fx%d_p%d\b([^>]*?)/?>" % (slot + 1, j), data)
        if not m:
            flags[j] = None
            continue
        attrs = m.group(1)
        deact = re.search(r'deactivated="([01])"', attrs)
        flags[j] = {
            "temposync": bool(re.search(r'temposync="1"', attrs)),
            "extend_range": bool(re.search(r'extend_range="1"', attrs)),
            "deactivated_absent": 'deactivated="' not in attrs,
            "deactivated": None if deact is None else deact.group(1) == "1",
        }
    tos = re.search(r'tempoOnSave[^>]*v="([-0-9.]+)"', data)
    return flags, (float(tos.group(1)) if tos else None)


def deactivated_flag(fx, j, deactivatable):
    """Reverb1 lowcut/highcut are plain (non-modulator) deactivatable
    frequency params: the pinned Parameter ctor defaults them to NOT
    deactivated when the raw attribute is absent (this rev-9 save carries
    no per-param attributes at all). Declared and cross-checked by the
    fidelity budget: the opposite hypothesis fails loudly (~-17 dB), this
    one reproduces the engine wet-dry difference exactly."""
    f = fx.get(j)
    if f is None:
        raise Refuse(f"no raw XML entry for p{j}")
    if f["deactivated_absent"]:
        return False
    return f["deactivated"]


def main():
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    blob = census_blob(REL_PATH)
    abs_path = os.path.join(oc.engine_dir(), REL_PATH)
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise Refuse(f"census blob mismatch: {actual} != {blob}")

    image = json.load(open(IMAGE_JSON))
    body = image["body"]
    graph = body["graph"]
    if image["header"]["source"]["census_blob_sha1"] != blob:
        raise Refuse("image census blob mismatch")
    img_scalars = graph["scalars"]
    if img_scalars.get("fxb") != 0:
        raise Refuse("fx section bypass != all-fx")
    if img_scalars.get("fxd") != 0:
        raise Refuse("fx disable mask nonzero")

    xml_flags, tempo = raw_xml_reverb_flags(REL_PATH, 5)

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(abs_path):
        raise Refuse(f"loadPatch failed: {REL_PATH}")
    patch = s.getPatch()

    # determinism gate (SXT-012 bit-identical class)
    sm = int(s.getParamVal(patch["scenemode"]))
    sa = int(s.getParamVal(patch["scene_active"]))
    if sm != 0 or sa != 0:
        raise Refuse(f"scene mode/active {sm}/{sa} not Single/A")
    drifts = []
    for sc_i in (sa,):
        sc = patch["scene"][sc_i]
        drift = float(s.getParamVal(sc["drift"]))
        drifts.append(drift)
        if drift != 0.0:
            raise Refuse(f"drift {drift} != 0 in scene {sc_i}")
        for oi in range(3):
            level = float(s.getParamVal(sc[f"level_o{oi+1}"]))
            mute = int(s.getParamVal(sc[f"mute_o{oi+1}"]))
            if level > 0 and mute == 0:
                rt = int(s.getParamVal(sc["osc"][oi]["retrigger"]))
                if rt != 1:
                    raise Refuse(f"osc{oi+1} retrigger off (non-muted)")

    engine_types = [int(s.getParamVal(patch["fx"][i]["type"])) for i in range(16)]
    graph_types = [fx.get("t", 0) for fx in graph["fx_slots"]]
    if engine_types != graph_types:
        raise Refuse("fx type mismatch engine vs image")

    volume_f = float(s.getParamVal(patch["volume"]))
    img_vol = graph["scalars"].get("vol")
    # The raw-side stored scalar is pre-migration; the engine getter (native
    # loader's normalized state) is authoritative (AGENTS.md). Metallic
    # (SXT-023) showed the same stored-0.0 / engine -2.025745 loader default.
    volume_note = None
    if img_vol is not None and abs(volume_f - img_vol) > 5e-7:
        volume_note = (f"image scalar vol={img_vol} is the pre-migration "
                       f"stored value; the loader's normalized master "
                       f"volume is {volume_f} dB (authoritative; same "
                       f"loader-default class as SXT-023 metallic)")
    scene_sends = [[float(s.getParamVal(patch["scene"][k]["send_level"][j]))
                    for j in range(2)] for k in range(2)]

    instances = []
    for slot in range(16):
        t = engine_types[slot]
        if t == 0:
            continue
        img_slot = graph["fx_slots"][slot]
        if not img_slot.get("on"):
            raise Refuse(f"slot{slot} enabled in engine but off in image")
        role = img_slot["r"]
        if t == REVERB1_TYPE:
            fxd = patch["fx"][slot]
            params = {}
            for j in range(REVERB1_PARAMS):
                v = float(s.getParamVal(fxd["p"][j]))
                pv = img_slot.get("p", [None] * 12)[j]
                if pv is not None and abs(v - pv) > 5e-7:
                    raise Refuse(
                        f"slot{slot} p{j} engine {v} vs image {pv}")
                params[PARAM_NAMES[j]] = v
            rl = float(s.getParamVal(fxd["return_level"]))
            if abs(rl - img_slot.get("rl", rl)) > 5e-7:
                raise Refuse("return level mismatch vs image")
            entry = {
                "slot": slot, "role": role, "type": "reverb1",
                "engine_order": body["derived"]["fx_section"]["slots"][slot]
                                  ["engine_order"],
                "params": params,
                "return_f": rl,
                "deactivated": {
                    "lowcut": deactivated_flag(xml_flags, 5, True),
                    "highcut": deactivated_flag(xml_flags, 8, True),
                },
                "caveat": "p11 (unused by Reverb1) carried verbatim from the "
                          "image; deactivated flags from the raw .fxp XML "
                          "attribute (surgepy exposure-gap bridge, "
                          "cross-checked by the fidelity budget)",
            }
        else:
            raise Refuse(f"slot{slot} type {t} outside the SXT-025 FX scope")
        if role.startswith("send"):
            idx = int(role[-1]) - 1
            if idx > 1:
                raise Refuse("send3/4 levels not exported (SXT-020 gate)")
            entry["send_slot"] = idx
            entry["send_gain_f"] = scene_sends[sa][idx]
            img_send = graph["scenes"][0].get("send", [None, None])[idx]
            if img_send is not None and abs(entry["send_gain_f"] - img_send) > 5e-7:
                raise Refuse(f"send level mismatch vs image bus{idx+1}")
        elif role.startswith(("ains", "bins", "global")):
            pass
        else:
            raise Refuse(f"role {role} outside the frozen scope")
        instances.append(entry)

    out = {
        "schema_version": 1,
        "issue": "SXT-025 (#18)",
        "slug": "hells_bells",
        "path": REL_PATH,
        "census_blob_sha1": blob,
        "compiled_image": os.path.relpath(IMAGE_JSON, REPO),
        "compiled_image_sha256":
            __import__("hashlib").sha256(
                open(os.path.join(REPO, "model", "integration", "preset",
                                  "Hell_s_Bells__e499f78d.image.bin"),
                     "rb").read()).hexdigest(),
        "rev_or_loader": "contributor rev 9 (census stored_revision)",
        "tempo_bpm": tempo if tempo is not None else 120.0,
        "tempo_source": ("tempoOnSave" if tempo is not None
                         else "engine default 120"),
        "volume_f": volume_f,
        "volume_image_scalar": img_vol,
        "volume_note": volume_note,
        "scene_mode": sm,
        "scene_active": sa,
        "drifts_asserted_zero": drifts,
        "scene_sends_f": scene_sends,
        "fx_instances": instances,
        "extraction": {
            "params": "engine getters post-load (normalized, authoritative), "
                      "cross-checked vs the compiled image at the SXT-011 "
                      "6-decimal export rounding (fail-closed)",
            "deactivated_source": "raw fxp XML attribute (surgepy exposure "
                                  "gap; no getter); cross-checked by the "
                                  "fidelity budget",
            "determinism_gate": "scene drift == 0, non-muted oscs retrigger "
                                "on (SXT-012 bit-identical class); the "
                                "fixture render adds the 3x fresh-instance "
                                "bit-identity gate",
        },
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"extracted -> {os.path.relpath(OUT_PATH, REPO)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
