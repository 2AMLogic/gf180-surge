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
  4. LIVE leg (#424): on the pinned oracle, natively `loadPatch`es the
     preset, reads the slot types / fx_bypass / fx_disable / scene mode back
     from the NATIVE normalized state, checks them against the carrier's
     declared shape (tools/screen_rf_bins12_carriers.py::SHAPES), and runs the
     shared per-voicing-scene drift gate (tools/carrier_drift_screen.py, #423).
     The per-carrier observation is recorded, not deferred. Per-slot algorithm
     parameter extraction and wet rendering remain out of THIS leaf's scope.
     If the pinned oracle is unavailable, the live leg is NOT_RUN (never
     fabricated; the static checks still proceed), any previously
     committed live observation is RETAINED, a record whose content did not
     otherwise change is left byte-identical, and the CLI exits 2. A
     provenance BLOCKED or a fresh native refusal is recorded as the current
     result (ok false); a prior live observation then survives only as
     STALE history (`prior_live_observation`), never as current evidence.
     Drift-gate eligibility is separately derived from the committed
     reports/SXT-028h/artifacts/carrier-drift-screen.json; drift PASS is
     necessary, never sufficient, for render eligibility.

Writes model/effects/fx_inputs/rf-rf-bins12-<slug>.json plus a refusal
transcript at reports/SXT-028h/artifacts/extract-refusals.txt (created even
when empty, matching the SXT-023/028c/028d refusal-log convention -- absence
of oracle coverage is recorded, never silently dropped).

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, and only for the item-4 attempt.
"""

import copy
import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import _census_graphs_common as cgc  # noqa: E402
import carrier_drift_screen as cds  # noqa: E402
import screen_rf_bins12_carriers as scr  # noqa: E402
from refusal import Refuse  # noqa: E402

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

# Labeled ADDITIONS (#424): the deterministic selection (first drift-gate PASS
# path in byte order among the same-shape candidates, excluding the original)
# recorded in reports/SXT-028h/artifacts/carrier-drift-screen.json. They are
# additions beside the originals, never silent substitutions; a test pins this
# list to the committed screen record. Drift PASS is necessary, never
# sufficient, for render eligibility.
ADDITIONS = [
    {"slug": "add-novuo-shape", "declared_sha1": "59a29d3c061e224354bcd095931478b528dca632",
     "role": "addition", "replaces_original_slug": "novuo",
     "path": "resources/data/patches_3rdparty/Aleksey Zhehanov/Pads/"
             "Winter Breath.fxp"},
    {"slug": "add-acoordion-basses-shape", "declared_sha1": "3090cd0f9b5f89a390ca0bdcc89a9d527760dfec",
     "role": "addition", "replaces_original_slug": "acoordion-basses",
     "path": "resources/data/patches_3rdparty/Bluelight/Splits/"
             "Royals Straight Flushed 110 BPM.fxp"},
    {"slug": "add-shore-shape", "declared_sha1": "ccf42b0e8bdc1c7884b3badbd3b26c6ec4ba0aba",
     "role": "addition", "replaces_original_slug": "shore",
     "path": "resources/data/patches_3rdparty/A.Liv/Basses/"
             "808er Than 808.fxp"},
]
for _c in CARRIERS:
    _c["role"] = "original"
    _c["shape_slug"] = _c["slug"]
for _a in ADDITIONS:
    _a["shape_slug"] = _a["replaces_original_slug"]

SCREEN_RECORD = scr.SCREEN_RECORD
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
OUT_DIR = os.path.join(REPO, "model", "effects", "fx_inputs")
REFUSALS = os.path.join(REPO, "reports", "SXT-028h", "artifacts",
                        "extract-refusals.txt")


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


def recompute_drift_eligibility(scene_mode_id, scene_active, drift_by_scene):
    """Independent recomputation of the drift-gate verdict from the recorded
    per-scene drift (NOT from a recorded status string). Voicing scenes: the
    active scene in Single mode (id 0), both scenes otherwise. Read-back is
    compared after the same nine-decimal rounding as
    extract_rf_send34_inputs.drift_gate. A voicing scene with no recorded
    value is ineligible (cannot be shown to be 0)."""
    voicing = [scene_active] if scene_mode_id == 0 else [0, 1]
    names = ["AB"[i] for i in voicing]
    missing = [n for n in names if n not in drift_by_scene]
    ok = not missing and all(round(float(drift_by_scene[n]), 9) == 0.0
                             for n in names)
    return {"voicing_scenes": names, "missing_scenes": missing,
            "drift_gate_eligible": ok, "read_back_decimals": 9}


def load_screen_record(path=None):
    p = path or SCREEN_RECORD
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def carrier_eligibility(carrier, record):
    """Drift-gate eligibility of a declared carrier, derived from the
    committed live screen record (recomputed from its recorded drift, and
    required to agree with the recorded gate status). Never a render
    eligibility claim."""
    base = {"render_eligibility": "NOT_ESTABLISHED",
            "scope": "drift-gate screening condition only; necessary, never "
                     "sufficient, for render eligibility"}
    if record is None:
        return dict(base, drift_gate_eligible=False,
                    status="NOT_RUN",
                    reason="no committed live screen record")
    shape = record["shapes"][carrier["shape_slug"]]
    cand = next((c for c in shape["run"].get("candidates", [])
                 if c["path"] == carrier["path"]), None)
    if cand is None or not cand.get("screened"):
        return dict(base, drift_gate_eligible=False, status="NO_VERDICT",
                    reason="carrier not screened in the committed record: "
                           f"{(cand or {}).get('refusal')}")
    gate = cand["determinism_gate"]
    native = cand["native_state"]
    rc = recompute_drift_eligibility(
        native["scene_mode_id"], native["scene_active"],
        gate["drift_per_voicing_scene"])
    if rc["drift_gate_eligible"] != (gate["status"] == "PASS"):
        raise Refuse(f"recorded gate status {gate['status']} disagrees with "
                     f"the recomputed verdict for {carrier['path']}")
    return dict(base, drift_gate_eligible=rc["drift_gate_eligible"],
                status="PASS" if rc["drift_gate_eligible"] else "FAIL",
                role=carrier["role"],
                shape_id=scr.SHAPES[carrier["shape_slug"]]["shape_id"],
                drift_per_voicing_scene=gate["drift_per_voicing_scene"],
                voicing_scenes=rc["voicing_scenes"],
                read_back_decimals=rc["read_back_decimals"],
                non_render_eligible=not rc["drift_gate_eligible"],
                reason=None if rc["drift_gate_eligible"] else
                "nonzero drift in a voicing scene; preserved, not removed")


_LIVE = {}


def _live_loader():
    """Open the pinned live loader once per process (full provenance check).
    Returns (loader, None) or (None, reason)."""
    if "v" not in _LIVE:
        loader = cds.PinnedSurgepyLoader()
        try:
            loader.open()
            _LIVE["v"] = (loader, None)
        except cds.OracleAbsent as e:
            _LIVE["v"] = (None, f"NOT_RUN: pinned oracle unavailable: {e}")
        except Refuse as e:
            _LIVE["v"] = (None, f"BLOCKED: {e}")
    return _LIVE["v"]


def try_live_oracle_extraction(carrier, graph, loader=None):
    """LIVE leg (#424): native load + shape read-back against the declared
    shape + the shared per-voicing-scene drift gate, for ONE carrier.
    Returns (ok, detail, live_or_None). `ok` means a native drift observation
    was obtained (NOT that the gate passed). Nothing here fabricates a value:
    an absent oracle yields (False, reason, None)."""
    if loader is None:
        loader, why = _live_loader()
        if loader is None:
            return False, why, None
    spec = scr.SHAPES[carrier["shape_slug"]]
    observed = {}
    cand = {"path": carrier["path"],
            "graphs_blob_sha1": carrier["declared_sha1"], "graph": graph["g"]}
    rec = cds.screen_candidate(loader, cand,
                               scr.make_shape_check(spec, observed),
                               cds.DRIFT_GATE)
    rec["native_state"] = observed.get(carrier["path"])
    if not rec["screened"]:
        return False, f"live leg refused: {rec['refusal']}", None
    g = rec["determinism_gate"]
    return True, ("native load + shape read-back + per-scene drift gate "
                  f"observed: {g['status']} "
                  f"{g['drift_per_voicing_scene']}"), {
        "live": True, "gate_status": g["status"],
        "engine_pin": cds.ENGINE_PIN, "record": rec}


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

    oracle_ok, oracle_detail, oracle_live = \
        try_live_oracle_extraction(carrier, graph)
    eligibility = carrier_eligibility(carrier, load_screen_record())

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
        "carrier_role": carrier["role"],
        "drift_eligibility": eligibility,
        "oracle_extraction": {"attempted": True, "ok": oracle_ok,
                              "detail": oracle_detail,
                              "live": oracle_live},
    }
    return doc


def live_leg_status(ox):
    """Classify THIS run's live leg from its oracle_extraction block:
    LIVE (a native observation was obtained), NOT_RUN (pinned oracle absent),
    BLOCKED (provenance refusal while opening the pinned oracle) or REFUSED
    (the native leg ran and refused this carrier, e.g. a shape mismatch)."""
    if ox.get("live"):
        return "LIVE"
    detail = ox.get("detail") or ""
    if detail.startswith("NOT_RUN"):
        return "NOT_RUN"
    if detail.startswith("BLOCKED"):
        return "BLOCKED"
    return "REFUSED"


def merge_prior_live(doc, prior):
    """Combine this run's live leg with a prior committed record.

    Prior LIVE evidence is retained as current ONLY for a true NOT_RUN (the
    pinned oracle is absent here, so nothing new was observed). A BLOCKED
    (provenance refusal) or REFUSED (fresh native refusal) result is a new
    negative observation: it is recorded as the current result (`ok: false`,
    `live: None`) and any prior live observation is kept only as STALE
    history under `prior_live_observation`, never presented as current."""
    ox = doc["oracle_extraction"]
    pox = (prior or {}).get("oracle_extraction") or {}
    status = live_leg_status(ox)
    if status == "LIVE":
        return doc
    current_run = {"status": status, "detail": ox["detail"]}
    if status == "NOT_RUN":
        if pox.get("live"):
            keep = {k: v for k, v in pox.items()
                    if k not in ("current_run", "prior_live_observation")}
            doc["oracle_extraction"] = dict(
                keep, retained_from_prior_live_run=True,
                current_run=current_run)
        else:
            doc["oracle_extraction"] = dict(ox, current_run=current_run)
        return doc
    new = dict(ox, ok=False, live=None, current_run=current_run)
    prior_live = pox.get("live") and pox or pox.get("prior_live_observation")
    if prior_live:
        stale = {k: v for k, v in prior_live.items()
                 if k not in ("current_run", "prior_live_observation",
                              "retained_from_prior_live_run", "status")}
        new["prior_live_observation"] = dict(
            stale, status="STALE",
            reason=f"superseded by a {status} live leg in a later run; "
                   "historical only, not current evidence")
    doc["oracle_extraction"] = new
    return doc


def _strip_current_run(doc):
    d = copy.deepcopy(doc)
    ox = d.get("oracle_extraction", {})
    ox.pop("current_run", None)
    ox.pop("retained_from_prior_live_run", None)
    return d


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(REFUSALS), exist_ok=True)
    refusal_lines = []
    written = []
    not_run = 0
    for carrier in CARRIERS + ADDITIONS:
        try:
            doc = extract_one(carrier)
        except Refuse as e:
            refusal_lines.append(f"{carrier['slug']}: REFUSED: {e}")
            continue
        out_path = os.path.join(OUT_DIR, f"rf-rf-bins12-{carrier['slug']}.json")
        prior = None
        if os.path.exists(out_path):
            with open(out_path) as f:
                prior = json.load(f)
            doc = merge_prior_live(doc, prior)
        status = (doc["oracle_extraction"].get("current_run")
                  or {"status": "LIVE"})["status"]
        if status == "NOT_RUN":
            not_run += 1
            # nothing live was observed: if nothing else changed either, leave
            # the committed record byte-identical (no host-specific detail)
            if prior is not None and \
                    _strip_current_run(doc) == _strip_current_run(prior):
                written.append(out_path)
                print(f"NOT_RUN: left {out_path} unchanged "
                      f"({doc['oracle_extraction']['current_run']['detail']})")
                continue
        with open(out_path, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out_path)
        print(f"wrote {out_path}")

    content = "\n".join(refusal_lines) + ("\n" if refusal_lines else "")
    old = open(REFUSALS).read() if os.path.exists(REFUSALS) else None
    if old != content:
        with open(REFUSALS, "w") as f:
            f.write(content)
    for line in refusal_lines:
        print(line)
    if len(written) != len(CARRIERS) + len(ADDITIONS):
        return 1
    return 2 if not_run else 0


if __name__ == "__main__":
    sys.exit(main())
