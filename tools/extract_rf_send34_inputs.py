#!/usr/bin/env python3
"""SXT-028l: fail-closed extraction of routing-form (Send buses 3-4, the
extended rack half) carrier metadata from the pinned engine's committed
corpus artifacts.

For each carrier preset this tool:
  1. re-verifies the census blob sha1 (corpus/census-v0.1/results/
     per-preset.csv) against the declared sha1, REFUSING on mismatch;
  2. cross-checks the normalized corpus graph (corpus/normalized/graphs.jsonl,
     SXT-011 output -- already surgepy-derived and committed, so no live
     oracle call is needed for this step) for the send3/send4 slot roles:
     occupancy (on/off), FX type name/id, the stored per-slot return_level
     (which this routing form REALLY DOES consume, unlike the insert/global
     forms), and the patch-level fxb (fx_bypass) / fxd (fx_disable) fields;
  3. records the scene context (scene mode; whether scene B is instantiated
     at all) because each send bus sums BOTH scenes' post-insert outputs, and
     the base-half context (send1/send2 occupancy) because those buses are
     co-tenants of the same main bus -- this leaf's declared seam;
  4. REFUSES to emit any per-scene send LEVEL for buses 3/4. That is the
     documented SXT-011 exposure gap (corpus/normalized/README.md "Send
     levels 3/4"; corpus/normalized/schema.json `scene.send`): a `.fxp`
     stores only two per-scene send levels and the surgepy binding exposes
     only `send_level[0..1]`, so buses 3/4 run at LOADER DEFAULTS for every
     corpus preset and no in-repo artifact carries a value. The gap is
     written into every record as `send_level_gap` with `stored: null` --
     never a fabricated default -- and is re-verified mechanically here (the
     committed corpus really does carry exactly two send levels per scene,
     never four). Fixture freezing for this routing form is therefore gated
     on the SXT-017 data-gap policy decision (#12);
  5. asserts ZERO DRIFT between the two independently-derived committed
     artifacts (census CSV vs normalized graph) on every field both carry:
     blob sha1, stored revision, scene mode, fx_bypass, fx_disable, the
     non-off FX slot count and the non-off FX type set. Any disagreement is a
     REFUSAL, never a silently-preferred source;
  6. runs a LIVE surgepy leg (#155 item 1a) against the pinned engine: it
     verifies the engine version really carries the pinned commit, re-verifies
     the `.fxp` blob sha1 inside the pinned checkout, `loadPatch()`es the
     preset, extracts the per-slot algorithm's own parameter values and
     `return_level` for send3/send4 from the NORMALIZED (post-loader) state,
     cross-checks every one of them against the committed graph, and runs the
     engine-side per-scene drift determinism gate (drift == 0 in every voicing
     scene, recorded as a PASS/FAIL verdict). It also re-verifies the SHAPE of
     the SXT-011 exposure gap live -- the binding still exposes exactly two
     per-scene send levels -- which until now was documented only. It
     deliberately does NOT probe the loader-default send LEVEL for buses 3/4:
     that probe is the SXT-017 data-gap decision's own input (#12) and stays
     BLOCKED. If the pinned oracle is unavailable in the current environment
     the leg is recorded NOT_RUN (never silently dropped, never fabricated as
     a pass) and the routing-verification checks above still proceed and are
     still written to the output record. A live engine that CONTRADICTS the
     committed artifacts is a REFUSAL, not a downgrade to "unavailable".

CARRIER SET. The first three carriers are the B4-scope presets named by the
issue (reports/sxt-028/leaves/SXT-028l.json `carriers.top_presets`). Unlike
the sibling global-rack leaf, one of them (`Batbrass.fxp`) really does occupy
BOTH send buses, so the issue's own carriers do reach the two-concurrent-
instance shape. Three further carriers are added from the same committed
corpus for routing SHAPES the acceptance checklist needs, verified by the
identical fail-closed path:
  * Strynth.fxp -- the SAME FX class (Nimbus) in BOTH send3 and send4 AND a
    Dual scene mode, i.e. the same-class dual-instance shape with scene B
    actually contributing to both buses.
  * Closeout Sale @ Electro Percussion Warehouse.fxp -- both slots occupied
    AND fx_disable = 13107, whose bits 12 and 13 are BOTH set: the
    real-corpus instance of this leaf's own per-slot disable gate.
  * Random Bass FX.fxp -- both slots occupied with return_level 0.0 on BOTH:
    the return-muted shape, which only exists because this routing form
    consumes `return_level` at all.
  * Violin Section.fxp (John Valentine) -- added by #322: the SAME FX class
    (EQ) in both send3 and send4 AND a Dual scene mode, i.e. the same routing
    shape as Strynth.fxp, but with per-scene drift 0 in both voicing scenes.
    Strynth.fxp fails the engine-side drift determinism gate (#155 item 1a),
    so it cannot carry a repeatable render; it is KEPT in this set as the
    non-render-eligible same-class carrier (the finding must survive), and
    this carrier is the same-class shape's render carrier once #12 clears.
    Selected by tools/screen_rf_send34_same_class.py, which screens every
    same-class dual-occupant corpus preset through `drift_gate()` below.
The additions are recorded as such (`carrier_source`), never presented as
issue-named carriers.

Writes model/effects/fx_inputs/rf-rf-send34-<slug>.json plus
reports/SXT-028l/artifacts/{extract-refusals.txt, corpus-occupancy.json,
send-level-gap.json} (the refusal transcript is created even when empty,
matching the SXT-023/028c/028d/028h/028j refusal-log convention -- absence of
oracle coverage is recorded, never silently dropped), and -- only when the
live leg actually ran -- reports/SXT-028l/artifacts/live-oracle-extraction.json.
Exit codes: 0 clean; 1 a carrier record could not be produced (see the refusal
transcript); 3 the live leg ran and recorded a determinism-gate FAIL (the
records are complete, but at least one carrier is not render-eligible).
That file is an oracle host's evidence, so a run in an environment WITHOUT the
oracle leaves it untouched instead of overwriting it with its own NOT_RUN
measurement; the absence is recorded per carrier and by
tools/rf_send34_oracle_status.py.

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only, and only for the item-6 attempt.
"""

