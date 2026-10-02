#!/usr/bin/env python3
"""SXT-028f: screen the corpus for Reverb 2 carriers the reference leg can use.

Two stages, in this order, because the static screen demonstrably cannot
replace the render gate (the SXT-028c finding, repeated here: all three
issue-named SXT-028f carriers pass every static screen and are still
REFUSED by the empirical 3x gate).

  STATIC (committed evidence only, no oracle needed)
    * active Reverb 2 slot, `fx_bypass == All FX`, `fx_disable == 0`
    * no modulation route whose destination names an FX parameter
    * the Reverb 2 slot is the LAST active FX slot and sits in a global
      role -- the declared model input boundary of this leaf
      (model/effects/run_reverb2_model.py)

  EMPIRICAL (needs the pinned oracle; `--render-gate`)
    * the unmodified wet bus renders 3x bit-identically

Output: reports/SXT-028f/artifacts/carrier-screen.json. This is an
inventory and prioritisation aid only (AGENTS.md) -- it is NOT a support
claim and NOT a coverage claim.

Original to this repository (Apache-2.0).
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "tools"))

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
FX_TYPE_REVERB2 = 11


def fx_destination_routes(md):
    hits = []

    def scan(rows):
        for r in rows or []:
            name = r[4] if len(r) > 4 else ""
            if isinstance(name, str) and name.startswith("FX"):
                hits.append(name)

    md = md or {}
    scan(md.get("g"))
    for sc in md.get("s") or []:
        scan(sc.get("s"))
        scan(sc.get("v"))
    return hits


def static_screen(graphs_path=GRAPHS):
    rows = []
    with open(graphs_path) as f:
        for line in f:
            g = json.loads(line)
            if g.get("st") != "normalized":
                continue
            gg = g["g"]
            slots = [x for x in gg["fx"] if x.get("on")]
            r2 = [x for x in slots if x["t"] == FX_TYPE_REVERB2]
            if not r2:
                continue
            if gg.get("fxb", 0) != 0 or gg.get("fxd", 0) != 0:
                continue
            if fx_destination_routes(gg.get("md")):
                continue
            last = max(x["i"] for x in slots)
            last_entry = [x for x in slots if x["i"] == last][0]
            if last_entry["t"] != FX_TYPE_REVERB2:
                continue
            if not str(last_entry["r"]).startswith("global"):
                continue
            rows.append({
                "path": g["p"],
                "sha": g["sha"],
                "scene_mode": gg.get("smn"),
                "reverb2_slots": [x["i"] for x in r2],
                "reverb2_roles": [x["r"] for x in r2],
                "reverb2_last_slot": last,
                "active_classes": sorted({x["tn"] for x in slots}),
                "n_active_slots": len(slots),
            })
    return sorted(rows, key=lambda r: r["path"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render-gate", action="store_true",
                    help="also run the empirical 3x determinism gate "
                         "(requires the pinned oracle)")
    ap.add_argument("--seq", default="seq-poly-8-v1")
    ap.add_argument("--out", default=os.path.join(
        REPO, "reports", "SXT-028f", "artifacts", "carrier-screen.json"))
    args = ap.parse_args()

    rows = static_screen()
    out = {
        "schema_version": 1,
        "leaf": "SXT-028f",
        "follow_up": "F-028f-1 (#126)",
        "claim_scope": "inventory and prioritisation only (AGENTS.md): NOT a "
                       "support claim, NOT a coverage claim",
        "static_screen": {
            "source": "corpus/normalized/graphs.jsonl (SXT-011)",
            "criteria": [
                "active Reverb 2 slot",
                "fx_bypass == All FX and fx_disable == 0",
                "no modulation route into an FX parameter",
                "the Reverb 2 slot is the LAST active FX slot, in a global "
                "role (the declared model input boundary)",
            ],
            "passing": len(rows),
        },
        "render_gate": {"run": bool(args.render_gate), "sequence": args.seq},
        "carriers": rows,
    }

    if args.render_gate:
        import oracle_common as oc

        surgepy = oc.import_surgepy()
        oc.apply_engine_env()
        import render_fx_fixtures as rfx
        import render_reverb2_fixtures as rr

        seq, _p, _s = rfx.rf.load_sequence(args.seq)
        npass = 0
        for r in rows:
            ap_path = os.path.join(oc.engine_dir(), r["path"])
            if not os.path.exists(ap_path):
                r["gate_3x"] = "REFUSED (preset not present in the pinned tree)"
                continue
            try:
                _w, _h, info = rr.render_bus_slots(surgepy, ap_path, seq, None)
                r["gate_3x"] = "PASS"
                r["wet_peak_abs"] = info["peak_abs"]
                npass += 1
            except rr.DeterminismRefusal as e:
                r["gate_3x"] = "REFUSED (determinism)"
                r["measured"] = e.stats
            except rfx.Refuse as e:
                r["gate_3x"] = "REFUSED"
                r["refusal"] = str(e)
        out["render_gate"]["passing"] = npass
        out["render_gate"]["attempted"] = len(rows)
        print("render gate: %d / %d carriers bit-identical over 3 repeats"
              % (npass, len(rows)))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print("static screen: %d carriers -> %s"
          % (len(rows), os.path.relpath(args.out, REPO)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
