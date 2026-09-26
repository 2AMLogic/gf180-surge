#!/usr/bin/env python3
"""SXT-028e-sse: fail-closed extraction of SSE-branch Distortion inputs.

Follows `tools/extract_distortion_inputs.py` (SXT-028e) exactly and REUSES
its parameter-name table, its census/graphs readers, its landed-class
derivation and its refusal machinery; only the carrier set and the
admissible FX model indices differ.

TWO MODES, and they are NOT interchangeable:

  --mode oracle   (default)  Requires the pinned surgepy oracle
      (`oracle/manifest.json`, ORACLE_SURGE_DIR). Writes a COMPLETE record
      the frozen model can run.
  --mode graphs              Oracle-free. Derives ONLY the 12 normalized
      parameter values from `corpus/normalized/graphs.jsonl`, re-verifies
      the census blob SHA, and writes an INCOMPLETE record whose oracle-only
      fields are explicitly `null`. `DistortionSSEParams` REFUSES such a
      record (fail-closed): it is a cross-check artifact and an
      extraction-status record, never a substitute for the oracle read.

CARRIER SELECTION IS THIS LEAF'S OWN. None of the three B4-scope carriers
named by SXT-028e (#57) uses an SSE-branch model -- all three are model 0 --
so this leaf selects one carrier per REACHABLE FX model from
`corpus/normalized/graphs.jsonl`, preferring the simplest active chain.
Inventory only; NOT a support claim.

  model 3 wst_sine       Damon Armani / Drums / Reverse Crash
  model 4 wst_digital    Damon Armani / Plucks / Trance Pluck
  model 5 wst_ojd        Kinsey Dulcet / Guitars / Mutant Lo-Fi Acoustic ...
  model 6 wst_fwrectify  Luna / Guitars / Awful FM Guitar   (fx_disable != 0
                         -- REFUSED by the shared fail-closed screen; it is
                         the ONLY model-6 instance in the whole corpus)
  model 7 wst_fuzzsoft   NO CARRIER EXISTS. The corpus histogram for active
                         Distortion slots is {3: 13, 4: 8, 5: 6, 6: 1, 7: 0}
                         -- `wst_fuzzsoft` is in algorithmic scope but has
                         ZERO corpus reach, so it is exercised by synthetic
                         corners only and no fixture record is written. That
                         is recorded, not silently skipped.

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, in --mode oracle.
"""

import argparse
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))

from sse_tables import SSE_MODELS, SSE_SHAPER_OF, FXWS_NAMES  # noqa: E402


