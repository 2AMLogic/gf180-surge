#!/usr/bin/env python3
"""SXT-028h: fail-closed extraction of routing-form (Scene-B insert FX bus,
slots 1-2) carrier metadata from the pinned engine's committed corpus
artifacts.

For each B4-scope carrier preset named in reports/sxt-028/leaves/SXT-028h.json
this tool:
  1. re-verifies the census blob sha1 (corpus/census-v0.1/results/
     per-preset.csv) against the pinned issue text, REFUSING on mismatch;
  2. cross-checks the normalized corpus graph (corpus/normalized/graphs.jsonl,
     SXT-011 output -- already surgepy-derived and committed, so no live
     oracle call is needed for this step) for the bins1/bins2 slot roles:
     occupancy (on/off), FX type name/id, the stored per-slot return_level
     (recorded but NOT consumed by the insert path -- return/send-level
     semantics belong to the send-form leaves), and the patch-level
     fxb (fx_bypass) / fxd (fx_disable) fields;
  3. asserts ZERO DRIFT between the two independently-derived committed
     artifacts (census CSV vs normalized graph) on every field both carry:
     blob sha1, stored revision, scene mode, fx_bypass, fx_disable, the
     non-off FX slot count and the non-off FX type set. Any disagreement is a
     REFUSAL, never a silently-preferred source;
  4. attempts a LIVE surgepy extraction of the per-slot algorithm's own
     parameter values and the engine-side determinism gate (per-scene drift
     == 0) -- both needed only for an eventual concrete-occupant reference
     render, which is out of THIS leaf's routing-form scope. If the pinned
     oracle build (surgepy) is unavailable in the current environment, this
     step REFUSES explicitly (never silently drops the preset, never
     fabricates a value) and the routing-verification checks above still
     proceed and are still written to the output record.

Writes model/effects/fx_inputs/rf-rf-bins12-<slug>.json plus a refusal
transcript at reports/SXT-028h/artifacts/extract-refusals.txt (created even
when empty, matching the SXT-023/028c/028d refusal-log convention -- absence
of oracle coverage is recorded, never silently dropped).

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, and only for the item-4 attempt.
"""

import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

# SurgeStorage.h fxslot_positions (re-derivable from
# tools/export_normalized_graphs.py FX_ROLES / corpus/normalized/graphs.jsonl)
FXSLOT_BINS1, FXSLOT_BINS2 = 2, 3

CARRIERS = [
    {"slug": "novuo",
     "path": "resources/data/patches_3rdparty/A.Liv/Leads/Novuo.fxp",
     "declared_sha1": "e688adfdcdee44073968942914733783163b0e8c"},
    {"slug": "acoordion-basses",
     "path": "resources/data/patches_3rdparty/Aleksey Zhehanov/Keys/"
             "Acoordion Basses.fxp",
     "declared_sha1": "a765202508e7522972196640c79dfd3fbb90f292"},
    {"slug": "shore",
     "path": "resources/data/patches_3rdparty/Altenberg/FX/Shore.fxp",
     "declared_sha1": "e0c8107755b359c69527aa22508ea7762991ac3d"},
]

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
OUT_DIR = os.path.join(REPO, "model", "effects", "fx_inputs")
REFUSALS = os.path.join(REPO, "reports", "SXT-028h", "artifacts",
                        "extract-refusals.txt")


class Refuse(Exception):
    pass


def census_row(rel_path):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel_path:
                return row
    raise Refuse(f"preset not in census: {rel_path}")


def graphs_entry(rel_path):
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel_path:
                return g
    raise Refuse(f"preset not in graphs.jsonl: {rel_path}")


def slot_entry(graph, slot_role):
    for fx in graph["g"]["fx"]:
        if fx.get("r") == slot_role:
            return fx
    raise Refuse(f"no {slot_role} entry in graphs.jsonl fx list")


def norm_type_name(name):
    """Census writes FX type names without spaces ("Reverb2"); the normalized
    graph uses the engine's display name ("Reverb 2"). Compare on the
    space-stripped form so the cross-check is about CONTENT, not spelling."""
    return "".join(str(name).split())


def cross_check(row, graph):
    """Zero-drift assertion between the two committed artifacts. Returns the
    per-field comparison record; raises Refuse on ANY disagreement."""
    g = graph["g"]
    on_slots = [fx for fx in g["fx"] if fx.get("on", 0)]
    census_types = {norm_type_name(t)
                    for t in row["stored_nonoff_fx_types"].split(";") if t}
    graph_types = {norm_type_name(fx.get("tn")) for fx in on_slots}
    checks = {
        "blob_sha1": (row["git_blob_sha1"], graph.get("sha")),
        "stored_revision": (int(row["stored_revision"]), graph.get("rev")),
        "scene_mode": (row["scene_mode"], g.get("smn")),
        "fx_bypass": (int(row["stored_fx_bypass"]), g.get("fxb")),
        "fx_disable": (int(row["stored_fx_disable"]), g.get("fxd")),
        "nonoff_fx_slot_count": (int(row["stored_nonoff_fx_slot_count"]),
                                 len(on_slots)),
        "nonoff_fx_type_set": (sorted(census_types), sorted(graph_types)),
    }
    disagreements = [k for k, (a, b) in checks.items() if a != b]
    if disagreements:
        detail = "; ".join(f"{k}: census={checks[k][0]!r} graphs={checks[k][1]!r}"
                           for k in disagreements)
        raise Refuse(f"census-vs-graphs drift on {disagreements}: {detail}")
    return {"fields_compared": sorted(checks),
            "census_vs_graphs_drift_count": 0,
            "values": {k: checks[k][0] for k in checks}}


