#!/usr/bin/env python3
"""SXT-028e-sse: fail-closed extraction of SSE-branch Distortion inputs.

Follows `tools/extract_distortion_inputs.py` (SXT-028e) exactly and REUSES
its parameter-name table, its census/graphs readers, its landed-class
derivation and its refusal machinery; only the carrier set and the
admissible FX model indices differ.

TWO MODES, and they are NOT interchangeable:

  --mode oracle   (default)  Requires the pinned surgepy oracle
      (`oracle/manifest.json`, ORACLE_SURGE_DIR). Writes a COMPLETE record
      the frozen model can run.
  --mode graphs              Oracle-free. Derives ONLY the 12 normalized
      parameter values from `corpus/normalized/graphs.jsonl`, re-verifies
      the census blob SHA, and writes an INCOMPLETE record whose oracle-only
      fields are explicitly `null`. `DistortionSSEParams` REFUSES such a
      record (fail-closed): it is a cross-check artifact and an
      extraction-status record, never a substitute for the oracle read.

CARRIER SELECTION IS THIS LEAF'S OWN. None of the three B4-scope carriers
named by SXT-028e (#57) uses an SSE-branch model -- all three are model 0 --
so this leaf selects one carrier per REACHABLE FX model from
`corpus/normalized/graphs.jsonl`, preferring the simplest active chain.
Inventory only; NOT a support claim.

  model 3 wst_sine       Damon Armani / Drums / Reverse Crash
  model 4 wst_digital    Damon Armani / Plucks / Trance Pluck
  model 5 wst_ojd        Kinsey Dulcet / Guitars / Mutant Lo-Fi Acoustic ...
  model 6 wst_fwrectify  Luna / Guitars / Awful FM Guitar   (fx_disable != 0
                         -- REFUSED by the shared fail-closed screen; it is
                         the ONLY model-6 instance in the whole corpus)
  model 7 wst_fuzzsoft   NO CARRIER EXISTS. The corpus histogram for active
                         Distortion slots is {3: 13, 4: 8, 5: 6, 6: 1, 7: 0}
                         -- `wst_fuzzsoft` is in algorithmic scope but has
                         ZERO corpus reach, so it is exercised by synthetic
                         corners only and no fixture record is written. That
                         is recorded, not silently skipped.

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, in --mode oracle.
"""

import argparse
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion-sse"))

from sse_tables import SSE_MODELS, SSE_SHAPER_OF, FXWS_NAMES  # noqa: E402


