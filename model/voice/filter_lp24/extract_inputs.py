#!/usr/bin/env python3
"""SXT-038 fail-closed case extractor (LP 24 dB filter leaf).

Reads the committed, sha-pinned normalized graph corpus
(`corpus/normalized/graphs.jsonl`) and emits one case file per declared
carrier/corner into `reports/SXT-038/artifacts/cases/`.  Nothing is guessed:
the filter parameters (type, subtype, cutoff, resonance, keytrack, env-mod,
keytrack root) come from the carrier's own normalized record, the census
blob sha1 is verified, and any mismatch REFUSES (exit 2).

Carrier presets are the three named in issue #72 plus two additional
recovery-basis presets that carry LIVE keytrack/env-mod into an LP 24 dB
unit (the three issue carriers all store kt = em = 0, so on their own they
would never exercise the keytrack/env-mod path or a moving coefficient
plane).  Every carrier below is in the issue's recovery-basis list.

The `.fxp` payloads themselves live in the externally pinned GPL Surge
checkout, which is NOT present in this environment; this extractor therefore
works entirely from the committed normalized graph state (SXT-011) and never
claims to have loaded a preset.

Usage:
  python3 model/voice/filter_lp24/extract_inputs.py [--out-dir DIR] [--check]
"""

import argparse
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
# Declared in issue #72 (data lineage) and in corpus/normalized/README.md.
GRAPHS_SHA256 = "c90424d91f2dc9ec4222c0cd28e4d0dba470dd895419db33305c53df39204715"
TAP_ARTIFACTS = os.path.join("reports", "sxt-037", "artifacts")
FUT_LP24 = 2

CARRIER_BLOCKS = 1944      # 124,416 OS samples (the SXT-037 tap stream length)
CORNER_BLOCKS = 384        # 24,576 OS samples

# Which (tag, lane) stream each committed SXT-037 tap bundle carries; the tap
# wrote tag 0 for filter unit 1 and tag 1 for filter unit 2.
TAP_STREAM = {"badnews": (0, 0), "rainy": (0, 0), "t9": (1, 0)}

# (case, census blob sha1, scene, unit, stimulus bundle, sequence)
CARRIERS = [
    # --- the three carriers named in issue #72 -----------------------------
    ("edges", "099e88298ae11cc7a5335054c04f3caf7e1539dc", 1, 0,
     "badnews", "seq-notes-coverage-v1"),
    ("chords-clean", "ceaa96a85b3fdd3d9f026087c70d6fb2a6e76057", 0, 0,
     "rainy", "seq-notes-coverage-v1"),
    ("chords-std", "ceaa96a85b3fdd3d9f026087c70d6fb2a6e76057", 1, 0,
     "rainy", "seq-notes-holds-v1"),
    ("brass", "5377665368711db5785c98179ece7f9f3996392b", 0, 0,
     "t9", "seq-notes-coverage-v1"),
    # --- recovery-basis carriers with live keytrack / env-mod --------------
    ("phase1", "52f18c7c55c45e7314edf082f2c1384191712d92", 0, 0,
     "badnews", "seq-notes-coverage-v1"),
    ("major7mk2", "3bfc43d08397f853b73387967f2b6f9a50bfa943", 1, 0,
     "rainy", "seq-notes-coverage-v1"),
]

# (case, base case, overrides, blocks, note)
CORNERS = [
    ("edges-reso1", "edges", {"res": 1.0}, CORNER_BLOCKS,
     "resonance -> 1.0: the self-oscillation corner of the Driven kernel"),
    ("edges-cut-hi", "edges", {"cut": 96.0}, CORNER_BLOCKS,
     "cutoff -> +96 st: the pinned boundFreq clamp upper edge (+75)"),
    ("edges-cut-lo", "edges", {"cut": -96.0}, CORNER_BLOCKS,
     "cutoff -> -96 st: the pinned boundFreq clamp lower edge (-55)"),
    ("edges-toggle", "edges", {"toggle_subtype": 2, "toggle_from_segment": 4},
     2 * CORNER_BLOCKS,
     "mid-render subtype change Driven -> Clean: CM.Reset() + FBP zero + "
     "FromDirect FirstRun, and the clipgain register moving from R[2] to R[4]"),
    ("phase1-substd", "phase1", {"subtype": 0}, CORNER_BLOCKS,
     "same carrier parameters through the Standard (SVF) kernel: the third "
     "subtype at a live keytrack/env-mod control plane"),
]


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_graphs():
    got = sha256_file(GRAPHS)
    if got != GRAPHS_SHA256:
        raise Refuse(f"graphs.jsonl sha256 {got} != declared {GRAPHS_SHA256}")
    by_blob = {}
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            by_blob[rec["sha"]] = rec
    return by_blob


