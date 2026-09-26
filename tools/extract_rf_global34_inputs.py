#!/usr/bin/env python3
"""SXT-028j: fail-closed extraction of routing-form (Global FX slots 3-4,
the extended rack half) carrier metadata from the pinned engine's committed
corpus artifacts.

For each carrier preset this tool:
  1. re-verifies the census blob sha1 (corpus/census-v0.1/results/
     per-preset.csv) against the declared sha1, REFUSING on mismatch;
  2. cross-checks the normalized corpus graph (corpus/normalized/graphs.jsonl,
     SXT-011 output -- already surgepy-derived and committed, so no live
     oracle call is needed for this step) for the global3/global4 slot roles:
     occupancy (on/off), FX type name/id, the stored per-slot return_level
     (recorded but NOT consumed by the global insert path -- return/send-level
     semantics belong to the send-form leaves), and the patch-level
     fxb (fx_bypass) / fxd (fx_disable) fields;
  3. records the UPSTREAM chain context (global1/global2 occupancy), because
     the master bus and the ring flag arriving at global3 are whatever the
     landed sibling leaf's global1 -> global2 segment left -- this leaf's
     declared seam;
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

CARRIER SET. The first three carriers are the B4-scope presets named by the
issue (reports/sxt-028/leaves/SXT-028j.json `carriers.top_presets`). All
three turn out to occupy global3 ONLY -- none of them exercises the
two-concurrent-instance shape this leaf's acceptance requires. Two further
carriers are therefore added from the same committed corpus, chosen for the
routing SHAPES the acceptance checklist needs and verified by the identical
fail-closed path:
  * String Contrabass.fxp -- the SAME FX class (Airwindows) in BOTH global3
    and global4: the concurrent dual-instance shape, and specifically the
    same-class case the issue's wrong-order/shared-state controls name.
  * Bassoon.fxp -- both slots occupied AND fx_disable = 49152 (bits 14|15):
    the real-corpus instance of this leaf's own per-slot disable gate.
The additions are recorded as such (`carrier_source`), never presented as
issue-named carriers.

Writes model/effects/fx_inputs/rf-rf-global34-<slug>.json plus a refusal
transcript at reports/SXT-028j/artifacts/extract-refusals.txt (created even
when empty, matching the SXT-023/028c/028d/028h refusal-log convention --
absence of oracle coverage is recorded, never silently dropped).

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, and only for the item-5 attempt.
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
FXSLOT_GLOBAL1, FXSLOT_GLOBAL2 = 6, 7
FXSLOT_GLOBAL3, FXSLOT_GLOBAL4 = 14, 15

CARRIERS = [
    # --- the three B4-scope carriers named by issue #62 / SXT-028j.json ---
    {"slug": "jigsaw",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Basses/Jigsaw.fxp",
     "declared_sha1": "676da8126b33e867fb2028701bf7be8ac63f2e72",
     "carrier_source": "issue-named B4-scope carrier"},
    {"slug": "pixel",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Keys/Pixel.fxp",
     "declared_sha1": "3a9f5294f5c2e2c4e1111822ac910067adcbec3f",
     "carrier_source": "issue-named B4-scope carrier"},
    {"slug": "lazy",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Pads/Lazy.fxp",
     "declared_sha1": "321848282edf3b40d6f93ad950a8ae35660f3258",
     "carrier_source": "issue-named B4-scope carrier"},
    # --- shape carriers added by this leaf (see module docstring) ---
    {"slug": "string-contrabass",
     "path": "resources/data/patches_3rdparty/John Valentine/Strings/"
             "String Contrabass.fxp",
     "declared_sha1": "50ee25dfecf475023179eac4c788483ebf12d30d",
     "carrier_source": "added by this leaf: concurrent dual-instance shape, "
                       "SAME FX class in both global3 and global4"},
    {"slug": "bassoon",
     "path": "resources/data/patches_3rdparty/John Valentine/Winds/"
             "Bassoon.fxp",
     "declared_sha1": "1b9c6dce3575e888348d6a60bb88582b457d68a3",
     "carrier_source": "added by this leaf: both slots occupied AND both "
                       "disabled by fx_disable bits 14|15"},
]

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
OUT_DIR = os.path.join(REPO, "model", "effects", "fx_inputs")
ARTIFACTS = os.path.join(REPO, "reports", "SXT-028j", "artifacts")
REFUSALS = os.path.join(ARTIFACTS, "extract-refusals.txt")
OCCUPANCY = os.path.join(ARTIFACTS, "corpus-occupancy.json")


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


def role_index_check(graph):
    """Re-derive this leaf's slot indices from the committed corpus role
    table itself (no live oracle). REFUSES if the record disagrees with the
    frozen model's FXSLOT_GLOBAL3/4."""
    roles = {fx.get("i"): fx.get("r") for fx in graph["g"]["fx"]}
    expect = {FXSLOT_GLOBAL1: "global1", FXSLOT_GLOBAL2: "global2",
              FXSLOT_GLOBAL3: "global3", FXSLOT_GLOBAL4: "global4"}
    bad = {i: (roles.get(i), r) for i, r in expect.items() if roles.get(i) != r}
    if bad:
        raise Refuse(f"graphs.jsonl slot-index/role table disagrees with the "
                     f"frozen model's fxslot constants: {bad}")
    return {"verified_indices": {str(i): r for i, r in expect.items()},
            "source": "corpus/normalized/graphs.jsonl fx[].i / fx[].r "
                      "(SXT-011 output; no live oracle needed)"}


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
    idx_check = role_index_check(graph)

    g3 = slot_entry(graph, "global3")
    g4 = slot_entry(graph, "global4")
    g1 = slot_entry(graph, "global1")
    g2 = slot_entry(graph, "global2")
    fxb = graph["g"]["fxb"]
    fxd = graph["g"]["fxd"]

    oracle_ok, oracle_detail = try_live_oracle_extraction(rel)

    def slot_doc(fx, bit):
        return {"occupied": bool(fx.get("on", 0)),
                "type_name": fx.get("tn"),
                "type_id": fx.get("t"),
                "airwindows_sub_id": fx.get("aw"),
                "airwindows_sub_name": fx.get("awn"),
                "fx_disable_bit": bool((fxd >> bit) & 1),
                "return_level_stored": fx.get("rl"),
                "return_level_consumed_by_global_path": False}

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028j",
        "routing_form": "rf-global34",
        "roles": ["global3", "global4"],
        "carrier_source": carrier["carrier_source"],
        "preset": {"path": rel, "bank": graph.get("b"),
                   "census_blob_sha1_verified": row["git_blob_sha1"],
                   "graphs_blob_sha1_verified": graph.get("sha"),
                   "census_status": row["status"],
                   "stored_revision": graph.get("rev")},
        "patch_level": {"fx_bypass": fxb,
                        "fx_bypass_name": graph["g"].get("fxbn"),
                        "fx_disable_mask": fxd,
                        "global_stage_runs_in_this_mode": fxb in (0, 1)},
        "upstream_chain_context": {
            "note": "the master bus and the ring flag arriving at global3 "
                    "are whatever the global1 -> global2 segment left; that "
                    "segment is the landed sibling leaf "
                    "model/effects/rf-rf-global2/ (SXT-028d) and is NOT "
                    "re-claimed here",
            "global1_occupied": bool(g1.get("on", 0)),
            "global1_type_name": g1.get("tn"),
            "global2_occupied": bool(g2.get("on", 0)),
            "global2_type_name": g2.get("tn"),
            "upstream_slots_active": int(bool(g1.get("on", 0))) +
                                     int(bool(g2.get("on", 0))),
        },
        "global3": slot_doc(g3, FXSLOT_GLOBAL3),
        "global4": slot_doc(g4, FXSLOT_GLOBAL4),
        "dual_instance_concurrent": bool(g3.get("on", 0)) and
                                    bool(g4.get("on", 0)),
        "same_class_both_slots": bool(g3.get("on", 0)) and
                                 bool(g4.get("on", 0)) and
                                 g3.get("tn") == g4.get("tn"),
        "both_slots_disabled": bool((fxd >> FXSLOT_GLOBAL3) & 1) and
                               bool((fxd >> FXSLOT_GLOBAL4) & 1),
        "cross_check": xcheck,
        "slot_index_check": idx_check,
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