import csv
import json
import os
import platform
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import _census_graphs_common as cgc  # noqa: E402
from refusal import Refuse  # noqa: E402

# SurgeStorage.h fxslot_positions (re-derivable from
# tools/export_normalized_graphs.py FX_ROLES / corpus/normalized/graphs.jsonl)
FXSLOT_SEND1, FXSLOT_SEND2 = 4, 5
FXSLOT_SEND3, FXSLOT_SEND4 = 12, 13

# The engine has four send buses; a .fxp stores (and surgepy exposes) only the
# first two per-scene send levels. Asserted mechanically against the committed
# corpus by `send_level_gap_scan()`.
N_SEND_SLOTS = 4
N_SEND_LEVELS_EXPOSED = 2

# Live-oracle leg (#155 item 1a). The pin is the single source of truth for
# which engine the live leg is allowed to talk to (oracle/manifest.json).
ENGINE_PIN = "58914e59c608ed4384ba6002e44c3465c58b2e71"
SAMPLE_RATE = 48000.0
# graphs.jsonl stores float parameter values rounded to 6 decimals; the same
# tolerance the landed SXT-028b extractor uses for its surgepy cross-check.
GRAPHS_VALUE_TOL = 5e-6

SEND_LEVEL_GAP_REASON = (
    "SXT-011 exposure gap: the engine has 4 send buses but a .fxp stores only "
    "2 per-scene send levels and surgepy exposes only send_level[0..1] "
    "(corpus/normalized/README.md 'Send levels 3/4'; "
    "corpus/normalized/schema.json scene.send). Buses 3/4 run at LOADER "
    "DEFAULTS for every corpus preset; no in-repo artifact carries a value, "
    "so none is emitted here. Resolving it needs an engine-behavior probe of "
    "the loader default plus an SXT-017 data-gap policy decision (#12) before "
    "reference fixtures for this routing form can be frozen."
)

CARRIERS = [
    # --- the three B4-scope carriers named by issue #64 / SXT-028l.json ---
    {"slug": "trance",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Basses/Trance.fxp",
     "declared_sha1": "c277c51ec0094a57c5fc219b3763db3801d7869e",
     "carrier_source": "issue-named B4-scope carrier"},
    {"slug": "batbrass",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Brass/Batbrass.fxp",
     "declared_sha1": "e6b6f04bea58347fe3b999bc8ba19a0f7a36febf",
     "carrier_source": "issue-named B4-scope carrier"},
    {"slug": "dystopia",
     "path": "resources/data/patches_3rdparty/Exquis MPE/FX/Dystopia.fxp",
     "declared_sha1": "f884c4d1c866fdb2c50ec8bf67cf8c5345156f7d",
     "carrier_source": "issue-named B4-scope carrier"},
    # --- shape carriers added by this leaf (see module docstring) ---
    {"slug": "strynth",
     "path": "resources/data/patches_3rdparty/Exquis MPE/Strings/Strynth.fxp",
     "declared_sha1": "f8c9666992e671d8ee5761d76867890c4c75c4ce",
     "carrier_source": "added by this leaf: SAME FX class (Nimbus) in both "
                       "send3 and send4 AND a Dual scene mode (scene B "
                       "really feeds both buses)"},
    {"slug": "closeout-sale",
     "path": "resources/data/patches_3rdparty/Kinsey Dulcet/Percussion/"
             "Closeout Sale @ Electro Percussion Warehouse.fxp",
     "declared_sha1": "e9238ad6f88e416d7db31c83af85b802fbc7e75b",
     "carrier_source": "added by this leaf: both slots occupied AND both "
                       "disabled by fx_disable bits 12|13 (mask 13107)"},
    {"slug": "random-bass-fx",
     "path": "resources/data/patches_3rdparty/Slowboat/FX/Random Bass FX.fxp",
     "declared_sha1": "e0b6b1d01a6dd1f696823056067bc3625e791075",
     "carrier_source": "added by this leaf: both slots occupied with "
                       "return_level 0.0 on BOTH (the return-muted shape; "
                       "this routing form is the one that consumes "
                       "return_level)"},
    {"slug": "violin-section",
     "path": "resources/data/patches_3rdparty/John Valentine/Strings/"
             "Violin Section.fxp",
     "declared_sha1": "8b63179855d865563a88516214874ba40fb299d8",
     "carrier_source": "added by this leaf (#322): SAME FX class (EQ) in "
                       "both send3 and send4 AND a Dual scene mode (scene B "
                       "really feeds "
                       "both buses) with per-scene drift 0 -- the drift-0 "
                       "render carrier for the same-class dual-instance "
                       "shape, because Strynth.fxp fails the drift gate "
                       "(reports/SXT-028l/artifacts/"
                       "same-class-carrier-screen.json)"},
]

# The routing SHAPE #322 restores render coverage for (the corpus predicate
# reports/SXT-028l/artifacts/corpus-occupancy.json already counts as
# `both_buses_occupied_same_fx_class`).
SAME_CLASS_SHAPE = ("same-FX-class dual-instance: send3.on && send4.on && "
                    "send3.tn == send4.tn")

CENSUS_CSV = os.path.join(REPO, "corpus", "census-v0.1", "results",
                          "per-preset.csv")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
