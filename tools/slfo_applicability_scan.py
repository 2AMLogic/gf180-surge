#!/usr/bin/env python3
"""SXT-041 applicability scan: which corpus presets route the SCENE LFOs
(ms_slfo1..ms_slfo6, pinned ids 23..28), where they route them, and why the
leaf's named carriers are or are not renderable end-to-end by the landed
voice arithmetic.

Input is the committed normalized graph export (`corpus/normalized/
graphs.jsonl`, SXT-011 schema rev 1.0.0 — `md.s[i].s` is the scene-bus route
list and `md.s[i].v` the voice-bus list, each row
`[source_id, source_scene, source_index, dest_synthside_id, dest_name,
depth, normalized_depth]`). No oracle is needed and none is used: this is an
inventory over committed data, NOT a support claim (AGENTS.md: the census and
the normalized export are prioritization aids only).

Every named carrier is reported with explicit, enumerated reasons, so a
preset that this leaf cannot render is recorded as such instead of being
silently dropped.

Usage:
  python3 tools/slfo_applicability_scan.py --out reports/SXT-041/artifacts/applicability-scan.json
"""

import argparse
import collections
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")

MS_SLFO = tuple(range(23, 29))          # ms_slfo1..ms_slfo6
MS_LFO = tuple(range(17, 23))           # ms_lfo1..ms_lfo6

# The carriers issue #75 names for this leaf.
CARRIERS = (
    "resources/data/patches_3rdparty/Bluelight/Pads/Bad News.fxp",
    "resources/data/patches_3rdparty/Bluelight/Pads/Rainy Day Dreamaway.fxp",
    "resources/data/patches_3rdparty/Emu/Plucks/Pluck 2 Pad Demon Sad.fxp",
)

# This leaf's frozen destination classes (the two SXT-032 classes, reached
# through modulation_scene instead of modulation_voice).
FROZEN_DESTS = ("A Filter 1 Cutoff", "A Filter 1 Resonance",
                "B Filter 1 Cutoff", "B Filter 1 Resonance")


def landed_slice_reasons(g):
    """Why this preset is / is not inside the landed voice arithmetic.

    The gates are the SXT-022 slice gates as generalized by SXT-026a/#48 and
    re-used by every voice leaf (single scene, no FX, poly, serial1 filter
    block, waveshaper off, lowcut off, osc1-only, Classic osc, LP12 filter).
    """
    reasons = []
    if g.get("st") != "normalized":
        reasons.append(f"graph state {g.get('st')!r}, not 'normalized'")
    gg = g["g"]
    if gg.get("sm") != 0:
        reasons.append(f"scene mode sm={gg.get('sm')} (not single-scene)")
    if gg.get("sa") != 0:
        reasons.append(f"active scene sa={gg.get('sa')} (not scene A)")
    fx = [f["t"] for f in gg.get("fx", []) if f.get("t")]
    if fx:
        reasons.append(f"{len(fx)} active FX slot(s), types {sorted(set(fx))}")
    A = gg["sc"][0]
    if A.get("pm") != 0:
        reasons.append(f"playmode pm={A.get('pm')} (not poly)")
    if A.get("fbc") != 0:
        reasons.append(f"filter block config fbc={A.get('fbc')} "
                       "(not serial1)")
    if A.get("ws", {}).get("t") != 0:
        reasons.append(f"waveshaper type {A.get('ws', {}).get('t')} "
                       "(not off)")
    if A.get("lc") != -72.0:
        reasons.append(f"scene lowcut {A.get('lc')} (not the off value -72)")
    active = [k for k in ("o1", "o2", "o3") if A["mix"][k][1] == 0]
    if active != ["o1"]:
        reasons.append(f"active mixer paths {active} (not osc1-only)")
    osc_types = sorted({o["t"] for o in A.get("osc", [])})
    if A["osc"][0]["t"] != 0:
        reasons.append(f"osc1 normalized type {A['osc'][0]['t']} "
                       "(not Classic); scene osc types "
                       f"{osc_types}")
    fu = [u["t"] for u in A.get("fu", [])]
    if fu[:2] != [1, 0]:
        reasons.append(f"filter unit types {fu} (landed slice is "
                       "LP12-active / unit-2 off)")
    return reasons


