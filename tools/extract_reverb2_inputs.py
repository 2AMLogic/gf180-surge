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
    carry). WITHOUT `--oracle` the flag stays UNRESOLVED (`ts_predelay:
    null`) and `complete_wet_render_possible` is false. WITH `--oracle`
    it is resolved from the native loader's own read-back
    (`SurgeSynthesizer::getTempoSync` on the slot's predelay parameter
    after `loadPatch`), which is the authoritative post-migration state.
  * determinism drift. The SXT-012 3x bit-identical render gate needs the
    oracle; `drift_asserted` is null (NOT_RUN) until the gate record
    written by tools/render_reverb2_fixtures.py says otherwise. It is set
    to 0 ONLY for a carrier whose every committed bus passed the gate --
    a REFUSED carrier keeps null and gains a measured refusal record.
  * unlanded sibling FX classes in the same chain refuse the
    complete-wet claim (the SXT-028c precedent). Note this is a
    *complete-preset* refusal; the class-scope reference leg of #126 has
    its own, narrower boundary (`reference_leg` below).
  * any modulation route whose destination names an FX parameter refuses
    the preset (parameter modulation into FX parameters is outside the
    frozen model scope).

Usage:
  python3 tools/extract_reverb2_inputs.py            # committed evidence only
  python3 tools/extract_reverb2_inputs.py --scan     # + corpus-wide ledger
  "$ORACLE_PYTHON" tools/extract_reverb2_inputs.py --oracle   # + readback
Original to this repository (Apache-2.0). No engine source, preset payload
or GPL asset is read or copied by this tool.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, REPO)

from refusal import Refuse  # noqa: E402

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

# The three issue-named B4-scope carriers (#58) ...
NAMED_CARRIERS = {
    "grant_me": "resources/data/patches_3rdparty/A.Liv/Keys/Grant Me....fxp",
    "novuo": "resources/data/patches_3rdparty/A.Liv/Leads/Novuo.fxp",
    "harp": "resources/data/patches_3rdparty/Aleksey Zhehanov/Strings/Harp.fxp",
}
# ... and the screened deterministic carriers the reference leg of #126
# actually runs on, because all three named ones are REFUSED by the
# empirical 3x render gate (tools/render_reverb2_fixtures.py; the SXT-028c
# precedent, where the issue-named carriers were likewise refused and
# replaced by screened ones).
SCREENED_CARRIERS = {
    "tacobell": "resources/data/patches_3rdparty/Luna/Bells/Taco Bell.fxp",
    "moire1": "resources/data/patches_3rdparty/Jacky Ligon/Soundscapes/Moire 1.fxp",
    "mystical": "resources/data/patches_3rdparty/TNMG/Bells/Mystical Creature.fxp",
}
CARRIERS = dict(NAMED_CARRIERS, **SCREENED_CARRIERS)


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
    refusals.append(TS_UNRESOLVED)
    refusals.append(GATE_NOT_RUN)

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
        "volume_f": None,
        "applicability": {
            "complete_wet_render_possible": False,
            "reasons": refusals,
            "status": "BLOCKED (oracle host required)",
        },
    }


# ------------------------------------------------------------- oracle leg
TS_UNRESOLVED = ("rev2_predelay temposync flag UNRESOLVED without the "
                 "oracle host (not carried by the SXT-011 normalized "
                 "graph; the .fxp bytes are external)")
GATE_NOT_RUN = ("SXT-012 3x bit-identical determinism gate NOT_RUN "
                "(requires the oracle host)")
PARAM_TOL = 1e-6


