#!/usr/bin/env python3
"""SXT-028h / #424: screen same-shape, drift-zero rf-bins12 carriers.

Background. reports/SXT-028l/artifacts/same-class-carrier-screen.json::
sibling_render_carrier_audit measured all three originally declared rf-bins12
carriers (A.Liv/Leads/Novuo, Aleksey Zhehanov/Keys/Acoordion Basses,
Altenberg/FX/Shore) with a nonzero per-scene engine drift, so none has a
repeatable render. This tool asks whether a corpus preset with the SAME
routing/occupancy shape as each original has drift 0. It uses the shared
helper tools/carrier_drift_screen.py (#423) for enumeration, provenance,
native load and the per-scene drift gate; only the SHAPE PREDICATES, the
native shape read-back and the selection rule live here.

The shape of each original is declared EXPLICITLY below (SHAPES), before any
screening, from the leaf evidence (reports/SXT-028h/EVIDENCE.md section 4 and
the original's own corpus/normalized/graphs.jsonl record):

  * scene mode id (exact; every original is multi-scene so scene B exists and
    the bins slots are reachable),
  * bins1 / bins2 occupancy (exact on/off pair),
  * for the two-occupant shape, the two slots hold DIFFERENT FX classes,
  * fx_bypass == 0 (All FX: the insert stage runs) and fx_disable == 0.

A census match or an FX type count is never taken for native agreement: the
shape check re-reads the slots' types, fx_bypass, fx_disable and scene mode
from the NATIVE loader's normalized state and refuses a candidate whose native
state disagrees with the predicate (the candidate then stays in the
denominator with no drift value).

Claims kept separate: COVERAGE (enumerated / attempted / screened / refused),
DRIFT OUTCOME (gate PASS/FAIL per candidate) and SELECTION. A drift-gate PASS
is necessary, never sufficient, for render eligibility; no wet fidelity,
preset support, audio repeatability or RTL-exactness claim follows.

Selection rule (deterministic, mechanical): among the shape's candidates that
were screened with drift gate PASS and are not the original, take the first in
ascending byte order of the corpus-relative path. The original keeps its own
recorded verdict regardless; a selected replacement is an ADDITION, never a
silent substitution. No eligible candidate -> a bounded coverage gap that
blocks only this leaf's render leg.

Output: reports/SXT-028h/artifacts/carrier-drift-screen.json, written ONLY when
the live oracle leg actually ran; with the oracle absent the run is NOT_RUN and
any committed live record is left untouched.

Run under the oracle interpreter (see oracle/README.md "Prebuilt oracle"):
  ORACLE_SURGE_DIR=... LD_LIBRARY_PATH=... "$ORACLE_PYTHON" \\
      tools/screen_rf_bins12_carriers.py
Exit codes: 0 live screen ran with complete coverage; 3 ran, coverage
incomplete; 1 BLOCKED; 2 NOT_RUN.

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only.
"""

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import carrier_drift_screen as cds
from refusal import Refuse

FXSLOT_BINS1, FXSLOT_BINS2 = 2, 3
SCREEN_RECORD = os.path.join(REPO, "reports", "SXT-028h", "artifacts",
                             "carrier-drift-screen.json")

SHAPE_SOURCE = ("reports/SXT-028h/EVIDENCE.md section 4 (carrier shapes) + "
                "the original's corpus/normalized/graphs.jsonl record")

# One explicit shape per original. `expected_count` is the committed
# denominator: the number of normalized graphs.jsonl records matching the
# predicate (a different count BLOCKS the run).
SHAPES = {
    "novuo": {
        "shape_id": "rf-bins12/dual-occupant-different-class/"
                    "scene-mode-2-fxb0-fxd0",
        "original_path": "resources/data/patches_3rdparty/A.Liv/Leads/"
                         "Novuo.fxp",
        "original_sha1": "e688adfdcdee44073968942914733783163b0e8c",
        "scene_mode_id": 2, "bins1_occupied": True, "bins2_occupied": True,
        "classes_differ": True, "fx_bypass": 0, "fx_disable": 0,
        "expected_count": 122,
    },
    "acoordion-basses": {
        "shape_id": "rf-bins12/bins1-only/scene-mode-1-fxb0-fxd0",
        "original_path": "resources/data/patches_3rdparty/Aleksey Zhehanov/"
                         "Keys/Acoordion Basses.fxp",
        "original_sha1": "a765202508e7522972196640c79dfd3fbb90f292",
        "scene_mode_id": 1, "bins1_occupied": True, "bins2_occupied": False,
        "classes_differ": None, "fx_bypass": 0, "fx_disable": 0,
        "expected_count": 11,
    },
    "shore": {
        "shape_id": "rf-bins12/bins1-only/scene-mode-2-fxb0-fxd0",
        "original_path": "resources/data/patches_3rdparty/Altenberg/FX/"
                         "Shore.fxp",
        "original_sha1": "e0c8107755b359c69527aa22508ea7762991ac3d",
        "scene_mode_id": 2, "bins1_occupied": True, "bins2_occupied": False,
        "classes_differ": None, "fx_bypass": 0, "fx_disable": 0,
        "expected_count": 84,
    },
}