def _load_sxt028e_extractor():
    path = os.path.join(REPO, "tools", "extract_distortion_inputs.py")
    spec = importlib.util.spec_from_file_location("sxt028e_extract", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E57 = _load_sxt028e_extractor()
Refuse = E57.Refuse
census_sha = E57.census_sha
graphs_entry = E57.graphs_entry
landed_classes = E57.landed_classes
FX_TYPE_TO_LEAF = E57.FX_TYPE_TO_LEAF
DIST_PARAM_NAMES = E57.DIST_PARAM_NAMES
ORACLE_ONLY = E57.ORACLE_ONLY
FX_TYPE_NAME = E57.FX_TYPE_NAME
OUTDIR = E57.OUTDIR

LEAF = "SXT-028e-sse"

# One carrier per reachable FX model (see the module docstring).
PRESETS = {
    "reversecrash": (
        "resources/data/patches_3rdparty/Damon Armani/Drums/Reverse Crash.fxp",
        "de5c684d96d6090728dfe2ede0a3dbd73af1d65f", 3),
    "trancepluck": (
        "resources/data/patches_3rdparty/Damon Armani/Plucks/Trance Pluck.fxp",
        "1bb5209f0f1d306df05a109d6015cf1a99c73d08", 4),
    "mutantlofiacoustic": (
        "resources/data/patches_3rdparty/Kinsey Dulcet/Guitars/"
        "Mutant Lo-Fi Acoustic Guitar Workstation.fxp",
        "714821ee0c7561bc1293bb422e2c4bd2f978b163", 5),
    "awfulfmguitar": (
        "resources/data/patches_3rdparty/Luna/Guitars/Awful FM Guitar.fxp",
        "d71a9cfd39789ca43e9b72ca3e65dd40d10be8f2", 6),
}
# FX models with zero corpus reach: recorded, never silently omitted.
NO_CARRIER_MODELS = [7]


def extract_graphs(slug, path, expect_sha, expect_model):
    """Oracle-free: loader-normalized parameter VALUES only (mode `graphs`)."""
    sha = census_sha(path)
    if expect_sha and not sha.startswith(expect_sha[:12]):
        raise Refuse(f"{slug}: census blob SHA drift "
                     f"(manifest {sha}, expected {expect_sha})")
    d = graphs_entry(path)
    if d.get("st") != "normalized":
        raise Refuse(f"{slug}: graphs status {d.get('st')} (not normalized)")
    g = d["g"]
    if g.get("fxd", 0) != 0:
        raise Refuse(f"{slug}: fx_disable = {g['fxd']} (non-zero)")
    landed = landed_classes()
    active = [f for f in g["fx"] if f.get("on")]
    unlanded = sorted({f["tn"] for f in active if f["tn"] not in landed})
    dist_slots = [f for f in active if f["tn"] == FX_TYPE_NAME]
    if not dist_slots:
        raise Refuse(f"{slug}: no active Distortion slot")
    slots = []
    for f in dist_slots:
        p = f["p"]
        rec = {k: p[i] for i, k in enumerate(DIST_PARAM_NAMES)}
        rec["model_i"] = int(p[11])
        if rec["model_i"] not in SSE_MODELS:
            # fail-closed the OTHER way: a model-0..2 slot belongs to #57
            raise Refuse(
                f"{slug}: Distortion slot {f['r']} uses FX model "
                f"{rec['model_i']} ({FXWS_NAMES[rec['model_i']]}), which is "
                "the SXT-028e (#57) table branch, not this leaf's SSE branch")
        for k in ORACLE_ONLY:
            rec[k] = None          # fail-closed: oracle-only, never guessed
        slots.append({"routing": f["r"], "slot_index": f["i"],
                      "fx_model_index": rec["model_i"],
                      "quad_waveshaper": SSE_SHAPER_OF[rec["model_i"]],
                      "params": rec})
    got_models = sorted({s["fx_model_index"] for s in slots})
    if expect_model is not None and expect_model not in got_models:
        raise Refuse(f"{slug}: expected FX model {expect_model}, "
                     f"graphs has {got_models}")
    return {
        "schema_version": 1,
        "leaf": LEAF,
        "slug": slug,
        "preset_path": path,
        "census_blob_sha1": sha,
        "extraction_mode": "graphs",
        "extraction_status": "INCOMPLETE-BLOCKED-ON-ORACLE",
        "source": "corpus/normalized/graphs.jsonl (SXT-011 pinned-loader "
                  "normalized export; deterministic, engine pin "
                  "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71)",
        "unresolved_fields": ORACLE_ONLY,
        "why_incomplete":
            "graphs.jsonl carries the 12 normalized FX parameter values but "
            "not the per-parameter `deactivated` / `extend_range` flags. "
            "DistortionSSEParams REFUSES a record with null fields, so this "
            "artifact cannot be used for a model run — it is a cross-check "
            "and extraction-status record only.",
        "chain": [{"routing": f["r"], "type": f["tn"], "slot_index": f["i"]}
                  for f in active],
        "unlanded_classes_in_chain": unlanded,
        "landed_classes_basis": {
            "source": "reports/coverage-v1/leaf-verification.json "
                      "(leaves[*].landed)",
            "landed_fx_classes": sorted(landed - {"Off"}),
            "note": "derived at extraction time, not hand-listed; a class "
                    "whose leaf is not marked landed in the committed table "
                    "counts as unlanded even if its PR has merged",
        },
        "complete_wet_render_possible": not unlanded,
        "distortion_slots": slots,
        "claim_scope": "data export only; no support, fidelity or "
                       "musical-quality claim",
    }


# Documented loader migrations for this effect
# (`DistortionEffect::handleStreamingMismatches`, as cited by
# tools/extract_distortion_inputs.py's module docstring and reproduced here):
#   streamingRevision <= 11  resets the model index and clears BOTH
#                            gain extend_range flags
#   streamingRevision <= 15  clears BOTH high-cut `deactivated` flags
# These are a CROSS-CHECK only. The authoritative read is the loader's own
# normalized state (`_loader_normalized_flags` below); a disagreement between
# the two refuses the extraction rather than picking a winner.
MIGRATE_MODEL_AND_GAIN_EXTEND_AT_OR_BELOW = 11
MIGRATE_HIGHCUT_DEACTIVATED_AT_OR_BELOW = 15

# Distortion parameter indices of the five oracle-only fields.
_DEACT_PARAM = {"preeq_highcut_deactivated": 3, "posteq_highcut_deactivated": 9}
_EXTEND_PARAM = {"preeq_gain_extend": 0, "posteq_gain_extend": 6,
                 "drive_extend": 4}


def _loader_normalized_flags(s, slot, tmpdir):
    """The five oracle-only fields from the loader's NORMALIZED state.

    `surgepy`'s `savePatch` serialises the patch the loader currently HOLDS,
    at the engine's CURRENT streaming revision, with every documented
    `handleStreamingMismatches` migration already applied by `loadPatch`.
    Parsing that round-trip is therefore a direct read of the normalized
    state — not a re-implementation of the migration, and not a read of the
    pre-migration raw `.fxp` (CLAUDE.md: raw `.fxp` values are
    pre-migration and are not authoritative).

    There is no `getDeactivated` getter on the binding, which is exactly why
    the round-trip is used: the alternative would be to *apply the migration
    rule ourselves*, which is a guess dressed up as a read.
    """
    import re

    out = os.path.join(tmpdir, f"roundtrip-slot{slot}.fxp")
    s.savePatch(out)
    with open(out, "rb") as f:
        data = f.read().decode("latin-1")
    m = re.search(r'<patch revision="(\d+)"', data)
    if not m:
        raise Refuse("savePatch round-trip has no revision attribute")
    saved_rev = int(m.group(1))
    attrs = {}
    for mm in re.finditer(r'<(fx%d_p\d+)\b([^>]*?)/?>' % (slot + 1), data):
        attrs[mm.group(1)] = mm.group(2)
    flags = {}
    for name, j in _DEACT_PARAM.items():
        a = attrs.get(f"fx{slot+1}_p{j}")
        if a is None:
            raise Refuse(f"round-trip has no fx{slot+1}_p{j} element")
        hit = re.search(r'deactivated="([01])"', a)
        if hit is None:
            raise Refuse(
                f"round-trip fx{slot+1}_p{j} carries no `deactivated` "
                "attribute; the normalized state does not declare the flag "
                "and this tool will not default it")
        flags[name] = hit.group(1) == "1"
    for name, j in _EXTEND_PARAM.items():
        a = attrs.get(f"fx{slot+1}_p{j}")
        if a is None:
            raise Refuse(f"round-trip has no fx{slot+1}_p{j} element")
        hit = re.search(r'extend_range="([01])"', a)
        if hit is None:
            raise Refuse(
                f"round-trip fx{slot+1}_p{j} carries no `extend_range` "
                "attribute; refusing rather than defaulting it")
        flags[name] = hit.group(1) == "1"
    return saved_rev, flags


def _cross_check_flags(s, patch, slot, raw_rev, xml_flags, flags):
    """Fail-closed agreement between three independent views of the flags.

    (a) the loader's normalized state (the authority, `flags`);
    (b) the live `getExtend` getter, for the three extend flags — observable,
        so a disagreement is a hard refusal;
    (c) the raw pre-migration `.fxp` attribute PLUS the documented migration
        rule, for all five — a cross-check, so a disagreement is also a hard
        refusal: one of the two readings is then wrong and this tool must not
        choose.
    """
    fxd = patch["fx"][slot]
    for name, j in _EXTEND_PARAM.items():
        live = bool(s.getExtend(fxd["p"][j]))
        if live != flags[name]:
            raise Refuse(
                f"slot{slot} {name}: loader-normalized state says "
                f"{flags[name]}, live getExtend says {live}")

    def raw(j):
        return xml_flags.get(f"fx{slot+1}_p{j}", {})

    for name, j in _EXTEND_PARAM.items():
        f = raw(j)
        expect = bool(f.get("extend_range", False))
        if (name in ("preeq_gain_extend", "posteq_gain_extend")
                and raw_rev <= MIGRATE_MODEL_AND_GAIN_EXTEND_AT_OR_BELOW):
            expect = False
        if expect != flags[name]:
            raise Refuse(
                f"slot{slot} {name}: normalized state {flags[name]} vs raw "
                f"XML + documented migration (rev {raw_rev}) {expect}")
    for name, j in _DEACT_PARAM.items():
        f = raw(j)
        if f and not f.get("deactivated_absent", True):
            expect = bool(f["deactivated"])
        else:
            expect = True        # deactivatable ctor default
        if raw_rev <= MIGRATE_HIGHCUT_DEACTIVATED_AT_OR_BELOW:
            expect = False
        if expect != flags[name]:
            raise Refuse(
                f"slot{slot} {name}: normalized state {flags[name]} vs raw "
                f"XML + documented migration (rev {raw_rev}) {expect}")


def _render_screens(s, patch, graphs, rel_path):
    """The SXT-012/023 render-admissibility screens, MEASURED and recorded.

    These do not change the parameter extraction (the record is written
    either way); they decide whether a reference FIXTURE may be rendered from
    this preset at all, and the measured reason is retained when it may not.
    """
    import extract_chorus_inputs as ec   # the committed FX-destination screen

    g = graphs["g"]
    screens = {"fx_bypass": int(g.get("fxb", 0)),
               "fx_disable": int(g.get("fxd", 0))}
    reasons = []
    if screens["fx_bypass"] != 0:
        reasons.append(f"fx_bypass = {screens['fx_bypass']} (not fxb_all_fx)")
    if screens["fx_disable"] != 0:
        reasons.append(f"fx_disable = {screens['fx_disable']} (non-zero)")
    fx_mod = ec.chorus_fx_destinations(graphs)
    screens["modulation_into_fx_params"] = sorted(set(fx_mod))
    if fx_mod:
        reasons.append("modulation routed into FX parameters: "
                       + ", ".join(sorted(set(fx_mod))[:6]))
    sm = int(s.getParamVal(patch["scenemode"]))
    sa = int(s.getParamVal(patch["scene_active"]))
    screens["scene_mode"] = sm
    screens["scene_active"] = sa
    voicing = [sa] if sm == 0 else [0, 1]
    drifts, osc = [], []
    for sc_i in voicing:
        sc = patch["scene"][sc_i]
        drift = float(s.getParamVal(sc["drift"]))
        drifts.append(drift)
        if drift != 0.0:
            reasons.append(f"drift = {drift} (not 0) in scene {sc_i}")
        for oi in range(3):
            level = float(s.getParamVal(sc[f"level_o{oi+1}"]))
            mute = int(s.getParamVal(sc[f"mute_o{oi+1}"]))
            rt = int(s.getParamVal(sc["osc"][oi]["retrigger"]))
            osc.append({"scene": sc_i, "osc": oi + 1, "level_f": level,
                        "mute": mute, "retrigger": rt})
            if level > 0 and mute == 0 and rt != 1:
                reasons.append(f"scene {sc_i} osc{oi+1} non-muted with "
                               "retrigger off")
    screens["drifts"] = drifts
    screens["oscillators"] = osc
    screens["reference_render_admissible"] = not reasons
    screens["refusal_reasons"] = reasons
    screens["note"] = (
        "static screens only. The 3x bit-identical render determinism gate is "
        "an EMPIRICAL gate and is applied by "
        "tools/render_distortion_sse_fixtures.py; passing these screens does "
        "not imply passing that one (SXT-028c precedent: melon, dronebee).")
    return screens


def _chain_models(s, patch, graphs, slots, landed):
    """A complete-wet chain description the frozen models can consume.

    Shaped like `tools/extract_chorus_inputs.py`'s `chain` block (ains /
    sends / globals), so `model/effects/run_distortion_sse_model.py` can
    build the chain with the already-landed sibling models. Returns
    `(chain, unlanded)`; `chain` is None when any active class is unlanded —
    fail-closed, never substituted with a generic.
    """
    import extract_chorus_inputs as ec
    from model.effects.extract_fx_inputs import read_delay, read_eq

    g = graphs["g"]
    active = [f for f in g["fx"] if f.get("on")]
    unlanded = sorted({f["tn"] for f in active if f["tn"] not in landed})
    if unlanded:
        return None, unlanded
    rev, tempo, xml_flags = ec.raw_xml_flags(graphs["p"])
    scene_sends = [[float(s.getParamVal(patch["scene"][k]["send_level"][j]))
                    for j in range(2)] for k in range(2)]
    chain = {"ains": [], "sends": [], "globals": []}
    for f in sorted(active, key=lambda f: f["i"]):
        slot, role, tn = f["i"], f["r"], f["tn"]
        if tn == FX_TYPE_NAME:
            entry = {"slot": slot, "role": role, "type": "distortion-sse",
                     "params": next(x["params"] for x in slots
                                    if x["slot_index"] == slot)}
        elif tn == "EQ":
            entry = {"slot": slot, "role": role, "type": "eq",
                     "params": read_eq(s, patch, slot, rev, xml_flags)}
        elif tn == "Delay":
            entry = {"slot": slot, "role": role, "type": "delay",
                     "params": read_delay(s, patch, slot, rev, xml_flags,
                                          tempo)}
        elif tn == "Chorus":
            entry = {"slot": slot, "role": role, "type": "chorus",
                     "params": ec.read_chorus(s, patch, slot, rev, xml_flags,
                                              tempo)}
        elif tn == "Reverb 1":
            entry = {"slot": slot, "role": role, "type": "reverb1",
                     "params": ec.read_reverb1(s, patch, slot, rev,
                                               xml_flags)}
        else:
            raise Refuse(f"slot{slot} class {tn} is marked landed but this "
                         "chain builder has no reader for it")
        if role.startswith("ains"):
            chain["ains"].append(entry)
        elif role.startswith("send"):
            idx = int(role[-1]) - 1
            entry["send_slot"] = idx
            entry["send_gain_f"] = scene_sends[0][idx]
            entry["return_f"] = float(
                s.getParamVal(patch["fx"][slot]["return_level"]))
            chain["sends"].append(entry)
        elif role.startswith("global"):
            chain["globals"].append(entry)
        else:
            raise Refuse(f"slot{slot} role {role} outside frozen chain scope")
    chain["volume_f"] = float(s.getParamVal(patch["volume"]))
    chain["scene_sends_f"] = scene_sends
    chain["tempo_bpm"] = tempo if tempo is not None else 120.0
    return chain, unlanded


def extract_oracle(slug, path, expect_sha, expect_model):
    """Oracle mode: the loader's NORMALIZED state (pinned surgepy required).

    Writes a COMPLETE record the frozen model can run: the twelve parameter
    values via `getParamVal`, and the five oracle-only `deactivated` /
    `extend_range` flags from the loader's own normalized state via a
    `savePatch` round-trip, cross-checked fail-closed against the live
    `getExtend` getters and against the raw pre-migration `.fxp` attributes
    plus the documented `handleStreamingMismatches` rules.
    """
    import tempfile

    sys.path.insert(0, os.path.join(REPO, "oracle"))
    sys.path.insert(0, os.path.join(REPO, "tools"))
    try:
        import oracle_common as oc
    except ImportError as e:
        raise Refuse(f"oracle harness unavailable: {e}")
    try:
        surgepy = oc.import_surgepy()
    except Exception as e:                            # noqa: BLE001
        raise Refuse(
            "no built surgepy at ORACLE_SURGE_DIR "
            f"({oc.engine_dir()}): {type(e).__name__}: {e}. The oracle "
            "extraction is BLOCKED and this tool refuses rather than "
            "inventing the missing flags. Install the pinned oracle first: "
            "oracle/fetch-and-build.sh --prebuilt (or --verify-only against "
            "a full checkout).")
    oc.apply_engine_env()
    from model.effects.extract_fx_inputs import raw_xml_flags

    sha = census_sha(path)
    if expect_sha and not sha.startswith(expect_sha[:12]):
        raise Refuse(f"{slug}: census blob SHA drift "
                     f"(manifest {sha}, expected {expect_sha})")
    abs_path = os.path.join(oc.engine_dir(), path)
    if not os.path.exists(abs_path):
        raise Refuse(f"{slug}: preset not present in the pinned checkout: "
                     f"{abs_path}")
    on_disk = oc.git_blob_sha1(abs_path)
    if on_disk != sha:
        raise Refuse(f"{slug}: census blob mismatch on the oracle host "
                     f"(census {sha}, on disk {on_disk})")
    d = graphs_entry(path)
    if d.get("st") != "normalized":
        raise Refuse(f"{slug}: graphs status {d.get('st')} (not normalized)")
    g = d["g"]
    if g.get("fxd", 0) != 0:
        raise Refuse(f"{slug}: fx_disable = {g['fxd']} (non-zero)")
    d = dict(d, p=path)

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(abs_path):
        raise Refuse(f"{slug}: loadPatch failed: {abs_path}")
    patch = s.getPatch()

    engine_types = [int(s.getParamVal(patch["fx"][i]["type"]))
                    for i in range(16)]
    graph_types = [fx.get("t", 0) for fx in g["fx"]]
    if engine_types != graph_types:
        raise Refuse(f"{slug}: fx type mismatch engine {engine_types} vs "
                     f"graphs {graph_types}")

    raw_rev, _tempo, xml_flags = raw_xml_flags(path)
    landed = landed_classes()
    active = [f for f in g["fx"] if f.get("on")]
    unlanded = sorted({f["tn"] for f in active if f["tn"] not in landed})
    dist_slots = [f for f in active if f["tn"] == FX_TYPE_NAME]
    if not dist_slots:
        raise Refuse(f"{slug}: no active Distortion slot")

    tmpdir = tempfile.mkdtemp(prefix="sxt028e-sse-roundtrip-")
    slots = []
    saved_revs = []
    for f in dist_slots:
        slot = f["i"]
        fxd = patch["fx"][slot]
        rec = {k: float(s.getParamVal(fxd["p"][i]))
               for i, k in enumerate(DIST_PARAM_NAMES)}
        rec["model_i"] = int(s.getParamVal(fxd["p"][11]))
        graph_vals = {k: f["p"][i] for i, k in enumerate(DIST_PARAM_NAMES)}
        # The committed SXT-011 export stores float parameters ROUNDED to 6
        # decimals (tools/export_normalized_graphs.py `_round6`), so the
        # cross-check compares at the export's own precision: equality after
        # applying the same rounding. Any larger difference is real drift.
        for k in DIST_PARAM_NAMES[:11]:
            if round(float(graph_vals[k]), 6) != round(rec[k], 6):
                raise Refuse(
                    f"{slug}: slot{slot} {k}: engine {rec[k]} vs committed "
                    f"graphs export {graph_vals[k]} (drift != 0 at the "
                    "export's 6-decimal precision)")
        if int(graph_vals["model_i"]) != rec["model_i"]:
            raise Refuse(f"{slug}: slot{slot} model index drift: engine "
                         f"{rec['model_i']} vs graphs {graph_vals['model_i']}")
        if rec["model_i"] not in SSE_MODELS:
            raise Refuse(
                f"{slug}: Distortion slot {f['r']} uses FX model "
                f"{rec['model_i']} ({FXWS_NAMES[rec['model_i']]}), which is "
                "the SXT-028e (#57) table branch, not this leaf's SSE branch")
        saved_rev, flags = _loader_normalized_flags(s, slot, tmpdir)
        saved_revs.append(saved_rev)
        _cross_check_flags(s, patch, slot, raw_rev, xml_flags, flags)
        rec.update(flags)
        slots.append({"routing": f["r"], "slot_index": slot,
                      "fx_model_index": rec["model_i"],
                      "quad_waveshaper": SSE_SHAPER_OF[rec["model_i"]],
                      "params": rec})
    got_models = sorted({x["fx_model_index"] for x in slots})
    if expect_model is not None and expect_model not in got_models:
        raise Refuse(f"{slug}: expected FX model {expect_model}, "
                     f"engine has {got_models}")

    screens = _render_screens(s, patch, d, path)
    chain, _unl = _chain_models(s, patch, d, slots, landed)

    out = {
        "schema_version": 2,
        "leaf": LEAF,
        "slug": slug,
        "preset_path": path,
        "census_blob_sha1": sha,
        "extraction_mode": "oracle",
        "extraction_status": "COMPLETE",
        "source": "the pinned engine's own loader, via surgepy at "
                  "ORACLE_SURGE_DIR (engine pin surge-synthesizer/surge@"
                  "58914e59c608ed4384ba6002e44c3465c58b2e71, 48 kHz, block "
                  "32); parameter values via getParamVal, the five "
                  "oracle-only flags from the loader's normalized state via "
                  "a savePatch round-trip",
        "unresolved_fields": [],
        "oracle_extraction": {
            "flags_source": "savePatch round-trip of the loaded patch — the "
                            "loader's NORMALIZED state at the engine's "
                            "current streaming revision, every documented "
                            "handleStreamingMismatches migration already "
                            "applied. Raw .fxp values are pre-migration and "
                            "are NOT authoritative (CLAUDE.md).",
            "raw_fxp_revision": raw_rev,
            "roundtrip_revision": sorted(set(saved_revs)),
            "cross_checks": [
                "live getExtend getter == normalized state (3 extend flags)",
                "raw pre-migration .fxp attribute + documented "
                "handleStreamingMismatches rule == normalized state (all 5)",
                "12 engine parameter values == the committed SXT-011 "
                "graphs.jsonl normalized export (drift == 0)",
                "engine FX slot types == graphs.jsonl FX slot types",
                "census blob SHA-1 re-verified against the file on the "
                "oracle host",
            ],
            "no_getter_note": "surgepy exposes no getDeactivated; the "
                              "round-trip is used precisely so the migration "
                              "rule is READ from the engine rather than "
                              "re-implemented here.",
        },
        "render_screens": screens,
        "chain": [{"routing": f["r"], "type": f["tn"], "slot_index": f["i"]}
                  for f in active],
        "chain_models": chain,
        "unlanded_classes_in_chain": unlanded,
        "landed_classes_basis": {
            "source": "reports/coverage-v1/leaf-verification.json "
                      "(leaves[*].landed)",
            "landed_fx_classes": sorted(landed - {"Off"}),
            "note": "derived at extraction time, not hand-listed; a class "
                    "whose leaf is not marked landed in the committed table "
                    "counts as unlanded even if its PR has merged",
        },
        "complete_wet_render_possible": not unlanded,
        "distortion_slots": slots,
        "claim_scope": "control-plane export + measured render-admissibility "
                       "screens; no support, fidelity or musical-quality "
                       "claim. A populated record permits a model run; it "
                       "does not assert that one agreed with the engine.",
    }
    del s
    return out


SYNTHETIC_OUTDIR = os.path.join(REPO, "reports", "SXT-028e-sse", "artifacts",
                                "synthetic")


def extract_synthetic(slug):
    """DECLARED SYNTHETIC carrier record (issue #136), read back from the engine.

    These records are written under `reports/SXT-028e-sse/artifacts/synthetic/`
    and NOT under `model/effects/fx_inputs/` on purpose: `fx_inputs` holds
    corpus-derived control-plane records, and a synthetic carrier is evidence
    about the engine, not an inventory of the corpus. See
    `tools/distortion_sse_synthetic.py` for the construction and for why the
    corpus carriers cannot serve here.
    """
    sys.path.insert(0, os.path.join(REPO, "oracle"))
    sys.path.insert(0, os.path.join(REPO, "tools"))
    try:
        import oracle_common as oc
    except ImportError as e:
        raise Refuse(f"oracle harness unavailable: {e}")
    try:
        surgepy = oc.import_surgepy()
    except Exception as e:                            # noqa: BLE001
        raise Refuse(f"no built surgepy at ORACLE_SURGE_DIR "
                     f"({oc.engine_dir()}): {type(e).__name__}: {e}")
    oc.apply_engine_env()
    import distortion_sse_synthetic as syn

    if slug not in syn.CARRIERS:
        raise Refuse(f"unknown synthetic carrier {slug!r}")
    model_i = syn.CARRIERS[slug]["model"]
    slots_wanted = syn.carrier_slots(slug)
    base_abs = os.path.join(oc.engine_dir(), syn.SYN_BASE)
    if not os.path.exists(base_abs):
        raise Refuse(f"synthetic base patch absent: {base_abs}")
    on_disk = oc.git_blob_sha1(base_abs)
    if on_disk != syn.SYN_BASE_CENSUS_SHA1:
        raise Refuse(f"synthetic base blob drift: census "
                     f"{syn.SYN_BASE_CENSUS_SHA1}, on disk {on_disk}")

    s = surgepy.createSurge(48000.0)
    if not s.loadPatch(base_abs):
        raise Refuse(f"loadPatch failed: {base_abs}")
    s.pitchBend(0, 0)
    s.channelController(0, 64, 0)
    s.channelController(0, 1, 0)
    s.channelController(0, 11, 0)
    s.channelAftertouch(0, 0)
    s.allNotesOff()
    settle_blocks = int(0.25 * 48000) // int(s.getBlockSize())
    try:
        rb = syn.construct(s, slug, slots_wanted, settle_blocks)
    except syn.SyntheticRefused as e:
        raise Refuse(f"{slug}: synthetic construction refused: {e}")

    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="sxt028e-sse-syn-")
    slots = []
    for slot in slots_wanted:
        info = rb["slots"][str(slot)]
        _rev, flags = _loader_normalized_flags(s, slot, tmpdir)
        params = dict(info["params"])
        params.update(flags)
        # the constructed state must satisfy the frozen model's own
        # fail-closed admission before this record is written
        sys.path.insert(0, os.path.join(REPO, "model", "effects",
                                        "type-distortion-sse"))
        from distortion_sse_model import DistortionSSEParams
        DistortionSSEParams(params)
        slots.append({"routing": info["role"], "slot_index": slot,
                      "fx_model_index": model_i,
                      "quad_waveshaper": info["quad_waveshaper"],
                      "params": params,
                      "return_f": info["return_f"]})

    chain = {"ains": [], "sends": [], "globals": [],
             "volume_f": rb["volume_f"],
             "scene_sends_f": [[rb["send1_level_f"], 0.0], [0.0, 0.0]],
             "tempo_bpm": 120.0}
    for sl in slots:
        entry = {"slot": sl["slot_index"], "role": sl["routing"],
                 "type": "distortion-sse", "params": sl["params"]}
        if sl["routing"].startswith("ains"):
            chain["ains"].append(entry)
        else:
            entry["send_slot"] = int(sl["routing"][-1]) - 1
            entry["send_gain_f"] = rb["send1_level_f"]
            entry["return_f"] = sl["return_f"]
            chain["sends"].append(entry)

    out = {
        "schema_version": 1,
        "leaf": LEAF,
        "slug": slug,
        "carrier_kind": "DECLARED-SYNTHETIC",
        "declaration": syn.DECLARATION,
        "corpus_reach": "NONE — this carrier is not a corpus preset. The "
                        "committed corpus histogram for active Distortion "
                        "slots is unchanged by it and no support claim "
                        "follows from any number measured on it.",
        "fx_model_index": model_i,
        "quad_waveshaper": SSE_SHAPER_OF[model_i],
        "fxws_name": FXWS_NAMES[model_i],
        "base_patch": syn.SYN_BASE,
        "base_patch_census_blob_sha1": syn.SYN_BASE_CENSUS_SHA1,
        "extraction_mode": "oracle-synthetic",
        "extraction_status": "COMPLETE",
        "unresolved_fields": [],
        "construction": {
            "active_slots": list(slots_wanted),
            "fixture_legs": list(syn.carrier_legs(slug)),
            "send1_level_f": rb["send1_level_f"],
            "volume_f": rb["volume_f"],
            "fx_types_readback": rb["fx_types"],
            "settle_blocks": settle_blocks,
            "settle_note": "1 FX-rebuild block + (settle_blocks - 1) settle "
                           "blocks; total settle unchanged at 0.25 s",
            "flags_source": "savePatch round-trip of the CONSTRUCTED patch "
                            "(the loader's normalized state), same reader as "
                            "the corpus carriers",
        },
        "chain_models": chain,
        "distortion_slots": slots,
        "complete_wet_render_possible": True,
        "claim_scope": "model-vs-pinned-engine numeric instrument only; no "
                       "corpus reach, no support claim, no musical-quality "
                       "claim.",
    }
    del s
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("oracle", "graphs", "synthetic"),
                    default="oracle")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--refusals", default=None)
    args = ap.parse_args()
    if args.outdir is None:
        args.outdir = SYNTHETIC_OUTDIR if args.mode == "synthetic" else OUTDIR
    if args.refusals is None:
        args.refusals = os.path.join(
            REPO, "reports", "SXT-028e-sse", "artifacts",
            f"extract-refusals-{args.mode}.txt")

    os.makedirs(args.outdir, exist_ok=True)
    os.makedirs(os.path.dirname(args.refusals), exist_ok=True)
    refusals = []
    written = []
    if args.mode == "synthetic":
        import distortion_sse_synthetic as syn  # noqa: PLC0415
        for slug in sorted(syn.CARRIERS):
            model = syn.CARRIERS[slug]["model"]
            try:
                rec = extract_synthetic(slug)
            except Refuse as e:
                refusals.append(f"REFUSED {slug} (synthetic model {model}): {e}")
                print("REFUSED", slug, "-", e)
                continue
            out = os.path.join(args.outdir,
                               f"type-distortion-sse-{slug}.json")
            with open(out, "w") as f:
                json.dump(rec, f, indent=2, sort_keys=True)
                f.write("\n")
            written.append(out)
            print("wrote", os.path.relpath(out, REPO),
                  f"({rec['extraction_status']}, DECLARED-SYNTHETIC)")
        header = (f"{LEAF} extraction transcript — mode=synthetic\n"
                  f"engine pin surge-synthesizer/surge@"
                  f"58914e59c608ed4384ba6002e44c3465c58b2e71\n"
                  "DECLARED SYNTHETIC carriers; no corpus reach\n"
                  f"written: {len(written)}  refused: {len(refusals)}\n\n")
        with open(args.refusals, "w") as f:
            f.write(header + "\n".join(refusals) + ("\n" if refusals else ""))
        return 0
    for slug, (path, sha, model) in sorted(PRESETS.items()):
        try:
            if args.mode == "oracle":
                rec = extract_oracle(slug, path, sha, model)
            else:
                rec = extract_graphs(slug, path, sha, model)
        except Refuse as e:
            refusals.append(f"REFUSED {slug} ({path}): {e}")
            print("REFUSED", slug, "-", e)
            continue
        out = os.path.join(args.outdir, f"type-distortion-sse-{slug}.json")
        with open(out, "w") as f:
            json.dump(rec, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out)
        print("wrote", os.path.relpath(out, REPO),
              f"({rec['extraction_status']})")
    for mi in NO_CARRIER_MODELS:
        refusals.append(
            f"NO-CARRIER model {mi} ({FXWS_NAMES[mi]}, {SSE_SHAPER_OF[mi]}): "
            "zero active Distortion slots in corpus/normalized/graphs.jsonl "
            "use this FX model. The algorithm is implemented and exercised by "
            "synthetic corners; no fixture record exists and none is invented.")
        print("NO-CARRIER model", mi, FXWS_NAMES[mi])
    header = (f"{LEAF} extraction transcript — mode={args.mode}\n"
              f"engine pin surge-synthesizer/surge@"
              f"58914e59c608ed4384ba6002e44c3465c58b2e71\n"
              f"written: {len(written)}  refused/no-carrier: {len(refusals)}\n\n")
    with open(args.refusals, "w") as f:
        f.write(header + "\n".join(refusals) + ("\n" if refusals else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