def oracle_resolve(doc, surgepy, oc):
    """Resolve what only the native loader can tell us (issue #126).

    * `ts_predelay` / `ts_ratio_inv` from `getTempoSync` on the slot's
      predelay parameter after `loadPatch` -- the authoritative
      post-migration state, not an .fxp byte reading.
    * the master volume, needed as the de-amp constant at the model
      boundary.
    * a cross-check of all ten Reverb 2 parameter values against the
      committed normalized graph: a mismatch is a REFUSAL, never a
      silent preference for one source.
    """
    rel = doc["preset"]["path"]
    abs_path = os.path.join(oc.engine_dir(), rel)
    actual = oc.git_blob_sha1(abs_path)
    if actual != doc["preset"]["git_blob_sha1"]:
        raise Refuse("census blob mismatch at the oracle: %s != %s"
                     % (actual, doc["preset"]["git_blob_sha1"]))
    s = surgepy.createSurge(48000.0)
    try:
        if not s.loadPatch(abs_path):
            raise Refuse("loadPatch failed: %s" % rel)
        patch = s.getPatch()
        tempo_bpm = 120.0        # pinned harness tempo (oracle/manifest.json)
        for inst in doc["instances"]:
            slot = inst["slot"]
            fxd = patch["fx"][slot]
            if int(s.getParamVal(fxd["type"])) != FX_TYPE_REVERB2:
                raise Refuse("slot %d is not Reverb 2 at the oracle" % slot)
            for j, name in enumerate(REV2_PARAM_NAMES):
                v = float(s.getParamVal(fxd["p"][j]))
                g = float(inst["params"][name])
                if abs(v - g) > PARAM_TOL:
                    raise Refuse(
                        "slot %d %s differs: engine %r vs normalized graph %r"
                        % (slot, name, v, g))
            ts = bool(s.getTempoSync(fxd["p"][0]))
            inst["params"]["ts_predelay"] = ts
            # Reverb2.h:217 predelay uses temposyncratio_inv when synced;
            # the harness never changes the transport tempo, so the ratio
            # is 120/tempo at the pinned 120 BPM.
            inst["params"]["ts_ratio_inv"] = (120.0 / tempo_bpm) if ts else 1.0
            inst["temposync_source"] = (
                "SurgeSynthesizer::getTempoSync on fx[%d].p[0] after "
                "loadPatch (native loader read-back, post-migration)" % slot)
            inst["return_level_engine"] = float(
                s.getParamVal(fxd["return_level"]))
        doc["volume_f"] = float(s.getParamVal(patch["volume"]))
        doc["tempo_bpm"] = tempo_bpm
        doc["scene_drift_f"] = [float(s.getParamVal(patch["scene"][k]["drift"]))
                                for k in range(2)]
    finally:
        del s
    reasons = [r for r in doc["applicability"]["reasons"] if r != TS_UNRESOLVED]
    doc["applicability"]["reasons"] = reasons
    doc["applicability"]["temposync_resolved"] = True
    return doc


def apply_gate(doc, slug, gate):
    """Fold the committed 3x-render-gate record into the input record.

    `drift_asserted` becomes 0 only when EVERY sequence of this carrier
    passed the gate. A carrier with any REFUSED sequence keeps `null`
    (NOT a pass) and carries the measured divergence.
    """
    rows = [r for r in gate.get("results", []) if r.get("slug") == slug]
    doc["determinism_gate"] = {
        "artifact": "reports/SXT-028f/artifacts/determinism-gate.json",
        "repeats": gate.get("repeats"),
        "sequences": {r["sequence"]: r["status"] for r in rows},
        "measured": {r["sequence"]: r["measured"]
                     for r in rows if "measured" in r},
    }
    reasons = [r for r in doc["applicability"]["reasons"] if r != GATE_NOT_RUN]
    if rows and all(r["status"] == "PASS" for r in rows):
        doc["drift_asserted"] = 0
        doc["determinism_gate"]["status"] = "PASS"
    else:
        doc["drift_asserted"] = None
        doc["determinism_gate"]["status"] = "FAIL" if rows else "NOT_RUN"
        reasons.append(
            "SXT-012 3x bit-identical determinism gate %s: %s"
            % (doc["determinism_gate"]["status"],
               ", ".join("%s=%s" % (k, v) for k, v in
                         sorted(doc["determinism_gate"]["sequences"].items()))
               or "no result row"))
    doc["applicability"]["reasons"] = reasons
    return doc


