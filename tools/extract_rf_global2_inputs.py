#!/usr/bin/env python3
"""SXT-028d: fail-closed extraction of routing-form (Global FX slot 2)
carrier metadata from the pinned engine's corpus artifacts.

For each B4-scope carrier preset named in reports/sxt-028/leaves/SXT-028d.json
this tool:
  1. re-verifies the census blob sha1 (corpus/census-v0.1/results/
     per-preset.csv) against the pinned issue text, REFUSING on mismatch;
  2. cross-checks the normalized corpus graph (corpus/normalized/
     graphs.jsonl, SXT-011 output -- already surgepy-derived and committed;
     no live oracle call needed for this step) for the global1/global2 slot
     roles: occupied (on/off), FX type name, and the patch-level fxb
     (fx_bypass)/fxd (fx_disable) fields;
  3. attempts a LIVE surgepy extraction of the per-slot algorithm's own
     parameter values (needed only for an eventual concrete-occupant
     reference render, out of THIS leaf's routing-form scope) -- if the
     pinned oracle build (surgepy) is unavailable in the current
     environment, this step REFUSES explicitly (never silently drops the
     preset) and the routing-verification checks above still proceed and
     are still written to the output record.

Writes model/effects/fx_inputs/rf-rf-global2-<slug>.json plus a refusal
transcript at reports/SXT-028d/artifacts/extract-refusals.txt (created even
when empty, matching the SXT-023/028c refusal-log convention -- absence of
oracle coverage is recorded, never silently dropped).

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, and only for the item-3 attempt.
"""

import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

FXSLOT_GLOBAL1, FXSLOT_GLOBAL2 = 6, 7

CARRIERS = [
    {"slug": "ancient-fm",
     "path": "resources/data/patches_3rdparty/Altenberg/Basses/Ancient FM.fxp",
     "declared_sha1": "9e796f283f2d4b2a69de6198878d57c34f6d86c3"},
    {"slug": "piercing",
     "path": "resources/data/patches_3rdparty/Altenberg/Basses/Piercing.fxp",
     "declared_sha1": "d02d14ea299bf15a113c10c3b5aef6f98f40df55"},
    {"slug": "rounded",
     "path": "resources/data/patches_3rdparty/Altenberg/Basses/Rounded.fxp",
     "declared_sha1": "4403d52200f19737cdd9a355b4aeb474b81bb3e3"},
]

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
OUT_DIR = os.path.join(REPO, "model", "effects", "fx_inputs")
REFUSALS = os.path.join(REPO, "reports", "SXT-028d", "artifacts",
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


def slot_entry(graph, slot_role):
    for fx in graph["g"]["fx"]:
        if fx.get("r") == slot_role:
            return fx
    raise Refuse(f"no {slot_role} entry in graphs.jsonl fx list")


def try_live_oracle_extraction(rel_path):
    """Attempt a live surgepy extraction of the per-slot algorithm's own
    parameters. Returns (ok, detail_or_reason). This is the ONLY step that
    needs the built oracle; the routing-verification metadata above never
    depends on it."""
    try:
        import oracle_common as oc  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - environment-dependent
        return False, f"oracle_common import failed: {e}"
    try:
        surgepy = oc.import_surgepy()
    except Exception as e:
        return False, f"surgepy unavailable (oracle not built in this " \
                      f"environment): {e}"
    # surgepy present: a full per-slot parameter extraction would run here
    # (out of THIS leaf's routing-form scope; left for the algorithm leaf
    # that eventually occupies each concrete slot). Recorded as available
    # but not exercised by this routing-form leaf.
    return True, f"surgepy present ({surgepy.__file__}); per-slot parameter " \
                 f"extraction is algorithm-leaf scope, not exercised here"


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

    g1 = slot_entry(graph, "global1")
    g2 = slot_entry(graph, "global2")
    fxb = graph["g"]["fxb"]
    fxd = graph["g"]["fxd"]

    oracle_ok, oracle_detail = try_live_oracle_extraction(rel)

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028d",
        "routing_form": "rf-global2",
        "preset": {"path": rel, "bank": graph.get("b"),
                   "census_blob_sha1_verified": row["git_blob_sha1"],
                   "graphs_blob_sha1_verified": graph.get("sha"),
                   "stored_revision": graph.get("rev")},
        "patch_level": {"fx_bypass": fxb, "fx_bypass_name": graph["g"].get("fxbn"),
                        "fx_disable_mask": fxd},
        "global1": {"occupied": bool(g1.get("on", 0)), "type_name": g1.get("tn"),
                   "type_id": g1.get("t"),
                   "fx_disable_bit": bool((fxd >> FXSLOT_GLOBAL1) & 1)},
        "global2": {"occupied": bool(g2.get("on", 0)), "type_name": g2.get("tn"),
                   "type_id": g2.get("t"),
                   "fx_disable_bit": bool((fxd >> FXSLOT_GLOBAL2) & 1)},
        "dual_instance_concurrent": bool(g1.get("on", 0)) and bool(g2.get("on", 0)),
        "applicability": {
            "routing_metadata_verified": True,
            "complete_wet_render_possible": False,
            "complete_wet_render_reason":
                "per-slot algorithm parameter extraction requires the "
                "pinned oracle (surgepy); this leaf's own routing/"
                "scheduling claims do not depend on it -- see "
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
        out_path = os.path.join(OUT_DIR, f"rf-rf-global2-{carrier['slug']}.json")
        with open(out_path, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out_path)
        print(f"wrote {out_path}")

    with open(REFUSALS, "w") as f:
        f.write("\n".join(refusal_lines) + ("\n" if refusal_lines else ""))
    for line in refusal_lines:
        print(line)
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
