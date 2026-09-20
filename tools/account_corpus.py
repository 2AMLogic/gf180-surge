#!/usr/bin/env python3
"""SXT-015 corpus accounting (issue #10 acceptance: corpus scan, examples,
negative controls).

Runs the deterministic resource-accounting model over ALL lines of
corpus/normalized/graphs.jsonl and emits byte-identical outputs for identical
inputs (sorted keys, fixed iteration order, no timestamps).

Outputs (default):
  reports/sxt-015/corpus-accounting.json      corpus distribution + fits/exceeds
  reports/sxt-015/examples/*.json             three worked examples (issue acceptance)
  reports/sxt-015/negative-control/*.json     negative-control records

NO hardware claim, NO area/cycle measurement claim, and NO fidelity or
preset-quality claim is made by this tool: numbers are model outputs under
named assumptions (cost profile placeholder-v0; SXT-016 replaces it).
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from model.resources.accounting import MODEL_VERSION, account_graph, params_digest
from model.resources.params import REG

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
OUTDIR = os.path.join(REPO, "reports", "sxt-015")


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=True)
        f.write("\n")


def _event_profile():
    """Corpus-derived event profile from the fixture sequence library."""
    seqdir = os.path.join(REPO, "fixtures", "sequences")
    max_coincident, peak_rate = 0, 0.0
    n = 0
    for name in sorted(os.listdir(seqdir)):
        if not name.endswith(".json"):
            continue
        n += 1
        seq = json.load(open(os.path.join(seqdir, name)))
        per_t = Counter(e["t"] for e in seq["events"])
        mx = max(per_t.values())
        max_coincident = max(max_coincident, mx)
        dur_s = max(e["t"] for e in seq["events"]) / REG.sample_rate_hz
        if dur_s > 0:
            peak_rate = max(peak_rate, len(seq["events"]) / dur_s)
    return {
        "max_coincident_events": max_coincident,
        "peak_events_per_second": round(peak_rate, 6),
        "sequence_fixtures": n,
        "source": "fixtures/sequences/ (SXT-012 library)",
    }


def scan_corpus(limit_free_only=False):
    """Account every graph; returns (per-entry minimal records, counts)."""
    ep = _event_profile()
    records = []
    for line in open(GRAPHS):
        d = json.loads(line)
        r = account_graph(d, fx_instance_limit=None, event_profile=ep)
        records.append({
            "path": d.get("p"), "sha": d.get("sha"), "bank": d.get("b"),
            "input_status": r["input_status"], "status": r["status"],
            "enabled_fx_instances":
                (r["fx_summary"] or {}).get("enabled_instances"),
            "processing_fx_instances":
                (r["fx_summary"] or {}).get("processing_instances"),
            "configured_fx_slots":
                (r["fx_summary"] or {}).get("configured_slots"),
            "distinct_fx_types": (r["fx_summary"] or {}).get("distinct_type_count"),
            "worst_case_voices": (r["voice"] or {}).get("worst_case_voices"),
            "unison_osc_instances_worst":
                (r["voice"] or {}).get("unison_osc_instances_worst_case"),
            "scene_mode": (r["voice"] or {}).get("scene_mode_name"),
            "state_bytes_external_writable":
                (r["memory"] or {}).get("external_writable_state_bytes"),
            "state_bytes_on_chip": (r["memory"] or {}).get("on_chip_state_bytes"),
            "ext_traffic_bytes_per_s":
                (r["memory"] or {}).get("ext_traffic_bytes_per_s"),
            "closure": (r["budget"] or {}).get("closure"),
            "cost_total_cycles": ((r["budget"] or {}).get(
                "cost_cycles_per_frame") or {}).get("total"),
            "rejection_codes": sorted(x["code"] for x in r["rejections"]),
            "anomaly_codes": sorted({x["code"] for x in r["anomalies"]}),
        })
    return records, ep


def cross_check_census(records):
    """Cross-check configured-slot counts against the static census."""
    census_csv = os.path.join(REPO, "corpus", "census-v0.1", "results",
                              "per-preset.csv")
    if not os.path.exists(census_csv):
        return {"status": "NOT_RUN", "note": "census per-preset.csv missing"}
    import csv

    census_fx = {}
    with open(census_csv) as f:
        for row in csv.DictReader(f):
            p = row.get("path")
            v = row.get("stored_nonoff_fx_slot_count", "")
            if p and v != "":
                census_fx[p] = int(v)
    if not census_fx:
        return {"status": "NOT_RUN",
                "note": "no stored_nonoff_fx_slot_count column in per-preset.csv"}
    mismatch = []
    for r in records:
        if r["input_status"] != "normalized":
            continue
        c = census_fx.get(r["path"])
        if c is not None and c != r["configured_fx_slots"]:
            mismatch.append({"path": r["path"], "census": c,
                             "graphs": r["configured_fx_slots"]})
    return {
        "status": "PASS" if not mismatch else "FAIL",
        "compared": len(census_fx), "mismatches": mismatch[:50],
        "mismatch_count": len(mismatch),
        "note": "configured non-Off slot counts vs census-v0.1 per-preset.csv",
    }


def pick_examples(records, lines_by_path):
    """Deterministic worked-example selection from real corpus entries."""
    def enabled(d):
        return [s for s in d["g"]["fx"] if s.get("on")]

    four = sorted(
        (p for p, d in lines_by_path.items()
         if len(enabled(d)) == 4 and d["g"]["fxd"] == 0),
        key=lambda p: ((lines_by_path[p]["b"], p)))
    if not four:
        four = sorted((p for p, d in lines_by_path.items()
                       if len(enabled(d)) == 4),
                      key=lambda p: ((lines_by_path[p]["b"], p)))
    unison = sorted(
        (p for p, d in lines_by_path.items() if d["g"]["sm"] == 2),
        key=lambda p: (-_unison_load(lines_by_path[p]), p))
    alloff = sorted((p for p, d in lines_by_path.items()
                     if not enabled(d)),
                    key=lambda p: ((lines_by_path[p]["b"], p)))
    return {
        "four_fx_instances": four[0] if four else None,
        "two_scene_unison": unison[0] if unison else None,
        "all_fx_off": alloff[0] if alloff else None,
    }


def _unison_load(d):
    tot = 0
    for si in ([d["g"]["sa"]] if d["g"]["sm"] == 0 else [0, 1]):
        for o in d["g"]["sc"][si]["osc"]:
            tot += max(1, min(o.get("uni", 1), REG.max_unison))
    return tot


def negative_controls(outdir):
    """Live negative controls; each must demonstrably fail the check it
    targets. Synthetic graphs go through a /tmp fixture file."""
    results = []
    ep = _event_profile()

    # pick a simple real base graph: all-fx-off AND within the placeholder
    # budget, so control 1 isolates the instance-limit check
    base = None
    for line in open(GRAPHS):
        d = json.loads(line)
        if d["st"] == "normalized" and not any(s.get("on") for s in d["g"]["fx"]):
            r0 = account_graph(d, fx_instance_limit=None, event_profile=ep)
            if r0["status"] == "fit":
                base = d
                break
    assert base is not None, "no all-fx-off preset fits the placeholder budget"

    # --- control 1: 5 enabled FX instances vs limit 4 => must REJECT --------
    nc = json.loads(json.dumps(base))
    nc["p"] = "synthetic/negative-control-5fx"
    roles = ["ains1", "ains2", "bins1", "send1", "global1"]
    # deliberately cheap classes (plus one Delay to exercise per-instance
    # external state) so the placeholder budget is NOT the binding check:
    # the control isolates the instance-limit rejection
    classes = ["EQ", "Delay", "Graphic EQ", "Conditioner", "Ring Mod"]
    for k, slot in enumerate(nc["g"]["fx"]):
        if k < 5:
            slot["on"] = 1
            slot["t"] = 1
            slot["tn"] = classes[k]
            slot["r"] = roles[k]
            if classes[k] == "Delay":
                slot["p"] = [0.0] * 12
    tmp = "/tmp/sxt-015-nc-fx5.jsonl"
    with open(tmp, "w") as f:
        f.write(json.dumps(nc, sort_keys=True, separators=(",", ":")) + "\n")
    loaded = json.loads(open(tmp).read())
    r4 = account_graph(loaded, fx_instance_limit=4, event_profile=ep)
    r8 = account_graph(loaded, fx_instance_limit=8, event_profile=ep)
    c1 = {
        "control": "instance_limit_overflow_rejected",
        "fixture_file": tmp,
        "targets": "graph exceeding declared instance limits must be REJECTED, "
                   "not silently squeezed (issue #10 acceptance)",
        "limit_4": {"status": r4["status"],
                    "rejections": r4["rejections"],
                    "enabled_instances": r4["fx_summary"]["enabled_instances"]},
        "limit_8": {"status": r8["status"],
                    "enabled_instances": r8["fx_summary"]["enabled_instances"]},
        "outcome": ("PASS" if (r4["status"] == "rejected"
                               and any(x["code"] == "fx_instance_overflow"
                                       for x in r4["rejections"])
                               and r8["status"] == "fit")
                    else "FAIL"),
        "note": "same graph: rejected at limit 4, fits at limit 8 — the "
                "rejection is limit-driven and explicit",
    }
    results.append(c1)
    _dump(os.path.join(outdir, "nc-instance-limit-overflow.json"), c1)

    # --- control 2: analysis_failure input fails closed ---------------------
    af = {"p": "synthetic/negative-control-analysis-failure", "b": "contributor",
          "sha": "0" * 40, "sz": 0, "st": "analysis_failure",
          "why": {"phase": "load", "reason": "load_false",
                  "detail": "synthetic control"}}
    raf = account_graph(af, fx_instance_limit=4)
    c2 = {
        "control": "analysis_failure_fails_closed",
        "targets": "an analysis_failure graph must fail closed (no default "
                   "costs), never be accounted with guessed numbers",
        "outcome": ("PASS" if (raf["status"] == "analysis_failure"
                               and raf["budget"] is None
                               and raf["memory"] is None
                               and raf["fx_instances"] is None)
                    else "FAIL"),
        "status": raf["status"], "costs_null": raf["budget"] is None,
        "anomalies": raf["anomalies"],
    }
    results.append(c2)
    _dump(os.path.join(outdir, "nc-analysis-failure-fails-closed.json"), c2)

    # --- control 3: budget overflow is an explicit rejection ----------------
    with REG.override("clock_hz", 1000000):  # absurd tiny clock on purpose
        rbo = account_graph(base, fx_instance_limit=4, event_profile=ep)
    c3 = {
        "control": "budget_overflow_explicit",
        "targets": "complete-patch cost above budget(F, Fs, reserve) must be "
                   "an explicit OVERFLOW rejection (issue #10 acceptance)",
        "clock_hz_overridden": 1000000,
        "outcome": ("PASS" if (rbo["status"] == "rejected"
                               and any(x["code"] == "budget_overflow"
                                       for x in rbo["rejections"]))
                    else "FAIL"),
        "closure": rbo["budget"]["closure"],
        "rejections": rbo["rejections"],
        "note": "declared experiment: clock overridden to 1 MHz to force the "
                "overflow path; the same graph fits under the default "
                "placeholder clock only where the model says so",
    }
    results.append(c3)
    _dump(os.path.join(outdir, "nc-budget-overflow.json"), c3)

    # --- control 4: unison beyond MAX_UNISON is flagged, not guessed --------
    nu = json.loads(json.dumps(base))
    nu["p"] = "synthetic/negative-control-unison-overflow"
    nu["g"]["sc"][0]["osc"][0]["uni"] = 999
    ru = account_graph(nu, fx_instance_limit=None, event_profile=ep)
    codes = {a["code"] for a in ru["anomalies"]}
    c4 = {
        "control": "unison_above_declared_max_flagged",
        "targets": "unison outside the engine-declared range must be an "
                   "explicit clamped anomaly (engine constant MAX_UNISON), "
                   "never silently trusted and never silently dropped",
        "outcome": ("PASS" if "unison_out_of_range" in codes else "FAIL"),
        "anomalies": [a for a in ru["anomalies"]
                      if a["code"] == "unison_out_of_range"],
    }
    results.append(c4)
    _dump(os.path.join(outdir, "nc-unison-out-of-range.json"), c4)

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--skip-negative-controls", action="store_true")
    args = ap.parse_args()

    examples_dir = os.path.join(args.outdir, "examples")
    nc_dir = os.path.join(args.outdir, "negative-control")

    records, ep = scan_corpus()
    lines_by_path = {}
    for line in open(GRAPHS):
        d = json.loads(line)
        lines_by_path[d["p"]] = d

    # corpus scan output -----------------------------------------------------
    dist_fx = Counter(r["enabled_fx_instances"] for r in records)
    dist_conf = Counter(r["configured_fx_slots"] for r in records)
    dist_voices = Counter(r["worst_case_voices"] for r in records)
    dist_unison = Counter(r["unison_osc_instances_worst"] for r in records)
    status_counter = Counter(r["status"] for r in records)
    closure = Counter(r["closure"] for r in records)
    anomaly_codes = Counter()
    for r in records:
        for c in r["anomaly_codes"]:
            anomaly_codes[c] += 1
    per_bank = {}
    for bank in ("factory", "contributor"):
        rs = [r for r in records if r["bank"] == bank]
        per_bank[bank] = {
            "presets": len(rs),
            "fits_4": sum(1 for r in rs if (r["enabled_fx_instances"] or 0) <= 4),
            "fits_8": sum(1 for r in rs if (r["enabled_fx_instances"] or 0) <= 8),
        }

    exceeds_detail = {}
    for lim in (4, 8):
        bad = [r for r in records
               if r["input_status"] == "normalized"
               and (r["enabled_fx_instances"] or 0) > lim]
        exceeds_detail[str(lim)] = [
            {"path": r["path"], "sha": r["sha"],
             "enabled_instances": r["enabled_fx_instances"],
             "reason": "fx_instance_overflow"}
            for r in sorted(bad, key=lambda x: x["path"])]

    summary = {
        "issue": "SXT-015",
        "model_version": MODEL_VERSION,
        "params_digest": params_digest(),
        "cost_profile": REG.cost_profile,
        "graphs_file": "corpus/normalized/graphs.jsonl",
        "graphs_count": len(records),
        "input_status_counts": dict(Counter(r["input_status"] for r in records)),
        "disclaimer": "Model outputs under named assumptions (cost profile "
                      "placeholder-v0, named limits, placeholder external "
                      "memory bandwidth). NOT area/cycle measurements "
                      "(SXT-016), NOT profile freeze (SXT-017), NOT a "
                      "fidelity or preset-quality claim, NO hardware claim.",
        "fx_instance_distribution": {
            "enabled_instances": {str(k): dist_fx.get(k, 0)
                                  for k in sorted(dist_fx)},
            "configured_slots": {str(k): dist_conf.get(k, 0)
                                 for k in sorted(dist_conf)},
        },
        "fits_candidate_limits": {
            "4": sum(1 for r in records
                     if (r["enabled_fx_instances"] or 0) <= 4
                     and r["input_status"] == "normalized"),
            "8": sum(1 for r in records
                     if (r["enabled_fx_instances"] or 0) <= 8
                     and r["input_status"] == "normalized"),
            "normalized_total": sum(1 for r in records
                                    if r["input_status"] == "normalized"),
            "per_bank": per_bank,
            "note": "candidate limits per plan section 3; NOT frozen product "
                    "limits (SXT-017). Slot-count observation cross-checked "
                    "against census-v0.1; counts are NOT support claims",
        },
        "exceeds_candidate_limits": exceeds_detail,
        "voice_distribution": {
            "worst_case_voices": {str(k): dist_voices.get(k, 0)
                                  for k in sorted(dist_voices)},
            "unison_osc_instances_worst_case_top":
                {str(k): dist_unison.get(k, 0)
                 for k in sorted(dist_unison, reverse=True)[:20]},
            "note": "worst-case voices = min(polylimit, voice_pool_limit); "
                    "dual mode consumes two pool voices per note",
        },
        "status_counts": dict(status_counter),
        "budget_closure_placeholder_v0": {
            "within_budget": closure.get("within_budget", 0),
            "overflow": closure.get("OVERFLOW", 0),
            "note": "cost profile placeholder-v0 ONLY; the split "
                    "demonstrates the closure machinery and supports no "
                    "technology claim (SXT-016 replaces the profile)",
        },
        "external_memory_bytes": {
            "max_state_bytes_external_writable":
                max(r["state_bytes_external_writable"] or 0 for r in records),
            "presets_with_external_writable_state":
                sum(1 for r in records
                    if (r["state_bytes_external_writable"] or 0) > 0),
            "max_ext_traffic_bytes_per_s":
                max(r["ext_traffic_bytes_per_s"] or 0 for r in records),
        },
        "anomaly_code_counts": dict(anomaly_codes),
        "event_profile": ep,
        "event_queue_depth": REG.event_queue_depth,
        "event_queue_overflows": sum(
            1 for r in records if "event_queue_overflow" in r["rejection_codes"]),
    }
    summary["census_cross_check"] = cross_check_census(records)
    _dump(os.path.join(args.outdir, "corpus-accounting.json"), summary)

    # worked examples ----------------------------------------------------------
    picks = pick_examples(records, lines_by_path)
    for key, fname in (("four_fx_instances", "example-a-four-fx-instances.json"),
                       ("two_scene_unison", "example-b-two-scene-unison.json"),
                       ("all_fx_off", "example-c-all-fx-off-baseline.json")):
        p = picks[key]
        d = lines_by_path[p]
        r = account_graph(d, fx_instance_limit=4, event_profile=ep)
        out = {
            "example": key, "issue": "SXT-015",
            "selection_rule": {
                "four_fx_instances": "first preset by (bank, path) with "
                                     "exactly 4 configured non-Off slots, all "
                                     "fxd-enabled; falls back to any exactly-4",
                "two_scene_unison": "Dual scene-mode preset maximizing the "
                                    "unison load of active-scene osc slots; "
                                    "ties broken by path",
                "all_fx_off": "first preset by (bank, path) with zero "
                              "configured non-Off slots",
            }[key],
            "source": {"path": d["p"], "sha": d["sha"], "bank": d["b"],
                       "size_bytes": d.get("sz")},
            "account": r,
        }
        _dump(os.path.join(examples_dir, fname), out)

    # negative controls --------------------------------------------------------
    if not args.skip_negative_controls:
        ncs = negative_controls(nc_dir)
        ok = all(c["outcome"] == "PASS" for c in ncs)
        _dump(os.path.join(nc_dir, "summary.json"), {
            "issue": "SXT-015", "controls": ncs, "all_pass": ok})

    print(json.dumps({
        "graphs": len(records),
        "fits_4": summary["fits_candidate_limits"]["4"],
        "fits_8": summary["fits_candidate_limits"]["8"],
        "census_cross_check": summary["census_cross_check"]["status"],
        "status_counts": summary["status_counts"],
    }, indent=1))


if __name__ == "__main__":
    main()
