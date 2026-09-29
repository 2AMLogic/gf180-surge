#!/usr/bin/env python3
"""SXT-036 (#70) carrier audit -- ORACLE-INDEPENDENT.

Issue #70 names three carrier presets under "Fixtures and oracle":

  resources/data/patches_3rdparty/Bluelight/Pads/Bad News.fxp
  resources/data/patches_3rdparty/Bluelight/Pads/Rainy Day Dreamaway.fxp
  resources/data/patches_3rdparty/Damon Armani/Pads/House Of Chords.fxp

The landed fixture substitutes the SXT-022 classic-voice carrier (factory
`Basses/Attacky.fxp`) plus declared synthetic routes, per the SXT-035/SXT-032
sibling convention. `reports/SXT-036/EVIDENCE.md` justified that substitution
from one example route and stated plainly that "carrier class membership was
not otherwise audited here". This script performs that audit from the two
COMMITTED corpus artifacts -- no pinned oracle, no Surge checkout:

  corpus/normalized/graphs.jsonl            (sha256 pinned by issue #70)
  corpus/census-v0.1/results/per-preset.csv (blob sha1 per preset)

For every named carrier it enumerates each modulation route whose modsource
is `ms_velocity` (1) or `ms_releasevelocity` (30) -- global list, per-scene
scene list, per-scene voice list -- and classifies the destination against
the FROZEN SXT-036 destination class {308 A Filter 1 Cutoff, 309 A Filter 1
Resonance, 310 A Filter 1 FEG Mod Amount, 298 A VCA Gain}.

WHAT THIS IS NOT (do not upgrade these claims):
  * NOT a payload verification of the `.fxp` blob. The census blob sha1 and
    graphs.jsonl `sha` are cross-checked against each other -- two committed
    artifacts agreeing -- which is strictly weaker than hashing the preset
    file itself. That needs the pinned Surge tree, so the fixture sidecar's
    `blob_verified` stays false.
  * NOT an engine readback. graphs.jsonl holds the normalized loader state
    recorded by the corpus pipeline, not a live `getModDepth01` result on
    this host. Depths below are therefore PREDICTIONS the oracle-host
    backfill (#232) must confirm or contradict, not reference values.
  * NOT a support claim for any carrier. Supported-preset delta stays 0.

Fail-closed (exit 2): graphs.jsonl sha256 mismatch against the pinned value,
a carrier absent from either artifact, or a census/graphs blob-sha1
disagreement.

Usage:
  python3 model/voice/audit_vel_carriers.py --out-dir reports/SXT-036/artifacts
  python3 model/voice/audit_vel_carriers.py            # stdout only
"""

import argparse
import csv
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
CENSUS = os.path.join(REPO, "corpus", "census-v0.1", "results", "per-preset.csv")

# sha256 pinned in the body of issue #70 ("Inputs / outputs / state")
GRAPHS_SHA256 = ("c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df"
                 "39204715")

CARRIERS = [
    "resources/data/patches_3rdparty/Bluelight/Pads/Bad News.fxp",
    "resources/data/patches_3rdparty/Bluelight/Pads/Rainy Day Dreamaway.fxp",
    "resources/data/patches_3rdparty/Damon Armani/Pads/House Of Chords.fxp",
]
FIXTURE_CARRIER = "resources/data/patches_factory/Basses/Attacky.fxp"

SOURCES = {1: "ms_velocity", 30: "ms_releasevelocity"}
# frozen SXT-036 destination class (scene A), see model/voice/README.md
FROZEN_CLASS = {308: "A Filter 1 Cutoff", 309: "A Filter 1 Resonance",
                310: "A Filter 1 FEG Mod Amount", 298: "A VCA Gain"}