def graph_shape(g):
    """Shape-relevant fields of a normalized graph record `g['g']`."""
    fx = {e.get("r"): e for e in g["fx"]}
    b1, b2 = fx.get("bins1", {}), fx.get("bins2", {})
    return {"scene_mode_id": g.get("sm"),
            "bins1_occupied": bool(b1.get("on", 0)),
            "bins2_occupied": bool(b2.get("on", 0)),
            "bins1_type_id": b1.get("t"), "bins2_type_id": b2.get("t"),
            "fx_bypass": g.get("fxb"), "fx_disable": g.get("fxd")}


def _classes_differ(sh):
    return sh["bins1_type_id"] != sh["bins2_type_id"]


def make_predicate(spec):
    """Explicit shape predicate over a graphs.jsonl record (a pure function)."""
    def predicate(rec):
        if rec.get("st") != "normalized":
            return False
        sh = graph_shape(rec["g"])
        if (sh["scene_mode_id"] != spec["scene_mode_id"]
                or sh["bins1_occupied"] != spec["bins1_occupied"]
                or sh["bins2_occupied"] != spec["bins2_occupied"]
                or sh["fx_bypass"] != spec["fx_bypass"]
                or sh["fx_disable"] != spec["fx_disable"]):
            return False
        if spec["classes_differ"] is not None:
            return _classes_differ(sh) == spec["classes_differ"]
        return True
    return predicate


def native_state(s, patch):
    """The shape-relevant NATIVE normalized state, read back after loadPatch."""
    def rv(p):
        return int(round(s.getParamVal(p)))
    return {"scene_mode_id": rv(patch["scenemode"]),
            "scene_active": rv(patch["scene_active"]),
            "bins1_type_id": rv(patch["fx"][FXSLOT_BINS1]["type"]),
            "bins2_type_id": rv(patch["fx"][FXSLOT_BINS2]["type"]),
            "fx_bypass": rv(patch["fx_bypass"]),
            "fx_disable": rv(patch["fx_disable"])}


def make_shape_check(spec, observed=None):
    """Return shape_check(s, patch, cand) -> None | mismatch string comparing
    the NATIVE state with the predicate AND with the graph record. `observed`
    (dict path -> native state) collects the read-back for the record."""
    def shape_check(s, patch, cand):
        n = native_state(s, patch)
        if observed is not None:
            observed[cand["path"]] = n
        gsh = graph_shape(cand["graph"])
        bad = []
        if n["scene_mode_id"] != spec["scene_mode_id"]:
            bad.append(f"scene mode native={n['scene_mode_id']} "
                       f"want={spec['scene_mode_id']}")
        for role, key in (("bins1", "bins1_type_id"),
                          ("bins2", "bins2_type_id")):
            occ = n[key] != 0
            if occ != spec[f"{role}_occupied"]:
                bad.append(f"{role} native occupied={occ} "
                           f"want={spec[f'{role}_occupied']}")
            if n[key] != gsh[key]:
                bad.append(f"{role} native type {n[key]} != graph "
                           f"{gsh[key]}")
        if (spec["classes_differ"] is not None
                and (n["bins1_type_id"] != n["bins2_type_id"])
                != spec["classes_differ"]):
            bad.append("native bins1/bins2 class relation disagrees")
        if n["fx_bypass"] != spec["fx_bypass"]:
            bad.append(f"fx_bypass native={n['fx_bypass']} "
                       f"want={spec['fx_bypass']}")
        if n["fx_disable"] != spec["fx_disable"]:
            bad.append(f"fx_disable native={n['fx_disable']} "
                       f"want={spec['fx_disable']}")
        return "; ".join(bad) or None
    return shape_check


def select_replacement(original_path, candidates):
    """Deterministic selection among same-shape drift-0 candidates: lowest
    path in ascending byte order among screened + gate PASS, excluding the
    original. Returns the path or None (bounded gap)."""
    ok = sorted(c["path"] for c in candidates
                if c["path"] != original_path and c.get("screened")
                and (c.get("determinism_gate") or {}).get("status") == "PASS")
    return ok[0] if ok else None


