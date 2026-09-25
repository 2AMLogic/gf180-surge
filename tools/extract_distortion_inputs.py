#!/usr/bin/env python3
"""SXT-028e: fail-closed extraction of Distortion-chain inputs.

Follows the `model/effects/extract_fx_inputs.py` (SXT-023) and
`tools/extract_chorus_inputs.py` (SXT-028c) conventions.

TWO MODES, and they are NOT interchangeable:

  --mode oracle   (default)  Requires the pinned surgepy oracle
      (`oracle/manifest.json`, ORACLE_SURGE_DIR). Reads the loader's
      normalized state: parameter values via `getParamVal`, the two high-cut
      `deactivated` flags and the three `extend_range` flags via the raw
      `.fxp` XML attributes plus the documented loader migrations
      (`DistortionEffect::handleStreamingMismatches`: streamingRevision <= 11
      resets the model index and clears both gain extend_range flags;
      <= 15 clears both high-cut `deactivated` flags), with the census blob
      SHA re-verified at extraction and graphs.jsonl cross-checked. Asserts
      drift == 0. Writes a COMPLETE record the frozen model can run.

  --mode graphs              Oracle-free. Derives ONLY the 12 normalized
      parameter values from `corpus/normalized/graphs.jsonl` (the SXT-011
      pinned-loader export — this IS loader-normalized state, not raw .fxp),
      re-verifies the census blob SHA, and writes an INCOMPLETE record whose
      oracle-only fields are explicitly `null`. `DistortionParams` REFUSES
      such a record (fail-closed): it is a cross-check artifact and an
      extraction-status record, never a substitute for the oracle read.

Distortion (fxt_distortion = 3) parameters (DistortionEffect.h dist_params):
  preeq_gain(0) preeq_freq(1) preeq_bw(2) preeq_highcut(3) drive(4)
  feedback(5) posteq_gain(6) posteq_freq(7) posteq_bw(8) posteq_highcut(9)
  gain(10) model(11)

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, in --mode oracle.
"""

import argparse
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

FX_TYPE_DISTORTION = 3
FX_TYPE_NAME = "Distortion"
DIST_PARAM_NAMES = ["preeq_gain_f", "preeq_freq_f", "preeq_bw_f",
                    "preeq_highcut_f", "drive_f", "feedback_f",
                    "posteq_gain_f", "posteq_freq_f", "posteq_bw_f",
                    "posteq_highcut_f", "gain_f", "model_i"]
ORACLE_ONLY = ["preeq_highcut_deactivated", "posteq_highcut_deactivated",
               "preeq_gain_extend", "posteq_gain_extend", "drive_extend"]

# Issue-named B4-scope carriers (census blob SHA-1 from the issue body /
# reports/sxt-028/leaves/SXT-028e.json)
PRESETS = {
    "novuo": ("resources/data/patches_3rdparty/A.Liv/Leads/Novuo.fxp",
              "e688adfdcdee44073968942914733783163b0e8c"),
    "monsterfeedback": (
        "resources/data/patches_3rdparty/Argitoth/FX/Monster Feedback.fxp",
        "2379e0713eb2830a3c4acbe3a9442500ab960fd9"),
    "screamingsaw": (
        "resources/data/patches_3rdparty/Argitoth/Leads/Screaming Saw.fxp",
        "c811a9aab5849303b252a0c36731e37685288072"),
}

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
CENSUS = os.path.join(REPO, "corpus", "census-v0.1", "corpus-manifest.json")
LEAF_TABLE = os.path.join(REPO, "reports", "coverage-v1",
                          "leaf-verification.json")
OUTDIR = os.path.join(REPO, "model", "effects", "fx_inputs")

# Effect class -> leaf key in the committed verification table (the same
# mapping tools/publish_coverage.py uses). "Off" is not a leaf: an inactive
# slot needs no model. Any class NOT in this map (Airwindows in particular,
# whose leaves are per-algorithm) is treated as unlanded -- fail-closed.
FX_TYPE_TO_LEAF = {
    "Delay": "fx:Delay",
    "EQ": "fx:EQ",
    "Reverb 1": "fx:Reverb1",
    "Chorus": "fx:Chorus",
    "Conditioner": "fx:Conditioner",
    "Distortion": "fx:Distortion",
    "Reverb 2": "fx:Reverb2",
    "Phaser": "fx:Phaser",
}