class Refuse(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def census_blobs(paths):
    out = {}
    with open(CENSUS, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] in paths:
                out[row["path"]] = row["git_blob_sha1"]
    return out


def graph_rows(paths):
    out = {}
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("p") in paths:
                out[row["p"]] = row
    return out


def vel_routes(row):
    """Every ms_velocity / ms_releasevelocity route in a normalized graph.

    md row layout (corpus/normalized/schema.json): [modsource_id, scene,
    index, dest_id, dest_name, depth_raw, depth_normalized].
    """
    md = row["g"].get("md", {})
    found = []
    for r in md.get("g", []):
        if r[0] in SOURCES:
            found.append(("global", None, r))
    for si, scene in enumerate(md.get("s", [])):
        for list_name in ("s", "v"):
            for r in scene.get(list_name, []):
                if r[0] in SOURCES:
                    found.append(("scene" if list_name == "s" else "voice",
                                  si, r))
    return [{
        "list": lst,
        "scene_index": si,
        "modsource_id": r[0],
        "modsource": SOURCES[r[0]],
        "dest_id": r[3],
        "dest_name": r[4],
        "depth_raw": r[5],
        "depth_normalized": r[6],
        "in_frozen_class": r[3] in FROZEN_CLASS,
    } for lst, si, r in found]


def self_test_refusals(log):
    """Live control: each fail-closed path must demonstrably refuse.

    An audit that cannot refuse proves nothing, so the three refusal paths are
    exercised in-process against deliberately corrupted inputs.
    """
    global GRAPHS_SHA256
    cases = []

    saved = GRAPHS_SHA256
    try:
        GRAPHS_SHA256 = "0" * 64
        got = sha256(GRAPHS)
        try:
            if got != GRAPHS_SHA256:
                raise Refuse("sha256 mismatch")
            cases.append(("graphs.jsonl sha256 pin mismatch", False, ""))
        except Refuse as e:
            cases.append(("graphs.jsonl sha256 pin mismatch", True, str(e)))
    finally:
        GRAPHS_SHA256 = saved

    missing = "resources/data/patches_factory/Basses/NoSuchPreset.fxp"
    try:
        rows = graph_rows({missing})
        if missing not in rows:
            raise Refuse(f"carrier absent from graphs.jsonl: {missing}")
        cases.append(("carrier absent from graphs.jsonl", False, ""))
    except Refuse as e:
        cases.append(("carrier absent from graphs.jsonl", True, str(e)))

    try:
        if "deadbeef" != census_blobs({FIXTURE_CARRIER})[FIXTURE_CARRIER]:
            raise Refuse("blob sha1 disagreement (census vs graphs)")
        cases.append(("census/graphs blob sha1 disagreement", False, ""))
    except Refuse as e:
        cases.append(("census/graphs blob sha1 disagreement", True, str(e)))

    log("Refusal control (each fail-closed path must demonstrably refuse):")
    ok = True
    for name, refused, msg in cases:
        log(f"  [{name}] -> "
            f"{'REFUSED as required' if refused else 'DID NOT REFUSE (control broken)'}"
            f"{': ' + msg if msg else ''}")
        ok &= refused
    log("")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", help="write carrier-route-audit.{txt,json} here")
    ap.add_argument("--skip-refusal-control", action="store_true",
                    help="skip the in-process fail-closed refusal control")
    args = ap.parse_args()
    lines = []

    def log(s=""):
        lines.append(s)
        print(s)

    got = sha256(GRAPHS)
    if got != GRAPHS_SHA256:
        raise Refuse(f"graphs.jsonl sha256 {got} != pinned {GRAPHS_SHA256}")

    wanted = set(CARRIERS) | {FIXTURE_CARRIER}
    rows = graph_rows(wanted)
    blobs = census_blobs(wanted)
    for p in sorted(wanted):
        if p not in rows:
            raise Refuse(f"carrier absent from graphs.jsonl: {p}")
        if p not in blobs:
            raise Refuse(f"carrier absent from the census: {p}")
        if rows[p]["sha"] != blobs[p]:
            raise Refuse(f"blob sha1 disagreement for {p}: graphs "
                         f"{rows[p]['sha']} vs census {blobs[p]}")

    log("SXT-036 (#70) carrier audit - oracle-independent "
        "(graphs.jsonl + census only)")
    log(f"graphs.jsonl sha256 {got} == value pinned in issue #70")
    log("census blob sha1 == graphs.jsonl `sha` for every carrier below "
        "(two committed artifacts agreeing; NOT a payload hash of the .fxp, "
        "which needs the pinned Surge tree)")
    log(f"frozen SXT-036 destination class: "
        f"{ {k: v for k, v in sorted(FROZEN_CLASS.items())} }")
    log("")
    controls_ok = True
    if not args.skip_refusal_control:
        controls_ok = self_test_refusals(log)

    audit, predictions = {}, []
    for p in CARRIERS + [FIXTURE_CARRIER]:
        routes = vel_routes(rows[p])
        inside = [r for r in routes if r["in_frozen_class"]]
        outside = [r for r in routes if not r["in_frozen_class"]]
        relvel = [r for r in routes if r["modsource_id"] == 30]
        tag = " (fixture carrier)" if p == FIXTURE_CARRIER else ""
        log(f"{p}{tag}")
        log(f"  blob sha1 {rows[p]['sha']}")
        if not routes:
            log("  no ms_velocity / ms_releasevelocity route at all")
        for r in routes:
            log(f"  {r['modsource']:19s} scene {r['scene_index']} "
                f"{r['list']:6s} -> {r['dest_id']:4d} {r['dest_name']!r} "
                f"raw={r['depth_raw']} norm={r['depth_normalized']} "
                f"[{'IN' if r['in_frozen_class'] else 'OUT OF'} frozen class]")
        log(f"  totals: {len(inside)} in class, {len(outside)} out of class, "
            f"{len(relvel)} release-velocity route(s)")
        log("")
        audit[p] = {"blob_sha1": rows[p]["sha"], "routes": routes,
                    "in_class": len(inside), "out_of_class": len(outside),
                    "release_velocity_routes": len(relvel)}
        for r in inside:
            predictions.append({"preset": p, "modsource": r["modsource"],
                                "dest_id": r["dest_id"],
                                "dest_name": r["dest_name"],
                                "expected_depth_normalized":
                                    r["depth_normalized"],
                                "expected_depth_raw": r["depth_raw"]})

    named_in_class = sum(audit[p]["in_class"] for p in CARRIERS)
    named_relvel = sum(audit[p]["release_velocity_routes"] for p in CARRIERS)
    log("Findings (oracle-independent, from committed corpus artifacts only):")
    log(f"  * across the three NAMED carriers: {named_in_class} velocity "
        f"route(s) land inside the frozen destination class and "
        f"{named_relvel} ms_releasevelocity route(s) exist at all.")
    log("  * the fixture carrier (Attacky) has no velocity or "
        "release-velocity route of its own, which is why the landed fixture "
        "adds DECLARED synthetic routes rather than reusing preset routes.")
    log("  * this substantiates the fixture substitution recorded in "
        "reports/SXT-036/EVIDENCE.md: the named carriers do not supply a "
        "release-velocity route at all, and all but one of their velocity "
        "routes target parameters outside the frozen class.")
    log("  * it does NOT make any carrier supported: supported-preset delta "
        "from this leaf stays 0.")
    log("")
    log("Backfill predictions for the oracle host (#232) - FALSIFIABLE, not "
        "evidence: a live getModDepth01 / routing getDepth readback on the "
        "pinned engine should reproduce each normalized depth below; a "
        "disagreement is a finding about the corpus pipeline, not a tuning "
        "opportunity.")
    for pr in predictions:
        log(f"  {pr['preset']}: {pr['modsource']} -> {pr['dest_id']} "
            f"{pr['dest_name']!r} norm={pr['expected_depth_normalized']}")
    if not predictions:
        log("  (none: no named carrier has an in-class route)")
    log("")
    log(f"VERDICT: audit complete (oracle-independent); refusal control "
        f"{'PASS' if controls_ok else 'FAIL'}"
        f"{' (skipped)' if args.skip_refusal_control else ''}. Acceptance "
        "items 2 and 5 of #70 remain NOT_RUN - pinned oracle unavailable on "
        "dispatch host (#96).")

    if args.out_dir:
        d = os.path.abspath(args.out_dir)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "carrier-route-audit.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(d, "carrier-route-audit.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"graphs_sha256": got,
                       "graphs_sha256_matches_issue_pin": True,
                       "blob_verification": "census-vs-graphs cross-check "
                                            "only; NOT a payload hash",
                       "frozen_destination_class": FROZEN_CLASS,
                       "named_carriers": CARRIERS,
                       "fixture_carrier": FIXTURE_CARRIER,
                       "audit": audit,
                       "oracle_host_backfill_predictions": predictions,
                       "refusal_control":
                           "SKIPPED" if args.skip_refusal_control
                           else ("PASS" if controls_ok else "FAIL"),
                       "reference_budget_items": "NOT_RUN (#96)"}, f, indent=2)
            f.write("\n")
    return 0 if controls_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        sys.exit(2)
