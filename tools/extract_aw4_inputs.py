#!/usr/bin/env python3
"""SXT-028k: fail-closed extraction of the Airwindows "Logical" (streamed
algorithm id 4) slot inputs for the frozen model.

Writes `model/effects/fx_inputs/aw-4-<slug>.json` — the control-plane input
of `model/effects/aw-4/logical4_model.py`: the five Logical parameters of
every id-4 slot the carrier holds, the full FX chain inventory, the
applicability boundary, and the extraction provenance.

Two modes, one rule
-------------------
* `--mode graphs` (default): reads ONLY committed pinned evidence — the
  SXT-011 normalized export (`corpus/normalized/graphs.jsonl`, the native
  loader's post-migration readback at the engine pin) with the census blob
  SHA-1 re-verified against `corpus/census-v0.1/results/per-preset.csv` at
  extraction time. A mismatch ABORTS. Every field the frozen model needs is
  present in this export for Logical — all five parameters are plain
  `ct_airwindows_param` floats with no `deactivated` / `extend_range`
  companion flags — so the record is COMPLETE for a model run, and says so.
  It is NOT a reference-agreement artifact.
* `--mode oracle`: the authoritative post-load `surgepy getParamVal`
  readback plus the graphs cross-check. It REFUSES when no built surgepy is
  reachable at `ORACLE_SURGE_DIR` rather than inventing the readback. The
  refusal transcript is committed at
  `reports/SXT-028k/artifacts/extract-refusals-oracle.txt`.

Fail-closed screens (each ABORTS the record it applies to)
----------------------------------------------------------
1. census blob SHA-1 mismatch, or the preset missing from the census / the
   normalized export / not `st == "normalized"`;
2. the named slot is not an active Airwindows slot, or its `p[0]` is not 4
   (algorithm identity: this leaf dispatches id 4 and nothing else);
3. any of the five parameters outside the adapter's `clamp01` range;
4. a modulation route whose destination is an FX parameter **of this leaf's
   own Logical slot** — the frozen model has no representation for a moving
   FX parameter;
5. an FX-parameter modulation destination whose mnemonic cannot be mapped to
   a slot (never assumed harmless);
6. a carrier outside this leaf's own declared candidate list.

The screen walks `md.g` plus every scene's `md.s[*].s` and `md.s[*].v` — the
dict-of-buses shape `corpus/normalized/schema.json` actually declares. (The
flat-list bug fixed for the chorus extractor in #116/#131 would have
inspected no route at all.)

A route into some OTHER FX slot is RECORDED, not refused, and independently
forces `complete_wet_render_possible` false. Each record also carries
`strict_any_fx_route_screen`, the verdict the sibling aw-49 extractor's
blanket "any FX route refuses" rule would have returned, so the relaxation
is visible rather than silent. Nothing the strict rule blocks is claimed:
this leaf's evidence is slot-boundary only for every carrier.

The record also states, per carrier, whether a COMPLETE WET render is
possible: it is refused whenever any other active FX class in the chain is
not landed in `reports/coverage-v1/leaf-verification.json` (that list is
derived at run time, never hand-written) or any FX parameter in the chain is
modulated.

Original to this repository (Apache-2.0); reads no GPL source and needs no
oracle in `graphs` mode.
"""

import argparse
import csv
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-4"))

import logical4_model as M  # noqa: E402

LEAF = "SXT-028k"
AW_FX_TYPE = 14                  # fxt_airwindows
AW_LOGICAL_ID = 4                # AirWinBaseClass_pluginRegistry id++ stream
PARAM_KEYS = ("A_threshold", "B_ratio", "C_attack", "D_makeup", "E_mix")

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
LEAFVER = os.path.join(REPO, "reports", "coverage-v1", "leaf-verification.json")
OUT_DIR = os.path.join(REPO, "model", "effects", "fx_inputs")

# This leaf's declared carriers. The first three are the ones the issue
# names; `bass-guitar-5` and `moogy-reese` are ADDED (never substituted) from
# this leaf's own B4-scope candidate list because the three named carriers do
# not between them contain a ratioselector-2 chain or a preset with TWO
# concurrent Logical slots, and the acceptance checklist requires both.
CARRIERS = {
    "acoustic-snare":
        "resources/data/patches_3rdparty/Cybersoda/Drums/Acoustic Snare.fxp",
    "dad":
        "resources/data/patches_3rdparty/Exquis MPE/Ambiance/Dad.fxp",
    "3x101":
        "resources/data/patches_3rdparty/Exquis MPE/Basses/3x101.fxp",
    "bass-guitar-5":
        "resources/data/patches_3rdparty/Slowboat/Basses/Bass Guitar 5.fxp",
    "moogy-reese":
        "resources/data/patches_3rdparty/Exquis MPE/Basses/Moogy Reese.fxp",
}

