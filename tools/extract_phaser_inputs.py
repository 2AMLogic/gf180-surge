#!/usr/bin/env python3
"""SXT-028g: fail-closed extraction of Phaser-chain inputs from the pinned
engine.

ORACLE-GATED. It imports surgepy from the pinned external oracle checkout
(oracle/manifest.json). Without that checkout it REFUSES — it never emits a
partially-guessed input file and never falls back to raw .fxp values (raw
values are pre-migration; only the native loader's normalized state is
authoritative, AGENTS.md).

Follows model/effects/extract_fx_inputs.py (SXT-023) and
tools/extract_chorus_inputs.py (SXT-028c) conventions:
  * census blob SHA-1 re-verified at extraction against
    corpus/census-v0.1 (mismatch -> Refuse),
  * graphs.jsonl (SXT-011) fx types cross-checked against the engine's own
    readback (mismatch -> Refuse),
  * fx_bypass / fx_disable asserted zero,
  * any modulation route into an FX parameter -> Refuse (fail-closed),
  * drift asserted 0 and non-muted oscillators asserted retrigger-on for
    every voicing scene (SXT-012 bit-identical determinism class),
  * `deactivated` from the RAW .fxp XML attribute plus the DOCUMENTED loader
    migrations of PhaserEffect::handleStreamingMismatches, cross-checked
    against the surgepy getters where observable,
  * mod_wave 5 (Noise) / 6 (Sample & Hold) -> Refuse: RNG-driven, outside
    the frozen deterministic scope of the model. As of #122 this is no
    longer only a leaf-local omission: the refusal's CONTRACT REASON is
    recorded in decision-records/0013-fx-modulation-rng-stream.md, the
    stream was measured unpinnable
    (reports/SXT-028-rng/artifacts/rng-characterization.json), and the
    coverage cost is published as a reduction
    (reports/SXT-028-rng/artifacts/coverage-impact.json). DETERMINISTIC_WAVES
    below is unchanged -- the gate is the same, its justification is now a
    visible contract revision routed to SXT-017 (#12).

Phaser (fxt_phaser = 3) parameters, sst-effects Phaser.h phaser_params:
  center(0) feedback(1) sharpness(2) mod_rate(3) mod_depth(4) stereo(5)
  mix(6) width(7) stages(8, int) spread(9) mod_wave(10, int) tone(11)

Loader migrations reproduced here for the raw-XML cross-check
(PhaserEffect.cpp handleStreamingMismatches):
  rev <= 13 : stages = 4, width = 0
  rev <= 15 : mod_wave = 1 (Triangle), mod_rate.deactivated = false
  rev <= 17 : tone = 0, tone.deactivated = true
  rev <  30 : sst-effects streaming 1 -> 2 waveform remap
              (mod_wave 3/4 -> +2 and stereo forced to 1; 5 -> 4)

Writes model/effects/fx_inputs/type-phaser-<slug>.json.
Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, copies nothing.
"""

import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import oracle_common as oc  # noqa: E402

oc.reexec_under_pinned_python(REPO)

from model.effects.extract_fx_inputs import (  # noqa: E402
    Refuse, census_entry, raw_xml_flags, read_delay, read_eq,
)

FX_TYPE_PHASER = 3
PHASER_PARAMS = 12
# off, delay, reverb1, eq, chorus (landed siblings) + phaser (this leaf)
LANDED_CLASSES = {0, 1, 2, 6, 9, 3}

DETERMINISTIC_WAVES = (0, 1, 2, 3, 4)   # sine, tri, saw, ramp, square

REV1_PARAM_IDS = ["predelay", "shape", "roomsize", "decaytime", "damping",
                  "lowcut", "freq1", "gain1", "highcut", "mix", "width"]

# B4-scope carriers named by issue #59, with the census blob SHA-1 recorded
# by the generator (reports/sxt-028/leaves/SXT-028g/newly-enabled.json).
# The SHA is re-verified from the engine checkout at extraction time.
PRESETS = {
    "reson": "resources/data/patches_3rdparty/Argitoth/FX/Reson.fxp",
    "bass11": "resources/data/patches_3rdparty/Bluelight/Basses/Bass 11.fxp",
    "bass17": "resources/data/patches_3rdparty/Bluelight/Basses/Bass 17.fxp",
}


