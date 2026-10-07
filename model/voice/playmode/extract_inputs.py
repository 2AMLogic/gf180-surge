#!/usr/bin/env python3
"""SXT-043 fail-closed input extractor for the pm_mono_st_fp leaf.

Reads the state the frozen model needs -- including everything
`corpus/normalized/graphs.jsonl` schema rev 1.0.0 does not carry -- from the
pinned native engine via surgepy AFTER `loadPatch` at 48 kHz, under the
DECLARED fixture configuration (`fixture_config.py`), and writes a versioned
JSON sidecar.

Fail-closed, in this order:
  1. the census blob SHA-1 of the preset on disk must match
     `corpus/census-v0.1/results/per-preset.csv`;
  2. the normalized graph entry must exist and be `normalized`;
  3. every gate of the declared SXT-043 articulation class must hold
     (`Refuse` -> exit 2), INCLUDING scene-A playmode == pm_mono_st_fp;
  4. every declared override must survive readback (`configure_loaded`:
     fixture revision 2 first clears osc-slot p[] routes by original
     parameter identity BEFORE the oscillator type switch, #329);
  5. every live modulation route must be either structurally inert under the
     overrides or inside the declared destination vocabulary;
  6. the live engine read must agree with the graphs.jsonl echo for the
     fields both expose.

Run under the pinned interpreter (auto re-exec via oracle_common).
"""

import argparse
import csv
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402
from refusal import Refuse  # noqa: E402
import fixture_config as fc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

SCHEMA_VERSION = 1
SCHEMA_ID = "sxt-043-playmode-inputs/1"
ENGINE_PIN = "58914e59c608ed4384ba6002e44c3465c58b2e71"
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")