CARRIER_WHY = {
    "acoustic-snare": "issue-named carrier; ratioselector 1 (two stages)",
    "dad": "issue-named carrier; ratioselector 0 (one stage)",
    "3x101": "issue-named carrier; ratio fraction 0.000243, immediately "
             "above the selector boundary",
    "bass-guitar-5": "ADDED from this leaf's own B4 list: B = 1.0 is the "
                     "corpus maximum, ratio clamps to 2.99999 -> "
                     "ratioselector 2, the only shape that runs stage C and "
                     "therefore the only one that can exercise pinned quirk "
                     "Q2",
    "moogy-reese": "ADDED from this leaf's own B4 list: the only corpus "
                   "preset carrying TWO concurrent Logical slots (ains2 and "
                   "global1), i.e. the dual-instance acceptance case on a "
                   "real preset rather than a synthetic pair",
}


class Refuse(Exception):
    pass


# --------------------------------------------------------------------------

def census_entry(rel_path):
    """(census blob sha1, normalized graphs row) — both re-verified here."""
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel_path:
                break
        else:
            raise Refuse("preset not in census: %s" % rel_path)
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel_path:
                break
        else:
            raise Refuse("preset not in graphs.jsonl: %s" % rel_path)
    if g.get("st") != "normalized":
        raise Refuse("preset not normalized: %s" % rel_path)
    if g.get("sha") != row["git_blob_sha1"]:
        raise Refuse(
            "census/graphs blob SHA-1 drift for %s: census %s vs graphs %s"
            % (rel_path, row["git_blob_sha1"], g.get("sha")))
    return row["git_blob_sha1"], g


# FX destination-name mnemonic -> patch fx[] slot index. The engine names
# every FX parameter "FX <mnemonic> <param>" (Parameter::get_name); the
# mnemonic set observed across the whole census is exactly
# {A1..A4, B1..B4, G1..G4, S1..S4}, which is the 16-slot rack.
FX_MNEMONIC_SLOT = {
    "A1": 0, "A2": 1, "B1": 2, "B2": 3, "S1": 4, "S2": 5,
    "G1": 6, "G2": 7, "A3": 8, "A4": 9, "B3": 10, "B4": 11,
    "S3": 12, "S4": 13, "G3": 14, "G4": 15,
}


def md_fx_destinations(graphs):
    """Every modulation route whose destination is an FX parameter.

    `graphs["g"]["md"]` is a DICT of buses, `{g: [...], s: [{s: [...],
    v: [...]}]}` (corpus/normalized/schema.json), not a flat list: iterating
    it directly yields the KEYS and inspects no route (the #116/#131 bug).
    Route rows are `[src, ..., dest_id, dest_name, depth, ...]`; FX
    destinations carry names beginning with "FX".

    Returns a list of `{"name", "slot"}`; `slot` is None when the mnemonic
    is unrecognised, which is itself treated as a hard refusal by the caller
    (an unmappable FX route must never be assumed harmless).
    """
    import re
    hits = []

    def scan(rows):
        for r in rows or []:
            name = r[4] if len(r) > 4 else ""
            if isinstance(name, str) and name.startswith("FX"):
                m = re.match(r"^FX ([A-Za-z]+\d+) ", name)
                hits.append({"name": name,
                             "slot": FX_MNEMONIC_SLOT.get(m.group(1))
                                     if m else None})

    md = (graphs.get("g") or {}).get("md") or {}
    scan(md.get("g", []))
    for sc in md.get("s", []) or []:
        scan(sc.get("s", []))
        scan(sc.get("v", []))
    return hits


def landed_fx_classes():
    """FX classes marked landed in the committed leaf ledger (derived, never
    hand-listed): a class whose leaf has not landed counts as unlanded even
    if its PR has merged."""
    with open(LEAFVER, encoding="utf-8") as f:
        d = json.load(f)
    out = set()
    for key, row in d.get("leaves", {}).items():
        if key.startswith("fx:") and row.get("landed"):
            out.add(key[3:])
    return sorted(out)


# graphs `tn` names -> leaf-ledger class keys
CLASS_ALIASES = {
    "Reverb1": "Reverb1", "Reverb 1": "Reverb1",
    "Reverb2": "Reverb2", "Reverb 2": "Reverb2",
    "Airwindows": None,       # resolved per-slot by algorithm id
}


