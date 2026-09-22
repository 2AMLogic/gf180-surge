#!/usr/bin/env python3
"""SXT-035: extract the scene-modwheel fixture inputs for the declared
synthetic carrier (factory `Basses/Attacky.fxp`, census-blob verified, the
landed SXT-022 voice-slice preset).

The leaf's named carrier presets (Rainy Day Dreamaway, Pluck 2 Pad Demon
Sad, Alone) are outside the landed voice class (see reports/sxt-035/), so —
per the SXT-032 sibling convention — the reference fixture is Attacky PLUS
one modulation route added at runtime through the engine's host modulation
API: ms_modwheel -> scene A `vca_level` ("A VCA Gain", normalized depth
0.4). Attacky's own preset modwheel routes (Filter 1 Cutoff / Resonance)
remain active in both the engine render and the model; the runtime route
exercises the new destination class.

The extractor:
  1. re-verifies the census blob SHA-1,
  2. cross-checks the engine's live modwheel routings (getAllModRoutings)
     against the normalized graphs.jsonl `md` rows (id + depth),
  3. adds the fixture route via setModDepth01 and reads it back
     (getModDepth01 + routing getDepth) — the model consumes exactly the
     read-back words,
  4. writes a versioned JSON sidecar (attacky_mw_inputs.json).

Fail-closed: refuses (exit 2) on any surprise. Run under the pinned
interpreter (auto re-exec via oracle_common).
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

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
PRESET_REL = "resources/data/patches_factory/Basses/Attacky.fxp"
MS_MODWHEEL = 6


class Refuse(Exception):
    pass


def census_blob(rel):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def graphs_modwheel_routes(rel):
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel:
                rows = [r for r in g["g"]["md"]["s"][0]["s"] if r[0] == MS_MODWHEEL]
                return [(r[3], r[4], r[5]) for r in rows]
    raise Refuse("preset not in graphs.jsonl")


def git_blob_sha1(path):
    import hashlib
    import zlib

    data = open(path, "rb").read()
    hdr = b"blob %d\x00" % len(data)
    return hashlib.sha1(hdr + data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(REPO, "model", "voice",
                                                  "attacky_mw_inputs.json"))
    ap.add_argument("--fixture-normalized-depth", type=float, default=0.4)
    args = ap.parse_args()

    expected = census_blob(PRESET_REL)
    preset_abs = os.path.join(oc.data_home(), PRESET_REL[len("resources/data/"):])
    if not os.path.exists(preset_abs):
        raise Refuse("pinned-engine preset not found; set ORACLE_SURGE_DIR")
    actual = git_blob_sha1(preset_abs)
    if actual != expected:
        raise Refuse(f"blob mismatch: {actual} != census {expected}")

    graph_routes = graphs_modwheel_routes(PRESET_REL)

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    import surgepy.constants as C

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(preset_abs):
        raise Refuse("loadPatch failed")
    ms = s.getModSource(C.ms_modwheel)

    # --- cross-check the preset's own modwheel routes against graphs.jsonl --
    live = s.getAllModRoutings()["scene"][0]["scene"]
    live_mw = [(r.getDest().getName(), r.getDepth()) for r in live]
    if len(live_mw) != len(graph_routes):
        raise Refuse(f"routing count {len(live_mw)} != graphs {len(graph_routes)}")
    preset_routes = []
    for (dst_id, dst_name, depth), (ld, ldepth) in zip(graph_routes, live_mw):
        if ld != dst_name:
            raise Refuse(f"dest name mismatch: engine {ld!r} != graphs {dst_name!r}")
        if abs(ldepth - depth) > 1e-4:
            raise Refuse(f"depth mismatch on {dst_name}: {ldepth} != {depth}")
        preset_routes.append({
            "dest_id": dst_id,
            "dest_name": dst_name,
            "depth_raw": depth,
            "source": "preset content (graphs.jsonl md, engine readback equal)",
        })

    # --- fixture route: modwheel -> scene A VCA Gain ------------------------
    target = s.getPatch()["scene"][0]["vca_level"]
    if not s.isValidModulation(target, ms):
        raise Refuse("ms_modwheel -> vca_level not a valid modulation")
    s.setModDepth01(target, ms, args.fixture_normalized_depth, 0, 0)
    got01 = s.getModDepth01(target, ms, 0, 0)
    if abs(got01 - args.fixture_normalized_depth) > 1e-6:
        raise Refuse(f"fixture depth01 readback {got01}")
    rows = s.getAllModRoutings()["scene"][0]["scene"]
    vca_rows = [r for r in rows if r.getDest().getName() == "A VCA Gain"]
    if len(vca_rows) != 1:
        raise Refuse(f"expected exactly one VCA routing, got {len(vca_rows)}")
    fixture_route = {
        "dest_id": 298,
        "dest_param": "vca_level",
        "dest_name": vca_rows[0].getDest().getName(),
        "modsource": "ms_modwheel",
        "modsource_id": MS_MODWHEEL,
        "normalized_depth": got01,
        "depth_raw": vca_rows[0].getDepth(),
        "source": "runtime setModDepth01 (host modulation API); preset file "
                  "untouched; synthetic declared fixture on the landed voice "
                  "slice",
    }

    out = {
        "schema_version": 1,
        "issue": "SXT-035",
        "frozen_scope": "scene-modwheel route table {Filter 1 Cutoff (308), "
                        "Filter 1 Resonance (309), VCA Gain (298)} on the "
                        "landed SXT-022/SXT-026a voice class; FAST_LINE "
                        "smoothing per the landed Modwheel (cited: "
                        "ModulationSource.h ControllerModulationSourceVector, "
                        "SurgeStorage.h:2063 default, SurgeSynthesizer.cpp "
                        "channelController case 1)",
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
        "preset_modwheel_routes": preset_routes,
        "fixture_routes": [fixture_route],
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({"out": os.path.relpath(args.out, REPO),
                      "preset_routes": len(preset_routes),
                      "fixture_route_depth_raw": fixture_route["depth_raw"],
                      "fixture_route_depth01": got01}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
