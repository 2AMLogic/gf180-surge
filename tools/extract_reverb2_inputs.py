#!/usr/bin/env python3
"""SXT-028f: fail-closed extraction of Reverb 2 chain inputs.

Source of truth is the COMMITTED pinned normalized state, not raw .fxp
bytes: `corpus/normalized/graphs.jsonl` (SXT-011) is the native loader's
post-migration readback from
surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71 at 48 kHz,
and every line re-states its own pin. Census blob identity is re-verified
against `corpus/census-v0.1/corpus-manifest.json` at extraction time; a
mismatch aborts.

Reverb 2 parameter order (sst-effects Reverb2.h:40-57 rev2_params, which is
the order the engine exposes in fx[].p):

    0 predelay   1 room_size  2 decay_time  3 diffusion  4 buildup
    5 modulation 6 lf_damping 7 hf_damping  8 width      9 mix

The mapping is cross-checked per preset against each parameter's declared
range (Reverb2.h:152-197 paramAt): a value outside its declared range is a
REFUSAL, never a silent clamp.

FAIL-CLOSED BOUNDARIES (recorded, never assumed away):

  * temposync. `rev2_predelay` is temposyncable, and the per-parameter
    temposync flag is NOT part of the SXT-011 normalized graph (and the
    .fxp bytes are external GPL assets that this repository does not
    carry). Without the oracle host the flag is UNRESOLVED, so every
    emitted record carries `ts_predelay: null` and its applicability
    record sets `complete_wet_render_possible: false`.
  * determinism drift. The SXT-012 3x bit-identical render gate needs the
    oracle; `drift_asserted` is therefore null (NOT_RUN), never 0.
  * unlanded sibling FX classes in the same chain refuse the
    complete-wet claim (the SXT-028c precedent).
  * any modulation route whose destination names an FX parameter refuses
    the preset (parameter modulation into FX parameters is outside the
    frozen model scope).

Usage:
  python3 tools/extract_reverb2_inputs.py            # named carriers
  python3 tools/extract_reverb2_inputs.py --scan     # + corpus-wide ledger
Original to this repository (Apache-2.0). No engine source, preset payload
or GPL asset is read or copied by this tool.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
CENSUS = os.path.join(REPO, "corpus", "census-v0.1", "corpus-manifest.json")
OUTDIR = os.path.join(REPO, "model", "effects", "fx_inputs")
ARTDIR = os.path.join(REPO, "reports", "SXT-028f", "artifacts")

FX_TYPE_REVERB2 = 11

REV2_PARAM_NAMES = ["predelay_f", "room_size_f", "decay_time_f",
                    "diffusion_f", "buildup_f", "modulation_f",
                    "lf_damping_f", "hf_damping_f", "width_f", "mix_f"]
# declared ranges (Reverb2.h paramAt): percent [0,1], bipolar [-1,1],
# decibel-narrow width [-24,24] (Surge's asDecibelNarrow)
REV2_PARAM_RANGE = [(-8.0, 1.0), (-1.0, 1.0), (-4.0, 6.0), (0.0, 1.0),
                    (0.0, 1.0), (0.0, 1.0), (0.0, 1.0), (0.0, 1.0),
                    (-24.0, 24.0), (0.0, 1.0)]

# FX classes with a landed frozen model in this repository
LANDED = {0: "off", 1: "delay (SXT-023)", 2: "reverb1 (SXT-024)",
          6: "eq (SXT-023)", 9: "chorus (SXT-028c)",
          FX_TYPE_REVERB2: "reverb2 (SXT-028f, this leaf)"}

CARRIERS = {
    "grant_me": "resources/data/patches_3rdparty/A.Liv/Keys/Grant Me....fxp",
    "novuo": "resources/data/patches_3rdparty/A.Liv/Leads/Novuo.fxp",
    "harp": "resources/data/patches_3rdparty/Aleksey Zhehanov/Strings/Harp.fxp",
}


class Refuse(Exception):
    """A fail-closed extraction refusal (recorded, never swallowed)."""


def load_census():
    with open(CENSUS) as f:
        man = json.load(f)
    return {e["path"]: e for e in man["entries"]}, man


def iter_graphs(paths=None):
    with open(GRAPHS) as f:
        for line in f:
            d = json.loads(line)
            if paths is None or d.get("p") in paths:
                yield d


def fx_destination_routes(md):
    """Modulation routes whose destination names an FX parameter."""
    hits = []
    for row in md.get("g", []) or []:
        name = str(row[4]) if len(row) > 4 else ""
        if name.startswith("FX "):
            hits.append(name)
    for sc in md.get("s", []) or []:
        for bus in ("s", "v"):
            for row in sc.get(bus, []) or []:
                name = str(row[4]) if len(row) > 4 else ""
                if name.startswith("FX "):
                    hits.append(name)
    return hits


def extract_one(graph, census):
    path = graph["p"]
    refusals = []
    if graph.get("st") != "normalized":
        raise Refuse("graph status is %r, not 'normalized'" % graph.get("st"))
    ce = census.get(path)
    if ce is None:
        raise Refuse("path is not in the census manifest")
    if ce["git_blob_sha1"] != graph.get("sha"):
        raise Refuse("census blob SHA-1 mismatch: %s != %s"
                     % (ce["git_blob_sha1"], graph.get("sha")))
    pin = graph.get("pin", {})
    g = graph["g"]

    slots = [f for f in g["fx"] if f.get("on")]
    rev2 = [f for f in slots if f["t"] == FX_TYPE_REVERB2]
    if not rev2:
        raise Refuse("no active Reverb 2 slot")

    instances = []
    for f in rev2:
        p = f.get("p") or []
        if len(p) < len(REV2_PARAM_NAMES):
            raise Refuse("slot %d has %d params, expected >= %d"
                         % (f["i"], len(p), len(REV2_PARAM_NAMES)))
        params = {}
        for j, name in enumerate(REV2_PARAM_NAMES):
            v = float(p[j])
            lo, hi = REV2_PARAM_RANGE[j]
            if not (lo - 1e-6 <= v <= hi + 1e-6):
                raise Refuse("slot %d param %s = %r outside declared range "
                             "[%g, %g]" % (f["i"], name, v, lo, hi))
            params[name] = v
        # temposync for rev2_predelay is NOT in the normalized graph
        params["ts_predelay"] = None
        params["ts_ratio_inv"] = None
        instances.append({"slot": f["i"], "role": f["r"],
                          "return_level": f.get("rl"), "params": params})

    chain = []
    unlanded = []
    for f in slots:
        landed = f["t"] in LANDED
        chain.append({"slot": f["i"], "role": f["r"], "type": f["t"],
                      "type_name": f["tn"], "landed_model": landed,
                      "landed_ref": LANDED.get(f["t"])})
        if not landed:
            unlanded.append(f["tn"])

    fxmod = fx_destination_routes(g.get("md", {}))
    if fxmod:
        refusals.append("modulation routes target FX parameters: %s"
                        % ", ".join(sorted(set(fxmod))))
    if g.get("fxb", 0) != 0:
        refusals.append("fx_bypass is %r (not 'All FX')" % g.get("fxbn"))
    if g.get("fxd", 0) != 0:
        refusals.append("fx_disable bitmask is %d (slots individually "
                        "disabled)" % g.get("fxd"))
    if unlanded:
        refusals.append("chain needs unlanded FX classes: %s"
                        % ", ".join(sorted(set(unlanded))))
    refusals.append("rev2_predelay temposync flag UNRESOLVED without the "
                    "oracle host (not carried by the SXT-011 normalized "
                    "graph; the .fxp bytes are external)")
    refusals.append("SXT-012 3x bit-identical determinism gate NOT_RUN "
                    "(requires the oracle host)")

    return {
        "schema_version": 1,
        "leaf": "SXT-028f",
        "fx_class": "Reverb 2",
        "source": {
            "normalized_graph": "corpus/normalized/graphs.jsonl (SXT-011)",
            "census_manifest": "corpus/census-v0.1/corpus-manifest.json",
            "engine_pin": pin.get("e"),
            "sample_rate_hz": pin.get("sr"),
            "patch_revision": graph.get("rev"),
        },
        "preset": {"path": path, "bank": graph.get("b"),
                   "git_blob_sha1": graph["sha"], "size": graph.get("sz"),
                   "census_size": ce.get("size")},
        "census_blob_reverified": True,
        "param_order_ref": ("sst-effects Reverb2.h:40-57 rev2_params; each "
                            "value range-checked against Reverb2.h:152-197 "
                            "paramAt"),
        "instances": instances,
        "chain": chain,
        "scene_mode": g.get("smn"),
        "fx_bypass": g.get("fxbn"),
        "fx_disable": g.get("fxd"),
        "drift_asserted": None,
        "applicability": {
            "complete_wet_render_possible": False,
            "reasons": refusals,
            "status": "BLOCKED (oracle host required)",
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true",
                    help="also write the corpus-wide Reverb 2 carrier ledger")
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--artdir", default=ARTDIR)
    args = ap.parse_args()

    census, man = load_census()
    os.makedirs(args.outdir, exist_ok=True)
    os.makedirs(args.artdir, exist_ok=True)

    by_path = {v: k for k, v in CARRIERS.items()}
    written, refused = [], []
    for graph in iter_graphs(set(CARRIERS.values())):
        slug = by_path[graph["p"]]
        try:
            doc = extract_one(graph, census)
        except Refuse as e:
            refused.append({"slug": slug, "path": graph["p"],
                            "refusal": str(e)})
            continue
        out = os.path.join(args.outdir, "type-reverb 2-%s.json" % slug)
        with open(out, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(os.path.relpath(out, REPO))
        print("wrote", os.path.relpath(out, REPO),
              "| complete-wet:",
              doc["applicability"]["complete_wet_render_possible"])

    if refused:
        with open(os.path.join(args.artdir, "extract-refusals.txt"),
                  "w") as f:
            for r in refused:
                f.write("%s\t%s\t%s\n" % (r["slug"], r["path"], r["refusal"]))
        for r in refused:
            print("REFUSED", r["slug"], "->", r["refusal"])

    if args.scan:
        rows = []
        for graph in iter_graphs():
            if graph.get("st") != "normalized":
                continue
            g = graph["g"]
            slots = [f for f in g["fx"] if f.get("on")]
            r2 = [f for f in slots if f["t"] == FX_TYPE_REVERB2]
            if not r2:
                continue
            unlanded = sorted({f["tn"] for f in slots if f["t"] not in LANDED})
            rows.append({
                "path": graph["p"], "bank": graph.get("b"),
                "sha": graph["sha"],
                "reverb2_slots": [f["r"] for f in r2],
                "instances": len(r2),
                "unlanded_classes": unlanded,
                "strict_fx_complete": not unlanded,
                "fx_bypass": g.get("fxbn"), "fx_disable": g.get("fxd"),
                "fx_param_modulation": bool(
                    fx_destination_routes(g.get("md", {}))),
            })
        ledger = {
            "schema_version": 1, "leaf": "SXT-028f",
            "source": "corpus/normalized/graphs.jsonl (SXT-011)",
            "engine_pin": man.get("commit"),
            "totals": {
                "carriers": len(rows),
                "multi_instance_carriers": sum(1 for r in rows
                                               if r["instances"] > 1),
                "strict_fx_complete": sum(1 for r in rows
                                          if r["strict_fx_complete"]),
                "with_fx_param_modulation": sum(1 for r in rows
                                                if r["fx_param_modulation"]),
            },
            "claim_scope": ("inventory and prioritisation only (AGENTS.md): "
                            "NOT a support claim, NOT a coverage claim"),
            "carriers": sorted(rows, key=lambda r: r["path"]),
        }
        out = os.path.join(args.artdir, "carrier-ledger.json")
        with open(out, "w") as f:
            json.dump(ledger, f, indent=2, sort_keys=True)
            f.write("\n")
        print("ledger:", ledger["totals"])

    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