OUT_DIR = os.path.join(REPO, "model", "effects", "fx_inputs")
ARTIFACTS = os.path.join(REPO, "reports", "SXT-028l", "artifacts")
REFUSALS = os.path.join(ARTIFACTS, "extract-refusals.txt")
OCCUPANCY = os.path.join(ARTIFACTS, "corpus-occupancy.json")
GAP = os.path.join(ARTIFACTS, "send-level-gap.json")
LIVE_LEG = os.path.join(ARTIFACTS, "live-oracle-extraction.json")


def census_row(rel_path):
    with open(CENSUS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] == rel_path:
                return row
    raise Refuse(f"preset not in census: {rel_path}")


def graphs_entry(rel_path):
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            if g.get("p") == rel_path:
                return g
    raise Refuse(f"preset not in graphs.jsonl: {rel_path}")


def slot_entry(graph, slot_role):
    for fx in graph["g"]["fx"]:
        if fx.get("r") == slot_role:
            return fx
    raise Refuse(f"no {slot_role} entry in graphs.jsonl fx list")


# The census-vs-graphs zero-drift comparison lives in ONE place for all the
# routing-form extractors (tools/_census_graphs_common.py, issue #154): the
# graph's stored FX type IDS are named through the census parser's own
# committed FX table, so the check compares CONTENT rather than the two
# artifacts' differing spellings ("FrequencyShifter" vs "Freq Shift"). These
# thin wrappers keep this module's local `Refuse` as the refusal type.
def census_fx_table():
    return cgc.census_fx_table()


def norm_type_name(name):
    return cgc.norm_type_name(name)


def cross_check(row, graph):
    """Zero-drift assertion between the two committed artifacts. Returns the
    per-field comparison record; raises Refuse on ANY disagreement."""
    return cgc.cross_check(row, graph, refuse=Refuse)


def role_index_check(graph):
    """Re-derive this leaf's slot indices from the committed corpus role
    table itself (no live oracle). REFUSES if the record disagrees with the
    frozen model's FXSLOT_SEND3/4 (or the base half's 4/5)."""
    roles = {fx.get("i"): fx.get("r") for fx in graph["g"]["fx"]}
    expect = {FXSLOT_SEND1: "send1", FXSLOT_SEND2: "send2",
              FXSLOT_SEND3: "send3", FXSLOT_SEND4: "send4"}
    bad = {i: (roles.get(i), r) for i, r in expect.items() if roles.get(i) != r}
    if bad:
        raise Refuse(f"graphs.jsonl slot-index/role table disagrees with the "
                     f"frozen model's fxslot constants: {bad}")
    return {"verified_indices": {str(i): r for i, r in expect.items()},
            "source": "corpus/normalized/graphs.jsonl fx[].i / fx[].r "
                      "(SXT-011 output; no live oracle needed)"}


def send_level_check(graph):
    """Fail-closed send-level record for ONE preset. The exposed per-scene
    levels (buses 1/2) are recorded as context; buses 3/4 get `null` plus the
    documented gap reason. REFUSES if a record ever carries more than the
    documented two levels per scene (that would mean the gap has been closed
    upstream and this leaf's contract must be revisited, not silently
    reinterpreted)."""
    per_scene = []
    for sc in graph["g"]["sc"]:
        levels = sc.get("send")
        if levels is None:
            raise Refuse("scene record carries no `send` array")
        if len(levels) != N_SEND_LEVELS_EXPOSED:
            raise Refuse(
                f"scene record carries {len(levels)} send levels, expected "
                f"{N_SEND_LEVELS_EXPOSED}: the SXT-011 exposure gap this "
                f"leaf's contract is built on may have changed upstream -- "
                f"refusing rather than reinterpreting")
        per_scene.append(levels)
    return {
        "exposed_levels_per_scene": per_scene,
        "exposed_bus_indices": [1, 2],
        "send3_send4_levels_stored": None,
        "reason": SEND_LEVEL_GAP_REASON,
        "blocking_issue": "#12 (SXT-017 data-gap policy decision)",
        "consumed_by_this_leaf_as": "control-plane stimulus only "
                                    "(model/effects/rf-rf-send34: "
                                    "send_gain_a / send_gain_b); never "
                                    "derived from a corpus record",
    }


def _param_record(s, p, graphs_value):
    """One live parameter row, cross-checked against the committed graph.

    `graphs.jsonl` stores int/bool params as ints and float params rounded to
    6 decimals (tools/export_normalized_graphs.py `val`/`valf`), so the
    comparison is made in the graph's own representation. A disagreement is a
    REFUSAL: the committed corpus artifact and the live pinned engine must not
    be allowed to drift silently."""
    vtype = s.getParamValType(p)
    raw = float(s.getParamVal(p))
    live = int(round(raw)) if vtype in ("int", "bool") else round(raw, 6)
    if vtype in ("int", "bool"):
        agrees = int(live) == int(graphs_value)
    else:
        agrees = abs(float(live) - float(graphs_value)) <= GRAPHS_VALUE_TOL
    if not agrees:
        raise Refuse(f"live surgepy value for {p.getName()} ({live}) "
                     f"disagrees with corpus/normalized/graphs.jsonl "
                     f"({graphs_value}); refusing rather than preferring one "
                     f"artifact over the pinned engine")
    return {"name": p.getName(), "value": live, "value_type": vtype,
            "display": s.getParamDisplay(p),
            "graphs_value": graphs_value}


