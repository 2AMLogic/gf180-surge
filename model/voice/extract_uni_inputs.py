#!/usr/bin/env python3
"""SXT-034: extract unison-stack voice inputs for the uni>1 fixtures.

Carrier: `Basses/Attacky.fxp` (the SXT-022 slice preset, census-blob
verified). The declared SXT-034 test configuration applies ONE override
through the official host parameter path - the oscillator unison-voices
parameter (osc p[6], ct_osccount) - read back and recorded; everything else
stays at the preset's own normalized state. This mirrors the SXT-012
declared-override pattern (test configuration on a real corpus carrier;
never an adapted preset, never a coverage claim).

The `nodraw` variant additionally forces the per-oscillator `retrigger`
parameter OFF (SXT-012 diagnostic adaptation class) to exercise the engine's
free-running init formula; the wall-clock-seeded rand_01() draws are NOT
reproducible, so the model input carries DECLARED draw words and no
reference-fidelity claim is possible for that fixture (quantified-variation
class, fixtures/README.md).

Fail-closed: re-verifies the census blob SHA-1, re-checks every SXT-022
voice gate, refuses (exit 2) on any surprise.

Run under the pinned interpreter (auto re-exec via oracle_common).
"""

import argparse
import csv
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

# Declared init-phase draws for the non-retrigger mechanism fixture
# (model input words, Q10.21-quantized once; engine rand_01() is
# wall-clock seeded and not reproducible -- SXT-012 variation class).
DECLARED_DRAWS = [0.10, 0.35, 0.60, 0.85, 0.20, 0.45, 0.70, 0.95]


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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--unison", type=int, required=True,
                    help="declared unison override value (2..16, or 1 to "
                         "re-extract the base state)")
    ap.add_argument("--nodraw", action="store_true",
                    help="additionally force retrigger OFF (mechanism "
                         "fixture; declared init-phase draws, no reference "
                         "claim)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not (1 <= args.unison <= 16):
        raise Refuse(f"unison override {args.unison} outside 1..16")
    if args.unison == 1 and args.nodraw:
        raise Refuse("nodraw with unison 1 is not an SXT-034 fixture")

    ge = graphs_entry(PRESET_REL)
    g = ge["g"]
    preset_abs = os.path.join(oc.data_home(), PRESET_REL[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse(
            "pinned-engine preset not found at %s - set ORACLE_SURGE_DIR to "
            "the pinned engine tree (see oracle/manifest.json); this tool "
            "requires the external oracle" % preset_abs)

    import hashlib
    data = open(preset_abs, "rb").read()
    actual = hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
    expected = census_blob(PRESET_REL)
    if actual != expected:
        raise Refuse(f"blob mismatch: {actual} != census {expected}")

    # --- structural gates (same gate set as the SXT-022 selection search) ---
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
        raise Refuse("filter config not serial1 (unison pan stays inert)")
    if A["ws"]["t"] != 0:
        raise Refuse("waveshaper not off")
    if A["lc"] != -72.0:
        raise Refuse("lowcut not at off value")
    active = [k for k in ("o1", "o2", "o3") if A["mix"][k][1] == 0]
    if active != ["o1"]:
        raise Refuse(f"active mixer paths {active} != ['o1']")
    if A["osc"][0]["t"] != 0:
        raise Refuse("osc1 not Classic")
    if A["fu"][0]["t"] != 1 or A["fu"][1]["t"] != 0:
        raise Refuse("filter units not LP12-active/2-off")

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(preset_abs):
        raise Refuse("loadPatch failed")

    osc1 = s.getPatch()["scene"][0]["osc"][0]
    # --- the declared override (official host parameter path) ---------------
    s.setParamVal(osc1["p"][6], float(args.unison))
    uni_read = int(round(s.getParamVal(osc1["p"][6])))
    if uni_read != args.unison:
        raise Refuse(f"unison override readback {uni_read} != {args.unison}")
    spread_read = float(s.getParamVal(osc1["p"][5]))
    if abs(spread_read - A["osc"][0]["udet"]) > 1e-6:
        raise Refuse(f"spread drifted: {spread_read} != {A['osc'][0]['udet']}")
    retrigger = bool(int(s.getParamVal(osc1["retrigger"])))
    if args.nodraw:
        s.setParamVal(osc1["retrigger"], 0.0)
        retrigger = bool(int(s.getParamVal(osc1["retrigger"])))
        if retrigger:
            raise Refuse("retrigger override did not read back 0")
    elif not retrigger:
        raise Refuse("base preset retrigger unexpectedly off")

    def pv(param):
        return s.getParamVal(param)

    out = {
        "schema_version": 1,
        "issue": "SXT-034",
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
        "unison_override": {
            "declared": True,
            "kind": "test configuration on a real corpus carrier "
                    "(SXT-012 declared-override pattern); never an adapted "
                    "preset, never a coverage claim",
            "param": "scene A osc1 unison voices (osc p[6], ct_osccount), "
                     "set via setParamVal before any audio",
            "value": args.unison,
            "readback": uni_read,
            "spread_left_at_preset_value": spread_read,
            "retrigger": retrigger,
            "init_phase_draws_declared": ([] if retrigger else DECLARED_DRAWS),
        },
        "not_in_graphs": {},
        "graph_echo": {
            "fu0": A["fu"][0],
            # the model reads the unison state from here (override recorded)
            "osc1": dict(A["osc"][0], uni=args.unison, rt=1 if retrigger else 0),
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
    sc = s.getPatch()["scene"][0]
    nii["scene_volume"] = pv(sc["volume"])
    nii["scene_drift"] = pv(sc["drift"])
    for idx, key in ((0, "adsr"), (1, "fadsr")):
        adsr = sc["adsr"][idx]
        nii[key] = {nm: pv(adsr[nm]) for nm in sorted(adsr.keys())}
    lfo1 = sc["lfo"][0]
    nii["lfo1"] = {nm: pv(lfo1[nm]) for nm in sorted(lfo1.keys())}
    nii["osc1_octave"] = pv(sc["osc"][0]["octave"])
    nii["fu0"] = {nm: pv(sc["filterunit"][0][nm]) for nm in sorted(sc["filterunit"][0].keys())}
    nii["character"] = pv(s.getPatch()["character"])
    nii["master_volume"] = pv(s.getPatch()["volume"])
    nii["polylimit"] = pv(s.getPatch()["polylimit"])
    nii["level_o1"] = pv(sc["level_o1"])
    nii["level_pfg"] = pv(sc["level_pfg"])
    nii["pan"] = pv(sc["pan"])
    nii["width"] = pv(sc["width"])
    nii["vca_level"] = pv(sc["vca_level"])
    nii["vca_velsense"] = pv(sc["vca_velsense"])
    nii["lowcut"] = pv(sc["lowcut"])
    nii["portamento"] = pv(sc["portamento"])
    nii["fbc"] = pv(sc["filterblock_configuration"])
    nii["keytrack_root"] = pv(sc["keytrack_root"])
    nii["send_levels"] = [pv(x) for x in sc["send_level"]]

    # fail-closed surprises (SXT-022 gates plus the SXT-034 determinism gate)
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
    print(json.dumps({
        "out": args.out,
        "unison": args.unison,
        "readback": uni_read,
        "retrigger": retrigger,
        "draws_declared": len(DECLARED_DRAWS) if not retrigger else 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
