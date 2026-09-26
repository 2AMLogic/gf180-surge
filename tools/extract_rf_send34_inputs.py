#!/usr/bin/env python3
"""SXT-028l: fail-closed extraction of routing-form (Send buses 3-4, the
extended rack half) carrier metadata from the pinned engine's committed
corpus artifacts.

For each carrier preset this tool:
  1. re-verifies the census blob sha1 (corpus/census-v0.1/results/
     per-preset.csv) against the declared sha1, REFUSING on mismatch;
  2. cross-checks the normalized corpus graph (corpus/normalized/graphs.jsonl,
     SXT-011 output -- already surgepy-derived and committed, so no live
     oracle call is needed for this step) for the send3/send4 slot roles:
     occupancy (on/off), FX type name/id, the stored per-slot return_level
     (which this routing form REALLY DOES consume, unlike the insert/global
     forms), and the patch-level fxb (fx_bypass) / fxd (fx_disable) fields;
  3. records the scene context (scene mode; whether scene B is instantiated
     at all) because each send bus sums BOTH scenes' post-insert outputs, and
     the base-half context (send1/send2 occupancy) because those buses are
     co-tenants of the same main bus -- this leaf's declared seam;
  4. REFUSES to emit any per-scene send LEVEL for buses 3/4. That is the
     documented SXT-011 exposure gap (corpus/normalized/README.md "Send
     levels 3/4"; corpus/normalized/schema.json `scene.send`): a `.fxp`
     stores only two per-scene send levels and the surgepy binding exposes
     only `send_level[0..1]`, so buses 3/4 run at LOADER DEFAULTS for every
     corpus preset and no in-repo artifact carries a value. The gap is
     written into every record as `send_level_gap` with `stored: null` --
     never a fabricated default -- and is re-verified mechanically here (the
     committed corpus really does carry exactly two send levels per scene,
     never four). Fixture freezing for this routing form is therefore gated
     on the SXT-017 data-gap policy decision (#12);
  5. asserts ZERO DRIFT between the two independently-derived committed
     artifacts (census CSV vs normalized graph) on every field both carry:
     blob sha1, stored revision, scene mode, fx_bypass, fx_disable, the
     non-off FX slot count and the non-off FX type set. Any disagreement is a
     REFUSAL, never a silently-preferred source;
  6. attempts a LIVE surgepy extraction of the per-slot algorithm's own
     parameter values, the loader-default send levels for buses 3/4 and the
     engine-side determinism gate (per-scene drift == 0) -- all needed only
     for an eventual concrete-occupant reference render, which is out of THIS
     leaf's routing-form scope. If the pinned oracle build (surgepy) is
     unavailable in the current environment, this step REFUSES explicitly
     (never silently drops the preset, never fabricates a value) and the
     routing-verification checks above still proceed and are still written to
     the output record.

CARRIER SET. The first three carriers are the B4-scope presets named by the
issue (reports/sxt-028/leaves/SXT-028l.json `carriers.top_presets`). Unlike
the sibling global-rack leaf, one of them (`Batbrass.fxp`) really does occupy
BOTH send buses, so the issue's own carriers do reach the two-concurrent-
instance shape. Three further carriers are added from the same committed
corpus for routing SHAPES the acceptance checklist needs, verified by the
identical fail-closed path:
  * Strynth.fxp -- the SAME FX class (Nimbus) in BOTH send3 and send4 AND a
    Dual scene mode, i.e. the same-class dual-instance shape with scene B
    actually contributing to both buses.
  * Closeout Sale @ Electro Percussion Warehouse.fxp -- both slots occupied
    AND fx_disable = 13107, whose bits 12 and 13 are BOTH set: the
    real-corpus instance of this leaf's own per-slot disable gate.
  * Random Bass FX.fxp -- both slots occupied with return_level 0.0 on BOTH:
    the return-muted shape, which only exists because this routing form
    consumes `return_level` at all.
The additions are recorded as such (`carrier_source`), never presented as
issue-named carriers.

Writes model/effects/fx_inputs/rf-rf-send34-<slug>.json plus
reports/SXT-028l/artifacts/{extract-refusals.txt, corpus-occupancy.json,
send-level-gap.json} (the refusal transcript is created even when empty,
matching the SXT-023/028c/028d/028h/028j refusal-log convention -- absence of
oracle coverage is recorded, never silently dropped).

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, and only for the item-6 attempt.
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
FXSLOT_SEND1, FXSLOT_SEND2 = 4, 5
FXSLOT_SEND3, FXSLOT_SEND4 = 12, 13

# The engine has four send buses; a .fxp stores (and surgepy exposes) only the
# first two per-scene send levels. Asserted mechanically against the committed
# corpus by `send_level_gap_scan()`.
N_SEND_SLOTS = 4
N_SEND_LEVELS_EXPOSED = 2

SEND_LEVEL_GAP_REASON = (
    "SXT-011 exposure gap: the engine has 4 send buses but a .fxp stores only "
    "2 per-scene send levels and surgepy exposes only send_level[0..1] "
    "(corpus/normalized/README.md 'Send levels 3/4'; "
    "corpus/normalized/schema.json scene.send). Buses 3/4 run at LOADER "
    "DEFAULTS for every corpus preset; no in-repo artifact carries a value, "
    "so none is emitted here. Resolving it needs an engine-behavior probe of "
    "the loader default plus an SXT-017 data-gap policy decision (#12) before "
    "reference fixtures for this routing form can be frozen."
)

CARRIERS = [
    # --- the three B4-scope carriers named by issue #64 / SXT-028l.json ---
    {"slug": "trance",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Basses/Trance.fxp",
     "declared_sha1": "c277c51ec0094a57c5fc219b3763db3801d7869e",
     "carrier_source": "issue-named B4-scope carrier"},
    {"slug": "batbrass",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Brass/Batbrass.fxp",
     "declared_sha1": "e6b6f04bea58347fe3b999bc8ba19a0f7a36febf",
     "carrier_source": "issue-named B4-scope carrier"},
    {"slug": "dystopia",
     "path": "resources/data/patches_3rdparty/Exquis MPE/FX/Dystopia.fxp",
     "declared_sha1": "f884c4d1c866fdb2c50ec8bf67cf8c5345156f7d",
     "carrier_source": "issue-named B4-scope carrier"},
    # --- shape carriers added by this leaf (see module docstring) ---
    {"slug": "strynth",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Strings/Strynth.fxp",
     "declared_sha1": "f8c9666992e671d8ee5761d76867890c4c75c4ce",
     "carrier_source": "added by this leaf: SAME FX class (Nimbus) in both "
                       "send3 and send4 AND a Dual scene mode (scene B "
                       "really feeds both buses)"},
    {"slug": "closeout-sale",
     "path": "resources/data/patches_3rdparty/Kinsey Dulcet/Percussion/"
             "Closeout Sale @ Electro Percussion Warehouse.fxp",
     "declared_sha1": "e9238ad6f88e416d7db31c83af85b802fbc7e75b",
     "carrier_source": "added by this leaf: both slots occupied AND both "
                       "disabled by fx_disable bits 12|13 (mask 13107)"},
    {"slug": "random-bass-fx",
     "path": "resources/data/patches_3rdparty/Slowboat/FX/Random Bass FX.fxp",
     "declared_sha1": "e0b6b1d01a6dd1f696823056067bc3625e791075",
     "carrier_source": "added by this leaf: both slots occupied with "
                       "return_level 0.0 on BOTH (the return-muted shape; "
                       "this routing form is the one that consumes "
                       "return_level)"},
]

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
OUT_DIR = os.path.join(REPO, "model", "effects", "fx_inputs")
ARTIFACTS = os.path.join(REPO, "reports", "SXT-028l", "artifacts")
REFUSALS = os.path.join(ARTIFACTS, "extract-refusals.txt")
OCCUPANCY = os.path.join(ARTIFACTS, "corpus-occupancy.json")
GAP = os.path.join(ARTIFACTS, "send-level-gap.json")


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
    """Normalize an FX type name for set comparison (spaces only)."""
    return "".join(str(name).split())


CENSUS_FX_TABLE = None


def census_fx_table():
    """The census parser's own static FX-type table (`corpus/census-v0.1/
    census.py` `FX`), indexed by stored type id.

    Why this exists. The census CSV names an FX by that table
    ("FrequencyShifter", "RingModulator"); the normalized graph names the
    same slot by the ENGINE's live display name ("Freq Shift", "Ring Mod").
    Those spellings genuinely differ for several FX types, so a name-vs-name
    comparison would refuse on SPELLING rather than on content. Comparing the
    graph's stored type IDS mapped through the census's OWN committed table
    against the census CSV's names keeps the cross-check an exact,
    fail-closed comparison of CONTENT (which FX is in which slot), with a
    single in-repo naming authority and no invented alias list. The engine
    display names are still recorded alongside, as context.
    """
    global CENSUS_FX_TABLE
    if CENSUS_FX_TABLE is None:
        import importlib.util  # noqa: PLC0415
        path = os.path.join(REPO, "corpus", "census-v0.1", "census.py")
        spec = importlib.util.spec_from_file_location("sxt028l_census", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        CENSUS_FX_TABLE = list(mod.FX)
    return CENSUS_FX_TABLE


def cross_check(row, graph):
    """Zero-drift assertion between the two committed artifacts. Returns the
    per-field comparison record; raises Refuse on ANY disagreement."""
    g = graph["g"]
    on_slots = [fx for fx in g["fx"] if fx.get("on", 0)]
    table = census_fx_table()
    census_types = {norm_type_name(t)
                    for t in row["stored_nonoff_fx_types"].split(";") if t}
    # the graph's stored type IDS, named through the census's OWN table --
    # a content comparison, not a spelling one (see census_fx_table())
    graph_types = set()
    for fx in on_slots:
        tid = fx.get("t")
        if not isinstance(tid, int) or not 0 <= tid < len(table):
            raise Refuse(f"graphs.jsonl fx type id {tid!r} outside the "
                         f"census FX table (0..{len(table) - 1})")
        graph_types.add(norm_type_name(table[tid]))
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
            "values": {k: checks[k][0] for k in checks},
            "fx_type_name_authority":
                "corpus/census-v0.1/census.py FX table, applied to the "
                "graph's stored type ids (content comparison, not spelling)",
            "engine_display_names_context":
                sorted({fx.get("tn") for fx in on_slots})}


def role_index_check(graph):
    """Re-derive this leaf's slot indices from the committed corpus role
    table itself (no live oracle). REFUSES if the record disagrees with the
    frozen model's FXSLOT_SEND3/4 (or the base half's 4/5)."""
    roles = {fx.get("i"): fx.get("r") for fx in graph["g"]["fx"]}
    expect = {FXSLOT_SEND1: "send1", FXSLOT_SEND2: "send2",
              FXSLOT_SEND3: "send3", FXSLOT_SEND4: "send4"}
    bad = {i: (roles.get(i), r) for i, r in expect.items() if roles.get(i) != r}
    if bad:
        raise Refuse(f"graphs.jsonl slot-index/role table disagrees with the "
                     f"frozen model's fxslot constants: {bad}")
    return {"verified_indices": {str(i): r for i, r in expect.items()},
            "source": "corpus/normalized/graphs.jsonl fx[].i / fx[].r "
                      "(SXT-011 output; no live oracle needed)"}


def send_level_check(graph):
    """Fail-closed send-level record for ONE preset. The exposed per-scene
    levels (buses 1/2) are recorded as context; buses 3/4 get `null` plus the
    documented gap reason. REFUSES if a record ever carries more than the
    documented two levels per scene (that would mean the gap has been closed
    upstream and this leaf's contract must be revisited, not silently
    reinterpreted)."""
    per_scene = []
    for sc in graph["g"]["sc"]:
        levels = sc.get("send")
        if levels is None:
            raise Refuse("scene record carries no `send` array")
        if len(levels) != N_SEND_LEVELS_EXPOSED:
            raise Refuse(
                f"scene record carries {len(levels)} send levels, expected "
                f"{N_SEND_LEVELS_EXPOSED}: the SXT-011 exposure gap this "
                f"leaf's contract is built on may have changed upstream -- "
                f"refusing rather than reinterpreting")
        per_scene.append(levels)
    return {
        "exposed_levels_per_scene": per_scene,
        "exposed_bus_indices": [1, 2],
        "send3_send4_levels_stored": None,
        "reason": SEND_LEVEL_GAP_REASON,
        "blocking_issue": "#12 (SXT-017 data-gap policy decision)",
        "consumed_by_this_leaf_as": "control-plane stimulus only "
                                    "(model/effects/rf-rf-send34: "
                                    "send_gain_a / send_gain_b); never "
                                    "derived from a corpus record",
    }


def try_live_oracle_extraction(rel_path):
    """Attempt a live surgepy extraction of the per-slot algorithm's own
    parameters, the loader-default send levels for buses 3/4, and the
    engine-side determinism gate (per-scene drift == 0). Returns
    (ok, detail_or_reason). This is the ONLY step that needs the built oracle;
    nothing above depends on it."""
    try:
        import oracle_common as oc  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - environment-dependent
        return False, f"oracle_common import failed: {e}"
    try:
        surgepy = oc.import_surgepy()
    except Exception as e:
        return False, f"surgepy unavailable (oracle not built in this " \
                      f"environment): {e}"
    # surgepy present: per-slot parameter extraction, the per-scene drift
    # determinism gate and the send-level loader-default probe would run here.
    # The first is algorithm-leaf scope; the last is the SXT-017 data-gap
    # decision's input (#12), not this leaf's to settle. Recorded as available
    # but not exercised by this routing-form leaf.
    return True, f"surgepy present ({surgepy.__file__}); per-slot parameter " \
                 f"extraction, the engine-side drift gate and the " \
                 f"loader-default send-level probe for buses 3/4 are NOT " \
                 f"exercised here (algorithm-leaf scope and SXT-017 #12 " \
                 f"scope respectively)"


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
    gap = send_level_check(graph)

    s3 = slot_entry(graph, "send3")
    s4 = slot_entry(graph, "send4")
    s1 = slot_entry(graph, "send1")
    s2 = slot_entry(graph, "send2")
    fxb = graph["g"]["fxb"]
    fxd = graph["g"]["fxd"]
    scene_mode_name = graph["g"].get("smn")
    scene_b_instantiated = scene_mode_name != "Single"

    oracle_ok, oracle_detail = try_live_oracle_extraction(rel)

    def slot_doc(fx, bit):
        return {"occupied": bool(fx.get("on", 0)),
                "type_name": fx.get("tn"),
                "type_id": fx.get("t"),
                "airwindows_sub_id": fx.get("aw"),
                "airwindows_sub_name": fx.get("awn"),
                "fx_disable_bit": bool((fxd >> bit) & 1),
                "return_level_stored": fx.get("rl"),
                "return_level_consumed_by_send_path": True,
                "return_muted": fx.get("rl") == 0.0 if fx.get("on", 0) else None}

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "routing_form": "rf-send34",
        "roles": ["send3", "send4"],
        "carrier_source": carrier["carrier_source"],
        "preset": {"path": rel, "bank": graph.get("b"),
                   "census_blob_sha1_verified": row["git_blob_sha1"],
                   "graphs_blob_sha1_verified": graph.get("sha"),
                   "census_status": row["status"],
                   "stored_revision": graph.get("rev")},
        "patch_level": {"fx_bypass": fxb,
                        "fx_bypass_name": graph["g"].get("fxbn"),
                        "fx_disable_mask": fxd,
                        "send_stage_runs_in_this_mode": fxb == 0},
        "scene_context": {
            "note": "each send bus sums BOTH scenes' post-insert outputs "
                    "through that scene's own send level; in Single scene "
                    "mode the engine never instantiates scene B, so only "
                    "scene A feeds the buses",
            "scene_mode": scene_mode_name,
            "scene_mode_id": graph["g"].get("sm"),
            "scene_b_instantiated": scene_b_instantiated,
        },
        "base_half_context": {
            "note": "send1/send2 are the BASE half of the same send rack. "
                    "They are not upstream of this leaf (the buses are "
                    "parallel) -- they are co-tenants of the same main bus, "
                    "so their returns are part of this leaf's `main_l`/"
                    "`main_r` stimulus. A sibling rf-send12-class leaf's "
                    "scope; no such leaf exists in this repository yet.",
            "send1_occupied": bool(s1.get("on", 0)),
            "send1_type_name": s1.get("tn"),
            "send2_occupied": bool(s2.get("on", 0)),
            "send2_type_name": s2.get("tn"),
            "base_half_slots_active": int(bool(s1.get("on", 0))) +
                                      int(bool(s2.get("on", 0))),
        },
        "send_level_gap": gap,
        "send3": slot_doc(s3, FXSLOT_SEND3),
        "send4": slot_doc(s4, FXSLOT_SEND4),
        "dual_instance_concurrent": bool(s3.get("on", 0)) and
                                    bool(s4.get("on", 0)),
        "same_class_both_buses": bool(s3.get("on", 0)) and
                                 bool(s4.get("on", 0)) and
                                 s3.get("tn") == s4.get("tn"),
        "both_slots_disabled": bool((fxd >> FXSLOT_SEND3) & 1) and
                               bool((fxd >> FXSLOT_SEND4) & 1),
        "cross_check": xcheck,
        "slot_index_check": idx_check,
        "applicability": {
            "routing_metadata_verified": True,
            "complete_wet_render_possible": False,
            "complete_wet_render_reason":
                "per-slot algorithm parameter extraction and any wet-audio "
                "render require the pinned oracle (surgepy); additionally, "
                "fixture freezing for THIS routing form is gated on the "
                "SXT-017 send-level data-gap decision (#12). This leaf's own "
                "routing/scheduling claims depend on neither -- see "
                "oracle_extraction and send_level_gap",
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
    s3_on = s4_on = both = same_class = 0
    dis3 = dis4 = dis_both = 0
    nonzero_bypass = 0
    dual_scene_with_occupant = 0
    zero_return = 0
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            total += 1
            fx = {e.get("r"): e for e in g["g"]["fx"]}
            a = bool(fx.get("send3", {}).get("on", 0))
            b = bool(fx.get("send4", {}).get("on", 0))
            fxd = g["g"].get("fxd", 0)
            s3_on += a
            s4_on += b
            if a and b:
                both += 1
                if fx["send3"].get("tn") == fx["send4"].get("tn"):
                    same_class += 1
            d3 = bool((fxd >> FXSLOT_SEND3) & 1)
            d4 = bool((fxd >> FXSLOT_SEND4) & 1)
            dis3 += d3
            dis4 += d4
            dis_both += d3 and d4
            if g["g"].get("fxb", 0) != 0 and (a or b):
                nonzero_bypass += 1
            if (a or b) and g["g"].get("smn") != "Single":
                dual_scene_with_occupant += 1
            if (a and fx["send3"].get("rl") == 0.0) or \
               (b and fx["send4"].get("rl") == 0.0):
                zero_return += 1
    return {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "source": "corpus/normalized/graphs.jsonl (SXT-011 output)",
        "claim_scope": "COVERAGE accounting only -- an inventory of which "
                       "corpus presets exercise this routing form's shapes. "
                       "NOT a support claim and NOT an agreement number.",
        "presets_scanned": total,
        "send3_occupied": s3_on,
        "send4_occupied": s4_on,
        "both_buses_occupied": both,
        "both_buses_occupied_same_fx_class": same_class,
        "fx_disable_bit12_set": dis3,
        "fx_disable_bit13_set": dis4,
        "fx_disable_both_bits_set": dis_both,
        "non_all_fx_bypass_with_a_send34_occupant": nonzero_bypass,
        "non_single_scene_mode_with_a_send34_occupant": dual_scene_with_occupant,
        "occupied_bus_with_return_level_zero": zero_return,
    }


def send_level_gap_scan():
    """Corpus-wide, mechanical re-verification of the SXT-011 send-level
    exposure gap this leaf's contract depends on: every scene record in the
    committed corpus carries exactly TWO per-scene send levels, never four.
    If that ever stops being true the gap has been closed upstream and this
    leaf's fixture contract must be revisited."""
    scenes = 0
    lengths = {}
    presets = 0
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)["g"]
            presets += 1
            for sc in g["sc"]:
                scenes += 1
                n = len(sc.get("send", []))
                lengths[str(n)] = lengths.get(str(n), 0) + 1
    return {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "gap": "per-scene send levels for send buses 3/4 are not stored in "
               "any .fxp and are not exposed by surgepy",
        "reason": SEND_LEVEL_GAP_REASON,
        "engine_send_buses": N_SEND_SLOTS,
        "levels_exposed_per_scene": N_SEND_LEVELS_EXPOSED,
        "presets_scanned": presets,
        "scene_records_scanned": scenes,
        "send_array_length_histogram": lengths,
        "gap_holds_across_the_whole_corpus":
            list(lengths) == [str(N_SEND_LEVELS_EXPOSED)],
        "consequence": "this leaf consumes the per-scene send gains for buses "
                       "3/4 as CONTROL-PLANE STIMULUS and emits no corpus-"
                       "derived value; reference-fixture freezing for this "
                       "routing form is gated on the SXT-017 data-gap policy "
                       "decision (#12). The RTL-vs-frozen-model exactness "
                       "claim does not depend on the gap being closed.",
        "blocking_issue": "#12 (SXT-017)",
        "status": "BLOCKED (policy decision pending, #12) -- recorded, not "
                  "worked around",
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
                                f"rf-rf-send34-{carrier['slug']}.json")
        with open(out_path, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out_path)
        print(f"wrote {out_path}")

    with open(OCCUPANCY, "w") as f:
        json.dump(corpus_occupancy(), f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {OCCUPANCY}")

    with open(GAP, "w") as f:
        json.dump(send_level_gap_scan(), f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {GAP}")

    with open(REFUSALS, "w") as f:
        f.write("\n".join(refusal_lines) + ("\n" if refusal_lines else ""))
    for line in refusal_lines:
        print(line)
    return 0 if len(written) == len(CARRIERS) else 1


if __name__ == "__main__":
    sys.exit(main())
