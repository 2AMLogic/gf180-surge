#!/usr/bin/env python3
"""SXT-028b: fail-closed extraction of Conditioner inputs from the engine.

ORACLE-HOST TOOL. Needs the pinned engine checkout + surgepy (SXT-010,
oracle/manifest.json). It has NOT been executed on the host that authored
this leaf (no oracle there): its output files
model/effects/fx_inputs/type-conditioner-<slug>.json do not exist yet and
the reference leg is BLOCKED (reports/SXT-028b/EVIDENCE.md). The pure
resolution logic below (deactivated-flag migrations, per-slot modulation
screen) is unit-tested oracle-free in tests/test_sxt028b.py.

Follows model/effects/extract_fx_inputs.py (SXT-023) conventions: census
blob re-verified on disk, graphs.jsonl fx types + stored values cross-
checked against surgepy readback after loadPatch (values must agree to the
graphs 6-decimal rounding), drift == 0 asserted on every voicing scene,
fx_bypass == all FX, fx_disable == 0, and ANY modulation route whose
destination is this Conditioner slot refuses (parameter modulation into the
leaf is outside the frozen scope). Unlike tools/extract_chorus_inputs.py,
the modulation screen walks the real md structure ({g: [...], s: [{s, v}]},
corpus/normalized/schema.json); the chorus screen iterates the dict's keys
and never inspects a route (follow-up issue).

`deactivated` flags come from the raw .fxp XML attribute (no surgepy
getter), then ConditionerEffect::handleStreamingMismatches:
  rev <= 15: bass, treble -> active;  rev <= 16: hpwidth -> -60, deactivated.
An ABSENT attribute that no migration resolves REFUSES (fail-closed) --
patch load uses loadFx(initp=false), so init_default_values() does not run
and there is no documented default to fall back on.

Conditioner (fxt_conditioner = 8) params (ConditionerEffect.h cond_params):
bass(0) treble(1) width(2) balance(3) threshold(4) attack(5) release(6)
gain(7) hpwidth(8).

Original to this repository (Apache-2.0); imports the GPL engine at
runtime only.
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, REPO)

from conditioner_corners import FIXTURE_PRESETS, PARAM_ORDER  # noqa: E402

FX_TYPE_CONDITIONER = 8
ROLE_TAG = {**{f"ains{i}": f"A{i}" for i in range(1, 5)},
            **{f"bins{i}": f"B{i}" for i in range(1, 5)},
            **{f"send{i}": f"S{i}" for i in range(1, 5)},
            **{f"global{i}": f"G{i}" for i in range(1, 5)}}
DEACTIVATABLE = {0: "bass", 1: "treble", 8: "hpwidth"}


class Refuse(Exception):
    pass


def md_routes(graphs):
    """Every modulation route row of a graphs.jsonl entry (all buses)."""
    md = graphs["g"]["md"]
    rows = list(md.get("g", []))
    for sc in md.get("s", []):
        rows += list(sc.get("s", [])) + list(sc.get("v", []))
    return rows


def slot_mod_hits(graphs, role):
    """Route destinations naming this FX slot ('FX <tag> <param>')."""
    tag = f"FX {ROLE_TAG[role]} "
    return [r[4] for r in md_routes(graphs)
            if len(r) > 4 and isinstance(r[4], str) and r[4].startswith(tag)]


def resolve_deactivated(xml_flags, slot, rev):
    """Raw XML deactivated attributes + handleStreamingMismatches."""
    out = {}
    for j, name in DEACTIVATABLE.items():
        f = xml_flags.get(f"fx{slot + 1}_p{j}", {})
        raw = None if (not f or f.get("deactivated_absent", True)) else bool(f["deactivated"])
        if name in ("bass", "treble") and rev <= 15:
            val = False
        elif name == "hpwidth" and rev <= 16:
            val = True
        elif raw is None:
            raise Refuse(f"slot{slot} {name}: deactivated attribute absent at "
                         f"rev {rev} and no documented migration resolves it")
        else:
            val = raw
        out[f"{name}_deactivated"] = val
    return out


def extract(slug, rel_path, out_path):  # pragma: no cover - oracle host only
    import oracle_common as oc
    from model.effects.extract_fx_inputs import census_entry, raw_xml_flags

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    blob, graphs = census_entry(rel_path)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise Refuse(f"census blob mismatch: {rel_path} {actual} != {blob}")
    if graphs["g"]["fxb"] != 0 or graphs["g"]["fxd"] != 0:
        raise Refuse(f"fx bypass/disable not neutral: {rel_path}")
    rev, tempo, xml_flags = raw_xml_flags(rel_path)

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(abs_path):
        raise Refuse(f"loadPatch failed: {rel_path}")
    patch = s.getPatch()
    sm = int(s.getParamVal(patch["scenemode"]))
    sa = int(s.getParamVal(patch["scene_active"]))
    drifts = []
    for sc_i in ([sa] if sm == 0 else [0, 1]):
        d = float(s.getParamVal(patch["scene"][sc_i]["drift"]))
        drifts.append(d)
        if d != 0.0:
            raise Refuse(f"drift {d} != 0 in scene {sc_i}: {rel_path}")

    engine_types = [int(s.getParamVal(patch["fx"][i]["type"])) for i in range(16)]
    if engine_types != [fx.get("t", 0) for fx in graphs["g"]["fx"]]:
        raise Refuse(f"fx type mismatch engine vs graphs: {rel_path}")

    slots = []
    for slot, t in enumerate(engine_types):
        if t != FX_TYPE_CONDITIONER:
            continue
        gfx = graphs["g"]["fx"][slot]
        role = gfx["r"]
        hits = slot_mod_hits(graphs, role)
        if hits:
            raise Refuse(f"modulation into Conditioner slot {slot}: {hits[:4]}")
        vals = [float(s.getParamVal(patch["fx"][slot]["p"][j])) for j in range(9)]
        for j, (v, gv) in enumerate(zip(vals, gfx["p"][:9])):
            if abs(v - float(gv)) > 5e-6:
                raise Refuse(f"slot{slot} p{j}: surgepy {v} != graphs {gv}")
        params = dict(zip(PARAM_ORDER, vals))
        params.update(resolve_deactivated(xml_flags, slot, rev))
        slots.append({"slot": slot, "role": role, "params": params,
                      "return_f": float(s.getParamVal(patch["fx"][slot]["return_level"]))})
    if not slots:
        raise Refuse(f"no Conditioner slot: {rel_path}")

    doc = {"schema_version": 1, "leaf": "SXT-028b", "slug": slug,
           "path": rel_path, "census_blob_sha1": blob, "rev": rev,
           "tempo_bpm": tempo if tempo is not None else 120.0,
           "drifts_asserted_zero": drifts, "engine_fx_types": engine_types,
           "conditioner_slots": slots,
           "extraction": {"values": "surgepy getParamVal after loadPatch, "
                          "cross-checked vs graphs.jsonl (<= 5e-6)",
                          "deactivated": "raw XML + handleStreamingMismatches; "
                          "absent-and-unmigrated refuses",
                          "mod_routes": "per-slot FX destination screen over "
                          "md.g + md.s[*].s + md.s[*].v"}}
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    return doc


def main():  # pragma: no cover - oracle host only
    import oracle_common as oc
    oc.reexec_under_pinned_python(REPO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(REPO, "model", "effects",
                                                      "fx_inputs"))
    ap.add_argument("--refusals", default=os.path.join(
        REPO, "reports", "SXT-028b", "artifacts", "extract-refusals.txt"))
    args = ap.parse_args()
    refusals = []
    for slug, rel in sorted(FIXTURE_PRESETS.items()):
        try:
            extract(slug, rel, os.path.join(args.out_dir,
                                            f"type-conditioner-{slug}.json"))
        except Refuse as e:
            refusals.append(f"{slug}: REFUSED: {e}")
    os.makedirs(os.path.dirname(args.refusals), exist_ok=True)
    with open(args.refusals, "w", encoding="utf-8") as f:
        f.write("\n".join(refusals) + ("\n" if refusals else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
