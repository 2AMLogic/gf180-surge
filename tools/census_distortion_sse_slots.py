#!/usr/bin/env python3
"""SXT-028e-sse follow-up #314 (F-028e-sse-8): per-slot corpus census.

Enumerates EVERY active Distortion slot whose normalized FX model is 3..7
(the SSE quad-waveshaper branch) over `corpus/normalized/graphs.jsonl`, one
row per (preset path, slot index) -- never one row per preset -- and applies
the SXT-012/023 static render screens that can be evaluated from the
committed normalized graphs alone. It is ORACLE-FREE and therefore reports
exactly what it can and cannot decide:

  * a row refused by any graph-derivable screen is REFUSED-STATIC with the
    measured reasons (these are the SAME screens
    `tools/extract_distortion_sse_inputs.py::_render_screens` and
    `attempt_corpus_carrier()` apply, reading the same normalized values);
  * a row that passes every graph-derivable screen is NOT admitted: it is
    `STATIC-PENDING-ORACLE`, because the scene `drift` parameter is not part
    of the normalized graph schema and the empirical 3x fresh-instance
    determinism gate (dry and wet bus) needs the pinned oracle. Both are
    recorded NOT_RUN, never a pass.

Nothing here relaxes a screen, freezes a modulation route, mutes an
oscillator, or substitutes a generic for an unlanded class. The census is
corpus-reach INVENTORY, not a preset-support claim, and never changes a
coverage number. FX model 7 has zero corpus instances; that is recorded
separately (`model_zero_instances`), not as a synthetic row.

Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
LEAF_TABLE = os.path.join(REPO, "reports", "coverage-v1",
                          "leaf-verification.json")
OUT_JSON = os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts",
                        "slot-census.json")
OUT_TXT = os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts",
                       "slot-census.txt")

SSE_MODELS = (3, 4, 5, 6, 7)
MODEL_NAMES = {3: "wst_sine", 4: "wst_digital", 5: "wst_ojd",
               6: "wst_fwrectify", 7: "wst_fuzzsoft"}
DIST_TN = "Distortion"
# Where the distortion model index lives in a normalized fx slot's `p`.
MODEL_P_INDEX = 11
# The distinct dispositions. Only the first is a terminal REFUSAL; the
# second is an honest "not decided here", never an admission.
REFUSED = "REFUSED-STATIC"
PENDING = "STATIC-PENDING-ORACLE"
# Terminal REFUSAL measured on the pinned oracle by #136 and committed in
# render-refusals.txt (a determinism-gate failure on the all-off dry bus).
REFUSED_EMPIRICAL = "REFUSED-EMPIRICAL-COMMITTED"
RENDER_REFUSALS = os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts",
                               "render-refusals.txt")


def committed_empirical_refusals(path=RENDER_REFUSALS):
    """{preset path: sorted unique measured determinism-gate reasons} read
    from the committed #136 oracle-host transcript. Only a `determinism gate
    failed` row counts; the quoted per-run hashes are dropped because they
    differ from run to run by definition."""
    out = {}
    if not os.path.exists(path):
        return out
    import re
    for line in open(path, encoding="utf-8"):
        m = re.match(r"NOT_RUN \S+ \((.+?\.fxp)\): (dry|wet) bus: "
                     r"determinism gate failed", line)
        if m:
            out.setdefault(m.group(1), set()).add(
                f"{m.group(2)} bus: determinism gate failed over 3 repeats")
    return {k: sorted(v) for k, v in out.items()}


def landed_fx_classes():
    """Landed FX classes from the committed ledger (same basis as
    tools/extract_distortion_inputs.py::landed_classes, fail-closed)."""
    import importlib.util
    path = os.path.join(REPO, "tools", "extract_distortion_inputs.py")
    spec = importlib.util.spec_from_file_location("sxt028e_extract", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.landed_classes()


def fx_destinations(g):
    """Modulation routes whose destination is an FX parameter (g/s/v buses)."""
    hits = []

    def scan(rows):
        for r in rows:
            name = r[4] if len(r) > 4 else ""
            if isinstance(name, str) and name.startswith("FX"):
                hits.append(name)

    md = g.get("md") or {}
    scan(md.get("g", []))
    for sc in md.get("s", []):
        scan(sc.get("s", []))
        scan(sc.get("v", []))
    return sorted(set(hits))


def preset_screens(g, landed):
    """Graph-derivable static screens for one preset's normalized graph.

    Returns (reasons, detail). Mirrors `_render_screens` plus the
    unlanded-class rule of `attempt_corpus_carrier()`. The drift screen is
    NOT evaluable here (not in the normalized schema) and is reported as
    such rather than assumed satisfied.
    """
    reasons = []
    if int(g.get("fxb", 0)) != 0:
        reasons.append(f"fx_bypass = {int(g['fxb'])} (not fxb_all_fx)")
    if int(g.get("fxd", 0)) != 0:
        reasons.append(f"fx_disable = {int(g['fxd'])} (non-zero)")
    fx_mod = fx_destinations(g)
    if fx_mod:
        reasons.append("modulation routed into FX parameters: "
                       + ", ".join(fx_mod[:6]))
    sm, sa = int(g["sm"]), int(g["sa"])
    voicing = [sa] if sm == 0 else [0, 1]
    for sc_i in voicing:
        sc = g["sc"][sc_i]
        for oi in range(3):
            level, mute = sc["mix"][f"o{oi+1}"][0], sc["mix"][f"o{oi+1}"][1]
            rt = int(sc["osc"][oi]["rt"])
            if level > 0 and int(mute) == 0 and rt != 1:
                reasons.append(f"scene {sc_i} osc{oi+1} non-muted with "
                               "retrigger off")
    active = [f for f in g["fx"] if f.get("on")]
    unlanded = sorted({f["tn"] for f in active if f["tn"] not in landed})
    if unlanded:
        reasons.append("unlanded class(es) in the active chain: "
                       + ", ".join(unlanded) + " -- a complete-wet "
                       "comparison would need a model this project has not "
                       "landed, and substituting a generic is refused")
    return reasons, {"unlanded": unlanded, "voicing_scenes": voicing}


def enumerate_slots(rows, landed, empirical=None):
    empirical = empirical or {}
    """One row per active Distortion slot with FX model 3..7."""
    out = []
    for r in rows:
        g = r.get("g")
        if not g:
            continue
        slots = [f for f in g["fx"]
                 if f.get("on") and f.get("tn") == DIST_TN
                 and int(f["p"][MODEL_P_INDEX]) in SSE_MODELS]
        if not slots:
            continue
        reasons, detail = preset_screens(g, landed)
        for f in slots:
            m = int(f["p"][MODEL_P_INDEX])
            row = {
                "preset": r["p"], "census_blob_sha1": r["sha"],
                "slot_index": f["i"], "slot_role": f["r"],
                "fx_model": m, "fx_model_name": MODEL_NAMES[m],
                "static_screen_reasons": list(reasons),
                "unlanded_classes_in_chain": detail["unlanded"],
                "drift_screen": "NOT_EVALUATED (scene drift is not in the "
                                "normalized graph schema; oracle read "
                                "required)",
            }
            if reasons:
                row["disposition"] = REFUSED
                row["determinism_gate_dry"] = "NOT_RUN (refused statically)"
                row["determinism_gate_wet"] = "NOT_RUN (refused statically)"
            elif r["p"] in empirical:
                row["disposition"] = REFUSED_EMPIRICAL
                row["empirical_refusal_reasons"] = empirical[r["p"]]
                row["empirical_basis"] = (
                    "reports/SXT-028e-sse/artifacts/render-refusals.txt "
                    "(#136, pinned oracle, harness control PASS)")
                gate = empirical[r["p"]]
                dry = any(x.startswith("dry") for x in gate)
                row["determinism_gate_dry"] = (
                    "FAIL (measured, #136)" if dry else "NOT_RUN")
                row["determinism_gate_wet"] = (
                    "FAIL (measured, #136)"
                    if any(x.startswith("wet") for x in gate)
                    else "NOT_RUN (short-circuited by the dry-bus refusal)")
            else:
                row["disposition"] = PENDING
                row["determinism_gate_dry"] = "NOT_RUN (BLOCKED: no pinned oracle on this host)"
                row["determinism_gate_wet"] = "NOT_RUN (BLOCKED: no pinned oracle on this host)"
            out.append(row)
    out.sort(key=lambda x: (x["fx_model"], x["preset"], x["slot_index"]))
    return out


def build_census(graphs_path=GRAPHS):
    with open(graphs_path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    landed = landed_fx_classes()
    slots = enumerate_slots(rows, landed, committed_empirical_refusals())
    hist = {m: sum(1 for s in slots if s["fx_model"] == m)
            for m in SSE_MODELS}
    disp = {}
    for s in slots:
        disp[s["disposition"]] = disp.get(s["disposition"], 0) + 1
    return {
        "leaf": "SXT-028e-sse", "issue": 314, "finding": "F-028e-sse-8",
        "source": "corpus/normalized/graphs.jsonl",
        "kind": "corpus-reach INVENTORY; not a support claim; coverage "
                "numbers do not move",
        "in_scope_slot_instances": len(slots),
        "model_histogram": {str(m): n for m, n in hist.items()},
        "model_zero_instances": [m for m in SSE_MODELS if hist[m] == 0],
        "disposition_counts": disp,
        "admitted_carriers": 0,
        "slots": slots,
    }


def render_text(c):
    lines = [
        "SXT-028e-sse per-slot corpus census (issue #314, F-028e-sse-8)",
        "inventory only; static screens evaluated from corpus/normalized/"
        "graphs.jsonl; NOT a support claim",
        f"in-scope slot instances: {c['in_scope_slot_instances']}  "
        f"histogram: {c['model_histogram']}",
        f"zero-instance models (recorded, no synthetic row): "
        f"{c['model_zero_instances']}",
        f"dispositions: {c['disposition_counts']}  "
        f"admitted carriers: {c['admitted_carriers']}", ""]
    for s in c["slots"]:
        lines.append(f"{s['disposition']} model{s['fx_model']} "
                     f"slot{s['slot_index']}/{s['slot_role']} "
                     f"[{s['preset']}] "
                     + ("; ".join(s["static_screen_reasons"])
                        or "; ".join(s.get("empirical_refusal_reasons", []))
                        or "passes every graph-derivable screen; drift + "
                           "3x dry/wet gates NOT_RUN"))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify committed artifacts match a fresh derivation")
    args = ap.parse_args()
    c = build_census()
    js = json.dumps(c, indent=2, sort_keys=True) + "\n"
    tx = render_text(c)
    if args.check:
        ok = (open(OUT_JSON).read() == js and open(OUT_TXT).read() == tx)
        print("PASS" if ok else "STALE")
        return 0 if ok else 1
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    open(OUT_JSON, "w").write(js)
    open(OUT_TXT, "w").write(tx)
    print(tx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