PM_MONO_ST_FP = 4
PLAY_MODE_NAMES = {
    0: "Poly", 1: "Mono", 2: "Mono (Single Trigger)",
    3: "Mono (Fingered Portamento)",
    4: "Mono (Single Trigger & Fingered Portamento)",
    5: "Latch (Monophonic)",
}


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
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def gate_graph(ge, rel):
    """Structural gates read off the normalized graph (pre-override)."""
    g = ge["g"]
    if ge.get("st") != "normalized":
        raise Refuse(f"{rel}: graphs entry not normalized")
    if g["sm"] != 0 or g["sa"] != 0:
        raise Refuse(f"{rel}: not single-scene-A (sm={g['sm']}, sa={g['sa']})")
    A = g["sc"][0]
    if A["pm"] != PM_MONO_ST_FP:
        raise Refuse(
            "%s: scene-A playmode is %d (%s); this leaf freezes ONLY "
            "pm_mono_st_fp (4, %s). Other submodes are separate leaves."
            % (rel, A["pm"], PLAY_MODE_NAMES.get(A["pm"], "?"),
               PLAY_MODE_NAMES[PM_MONO_ST_FP]))
    if A["porta"] <= -8.0:
        raise Refuse(
            "%s: portamento at its minimum (%r) makes the ramp arithmetic "
            "structurally unreachable, so this carrier cannot exercise the "
            "submode's fingered-portamento half" % (rel, A["porta"]))
    if abs(A["po"]) > 0:
        raise Refuse(f"{rel}: scene pitch param {A['po']} != 0")
    if A["pbrD"] != 2 or A["pbrU"] != 2:
        # declared only because the fixtures send no pitch bend; recorded so
        # a later bend-carrying sequence cannot silently inherit this gate
        pass
    return A


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carrier", required=True, choices=sorted(fc.CARRIERS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()

    carrier = args.carrier
    rel = fc.preset_rel(carrier)
    abs_path = fc.preset_abs(oc, carrier)
    if not os.path.exists(abs_path):
        raise Refuse(
            "pinned-engine preset not found at %s -- set ORACLE_SURGE_DIR "
            "(oracle/manifest.json; oracle/fetch-and-build.sh --prebuilt)"
            % abs_path)
    got = git_blob_sha1(abs_path)
    want = census_blob(rel)
    if got != want:
        raise Refuse(f"{rel}: blob {got} != census {want}")

    ge = graphs_entry(rel)
    A = gate_graph(ge, rel)

    s, d, routes = fc.build_instance(surgepy, oc, carrier)
    try:
        nonparam = fc.read_nonparam_mono_config(s)
    finally:
        # release the instance BEFORE the A/B probe builds its own: holding
        # several live engine instances at once is not a supported surgepy
        # usage and segfaults on this build
        del s
    cuts = fc.probe_cut_activation(surgepy, oc, carrier)

    # ---- post-override gates on the live engine read -----------------
    if d["polymode"] != PM_MONO_ST_FP:
        raise Refuse(f"{rel}: engine polymode {d['polymode']} != 4")
    if d["adsr"]["mode"] != 0:
        raise Refuse(f"{rel}: analog amp envelope not in the frozen slice")
    if int(d["adsr"]["d_s"]) != 0 or int(d["adsr"]["a_s"]) != 1:
        raise Refuse(
            "%s: amp envelope shapes (a_s=%d, d_s=%d) outside the frozen "
            "SXT-022 digital slice (a_s=1, d_s=0)"
            % (rel, int(d["adsr"]["a_s"]), int(d["adsr"]["d_s"])))
    if d["portamento_temposync"]:
        raise Refuse(f"{rel}: portamento temposync is outside the declared "
                     "class (tempo is pinned at 120 and not swept here)")
    if d["portamento_options"]["retrigger"]:
        raise Refuse(
            "%s: porta_retrigger re-triggers the OSCILLATOR mid-glide, which "
            "is outside this leaf's declared audio slice (the ramp-state "
            "half IS modeled and is exercised by the declared corner probe)"
            % rel)
    if d["portamento"] <= d["portamento_min"]:
        raise Refuse(f"{rel}: portamento at val_min: ramp unreachable")
    if not (d["portamento_min"] <= d["portamento"] <= d["portamento_max"]):
        raise Refuse(f"{rel}: portamento outside engine-declared range")
    if nonparam["mono_voice_priority_mode"] not in (0, 1, 2, 3):
        raise Refuse(f"{rel}: monoVoicePriorityMode outside the pinned enum")
    if nonparam["mono_voice_envelope_mode"] not in (0, 1):
        raise Refuse(f"{rel}: monoVoiceEnvelopeMode outside the pinned enum")
    if d["character"] not in (0, 1):
        raise Refuse(f"{rel}: character {d['character']} not Warm/Neutral")
    if abs(d["width"]) > 1.0 + 1e-9:
        raise Refuse(f"{rel}: scene width out of range")
    if d["polylimit"] < 1:
        raise Refuse(f"{rel}: polylimit {d['polylimit']} < 1")

    # ---- cross-check live engine read vs the graphs.jsonl echo --------
    echo = [
        ("scene_octave", d["scene_octave"], A["oct"]),
        ("polymode", d["polymode"], A["pm"]),
        ("portamento", round(d["portamento"], 5), round(A["porta"], 5)),
        ("pan", round(d["pan"], 5), round(A["pan"], 5)),
        ("vca_db", round(d["vca_db"], 5), round(A["vca"], 5)),
        ("vca_velsense", round(d["vca_velsense"], 5), round(A["vs"], 5)),
        ("keytrack_root", 60, A["ktR"]),
    ]
    for name, got_v, want_v in echo:
        if isinstance(got_v, float) or isinstance(want_v, float):
            if abs(float(got_v) - float(want_v)) > 1e-4:
                raise Refuse(f"{rel}: engine/graphs mismatch {name}: "
                             f"{got_v} != {want_v}")
        elif int(got_v) != int(want_v):
            raise Refuse(f"{rel}: engine/graphs mismatch {name}: "
                         f"{got_v} != {want_v}")

    out = {
        "schema_version": SCHEMA_VERSION,
        "schema": SCHEMA_ID,
        "leaf": "SXT-043",
        "issue": 77,
        "engine_pin": "surge-synthesizer/surge@" + ENGINE_PIN,
        "sample_rate": 48000,
        "carrier": carrier,
        "preset_path": rel,
        "preset_census_blob_sha1": want,
        "graphs_sha": ge.get("sha"),
        "slot": fc.CARRIERS[carrier][1],
        "play_mode": {"id": d["polymode"],
                      "name": PLAY_MODE_NAMES[d["polymode"]]},
        "portamento": {
            "value": d["portamento"],
            "val_min": d["portamento_min"],
            "val_max": d["portamento_max"],
            "options": d["portamento_options"],
            "temposync": d["portamento_temposync"],
        },
        "mono_voice_priority_mode": nonparam["mono_voice_priority_mode"],
        "mono_voice_envelope_mode": nonparam["mono_voice_envelope_mode"],
        "poly_voice_repeated_key_mode":
            nonparam["poly_voice_repeated_key_mode"],
        "declared_overrides": fc.OVERRIDE_KEYS,
        "fixture_revision": fc.FIXTURE_REVISION,
        "modulation_routes": routes,
        "osc_cut_activation_probe": cuts,
        # audio-stage words (post-override; the landed Sine slice reads these)
        "osc_type": d["osc_type"],
        "octave": d["octave"],
        "scene_octave": d["scene_octave"],
        "keytrack": d["keytrack"],
        "pitch_param": d["pitch_param"],
        "pitch_extend": d["pitch_extend"],
        "retrigger": d["retrigger"],
        "shape": d["shape"],
        "fb": d["fb"],
        "fb_extend": d["fb_extend"],
        "fmmode": d["fmmode"],
        "lowcut": d["lowcut"],
        "highcut": d["highcut"],
        "unison_detune": d["unison_detune"],
        "extend_detune": d["extend_detune"],
        "absolute_detune": d["absolute_detune"],
        "unison": d["unison"],
        "character": d["character"],
        "drift": d["drift"],
        "o_level": d["o_level"],
        "level_pfg": d["level_pfg"],
        "pan": d["pan"],
        "width": d["width"],
        "scene_volume": d["scene_volume"],
        "vca_db": d["vca_db"],
        "vca_velsense": d["vca_velsense"],
        "master_db": d["master_db"],
        "polylimit": d["polylimit"],
        "adsr": d["adsr"],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({"carrier": carrier, "out": args.out,
                      "fixture_revision": fc.FIXTURE_REVISION,
                      "osc_p_routes_cleared": len(
                          routes["osc_p_route_clear"]["cleared"]),
                      "play_mode": out["play_mode"],
                      "portamento": out["portamento"],
                      "mono_voice_priority_mode":
                          out["mono_voice_priority_mode"],
                      "mono_voice_envelope_mode":
                          out["mono_voice_envelope_mode"],
                      "osc_cuts_deactivated": [
                          cuts["lowcut_deactivated"],
                          cuts["highcut_deactivated"]],
                      "live_routes": len(routes["live"]),
                      "inert_routes": len(routes["inert"]),
                      "pinned_routes": len(routes["pinned"])}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSED (outside declared SXT-043 class): {e}",
              file=sys.stderr)
        sys.exit(2)