def drift_gate(s, patch):
    """The engine-side per-scene drift determinism gate, read from a LOADED
    pinned-engine instance (`s.loadPatch()` already done; `patch` is
    `s.getPatch()`), i.e. from the native loader's normalized state, never the
    raw `.fxp`.

    Scene `drift` adds per-voice randomness (the harness never seeds engine RNG
    -- oracle/manifest.json "randomness"), so a nonzero value in any VOICING
    scene makes every render of the preset non-repeatable. Voicing scenes: the
    active scene in Single mode, both scenes otherwise.

    The ONE implementation used both by this extractor's live leg and by
    tools/screen_rf_send34_same_class.py (#322), so a candidate replacement
    carrier is screened exactly the way the committed carriers are.

    Scope: drift == 0 is a NECESSARY condition for a repeatable render, not a
    sufficient one. Other engine RNG paths (free-running oscillator phase,
    RNG-driven FX classes -- fixtures/README.md, oracle/manifest.json
    `fx_modulation_randomness`, #310) are only caught by an empirical repeated
    render, which is the render leg's job (BLOCKED on #12 here)."""
    scene_mode = int(round(s.getParamVal(patch["scenemode"])))
    scene_active = int(round(s.getParamVal(patch["scene_active"])))
    voicing = [scene_active] if scene_mode == 0 else [0, 1]
    drifts = {"AB"[i]: round(float(s.getParamVal(patch["scene"][i]["drift"])), 9)
              for i in voicing}
    gate_ok = all(v == 0.0 for v in drifts.values())
    return {
        "what": "engine-side per-scene drift must be 0 in every voicing "
                "scene, or no render of this carrier is repeatable",
        "scene_mode_id": scene_mode,
        "scene_active": scene_active,
        "voicing_scenes": ["AB"[i] for i in voicing],
        "drift_per_voicing_scene": drifts,
        "status": "PASS" if gate_ok else "FAIL",
    }


def live_oracle_extraction(carrier, graph):
    """LIVE surgepy leg (#155 item 1a): extract the per-slot algorithm's own
    parameter values for send3/send4 from the pinned engine's normalized
    (post-`loadPatch`) state, and run the engine-side per-scene drift
    determinism gate.

    Returns `(ok, summary_string, record_or_None)`:
      * `ok` False with a reason string when the pinned oracle is not
        installed in this environment -- the leg is then NOT_RUN and the
        oracle-free routing checks above still stand on their own;
      * `ok` True with a record when the leg actually ran. The record carries
        its own `determinism_gate.status`, which is PASS only when every
        voicing scene really reported drift 0.0 -- a nonzero drift is recorded
        as FAIL, never absorbed.

    SCOPE. This is an ENGINE-SIDE extraction and determinism gate. It is NOT a
    model-vs-pinned-engine agreement number (leg 1c, which needs reference
    fixtures and is BLOCKED on #12) and NOT an RTL claim. It deliberately does
    NOT probe the loader-default send levels for buses 3/4: that probe is the
    SXT-017 data-gap decision's own input (#12) and stays BLOCKED. What it DOES
    check live is the *shape* of the gap -- that the binding still exposes
    exactly two per-scene send levels -- which until now was only documented.

    A contradiction between the live engine and the committed corpus artifacts
    (blob sha1, fx type vector, per-slot parameter values, return level, send
    level count) is a REFUSAL, never a downgrade to "oracle unavailable"."""
    rel = carrier["path"]
    try:
        import oracle_common as oc  # noqa: PLC0415
    except Exception as e:  # pragma: no cover - environment-dependent
        return False, f"oracle_common import failed: {e}", None
    try:
        surgepy = oc.import_surgepy()
    except Exception as e:
        return False, (f"surgepy unavailable (pinned oracle not built or not "
                       f"installed in this environment): {e}"), None
    oc.apply_engine_env()

    version = surgepy.getVersion()
    if ENGINE_PIN[:9] not in version:
        raise Refuse(f"live surgepy reports engine version {version!r}, which "
                     f"does not carry the pinned commit {ENGINE_PIN[:9]} "
                     f"(oracle/manifest.json); refusing to extract against an "
                     f"unpinned engine")

    abs_path = os.path.join(oc.engine_dir(), rel)
    if not os.path.exists(abs_path):
        return False, (f"pinned engine checkout {oc.engine_dir()} does not "
                       f"carry {rel}"), None
    on_disk_sha1 = oc.git_blob_sha1(abs_path)
    if on_disk_sha1 != carrier["declared_sha1"]:
        raise Refuse(f"pinned-checkout blob sha1 mismatch for {rel}: "
                     f"on disk={on_disk_sha1} "
                     f"declared={carrier['declared_sha1']}")

    s = surgepy.createSurge(SAMPLE_RATE)
    if not s.loadPatch(abs_path):
        raise Refuse(f"loadPatch failed in the pinned engine: {rel}")
    patch = s.getPatch()

    # --- engine-side per-scene drift determinism gate -------------------
    # Scene `drift` adds per-voice randomness, so a nonzero value makes any
    # render of this carrier non-repeatable. Recorded as a verdict (PASS/FAIL)
    # rather than a refusal: it bounds the RENDER legs (1b/1c), not the
    # routing metadata above.
    gate = drift_gate(s, patch)

    # --- live re-verification of the SXT-011 send-level exposure SHAPE ---
    exposed = [len(patch["scene"][i]["send_level"]) for i in range(2)]
    if exposed != [N_SEND_LEVELS_EXPOSED] * 2:
        raise Refuse(f"the live surgepy binding exposes {exposed} per-scene "
                     f"send levels, not {N_SEND_LEVELS_EXPOSED}: the SXT-011 "
                     f"exposure gap this leaf's contract is built on has "
                     f"changed -- refusing rather than reinterpreting")

    # --- fx type vector: live engine vs committed graph -----------------
    live_types = [int(round(s.getParamVal(patch["fx"][i]["type"])))
                  for i in range(len(graph["g"]["fx"]))]
    graph_types = [fx.get("t", 0) for fx in graph["g"]["fx"]]
    if live_types != graph_types:
        raise Refuse(f"live fx type vector disagrees with graphs.jsonl for "
                     f"{rel}: engine={live_types} graphs={graph_types}")

    # --- per-slot algorithm parameters for THIS leaf's two slots --------
    slots = {}
    for role, slot in (("send3", FXSLOT_SEND3), ("send4", FXSLOT_SEND4)):
        gfx = slot_entry(graph, role)
        fx = patch["fx"][slot]
        occupied = bool(gfx.get("on", 0))
        rec = {"slot": slot,
               "occupied": occupied,
               "type_id": int(round(s.getParamVal(fx["type"]))),
               "type_display": s.getParamDisplay(fx["type"])}
        if not occupied:
            rec["params"] = None
            rec["return_level"] = None
            rec["note"] = ("slot is off in the normalized state; the engine "
                           "exposes no algorithm parameters to extract")
            slots[role] = rec
            continue
        gp = gfx.get("p")
        if gp is None or len(gp) != len(fx["p"]):
            raise Refuse(f"graphs.jsonl {role} parameter vector has "
                         f"{None if gp is None else len(gp)} entries, engine "
                         f"exposes {len(fx['p'])}")
        rec["params"] = [_param_record(s, p, gp[j])
                         for j, p in enumerate(fx["p"])]
        rl_live = round(float(s.getParamVal(fx["return_level"])), 6)
        if abs(rl_live - float(gfx["rl"])) > GRAPHS_VALUE_TOL:
            raise Refuse(f"live {role} return_level {rl_live} disagrees with "
                         f"graphs.jsonl {gfx['rl']}")
        rec["return_level"] = rl_live
        slots[role] = rec

    record = {
        "ran": True,
        "engine": {"pin": ENGINE_PIN, "surgepy_version": version,
                   "surgepy_module": surgepy.__file__,
                   "sample_rate": s.getSampleRate(),
                   "block_size": s.getBlockSize(),
                   "oracle_surge_dir": oc.engine_dir()},
        "preset_blob_sha1_on_disk": on_disk_sha1,
        "determinism_gate": gate,
        "send_level_exposure_recheck": {
            "what": "live re-verification of the SXT-011 exposure gap's SHAPE "
                    "against the binding itself (previously documented only)",
            "levels_exposed_per_scene": exposed,
            "buses_3_4_value_read": False,
            "loader_default_probe": "BLOCKED (#12) -- deliberately not probed "
                                    "here; the default's semantics are the "
                                    "SXT-017 decision's own input",
        },
        "fx_type_vector_matches_graphs": True,
        "slots": slots,
        "claim_scope": "ENGINE-SIDE extraction + determinism gate only. NOT a "
                       "model-vs-pinned-engine agreement number (leg 1c, "
                       "BLOCKED on #12) and NOT an RTL claim.",
    }
    summary = (f"LIVE surgepy leg RAN against {version}: per-slot algorithm "
               f"parameters extracted for send3/send4 and cross-checked "
               f"against graphs.jsonl (drift gate "
               f"{record['determinism_gate']['status']}); the loader-default "
               f"send-level probe for buses 3/4 stays BLOCKED on #12")
    return True, summary, record


