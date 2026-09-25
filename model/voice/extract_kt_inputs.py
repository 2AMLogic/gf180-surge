#!/usr/bin/env python3
"""SXT-042: extract the keytrack (ms_keytrack, pinned id 2) fixture inputs for
the declared carrier `Rozzer/Bells/Hell's Bells.fxp`.

Why this carrier: it is the one preset in the landed SXT-026a voice class
whose PRESET CONTENT carries a live keytrack voice route (ms_keytrack ->
"A Filter 1 Cutoff", depth 4.387498 semitones), and the pinned engine's DRY
render of it is already committed, sha-pinned and determinism-gated, in
`reports/sxt-025/fixtures/` (see tools/kt_reference_from_fixture.py).  The
three carriers named in issue #76 are outside the landed voice class (their
refusals are recorded by the negative-control transcript).

The extractor is fail-closed (`Refuse` -> exit 2) and cross-checks FOUR
independent committed records of the same preset before emitting anything:

  1. `corpus/census-v0.1/results/per-preset.csv`   (git blob SHA-1)
  2. `corpus/normalized/graphs.jsonl`              (`sha` field + md rows)
  3. `model/voice/bells_inputs.json`               (schema-2 sidecar, the
     #48 engine readback: `graph_echo.md_scene_A` must equal the graphs rows
     word-for-word, and its `census_blob_sha1` must equal 1.)
  4. `reports/sxt-025/fixtures/hells_bells__sxt025-accept-v1.json`
     (the pinned-engine reference fixture manifest)

Provenance modes:
  * `engine-readback` (default): the pinned oracle is imported and the live
    `getAllModRoutings()` rows are compared against the graph rows, exactly
    as `extract_mw_inputs.py` does.  Requires ORACLE_SURGE_DIR.
  * `offline-committed-state` (`--allow-offline-provenance`): no oracle on
    this host; provenance is the four committed records above, and the
    sidecar records that NO new engine readback occurred.  This never
    invents a value: every number written comes from a committed,
    sha-checked artifact.

Usage:
  python3 model/voice/extract_kt_inputs.py [--allow-offline-provenance]
"""

import argparse
import csv
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
V2_SIDECAR = os.path.join(REPO, "model", "voice", "bells_inputs.json")
REF_MANIFEST = os.path.join(REPO, "reports", "sxt-025", "fixtures",
                            "hells_bells__sxt025-accept-v1.json")
PRESET_REL = "resources/data/patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp"
ENGINE_COMMIT = "58914e59c608ed4384ba6002e44c3465c58b2e71"

MS_VELOCITY = 1
MS_KEYTRACK = 2
DEST_NAMES = {
    308: "A Filter 1 Cutoff",
    309: "A Filter 1 Resonance",
    310: "A Filter 1 FEG Mod Amount",
    314: "A Filter 2 Cutoff",
    315: "A Filter 2 Resonance",
    318: "A Filter 2 FEG Mod Amount",
    298: "A VCA Gain",
}
KT_DEST_LIVE = (308, 309, 310)        # modeled (filter unit 1 is the live unit)
KT_DEST_INERT = (314, 315, 318)       # accepted, inert (unit 2 Off in class)


class Refuse(Exception):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def census_blob(rel):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel:
                return row["git_blob_sha1"]
    raise Refuse(f"preset not in census: {rel}")


def graphs_row(rel):
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("p") == rel:
                return r
    raise Refuse(f"preset not in graphs.jsonl: {rel}")


