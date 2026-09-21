#!/usr/bin/env python3
"""SXT-026 model-input extractor (requires the external pinned oracle).

Reads the wavetable slice's control-plane inputs for the normalized corpus
preset `resources/data/patches_3rdparty/Argitoth/Drums/Kick.fxp` from the
engine after loadPatch (the same authoritative post-loader state rule as
SXT-011/022), applies the DECLARED fixture overrides through the official
surgepy parameter-change path (setParamVal, like the SXT-012 dry-bypass
mechanism), verifies every readback, and writes `inputs/<name>.json`.

Fail-closed: refuses on census/blob drift, override readback mismatch, or
wavetable asset identity mismatch (sha256 vs the compiled image manifest).

The fixture overrides exist to isolate the WAVETABLE oscillator slice for
model-vs-reference budget checks; they are declared test configurations,
NOT adapted presets, and never count toward preset coverage. The unmodified
preset's own wet reference is also rendered (see tools/render_wt_reference.py).
"""

import argparse
import glob
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

PRESET_REL = "resources/data/patches_3rdparty/Argitoth/Drums/Kick.fxp"
IMAGE_GLOB = os.path.join(REPO, "compiler", "golden", "compiled",
                          "wavetable-asset.image.json")


class Refuse(Exception):
    pass


def wavetable_record():
    """The graph's wavetable asset record from the pinned golden image."""
    with open(IMAGE_GLOB, encoding="utf-8") as f:
        img = json.load(f)
    wta = img["body"]["graph"]["wavetable_assets"][0]
    path, sha = wta["res"][0]
    return {"name": wta["name"], "graph_path": path, "sha256": sha,
            "scene": wta["sc"], "osc": wta["osc"],
            "emb": wta.get("emb")}