def extract_one(carrier):
    rel = carrier["path"]
    row = census_row(rel)
    if row["git_blob_sha1"] != carrier["declared_sha1"]:
        raise Refuse(f"census blob sha1 mismatch for {rel}: "
                     f"declared={carrier['declared_sha1']} "
                     f"census={row['git_blob_sha1']}")
    graph = graphs_entry(rel)
    if graph.get("sha") != carrier["declared_sha1"]:
        raise Refuse(f"graphs.jsonl blob sha1 mismatch for {rel}")
    if graph.get("st") != "normalized":
        raise Refuse(f"preset not normalized: {rel}")
    if row["content_verified"] != "True":
        raise Refuse(f"census content not verified: {rel}")

    xcheck = cross_check(row, graph)
    idx_check = role_index_check(graph)
    gap = send_level_check(graph)

    s3 = slot_entry(graph, "send3")
    s4 = slot_entry(graph, "send4")
    s1 = slot_entry(graph, "send1")
    s2 = slot_entry(graph, "send2")
    fxb = graph["g"]["fxb"]
    fxd = graph["g"]["fxd"]
    scene_mode_name = graph["g"].get("smn")
    scene_b_instantiated = scene_mode_name != "Single"

    oracle_ok, oracle_detail, oracle_live = live_oracle_extraction(carrier,
                                                                   graph)

    def slot_doc(fx, bit):
        return {"occupied": bool(fx.get("on", 0)),
                "type_name": fx.get("tn"),
                "type_id": fx.get("t"),
                "airwindows_sub_id": fx.get("aw"),
                "airwindows_sub_name": fx.get("awn"),
                "fx_disable_bit": bool((fxd >> bit) & 1),
                "return_level_stored": fx.get("rl"),
                "return_level_consumed_by_send_path": True,
                "return_muted": fx.get("rl") == 0.0 if fx.get("on", 0) else None}

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "routing_form": "rf-send34",
        "roles": ["send3", "send4"],
        "carrier_source": carrier["carrier_source"],
        "preset": {"path": rel, "bank": graph.get("b"),
                   "census_blob_sha1_verified": row["git_blob_sha1"],
                   "graphs_blob_sha1_verified": graph.get("sha"),
                   "census_status": row["status"],
                   "stored_revision": graph.get("rev")},
        "patch_level": {"fx_bypass": fxb,
                        "fx_bypass_name": graph["g"].get("fxbn"),
                        "fx_disable_mask": fxd,
                        "send_stage_runs_in_this_mode": fxb == 0},
        "scene_context": {
            "note": "each send bus sums BOTH scenes' post-insert outputs "
                    "through that scene's own send level; in Single scene "
                    "mode the engine never instantiates scene B, so only "
                    "scene A feeds the buses",
            "scene_mode": scene_mode_name,
            "scene_mode_id": graph["g"].get("sm"),
            "scene_b_instantiated": scene_b_instantiated,
        },
        "base_half_context": {
            "note": "send1/send2 are the BASE half of the same send rack. "
                    "They are not upstream of this leaf (the buses are "
                    "parallel) -- they are co-tenants of the same main bus, "
                    "so their returns are part of this leaf's `main_l`/"
                    "`main_r` stimulus. A sibling rf-send12-class leaf's "
                    "scope; no such leaf exists in this repository yet.",
            "send1_occupied": bool(s1.get("on", 0)),
            "send1_type_name": s1.get("tn"),
            "send2_occupied": bool(s2.get("on", 0)),
            "send2_type_name": s2.get("tn"),
            "base_half_slots_active": int(bool(s1.get("on", 0))) +
                                      int(bool(s2.get("on", 0))),
        },
        "send_level_gap": gap,
        "send3": slot_doc(s3, FXSLOT_SEND3),
        "send4": slot_doc(s4, FXSLOT_SEND4),
        "dual_instance_concurrent": bool(s3.get("on", 0)) and
                                    bool(s4.get("on", 0)),
        "same_class_both_buses": bool(s3.get("on", 0)) and
                                 bool(s4.get("on", 0)) and
                                 s3.get("tn") == s4.get("tn"),
        "both_slots_disabled": bool((fxd >> FXSLOT_SEND3) & 1) and
                               bool((fxd >> FXSLOT_SEND4) & 1),
        "cross_check": xcheck,
        "slot_index_check": idx_check,
        "applicability": {
            "routing_metadata_verified": True,
            "complete_wet_render_possible": False,
            "complete_wet_render_reason":
                "a wet-audio render needs BOTH the pinned oracle (surgepy, "
                "for the per-slot algorithm parameters -- see "
                "oracle_extraction) AND a per-scene send level for buses 3/4, "
                "which no artifact carries: fixture freezing for THIS routing "
                "form is gated on the SXT-017 send-level data-gap decision "
                "(#12), so this stays False even on an oracle host. This "
                "leaf's own routing/scheduling claims depend on neither -- "
                "see oracle_extraction and send_level_gap",
        },
        # `ok` False means the LIVE leg was NOT_RUN in this environment -- never
        # a pass. `live` carries the leg's own record when it did run.
        "oracle_extraction": {"attempted": True, "ok": oracle_ok,
                              "detail": oracle_detail,
                              "live": oracle_live},
    }
    return doc