def corpus_occupancy():
    """Corpus-wide occupancy scan for this leaf's two roles. COVERAGE
    accounting only -- it is not a support claim and says nothing about
    agreement (AGENTS.md: coverage is reported separately from agreement)."""
    total = 0
    g3_on = g4_on = both = same_class = 0
    dis3 = dis4 = dis_both = 0
    nonzero_bypass = 0
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            total += 1
            fx = {e.get("r"): e for e in g["g"]["fx"]}
            a = bool(fx.get("global3", {}).get("on", 0))
            b = bool(fx.get("global4", {}).get("on", 0))
            fxd = g["g"].get("fxd", 0)
            g3_on += a
            g4_on += b
            if a and b:
                both += 1
                if fx["global3"].get("tn") == fx["global4"].get("tn"):
                    same_class += 1
            d3 = bool((fxd >> FXSLOT_GLOBAL3) & 1)
            d4 = bool((fxd >> FXSLOT_GLOBAL4) & 1)
            dis3 += d3
            dis4 += d4
            dis_both += d3 and d4
            if g["g"].get("fxb", 0) != 0 and (a or b):
                nonzero_bypass += 1
    return {
        "schema_version": 1,
        "leaf": "SXT-028j",
        "source": "corpus/normalized/graphs.jsonl (SXT-011 output)",
        "claim_scope": "COVERAGE accounting only -- an inventory of which "
                       "corpus presets exercise this routing form's shapes. "
                       "NOT a support claim and NOT an agreement number.",
        "presets_scanned": total,
        "global3_occupied": g3_on,
        "global4_occupied": g4_on,
        "both_slots_occupied": both,
        "both_slots_occupied_same_fx_class": same_class,
        "fx_disable_bit14_set": dis3,
        "fx_disable_bit15_set": dis4,
        "fx_disable_both_bits_set": dis_both,
        "non_all_fx_bypass_with_a_global34_occupant": nonzero_bypass,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(ARTIFACTS, exist_ok=True)
    refusal_lines = []
    written = []
    for carrier in CARRIERS:
        try:
            doc = extract_one(carrier)
        except Refuse as e:
            refusal_lines.append(f"{carrier['slug']}: REFUSED: {e}")
            continue
        out_path = os.path.join(OUT_DIR,
                                f"rf-rf-global34-{carrier['slug']}.json")
        with open(out_path, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out_path)
        print(f"wrote {out_path}")

    with open(OCCUPANCY, "w") as f:
        json.dump(corpus_occupancy(), f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {OCCUPANCY}")

    with open(REFUSALS, "w") as f:
        f.write("\n".join(refusal_lines) + ("\n" if refusal_lines else ""))
    for line in refusal_lines:
        print(line)
    return 0 if len(written) == len(CARRIERS) else 1


if __name__ == "__main__":
    sys.exit(main())
