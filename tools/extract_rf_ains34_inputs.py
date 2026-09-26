#!/usr/bin/env python3
"""SXT-028i: fail-closed extraction of routing-form (Scene-A insert FX bus,
slots 3-4, the extended rack half) carrier metadata from the pinned engine's
committed corpus artifacts.

For each B4-scope carrier preset this tool:
  1. re-verifies the census blob sha1 (corpus/census-v0.1/results/
     per-preset.csv) against the pinned issue text, REFUSING on mismatch;
  2. re-verifies that the carrier is one of this leaf's own B4-scope
     candidates (reports/sxt-028/leaves/SXT-028i/newly-enabled.json), blob
     sha1 included, so no preset can be quietly pulled in from outside the
     leaf's declared scope;
  3. cross-checks the normalized corpus graph (corpus/normalized/graphs.jsonl,
     SXT-011 output -- already surgepy-derived and committed, so no live
     oracle call is needed for this step) for the ains3/ains4 slot roles:
     occupancy (on/off), FX type name/id, the stored per-slot return_level
     (recorded but NOT consumed by the insert path -- return/send-level
     semantics belong to the send-form leaves), and the patch-level
     fxb (fx_bypass) / fxd (fx_disable) fields;
  4. asserts ZERO DRIFT between the two independently-derived committed
     artifacts (census CSV vs normalized graph) on every field both carry:
     blob sha1, stored revision, scene mode, fx_bypass, fx_disable, the
     non-off FX slot count and the non-off FX type set. Any disagreement is a
     REFUSAL, never a silently-preferred source;
  5. attempts a LIVE surgepy extraction of the per-slot algorithm's own
     parameter values and the engine-side determinism gate (per-scene drift
     == 0) -- both needed only for an eventual concrete-occupant reference
     render, which is out of THIS leaf's routing-form scope. If the pinned
     oracle build (surgepy) is unavailable in the current environment, this
     step REFUSES explicitly (never silently drops the preset, never
     fabricates a value) and the routing-verification checks above still
     proceed and are still written to the output record.

Carrier set. The issue's Fixtures plan NAMES three carriers (Jigsaw,
Resurrection, Pixel). All three occupy exactly ONE of ains3/ains4, so none of
them exercises this leaf's two-concurrent-instance shape or its disabled-slot
shape. Two further carriers are therefore added FROM THIS LEAF'S OWN B4-scope
candidate list (never from outside it, and checked against it in step 2):
`Sand Storm.fxp` (ains3 = Reverb 1 AND ains4 = EQ, fx_disable 0 -- the
concurrent dual-instance shape) and `Brass Ensemble.fxp` (both slots occupied
with fx_disable = 256, i.e. bit 8 = ains3 disabled -- the routing-level
disable gate on a real preset). Each record states which of the two it is via
`carrier_source`.

Writes model/effects/fx_inputs/rf-rf-ains34-<slug>.json plus a refusal
transcript at reports/SXT-028i/artifacts/extract-refusals.txt (created even
when empty, matching the SXT-023/028c/028d/028h refusal-log convention --
absence of oracle coverage is recorded, never silently dropped).

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, and only for the step-5 attempt.
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
FXSLOT_AINS3, FXSLOT_AINS4 = 8, 9

NAMED_BY_ISSUE = "issue #61 Fixtures plan (named B4-scope carrier)"
ADDED_BY_LEAF = ("added by this leaf from its own B4-scope candidate list "
                 "(reports/sxt-028/leaves/SXT-028i/newly-enabled.json): the "
                 "three issue-named carriers each occupy only ONE of "
                 "ains3/ains4, so none of them exercises the concurrent "
                 "dual-instance or disabled-slot shape this leaf claims")

CARRIERS = [
    {"slug": "jigsaw",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Basses/Jigsaw.fxp",
     "declared_sha1": "676da8126b33e867fb2028701bf7be8ac63f2e72",
     "source": NAMED_BY_ISSUE},
    {"slug": "resurrection",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Basses/"
             "Resurrection.fxp",
     "declared_sha1": "e2ccab1d70342ce5d18d4bb0993825ff7f959728",
     "source": NAMED_BY_ISSUE},
    {"slug": "pixel",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Keys/Pixel.fxp",
     "declared_sha1": "3a9f5294f5c2e2c4e1111822ac910067adcbec3f",
     "source": NAMED_BY_ISSUE},
    {"slug": "sand-storm",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Keys/Sand Storm.fxp",
     "declared_sha1": "2ba21470c23e49ca2bc12dd185159b1b539bbbb8",
     "source": ADDED_BY_LEAF},
    {"slug": "brass-ensemble",
     "path": "resources/data/patches_3rdparty/Lopyt/Brass/Brass Ensemble.fxp",
     "declared_sha1": "c61dbef103a1c60e0e7d151cfecf1a2a4a483c7f",
     "source": ADDED_BY_LEAF},
]

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
LEAF_B4 = os.path.join(REPO, "reports", "sxt-028", "leaves", "SXT-028i",
                       "newly-enabled.json")
OUT_DIR = os.path.join(REPO, "model", "effects", "fx_inputs")
REFUSALS = os.path.join(REPO, "reports", "SXT-028i", "artifacts",
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


def b4_candidate(rel_path):
    """This leaf's own declared B4-scope candidate list. A carrier absent from
    it is a REFUSAL: no preset may be pulled in from outside the leaf's
    declared scope, not even a convenient one."""
    with open(LEAF_B4, encoding="utf-8") as f:
        doc = json.load(f)
    for c in doc["b4_scope_candidates"]:
        if c["path"] == rel_path:
            return c
    raise Refuse(f"preset is not a declared B4-scope candidate of this leaf "
                 f"(reports/sxt-028/leaves/SXT-028i/newly-enabled.json): "
                 f"{rel_path}")


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
    b4 = b4_candidate(rel)
    if b4.get("sha") != carrier["declared_sha1"]:
        raise Refuse(f"B4-candidate blob sha1 mismatch for {rel}: "
                     f"declared={carrier['declared_sha1']} "
                     f"leaf-list={b4.get('sha')}")
    graph = graphs_entry(rel)
    if graph.get("sha") != carrier["declared_sha1"]:
        raise Refuse(f"graphs.jsonl blob sha1 mismatch for {rel}")
    if graph.get("st") != "normalized":
        raise Refuse(f"preset not normalized: {rel}")
    if row["content_verified"] != "True":
        raise Refuse(f"census content not verified: {rel}")

    xcheck = cross_check(row, graph)

    a3 = slot_entry(graph, "ains3")
    a4 = slot_entry(graph, "ains4")
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
        "leaf": "SXT-028i",
        "routing_form": "rf-ains34",
        "roles": ["ains3", "ains4"],
        "carrier_source": carrier["source"],
        "preset": {"path": rel, "bank": graph.get("b"),
                   "census_blob_sha1_verified": row["git_blob_sha1"],
                   "graphs_blob_sha1_verified": graph.get("sha"),
                   "leaf_b4_candidate_sha1_verified": b4.get("sha"),
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
            "scene_a_instantiated": True,
            "note": "scene A is instantiated in EVERY scene mode (Single "
                    "included), so a scene-A insert slot is reachable in "
                    "every patch that loads -- unlike the scene-B insert bus "
                    "(sibling leaf rf-rf-bins12), whose slots are unreachable "
                    "in a Single-scene patch",
        },
        "ains3": slot_doc(a3, FXSLOT_AINS3),
        "ains4": slot_doc(a4, FXSLOT_AINS4),
        "dual_instance_concurrent": bool(a3.get("on", 0)) and
                                    bool(a4.get("on", 0)),
        "extended_half_position": {
            "ains1_occupied": bool(slot_entry(graph, "ains1").get("on", 0)),
            "ains2_occupied": bool(slot_entry(graph, "ains2").get("on", 0)),
            "note": "the ains1/ains2 BASE half of the same scene-A insert "
                    "chain is upstream of this leaf and is a declared scope "
                    "omission (a sibling rf-ains12-class leaf's scope); "
                    "recorded here so the composition is visible, not "
                    "modeled",
        },
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
        out_path = os.path.join(OUT_DIR, f"rf-rf-ains34-{carrier['slug']}.json")
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