def slfo_routes_of(g):
    out = []
    md = g["g"].get("md", {})
    for si, sc in enumerate(md.get("s", [])):
        for listname, key in (("scene", "s"), ("voice", "v")):
            for row in sc.get(key, []):
                if row[0] in MS_SLFO:
                    out.append({"scene": si, "list": listname,
                                "source_id": row[0],
                                "modsource": f"ms_slfo{row[0] - 22}",
                                "dest_name": row[4], "depth": row[5],
                                "normalized_depth": row[6]})
    for row in md.get("g", []):
        if row[0] in MS_SLFO:
            out.append({"scene": row[1], "list": "global",
                        "source_id": row[0],
                        "modsource": f"ms_slfo{row[0] - 22}",
                        "dest_name": row[4], "depth": row[5],
                        "normalized_depth": row[6]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphs", default=GRAPHS)
    ap.add_argument("--out")
    args = ap.parse_args()

    total = 0
    with_slfo = 0
    with_voice_lfo = 0
    dest_counts = collections.Counter()
    list_counts = collections.Counter()
    instance_counts = collections.Counter()
    inside_frozen_dests = 0
    carriers = {}

    with open(args.graphs, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            total += 1
            routes = slfo_routes_of(g)
            md = g["g"].get("md", {})
            if any(row[0] in MS_LFO
                   for sc in md.get("s", [])
                   for key in ("s", "v")
                   for row in sc.get(key, [])):
                with_voice_lfo += 1
            if routes:
                with_slfo += 1
                for r in routes:
                    dest_counts[r["dest_name"]] += 1
                    list_counts[r["list"]] += 1
                    instance_counts[r["modsource"]] += 1
                if any(r["dest_name"] in FROZEN_DESTS for r in routes):
                    inside_frozen_dests += 1
            if g["p"] in CARRIERS:
                reasons = landed_slice_reasons(g)
                dests = sorted({r["dest_name"] for r in routes})
                carriers[g["p"]] = {
                    "slfo_routes": routes,
                    "slfo_route_count": len(routes),
                    "slfo_destinations": dests,
                    "destinations_inside_frozen_classes": sorted(
                        d for d in dests if d in FROZEN_DESTS),
                    "destinations_outside_frozen_classes": sorted(
                        d for d in dests if d not in FROZEN_DESTS),
                    "landed_slice_blockers": reasons,
                    "renderable_end_to_end_by_landed_leaves": not reasons,
                }

    missing = [p for p in CARRIERS if p not in carriers]
    out = {
        "issue": "SXT-041",
        "claim_scope": "Inventory over the committed normalized export "
                       "(corpus/normalized/graphs.jsonl). NOT a support "
                       "claim, NOT a coverage claim, and no oracle was used. "
                       "Per AGENTS.md the census/normalized export is a "
                       "prioritization aid only.",
        "source": os.path.relpath(args.graphs, REPO),
        "frozen_destination_classes": list(FROZEN_DESTS),
        "corpus": {
            "presets_scanned": total,
            "presets_routing_scene_lfos": with_slfo,
            "presets_routing_voice_lfos": with_voice_lfo,
            "presets_with_at_least_one_scene_lfo_route_inside_the_frozen_"
            "destination_classes": inside_frozen_dests,
            "scene_lfo_routes_by_list": dict(list_counts),
            "scene_lfo_routes_by_instance": dict(
                sorted(instance_counts.items())),
            "top_scene_lfo_destinations": dict(dest_counts.most_common(15)),
        },
        "named_carriers": carriers,
        "named_carriers_absent_from_graphs": missing,
    }
    renderable = [p for p, v in carriers.items()
                  if v["renderable_end_to_end_by_landed_leaves"]]
    out["finding"] = (
        f"{len(renderable)} of {len(CARRIERS)} named carriers are renderable "
        "end-to-end by the landed voice arithmetic, so the leaf's "
        "model-vs-reference legs run on the declared synthetic fixture "
        "instead (reports/SXT-041/EVIDENCE.md). Supported-preset delta from "
        "this leaf: 0.")
    print(json.dumps(out, indent=2, sort_keys=True))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(out, f, indent=2, sort_keys=True)
            f.write("\n")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