def screen_shape(slug, loader):
    spec = SHAPES[slug]
    predicate = make_predicate(spec)
    observed = {}
    doc = cds.run_screen(spec["shape_id"], predicate,
                         make_shape_check(spec, observed), loader,
                         expected_count=spec["expected_count"])
    for c in doc.get("candidates", []):
        c["native_state"] = observed.get(c["path"])
    return doc


def summarize(slug, doc):
    spec = SHAPES[slug]
    out = {"shape_spec": {k: v for k, v in spec.items()},
           "shape_source": SHAPE_SOURCE, "run": doc}
    cands = doc.get("candidates")
    if cands is None:
        out["original"] = None
        out["selection"] = {"status": "NOT_RUN" if doc["status"] == "NOT_RUN"
                            else "BLOCKED"}
        return out
    orig = next((c for c in cands if c["path"] == spec["original_path"]),
                None)
    gate = (orig or {}).get("determinism_gate")
    out["original"] = {
        "path": spec["original_path"],
        "in_denominator": orig is not None,
        "screened": bool(orig and orig["screened"]),
        "drift_gate": gate["status"] if gate else None,
        "drift_per_voicing_scene": gate["drift_per_voicing_scene"]
        if gate else None,
        "drift_eligible": bool(gate and gate["status"] == "PASS"),
        "render_eligibility": "NOT_ESTABLISHED",
        "preserved_as": "drift-gate PASS only; render still gated"
        if gate and gate["status"] == "PASS"
        else "non-render-eligible (drift gate failed or not screened); "
             "preserved, not removed"}
    pick = select_replacement(spec["original_path"], cands)
    full = doc.get("coverage", {}).get("candidates_screened") == \
        doc.get("coverage", {}).get("candidates_in_corpus")
    out["selection"] = {
        "rule": "first path in ascending byte order among screened, "
                "drift-gate PASS candidates excluding the original",
        "selected_addition": pick,
        "label": "addition (never a silent substitution)" if pick else None,
        "bounded_gap": pick is None,
        "gap_scope": None if pick else
        "blocks only SXT-028h's render leg for this shape; static routing "
        "and RTL-vs-model claims are unaffected",
        "coverage_complete": bool(full),
    }
    return out


def build_record(loader, slugs=None):
    shapes, engine, statuses = {}, None, []
    for slug in (slugs or list(SHAPES)):
        doc = screen_shape(slug, loader)
        shapes[slug] = summarize(slug, doc)
        statuses.append(doc["status"])
        engine = engine or doc.get("engine")
    if "BLOCKED" in statuses:
        status = "BLOCKED"
    elif "NOT_RUN" in statuses:
        status = "NOT_RUN"
    elif "NO_VERDICT" in statuses:
        status = "NO_VERDICT"
    else:
        status = "PASS"
    drifts = [s["run"].get("drift_gate_status") for s in shapes.values()]
    return {"schema_version": 1, "issue": "#424", "leaf": "SXT-028h",
            "claim_scope": cds.CLAIM_SCOPE,
            "status": status,
            "status_scope": "coverage only (every candidate attempted and "
                            "screened); NOT a drift-clean or support claim",
            "drift_gate_status_per_shape": dict(zip(shapes, drifts)),
            "live": status in ("PASS", "NO_VERDICT") and all(
                s["run"].get("live") for s in shapes.values()),
            "drift_gate_read_back_decimals": 9,
            "engine": engine, "shapes": shapes}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=SCREEN_RECORD)
    a = ap.parse_args(argv)
    doc = build_record(cds.PinnedSurgepyLoader())
    print(f"rf-bins12 carrier drift screen: {doc['status']}")
    for slug, sh in doc["shapes"].items():
        run = sh["run"]
        print(f"  {slug}: {run['status']} coverage={run.get('coverage')} "
              f"drift_gate_status={run.get('drift_gate_status')} "
              f"original={sh['original'] and sh['original']['drift_gate']} "
              f"selected={sh['selection'].get('selected_addition')}")
    if doc["status"] in ("NOT_RUN", "BLOCKED"):
        print("record NOT written (committed live evidence, if any, is "
              "left untouched)")
        return 2 if doc["status"] == "NOT_RUN" else 1
    try:
        cds.write_record(doc, a.out)
    except Refuse as e:
        print(f"refused: {e}")
        return 1
    print(f"wrote {a.out}")
    return 0 if doc["status"] == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())
