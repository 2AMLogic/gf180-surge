#!/usr/bin/env python3
"""SXT-028a: fail-closed extraction of the Airwindows-49 (Galactic) fixture
inputs from the pinned engine.

Follows the model/effects/extract_fx_inputs.py (SXT-023) conventions: census
blob re-verified, graphs.jsonl cross-checked, post-load normalized state via
surgepy getters is authoritative, drift asserted/recorded, fail-closed on
anything the leaf does not model. Differences (declared):

  * the fixtures are free-phase/drift carriers with Airwindows vibrato
    randomization (C > 0), so they are NOT in the bit-identical
    repeatability class; drift > 0 and C > 0 are RECORDED (repeatability
    class "conditioned-on-tap") instead of refused - the reference leg
    conditions on oracle taps (decision-records/0006);
  * every active FX slot is inventoried; slots outside the landed leaf set
    mark the preset's complete-wet render REFUSED (applicability boundary,
    fail-closed) - only a slot-boundary (tapped) comparison is possible;
  * modulation into ANY FX parameter refuses (outside the frozen model).

Writes model/effects/fx_inputs/aw-49-<slug>.json.

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

FX_TYPE_DELAY = 1
FX_TYPE_REVERB1 = 2
FX_TYPE_EQ = 6
FX_TYPE_AW = 14
AW_GALACTIC = 49

# Landed leaf classes for the applicability boundary (coverage-v1 ledger):
# EQ (SXT-023) and Reverb1 (SXT-024) are leaf-verified (PENDING-FREEZE);
# Delay (SXT-023) is landed but FAIL (#16 routed to #12); Airwindows 49 is
# THIS leaf; every other class is unlanded (sibling 028 leaves etc.).
LANDED = {
    FX_TYPE_EQ: "landed:SXT-023-EQ",
    FX_TYPE_REVERB1: "landed:SXT-024-Reverb1",
    FX_TYPE_DELAY: "landed-failing:SXT-023-Delay(#16->#12)",
}
LANDED_AW = {AW_GALACTIC: "this-leaf:SXT-028a"}

PRESETS = {
    "temple": "resources/data/patches_3rdparty/Altenberg/Guitars/Temple.fxp",
    "sine_lead": "resources/data/patches_3rdparty/Altenberg/Leads/Sine Lead.fxp",
    "unity": "resources/data/patches_3rdparty/Altenberg/Pads/Unity.fxp",
    "fmod09": "resources/data/patches_factory/Tutorials/Formula Modulator/09 Example - Crossfading Oscillators.fxp",
}


class Refuse(Exception):
    pass


def census_entry(rel_path):
    import csv

    csv_path = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel_path:
                break
        else:
            raise Refuse(f"preset not in census: {rel_path}")
    graphs_line = None
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel_path:
                graphs_line = g
                break
    if graphs_line is None or graphs_line.get("st") != "normalized":
        raise Refuse(f"preset not normalized: {rel_path}")
    return row["git_blob_sha1"], graphs_line


def md_fx_destinations(graphs):
    """Machine-readable check: modulation INTO any FX parameter refuses.

    graphs md rows are [src, ..., dest_id, dest_name, depth, ...] per
    corpus/normalized/README.md; FX destinations carry names starting
    with 'FX'."""
    hits = []

    def scan(rows):
        for r in rows:
            name = r[4] if len(r) > 4 else ""
            if isinstance(name, str) and name.startswith("FX"):
                hits.append(name)

    md = graphs["g"]["md"]
    scan(md.get("g", []))
    for sc in md.get("s", []):
        scan(sc.get("s", []))
        scan(sc.get("v", []))
    return hits


def extract(slug, rel_path, out_path):
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    blob, graphs = census_entry(rel_path)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise Refuse(f"census blob mismatch: {rel_path} {actual} != {blob}")
    if graphs["g"]["fxb"] != 0:
        raise Refuse(f"fx_bypass != fxb_all_fx: {rel_path}")
    if graphs["g"]["fxd"] != 0:
        raise Refuse(f"fx_disable nonzero: {rel_path}")
    hits = md_fx_destinations(graphs)
    if hits:
        raise Refuse(f"modulation into FX params (unmodeled, fail-closed): "
                     f"{rel_path}: {hits[:4]}")

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(abs_path):
        raise Refuse(f"loadPatch failed: {rel_path}")
    patch = s.getPatch()

    sm = int(s.getParamVal(patch["scenemode"]))
    sa = int(s.getParamVal(patch["scene_active"]))
    voicing = [sa] if sm == 0 else [0, 1]
    drifts = [float(s.getParamVal(patch["scene"][v]["drift"])) for v in voicing]

    engine_types = [int(s.getParamVal(patch["fx"][i]["type"])) for i in range(16)]
    graph_types = [fx.get("t", 0) for fx in graphs["g"]["fx"]]
    if engine_types != graph_types:
        raise Refuse(f"fx type mismatch engine vs graphs: {rel_path}")

    volume_f = float(s.getParamVal(patch["volume"]))
    scene_sends = [[float(s.getParamVal(patch["scene"][k]["send_level"][j]))
                    for j in range(2)] for k in range(2)]

    aw49_slots = []
    slots = []
    for slot in range(16):
        t = engine_types[slot]
        if t == 0:
            continue
        gxf = graphs["g"]["fx"][slot]
        fxd = patch["fx"][slot]
        aw = int(s.getParamVal(fxd["p"][0])) if t == FX_TYPE_AW else None
        params = [float(s.getParamVal(fxd["p"][j])) for j in range(12)]
        # cross-check engine readback against the graphs export (6-decimal)
        if aw is not None:
            if gxf.get("aw") != aw:
                raise Refuse(f"aw id mismatch slot{slot}: {rel_path}")
        for j in range(12):
            gv = gxf["p"][j]
            if abs(params[j] - gv) > 1.5e-6:
                raise Refuse(f"param mismatch slot{slot} p{j}: {rel_path} "
                             f"{params[j]} vs {gv}")
        role = gxf["r"]
        entry = {
            "slot": slot, "role": role, "type": t,
            "type_name": gxf.get("tn"),
            "aw": aw, "aw_name": gxf.get("awn"),
            "params_f": params,
            "return_f": float(s.getParamVal(fxd["return_level"])),
        }
        if t == FX_TYPE_AW and aw == AW_GALACTIC:
            # Galactic params (adapter p[1..5] -> A..E); C = p[3]
            if sm != 0:
                raise Refuse(f"multi-scene send bookkeeping unsupported: {rel_path}")
            entry["galactic"] = {
                "A_replace_f": params[1], "B_brightness_f": params[2],
                "C_modulation_f": params[3], "D_size_f": params[4],
                "E_mix_f": params[5],
                "active_scene": sa,
                "scene_send_f": scene_sends[sa],
            }
            aw49_slots.append(slot)
        slots.append(entry)

    if len(aw49_slots) != 1:
        raise Refuse(f"expected exactly one AW-49 slot, got {aw49_slots}: "
                     f"{rel_path}")

    # applicability boundary (fail-closed bookkeeping, machine-readable)
    classes = []
    complete_wet_possible = True
    unlanded = []
    for e in slots:
        t, aw = e["type"], e["aw"]
        if t == FX_TYPE_AW and aw in LANDED_AW:
            cls = LANDED_AW[aw]
        elif t in LANDED:
            cls = LANDED[t]
            if t == FX_TYPE_DELAY:
                complete_wet_possible = False  # landed but FAIL (#16)
        else:
            cls = f"unlanded:{e.get('type_name')}({'aw' + str(aw) if aw else t})"
            complete_wet_possible = False
            unlanded.append({"slot": e["slot"], "cls": cls})
        classes.append({"slot": e["slot"], "class": cls})

    c_mod = slots[[e["slot"] for e in slots].index(aw49_slots[0])] \
        ["galactic"]["C_modulation_f"]
    rep = {
        "bit_identical": all(d == 0.0 for d in drifts) and c_mod == 0.0,
        "reasons": (["scene drift > 0: " + repr(drifts)] if any(drifts) else [])
                   + ([f"aw49 C (Modulation) = {c_mod} > 0: engine vibrato "
                       "seed is wall-clock seeded"] if c_mod > 0 else []),
    }

    out = {
        "schema_version": 1,
        "leaf": "SXT-028a",
        "slug": slug,
        "path": rel_path,
        "census_blob_sha1": blob,
        "graphs_sha256_prefix": graphs["sha"][:16],
        "volume_f": volume_f,
        "scene_mode": sm,
        "scene_active": sa,
        "drifts_recorded": drifts,
        "scene_sends_f": scene_sends,
        "repeatability_class": rep,
        "applicability": {
            "complete_wet_render_possible": complete_wet_possible,
            "slot_classes": classes,
            "unlanded_slots": unlanded,
            "rule": "complete-wet renders REFUSED unless every active class "
                    "is landed and passing; tapped slot-boundary comparison "
                    "is the reference leg (decision-records/0006)",
        },
        "chain": slots,
        "aw49_slot": aw49_slots[0],
        "extraction": {
            "params_source": "surgepy getParamVal post-load (normalized, "
                             "authoritative), cross-checked against "
                             "graphs.jsonl within 1.5e-6",
            "modulation_check": "graphs md rows with FX destinations refuse "
                                "(unmodeled, fail-closed)",
            "drift_policy": "recorded, not gated: the leaf conditions the "
                            "reference leg on oracle taps",
        },
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"extracted {slug} -> {out_path} "
          f"(complete_wet={complete_wet_possible}, bitident={rep['bit_identical']})")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    ap.add_argument("--slugs", help="comma-separated subset")
    args = ap.parse_args()
    slugs = args.slugs.split(",") if args.slugs else sorted(PRESETS)
    refused = []
    for slug in slugs:
        try:
            extract(slug, PRESETS[slug],
                    os.path.join(args.out_dir, f"aw-49-{slug}.json"))
        except Refuse as e:
            print(f"REFUSED {slug}: {e}")
            refused.append((slug, str(e)))
    for slug, why in refused:
        print(f"REFUSED {slug}: {why}", file=sys.stderr)
    if refused:
        print(f"{len(refused)}/{len(slugs)} fixtures refused (fail-closed "
              "transcript above); refused fixtures produce no input JSON")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
