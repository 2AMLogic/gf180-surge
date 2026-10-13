#!/usr/bin/env python3
"""SXT-028d / #425: shape-preserving drift screen for rf-global2 carriers.

Uses the shared helper tools/carrier_drift_screen.py (#423). For each
AFFECTED original carrier (the ones whose engine-side per-scene drift gate
failed in reports/SXT-028l/artifacts/same-class-carrier-screen.json,
`sibling_render_carrier_audit`; that file is a read-only historical
measurement and is re-measured here, never trusted) this tool

  1. declares the carrier's EXACT routing/occupancy shape predicate BEFORE
     screening (SHAPES below; every field is read from the original's own
     committed corpus record and the predicate is asserted to match the
     original itself -- an original that does not satisfy its own predicate
     BLOCKS the run);
  2. enumerates every corpus candidate matching it (corpus order, complete
     denominator, pinned by an expected count);
  3. screens each LIVE on the pinned oracle through the native loader with the
     per-scene drift gate, cross-checking the shape against the NATIVE
     normalized state (fx type vector, fx_bypass, fx_disable, scene mode,
     active scene);
  4. applies a deterministic selection rule to the same-shape drift-0
     candidates, or commits a bounded gap.

Shape fields (routing form `rf-global2`): global1 occupancy, global2
occupancy, fx_bypass == All FX, fx_disable == 0, Single scene mode with scene
A active. The FX CLASS in each slot is deliberately NOT part of the shape
(this leaf is routing-form scope, not algorithm scope --
model/effects/rf-rf-global2/README.md); it only ranks drift-0 candidates.

Claims kept separate: coverage (candidates enumerated/screened/refused) vs
drift verdict vs selection. A drift-0 candidate is a labeled ADDITION, never a
silent substitution of the original; an original whose gate fails stays
non-render-eligible. Drift 0 is necessary, never sufficient, for render
eligibility, and says nothing about wet fidelity, preset support, audio
repeatability or RTL exactness. Nothing here seeds RNG, zeroes drift, widens
a predicate, or treats an injected-loader run as live evidence
(`carrier_drift_screen.write_record` refuses it).

Exit codes: 0 record written, 1 BLOCKED, 2 NOT_RUN (nothing written, no
committed evidence touched), 3 coverage incomplete (record still written).

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, through the helper's provenance-verified loader.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import carrier_drift_screen as cds  # noqa: E402
from refusal import Refuse  # noqa: E402

FXSLOT_GLOBAL1, FXSLOT_GLOBAL2 = 6, 7
DEFAULT_OUT = os.path.join(REPO, "reports", "SXT-028d", "artifacts",
                           "carrier-drift-screen.json")

# Affected originals. `expected_count` pins the committed-corpus denominator
# of the shape predicate; a disagreement BLOCKS rather than screening a
# different denominator.
SHAPES = [
    {"slug": "ancient-fm",
     "id": "rf-global2/dual-g1on-g2on-allfx-fxd0-single-sceneA",
     "path": "resources/data/patches_3rdparty/Altenberg/Basses/Ancient FM.fxp",
     "global1_occupied": True, "global2_occupied": True,
     "expected_count": 490},
    {"slug": "rounded",
     "id": "rf-global2/single-g1off-g2on-allfx-fxd0-single-sceneA",
     "path": "resources/data/patches_3rdparty/Altenberg/Basses/Rounded.fxp",
     "global1_occupied": False, "global2_occupied": True,
     "expected_count": 86},
]

SELECTION_RULE = (
    "Among candidates of the same shape whose per-scene drift gate PASSES "
    "(carrier_drift_screen.assert_drift_gate_passed), excluding the original "
    "itself: rank by the number of the original's occupied global slots whose "
    "native FX type id the candidate also hosts (more is better; the class "
    "is NOT part of the shape), ties broken by ascending corpus path. The "
    "first-ranked candidate is proposed as a labeled ADDITION. If no "
    "candidate passes, the outcome is BOUNDED_GAP, which blocks only this "
    "leaf's render leg.")


def _slot(graph, role):
    for fx in graph["g"]["fx"]:
        if fx.get("r") == role:
            return fx
    return None


def make_predicate(shape):
    """Explicit corpus-record predicate for `shape` (normalized records only)."""
    def predicate(rec):
        if rec.get("st") != "normalized":
            return False
        g = rec["g"]
        g1, g2 = _slot(rec, "global1"), _slot(rec, "global2")
        if g1 is None or g2 is None:
            return False
        return (bool(g1.get("on", 0)) == shape["global1_occupied"]
                and bool(g2.get("on", 0)) == shape["global2_occupied"]
                and g.get("fxb") == 0 and g.get("fxd") == 0
                and g.get("sm") == 0 and g.get("sa") == 0)
    return predicate


def make_shape_check(shape, native_state):
    """Native cross-check of the shape; records the native normalized state of
    each inspected candidate into `native_state[path]`."""
    def check(s, patch, cand):
        types = [int(round(s.getParamVal(patch["fx"][i]["type"])))
                 for i in range(len(cand["graph"]["fx"]))]
        fxb = int(round(s.getParamVal(patch["fx_bypass"])))
        fxd = int(round(s.getParamVal(patch["fx_disable"])))
        mode = int(round(s.getParamVal(patch["scenemode"])))
        active = int(round(s.getParamVal(patch["scene_active"])))
        native_state[cand["path"]] = {
            "fx_type_ids": types, "fx_bypass": fxb, "fx_disable": fxd,
            "scene_mode_id": mode, "scene_active": active,
            "global1_type_id": types[FXSLOT_GLOBAL1],
            "global2_type_id": types[FXSLOT_GLOBAL2]}
        graph_types = [fx.get("t", 0) for fx in cand["graph"]["fx"]]
        if types != graph_types:
            return (f"native fx type vector {types} disagrees with "
                    f"graphs.jsonl {graph_types}")
        if (types[FXSLOT_GLOBAL1] != 0) != shape["global1_occupied"]:
            return "native global1 occupancy disagrees with the shape"
        if (types[FXSLOT_GLOBAL2] != 0) != shape["global2_occupied"]:
            return "native global2 occupancy disagrees with the shape"
        if (fxb, fxd, mode, active) != (0, 0, 0, 0):
            return (f"native (fx_bypass, fx_disable, scene_mode, "
                    f"scene_active)={(fxb, fxd, mode, active)} is not the "
                    f"shape (0, 0, 0, 0)")
        return None
    return check


def select_replacement(candidates, original_path, original_types,
                       global_slots=(FXSLOT_GLOBAL1, FXSLOT_GLOBAL2)):
    """Deterministic selection among same-shape drift-0 candidates.

    candidates: records with `path`, `screened`, `determinism_gate` and
    `native_state`. Eligibility is derived ONLY from the recorded gate via
    cds.assert_drift_gate_passed; nothing else can make a candidate eligible.
    Returns (eligible_ranked_paths, selected_path_or_None)."""
    ranked = []
    for c in candidates:
        if c["path"] == original_path:
            continue
        try:
            cds.assert_drift_gate_passed(c)
        except AssertionError:
            continue
        native = c.get("native_state") or {}
        types = native.get("fx_type_ids") or []
        match = sum(1 for i in global_slots
                    if original_types[i] != 0 and i < len(types)
                    and types[i] == original_types[i])
        ranked.append((-match, c["path"]))
    ranked.sort()
    paths = [p for _, p in ranked]
    return paths, (paths[0] if paths else None)


def original_eligibility(candidates, path):
    """Render-eligibility (drift screening condition only) of the original."""
    rec = next((c for c in candidates if c["path"] == path), None)
    if rec is None:
        return {"drift_screen": "NOT_IN_DENOMINATOR", "render_eligible": False}
    try:
        cds.assert_drift_gate_passed(rec)
    except AssertionError as e:
        return {"drift_screen": "FAIL" if rec.get("screened") else "REFUSED",
                "render_eligible": False, "reason": str(e)}
    return {"drift_screen": "PASS",
            "render_eligible": "NOT_ESTABLISHED (drift 0 is necessary, "
                               "never sufficient)"}


def _original_graph(path, graphs_path=None):
    with open(graphs_path or cds.GRAPHS, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                g = json.loads(line)
                if g["p"] == path:
                    return g
    raise Refuse(f"original not in graphs.jsonl: {path}")


def screen_shape(shape, loader, **kw):
    """Run the helper screen for one shape; returns the per-shape record."""
    orig = _original_graph(shape["path"], kw.get("graphs_path"))
    pred = make_predicate(shape)
    if not pred(orig):
        raise cds.RunBlocked(
            f"original {shape['path']} does not satisfy its own declared "
            f"shape predicate {shape['id']}")
    native = {}
    doc = cds.run_screen(shape["id"], pred, make_shape_check(shape, native),
                         loader, expected_count=shape["expected_count"], **kw)
    out = {"shape": {k: shape[k] for k in ("id", "slug", "path",
                                           "global1_occupied",
                                           "global2_occupied")},
           "shape_definition": "global1/global2 occupancy as stated, "
                               "fx_bypass==All FX, fx_disable==0, Single "
                               "scene mode, scene A active; FX class NOT "
                               "part of the shape",
           "original_graphs_blob_sha1": orig["sha"],
           "run": doc}
    for c in doc.get("candidates", []):
        c["native_state"] = native.get(c["path"])
    if doc.get("status") in ("NOT_RUN", "BLOCKED"):
        return out
    cands = doc["candidates"]
    out["original_result"] = next(
        (c for c in cands if c["path"] == shape["path"]), None)
    out["original_eligibility"] = original_eligibility(cands, shape["path"])
    otypes = [fx.get("t", 0) for fx in orig["g"]["fx"]]
    ranked, selected = select_replacement(cands, shape["path"], otypes)
    out["selection"] = {
        "rule": SELECTION_RULE,
        "eligible_same_shape_drift0_ranked": ranked,
        "selected_addition": selected,
        "outcome": "REPLACEMENT_SELECTED" if selected else "BOUNDED_GAP",
        "label": ("labeled ADDITION; the original stays in the record as "
                  "non-render-eligible where its gate fails"
                  if selected else
                  "no same-shape drift-0 candidate; blocks only this leaf's "
                  "render leg for this shape"),
    }
    return out


def screen_all(loader, shapes=SHAPES, **kw):
    doc = {"schema_version": 1, "issue": "#425", "leaf": "SXT-028d",
           "routing_form": "rf-global2", "claim_scope": cds.CLAIM_SCOPE,
           "historical_measurement_read_only":
               "reports/SXT-028l/artifacts/same-class-carrier-screen.json::"
               "sibling_render_carrier_audit (not fresh evidence)",
           "shapes": []}
    for sh in shapes:
        doc["shapes"].append(screen_shape(sh, loader, **kw))
    statuses = [s["run"]["status"] for s in doc["shapes"]]
    live = all(s["run"].get("live") for s in doc["shapes"])
    doc["live"] = live
    for tok in ("BLOCKED", "NOT_RUN", "NO_VERDICT"):
        if tok in statuses:
            doc["status"] = tok
            break
    else:
        doc["status"] = "PASS"
    doc["status_scope"] = "coverage only; see per-shape drift_gate_status"
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    try:
        doc = screen_all(cds.PinnedSurgepyLoader())
    except Refuse as e:
        print(f"BLOCKED: {e}")
        return 1
    for s in doc["shapes"]:
        r = s["run"]
        print(f"[{s['shape']['id']}] {r['status']}: {r['status_reason']}")
        if "coverage" in r:
            print(f"  coverage={r['coverage']['candidates_screened']}/"
                  f"{r['coverage']['candidates_in_corpus']} "
                  f"drift_gate_status={r['drift_gate_status']} "
                  f"outcome={s['selection']['outcome']} "
                  f"selected={s['selection']['selected_addition']}")
    if doc["status"] in ("NOT_RUN", "BLOCKED"):
        return 2 if doc["status"] == "NOT_RUN" else 1
    cds.write_record(doc, a.out)
    print(f"wrote {a.out}")
    return 0 if doc["status"] == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())