def census_blob_sha1():
    import csv

    p = os.path.join(REPO, "corpus", "census-v0.1", "results",
                     "per-preset.csv")
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == PRESET_REL:
                return row["git_blob_sha1"]
    raise Refuse("preset not in census: %s" % PRESET_REL)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "inputs"))
    ap.add_argument("--deform-mode", default="xt14_continuous",
                    choices=["xt14_continuous", "xt134_legacy"],
                    help="morph deform mode (determined empirically; see "
                         "reports/sxt-026/EVIDENCE.md)")
    args = ap.parse_args()

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    rec = wavetable_record()
    # graph res paths are recorded root-relative ("Basic/Triangle.wt");
    # the payload lives under wavetables/ of the data home
    for cand in (rec["graph_path"],
                 os.path.join("wavetables", rec["graph_path"])):
        p = os.path.join(oc.data_home(), cand)
        if os.path.isfile(p):
            asset_abs = p
            rec["graph_path_resolved"] = cand.replace(os.sep, "/")
            break
    else:
        raise Refuse("wavetable asset not found under %s: %s"
                     % (oc.data_home(), rec["graph_path"]))
    actual_sha = oc.sha256_file(asset_abs)
    if actual_sha != rec["sha256"]:
        raise Refuse("wavetable asset identity mismatch: %s != %s"
                     % (actual_sha, rec["sha256"]))

    preset_abs = os.path.join(oc.engine_dir(), PRESET_REL)
    blob = oc.git_blob_sha1(preset_abs)
    expected_blob = census_blob_sha1()
    if blob != expected_blob:
        raise Refuse("preset blob %s != census %s" % (blob, expected_blob))

    # base parameter read (no overrides)
    def read_params(s):
        sc = s.getPatch()["scene"][0]
        o = sc["osc"][1]
        p = {k: s.getParamVal(o["p"][k]) for k in range(7)}
        return {
            "osc_type": s.getParamVal(o["type"]),
            "octave": s.getParamVal(o["octave"]),
            "keytrack": s.getParamVal(o["keytrack"]),
            "retrigger": s.getParamVal(o["retrigger"]),
            "morph": p[0], "skewv": p[1], "saturate": p[2], "formant": p[3],
            "skewh": p[4], "unison_detune": p[5], "unison": p[6],
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

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(preset_abs):
        raise Refuse("loadPatch failed")
    base = read_params(s)
    del s

    expected = {
        "osc_type": 2.0, "retrigger": 1.0, "playmode": 1.0,
        "drift": 0.0, "width": 0.0, "pan": 0.0,
        "fu0_type": 0.0, "filter_config": 0.0,
    }
    for k, v in expected.items():
        if abs(base[k] - v) > 1e-6:
            raise Refuse("preset base state drift: %s = %r (expected %r)"
                         % (k, base[k], v))
    if base["unison_detune"] != base["unison_detune"]:  # NaN guard
        raise Refuse("NaN detune")

    def inputs(name, overrides, note):
        s = surgepy.createSurge(48000.0)
        try:
            if not s.loadPatch(preset_abs):
                raise Refuse("loadPatch failed")
            sc = s.getPatch()["scene"][0]
            applied = {}
            for key, val in overrides:
                if key == "mute_o1":
                    s.setParamVal(sc["mute_o1"], 1.0)
                    applied["mute_o1"] = 1.0
                elif key == "mute_noise":
                    s.setParamVal(sc["mute_noise"], 1.0)
                    applied["mute_noise"] = 1.0
                elif key == "fu1_off":
                    # filter unit Off == fut_none == 0
                    s.setParamVal(sc["filterunit"][1]["type"], 0.0)
                    applied["fu1_type"] = 0.0
                elif key == "unison":
                    s.setParamVal(sc["osc"][1]["p"][6], float(val))
                    applied["unison"] = float(val)
                elif key == "morph":
                    s.setParamVal(sc["osc"][1]["p"][0], float(val))
                    applied["morph"] = float(val)
                elif key == "octave":
                    s.setParamVal(sc["osc"][1]["octave"], float(val))
                    applied["octave"] = float(val)
                else:
                    raise Refuse("unknown override %r" % key)
            d = read_params(s)
            if os.environ.get("SXT026_DEBUG"):
                print("DEBUG post-override:", {k: d[k] for k in
                                               ("mute_o1", "mute_noise",
                                                "fu1_type", "unison",
                                                "morph")}, file=sys.stderr)
            # verify readbacks of exactly the applied overrides
            for k, v in applied.items():
                if abs(d[k] - v) > 1e-6:
                    raise Refuse("override readback failed: %s = %r" % (k, d[k]))
            out = {
                "preset_path": PRESET_REL,
                "preset_census_blob_sha1": expected_blob,
                "wt_relpath": rec["graph_path_resolved"],
                "wt_sha256": rec["sha256"],
                "wt_name": rec["name"],
                "deform_mode": args.deform_mode,
                "extend_range": True,
                "retrigger": d["retrigger"] > 0.5,
                "octave": int(d["octave"]),
                "unison": int(round(d["unison"])),
                "morph": d["morph"], "skewv": d["skewv"],
                "saturate": d["saturate"], "formant": d["formant"],
                "skewh": d["skewh"], "unison_detune": d["unison_detune"],
                "o2_level": d["o2_level"],
                "scene_volume": d["scene_volume"],
                "vca_db": d["vca_db"],
                "vca_velsense": d["vca_velsense"],
                "master_db": d["master_db"],
                "adsr": {k: d["adsr"][k] for k in
                         ("a", "d", "s", "r", "a_s", "d_s", "r_s", "mode")},
                "declared_overrides": [list(o) for o in overrides],
                "note": note,
                "engine_version": surgepy.getVersion(),
                "unison_cap": 16,
            }
            os.makedirs(args.out_dir, exist_ok=True)
            path = os.path.join(args.out_dir, name + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=1, sort_keys=True)
                f.write("\n")
            print("wrote", path)
        finally:
            del s

    # The original preset state (no overrides) — reference documentation of
    # the extracted values; audio from this config is NOT model-compared
    # (the slice does not model the sine osc or noise generator).
    inputs("kick-original", [], "unmodified preset state; documented input")

    # Declared WT-validation fixture configuration: mute the sine osc and
    # the noise generator, set both filter units to Off. The WT osc then
    # drives the whole documented slice (osc -> level -> AEG -> out).
    WT_FIX = [("mute_o1", 1), ("mute_noise", 1), ("fu1_off", 1)]
    inputs("kick-wtfix", WT_FIX,
           "declared fixture config: WT osc only, filters Off")
    inputs("kick-wtfix-uni16", WT_FIX + [("unison", 16)],
           "declared fixture config at MAX_UNISON=16")
    inputs("kick-wtfix-morph25", WT_FIX + [("morph", 0.25)],
           "declared fixture config, morph 0.25 (frame interpolation active)")
    inputs("kick-wtfix-morph75", WT_FIX + [("morph", 0.75)],
           "declared fixture config, morph 0.75")
    inputs("kick-wtfix-oct0", WT_FIX + [("octave", 0)],
           "declared fixture config, osc octave 0 (reaches wavetable mips "
           "5/6 at the top of the MIDI range; the stored -3 octave caps "
           "the reachable osc pitch at 91)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print("REFUSING: %s" % e, file=sys.stderr)
        sys.exit(2)
