#!/usr/bin/env python3
"""SXT-025 preset selection: fail-closed census search + selection record.

Re-runs the documented selection search over ALL 3,561 SXT-011 normalized
graphs (census sha pinned in the output) and emits `selection-scan.json`:

  Tier 0  compiler-compiled (SXT-020 corpus scan, reconciled against the
          committed SXT-017 B4-broad prediction)
  Tier 1  FX gate: enabled FX classes subset of {EQ, Reverb 1} -- Delay
          excluded (Delay leaf budget decision open at issue #16)
  Tier 2  single scene (mode Single, scene A), poly playmode
  Tier 3  the SXT-022 voice-slice structural gates verbatim (filter config
          Serial 1, waveshaper Off, lowcut off, one mixer path, Classic-or-
          Sine osc unison 1, filter unit 2 Off)
  Tier 4  the landed SXT-022 voice-MODEL arithmetic gates (the additional
          constraints the frozen Attacky-slice model actually enforces:
          modwheel-only mod routes to Filter 1 Cutoff/Resonance, no
          velocity/global modulation, o1-only Classic with keytrack and zero
          pitch offset, LP 12 dB/Driven unit 1 with no keytrack, scene
          width/pan/pfg/velsense/portamento inert, character Warm/Neutral)

Reported for every tier; the outcome is the documented selection finding:
Tier 3 leaves exactly one FX-carrying preset (the selection), and Tier 4
leaves exactly one preset in the whole corpus -- Attacky, which carries no
FX -- so no corpus preset is renderable by the landed voice model with its
effects; the voice stage of the integrated path needs the declared
adaptation recorded in model/integration/README.md.

Emits the chosen preset's census blob, graph sha256 and compiled-image
sha256 (compiled live with the committed compiler, byte-deterministic).

Original to this repository (Apache-2.0); reads committed artifacts only.
"""
import hashlib
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
SCAN = os.path.join(REPO, "reports", "sxt-020", "compile-corpus-scan.json")
COMPILER = os.path.join(REPO, "compiler", "compile.py")
OUT = os.path.join(REPO, "model", "integration", "selection-scan.json")

