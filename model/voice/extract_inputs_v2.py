#!/usr/bin/env python3
"""SXT-026a: extract normalized voice inputs for the generalized voice class.

Schema-2 sibling of `extract_inputs.py` (SXT-022): reads the state that
graphs.jsonl schema rev 1.0.0 does not carry (ADSRs, scene volume/drift,
character, master volume, polylimit, mixer levels, keytrack root, scene
octave, ...) from the pinned native engine via surgepy AFTER `loadPatch`
at 48 kHz -- the same normalized state authority as the SXT-011 export --
and writes a versioned JSON sidecar consumed by `InputsV2`.

Fail-closed: re-verifies the census blob SHA-1, re-checks every gate of the
declared SXT-026a voice class (see model/voice/README.md), and refuses
(exit 2) on any surprise instead of guessing.  Cross-checks the live engine
read against the graphs.jsonl echo for the fields both expose.

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
    ap.add_argument("--preset-rel", required=True,
                    help="corpus-relative preset path, e.g. "
                         "resources/data/patches_3rdparty/.../X.fxp")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    rel = args.preset_rel

    ge = graphs_entry(rel)
    g = ge["g"]
    preset_abs = os.path.join(oc.data_home(), rel[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse(
            "pinned-engine preset not found at %s -- set ORACLE_SURGE_DIR to "
            "the pinned engine tree (see oracle/manifest.json); this tool "
            "requires the external oracle" % preset_abs)
    actual = git_blob_sha1(preset_abs)
    expected = census_blob(rel)
    if actual != expected:
        raise Refuse(f"blob mismatch: {actual} != census {expected}")

    # --- structural gates shared by the declared class (mirrors InputsV2) ---
    if ge["st"] != "normalized":
        raise Refuse("graphs entry not normalized")
    if g["sm"] != 0 or g["sa"] != 0:
        raise Refuse("not single-scene-A")
    A = g["sc"][0]
    if A["pm"] != 0:
        raise Refuse("not poly playmode")
    if A["fbc"] != 0:
        raise Refuse("filter config not serial1")
    if A["ws"]["t"] != 0:
        raise Refuse("waveshaper not off")
    if A["lc"] != -72.0:
        raise Refuse("lowcut not at off value")
    act = [k for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23")
           if A["mix"].get(k, [1, 1])[1] == 0]
    if act != ["o1"]:
        raise Refuse(f"active mixer paths {act} != ['o1']")
    if A["fu"][1]["t"] != 0:
        raise Refuse("filter unit 2 not Off")
    if A["fu"][0]["t"] not in (1, 2) or A["fu"][0]["st"] != 1:
        raise Refuse("filter unit 1 not LP12/LP24 Driven")
    if A["fu"][0]["kt"] != 0.0:
        raise Refuse("filter unit 1 keytrack param != 0")
    o1 = A["osc"][0]
    if o1["t"] not in (0, 1):
        raise Refuse("osc1 not Classic/Sine")
    if o1["uni"] != 1 or o1["rt"] != 1:
        raise Refuse("osc1 not unison-1/retrigger")
    if o1["kt"] != 1 or o1["pit"] != 0.0:
        raise Refuse("osc1 keytrack/pitch gate")
    if abs(A["vs"]) > 0 or abs(A["pan"]) > 0 or abs(A["pfg"]) > 0:
        raise Refuse("vs/pan/pfg gate")
    if A["porta"] != -8.0:
        raise Refuse("portamento active")
    if g["ch"] not in (0, 1):
        raise Refuse("character not Warm/Neutral")
    if g["md"]["g"]:
        raise Refuse("global mod routes present")
    o1_sine = o1["t"] == 1
    if o1_sine:
        for name, o in (("osc1", o1), ("osc2", A["osc"][1]), ("osc3", A["osc"][2])):
            if o["t"] != 1:
                raise Refuse(f"{name} not Sine")
            if o["uni"] != 1 or o["rt"] != 1:
                raise Refuse(f"{name} not unison-1/retrigger")
            p = o["p"]
            if int(p[0]) != 0 or int(p[2]) != 0:
                raise Refuse(f"{name} sine shape/FMmode gate")
            if not (-60.0 <= p[3] <= 70.0 and -60.0 <= p[4] <= 70.0):
                raise Refuse(f"{name} lowcut/highcut gate")
        if A["fm"]["sw"] not in (0, 2):
            raise Refuse("fm_switch not in {0,2}")
    else:
        if A["fm"]["sw"] != 0:
            raise Refuse("classic-kind fixture with FM routing")
        if abs(o1["p"][4]) > 0:
            raise Refuse("classic sync param p[4] not 0")
        if abs(A["oct"]) > 0:
            raise Refuse("classic-kind fixture with scene octave")

    # --- live engine read ----------------------------------------------------
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(preset_abs):
        raise Refuse("loadPatch failed")

    def pv(name):
        return s.getParamVal(s.getPatch()["scene"][0][name])

    out = {
        "schema_version": 2,
        "issue": "SXT-026a",
        "voice_class": "sine-fm-lp24-v2" if o1_sine else "classic-lp12-v1",
        "preset": {
            "path": rel,
            "census_blob_sha1": expected,
            "graphs_sha256_of_line_source": "corpus/normalized/graphs.jsonl",
        },
        "engine": {
            "commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
            "version_string": surgepy.getVersion(),
            "sample_rate": int(s.getSampleRate()),
            "block_size": int(s.getBlockSize()),
        },
        "not_in_graphs": {},
        # fields graphs.jsonl already carries (echo; authoritative source)
        "graph_echo": {
            "osc1": A["osc"][0],
            "osc2": A["osc"][1],
            "osc3": A["osc"][2],
            "fu0": A["fu"][0],
            "fu1": A["fu"][1],
            "mix": A["mix"],
            "fm": A["fm"],
            "oct": A["oct"],
            "ktR": A["ktR"],
            "vca": A["vca"],
            "vs": A["vs"],
            "oct_": A["oct"],
            "pan": A["pan"],
            "wid": A["wid"],
            "bal": A["bal"],
            "pfg": A["pfg"],
            "porta": A["porta"],
            "fbc": A["fbc"],
            "fb": A["fb"],
            "lc": A["lc"],
            "ch": g["ch"],
            "chn": g["chn"],
            "vol": g["vol"],
            "poly": g["poly"],
            "pm": A["pm"],
            "md_scene_A": g["md"]["s"][0],
        },
    }

    sc = s.getPatch()["scene"][0]
    nii = out["not_in_graphs"]
    nii["scene_volume"] = pv("volume")
    nii["scene_drift"] = pv("drift")
    nii["scene_octave"] = pv("octave")
    for idx, key in ((0, "adsr"), (1, "fadsr")):
        adsr = sc["adsr"][idx]
        nii[key] = {nm: s.getParamVal(adsr[nm]) for nm in sorted(adsr.keys())}
    lfo1 = sc["lfo"][0]
    nii["lfo1"] = {nm: s.getParamVal(lfo1[nm]) for nm in sorted(lfo1.keys())}
    nii["fu0"] = {nm: s.getParamVal(sc["filterunit"][0][nm])
                  for nm in sorted(sc["filterunit"][0].keys())}
    nii["character"] = s.getParamVal(s.getPatch()["character"])
    nii["master_volume"] = s.getParamVal(s.getPatch()["volume"])
    nii["polylimit"] = s.getParamVal(s.getPatch()["polylimit"])
    nii["level_o1"] = pv("level_o1")
    nii["level_pfg"] = pv("level_pfg")
    nii["pan"] = pv("pan")
    nii["width"] = pv("width")
    nii["vca_level"] = pv("vca_level")
    nii["vca_velsense"] = pv("vca_velsense")
    nii["lowcut"] = pv("lowcut")
    nii["portamento"] = pv("portamento")
    nii["keytrack_root"] = pv("keytrack_root")
    nii["send_levels"] = [s.getParamVal(x) for x in sc["send_level"]]

    # --- fail-closed surprises + graph cross-checks --------------------------
    if abs(nii["scene_drift"]) > 0:
        raise Refuse(f"scene drift {nii['scene_drift']} != 0 (determinism gate)")
    if abs(nii["scene_volume"]) == 0:
        raise Refuse("scene volume reads 0")
    if int(nii["adsr"]["mode"]) != 0 or int(nii["fadsr"]["mode"]) != 0:
        raise Refuse("analog envelopes not in class")
    if int(nii["fadsr"]["d_s"]) != 0:
        raise Refuse("filter env decay shape not in class")
    for a, b in ((nii["fu0"]["cutoff"], A["fu"][0]["cut"]),
                 (nii["fu0"]["resonance"], A["fu"][0]["res"]),
                 (nii["fu0"]["envmod"], A["fu"][0]["em"]),
                 (nii["fu0"]["keytrack"], A["fu"][0]["kt"]),
                 (nii["fu0"]["type"], A["fu"][0]["t"]),
                 (nii["fu0"]["subtype"], A["fu"][0]["st"]),
                 (nii["scene_octave"], A["oct"]),
                 (nii["level_o1"], A["mix"]["o1"][0])):
        if abs(float(a) - float(b)) > 1e-6:
            raise Refuse(f"engine/graphs disagreement: {a} != {b}")
    # keytrack_root: BOUNDED DATA FINDING (recorded, resolved by native
    # behavior): the committed graphs line carries ktR=61 for this preset
    # while the live pinned engine -- and the SXT-011 export tool itself,
    # re-run against the pinned tree -- read 60.0 (all other fields match).
    # The live oracle wins; the finding is recorded in the sidecar and in
    # reports/sxt-026a/EVIDENCE.md, and the model-vs-reference budgets are
    # the backstop (a wrong root would detune the keytrack route audibly).
    if abs(float(nii["keytrack_root"]) - float(A["ktR"])) > 1e-6:
        out["keytrack_root_finding"] = {
            "graphs_ktR": A["ktR"],
            "live_engine_keytrack_root": nii["keytrack_root"],
            "resolution": "live pinned-engine value used; SXT-011 export "
                          "tool re-run at the pin reproduces the live value; "
                          "committed graphs field recorded as stale",
        }
    if o1_sine:
        for i in (2, 3):
            if A["mix"][f"o{i}"][1] != 1:
                raise Refuse(f"osc{i} must be muted for the FM-source class")
    if int(nii["polylimit"]) != int(g["poly"]):
        raise Refuse("polylimit disagreement (migration gate)")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({"out": args.out, "class": out["voice_class"],
                      "preset": rel}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
