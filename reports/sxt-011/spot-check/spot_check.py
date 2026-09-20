#!/usr/bin/env python3
"""SXT-011 acceptance spot-check: committed graphs vs LIVE surgepy state.

For a fixed list of presets (both banks, dual-scene, FX-heavy, wavetable
assets, low-revision migrations) this script:

  1. loads the COMMITTED graph line from corpus/normalized/graphs.jsonl,
  2. loads the preset into a FRESH pinned-engine instance via surgepy,
  3. re-extracts the graph with the exporter's own extraction function,
  4. compares the two graphs field-by-field (canonical JSON equality),
  5. additionally prints hand-checked live surgepy getter queries
     (getParamVal/getParamDisplay/getAllModRoutings) next to the committed
     fields, as the direct "matches live native state" evidence.

Writes spot-check-transcript.txt and spot-check-summary.json in this
directory. Exit code 0 iff every preset PASSes.

Usage: python3 reports/sxt-011/spot-check/spot_check.py
"""

import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import oracle_common as oc  # noqa: E402
import export_normalized_graphs as eng  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

PRESETS = [
    # (census path, why it is in the spot-check set)
    ("resources/data/patches_factory/Basses/Sub 4.fxp",
     "factory, simple voice graph; continuity with the SXT-010 note capture"),
    ("resources/data/patches_factory/Percussion/Drum One.fxp",
     "factory, stored revision 4: Great Filter Remap era (fut_14 raw ids)"),
    ("resources/data/patches_factory/Tutorials/Formula Modulator/10 Example - Both Time And Space.fxp",
     "factory, DUAL scene, FX-heavy (Flanger/2x Airwindows/Delay/Combulator), Formula LFO, mod routes"),
    ("resources/data/patches_3rdparty/A.Liv/Basses/Amen Polska.fxp",
     "contributor, embedded wavetable assets, Wavetable+Sine+FM2 oscs, 18 mod routes"),
    ("resources/data/patches_3rdparty/Slowboat/Atmospheres/Harmonic Blast.fxp",
     "contributor, 9 configured FX slots across insert/send/global incl. 2 Airwindows algorithms"),
]


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def live_queries(s, patch, sp, g):
    """Independent hand checks: live getters vs committed fields. Strings
    returned are 'LIVE <x> | COMMITTED <y> | OK/MISMATCH'."""
    out = []

    def check(label, live, committed):
        ok = "OK" if live == committed else "MISMATCH"
        out.append("%-34s LIVE %r | COMMITTED %r | %s" % (label, live, committed, ok))
        return ok == "OK"

    allok = True
    allok &= check("scenemode display", s.getParamDisplay(patch["scenemode"]), g["smn"])
    allok &= check("scenemode id", int(s.getParamVal(patch["scenemode"])), g["sm"])
    allok &= check("fx_bypass display", s.getParamDisplay(patch["fx_bypass"]), g["fxbn"])
    allok &= check("polylimit", int(s.getParamVal(patch["polylimit"])), g["poly"])
    for sc in (0, 1):
        e = g["sc"][sc]
        p = patch["scene"][sc]
        allok &= check("sc%d filterblock display" % sc,
                       s.getParamDisplay(p["filterblock_configuration"]), e["fbcn"])
        for oi in range(eng.N_OSCS):
            o = p["osc"][oi]
            oe = e["osc"][oi]
            allok &= check("sc%d.osc%d type" % (sc, oi),
                           int(s.getParamVal(o["type"])), oe["t"])
            allok &= check("sc%d.osc%d type display" % (sc, oi),
                           s.getParamDisplay(o["type"]), oe["tn"])
            if oe["t"] == sp.constants.ot_sine or oe["t"] == sp.constants.ot_classic:
                allok &= check("sc%d.osc%d submode p[0]" % (sc, oi),
                               int(s.getParamVal(o["p"][0])), oe["p"][0])
                out.append("%-34s LIVE %r | (informational: committed schema "
                           "stores the submode id only)"
                           % ("sc%d.osc%d submode display" % (sc, oi),
                              s.getParamDisplay(o["p"][0])))
            uv = next((pp for pp in o["p"] if pp.getName().endswith("Unison Voices")), None)
            if uv is not None:
                allok &= check("sc%d.osc%d unison voices" % (sc, oi),
                               int(s.getParamVal(uv)), oe.get("uni"))
        for fi in range(eng.N_FILTERUNITS):
            fu = p["filterunit"][fi]
            fe = e["fu"][fi]
            allok &= check("sc%d.fu%d type" % (sc, fi),
                           int(s.getParamVal(fu["type"])), fe["t"])
            allok &= check("sc%d.fu%d type display" % (sc, fi),
                           s.getParamDisplay(fu["type"]), fe["tn"])
            allok &= check("sc%d.fu%d subtype" % (sc, fi),
                           int(s.getParamVal(fu["subtype"])), fe["st"])
            allok &= check("sc%d.fu%d subtype display" % (sc, fi),
                           s.getParamDisplay(fu["subtype"]), fe["stn"])
        allok &= check("sc%d wsunit type" % sc,
                       int(s.getParamVal(p["wsunit"]["type"])), e["ws"]["t"])
    for i in range(eng.N_FX_SLOTS):
        fx = patch["fx"][i]
        fe = g["fx"][i]
        allok &= check("fx slot %d type" % i, int(s.getParamVal(fx["type"])), fe["t"])
        allok &= check("fx slot %d role" % i, eng.FX_ROLES[i], fe["r"])
        if fe.get("on"):
            awp = fx["p"][0]
            if fe.get("aw") is not None:
                allok &= check("fx slot %d airwindows id" % i,
                               int(s.getParamVal(awp)), fe["aw"])
                allok &= check("fx slot %d airwindows name" % i,
                               s.getParamDisplay(awp), fe["awn"])
    # mod routes: count + first rows
    md = s.getAllModRoutings()
    live_rows = [[int(r.getSource().getModSource()), int(r.getSourceScene()),
                  int(r.getSourceIndex()),
                  int(r.getDest().getId().getSynthSideId()),
                  r.getDest().getName(),
                  round(r.getDepth(), 6), round(r.getNormalizedDepth(), 6)]
                 for r in md["global"]]
    allok &= check("global route count", len(live_rows), len(g["md"]["g"]))
    for k in range(min(3, len(live_rows))):
        allok &= check("global route[%d]" % k, live_rows[k], g["md"]["g"][k])
    return allok, out