def phaser_fx_destinations(graphs):
    """Modulation routes whose destination is an FX parameter (fail-closed).

    `graphs["g"]["md"]` is a DICT of modulation buses --
    `{g: [...], s: [{s: [...], v: [...]}]}` (corpus/normalized/schema.json) --
    not a flat list of routes, so iterating it directly yields the keys
    "g"/"s" and inspects no route at all. Walk `md.g` plus each scene's `s`
    (scene) and `v` (voice) buses, exactly as
    tools/extract_chorus_inputs.py::chorus_fx_destinations (#116),
    tools/extract_aw49_inputs.py::md_fx_destinations and
    tools/extract_conditioner_inputs.py::md_routes do.

    Route rows are `[src, ..., dest_id, dest_name, depth, ...]`
    (corpus/normalized/README.md); FX destinations carry names starting with
    "FX" (e.g. "FX B1 Mix"). Rows with no destination-name field are skipped
    rather than raising (same `len(r) > 4` guard as the aw49 screen).

    Pure: reads only the committed graphs line, so the screen is exercisable
    without surgepy / the oracle host (tests/test_extract_phaser_inputs.py).
    """
    hits = []

    def scan(rows):
        for r in rows:
            name = r[4] if len(r) > 4 else ""
            if isinstance(name, str) and name.startswith("FX"):
                hits.append(name)

    md = graphs["g"].get("md") or {}
    scan(md.get("g", []))
    for sc in md.get("s", []):
        scan(sc.get("s", []))
        scan(sc.get("v", []))
    return hits


def read_phaser(s, patch, slot, rev, xml_flags, tempo_bpm):
    fxd = patch["fx"][slot]

    def fv(j):
        return float(s.getParamVal(fxd["p"][j]))

    def iv(j):
        return int(round(float(s.getParamVal(fxd["p"][j]))))

    def ts(j):
        return bool(s.getTempoSync(fxd["p"][j]))

    xf = lambda j: xml_flags.get(f"fx{slot+1}_p{j}", {})  # noqa: E731

    for j in range(PHASER_PARAMS):
        f = xf(j)
        if f and "temposync" in f and f["temposync"] != ts(j):
            raise Refuse(f"temposync mismatch slot{slot} p{j}")

    def deactivated(j, ctor_default):
        f = xf(j)
        if f and not f["deactivated_absent"]:
            raw = bool(f["deactivated"])
        else:
            raw = ctor_default
        # PhaserEffect::handleStreamingMismatches, documented above
        if j == 3 and rev <= 15:      # ph_mod_rate
            return False
        if j == 11 and rev <= 17:     # ph_tone
            return True
        return raw

    wave = iv(10)
    if wave not in DETERMINISTIC_WAVES:
        raise Refuse(
            f"mod_wave {wave} (Noise/Sample&Hold) is RNG-driven and outside "
            "the frozen deterministic scope of the SXT-028g model")
    stages = iv(8)
    if not 1 <= stages <= 16:
        raise Refuse(f"stages {stages} outside Phaser.h range 1..16")

    d = {
        "center_f": fv(0), "feedback_f": fv(1), "sharpness_f": fv(2),
        "mod_rate_f": fv(3), "mod_depth_f": fv(4), "stereo_f": fv(5),
        "mix_f": fv(6), "width_f": fv(7),
        "stages_i": stages, "spread_f": fv(9),
        "mod_wave_i": wave, "tone_f": fv(11),
        "mod_rate_deactivated": deactivated(3, False),
        "tone_deactivated": deactivated(11, False),
        "ts_flags": [ts(j) for j in range(PHASER_PARAMS)],
    }
    if tempo_bpm is None:
        tempo_bpm = 120.0
    # Phaser::setvars: only ph_mod_rate consumes temposyncRatio
    d["ts_rate"] = bool(d["ts_flags"][3])
    d["ts_ratio_mod"] = tempo_bpm / 120.0 if d["ts_rate"] else 1.0
    return d