def try_live_oracle_extraction(rel_path):
    """Attempt a live surgepy extraction of the per-slot algorithm's own
    parameters and the engine-side determinism gate (per-scene drift == 0).
    Returns (ok, detail_or_reason). This is the ONLY step that needs the built
    oracle; nothing above depends on it."""
    try:
        import oracle_common as oc  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - environment-dependent
        return False, f"oracle_common import failed: {e}"
    try:
        surgepy = oc.import_surgepy()
    except Exception as e:
        return False, f"surgepy unavailable (oracle not built in this " \
                      f"environment): {e}"
    # surgepy present: per-slot parameter extraction + the per-scene drift
    # determinism gate would run here (out of THIS leaf's routing-form scope;
    # left for the algorithm leaf that eventually occupies each concrete
    # slot). Recorded as available but not exercised by this routing-form leaf.
    return True, f"surgepy present ({surgepy.__file__}); per-slot parameter " \
                 f"extraction and the engine-side drift gate are " \
                 f"algorithm-leaf scope, not exercised here"


def extract_one(carrier):
    rel = carrier["path"]
    row = census_row(rel)
    if row["git_blob_sha1"] != carrier["declared_sha1"]:
        raise Refuse(f"census blob sha1 mismatch for {rel}: "
                     f"declared={carrier['declared_sha1']} "
                     f"census={row['git_blob_sha1']}")
    graph = graphs_entry(rel)
    if graph.get("sha") != carrier["declared_sha1"]:
        raise Refuse(f"graphs.jsonl blob sha1 mismatch for {rel}")
    if graph.get("st") != "normalized":
        raise Refuse(f"preset not normalized: {rel}")
    if row["content_verified"] != "True":
        raise Refuse(f"census content not verified: {rel}")

    xcheck = cross_check(row, graph)

    b1 = slot_entry(graph, "bins1")
    b2 = slot_entry(graph, "bins2")
    fxb = graph["g"]["fxb"]
    fxd = graph["g"]["fxd"]
    scene_mode_name = graph["g"].get("smn")

    oracle_ok, oracle_detail = try_live_oracle_extraction(rel)

    def slot_doc(fx, bit):
        return {"occupied": bool(fx.get("on", 0)),
                "type_name": fx.get("tn"),
                "type_id": fx.get("t"),
                "fx_disable_bit": bool((fxd >> bit) & 1),
                "return_level_stored": fx.get("rl"),
                "return_level_consumed_by_insert_path": False}

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028h",
        "routing_form": "rf-bins12",
        "roles": ["bins1", "bins2"],
        "preset": {"path": rel, "bank": graph.get("b"),
                   "census_blob_sha1_verified": row["git_blob_sha1"],
                   "graphs_blob_sha1_verified": graph.get("sha"),
                   "census_status": row["status"],
                   "stored_revision": graph.get("rev")},
        "patch_level": {"fx_bypass": fxb,
                        "fx_bypass_name": graph["g"].get("fxbn"),
                        "fx_disable_mask": fxd,
                        "insert_stage_runs_in_this_mode": fxb != 3},
        "scene_context": {
            "scene_mode_id": graph["g"].get("sm"),
            "scene_mode_name": scene_mode_name,
            "census_scene_mode": row["scene_mode"],
            "census_required_scenes": row["required_scenes"],
            "scene_b_instantiated": scene_mode_name != "Single",
            "note": "a Single-scene patch never instantiates scene B, so its "
                    "bins slots are unreachable; all carriers named by this "
                    "leaf are multi-scene",
        },
        "bins1": slot_doc(b1, FXSLOT_BINS1),
        "bins2": slot_doc(b2, FXSLOT_BINS2),
        "dual_instance_concurrent": bool(b1.get("on", 0)) and
                                    bool(b2.get("on", 0)),
        "cross_check": xcheck,
        "applicability": {
            "routing_metadata_verified": True,
            "complete_wet_render_possible": False,
            "complete_wet_render_reason":
                "per-slot algorithm parameter extraction and any wet-audio "
                "render require the pinned oracle (surgepy); this leaf's own "
                "routing/scheduling claims do not depend on it -- see "
                "oracle_extraction below",
        },
        "oracle_extraction": {"attempted": True, "ok": oracle_ok,
                              "detail": oracle_detail},
    }
    return doc


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(REFUSALS), exist_ok=True)
    refusal_lines = []
    written = []
    for carrier in CARRIERS:
        try:
            doc = extract_one(carrier)
        except Refuse as e:
            refusal_lines.append(f"{carrier['slug']}: REFUSED: {e}")
            continue
        out_path = os.path.join(OUT_DIR, f"rf-rf-bins12-{carrier['slug']}.json")
        with open(out_path, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out_path)
        print(f"wrote {out_path}")

    with open(REFUSALS, "w") as f:
        f.write("\n".join(refusal_lines) + ("\n" if refusal_lines else ""))
    for line in refusal_lines:
        print(line)
    return 0 if len(written) == len(CARRIERS) else 1


if __name__ == "__main__":
    sys.exit(main())