def finalize_applicability(doc):
    """Complete-wet stays false unless NOTHING refuses it; the narrower
    class-scope reference leg gets its own, explicitly separate record."""
    reasons = doc["applicability"]["reasons"]
    doc["applicability"]["complete_wet_render_possible"] = not reasons
    doc["applicability"]["status"] = (
        "OK" if not reasons else "REFUSED (fail-closed)")
    inst = doc["instances"]
    ok = (doc.get("drift_asserted") == 0
          and doc.get("volume_f") is not None
          and len(inst) == 1
          and str(inst[0]["role"]).startswith("global")
          and max(c["slot"] for c in doc["chain"]) == inst[0]["slot"]
          and inst[0]["params"].get("ts_predelay") is not None)
    why = []
    if doc.get("drift_asserted") != 0:
        why.append("3x determinism gate did not pass")
    if doc.get("volume_f") is None:
        why.append("no master-volume read-back")
    if len(inst) != 1:
        why.append("boundary defined for exactly one Reverb 2 instance")
    elif not str(inst[0]["role"]).startswith("global"):
        why.append("Reverb 2 is not in a global slot")
    elif max(c["slot"] for c in doc["chain"]) != inst[0]["slot"]:
        why.append("an active FX slot sits downstream of the Reverb 2")
    if inst and inst[0]["params"].get("ts_predelay") is None:
        why.append("rev2_predelay temposync UNRESOLVED")
    doc["reference_leg"] = {
        "scope": "fx:Reverb 2 CLASS agreement only (model fed the engine's "
                 "own per-slot-bypass bus); this is NOT a complete-wet "
                 "preset claim and NOT a coverage or quality claim",
        "input_boundary": "per-slot bypass (global-last) -- see "
                          "model/effects/run_reverb2_model.py",
        "usable": bool(ok),
        "refusals": why,
    }
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true",
                    help="also write the corpus-wide Reverb 2 carrier ledger")
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--artdir", default=ARTDIR)
    ap.add_argument("--oracle", action="store_true",
                    help="resolve the temposync flag and the master volume "
                         "from the pinned engine's native loader read-back, "
                         "and fold in the committed 3x render-gate record")
    ap.add_argument("--gate", default=os.path.join(
        ARTDIR, "determinism-gate.json"),
        help="render-gate record written by tools/render_reverb2_fixtures.py")
    args = ap.parse_args()

    census, man = load_census()
    os.makedirs(args.outdir, exist_ok=True)
    os.makedirs(args.artdir, exist_ok=True)

    surgepy = oc = gate = None
    if args.oracle:
        sys.path.insert(0, os.path.join(REPO, "oracle"))
        import oracle_common as oc  # noqa: PLC0415
        surgepy = oc.import_surgepy()
        oc.apply_engine_env()
        if os.path.exists(args.gate):
            with open(args.gate) as f:
                gate = json.load(f)
        else:
            print("NOTE: no render-gate record at %s; drift_asserted stays "
                  "null (NOT_RUN)" % args.gate, file=sys.stderr)

    by_path = {v: k for k, v in CARRIERS.items()}
    written, refused = [], []
    for graph in iter_graphs(set(CARRIERS.values())):
        slug = by_path[graph["p"]]
        try:
            doc = extract_one(graph, census)
            if args.oracle:
                doc = oracle_resolve(doc, surgepy, oc)
                if gate is not None:
                    doc = apply_gate(doc, slug, gate)
                doc = finalize_applicability(doc)
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
              doc["applicability"]["complete_wet_render_possible"],
              "| drift_asserted:", doc.get("drift_asserted"),
              "| ts_predelay:",
              [i["params"].get("ts_predelay") for i in doc["instances"]],
              "| reference-leg usable:",
              (doc.get("reference_leg") or {}).get("usable"))

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