def read_reverb1(s, patch, slot, xml_flags):
    fxd = patch["fx"][slot]
    params = {n: float(s.getParamVal(fxd["p"][i]))
              for i, n in enumerate(REV1_PARAM_IDS)}
    xf = lambda j: xml_flags.get(f"fx{slot+1}_p{j}", {})  # noqa: E731

    def deactivated(j):
        f = xf(j)
        if f and not f["deactivated_absent"]:
            return bool(f["deactivated"])
        return None

    return {"params": params,
            "lowcut_deactivated_raw": deactivated(5),
            "highcut_deactivated_raw": deactivated(8),
            "return_f": float(s.getParamVal(fxd["return_level"]))}


def extract(slug, rel_path, out_path):
    surgepy = oc.import_surgepy()
    oc.apply_engine_env()
    blob, graphs = census_entry(rel_path)
    abs_path = os.path.join(oc.engine_dir(), rel_path)
    actual = oc.git_blob_sha1(abs_path)
    if actual != blob:
        raise Refuse(f"census blob mismatch: {rel_path} {actual} != {blob}")
    if graphs["g"]["fxb"] != 0:
        raise Refuse(f"fx_bypass != fxb_all_fx: {rel_path}")
    if graphs["g"]["fxd"] != 0:
        raise Refuse(f"fx_disable nonzero: {rel_path}")
    fx_mod = phaser_fx_destinations(graphs)
    if fx_mod:
        raise Refuse(f"modulation route into FX parameter ({fx_mod[:4]}): "
                     f"{rel_path}")

    rev, tempo, xml_flags = raw_xml_flags(rel_path)

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(abs_path):
        raise Refuse(f"loadPatch failed: {rel_path}")
    patch = s.getPatch()

    sm = int(s.getParamVal(patch["scenemode"]))
    sa = int(s.getParamVal(patch["scene_active"]))
    voicing = [sa] if sm == 0 else [0, 1]
    drifts = []
    for sc_i in voicing:
        sc = patch["scene"][sc_i]
        drift = float(s.getParamVal(sc["drift"]))
        drifts.append(drift)
        if drift != 0.0:
            raise Refuse(f"drift {drift} != 0 in scene {sc_i}: {rel_path}")
        for oi in range(3):
            level = float(s.getParamVal(sc[f"level_o{oi+1}"]))
            mute = int(s.getParamVal(sc[f"mute_o{oi+1}"]))
            if level > 0 and mute == 0:
                if int(s.getParamVal(sc["osc"][oi]["retrigger"])) != 1:
                    raise Refuse(f"osc{oi+1} retrigger off (non-muted): "
                                 f"{rel_path}")

    engine_types = [int(s.getParamVal(patch["fx"][i]["type"]))
                    for i in range(16)]
    graph_types = [fx.get("t", 0) for fx in graphs["g"]["fx"]]
    if engine_types != graph_types:
        raise Refuse(f"fx type mismatch engine vs graphs: {rel_path}")

    out_of_scope = sorted({t for t in engine_types if t not in LANDED_CLASSES})
    complete_wet = not out_of_scope
    if not complete_wet:
        print(f"applicability {slug}: complete-wet REFUSED (unlanded classes "
              f"{out_of_scope})", file=sys.stderr)

    volume_f = float(s.getParamVal(patch["volume"]))
    scene_sends = [[float(s.getParamVal(patch["scene"][k]["send_level"][j]))
                    for j in range(2)] for k in range(2)]

    chain = {"ains": [], "sends": []}
    phaser_slots = []
    for slot in range(16):
        t = engine_types[slot]
        if t == 0:
            continue
        role = graphs["g"]["fx"][slot]["r"]
        if t == FX_TYPE_PHASER:
            params = read_phaser(s, patch, slot, rev, xml_flags, tempo)
            entry = {"slot": slot, "role": role, "type": "phaser",
                     "params": params}
            phaser_slots.append(slot)
        elif t == 1:
            entry = {"slot": slot, "role": role, "type": "delay",
                     "params": read_delay(s, patch, slot, rev, xml_flags,
                                          tempo)}
        elif t == 6:
            entry = {"slot": slot, "role": role, "type": "eq",
                     "params": read_eq(s, patch, slot, rev, xml_flags)}
        elif t == 2:
            entry = {"slot": slot, "role": role, "type": "reverb1",
                     "params": read_reverb1(s, patch, slot, xml_flags)}
        else:
            raise Refuse(f"slot{slot} type {t} outside landed scope: "
                         f"{rel_path}")
        if role.startswith("ains"):
            chain["ains"].append(entry)
        elif role.startswith("send"):
            idx = int(role[-1]) - 1
            entry["send_slot"] = idx
            entry["return_f"] = float(
                s.getParamVal(patch["fx"][slot]["return_level"]))
            entry["send_gain_f"] = scene_sends[0][idx]
            chain["sends"].append(entry)
        elif role.startswith("global"):
            chain.setdefault("globals", []).append(entry)
        elif role.startswith("bins"):
            entry["inactive_note"] = ("scene-B insert slot recorded for "
                                      "census; not processed by this leaf's "
                                      "chain model")
            chain.setdefault("inactive", []).append(entry)
        else:
            raise Refuse(f"slot{slot} role {role} outside frozen scope: "
                         f"{rel_path}")

    if not phaser_slots:
        raise Refuse(f"no phaser slot in {rel_path}")

    out = {
        "schema_version": 1,
        "leaf": "SXT-028g",
        "source": "oracle-extraction",
        "slug": slug,
        "path": rel_path,
        "census_blob_sha1": blob,
        "graphs_sha256_prefix": graphs["sha"][:16],
        "rev": rev,
        "tempo_bpm": tempo if tempo is not None else 120.0,
        "tempo_source": "tempoOnSave" if tempo is not None
                        else "engine default 120",
        "volume_f": volume_f,
        "scene_mode": sm,
        "scene_active": sa,
        "drifts_asserted_zero": drifts,
        "scene_sends_f": scene_sends,
        "phaser_slots": phaser_slots,
        "chain": chain,
        "applicability": {
            "complete_wet_render_possible": complete_wet,
            "unlanded_classes": out_of_scope,
            "note": "complete-wet refused fail-closed when any active slot "
                    "needs an unlanded class; the refusal is retained as "
                    "evidence, never silently dropped",
        },
        "extraction": {
            "deactivated_source": "raw fxp XML attribute + the documented "
                                  "PhaserEffect::handleStreamingMismatches "
                                  "migrations (rev<=15 mod_rate, rev<=17 "
                                  "tone)",
            "tempo_source": "raw <tempoOnSave v=..> applied by loadPatch",
            "observable_flags": "temposync via surgepy getters, cross-checked "
                                "against raw XML fail-closed",
            "mod_routes": "graphs.jsonl md.g + md.s[*].s + md.s[*].v rows "
                          "screened; any FX-destination route refuses "
                          "extraction (fail-closed)",
            "mod_wave_scope": "Noise (5) / Sample & Hold (6) refused: "
                              "RNG-driven, outside the frozen scope",
        },
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"extracted {slug} -> {out_path}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir",
                    default=os.path.join(REPO, "model", "effects", "fx_inputs"))
    ap.add_argument("--refusals",
                    default=os.path.join(REPO, "reports", "SXT-028g",
                                         "artifacts", "extract-refusals.txt"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.refusals), exist_ok=True)
    refusals = []
    for slug, rel in sorted(PRESETS.items()):
        try:
            extract(slug, rel,
                    os.path.join(args.out_dir, f"type-phaser-{slug}.json"))
        except Refuse as e:
            refusals.append(f"{slug}: REFUSED: {e}")
            print(f"REFUSED {slug}: {e}", file=sys.stderr)
    with open(args.refusals, "w", encoding="utf-8") as f:
        f.write("\n".join(refusals) + ("\n" if refusals else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(f"REFUSING: {e}", file=sys.stderr)
        sys.exit(2)
