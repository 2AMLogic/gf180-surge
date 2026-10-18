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
  5. attempts the LIVE surgepy leg (#150): global3/global4 parameter vectors
     read from the native post-loadPatch state and cross-checked against the
     graph (any disagreement REFUSES), plus the engine-side per-scene drift
     determinism gate (shared carrier_drift_screen gate; PASS is eligibility,
     never proof of repeatability -- decision record 0019). If the pinned
     oracle is unavailable this step records ok=false (never silently drops
     the preset, never fabricates a value) and the routing-verification
     checks above still proceed and are still written to the output record.

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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import _census_graphs_common as cgc  # noqa: E402
from refusal import Refuse  # noqa: E402

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


# The census-vs-graphs zero-drift comparison lives in ONE place for all the
# routing-form extractors (tools/_census_graphs_common.py, issue #154): the
# graph's stored FX type IDS are named through the census parser's own
# committed FX table, so the check compares CONTENT rather than the two
# artifacts' differing spellings. The previous local helper stripped spaces
# only, which resolves "Reverb 2" -> "Reverb2" but NOT "Freq Shift" ->
# "FrequencyShifter" or "Ring Mod" -> "RingModulator", and therefore refused
# on SPELLING for content-identical slots. These thin wrappers keep this
# module's local `Refuse` as the refusal type.
def census_fx_table():
    return cgc.census_fx_table()


def norm_type_name(name):
    return cgc.norm_type_name(name)


def cross_check(row, graph):
    """Zero-drift assertion between the two committed artifacts. Returns the
    per-field comparison record; raises Refuse on ANY disagreement."""
    return cgc.cross_check(row, graph, refuse=Refuse)


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


GRAPHS_VALUE_TOL = 5e-6   # graphs.jsonl stores float params rounded to 6 dp


def _param_record(s, p, graphs_value):
    """One live parameter row, cross-checked against the committed graph.
    `graphs.jsonl` stores int/bool params as ints and floats rounded to 6 dp,
    so the comparison is made in the graph's own representation. A
    disagreement is a REFUSAL: the committed corpus artifact and the live
    pinned engine must not be allowed to drift silently."""
    vtype = s.getParamValType(p)
    raw = float(s.getParamVal(p))
    live = int(round(raw)) if vtype in ("int", "bool") else round(raw, 6)
    if vtype in ("int", "bool"):
        agrees = int(live) == int(graphs_value)
    else:
        agrees = abs(float(live) - float(graphs_value)) <= GRAPHS_VALUE_TOL
    if not agrees:
        raise Refuse(f"live surgepy value for {p.getName()} ({live}) "
                     f"disagrees with corpus/normalized/graphs.jsonl "
                     f"({graphs_value}); refusing rather than preferring one "
                     f"artifact over the pinned engine")
    return {"name": p.getName(), "value": live, "value_type": vtype,
            "display": s.getParamDisplay(p), "graphs_value": graphs_value}


def try_live_oracle_extraction(carrier, graph):
    """LIVE surgepy leg (#150 item 1): per-slot algorithm parameter values for
    global3/global4 read from the pinned engine's normalized (post-loadPatch)
    state and cross-checked against graphs.jsonl, plus the engine-side
    per-scene drift determinism gate (the shared carrier_drift_screen gate).

    Returns (ok, detail, record_or_None). ok False = the pinned oracle is not
    installed here (NOT_RUN; the oracle-free routing checks stand alone). A
    contradiction between the live engine and the committed corpus artifacts
    is a Refuse, never a downgrade to "oracle unavailable".

    SCOPE: engine-side extraction + determinism gate only. Not a
    model-vs-pinned-engine agreement number and not an RTL claim."""
    try:
        import carrier_drift_screen as cds  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - environment-dependent
        return False, f"carrier_drift_screen import failed: {e}", None
    loader = cds.PinnedSurgepyLoader()
    try:
        info = loader.open()
    except cds.OracleAbsent as e:
        return False, f"surgepy unavailable (pinned oracle not installed " \
                      f"in this environment): {e}", None
    except Refuse as e:
        return False, f"oracle provenance BLOCKED: {e}", None
    try:
        s, patch, on_disk = loader.load(carrier["path"],
                                        carrier["declared_sha1"])
    except cds.LoadRefusal as e:
        raise Refuse(f"{e.code}: {e.detail}") from e

    live_types = [int(round(s.getParamVal(patch["fx"][i]["type"])))
                  for i in range(len(graph["g"]["fx"]))]
    graph_types = [fx.get("t", 0) for fx in graph["g"]["fx"]]
    if live_types != graph_types:
        raise Refuse(f"live fx type vector disagrees with graphs.jsonl for "
                     f"{carrier['path']}: engine={live_types} "
                     f"graphs={graph_types}")
    live_fxb = int(round(s.getParamVal(patch["fx_bypass"])))
    live_fxd = int(round(s.getParamVal(patch["fx_disable"])))
    if (live_fxb, live_fxd) != (graph["g"]["fxb"], graph["g"]["fxd"]):
        raise Refuse(f"live fx_bypass/fx_disable {(live_fxb, live_fxd)} "
                     f"disagree with graphs.jsonl "
                     f"{(graph['g']['fxb'], graph['g']['fxd'])}")

    slots = {}
    for role, slot in (("global3", FXSLOT_GLOBAL3),
                       ("global4", FXSLOT_GLOBAL4)):
        gfx = slot_entry(graph, role)
        fx = patch["fx"][slot]
        rec = {"slot": slot, "occupied": bool(gfx.get("on", 0)),
               "type_id": int(round(s.getParamVal(fx["type"]))),
               "type_display": s.getParamDisplay(fx["type"])}
        if not rec["occupied"]:
            rec["params"] = None
            rec["return_level"] = None
        else:
            gp = gfx.get("p")
            if gp is None or len(gp) != len(fx["p"]):
                raise Refuse(f"graphs.jsonl {role} parameter vector has "
                             f"{None if gp is None else len(gp)} entries, "
                             f"engine exposes {len(fx['p'])}")
            rec["params"] = [_param_record(s, p, gp[j])
                             for j, p in enumerate(fx["p"])]
            rl = round(float(s.getParamVal(fx["return_level"])), 6)
            if abs(rl - float(gfx["rl"])) > GRAPHS_VALUE_TOL:
                raise Refuse(f"live {role} return_level {rl} disagrees with "
                             f"graphs.jsonl {gfx['rl']}")
            rec["return_level"] = rl
        slots[role] = rec

    record = {
        "ran": True,
        "engine": {"pin": info["pin"],
                   "surgepy_version": info["surgepy_version"],
                   "sample_rate": info["sample_rate"],
                   "provenance_mode": info["provenance"]["mode"],
                   "surgepy_module_sha256": info["binding"]["module_sha256"]},
        "preset_blob_sha1_on_disk": on_disk,
        "determinism_gate": cds.DRIFT_GATE(s, patch),
        "fx_type_vector_matches_graphs": True,
        "fx_bypass_fx_disable_match_graphs": True,
        "slots": slots,
        "claim_scope": "ENGINE-SIDE extraction + determinism gate only. NOT "
                       "a model-vs-pinned-engine agreement number and NOT an "
                       "RTL claim.",
    }
    summary = (f"LIVE surgepy leg RAN against {info['surgepy_version']}: "
               f"global3/global4 parameters cross-checked against "
               f"graphs.jsonl; drift gate "
               f"{record['determinism_gate']['status']}")
    return True, summary, record


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

    oracle_ok, oracle_detail, oracle_live = \
        try_live_oracle_extraction(carrier, graph)

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
                              "detail": oracle_detail, "live": oracle_live},
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