def tap_sha(bundle):
    """sha256 of a committed SXT-037 tap stream, from its sha256sums.txt."""
    sums = os.path.join(REPO, TAP_ARTIFACTS, "sha256sums.txt")
    want = f"{bundle}/units.bin"
    with open(sums, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2 and parts[1] == want:
                return parts[0]
    raise Refuse(f"no sha256sums.txt entry for {want}")


def carrier_case(name, blob, scene, unit, bundle, seq, graphs):
    rec = graphs.get(blob)
    if rec is None:
        raise Refuse(f"{name}: census blob {blob} not present in graphs.jsonl")
    scenes = rec["g"]["sc"]
    if scene >= len(scenes):
        raise Refuse(f"{name}: scene {scene} out of range")
    sc = scenes[scene]
    if unit >= len(sc["fu"]):
        raise Refuse(f"{name}: filter unit {unit} out of range")
    fu = sc["fu"][unit]
    if int(fu["t"]) != FUT_LP24:
        raise Refuse(f"{name}: scene {scene} unit {unit} is type {fu['t']} "
                     f"({fu.get('tn')!r}), not fut_lp24")
    if int(fu["st"]) not in (0, 1, 2):
        raise Refuse(f"{name}: subtype {fu['st']} outside the declared LP24 set")
    if not (0.0 <= float(fu["res"]) <= 1.0):
        raise Refuse(f"{name}: resonance {fu['res']} outside [0, 1]")
    bundle_rel = os.path.join(TAP_ARTIFACTS, f"bundle-{bundle}")
    if bundle not in TAP_STREAM:
        raise Refuse(f"{name}: no declared tap stream for bundle {bundle}")
    tag, lane = TAP_STREAM[bundle]
    return {
        "schema": "sxt-038-case/1",
        "case": name,
        "issue": "SXT-038",
        "carrier": {
            "rel": rec["p"],
            "census_blob_sha1": blob,
            "scene": scene,
            "unit": unit,
            "graphs_sha256": GRAPHS_SHA256,
            "schema_version": rec["pin"]["sv"],
            "engine_pin": rec["pin"]["e"],
        },
        "filter": {
            "type": int(fu["t"]),
            "type_name": fu.get("tn"),
            "subtype": int(fu["st"]),
            "subtype_name": fu.get("stn"),
            "cut": float(fu["cut"]),
            "res": float(fu["res"]),
            "kt": float(fu["kt"]),
            "em": float(fu["em"]),
            "ktR": float(sc["ktR"]),
        },
        "sequence": seq,
        "stimulus": {
            "source": "sxt037-tap",
            "bundle": bundle_rel,
            "sha256": tap_sha(bundle),
            "tag": tag,
            "lane": lane,
            "blocks": CARRIER_BLOCKS,
            "note": ("real engine voice-path signal captured at the filter-unit "
                     "INPUT boundary by the SXT-037 oracle tap (DR-0005) and "
                     "committed there; reused here as a declared stimulus, "
                     "identical for both legs"),
        },
    }


def corner_case(name, base_case, overrides, blocks, note):
    case = json.loads(json.dumps(base_case))
    case["case"] = name
    case["derived_from"] = base_case["case"]
    case["overrides"] = overrides
    case["corner_note"] = note
    case["stimulus"] = dict(case["stimulus"], blocks=blocks)
    return case


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(REPO, "reports", "SXT-038",
                                                      "artifacts", "cases"))
    ap.add_argument("--check", action="store_true",
                    help="regenerate and diff against the committed cases")
    args = ap.parse_args()

    graphs = load_graphs()
    cases = {}
    for name, blob, scene, unit, bundle, seq in CARRIERS:
        cases[name] = carrier_case(name, blob, scene, unit, bundle, seq, graphs)
    for name, base, ov, blocks, note in CORNERS:
        if base not in cases:
            raise Refuse(f"{name}: unknown base case {base}")
        cases[name] = corner_case(name, cases[base], ov, blocks, note)

    os.makedirs(args.out_dir, exist_ok=True)
    changed = []
    for name, case in cases.items():
        path = os.path.join(args.out_dir, f"{name}.json")
        body = json.dumps(case, indent=1, sort_keys=True) + "\n"
        old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if old != body:
            changed.append(name)
            if not args.check:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(body)
    summary = {
        "cases": sorted(cases),
        "carriers": [c for c, *_ in CARRIERS],
        "corners": [c for c, *_ in CORNERS],
        "changed": changed,
        "graphs_sha256": GRAPHS_SHA256,
    }
    print(json.dumps(summary, indent=2))
    if args.check and changed:
        print("REFUSING: committed cases differ from a fresh extraction", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