def corpus_occupancy():
    """Corpus-wide occupancy scan for this leaf's two roles. COVERAGE
    accounting only -- it is not a support claim and says nothing about
    agreement (AGENTS.md: coverage is reported separately from agreement)."""
    total = 0
    s3_on = s4_on = both = same_class = 0
    dis3 = dis4 = dis_both = 0
    nonzero_bypass = 0
    dual_scene_with_occupant = 0
    zero_return = 0
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            total += 1
            fx = {e.get("r"): e for e in g["g"]["fx"]}
            a = bool(fx.get("send3", {}).get("on", 0))
            b = bool(fx.get("send4", {}).get("on", 0))
            fxd = g["g"].get("fxd", 0)
            s3_on += a
            s4_on += b
            if a and b:
                both += 1
                if fx["send3"].get("tn") == fx["send4"].get("tn"):
                    same_class += 1
            d3 = bool((fxd >> FXSLOT_SEND3) & 1)
            d4 = bool((fxd >> FXSLOT_SEND4) & 1)
            dis3 += d3
            dis4 += d4
            dis_both += d3 and d4
            if g["g"].get("fxb", 0) != 0 and (a or b):
                nonzero_bypass += 1
            if (a or b) and g["g"].get("smn") != "Single":
                dual_scene_with_occupant += 1
            if (a and fx["send3"].get("rl") == 0.0) or \
               (b and fx["send4"].get("rl") == 0.0):
                zero_return += 1
    return {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "source": "corpus/normalized/graphs.jsonl (SXT-011 output)",
        "claim_scope": "COVERAGE accounting only -- an inventory of which "
                       "corpus presets exercise this routing form's shapes. "
                       "NOT a support claim and NOT an agreement number.",
        "presets_scanned": total,
        "send3_occupied": s3_on,
        "send4_occupied": s4_on,
        "both_buses_occupied": both,
        "both_buses_occupied_same_fx_class": same_class,
        "fx_disable_bit12_set": dis3,
        "fx_disable_bit13_set": dis4,
        "fx_disable_both_bits_set": dis_both,
        "non_all_fx_bypass_with_a_send34_occupant": nonzero_bypass,
        "non_single_scene_mode_with_a_send34_occupant": dual_scene_with_occupant,
        "occupied_bus_with_return_level_zero": zero_return,
    }


