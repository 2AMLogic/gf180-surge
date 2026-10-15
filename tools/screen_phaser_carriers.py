#!/usr/bin/env python3
"""SXT-028g / #426: shape-preserving drift screen for Phaser carriers.

Uses the shared helper tools/carrier_drift_screen.py (#423), following the
pattern of tools/screen_rf_global2_carriers.py (#425). The affected original
is patches_factory/Leads/Squelch.fxp (engine-side drift A = 0.1875 in the
read-only historical measurement reports/SXT-028l/artifacts/
same-class-carrier-screen.json::sibling_render_carrier_audit, which is
re-measured here, never trusted).

Shape (declared BEFORE screening; asserted to match the original itself, and an
original that does not satisfy it BLOCKS the run): exactly one occupied FX
slot, `ains1`, hosting the Phaser class (fx type 3); fx_bypass == All FX;
fx_disable == 0; Single scene mode with scene A active. Unlike the routing-form
leaves, the FX class IS part of this shape because this leaf is the Phaser
algorithm leaf.

Claims kept separate: coverage (enumerated/screened/refused) vs drift verdict
vs selection. A drift-0 candidate is a labeled ADDITION, never a silent
substitution of the original; an original whose gate fails stays
non-render-eligible. Drift 0 is necessary, never sufficient, and says nothing
about wet fidelity, preset support, audio repeatability or RTL exactness.
The extractor's other gates (FX-destination modulation screen, mod_wave,
retrigger, stages, temposync) still apply to any adopted addition.

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

FX_TYPE_PHASER = 3
FXSLOT_AINS1 = 0
DEFAULT_OUT = os.path.join(REPO, "reports", "SXT-028g", "artifacts",
                           "carrier-drift-screen.json")

SHAPES = [
    {"slug": "squelch",
     "id": "type-phaser/ains1-only-phaser-allfx-fxd0-single-sceneA",
     "path": "resources/data/patches_factory/Leads/Squelch.fxp",
     "expected_count": 5},
]

SELECTION_RULE = (
    "Among candidates of the same shape whose per-scene drift gate PASSES "
    "(carrier_drift_screen.assert_drift_gate_passed), excluding the original "
    "itself: ascending corpus path; the first is proposed as a labeled "
    "ADDITION. If none passes, the outcome is BOUNDED_GAP, which blocks only "
    "this leaf's render leg.")


def make_predicate(shape=None):
    """Explicit corpus-record predicate (normalized records only)."""
    def predicate(rec):
        if rec.get("st") != "normalized":
            return False
        g = rec["g"]
        for fx in g["fx"]:
            want = fx.get("r") == "ains1"
            if bool(fx.get("on", 0)) != want:
                return False
            if want and fx.get("t") != FX_TYPE_PHASER:
                return False
        return (g.get("fxb") == 0 and g.get("fxd") == 0
                and g.get("sm") == 0 and g.get("sa") == 0)
    return predicate


def make_shape_check(native_state):
    """Native cross-check; records native normalized state per candidate."""
    def check(s, patch, cand):
        n = len(cand["graph"]["fx"])
        types = [int(round(s.getParamVal(patch["fx"][i]["type"])))
                 for i in range(n)]
        fxb = int(round(s.getParamVal(patch["fx_bypass"])))
        fxd = int(round(s.getParamVal(patch["fx_disable"])))
        mode = int(round(s.getParamVal(patch["scenemode"])))
        active = int(round(s.getParamVal(patch["scene_active"])))
        native_state[cand["path"]] = {
            "fx_type_ids": types, "fx_bypass": fxb, "fx_disable": fxd,
            "scene_mode_id": mode, "scene_active": active}
        graph_types = [fx.get("t", 0) for fx in cand["graph"]["fx"]]
        if types != graph_types:
            return (f"native fx type vector {types} disagrees with "
                    f"graphs.jsonl {graph_types}")
        want = [FX_TYPE_PHASER if i == FXSLOT_AINS1 else 0 for i in range(n)]
        if types != want:
            return f"native fx type vector {types} is not the shape {want}"
        if (fxb, fxd, mode, active) != (0, 0, 0, 0):
            return (f"native (fx_bypass, fx_disable, scene_mode, "
                    f"scene_active)={(fxb, fxd, mode, active)} is not the "
                    f"shape (0, 0, 0, 0)")
        return None
    return check


def select_replacement(candidates, original_path):
    """Deterministic selection among same-shape drift-0 candidates.

    Eligibility is derived ONLY from the recorded gate via
    cds.assert_drift_gate_passed. Returns (ranked_paths, selected_or_None)."""
    ranked = []
    for c in candidates:
        if c["path"] == original_path:
            continue
        try:
            cds.assert_drift_gate_passed(c)
        except AssertionError:
            continue
        ranked.append(c["path"])
    ranked.sort()
    return ranked, (ranked[0] if ranked else None)


def original_eligibility(candidates, path):
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
    orig = _original_graph(shape["path"], kw.get("graphs_path"))
    pred = make_predicate(shape)
    if not pred(orig):
        raise cds.RunBlocked(
            f"original {shape['path']} does not satisfy its own declared "
            f"shape predicate {shape['id']}")
    native = {}
    doc = cds.run_screen(shape["id"], pred, make_shape_check(native), loader,
                         expected_count=shape["expected_count"], **kw)
    out = {"shape": {k: shape[k] for k in ("id", "slug", "path")},
           "shape_definition": "only ains1 occupied, hosting Phaser (fx type "
                               "3); fx_bypass==All FX, fx_disable==0, Single "
                               "scene mode, scene A active",
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
    ranked, selected = select_replacement(cands, shape["path"])
    out["selection"] = {
        "rule": SELECTION_RULE,
        "eligible_same_shape_drift0_ranked": ranked,
        "selected_addition": selected,
        "outcome": "REPLACEMENT_SELECTED" if selected else "BOUNDED_GAP",
        "label": ("labeled ADDITION; the original stays in the record as "
                  "non-render-eligible where its gate fails"
                  if selected else
                  "no same-shape drift-0 candidate; blocks only this leaf's "
                  "render leg"),
    }
    return out


def screen_all(loader, shapes=SHAPES, **kw):
    doc = {"schema_version": 1, "issue": "#426", "leaf": "SXT-028g",
           "algorithm": "type-phaser", "claim_scope": cds.CLAIM_SCOPE,
           "historical_measurement_read_only":
               "reports/SXT-028l/artifacts/same-class-carrier-screen.json::"
               "sibling_render_carrier_audit (not fresh evidence)",
           "shapes": [screen_shape(sh, loader, **kw) for sh in shapes]}
    statuses = [s["run"]["status"] for s in doc["shapes"]]
    doc["live"] = all(s["run"].get("live") for s in doc["shapes"])
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