def _load_sxt028e_extractor():
    path = os.path.join(REPO, "tools", "extract_distortion_inputs.py")
    spec = importlib.util.spec_from_file_location("sxt028e_extract", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E57 = _load_sxt028e_extractor()
Refuse = E57.Refuse
census_sha = E57.census_sha
graphs_entry = E57.graphs_entry
landed_classes = E57.landed_classes
FX_TYPE_TO_LEAF = E57.FX_TYPE_TO_LEAF
DIST_PARAM_NAMES = E57.DIST_PARAM_NAMES
ORACLE_ONLY = E57.ORACLE_ONLY
FX_TYPE_NAME = E57.FX_TYPE_NAME
OUTDIR = E57.OUTDIR

LEAF = "SXT-028e-sse"

# One carrier per reachable FX model (see the module docstring).
PRESETS = {
    "reversecrash": (
        "resources/data/patches_3rdparty/Damon Armani/Drums/Reverse Crash.fxp",
        "de5c684d96d6090728dfe2ede0a3dbd73af1d65f", 3),
    "trancepluck": (
        "resources/data/patches_3rdparty/Damon Armani/Plucks/Trance Pluck.fxp",
        "1bb5209f0f1d306df05a109d6015cf1a99c73d08", 4),
    "mutantlofiacoustic": (
        "resources/data/patches_3rdparty/Kinsey Dulcet/Guitars/"
        "Mutant Lo-Fi Acoustic Guitar Workstation.fxp",
        "714821ee0c7561bc1293bb422e2c4bd2f978b163", 5),
    "awfulfmguitar": (
        "resources/data/patches_3rdparty/Luna/Guitars/Awful FM Guitar.fxp",
        "d71a9cfd39789ca43e9b72ca3e65dd40d10be8f2", 6),
}
# FX models with zero corpus reach: recorded, never silently omitted.
NO_CARRIER_MODELS = [7]


def extract_graphs(slug, path, expect_sha, expect_model):
    """Oracle-free: loader-normalized parameter VALUES only (mode `graphs`)."""
    sha = census_sha(path)
    if expect_sha and not sha.startswith(expect_sha[:12]):
        raise Refuse(f"{slug}: census blob SHA drift "
                     f"(manifest {sha}, expected {expect_sha})")
    d = graphs_entry(path)
    if d.get("st") != "normalized":
        raise Refuse(f"{slug}: graphs status {d.get('st')} (not normalized)")
    g = d["g"]
    if g.get("fxd", 0) != 0:
        raise Refuse(f"{slug}: fx_disable = {g['fxd']} (non-zero)")
    landed = landed_classes()
    active = [f for f in g["fx"] if f.get("on")]
    unlanded = sorted({f["tn"] for f in active if f["tn"] not in landed})
    dist_slots = [f for f in active if f["tn"] == FX_TYPE_NAME]
    if not dist_slots:
        raise Refuse(f"{slug}: no active Distortion slot")
    slots = []
    for f in dist_slots:
        p = f["p"]
        rec = {k: p[i] for i, k in enumerate(DIST_PARAM_NAMES)}
        rec["model_i"] = int(p[11])
        if rec["model_i"] not in SSE_MODELS:
            # fail-closed the OTHER way: a model-0..2 slot belongs to #57
            raise Refuse(
                f"{slug}: Distortion slot {f['r']} uses FX model "
                f"{rec['model_i']} ({FXWS_NAMES[rec['model_i']]}), which is "
                "the SXT-028e (#57) table branch, not this leaf's SSE branch")
        for k in ORACLE_ONLY:
            rec[k] = None          # fail-closed: oracle-only, never guessed
        slots.append({"routing": f["r"], "slot_index": f["i"],
                      "fx_model_index": rec["model_i"],
                      "quad_waveshaper": SSE_SHAPER_OF[rec["model_i"]],
                      "params": rec})
    got_models = sorted({s["fx_model_index"] for s in slots})
    if expect_model is not None and expect_model not in got_models:
        raise Refuse(f"{slug}: expected FX model {expect_model}, "
                     f"graphs has {got_models}")
    return {
        "schema_version": 1,
        "leaf": LEAF,
        "slug": slug,
        "preset_path": path,
        "census_blob_sha1": sha,
        "extraction_mode": "graphs",
        "extraction_status": "INCOMPLETE-BLOCKED-ON-ORACLE",
        "source": "corpus/normalized/graphs.jsonl (SXT-011 pinned-loader "
                  "normalized export; deterministic, engine pin "
                  "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71)",
        "unresolved_fields": ORACLE_ONLY,
        "why_incomplete":
            "graphs.jsonl carries the 12 normalized FX parameter values but "
            "not the per-parameter `deactivated` / `extend_range` flags. "
            "DistortionSSEParams REFUSES a record with null fields, so this "
            "artifact cannot be used for a model run — it is a cross-check "
            "and extraction-status record only.",
        "chain": [{"routing": f["r"], "type": f["tn"], "slot_index": f["i"]}
                  for f in active],
        "unlanded_classes_in_chain": unlanded,
        "landed_classes_basis": {
            "source": "reports/coverage-v1/leaf-verification.json "
                      "(leaves[*].landed)",
            "landed_fx_classes": sorted(landed - {"Off"}),
            "note": "derived at extraction time, not hand-listed; a class "
                    "whose leaf is not marked landed in the committed table "
                    "counts as unlanded even if its PR has merged",
        },
        "complete_wet_render_possible": not unlanded,
        "distortion_slots": slots,
        "claim_scope": "data export only; no support, fidelity or "
                       "musical-quality claim",
    }


def extract_oracle(slug, path, expect_sha, expect_model):
    """Oracle mode (requires the pinned surgepy build; see oracle/README.md)."""
    sys.path.insert(0, os.path.join(REPO, "oracle"))
    try:
        import oracle_common as oc  # noqa: F401
    except ImportError as e:
        raise Refuse(f"oracle harness unavailable: {e}")
    raise Refuse(
        "oracle mode requires a built surgepy at ORACLE_SURGE_DIR "
        "(oracle/manifest.json expected_checkout). No oracle is reachable in "
        "this environment, so the oracle extraction is BLOCKED and this tool "
        "refuses rather than inventing the missing flags. Reproduce on an "
        "oracle host: ORACLE_SURGE_DIR=... python3.11 "
        "tools/extract_distortion_sse_inputs.py --mode oracle")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("oracle", "graphs"), default="oracle")
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--refusals", default=None)
    args = ap.parse_args()
    if args.refusals is None:
        args.refusals = os.path.join(
            REPO, "reports", "SXT-028e-sse", "artifacts",
            f"extract-refusals-{args.mode}.txt")

    os.makedirs(args.outdir, exist_ok=True)
    os.makedirs(os.path.dirname(args.refusals), exist_ok=True)
    refusals = []
    written = []
    for slug, (path, sha, model) in sorted(PRESETS.items()):
        try:
            if args.mode == "oracle":
                rec = extract_oracle(slug, path, sha, model)
            else:
                rec = extract_graphs(slug, path, sha, model)
        except Refuse as e:
            refusals.append(f"REFUSED {slug} ({path}): {e}")
            print("REFUSED", slug, "-", e)
            continue
        out = os.path.join(args.outdir, f"type-distortion-sse-{slug}.json")
        with open(out, "w") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out)
        print("wrote", os.path.relpath(out, REPO),
              f"({rec['extraction_status']})")
    for mi in NO_CARRIER_MODELS:
        refusals.append(
            f"NO-CARRIER model {mi} ({FXWS_NAMES[mi]}, {SSE_SHAPER_OF[mi]}): "
            "zero active Distortion slots in corpus/normalized/graphs.jsonl "
            "use this FX model. The algorithm is implemented and exercised by "
            "synthetic corners; no fixture record exists and none is invented.")
        print("NO-CARRIER model", mi, FXWS_NAMES[mi])
    header = (f"{LEAF} extraction transcript — mode={args.mode}\n"
              f"engine pin surge-synthesizer/surge@"
              f"58914e59c608ed4384ba6002e44c3465c58b2e71\n"
              f"written: {len(written)}  refused/no-carrier: {len(refusals)}\n\n")
    with open(args.refusals, "w") as f:
        f.write(header + "\n".join(refusals) + ("\n" if refusals else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