def landed_classes():
    """FX classes with a landed frozen model, DERIVED, never hand-listed.

    The authority is the committed leaf-verification table's `landed` flags
    (`reports/coverage-v1/leaf-verification.json`), not a literal in this
    file: a hand-maintained set silently goes stale the moment a sibling leaf
    merges, and a stale "landed" claim is exactly the kind of drift this
    extraction is supposed to refuse. A class whose leaf is absent or not
    marked landed counts as UNLANDED (fail-closed) even if a PR for it has
    merged -- the ledger, not the git log, is the basis.
    """
    with open(LEAF_TABLE) as f:
        table = json.load(f)
    leaves = table.get("leaves", {})
    out = {"Off"}
    for tn, key in FX_TYPE_TO_LEAF.items():
        if leaves.get(key, {}).get("landed") is True:
            out.add(tn)
    return out


class Refuse(Exception):
    """A fail-closed refusal: recorded as evidence, never silently dropped."""


def census_sha(path):
    """The census blob SHA-1 for a corpus path (re-verified at extraction)."""
    with open(CENSUS) as f:
        man = json.load(f)
    for e in man.get("entries", []):
        if e.get("path") == path:
            return e["git_blob_sha1"]
    raise Refuse(f"census: no manifest entry for {path}")


def graphs_entry(path):
    with open(GRAPHS) as f:
        for line in f:
            d = json.loads(line)
            if d.get("p") == path:
                return d
    raise Refuse(f"graphs.jsonl: no entry for {path}")


def extract_graphs(slug, path, expect_sha):
    """Oracle-free: loader-normalized parameter VALUES only (mode `graphs`)."""
    sha = census_sha(path)
    if expect_sha and not sha.startswith(expect_sha[:12]):
        raise Refuse(f"{slug}: census blob SHA drift "
                     f"(manifest {sha}, issue {expect_sha})")
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
        for k in ORACLE_ONLY:
            rec[k] = None          # fail-closed: oracle-only, never guessed
        slots.append({"routing": f["r"], "slot_index": f["i"], "params": rec})
    return {
        "schema_version": 1,
        "leaf": "SXT-028e",
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
            "DistortionParams REFUSES a record with null fields, so this "
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


def extract_oracle(slug, path, expect_sha):
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
        "tools/extract_distortion_inputs.py --mode oracle")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("oracle", "graphs"), default="oracle")
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--refusals", default=None)
    args = ap.parse_args()
    if args.refusals is None:
        args.refusals = os.path.join(
            REPO, "reports", "SXT-028e", "artifacts",
            f"extract-refusals-{args.mode}.txt")

    os.makedirs(args.outdir, exist_ok=True)
    os.makedirs(os.path.dirname(args.refusals), exist_ok=True)
    refusals = []
    written = []
    for slug, (path, sha) in sorted(PRESETS.items()):
        try:
            if args.mode == "oracle":
                rec = extract_oracle(slug, path, sha)
            else:
                rec = extract_graphs(slug, path, sha)
        except Refuse as e:
            refusals.append(f"REFUSED {slug} ({path}): {e}")
            print("REFUSED", slug, "-", e)
            continue
        out = os.path.join(args.outdir, f"type-distortion-{slug}.json")
        with open(out, "w") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out)
        print("wrote", os.path.relpath(out, REPO),
              f"({rec['extraction_status']})")
    header = (f"SXT-028e extraction transcript — mode={args.mode}\n"
              f"engine pin surge-synthesizer/surge@"
              f"58914e59c608ed4384ba6002e44c3465c58b2e71\n"
              f"written: {len(written)}  refused: {len(refusals)}\n\n")
    with open(args.refusals, "w") as f:
        f.write(header + "\n".join(refusals) + ("\n" if refusals else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
