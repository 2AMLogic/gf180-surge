#!/usr/bin/env python3
"""SXT-042 applicability scan: how far does the frozen keytrack leaf reach?

Reads ONLY committed normalized state (`corpus/normalized/graphs.jsonl`) and
answers three separable questions, reported separately (AGENTS.md: coverage
is reported separately from agreement, and a screen is never a support
claim):

  1. INVENTORY   how many corpus presets route ms_keytrack at all, and to
                 which destinations (scene A).
  2. ROUTE-CLASS how many of those route keytrack ONLY to destinations inside
                 this leaf's frozen class {308 Filter 1 Cutoff, 309 Filter 1
                 Resonance, 310 Filter 1 FEG Mod} (+ the inert unit-2
                 destinations {314, 315, 318}).
  3. VOICE-CLASS how many of THOSE also pass the graph-visible subset of the
                 landed SXT-026a voice class gate -- i.e. an upper bound on
                 the presets this leaf could contribute to.

**This screen is an upper bound, never a support claim.** The authoritative
gate is `voice_model.InputsV2` over an engine-readback sidecar, which is
strictly stricter (it additionally checks scene drift, vca velsense,
envelope modes/shapes and other fields that the normalized graph does not
carry), and support additionally requires the fidelity-freeze gate (#12) and
the complete wet path (effects), neither of which this leaf touches.

Usage:
  python3 tools/kt_applicability_scan.py [--json OUT.json]
"""

import argparse
import json
import os
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")

MS_VELOCITY, MS_KEYTRACK, MS_MODWHEEL = 1, 2, 6
KT_LIVE = (308, 309, 310)
KT_INERT = (314, 315, 318)
VEL_OK = (298, 308, 309, 310, 314, 315, 318)
SCENE_OK = (308, 309, 260, 298)

# The leaf carrier (this leaf's fixture) and the three carriers named in the
# body of issue #76 -- reported individually so the record states the
# measured outcome for each rather than the issue's attribution figure.
NAMED_CARRIERS = [
    "resources/data/patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Alone.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Autumn 2.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Disturbances.fxp",
]

# The 34 "recovery basis" presets listed in issue #76 (attribution only; the
# issue itself marks their essentiality UNVERIFIED).
RECOVERY_BASIS = [
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Alone.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Autumn 2.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Disturbances.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Fragile 4.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Go Carefully.fxp",
    "resources/data/patches_3rdparty/Inigo Kennedy/Atmospheres/Mystery 4.fxp",
    "resources/data/patches_factory/Basses/Bass 5.fxp",
    "resources/data/patches_factory/Basses/Behemoth.fxp",
    "resources/data/patches_factory/Basses/Distorted FM.fxp",
    "resources/data/patches_factory/Basses/FM Bass 1.fxp",
    "resources/data/patches_factory/Basses/Piano Bass.fxp",
    "resources/data/patches_factory/Basses/Static 2.fxp",
    "resources/data/patches_factory/Chords/Maj-Min Saw.fxp",
    "resources/data/patches_factory/Keys/Soft Suitcase.fxp",
    "resources/data/patches_factory/Leads/Cell.fxp",
    "resources/data/patches_factory/Leads/Chatter.fxp",
    "resources/data/patches_factory/Leads/FM Rock.fxp",
    "resources/data/patches_factory/Leads/Later.fxp",
    "resources/data/patches_factory/Leads/Photon.fxp",
    "resources/data/patches_factory/Leads/Violini Solo.fxp",
    "resources/data/patches_factory/Pads/Communication.fxp",
    "resources/data/patches_factory/Pads/Robochoir 1.fxp",
    "resources/data/patches_factory/Pads/Robochoir 2.fxp",
    "resources/data/patches_factory/Pads/Sprinkly.fxp",
    "resources/data/patches_factory/Pads/Synth Choir MW O-Ah.fxp",
    "resources/data/patches_factory/Pads/Worried.fxp",
    "resources/data/patches_factory/Plucks/Bell 2.fxp",
    "resources/data/patches_factory/Plucks/Diamonds.fxp",
    "resources/data/patches_factory/Plucks/Half FM.fxp",
    "resources/data/patches_factory/Plucks/Hasselhoff.fxp",
    "resources/data/patches_factory/Plucks/Magical Guitar.fxp",
    "resources/data/patches_factory/Plucks/Pinkerton Tinfurter.fxp",
    "resources/data/patches_factory/Plucks/Pol Pot.fxp",
    "resources/data/patches_factory/Plucks/Scrape Pluck.fxp",
]


