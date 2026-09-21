#!/usr/bin/env python3
"""SXT-026 model-input extractor (requires the external pinned oracle).

Reads the wavetable slice's control-plane inputs for two normalized corpus
presets from the engine after loadPatch (the same authoritative post-loader
state rule as SXT-011/022), applies the DECLARED fixture overrides through
the official surgepy parameter-change path (see fixture_config.py), verifies
every readback, and writes `inputs/<name>.json`:

  * `Kick.fxp` (compiler golden `wavetable-asset`): base, MAX_UNISON=16,
    morph (audibly inert — all 16 Triangle frames are identical, recorded
    finding), keytrack ON pitch-sweep variant;
  * `Monster Feedback.fxp` (compiler golden `four-fx-instance`): the MORPH
    fixture — its `Sampled/Banjo 1.wt` has 15 distinct 128-entry frames, so
    frame interpolation is genuinely exercised; FX instances are set Off via
    the declared dry-bypass and retrigger is forced ON for determinism.

Fail-closed: refuses on census/blob drift, override readback mismatch, or
wavetable asset identity mismatch (sha256 vs the compiled image manifest).
Fixture overrides are declared test configurations, NOT adapted presets;
they never count toward preset coverage.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oracle_common as oc  # noqa: E402
import fixture_config as fc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

GOLDEN = os.path.join(REPO, "compiler", "golden", "compiled")
PRESETS = [
    {
        "name": "kick",
        "preset_rel": fc.PRESET_REL,
        "image_glob": os.path.join(GOLDEN, "wavetable-asset.image.json"),
        "expected": {
            "osc_type": 2.0, "retrigger": 1.0, "playmode": 1.0,
            "drift": 0.0, "width": 0.0, "pan": 0.0,
            "fu0_type": 0.0, "filter_config": 0.0,
        },
        "configs": [
            ("kick-original", [], "unmodified preset state; documented input"),
            ("kick-wtfix", fc.WT_FIX,
             "declared fixture config: WT osc only, filters Off"),
            ("kick-wtfix-uni16", fc.WT_FIX + [("unison", 16)],
             "declared fixture config at MAX_UNISON=16"),
            ("kick-wtfix-morph25", fc.WT_FIX + [("morph", 0.25)],
             "declared fixture config, morph 0.25 (Triangle frames are all "
             "identical: morph is audibly inert on this asset — recorded)"),
            ("kick-wtfix-morph75", fc.WT_FIX + [("morph", 0.75)],
             "declared fixture config, morph 0.75 (audibly inert, as above)"),
            ("kick-wtfix-kt", fc.WT_FIX + [("keytrack", 1), ("octave", 0)],
             "declared fixture config, keytrack ON + osc octave 0: the osc "
             "pitch follows the played note (note + 6.0037 st from the "
             "preset's own pitch param), reaching wavetable mips 5/6"),
        ],
    },
    {
        "name": "mf",
        "preset_rel": fc.PRESET_MF_REL,
        "image_glob": os.path.join(GOLDEN, "four-fx-instance.image.json"),
        "expected": {
            "osc_type": 2.0, "retrigger": 0.0, "drift": 0.0,
            "width": 0.0, "pan": 0.0,
        },
        "configs": [
            ("mf-original", [], "unmodified preset state; documented input"),
            ("mf-wtfix", fc.MF_FIX,
             "declared fixture config: WT osc only, filters + FX Off, "
             "retrigger forced on"),
            ("mf-wtfix-morph25", fc.MF_FIX + [("morph", 0.25)],
             "declared fixture config, morph 0.25: Banjo 1.wt has 15 "
             "distinct frames - frame interpolation genuinely exercised"),
            ("mf-wtfix-morph75", fc.MF_FIX + [("morph", 0.75)],
             "declared fixture config, morph 0.75"),
        ],
    },
]


def wavetable_record(image_glob):
    """The graph's wavetable asset record from the pinned golden image."""
    with open(image_glob, encoding="utf-8") as f:
        img = json.load(f)
    wta = img["body"]["graph"]["wavetable_assets"][0]
    path, sha = wta["res"][0]
    return {"name": wta["name"], "graph_path": path, "sha256": sha,
            "scene": wta["sc"], "osc": wta["osc"], "emb": wta.get("emb")}


def census_blob_sha1(preset_rel):
    import csv

    p = os.path.join(REPO, "corpus", "census-v0.1", "results",
                     "per-preset.csv")
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == preset_rel:
                return row["git_blob_sha1"]
    raise fc.Refuse("preset not in census: %s" % preset_rel)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir",
                    default=os.path.join(os.path.dirname(
                        os.path.abspath(__file__)), "inputs"))
    ap.add_argument("--deform-mode", default="xt14_continuous",
                    choices=["xt14_continuous", "xt134_legacy"],
                    help="morph deform mode (determined empirically; see "
                         "reports/sxt-026/EVIDENCE.md)")
    args = ap.parse_args()

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    os.makedirs(args.out_dir, exist_ok=True)

    for spec in PRESETS:
        rec = wavetable_record(spec["image_glob"])
        for cand in (rec["graph_path"],
                     os.path.join("wavetables", rec["graph_path"])):
            p = os.path.join(oc.data_home(), cand)
            if os.path.isfile(p):
                rec["graph_path_resolved"] = cand.replace(os.sep, "/")
                break
        else:
            raise fc.Refuse("wavetable asset not found under %s: %s"
                            % (oc.data_home(), rec["graph_path"]))
        actual_sha = oc.sha256_file(p)
        if actual_sha != rec["sha256"]:
            raise fc.Refuse("wavetable asset identity mismatch: %s != %s"
                            % (actual_sha, rec["sha256"]))

        preset = fc.preset_abs(oc, spec["preset_rel"])
        blob = oc.git_blob_sha1(preset)
        expected_blob = census_blob_sha1(spec["preset_rel"])
        if blob != expected_blob:
            raise fc.Refuse("preset blob %s != census %s"
                            % (blob, expected_blob))

        base = fc.read_params(fc.build_instance(surgepy, oc, [],
                                                spec["preset_rel"]))
        for k, v in spec["expected"].items():
            if abs(base[k] - v) > 1e-6:
                raise fc.Refuse("%s base state drift: %s = %r (expected %r)"
                                % (spec["name"], k, base[k], v))

        for name, overrides, note in spec["configs"]:
            d = fc.read_params(fc.build_instance(surgepy, oc, overrides,
                                                 spec["preset_rel"]))
            out = {
                "preset_path": spec["preset_rel"],
                "preset_census_blob_sha1": expected_blob,
                "wt_relpath": rec["graph_path_resolved"],
                "wt_sha256": rec["sha256"],
                "wt_name": rec["name"],
                "deform_mode": args.deform_mode,
                "extend_range": True,
                "retrigger": d["retrigger"] > 0.5,
                "octave": int(d["octave"]),
                "scene_octave": int(d["scene_octave"]),
                "keytrack": d["keytrack"] > 0.5,
                "pitch_param": d["pitch_param"],
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
            path = os.path.join(args.out_dir, name + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=1, sort_keys=True)
                f.write("\n")
            print("wrote", path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except fc.Refuse as e:
        print("REFUSING: %s" % e, file=sys.stderr)
        sys.exit(2)