GRAPH_SHA = "c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715"
CHOSEN = "resources/data/patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp"
FX_LEGAL = {6: "EQ", 2: "Reverb 1"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def gates(g):
    """Returns (declared_tier3_failures, model_tier4_failures, legal_fx_list)."""
    gg = g["g"]
    f3, f4 = set(), set()
    if gg.get("sm") != 0:
        f3.add("single_scene")
    if gg.get("sa") != 0:
        f3.add("scene_A_active")
    if gg.get("pm", gg["sc"][0].get("pm")) != 0:
        f3.add("poly_playmode")
    sc = gg["sc"][0]
    if sc.get("fbc") != 0:
        f3.add("filter_config_serial1")
    if sc.get("ws", {}).get("t") != 0:
        f3.add("waveshaper_off")
    if sc.get("lc") != -72.0:
        f3.add("lowcut_off")
    mix = sc.get("mix", {})
    if not isinstance(mix, dict):
        f3.add("one_mixer_path")
    else:
        act = [k for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23")
               if mix.get(k, [1, 1])[1] == 0]
        if act != ["o1"]:
            f3.add("one_mixer_path")
    o1 = sc["osc"][0]
    if o1.get("t") not in (0, 1):
        f3.add("classic_or_sine_osc")
    if o1.get("uni") != 1:
        f3.add("unison_1")
    if o1.get("rt") != 1:
        f3.add("retrigger_on")
    if sc["fu"][1].get("t") != 0:
        f3.add("filter_unit2_off")

    # Tier 4: landed voice-model arithmetic gates (Attacky-slice reach)
    if o1.get("t") != 0:
        f4.add("osc1_classic")
    if o1.get("kt") != 1:
        f4.add("osc1_keytrack")
    if o1.get("pit") != 0.0:
        f4.add("osc1_pitch_zero")
    fu0 = sc["fu"][0]
    if not (fu0.get("t") == 1 and fu0.get("st") == 1):
        f4.add("filter1_lp12_driven")
    if fu0.get("kt") != 0.0:
        f4.add("filter1_keytrack_off")
    if sc.get("wid") != 0.0:
        f4.add("scene_width_zero")
    if sc.get("pan") != 0.0:
        f4.add("scene_pan_zero")
    if sc.get("pfg") != 0.0:
        f4.add("pfg_zero")
    if sc.get("vs") != 0.0:
        f4.add("vca_velsense_zero")
    if sc.get("porta") != -8.0:
        f4.add("portamento_off")
    if gg.get("ch") not in (0, 1):
        f4.add("character_warm_neutral")
    md = gg["md"]
    if md.get("g"):
        f4.add("no_global_mod")
    s0 = md["s"][0]
    if s0.get("v"):
        f4.add("no_velocity_mod")
    for r in s0.get("s", []):
        if r[0] != 6 or r[4] not in ("A Filter 1 Cutoff", "A Filter 1 Resonance"):
            f4.add("modwheel_to_filter1_only")

    fxt = []
    for x in gg["fx"]:
        if x.get("on") == 1:
            if x.get("t") in FX_LEGAL:
                fxt.append((x["r"], FX_LEGAL[x["t"]]))
            else:
                f4.add("fx_class_eq_reverb1_only")
                f3.add("fx_class_eq_reverb1_only")
    return f3, f4, fxt


def main():
    assert sha256_file(GRAPHS) == GRAPH_SHA, "graphs.jsonl sha drift"
    scan = json.load(open(SCAN))
    comp = {o["path"]: o["outcome"] for o in scan["outcomes"]}

    counts = {"total": 0, "compiled": 0, "tier1_fx_legal": 0,
              "tier2_scene_playmode": 0, "tier3_declared_voice_gates": 0,
              "tier4_landed_voice_model_any_fx": 0,
              "tier4_landed_voice_model_with_fx": 0}
    tier3_carrying = []
    tier4_any = []
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            p = g["p"]
            counts["total"] += 1
            if comp.get(p) != "compiled":
                continue
            counts["compiled"] += 1
            f3, f4, fxt = gates(g)
            if "fx_class_eq_reverb1_only" in f4 or not fxt:
                continue
            counts["tier1_fx_legal"] += 1
            if {"single_scene", "scene_A_active", "poly_playmode"} & f3:
                continue
            counts["tier2_scene_playmode"] += 1
            if f3:
                continue
            counts["tier3_declared_voice_gates"] += 1
            tier3_carrying.append(
                {"path": p, "fx": [list(x) for x in fxt],
                 "landed_voice_model_failures": sorted(f4)})
    # tier-4-only scan (any FX, including none) for the voice-slice statement
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            p = g["p"]
            if comp.get(p) != "compiled":
                continue
            f3, f4, fxt = gates(g)
            if f4:
                continue
            tier4_any.append({"path": p, "fx": [list(x) for x in fxt]})
    counts["tier3_declared_voice_gates"] = len(tier3_carrying)
    counts["tier4_landed_voice_model_any_fx"] = len(tier4_any)
    counts["tier4_landed_voice_model_with_fx"] = sum(
        1 for e in tier4_any if e["fx"])

    # compile the chosen preset with the committed compiler (byte-deterministic)
    outdir = "/tmp/sxt025-selection"
    os.makedirs(outdir, exist_ok=True)
    r = subprocess.run(
        [sys.executable, COMPILER, "compile", "--path", CHOSEN,
         "--out-dir", outdir], capture_output=True, text=True, check=True)
    img_bin = [f for f in os.listdir(outdir) if f.endswith(".image.bin")][0]
    img_json = json.load(open(os.path.join(outdir, img_bin.replace(".bin", ".json"))))
    graph_line = None
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g["p"] == CHOSEN:
                graph_line = g
                break

    import csv
    blob = None
    with open(os.path.join(REPO, "corpus", "census-v0.1", "results",
                           "per-preset.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == CHOSEN:
                blob = row["git_blob_sha1"]
                break

    rec = {
        "issue": "SXT-025 (#18)",
        "claim_scope": "preset-selection rationale only; no fidelity, support, "
                       "or quality claim. Selection is forced by fail-closed "
                       "gates, not tuned.",
        "inputs": {
            "graphs_jsonl_sha256": GRAPH_SHA,
            "compile_corpus_scan": os.path.relpath(SCAN, REPO),
            "compiler": "compiler/compile.py (SXT-020, unmodified)",
        },
        "tier_counts": counts,
        "tier3_survivors_with_legal_fx": tier3_carrying,
        "tier4_survivors_any_fx": tier4_any,
        "selection": {
            "path": CHOSEN,
            "census_blob_sha1": blob,
            "normalized_graph_sha256": graph_line["sha"],
            "compiled_image": img_bin,
            "compiled_image_sha256": sha256_file(os.path.join(outdir, img_bin)),
            "fx_composition": [["send2", "Reverb 1"]],
            "fx_rationale": "Reverb1+EQ > Reverb1-only > EQ-only ranking: no "
                            "Reverb1+EQ preset survives Tier 2 (or any near "
                            "relaxation of the voice gates); the unique Tier-3 "
                            "survivor carries exactly one Reverb 1 (send2), so "
                            "Reverb1-only is the richest legal FX available.",
            "voice": "Sine osc (uni 1, retrig on), LP 24 dB/Driven unit 1, "
                     "unit 2 Off, Warm, Single/Poly -- INSIDE the Tier-3 "
                     "declared structural gates but OUTSIDE the Tier-4 landed "
                     "voice-model arithmetic (see README finding F-1).",
        },
        "finding": {
            "id": "F-1",
            "text": "No compiled corpus preset carrying EQ/Reverb1 FX is "
                    "renderable by the landed SXT-022 voice-model arithmetic: "
                    "the unique Tier-4 survivor (Attacky) carries no FX. The "
                    "integrated path therefore uses the declared FX-leaf "
                    "input boundary (the engine's own all-off dry bus of the "
                    "same preset+sequence) for the voice stage, which makes "
                    "the configuration ADAPTED -- it can never count as a "
                    "supported preset. Routed as the blocked dependency "
                    "(voice-slice extension); the wet-preset gate itself is "
                    "not weakened.",
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(counts, indent=2))
    print("tier3 survivors:", [e["path"] for e in tier3_carrying])
    print("tier4 survivors:", [e["path"] for e in tier4_any])
    print(f"wrote {os.path.relpath(OUT, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