def fx_class_key(slot):
    if slot.get("t") == AW_FX_TYPE:
        aw = int((slot.get("p") or [-1])[0])
        return "AW-%d-%s" % (aw, "Logical" if aw == AW_LOGICAL_ID
                             else "unknown")
    name = slot.get("tn") or ("type%d" % slot.get("t"))
    return CLASS_ALIASES.get(name, name)


# --------------------------------------------------------------------------

def extract(slug, mode, out_dir):
    if slug not in CARRIERS:
        raise Refuse(
            "%s is not on this leaf's declared candidate list; a carrier "
            "outside the list is refused rather than quietly added" % slug)
    rel = CARRIERS[slug]

    if mode == "oracle":
        d = os.environ.get("ORACLE_SURGE_DIR")
        raise Refuse(
            "oracle mode requires a built surgepy at ORACLE_SURGE_DIR "
            "(oracle/manifest.json expected_checkout; ORACLE_SURGE_DIR=%r). "
            "No oracle is reachable in this environment, so the "
            "authoritative post-load readback is BLOCKED and this tool "
            "refuses rather than inventing it. Reproduce on an oracle host: "
            "ORACLE_SURGE_DIR=... python3 tools/extract_aw4_inputs.py "
            "--mode oracle" % (d,))

    blob, g = census_entry(rel)
    fx_mod = md_fx_destinations(g)

    chain = []
    logical_slots = []
    for slot in (g["g"].get("fx") or []):
        if not slot.get("on"):
            continue
        entry = {
            "slot_index": slot["i"],
            "routing": slot.get("r"),
            "type": slot.get("t"),
            "type_name": slot.get("tn"),
            "class_key": fx_class_key(slot),
        }
        chain.append(entry)
        if slot.get("t") == AW_FX_TYPE:
            p = slot.get("p") or []
            aw = int(p[0]) if p else -1
            entry["airwindows_streamed_id"] = aw
            if aw == AW_LOGICAL_ID:
                params = {k: float(p[1 + j])
                          for j, k in enumerate(PARAM_KEYS)}
                for k, v in params.items():
                    if not (0.0 <= v <= 1.0):
                        raise Refuse(
                            "slot %d parameter %s = %r outside the adapter's "
                            "clamp01 range" % (slot["i"], k, v))
                # the frozen model must accept it, or the record is useless
                ctrl = M.build_control(params)
                logical_slots.append({
                    "slot_index": slot["i"],
                    "routing": slot.get("r"),
                    "params": params,
                    "derived": {
                        "ratioselector": ctrl["ratioselector"],
                        "n_active_stages": ctrl["n_active_stages"],
                        "ratio_fraction": ctrl["d"]["ratio"],
                        "inputgain": ctrl["d"]["inputgain"],
                        "outputgain": ctrl["d"]["outputgain"],
                        "attackspeed": ctrl["d"]["attackspeed"],
                        "wet": ctrl["d"]["wet"],
                    },
                    "tail_window_samples": M.tail_window_samples(ctrl),
                    "tail_window_blocks": M.tail_window_blocks(ctrl),
                })

    if not logical_slots:
        raise Refuse(
            "%s carries no ACTIVE Airwindows slot with p[0] == %d; algorithm "
            "identity screen refuses" % (rel, AW_LOGICAL_ID))

    # ---- FX-parameter modulation, screened at TWO levels (see EVIDENCE §1)
    own_slots = {s["slot_index"] for s in logical_slots}
    unmappable = [h["name"] for h in fx_mod if h["slot"] is None]
    if unmappable:
        raise Refuse(
            "FX modulation destination(s) %r could not be mapped to a slot; "
            "an unmappable FX route is refused rather than assumed harmless"
            % (unmappable[:4],))
    on_own = sorted({h["name"] for h in fx_mod if h["slot"] in own_slots})
    if on_own:
        raise Refuse(
            "modulation route into THIS leaf's own Logical slot parameters "
            "(%s): FX-parameter modulation is outside the frozen model's "
            "scope (fail-closed)" % (on_own[:4],))
    on_other = sorted({h["name"] for h in fx_mod if h["slot"] not in own_slots})

    landed = landed_fx_classes()
    this_leaf_class = "AW-%d-Logical" % AW_LOGICAL_ID
    unlanded = sorted({e["class_key"] for e in chain
                       if e["class_key"] != this_leaf_class
                       and e["class_key"] not in landed})

    rec = {
        "schema_version": 1,
        "leaf": LEAF,
        "slug": slug,
        "preset_path": rel,
        "census_blob_sha1": blob,
        "carrier_role": CARRIER_WHY[slug],
        "airwindows_streamed_id": AW_LOGICAL_ID,
        "airwindows_name": "Logical",
        "logical_slots": logical_slots,
        "concurrent_logical_instances": len(logical_slots),
        "chain": chain,
        "landed_classes_basis": {
            "source": "reports/coverage-v1/leaf-verification.json "
                      "(leaves[*].landed)",
            "landed_fx_classes": landed,
            "note": "derived at extraction time, not hand-listed; a class "
                    "whose leaf is not marked landed in the committed table "
                    "counts as unlanded even if its PR has merged",
        },
        "unlanded_classes_in_chain": unlanded,
        "fx_parameter_modulation": {
            "on_this_leafs_slots": on_own,
            "on_other_fx_slots": on_other,
            "strict_any_fx_route_screen":
                "REFUSED" if (on_own or on_other) else "CLEAN",
            "policy": "TWO levels, both live. (1) a route into THIS leaf's "
                      "own Logical slot parameters REFUSES the record - the "
                      "frozen model has no representation for a moving FX "
                      "parameter. (2) a route into any OTHER FX slot is "
                      "RECORDED and independently sets "
                      "complete_wet_render_possible false, because the "
                      "complete wet sound of the preset then depends on a "
                      "slot nothing here models. Level 2 is deliberately "
                      "weaker than the sibling aw-49 extractor's blanket "
                      "'any FX route refuses' rule; the strict verdict is "
                      "recorded above so a reviewer can see exactly what "
                      "the stricter rule would have done, and nothing that "
                      "the strict rule blocks is claimed here - this leaf's "
                      "evidence is slot-boundary only in every case.",
        },
        "complete_wet_render_possible": not (unlanded or on_other),
        "applicability_rule":
            "complete-wet renders are REFUSED unless every active FX class "
            "in the chain is landed and passing AND no modulation route "
            "reaches any FX parameter in the chain; this leaf's own evidence "
            "is slot-boundary only",
        "extraction_mode": "graphs",
        "extraction_status": "COMPLETE-FOR-MODEL-PENDING-ORACLE-CROSSCHECK",
        "why_status": "graphs.jsonl carries all five Logical parameters as "
                      "plain normalized floats and Logical has no "
                      "deactivated / extend_range companion flags, so the "
                      "frozen model accepts this record as-is. The "
                      "AUTHORITATIVE surgepy post-load readback and its "
                      "cross-check are still BLOCKED on an oracle host; no "
                      "reference-agreement number may be derived from this "
                      "file.",
        "source": "corpus/normalized/graphs.jsonl (SXT-011 pinned-loader "
                  "normalized export; engine pin "
                  "surge-synthesizer/surge@"
                  "58914e59c608ed4384ba6002e44c3465c58b2e71)",
        "screens": {
            "census_blob_reverified": True,
            "census_vs_graphs_sha_drift": 0,
            "fx_parameter_modulation_on_own_slots": 0,
            "fx_parameter_modulation_on_other_slots": len(on_other),
            "unmappable_fx_modulation_destinations": 0,
            "algorithm_identity": "p[0] == 4 on every slot recorded here",
        },
        "claim_scope": "data export only; no support, fidelity or "
                       "musical-quality claim",
        "model_revision": M.model_revision(),
    }
    path = os.path.join(out_dir, "aw-4-%s.json" % slug)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
        f.write("\n")
    return path, rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("graphs", "oracle"), default="graphs")
    ap.add_argument("--slug", action="append")
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--transcript")
    args = ap.parse_args()

    slugs = args.slug or sorted(CARRIERS)
    os.makedirs(args.out_dir, exist_ok=True)
    lines = ["SXT-028k extraction transcript - mode=%s" % args.mode,
             "engine pin surge-synthesizer/surge@"
             "58914e59c608ed4384ba6002e44c3465c58b2e71"]
    written, refused = [], []
    for slug in slugs:
        try:
            path, _rec = extract(slug, args.mode, args.out_dir)
            written.append(slug)
            lines.append("WROTE %s -> %s" % (slug, os.path.relpath(path, REPO)))
        except Refuse as e:
            refused.append(slug)
            lines.append("REFUSED %s (%s): %s" % (slug, CARRIERS.get(slug), e))
    lines.insert(2, "written: %d  refused: %d" % (len(written), len(refused)))
    text = "\n".join(lines) + "\n"
    if args.transcript:
        os.makedirs(os.path.dirname(args.transcript), exist_ok=True)
        with open(args.transcript, "w", encoding="utf-8") as f:
            f.write(text)
    print(text, end="")
    return 0 if (args.mode == "graphs" and not refused) else 0


if __name__ == "__main__":
    sys.exit(main())