def scene_a_rows(g):
    md = g.get("md", {})
    scenes = md.get("s", [])
    if not scenes:
        return [], [], []
    rest = [r for sc in scenes[1:] for r in sc.get("v", []) + sc.get("s", [])]
    return scenes[0].get("v", []), scenes[0].get("s", []), rest


def route_class_reasons(v_rows, s_rows, rest_rows):
    """Reasons the preset's ROUTE TABLE is outside this leaf's class."""
    reasons = []
    kt = [r for r in v_rows if r[0] == MS_KEYTRACK]
    if not kt:
        reasons.append("no keytrack voice route in scene A")
    for r in kt:
        if r[3] not in KT_LIVE + KT_INERT:
            reasons.append(f"keytrack->{r[3]} ({r[4]}) outside {{308,309,310}}")
    for r in v_rows:
        if r[0] not in (MS_VELOCITY, MS_KEYTRACK):
            reasons.append(f"voice route source {r[0]} outside "
                           "{velocity, keytrack}")
        elif r[0] == MS_VELOCITY and r[3] not in VEL_OK:
            reasons.append(f"velocity->{r[3]} ({r[4]}) outside the class")
    for r in s_rows:
        if r[0] != MS_MODWHEEL or r[3] not in SCENE_OK:
            reasons.append(f"scene route {r[0]}->{r[3]} ({r[4]}) outside "
                           "the class")
    if rest_rows:
        reasons.append("scene B carries modulation routes (single-scene class)")
    return sorted(set(reasons))