def main():
    oc.reexec_under_pinned_python(REPO)
    oc.apply_engine_env()
    surgepy = oc.import_surgepy()
    if surgepy.getVersion() != eng.ENGINE_VERSION_STR:
        print("REFUSING: engine version %r != pinned %r"
              % (surgepy.getVersion(), eng.ENGINE_VERSION_STR), file=sys.stderr)
        return 2

    committed = {}
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            committed[d["p"]] = d

    data_home = oc.data_home()
    transcript = []
    results = {}

    for path, why in PRESETS:
        transcript.append("=" * 100)
        transcript.append("PRESET: %s" % path)
        transcript.append("WHY:    %s" % why)
        c = committed.get(path)
        if c is None:
            transcript.append("FAIL: no committed line")
            results[path] = {"status": "FAIL", "reason": "missing_line"}
            continue
        if c["st"] != "normalized":
            transcript.append("FAIL: committed status %r" % c["st"])
            results[path] = {"status": "FAIL", "reason": "not_normalized"}
            continue

        ex = eng.Extractor(surgepy, data_home)
        raw = eng.read_fxp_raw(os.path.join(data_home,
                                           os.path.relpath(path, "resources/data")))
        fxp = os.path.join(data_home, os.path.relpath(path, "resources/data"))
        # same declared reset policy as the exporter (non-streamed globals)
        _p = ex.s.getPatch()
        for _pn in ("volume", "fx_bypass", "character", "polylimit"):
            _pr = _p[_pn]
            ex.s.setParamVal(_pr, ex.s.getParamDef(_pr))
        ex.s.allNotesOff()
        ok = ex.s.loadPatch(fxp)
        if not ok:
            transcript.append("FAIL: live load returned false")
            results[path] = {"status": "FAIL", "reason": "load_false"}
            continue
        g2 = ex.extract(raw)
        ev, missing, uninterp = eng.migration_events(raw, g2, ex)
        if ev:
            g2["mi"] = ev
        if missing:
            g2["rwm"] = sorted(missing)
        if uninterp:
            g2["rwu"] = sorted(uninterp, key=lambda d: (d["f"], d["raw"]))
        v = eng.validate(g2, ex, surgepy)
        if v:
            transcript.append("FAIL: re-extracted graph failed validation: %s" % v)
            results[path] = {"status": "FAIL", "reason": "validation"}
            continue

        same = canonical(c["g"]) == canonical(g2)
        transcript.append("FULL-GRAPH COMPARISON (canonical JSON): %s"
                          % ("IDENTICAL" if same else "DIFFERENT"))
        allok, lines = live_queries(ex.s, ex.s.getPatch(), surgepy, c["g"])
        transcript.extend(lines)
        n_check = sum(1 for l in lines if l.endswith("OK"))
        n_mism = sum(1 for l in lines if l.endswith("MISMATCH"))
        status = "PASS" if (same and allok) else "FAIL"
        transcript.append("VERDICT: %s (full-graph %s; %d live getter checks OK, %d mismatches)"
                          % (status, "IDENTICAL" if same else "DIFFERENT", n_check, n_mism))
        results[path] = {"status": status, "live_checks_ok": n_check,
                         "live_checks_mismatch": n_mism,
                         "full_graph_identical": same}

    transcript.append("=" * 100)
    npass = sum(1 for r in results.values() if r["status"] == "PASS")
    transcript.append("TOTAL: %d/%d PASS" % (npass, len(results)))

    with open(os.path.join(HERE, "spot-check-transcript.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(transcript) + "\n")
    with open(os.path.join(HERE, "spot-check-summary.json"), "w",
              encoding="utf-8") as f:
        json.dump({"engine_commit": eng.ENGINE_COMMIT,
                   "engine_version": surgepy.getVersion(),
                   "sample_rate": eng.SAMPLE_RATE,
                   "presets": results,
                   "pass_count": npass,
                   "total": len(results)}, f, indent=2)
    print("\n".join(transcript[-(len(results) + 2):]))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