def send_level_gap_scan():
    """Corpus-wide, mechanical re-verification of the SXT-011 send-level
    exposure gap this leaf's contract depends on: every scene record in the
    committed corpus carries exactly TWO per-scene send levels, never four.
    If that ever stops being true the gap has been closed upstream and this
    leaf's fixture contract must be revisited."""
    scenes = 0
    lengths = {}
    presets = 0
    with open(GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)["g"]
            presets += 1
            for sc in g["sc"]:
                scenes += 1
                n = len(sc.get("send", []))
                lengths[str(n)] = lengths.get(str(n), 0) + 1
    return {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "gap": "per-scene send levels for send buses 3/4 are not stored in "
               "any .fxp and are not exposed by surgepy",
        "reason": SEND_LEVEL_GAP_REASON,
        "engine_send_buses": N_SEND_SLOTS,
        "levels_exposed_per_scene": N_SEND_LEVELS_EXPOSED,
        "presets_scanned": presets,
        "scene_records_scanned": scenes,
        "send_array_length_histogram": lengths,
        "gap_holds_across_the_whole_corpus":
            list(lengths) == [str(N_SEND_LEVELS_EXPOSED)],
        "consequence": "this leaf consumes the per-scene send gains for buses "
                       "3/4 as CONTROL-PLANE STIMULUS and emits no corpus-"
                       "derived value; reference-fixture freezing for this "
                       "routing form is gated on the SXT-017 data-gap policy "
                       "decision (#12). The RTL-vs-frozen-model exactness "
                       "claim does not depend on the gap being closed.",
        "blocking_issue": "#12 (SXT-017)",
        "status": "BLOCKED (policy decision pending, #12) -- recorded, not "
                  "worked around",
    }


def same_class_coverage(docs, ran, gates):
    """#322: does the same-FX-class dual-instance routing shape have at least
    one carrier that can carry a REPEATABLE render once #12 clears?

    Derived from the per-carrier records and the measured gate verdicts, never
    asserted. Coverage (which carriers have the shape, which of those the live
    leg ran for) is kept apart from eligibility, and the render itself is
    BLOCKED on #12 either way -- an eligible carrier is not a rendered one,
    and the drift gate is necessary, not sufficient, for repeatability (see
    `drift_gate`)."""
    with_shape = sorted(s for s, d in docs.items() if d["same_class_both_buses"])
    screened = [s for s in with_shape if s in ran]
    eligible = sorted(s for s in screened if gates[s] == "PASS")
    not_eligible = sorted(s for s in screened if gates[s] != "PASS")
    if len(screened) != len(with_shape):
        eligibility = "NOT_RUN"
    elif eligible:
        eligibility = "PASS"
    else:
        eligibility = "FAIL"
    return {
        "shape": SAME_CLASS_SHAPE,
        "carriers_with_shape": with_shape,
        "carriers_with_shape_leg_ran": screened,
        "render_eligible_carriers": eligible,
        "not_render_eligible_carriers": not_eligible,
        "eligible_carrier_exists": eligibility,
        "eligible_carrier_exists_note":
            "PASS here means only that at least one carrier with this shape "
            "passed the drift gate. It is NOT a render result: no fixture for "
            "this routing form has been rendered.",
        "render": "BLOCKED (#12)",
        "screen": "reports/SXT-028l/artifacts/same-class-carrier-screen.json "
                  "(every same-class dual-occupant preset in the corpus, "
                  "screened through the same drift_gate)",
    }