def voice_class_reasons(g):
    """Graph-visible subset of the SXT-026a class gate (UPPER BOUND)."""
    reasons = []
    if g.get("sm") != 0:
        reasons.append(f"scene mode {g.get('smn')!r} != Single")
    if g.get("chn") not in ("Warm", "Neutral"):
        reasons.append(f"character {g.get('chn')!r} not in {{Warm, Neutral}}")
    scs = g.get("sc") or []
    if not scs:
        return reasons + ["no scene data"]
    sc = scs[0]
    if sc.get("pm") != 0:
        reasons.append(f"play mode {sc.get('pmn')!r} != Poly")
    if sc.get("fbc") != 0:
        reasons.append(f"filter config {sc.get('fbcn')!r} != Serial 1")
    if sc.get("lc") != -72.0:
        reasons.append("scene lowcut not at the off value")
    if (sc.get("ws") or {}).get("t", 0) != 0:
        reasons.append("waveshaper not Off")
    if abs(sc.get("pan", 0.0)) > 0:
        reasons.append("scene pan != 0 (mono-bus class)")
    if abs(sc.get("pfg", 0.0)) > 0:
        reasons.append("pre-filter gain != 0")
    if abs(sc.get("vs", 0.0)) > 0:
        reasons.append("vca velocity sensitivity != 0")
    if sc.get("porta") != -8.0:
        reasons.append("portamento active")
    mix = sc.get("mix") or {}
    active = [k for k in ("o1", "o2", "o3", "noise", "ring_12", "ring_23")
              if mix.get(k, [1, 1])[1] == 0]
    if active != ["o1"]:
        reasons.append(f"active mixer paths {active} != ['o1']")
    fu = sc.get("fu") or []
    if len(fu) < 2 or fu[1].get("t", 0) != 0:
        reasons.append("filter unit 2 not Off")
    if not fu or fu[0].get("t") not in (1, 2):
        reasons.append("filter unit 1 not LP12/LP24")
    elif fu[0].get("st") != 1:
        reasons.append("filter unit 1 subtype not Driven")
    if fu and fu[0].get("kt", 0.0) != 0.0:
        reasons.append("filter unit 1 keytrack parameter != 0")
    osc = sc.get("osc") or []
    if not osc:
        reasons.append("no oscillator data")
    else:
        o1 = osc[0]
        if o1.get("t") not in (0, 1):
            reasons.append(f"osc1 type {o1.get('tn')!r} not Classic/Sine")
        if o1.get("kt") != 1:
            reasons.append("osc1 keytrack off")
        if abs(o1.get("pit", 0.0)) > 0:
            reasons.append("osc1 pitch offset != 0")
        if o1.get("uni") != 1 or o1.get("rt") != 1:
            reasons.append("osc1 not unison-1/retrigger")
        fm = (sc.get("fm") or {}).get("sw", 0)
        if o1.get("t") == 1:
            p = o1.get("p") or [0] * 5
            if int(p[0]) != 0:
                reasons.append(f"sine shape {p[0]} != 0")
            if int(p[2]) != 0:
                reasons.append(f"sine FMmode {p[2]} != 0")
            if fm not in (0, 2):
                reasons.append(f"fm_switch {fm} not in {{0, 2}}")
        else:
            if fm != 0:
                reasons.append("classic osc with FM routing")
            if sc.get("oct", 0) != 0:
                reasons.append("classic osc with scene octave != 0")
    return sorted(set(reasons))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graphs", default=GRAPHS)
    ap.add_argument("--json", help="write the record here")
    args = ap.parse_args()

    total = 0
    kt_presets = 0
    dest_hist = Counter()
    route_class_ok = []
    voice_class_ok = []
    per_path = {}

    with open(args.graphs, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            total += 1
            g = r["g"]
            v_rows, s_rows, rest = scene_a_rows(g)
            kt_rows = [x for x in v_rows if x[0] == MS_KEYTRACK]
            for x in kt_rows:
                dest_hist[x[4]] += 1
            if kt_rows:
                kt_presets += 1
            rc = route_class_reasons(v_rows, s_rows, rest)
            vc = voice_class_reasons(g) if not rc else None
            if not rc:
                route_class_ok.append(r["p"])
                if not vc:
                    voice_class_ok.append(r["p"])
            if r["p"] in NAMED_CARRIERS or r["p"] in RECOVERY_BASIS:
                per_path[r["p"]] = {
                    "path": r["p"],
                    "keytrack_routes": [{"dest_id": x[3], "dest": x[4],
                                         "depth_raw": x[5]} for x in kt_rows],
                    "route_class_reasons": rc,
                    "voice_class_reasons": vc if vc is not None else [],
                    "in_class": bool(not rc and not vc),
                }

    for p in NAMED_CARRIERS + RECOVERY_BASIS:
        per_path.setdefault(p, {"path": p, "keytrack_routes": [],
                                "route_class_reasons": ["not in graphs.jsonl"],
                                "voice_class_reasons": [],
                                "in_class": False})

    recovery_in_class = [p for p in RECOVERY_BASIS if per_path[p]["in_class"]]
    rec = {
        "issue": "SXT-042",
        "claim": ("graph-visible screen and UPPER BOUND on reach; not a "
                  "support claim, not a fidelity claim -- the authoritative "
                  "gate is InputsV2 on an engine-readback sidecar, and "
                  "support additionally requires #12 and the wet path"),
        "graphs": os.path.relpath(args.graphs, REPO),
        "presets_scanned": total,
        "presets_routing_keytrack": kt_presets,
        "keytrack_destination_histogram": dest_hist.most_common(),
        "route_class_ok_count": len(route_class_ok),
        "route_class_ok": sorted(route_class_ok),
        "voice_class_ok_count": len(voice_class_ok),
        "voice_class_ok": sorted(voice_class_ok),
        "recovery_basis_total": len(RECOVERY_BASIS),
        "recovery_basis_in_class": sorted(recovery_in_class),
        "recovery_basis_in_class_count": len(recovery_in_class),
        "carriers": [per_path[p] for p in NAMED_CARRIERS],
        "recovery_basis_detail": [per_path[p] for p in RECOVERY_BASIS],
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
    summary = {k: rec[k] for k in ("presets_scanned",
                                   "presets_routing_keytrack",
                                   "route_class_ok_count",
                                   "voice_class_ok_count",
                                   "recovery_basis_in_class_count")}
    summary["voice_class_ok"] = rec["voice_class_ok"]
    summary["carriers"] = [{"path": c["path"], "in_class": c["in_class"],
                            "reasons": (c["route_class_reasons"]
                                        + c["voice_class_reasons"])[:4]}
                           for c in rec["carriers"]]
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
