#!/usr/bin/env python3
"""SXT-028b parameter corners for the Conditioner leaf (claim 1 inputs).

Three corner families (issue #54 "Parameter corners"):

  * loader defaults -- Parameter::set_type defaults for the ctrltypes set in
    ConditionerEffect::init_ctrltypes (pinned src/common/Parameter.cpp):
    ct_decibel_extra_narrow_deactivatable [-12, 12] default 0 (bass,
    treble); ct_percent_bipolar [-1, 1] default 0 (width, balance, attack,
    release); ct_decibel_attenuation [-48, 0] default 0 (threshold, gain);
    ct_freq_audible_deactivatable_hp [-60, 70] default -60 (side low cut),
    plus init_default_values(): bass/treble active, hpwidth deactivated;
  * extremes of each named param (all-min and all-max, every stage active);
  * the fixture presets' stored values, read from corpus/normalized/
    graphs.jsonl (SXT-011: native-loader-normalized, rounded to 6 decimals),
    census blob SHA-1 re-verified against corpus/census-v0.1 per-preset.csv.

LIMITATION (recorded, not hidden): graphs.jsonl does not export the
`deactivated` flags, so for the fixture-value corners they are ASSUMED at
the engine defaults (bass/treble active, side low cut deactivated). These
corners therefore exercise claim (1) RTL == frozen model on realistic
values only; they are NOT the fail-closed extraction the reference leg needs
(tools/extract_conditioner_inputs.py, oracle host, NOT_RUN here).

Original to this repository (Apache-2.0).
"""
import csv
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PARAM_ORDER = ("bass_db", "treble_db", "width_f", "balance_f", "threshold_db",
               "attack_f", "release_f", "gain_db", "hpwidth_semitones")
RANGES = {  # pinned Parameter.cpp ranges for the ctrltypes above
    "bass_db": (-12.0, 12.0, 0.0), "treble_db": (-12.0, 12.0, 0.0),
    "width_f": (-1.0, 1.0, 0.0), "balance_f": (-1.0, 1.0, 0.0),
    "threshold_db": (-48.0, 0.0, 0.0), "attack_f": (-1.0, 1.0, 0.0),
    "release_f": (-1.0, 1.0, 0.0), "gain_db": (-48.0, 0.0, 0.0),
    "hpwidth_semitones": (-60.0, 70.0, -60.0),
}
FX_TYPE_CONDITIONER = 8

FIXTURE_PRESETS = {
    "doomsday": "resources/data/patches_factory/Basses/Doomsday.fxp",
    "piercing": "resources/data/patches_3rdparty/Altenberg/Basses/Piercing.fxp",
    "aoe": "resources/data/patches_3rdparty/Altenberg/Leads/AOE.fxp",
    "computerlanguage1":
        "resources/data/patches_3rdparty/Argitoth/FX/Computer Language 1.fxp",
}
# census blob prefixes named in issue #54 (verified again against the census)
ISSUE_BLOB_PREFIX = {"doomsday": "a8a3a395d52c", "piercing": "d02d14ea299b",
                     "aoe": "427dedd36235", "computerlanguage1": "fed86e4fda95"}


def defaults():
    d = {k: RANGES[k][2] for k in PARAM_ORDER}
    d.update(bass_deactivated=False, treble_deactivated=False,
             hpwidth_deactivated=True)
    return d


def extreme(which):
    i = 0 if which == "min" else 1
    d = {k: RANGES[k][i] for k in PARAM_ORDER}
    d.update(bass_deactivated=False, treble_deactivated=False,
             hpwidth_deactivated=False)
    return d


def census_blob(rel_path):
    path = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel_path:
                return row["git_blob_sha1"]
    raise KeyError(f"not in census: {rel_path}")


def graphs_line(rel_path):
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel_path:
                return g
    raise KeyError(f"not in graphs.jsonl: {rel_path}")


def fixture_corners():
    """[(slug, params, provenance)] for every Conditioner slot of each
    fixture preset (fail-closed on any census/graphs inconsistency)."""
    out = []
    for slug, rel in sorted(FIXTURE_PRESETS.items()):
        g = graphs_line(rel)
        blob = census_blob(rel)
        if g["st"] != "normalized":
            raise ValueError(f"{slug}: graphs status {g['st']}")
        if g["sha"] != blob or not blob.startswith(ISSUE_BLOB_PREFIX[slug]):
            raise ValueError(f"{slug}: blob mismatch graphs={g['sha']} census={blob}")
        slots = [fx for fx in g["g"]["fx"] if fx.get("t") == FX_TYPE_CONDITIONER]
        if not slots:
            raise ValueError(f"{slug}: no Conditioner slot")
        for fx in slots:
            vals = fx["p"][:len(PARAM_ORDER)]
            params = dict(zip(PARAM_ORDER, (float(v) for v in vals)))
            for k, v in params.items():
                lo, hi, _ = RANGES[k]
                if not lo <= v <= hi:
                    raise ValueError(f"{slug}: {k}={v} outside [{lo},{hi}]")
            params.update(bass_deactivated=False, treble_deactivated=False,
                          hpwidth_deactivated=True)
            out.append((f"{slug}-slot{fx['i']:02d}", params, {
                "path": rel, "census_blob_sha1": blob, "graphs_rev": g.get("rev"),
                "slot": fx["i"], "role": fx["r"], "on": fx["on"],
                "active_chain": [(f["i"], f["r"], f["tn"]) for f in g["g"]["fx"]
                                 if f.get("on")],
                "deactivated_flags": "ASSUMED engine defaults (graphs.jsonl "
                                     "does not export them); claim-1 corner only",
            }))
    return out


def all_corners():
    c = [("loader-defaults", defaults(), {"source": "Parameter.cpp defaults + "
                                          "init_default_values"}),
         ("extreme-min", extreme("min"), {"source": "Parameter.cpp val_min"}),
         ("extreme-max", extreme("max"), {"source": "Parameter.cpp val_max"})]
    return c + fixture_corners()


if __name__ == "__main__":
    for name, p, prov in all_corners():
        print(name, json.dumps(p, sort_keys=True), prov.get("role", ""))
