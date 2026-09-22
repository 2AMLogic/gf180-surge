#!/usr/bin/env python3
"""SXT-032: extract the LFO-slice inputs for `Basses/Attacky.fxp` + the
declared runtime modulation routes.

graphs.jsonl (SXT-011, schema rev 1.0.0) does not carry LFO definition
state. The frozen SXT-032 model needs it, so this script reads it from the
pinned native engine via surgepy AFTER `loadPatch` at 48 kHz (the same
normalized-state authority as SXT-011) and writes a versioned JSON sidecar
consumed by `model/voice/run_lfo_model.py`.

The SXT-032 reference fixture is the landed SXT-022 voice-slice preset
(Attacky, census-blob verified) PLUS two modulation routes added at runtime
through the engine's own host modulation API (`setModDepth01`):
    LFO1 (ms_lfo1) -> A Filter 1 Cutoff      normalized depth 0.5
    LFO1 (ms_lfo1) -> A Filter 1 Resonance   normalized depth 0.5
The added routes are an explicitly declared synthetic fixture (the preset
file itself is untouched); the engine render of this configuration is the
oracle reference for the leaf. The resulting depths are read back from
`getModDepth01` (engine-authoritative) and recorded in the sidecar.

Fail-closed: re-verifies the census blob SHA-1, re-checks the SXT-022
structural gates, and refuses (exit 2) on any surprise instead of guessing:
shapes outside the frozen waveform set, deform != 0 on type_3 shapes,
lm_random trigger, routes targeting LFO parameters, or pre-existing preset
routings from voice LFOs 2..6.

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
GRAPHS = os.path.join(REPO, "corpus/normalized/graphs.jsonl")
ROUTE_CUTOFF_F01 = 0.5
ROUTE_RESO_F01 = 0.5
FROZEN_SHAPES = (0, 1, 2, 3)          # sine, tri, square, ramp
N_VOICE_LFOS = 6


class Refuse(Exception):
    pass


def census_blob(rel):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def git_blob_sha1(path):
    import zlib

    data = open(path, "rb").read()
    hdr = b"blob %d\x00" % len(data)
    return hashlib.sha1(hdr + data).hexdigest()


def graphs_modwheel_routes(rel):
    """The preset's own normalized modwheel routes (SXT-022 reuse)."""
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel:
                routes = {}
                for r in g["g"]["md"]["s"][0]["s"]:
                    if r[4] == "A Filter 1 Cutoff":
                        routes["cutoff_depth"] = r[5]
                    elif r[4] == "A Filter 1 Resonance":
                        routes["reso_depth"] = r[5]
                return routes
    raise Refuse("preset not found in graphs.jsonl")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(REPO, "model", "voice",
                                                  "attacky_lfo_inputs.json"))
    args = ap.parse_args()

    preset_abs = os.path.join(oc.data_home(), PRESET_REL[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse(
            "pinned-engine preset not found at %s — set ORACLE_SURGE_DIR to "
            "the pinned engine tree (see oracle/manifest.json); this tool "
            "requires the external oracle" % preset_abs)

    actual = git_blob_sha1(preset_abs)
    expected = census_blob(PRESET_REL)
    if actual != expected:
        raise Refuse(f"blob mismatch: {actual} != census {expected}")

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    import surgepy.constants as C

    s = surgepy.createSurge(48000.0)
    try:
        if not s.loadPatch(preset_abs):
            raise Refuse("loadPatch failed")

        g = s.getPatch()
        sc = g["scene"][0]

        # --- structural gates (SXT-022 slice) --------------------------------
        for slot in range(16):
            if int(s.getParamVal(g["fx"][slot]["type"])) != C.fxt_off:
                raise Refuse(f"fx slot {slot} not Off")
        if int(s.getParamVal(sc["polymode"])) != 0:
            raise Refuse("not poly playmode")
        if int(s.getParamVal(sc["filterblock_configuration"])) != 0:
            raise Refuse("filter config not serial1")
        if int(s.getParamVal(sc["wsunit"]["type"])) != 0:
            raise Refuse("waveshaper not off")
        if abs(float(s.getParamVal(sc["lowcut"])) + 72.0) > 0:
            raise Refuse("lowcut not at off value")
        if int(s.getParamVal(sc["osc"][0]["type"])) != 0 \
                or int(s.getParamVal(sc["osc"][0]["unison"])) != 1 \
                or int(s.getParamVal(sc["osc"][0]["retrigger"])) != 1:
            raise Refuse("osc1 not Classic/unison1/retrigger")
        if abs(float(s.getParamVal(sc["drift"]))) > 0:
            raise Refuse("scene drift not 0 (determinism gate)")

        # --- pre-existing voice-LFO routings must be empty for this fixture -
        base_routes = s.getAllModRoutings()
        for scene_row in base_routes["scene"]:
            for r in scene_row["voice"]:
                src = r.getSource().getModSource()
                if 17 + 1 <= src <= 17 + N_VOICE_LFOS:
                    raise Refuse(
                        f"preset already routes voice LFO {src - 17 + 1}; "
                        "the isolated fixture requires a clean LFO slate")

        # --- LFO definitions (fail-closed gates) -----------------------------
        lfos = []
        for li in range(N_VOICE_LFOS):
            d = {nm: s.getParamVal(p) for nm, p in sc["lfo"][li].items()}
            shape = int(d["shape"])
            if shape not in FROZEN_SHAPES:
                raise Refuse(f"LFO{li + 1} shape {shape} outside the frozen "
                             "waveform set")
            if shape in (0, 1, 3) and float(d["deform"]) != 0.0:
                raise Refuse(f"LFO{li + 1} deform {d['deform']} on a type_3 "
                             "shape is outside the frozen slice")
            if int(d["trigmode"]) == 2:
                raise Refuse(f"LFO{li + 1} trigmode lm_random (engine RNG)")
            lfos.append({k: (int(v) if k in ("shape", "trigmode", "unipolar")
                             else float(v)) for k, v in sorted(d.items())})

        # --- add the declared fixture routes (host modulation API) -----------
        routes = []
        for dest_key, f01 in (("cutoff", ROUTE_CUTOFF_F01),
                              ("resonance", ROUTE_RESO_F01)):
            target = sc["filterunit"][0][dest_key]
            ms = s.getModSource(C.ms_lfo1)
            if not s.isValidModulation(target, ms):
                raise Refuse(f"modulation LFO1 -> fu1 {dest_key} invalid")
            s.setModDepth01(target, ms, f01, 0, 0)
            depth01 = s.getModDepth01(target, ms, 0, 0)
            if abs(depth01 - f01) > 1e-6:
                raise Refuse(f"route depth readback {depth01} != {f01}")
            routes.append({"dest": f"filterunit0_{dest_key}",
                           "dest_param": dest_key,
                           "modsource": "ms_lfo1", "modsource_id": 17,
                           "normalized_depth": f01,
                           "depth_readback": depth01})

        # no route may target an LFO parameter (destination class gate);
        # (re-read after the adds: only our two routes must exist)
        after = s.getAllModRoutings()
        voc = after["scene"][0]["voice"]
        if len(voc) != 2:
            raise Refuse(f"expected exactly 2 voice routes, got {len(voc)}")
        raw_by_dest = {}
        for r in voc:
            if r.getSource().getModSource() != C.ms_lfo1:
                raise Refuse("unexpected non-LFO1 voice route")
            raw_by_dest[r.getDest().name] = r.getDepth()
        for entry in routes:
            dest_name = ("A Filter 1 Cutoff" if entry["dest"].endswith("cutoff")
                         else "A Filter 1 Resonance")
            if dest_name not in raw_by_dest:
                raise Refuse(f"route readback missing for {dest_name}")
            entry["dest_name"] = dest_name
            entry["depth_raw"] = raw_by_dest[dest_name]
        if set(raw_by_dest) != {"A Filter 1 Cutoff", "A Filter 1 Resonance"}:
            raise Refuse(f"unexpected route destinations: {sorted(raw_by_dest)}")

        out = {
            "schema_version": 1,
            "issue": "SXT-032",
            "preset": {
                "path": PRESET_REL,
                "census_blob_sha1": expected,
                "actual_blob_sha1": actual,
            },
            "engine": {
                "commit": "58914e59c608ed4384ba6002e44c3465c58b2e71",
                "version_string": surgepy.getVersion(),
                "sample_rate": int(s.getSampleRate()),
                "block_size": int(s.getBlockSize()),
            },
            "fixture_routes": routes,
            "preset_modwheel_routes": graphs_modwheel_routes(PRESET_REL),
            "lfo_defs": lfos,
            "frozen_scope": {
                "waveforms": "sine(deform=0), tri(deform=0), square, "
                             "ramp(deform=0)",
                "destination_classes": ["A Filter 1 Cutoff",
                                        "A Filter 1 Resonance"],
                "trigmodes": ["freerun(songpos=0)", "keytrigger"],
                "gaps": [
                    "rate temposync / deactivated flags not observable via "
                    "surgepy; frozen model implements non-temposync, "
                    "non-deactivated paths",
                    "step-sequencer grids outside normalized schema rev 1.0.0",
                    "MSEG/Formula contents not exposed by surgepy",
                    "noise/snh shapes consume engine RNG (nondeterministic)",
                    "lt_envelope and type_3 deform bends need runtime sin",
                ],
            },
        }

        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, sort_keys=True)
            f.write("\n")
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0
    finally:
        del s


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