def engine_cross_check(preset_abs, graph_v_rows):
    """Optional live readback (pinned oracle); fail-closed on any surprise."""
    sys.path.insert(0, os.path.join(REPO, "oracle"))
    import oracle_common as oc                      # noqa: E402

    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(preset_abs):
        raise Refuse("loadPatch failed")
    live = s.getAllModRoutings()["scene"][0]["voice"]
    live_rows = [(r.getDest().getName(), r.getDepth()) for r in live]
    if len(live_rows) != len(graph_v_rows):
        raise Refuse(f"voice routing count {len(live_rows)} != graphs "
                     f"{len(graph_v_rows)}")
    for (name, depth), row in zip(live_rows, graph_v_rows):
        if name != row[4]:
            raise Refuse(f"dest name mismatch: engine {name!r} != graphs "
                         f"{row[4]!r}")
        if abs(depth - row[5]) > 1e-4:
            raise Refuse(f"depth mismatch on {name}: {depth} != {row[5]}")
    return {"version_string": surgepy.getVersion(),
            "sample_rate": int(s.getSampleRate()),
            "block_size": int(s.getBlockSize()),
            "voice_routings_read": len(live_rows)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(REPO, "model", "voice",
                                                  "bells_kt_inputs.json"))
    ap.add_argument("--allow-offline-provenance", action="store_true",
                    help="no pinned oracle on this host: derive provenance "
                         "from the committed census/graphs/sidecar/fixture "
                         "records only (recorded in the sidecar)")
    args = ap.parse_args()

    # --- 1/2: census + graphs ------------------------------------------------
    blob = census_blob(PRESET_REL)
    row = graphs_row(PRESET_REL)
    if row.get("sha") != blob:
        raise Refuse(f"graphs sha {row.get('sha')} != census blob {blob}")
    scenes = row["g"]["md"]["s"]
    if len(scenes) < 1:
        raise Refuse("graphs md carries no scene rows")
    v_rows = scenes[0]["v"]
    if any(sc["v"] or sc["s"] for sc in scenes[1:]):
        raise Refuse("scene B carries modulation routes: outside the "
                     "single-scene class")

    # --- 3: schema-2 sidecar (the #48 engine readback) -----------------------
    with open(V2_SIDECAR, encoding="utf-8") as f:
        v2 = json.load(f)
    if v2["preset"]["path"] != PRESET_REL:
        raise Refuse("v2 sidecar is for a different preset")
    if v2["preset"]["census_blob_sha1"] != blob:
        raise Refuse("v2 sidecar blob != census blob")
    if v2["graph_echo"]["md_scene_A"]["v"] != v_rows:
        raise Refuse("v2 sidecar md_scene_A.v != graphs.jsonl scene-A v rows")
    keytrack_root = v2["not_in_graphs"]["keytrack_root"]
    scene_octave = v2["not_in_graphs"]["scene_octave"]
    if float(keytrack_root) != int(keytrack_root):
        raise Refuse(f"non-integer keytrack_root {keytrack_root}")
    if float(scene_octave) != int(scene_octave):
        raise Refuse(f"non-integer scene octave {scene_octave}")

    # --- 4: the committed pinned-engine reference fixture --------------------
    with open(REF_MANIFEST, encoding="utf-8") as f:
        refman = json.load(f)
    if refman["preset"]["census_blob_sha1"] != blob:
        raise Refuse("reference fixture manifest blob != census blob")
    if refman["engine"]["engine_commit"] != ENGINE_COMMIT:
        raise Refuse("reference fixture engine commit != pinned commit")

    # --- route table (md order preserved) ------------------------------------
    routes, kt_live, kt_inert = [], 0, 0
    for r in v_rows:
        src, dst, name, depth, norm = r[0], r[3], r[4], r[5], r[6]
        if src not in (MS_VELOCITY, MS_KEYTRACK):
            raise Refuse(f"voice route source {src} outside the declared "
                         "class {velocity(1), keytrack(2)}")
        if DEST_NAMES.get(dst) != name:
            raise Refuse(f"destination id/name mismatch: {dst} vs {name!r}")
        if src == MS_KEYTRACK and dst not in KT_DEST_LIVE + KT_DEST_INERT:
            raise Refuse(f"keytrack route -> {dst} ({name!r}) outside the "
                         f"declared SXT-042 destination class "
                         f"{{{', '.join(str(d) for d in KT_DEST_LIVE)}}} "
                         f"(+ inert unit-2 {KT_DEST_INERT})")
        live = dst in KT_DEST_LIVE or (src == MS_VELOCITY and dst in
                                       (298,) + KT_DEST_LIVE)
        if src == MS_KEYTRACK:
            kt_live += int(dst in KT_DEST_LIVE)
            kt_inert += int(dst in KT_DEST_INERT)
        routes.append({
            "source_id": src,
            "source": "ms_keytrack" if src == MS_KEYTRACK else "ms_velocity",
            "dest_id": dst,
            "dest_name": name,
            "depth_raw": depth,
            "depth_normalized": norm,
            "modeled": bool(live),
            "note": ("inert: filter unit 2 is Off in the declared class"
                     if dst in KT_DEST_INERT else "modeled"),
        })
    if kt_live == 0:
        raise Refuse("no LIVE keytrack route in this preset: nothing for the "
                     "SXT-042 leaf to verify against the reference")

    engine = {"commit": ENGINE_COMMIT}
    if args.allow_offline_provenance:
        mode = "offline-committed-state"
        engine["readback"] = ("NOT_RUN: no pinned oracle on this host; every "
                              "value below comes from a committed, "
                              "sha-checked record (census/graphs/#48 "
                              "sidecar/SXT-025 fixture manifest)")
        engine["version_string"] = refman["engine"]["engine_version_string"]
        engine["sample_rate"] = refman["engine"]["sample_rate"]
        engine["block_size"] = refman["engine"]["block_size_samples"]
    else:
        sys.path.insert(0, os.path.join(REPO, "oracle"))
        import oracle_common as oc                  # noqa: E402
        preset_abs = os.path.join(oc.data_home(),
                                  PRESET_REL[len("resources/data/"):])
        if not os.path.exists(preset_abs):
            raise Refuse("pinned-engine preset not found; set ORACLE_SURGE_DIR "
                         "or pass --allow-offline-provenance")
        mode = "engine-readback"
        engine.update(engine_cross_check(preset_abs, v_rows))

    out = {
        "schema_version": 1,
        "issue": "SXT-042",
        "frozen_scope": (
            "ms_keytrack (pinned id 2) as a per-voice modulation source on "
            "the landed SXT-022/SXT-026a voice class: word = "
            "(state.pitch - keytrack_root)/12 in Q10.21, per voice instance, "
            "refreshed AFTER each control pass's route application (declared "
            "1-control-pass lag); destination class {308 Filter 1 Cutoff, "
            "309 Filter 1 Resonance, 310 Filter 1 FEG Mod Amount} live, "
            "{314, 315, 318} accepted-inert (unit 2 Off); every other "
            "destination and every other source refused fail-closed"),
        "provenance_mode": mode,
        "preset": {
            "path": PRESET_REL,
            "census_blob_sha1": blob,
            "graphs_sha": row.get("sha"),
            "v2_sidecar": os.path.relpath(V2_SIDECAR, REPO),
            "v2_sidecar_sha256": sha256_file(V2_SIDECAR),
            "reference_manifest": os.path.relpath(REF_MANIFEST, REPO),
            "reference_manifest_sha256": sha256_file(REF_MANIFEST),
        },
        "engine": engine,
        "keytrack_root": int(keytrack_root),
        "scene_octave": int(scene_octave),
        "voice_routes": routes,
        "keytrack_route_counts": {"live": kt_live, "inert": kt_inert},
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps({"out": os.path.relpath(args.out, REPO),
                      "provenance_mode": mode,
                      "voice_routes": len(routes),
                      "keytrack_live": kt_live,
                      "keytrack_inert": kt_inert}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
