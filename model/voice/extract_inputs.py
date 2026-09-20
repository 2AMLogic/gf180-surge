#!/usr/bin/env python3
"""SXT-022: extract the complete normalized voice inputs for `Basses/Attacky.fxp`.

graphs.jsonl (SXT-011) deliberately excludes envelope (ADSR) values, scene
volume/drift, and LFO envelope/deform sub-parameters (schema rev 1.0.0 scope
note). The frozen fixed-point model needs them, so this script reads them
from the pinned native engine via surgepy AFTER `loadPatch` at 48 kHz - the
same normalized state authority as the SXT-011 export - and writes a
versioned JSON sidecar consumed by `model/voice/voice_model.py`.

The script is fail-closed: it re-verifies the census blob SHA-1, re-checks
every gate that the SXT-022 preset-selection search assumed (single scene,
no FX, one active Classic oscillator, LP 12 dB filter, no waveshaper,
poly playmode), and refuses (exit 2) on any surprise instead of guessing.

Run under the pinned interpreter (auto re-exec via oracle_common).
"""

import argparse
import csv
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")


class Refuse(Exception):
    pass


def census_blob(rel):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def graphs_entry(rel):
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel:
                return g
    raise Refuse(f"preset not in graphs.jsonl: {rel}")


def git_blob_sha1(path):
    import struct
    import zlib

    data = open(path, "rb").read()
    hdr = b"blob %d\x00" % len(data)
    return hashlib.sha1(hdr + data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(REPO, "model", "voice", "attacky_inputs.json"))
    args = ap.parse_args()

    ge = graphs_entry(PRESET_REL)
    g = ge["g"]
    preset_abs = os.path.join(oc.data_home(), PRESET_REL[len("resources/data/") :])

    actual = git_blob_sha1(preset_abs)
    expected = census_blob(PRESET_REL)
    if actual != expected:
        raise Refuse(f"blob mismatch: {actual} != census {expected}")

    # --- structural gates assumed by the SXT-022 selection search ------------
    if ge["st"] != "normalized":
        raise Refuse("graphs entry not normalized")
    if g["sm"] != 0 or g["sa"] != 0:
        raise Refuse("not single-scene")
    if any(f["t"] != 0 for f in g["fx"]):
        raise Refuse("preset has FX")
    A = g["sc"][0]
    if A["pm"] != 0:
        raise Refuse("not poly playmode")
    if A["fbc"] != 0:
        raise Refuse("filter config not serial1")
    if A["ws"]["t"] != 0:
        raise Refuse("waveshaper not off")
    if A["lc"] != -72.0:
        raise Refuse("lowcut not at off value")
    active = [k for k in ("o1", "o2", "o3") if A["mix"][k][1] == 0]
    if active != ["o1"]:
        raise Refuse(f"active mixer paths {active} != ['o1']")
    if A["osc"][0]["t"] != 0 or A["osc"][0]["uni"] != 1 or A["osc"][0]["rt"] != 1:
        raise Refuse("osc1 not Classic/unison1/retrigger")
    if A["fu"][0]["t"] != 1 or A["fu"][1]["t"] != 0:
        raise Refuse("filter units not LP12-active/2-off")

    # --- live engine read ----------------------------------------------------
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    import surgepy.constants as C

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(preset_abs):
        raise Refuse("loadPatch failed")

    def pv(name):
        return s.getParamVal(s.getPatch()["scene"][0][name])

    def pvi(name):
        return int(s.getParamVal(s.getPatch()["scene"][0][name]))

    out = {
        "schema_version": 1,
        "issue": "SXT-022",
        "preset": {
            "path": PRESET_REL,
            "census_blob_sha1": expected,
            "graphs_sha256_of_line_source": "corpus/normalized/graphs.jsonl",
        },
        "engine": {
            "commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
            "version_string": surgepy.getVersion(),
            "sample_rate": int(s.getSampleRate()),
            "block_size": int(s.getBlockSize()),
        },
        # fields missing from graphs.jsonl schema rev 1.0.0 (documented there)
        "not_in_graphs": {},
        "graph_echo": {
            "fu0": A["fu"][0],
            "osc1": A["osc"][0],
            "mix": A["mix"],
            "vca": A["vca"],
            "vs": A["vs"],
            "oct": A["oct"],
            "pan": A["pan"],
            "wid": A["wid"],
            "pfg": A["pfg"],
            "porta": A["porta"],
            "fbc": A["fbc"],
            "fb": A["fb"],
            "bal": A["bal"],
            "lc": A["lc"],
            "ch": g["ch"],
            "chn": g["chn"],
            "vol": g["vol"],
            "poly": g["poly"],
            "pm": A["pm"],
            "md_scene_A": g["md"]["s"][0],
        },
    }

    nii = out["not_in_graphs"]

    def obj(param):
        return s.getParamVal(param)

    sc = s.getPatch()["scene"][0]
    nii["scene_volume"] = obj(sc["volume"])
    nii["scene_drift"] = obj(sc["drift"])
    for idx, key in ((0, "adsr"), (1, "fadsr")):
        adsr = sc["adsr"][idx]
        nii[key] = {nm: obj(adsr[nm]) for nm in sorted(adsr.keys())}
    lfo1 = sc["lfo"][0]
    nii["lfo1"] = {nm: obj(lfo1[nm]) for nm in sorted(lfo1.keys())}
    nii["osc1_octave"] = obj(sc["osc"][0]["octave"])
    nii["fu0"] = {nm: obj(sc["filterunit"][0][nm]) for nm in sorted(sc["filterunit"][0].keys())}
    nii["character"] = obj(s.getPatch()["character"])
    nii["master_volume"] = obj(s.getPatch()["volume"])
    nii["polylimit"] = obj(s.getPatch()["polylimit"])
    nii["level_o1"] = obj(sc["level_o1"])
    nii["level_pfg"] = obj(sc["level_pfg"])
    nii["pan"] = obj(sc["pan"])
    nii["width"] = obj(sc["width"])
    nii["vca_level"] = obj(sc["vca_level"])
    nii["vca_velsense"] = obj(sc["vca_velsense"])
    nii["lowcut"] = obj(sc["lowcut"])
    nii["portamento"] = obj(sc["portamento"])
    nii["fbc"] = obj(sc["filterblock_configuration"])
    nii["keytrack_root"] = obj(sc["keytrack_root"])
    nii["send_levels"] = [obj(x) for x in sc["send_level"]]

    # fail-closed surprises
    if abs(nii["scene_drift"]) > 0:
        raise Refuse(f"scene drift is {nii['scene_drift']}, expected 0 (determinism gate)")
    if abs(nii["scene_volume"]) == 0:
        raise Refuse("scene volume reads 0")
    if abs(A["osc"][0]["p"][4]) > 0:
        raise Refuse("classic sync param p[4] not 0")
    if abs(nii["lfo1"]["deform"]) > 0:
        raise Refuse(f"lfo1 deform not 0: {nii['lfo1']['deform']}")
    if int(nii["adsr"]["mode"]) != 0:
        raise Refuse(f"amp env not in digital mode: {nii['adsr']['mode']}")
    if int(nii["fadsr"]["mode"]) != 0:
        raise Refuse(f"filter env not in digital mode: {nii['fadsr']['mode']}")
    if abs(A["fm"]["sw"]) != 0:
        raise Refuse("FM switch not off")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