def live_leg_summary(docs):
    """Roll the per-carrier LIVE legs up into one record of the leg itself
    (#155 item 1a).

    TWO verdicts are kept separate, and neither is inferred from the other:

      * `parameter_extraction.status` -- did the live per-slot extraction run
        for every carrier and agree with the committed corpus artifacts? PASS
        only when it ran for ALL of them (a partial run is NOT_RUN coverage,
        never a pass).
      * `determinism_gate.status` -- is every carrier's per-scene drift 0, so
        that a reference render of it could be repeatable at all? A carrier
        with nonzero drift FAILS, is listed by name, and is marked
        `render_eligible: false`. The gate bounds the RENDER legs (1b/1c);
        it does not touch the oracle-free routing metadata and it does not
        touch the RTL-vs-frozen-model claim.

    COVERAGE (how many carriers the leg ran for) is reported separately from
    both verdicts, and NOT_RUN is recorded rather than a pass when the oracle
    is absent."""
    ran = {slug: d for slug, d in docs.items()
           if d["oracle_extraction"]["ok"]}
    not_run = {slug: d["oracle_extraction"]["detail"]
               for slug, d in docs.items()
               if not d["oracle_extraction"]["ok"]}
    gates = {slug: d["oracle_extraction"]["live"]["determinism_gate"]["status"]
             for slug, d in ran.items()}
    drifts = {slug: d["oracle_extraction"]["live"]["determinism_gate"]
              ["drift_per_voicing_scene"] for slug, d in ran.items()}
    gate_failures = sorted(s for s, v in gates.items() if v != "PASS")
    if not ran:
        extraction_status = "NOT_RUN"
    elif len(ran) != len(docs):
        extraction_status = "NOT_RUN"
    else:
        extraction_status = "PASS"
    if not ran:
        gate_status = "NOT_RUN"
    elif gate_failures:
        gate_status = "FAIL"
    else:
        gate_status = "PASS"
    status = "NOT_RUN" if not ran else (
        "FAIL" if (extraction_status != "PASS" or gate_status != "PASS")
        else "PASS")
    engines = sorted({json.dumps(d["oracle_extraction"]["live"]["engine"],
                                 sort_keys=True) for d in ran.values()})
    return {
        "schema_version": 2,
        "leaf": "SXT-028l",
        "work_item": "#155 item 1a (oracle-host reference leg: LIVE surgepy "
                     "per-slot parameter extraction + the engine-side "
                     "per-scene drift determinism gate)",
        "claim_scope": "ENGINE-SIDE extraction and determinism only. This "
                       "record establishes NO model-vs-pinned-engine "
                       "agreement number (leg 1c; BLOCKED on #12), NO "
                       "RTL-vs-frozen-model claim (that is "
                       "reports/SXT-028l/rtl-exactness.json, which needs no "
                       "oracle), NO preset-support claim and NO "
                       "musical-quality claim.",
        "status": status,
        "status_note": "`status` is the WORST of the two independent verdicts "
                       "below; read them separately. It is deliberately not a "
                       "single pass/fail judgement on the leaf.",
        "parameter_extraction": {
            "what": "per-slot algorithm parameter values + return_level for "
                    "send3/send4, read from the pinned engine's normalized "
                    "(post-loadPatch) state and cross-checked against "
                    "corpus/normalized/graphs.jsonl",
            "status": extraction_status,
            "carriers_extracted": len(ran),
            "carriers_total": len(docs),
        },
        "determinism_gate": {
            "what": "per-scene `drift` must be 0 in every voicing scene, or no "
                    "reference render of that carrier is repeatable (the "
                    "harness never seeds engine RNG -- oracle/manifest.json)",
            "status": gate_status,
            "carriers_passing": sorted(s for s, v in gates.items()
                                       if v == "PASS"),
            "carriers_failing": gate_failures,
            "drift_per_carrier": drifts,
            "bounds": "the RENDER legs (1b/1c) only. A carrier that fails this "
                      "gate cannot carry a frozen reference fixture even once "
                      "#12 clears; it is NOT excluded from the routing "
                      "metadata above and the RTL-vs-frozen-model exactness "
                      "claim is unaffected.",
            "routed_to": "#322 (restore render coverage of the same-class "
                         "dual-instance shape with a drift-0 carrier, or "
                         "record a bounded coverage gap) -- see "
                         "`same_class_dual_instance_render_coverage`",
        },
        "same_class_dual_instance_render_coverage": same_class_coverage(
            docs, ran, gates),
        "render_eligible_once_12_clears": {
            slug: gates[slug] == "PASS" for slug in sorted(ran)},
        "host": {"platform": platform.platform(),
                 "machine": platform.machine(),
                 "python": platform.python_version()},
        "engines_observed": [json.loads(e) for e in engines],
        "coverage": {"carriers_total": len(docs),
                     "carriers_leg_ran": len(ran),
                     "carriers_leg_not_run": not_run},
        "determinism_gate_per_carrier": gates,
        "send_level_exposure_recheck": [
            json.loads(e) for e in sorted(
                {json.dumps(d["oracle_extraction"]["live"]
                            ["send_level_exposure_recheck"], sort_keys=True)
                 for d in ran.values()})],
        "legs_still_not_run_or_blocked": {
            "render": "BLOCKED (#12) -- new reference fixtures for this "
                      "routing form need a per-scene send level for buses 3/4",
            "model-render": "BLOCKED (#12) -- same gate: no fixture bus to "
                            "drive the frozen model with",
            "reference-compare": "BLOCKED (#12) -- no reference fixture, so no "
                                 "model-vs-engine agreement number",
            "send-level-default-probe": "BLOCKED (#12) -- the loader-default "
                                        "semantics are the SXT-017 decision's "
                                        "own input and are deliberately not "
                                        "probed here",
        },
        "per_carrier": {slug: d["oracle_extraction"]["live"]
                        for slug, d in sorted(ran.items())},
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(ARTIFACTS, exist_ok=True)
    refusal_lines = []
    written = []
    docs = {}
    for carrier in CARRIERS:
        try:
            doc = extract_one(carrier)
        except Refuse as e:
            refusal_lines.append(f"{carrier['slug']}: REFUSED: {e}")
            continue
        out_path = os.path.join(OUT_DIR,
                                f"rf-rf-send34-{carrier['slug']}.json")
        with open(out_path, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        written.append(out_path)
        docs[carrier["slug"]] = doc
        print(f"wrote {out_path}")

    live = live_leg_summary(docs) if docs else None
    if live is None:
        print("live leg: NOT_RUN (no carrier record was produced at all)")
    elif live["status"] == "NOT_RUN":
        # Do NOT overwrite a committed live-leg record with this environment's
        # NOT_RUN measurement: that record is an oracle host's evidence and a
        # NOT_RUN here is not a reason to delete it. The absence of the oracle
        # here is already recorded per carrier (oracle_extraction.ok: false)
        # and by tools/rf_send34_oracle_status.py.
        print(f"live leg: NOT_RUN in this environment (oracle absent); left "
              f"{LIVE_LEG} untouched")
        for slug, why in live["coverage"]["carriers_leg_not_run"].items():
            print(f"  {slug}: NOT_RUN: {why}")
    else:
        with open(LIVE_LEG, "w") as f:
            json.dump(live, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"wrote {LIVE_LEG}")
        print(f"live leg: parameter extraction "
              f"{live['parameter_extraction']['status']} "
              f"({live['parameter_extraction']['carriers_extracted']}/"
              f"{live['parameter_extraction']['carriers_total']} carriers); "
              f"per-scene drift determinism gate "
              f"{live['determinism_gate']['status']}")
        for slug in live["determinism_gate"]["carriers_failing"]:
            print(f"  GATE FAIL {slug}: drift "
                  f"{live['determinism_gate']['drift_per_carrier'][slug]} != 0 "
                  f"-- not render-eligible (bounds legs 1b/1c only)")

    with open(OCCUPANCY, "w") as f:
        json.dump(corpus_occupancy(), f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {OCCUPANCY}")

    with open(GAP, "w") as f:
        json.dump(send_level_gap_scan(), f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {GAP}")

    with open(REFUSALS, "w") as f:
        f.write("\n".join(refusal_lines) + ("\n" if refusal_lines else ""))
    for line in refusal_lines:
        print(line)
    if len(written) != len(CARRIERS):
        return 1
    # Exit 3: the live leg RAN and recorded a determinism-gate FAIL. A distinct
    # code, because this is neither a clean run (0) nor a failure to produce the
    # records (1): the carrier metadata is complete and correct, and one or more
    # carriers are simply not render-eligible. It must stay visible rather than
    # be absorbed into exit 0 -- the fix is to record the finding (and to pick a
    # different render carrier), never to drop the gate.
    if live is not None and live["determinism_gate"]["status"] == "FAIL":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
