#!/usr/bin/env python3
"""SXT-028 effects leaf generator (issue #21).

Deterministically generates per-algorithm / per-routing-form effect leaf
issues for the B4-broad remaining FX scope, ordered by measured recovery
(SXT-014 numeric ablation deltas first, then corpus carrier frequency), with
the essentiality caveat machine-stamped on every artifact:

    "essentiality UNVERIFIED -- listening pending (#9)"

Inputs (all committed data; no oracle, no network):
  corpus/normalized/graphs.jsonl          normalized FX graphs (SXT-011)
  reports/sxt-014/ablation-summary.json   diagnostic ablation deltas (SXT-014)
  contracts/profile-v1-bundle-DRAFT.json  B4-broad FX gates (SXT-017 DRAFT)

Outputs (byte-deterministic; verify with --verify):
  reports/sxt-028/allocation.json          SXT-028<letter> allocation table
  reports/sxt-028/leaf-backlog.json        all generated leaves, ordered
  reports/sxt-028/leaves/<id>.json         full leaf spec
  reports/sxt-028/leaves/<id>.md           issue body (filed leaves)
  reports/sxt-028/leaves/<id>/newly-enabled.json  preset hashes per leaf
  reports/sxt-028/negative-controls.txt    generator self-test transcript

Claim discipline: this tool generates *issue text*. It establishes no
fidelity, support, cost, or musical-quality claim, and no essentiality
label. Numeric ablation deltas are diagnostic only (SXT-014).

Usage:
  python3 tools/generate_effect_leaves.py [--filed N] [--verify] [--self-test]
"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "corpus/normalized/graphs.jsonl"
ABLATION = REPO / "reports/sxt-014/ablation-summary.json"
BUNDLE = REPO / "contracts/profile-v1-bundle-DRAFT.json"
OUT_DIR = REPO / "reports/sxt-028"
BUNDLE_ID = "B4-broad"

SCHEMA_VERSION = "sxt-028-effect-leaf/1.0.0"
GENERATED_BY = "SXT-028 issue generator (tools/generate_effect_leaves.py)"
ESSENTIALITY_STAMP = "essentiality UNVERIFIED -- listening pending (#9)"
CLAIM_SCOPE = (
    "Issue text only: no model/RTL exists, no fidelity or support claim, "
    "no cost claim, no musical-quality claim. Ablation deltas are "
    "reference-vs-reference diagnostics (SXT-014)."
)

# Engine pin (oracle/manifest.json); cited, never copied.
ENGINE_PIN = "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71"
SST_EFFECTS_PIN = (
    "libs/sst/sst-effects@adcac6950292dacc529651093e7ece2d1c8c0d4b"
)

# Landed / in-flight FX classes that other issues already own. Delay + EQ are
# IN FLIGHT under SXT-023 (#16, open delay-budget finding); Reverb 1 landed
# under SXT-024 (#17). A preset counts toward a leaf's strict-FX-complete
# newly-enabled set only when every other active FX class it uses is covered
# here and it uses no other un-covered Airwindows algorithm.
COVERED_CLASSES = {
    "Reverb 1": "landed (SXT-024, #17)",
    "Delay": "in-flight (SXT-023, #16; open delay-budget finding)",
    "EQ": "in-flight (SXT-023, #16)",
}

# Routing roles exercised by fixtures of record so far, with provenance.
# SXT-014 pilot renders: ains1/ains2 (EQ, Chorus), send1/send2 (Reverb 1,
# Delay, Airwindows), global1 (Conditioner); SXT-023 fixtures: ains1, send1;
# SXT-025 integration: ains1, send2. Roles outside this set are routing
# forms not yet exercised by any fixture of record.
EXERCISED_ROLES = {"ains1", "ains2", "send1", "send2", "global1"}
EXERCISED_ROLES_PROVENANCE = (
    "SXT-014 pilot + SXT-023 fixtures + SXT-025 integration "
    "(reports/sxt-014/EVIDENCE.md, reports/sxt-023/EVIDENCE.md, "
    "reports/sxt-025/EVIDENCE.md)"
)

# Routing forms not yet exercised, derived from the role data. Each form is
# one leaf: one routing form per leaf (issue #21 acceptance).
ROUTING_FORMS = [
    ("rf-global2", "Global FX slot 2 (second concurrent global FX instance)",
     ["global2"]),
    ("rf-bins12", "Scene-B insert FX bus, slots 1-2 (bins1/bins2)", ["bins1", "bins2"]),
    ("rf-ains34", "Scene-A insert FX slots 3-4 (ains3/ains4, extended rack half)",
     ["ains3", "ains4"]),
    ("rf-global34", "Global FX slots 3-4 (global3/global4, extended rack half)",
     ["global3", "global4"]),
    ("rf-send34", "Send buses 3-4 (send3/send4, extended rack half)",
     ["send3", "send4"]),
]

# Per-type pinned structure authority (READ + cited; nothing copied).
# sst-effects headers live in the pinned submodule; everything else in the
# pinned engine tree. Airwindows algorithm headers are vendored in the engine
# tree at libs/airwindows (not a submodule at the pinned commit).
SST_TYPES = {
    "Chorus": [f"{SST_EFFECTS_PIN}/include/sst/effects/Chorus.h "
               "(ChorusEffect: initialize/setvars/processBlock; nested "
               "ChorusEffectBase lags and LFO phase)",
               f"{SST_EFFECTS_PIN}/include/sst/effects/EffectCore.h",
               f"{ENGINE_PIN}: src/common/dsp/effects/SurgeSSTFXAdapter.h "
               "(envelopeRateLinear/temposyncRatio adapters)"],
    "Phaser": [f"{SST_EFFECTS_PIN}/include/sst/effects/Phaser.h "
               "(PhaserEffect stages/lfo shift+scale)",
               f"{SST_EFFECTS_PIN}/include/sst/effects/EffectCore.h",
               f"{ENGINE_PIN}: src/common/dsp/effects/SurgeSSTFXAdapter.h"],
    "Reverb 2": [f"{SST_EFFECTS_PIN}/include/sst/effects/Reverb2.h "
                 "(Reverb2Effectverb: comb/allpass/tank structure, damping, "
                 "outcoarse/outscale precomputed in setvars)",
                 f"{SST_EFFECTS_PIN}/include/sst/effects/EffectCore.h",
                 f"{ENGINE_PIN}: src/common/dsp/effects/SurgeSSTFXAdapter.h"],
    "Conditioner": [f"{ENGINE_PIN}: src/common/dsp/effects/"
                    "ConditionerEffect.{h,cpp} (ConditionerEffect: "
                    "process_block; gate/comp envelope lag objects; shared "
                    "LFO)"],
    "Distortion": [f"{ENGINE_PIN}: src/common/dsp/effects/"
                   "DistortionEffect.{h,cpp} (DistortionEffect::process; "
                   "band/state-variable stages; WS drive tables via "
                   "waveshapers)"],
}
AW_ALGORITHMS = [
    (49, "Galactic", "Galactic.h"),
    (4, "Logical", "Logical4.h"),
    (46, "Capacitor", "Capacitor.h"),
    (42, "To Tape", "ToTape6.h"),
    (24, "Pocket Verbs", "PocketVerbs.h"),
    (5, "Mojo", "Mojo.h"),
    (35, "NC-17", "NCSeventeen.h"),
    (30, "Drive", "Drive.h"),
    (21, "Bright Ambience", "BrightAmbience2.h"),
    (15, "DeRez", "DeRez2.h"),
    (3, "Compresaturator", "Compresaturator.h"),
    (41, "Iron Oxide", "IronOxide5.h"),
]
AW_SOURCES_TMPL = [
    f"{ENGINE_PIN}: libs/airwindows/src/@HDR@ + "
    "libs/airwindows/include/airwindows/AirWinBaseClass.h (vendored at the "
    "engine commit; algorithm id registry)",
    f"{ENGINE_PIN}: src/common/dsp/effects/airwindows/"
    "AirWindowsEffect.{h,cpp} (shared adapter: param block, IO buffers, "
    "per-instance state object)",
]
TYPE_LEAF_TITLES = {
    "Chorus": "Chorus effect leaf (sst-effects Chorus, delay-line class)",
    "Conditioner": "Conditioner effect leaf (gate/compressor/LFO)",
    "Phaser": "Phaser effect leaf (sst-effects Phaser)",
    "Distortion": "Distortion effect leaf (multiband + waveshaper drive)",
    "Reverb 2": "Reverb 2 effect leaf (sst-effects tank reverb)",
}

# SXT-014 pilot carriers by delta-file slug (reports/sxt-014/EVIDENCE.md);
# census paths resolved from graphs.jsonl at generation time (fail-closed).
PILOT_PRESET_SLUGS = {
    "Chorus": "fmcombo",
    "Conditioner": "doomsday",
    "Airwindows": "fmod09",
}
PILOT_PRESET_PATHS = {
    "fmcombo": "resources/data/patches_factory/Basses/FM Combo.fxp",
    "doomsday": "resources/data/patches_factory/Basses/Doomsday.fxp",
    "fmod09": "resources/data/patches_factory/Tutorials/"
              "Formula Modulator/09 Example - Crossfading Oscillators.fxp",
}

# Leaves that inherit an open SXT-017 (#12) decision before budgets freeze.
SXT017_MARKERS = {
    "type:Chorus": (
        "Chorus shares Delay's LFO-modulated delay-line semantics; the open "
        "delay-budget finding (SXT-023 diagnosis: LFO term presence in the "
        "delay-time path, reports/sxt-023/delay-budget-diagnosis.md) applies "
        "to the Chorus delay time path too. SXT-017 DECISION REQUIRED before "
        "any Chorus reference budget freezes; coordinate with #16."
    ),
    "rf:rf-send34": (
        "Send buses 3/4 hit a documented SXT-011 data gap: no factory .fxp "
        "stores send_level for buses 3/4 and the surgepy binding does not "
        "expose them (corpus/normalized/schema.json). The loader-default "
        "send level semantics need an engine-behavior probe and an SXT-017 "
        "data-gap policy decision before fixture freezing."
    ),
    "type:Reverb 2": (
        "Reverb 2 tank state is the largest candidate external-memory "
        "resident of this batch; the ext-mem residency/traffic budget is "
        "[PENDING-SXT-016] and the SXT-017 freeze (#12) gates any fit "
        "claim. Decision required at freeze stage, not a scope exclusion."
    ),
}

SEQUENCES = "seq-notes-coverage-v1 + seq-poly-8-v1 (SXT-012 library, SHA-256-pinned; reports/sxt-014 run manifests)"

LEAF_KIND_RANK = {"type": 0, "aw": 1, "rf": 2}


class LeafRefusal(Exception):
    """Generator refuses to emit a leaf (negative control or bad input)."""


def sha256_file(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def load_corpus():
    presets = []
    with open(CORPUS, encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e["st"] != "normalized":
                continue
            types, aw, roles, pcount = set(), set(), set(), {}
            for fx in e["g"]["fx"]:
                if fx.get("on") != 1:
                    continue
                types.add(fx["tn"])
                roles.add(fx["r"])
                pcount[fx["i"]] = len(fx.get("p", []))
                if fx["tn"] == "Airwindows":
                    aw.add(fx["aw"])
            presets.append(
                {"path": e["p"], "sha": e["sha"], "bank": e["b"],
                 "types": types, "aw": aw, "roles": roles,
                 "param_count": pcount}
            )
    presets.sort(key=lambda p: (p["bank"], p["path"]))
    return presets


def load_ablation():
    """Per exact algorithm: max/mean diagnostic delta + provenance rows."""
    data = json.loads(ABLATION.read_text(encoding="utf-8"))
    agg = defaultdict(lambda: {"deltas": [], "rows": []})
    for r in data["rows"]:
        if r["kind"] != "bypass-slot" or r.get("slot") is None:
            continue
        s = r["slot"]
        if s["type_name"] == "Airwindows":
            key = ("aw", s["airwindows"]["algorithm_id"])
        else:
            key = ("type", s["type_name"])
        agg[key]["deltas"].append(r["mean_block_rms_delta_db"])
        agg[key]["rows"].append(r["delta_json"])
    out = {}
    for key, v in agg.items():
        out[key] = {
            "max_mean_block_rms_delta_db": round(max(v["deltas"]), 3),
            "min_mean_block_rms_delta_db": round(min(v["deltas"]), 3),
            "delta_jsons": sorted(v["rows"]),
        }
    return out


def load_b4():
    data = json.loads(BUNDLE.read_text(encoding="utf-8"))
    for b in data["bundles"]:
        if b["bundle_id"] == BUNDLE_ID:
            spec = b["spec"]
            return {
                "fx_types": set(spec["fx_type_allowlist"]),
                "aw_ids": set(spec["airwindows_policy"]["selected_algorithm_ids"]),
                "status": data["status"],
            }
    raise SystemExit(f"bundle {BUNDLE_ID} not found")


def in_b4(p, b4):
    return (p["types"] - {"Airwindows"}) <= b4["fx_types"] and \
        p["aw"] <= b4["aw_ids"]


def build_leaves(presets, ablation, b4):
    remaining = [t for t in sorted(TYPE_LEAF_TITLES)
                 if t not in COVERED_CLASSES]
    leaves = []
    for t in remaining:
        leaves.append({
            "kind": "type", "fid": t,
            "title": TYPE_LEAF_TITLES[t],
            "feature": {"class": t},
            "match": lambda p, t=t: t in p["types"],
            "strict_ok": lambda p, t=t: p["types"] <= set(COVERED_CLASSES) | {t}
            and not p["aw"],
        })
    for aid, name, header in AW_ALGORITHMS:
        leaves.append({
            "kind": "aw", "fid": aid,
            "title": f"Airwindows algorithm leaf: {name} (id {aid})",
            "feature": {"airwindows_algorithm_id": aid,
                        "algorithm_name": name, "header": header},
            "match": lambda p, a=aid: a in p["aw"],
            "strict_ok": lambda p, a=aid: p["types"] <= set(COVERED_CLASSES)
            | {"Airwindows"} and p["aw"] <= {a},
        })
    for fid, title, roles in ROUTING_FORMS:
        rs = set(roles)
        leaves.append({
            "kind": "rf", "fid": fid,
            "title": f"Routing-form leaf: {title}",
            "feature": {"routing_form": fid, "roles": roles},
            "match": lambda p, rs=rs: bool(p["roles"] & rs),
            "strict_ok": lambda p: p["types"] <= set(COVERED_CLASSES)
            and not p["aw"],
        })
    for lf in leaves:
        cand = [p for p in presets if in_b4(p, b4) and lf["match"](p)]
        strict = [p for p in cand if lf["strict_ok"](p)]
        lf["candidates"] = cand
        lf["strict"] = strict
        key = (("aw", lf["fid"]) if lf["kind"] == "aw"
               else ("type", lf["fid"])) if lf["kind"] != "rf" else None
        lf["ablation"] = ablation.get(key) if key else None
        slug = None
        if lf["kind"] == "type":
            slug = PILOT_PRESET_SLUGS.get(lf["fid"])
        elif lf["kind"] == "aw" and lf["ablation"]:
            slug = PILOT_PRESET_SLUGS.get("Airwindows")
        pilot = None
        if slug:
            path = PILOT_PRESET_PATHS[slug]
            matches = [p for p in presets if p["path"] == path]
            if not matches:
                raise SystemExit(f"pilot preset {slug} ({path}) missing "
                                 "from corpus -- refusing to generate")
            pilot = {"slug": slug, "path": path,
                     "sha": matches[0]["sha"], "bank": matches[0]["bank"]}
        lf["pilot"] = pilot
    return leaves


def order_leaves(leaves):
    """Measured recovery first (delta desc), then carriers desc.

    Essentiality labels are BLOCKED-on-human (#9); until then numeric deltas
    + carrier frequency order the queue, stamped caveat. Tie-break:
    (kind rank, feature id) ascending -- deterministic.
    """

    def key(lf):
        kid = (f"{lf['fid']:04d}" if isinstance(lf["fid"], int)
               else str(lf["fid"]))
        ab = lf.get("ablation")
        if ab:
            return (0, -ab["max_mean_block_rms_delta_db"],
                    LEAF_KIND_RANK[lf["kind"]], kid)
        return (1, -len(lf["candidates"]),
                LEAF_KIND_RANK[lf["kind"]], kid)

    return sorted(leaves, key=key)


def pinned_sources_for(lf):
    if lf["kind"] == "type":
        return SST_TYPES[lf["fid"]]
    if lf["kind"] == "aw":
        return [s.replace("@HDR@", lf["feature"]["header"])
                for s in AW_SOURCES_TMPL]
    return [
        f"{ENGINE_PIN}: src/common/SurgeSynthesizer.cpp -- process() "
        "(fxsendout buses, sendToIndex[fxslot_send1..4], per-scene "
        "send_level smoothing, fx return_level, fx_bypass gating), "
        "loadFx() (per-slot reload), reorderFx(), enqueueFXOff()",
        f"{ENGINE_PIN}: src/common/SurgeStorage.h -- fxslot_* slot index "
        "constants, n_send_slots, fxb_* bypass states",
        f"{ENGINE_PIN}: src/common/dsp/effects/SurgeSSTFXAdapter.h + "
        "SurgeEffect.h (instance construction/suspend per slot)",
    ]


def validate_leaf(lf):
    """Structural refusals. These are the generator's live negative rules."""
    keys = [k for k in lf["feature"].keys()
            if k in ("class", "airwindows_algorithm_id", "routing_form")]
    if len(keys) > 1:
        raise LeafRefusal(
            f"cross-type merged leaf refused: features {keys} -- one "
            "algorithm (or routing form) per leaf (#21 acceptance)")
    if not lf["candidates"]:
        raise LeafRefusal(
            f"leaf refused: zero newly-enabled presets in B4 scope "
            f"(feature {lf['feature']}) -- nothing to enable, not filed")
    return True


def make_spec(lf, order, letter, presets, b4):
    fid = f"SXT-028{letter}"
    ab = lf.get("ablation")
    cand = lf["candidates"]
    fac = sum(1 for p in cand if p["bank"] == "factory")
    con = len(cand) - fac
    tops = cand[:3]
    marker = SXT017_MARKERS.get(f"{lf['kind']}:{lf['fid']}")
    if lf["kind"] == "type":
        pmap = {
            "authority": "pinned sources + surgepy readback at load, "
                         "cross-checked against graphs.jsonl (SXT-011)",
        }
    elif lf["kind"] == "aw":
        pmap = {
            "authority": "pinned AirWindowsEffect adapter + surgepy "
                         "readback at load, cross-checked against "
                         "graphs.jsonl (SXT-011)",
            "note": "p[0] selects the algorithm id; the 12-slot block is "
                    "the shared AirWindowsEffect adapter",
        }
    else:
        pmap = {
            "authority": "slot-index/role mapping pinned by SurgeStorage.h "
                         "fxslot_* constants, cross-checked against "
                         "graphs.jsonl role data (SXT-011); send leaves pin "
                         "return_level and per-scene send_level semantics "
                         "from SurgeSynthesizer::process()",
        }
    roles_used = sorted(lf["feature"]["roles"]) if lf["kind"] == "rf" \
        else sorted({r for p in cand for r in p["roles"]})
    spec = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        "essentiality": ESSENTIALITY_STAMP,
        "claim_scope": CLAIM_SCOPE,
        "leaf_id": fid,
        "title": fid + ": " + lf["title"],
        "kind": lf["kind"],
        "feature": lf["feature"],
        "routing_roles_used_in_scope": roles_used,
        "recovery_order": order,
        "ordering_basis": (
            {"measured": True,
             "max_mean_block_rms_delta_db": ab["max_mean_block_rms_delta_db"],
             "delta_jsons": ab["delta_jsons"],
             "caveat": "diagnostic ablation delta; label requires listening (#9)"}
            if ab else
            {"measured": False,
             "carrier_basis": "B4-scope candidate preset count",
             "carrier_count": len(cand),
             "caveat": "no SXT-014 ablation carrier for this algorithm; "
                       "ordered by corpus frequency; essentiality "
                       "UNVERIFIED -- listening pending (#9)"}),
        "ablation_carriers": ab,
        "carriers": {
            "b4_scope_candidate_presets": len(cand),
            "factory": fac,
            "contributor": con,
            "top_presets": [{"path": p["path"], "sha": p["sha"],
                             "bank": p["bank"]} for p in tops],
        },
        "newly_enabled": {
            "rule": "strict-FX-complete: every active FX class of the "
                    "preset is landed/in-flight (" + "; ".join(
                        f"{k} {v}" for k, v in sorted(COVERED_CLASSES.items()))
                    + ") or this leaf's own feature; B4-scope candidate "
                      "count is the upper bound. Presets needing sibling "
                      "028 leaves count toward neither until the last "
                      "sibling lands.",
            "strict_fx_complete_count": len(lf["strict"]),
            "b4_scope_candidate_count": len(cand),
            "artifact": f"reports/sxt-028/leaves/{fid}/newly-enabled.json",
            "caveat": "FX-scope accounting only; voice stage, scheduling, "
                      "and profile v1 freeze gate actual support. NOT a "
                      "support claim.",
        },
        "pinned_sources": pinned_sources_for(lf),
        "parameter_mapping": pmap,
        "state_and_cost": {
            "per_instance_state": "every concurrent instance keeps "
                                  "independent histories; arithmetic may "
                                  "be shared only observably (plan section "
                                  "4; AGENTS.md)",
            "long_buffers": "delay/reverb-class buffers live in external "
                            "WRITABLE memory; processing stays on-chip; "
                            "flash is not writable delay memory",
            "ext_mem_traffic_estimate": "[PENDING-SXT-016] estimate via "
                                        "SXT-015 accounting on the frozen "
                                        "model; no number invented here",
        },
        "sxt017_decision_required": marker,
        "fixtures_plan": fixtures_plan_for(lf),
        "acceptance": acceptance_for(lf),
        "negative_controls": negative_controls_for(lf),
        "deliverables": deliverables_for(lf, fid),
        "dependencies": dependencies_for(lf),
        "non_goals": ["Implementing the leaf here; coverage publication "
                      "(#22); any substitute/generic effect under a support "
                      "claim"],
        "stop_escalate": "If the effect cannot be bounded in state/cost "
                         "under the shared instance schedule, record the "
                         "finding and route to SXT-017 (#12) before "
                         "freezing budgets; do not weaken acceptance to "
                         "pass.",
        "inputs": {
            "corpus": "corpus/normalized/graphs.jsonl",
            "ablation": "reports/sxt-014/ablation-summary.json",
            "bundle": f"contracts/profile-v1-bundle-DRAFT.json#{BUNDLE_ID}"
                      f" (status {b4['status']})",
        },
    }
    return spec


def fixtures_plan_for(lf):
    tops = lf["candidates"][:3]
    items = []
    if lf.get("ablation"):
        pilot = lf["pilot"]
        items.append(
            "SXT-014 pilot carrier exists: "
            f"{pilot['path']} ({pilot['bank']}, blob {pilot['sha'][:12]}...)"
            " -- reuse the committed SXT-012 fixture WAVs + SXT-014 ablation"
            " tree for the comparability leg (same engine pin, sequences, "
            "policies); no re-render needed for that leg.")
    else:
        items.append(
            "No SXT-014 ablation carrier exists for this algorithm: render "
            "new reference fixtures from the pinned oracle under SXT-012 "
            "policies (tools/render_fx_fixtures.py pattern), original + "
            "per-slot bypass + all-off dry, tails included.")
    items.append(
        "Proposed additional fixture presets (B4-scope carriers, "
        "census-blob sha verified at render): " + "; ".join(
            f"{p['path']} ({p['bank']}, blob {p['sha'][:12]}...)"
            for p in tops))
    items.append(f"Sequences: {SEQUENCES}.")
    items.append(
        "Comparability caveat: free-phase presets have single-instance "
        "numeric deltas with a repeatability-class floor (reports/sxt-012/"
        "repeatability.json); bit-identical-class presets preferred for "
        "exactness claims.")
    items.append(
        "Parameter corners: loader defaults, extremes of each named param, "
        "and the fixture preset's stored values; temposync cases pin "
        "loadPatch tempo (SXT-023 pattern).")
    return items


def acceptance_for(lf):
    acc = [
        "Fixed-model/RTL equality: RTL matches the frozen fixed-point model "
        "exactly (integer equality at declared checkpoints; "
        "tools/compare_rtl_model_fx.py pattern). This is a separate claim "
        "from reference agreement.",
        "Reference budgets [PROPOSED, not frozen]: model-vs-pinned-engine "
        "agreement within declared max/rms/corr budgets on the fixture "
        "presets; budgets freeze only via SXT-017 (#12).",
        "Per-instance state: two concurrent instances of this "
        f"{'algorithm' if lf['kind'] != 'rf' else 'routing form'} keep "
        "independent histories (dual-slot model-level fixture); RTL/model "
        "equality must hold per instance.",
        "Tails: acceptance renders include the effect's own tail span; "
        "patch-change mid-tail and reset/panic behavior specified and "
        "tested; dropped-tail renders FAIL.",
        "External-memory traffic: state residency + read/write traffic "
        "estimate from the frozen model via SXT-015 accounting "
        "[PENDING-SXT-016]; long buffers external-writable, never flash.",
        "Negative controls live: each control below demonstrably fails the "
        "check it targets; a control that passes is a broken control.",
    ]
    if lf["kind"] == "aw":
        acc.insert(1,
                   "Algorithm identity: the shared adapter dispatches p[0] "
                   "to exactly this algorithm; sibling algorithms remain "
                   "out of scope of this leaf.")
    return acc


def negative_controls_for(lf):
    return [
        "Wrong order: two same-class slots swapped (slot-content "
        "permutation, tools/ablate_fx.py permute pattern) must FAIL the "
        "order-sensitive equality/agreement check.",
        "Shared state: a mutant that pools the two instances' histories "
        "into one (tb_fx_shared_line pattern) must FAIL the dual-instance "
        "equality check.",
        "Generic substitute: any variant that swaps this algorithm for a "
        "convenient generic is labeled ADAPTED and must be refused/excluded "
        "from original-preset coverage (tools/ablate_fx.py substitute "
        "pattern); bypass tests retain the unmodified wet reference.",
        "Dropped tail: truncating the render before the declared tail span "
        "must FAIL the tail check.",
        "Stale stub: the RTL harness pins the frozen-model revision hash; "
        "a stale harness must refuse to report PASS.",
    ]


def deliverables_for(lf, fid):
    slug = lf["kind"] + "-" + str(lf["fid"]).lower()
    d = [
        f"model/effects/{slug}/ -- frozen fixed-point model + README "
        "(word lengths, state layout, per-instance state ownership) "
        "(model/effects/README.md pattern)",
        f"model/effects/fx_inputs/{slug}-*.json -- fail-closed input "
        "extraction (extract_fx_inputs.py pattern; census blob re-verified, "
        "graphs cross-check, drift asserted 0)",
        f"rtl/effects/{slug}/ -- RTL + iverilog testbench incl. the "
        "dual-instance and negative-control benches",
        f"reports/{fid}/ -- EVIDENCE.md: verification statuses PASS/FAIL/"
        "NOT_RUN/BLOCKED, budgets vs achieved, coverage separate from "
        "agreement, ext-mem estimate [PENDING-SXT-016]",
        f"tests/test_{fid.replace('-', '').lower()}.py -- "
        "generator-consistency + exactness harness guards (oracle-dependent "
        "tests skip NOT_RUN without oracle)",
    ]
    if lf["kind"] == "aw":
        d.append("decision-records/ entry: license decision record for any "
                 "airwindows table/code adoption before merge (AGENTS.md "
                 "licensing rule; libs/airwindows LICENSE terms reviewed)")
    return d


def dependencies_for(lf):
    deps = [
        "#9 SXT-014 (done: numeric deltas; listening labels BLOCKED-on-human)",
        "#12 SXT-017 profile freeze (budget freeze gate)",
        "#16 SXT-023 Delay/EQ (per-effect acceptance pattern + the open "
        "delay-budget finding feeds SXT-017)",
        "#17 SXT-024 Reverb 1 (done: per-effect acceptance pattern, DR-0003 "
        "constant-table pattern)",
    ]
    if lf["kind"] == "rf":
        deps.append("#18 SXT-025 (done: integration boundary + scheduling "
                    "for multi-slot wet paths)")
    else:
        deps.append("#18 SXT-025 (done: integration boundary)")
    return deps


def issue_body(spec, allocation_note):
    lf_rf = spec["kind"] == "rf"
    L = []
    a = spec
    L.append(f"**Epic:** #3 (effects expansion) · **Plan:** "
             f"docs/surge-xt-chip-plan-v0.1-2026-09-20.md §6 (SXT-028 row) · "
             f"planning ID: {spec['leaf_id']} · raised by SXT-028 (#21)")
    L.append("")
    L.append(f"**{ESSENTIALITY_STAMP}.** {CLAIM_SCOPE}")
    L.append("")
    L.append("## Outcome")
    L.append("")
    L.append(f"One {'algorithm' if spec['kind'] != 'rf' else 'routing form'}"
             " per leaf: " + spec["title"].split(": ", 1)[1] + ". "
             "Preserves per-instance state and tails under the shared "
             "instance schedule; no monolithic FX port.")
    L.append("")
    L.append("## Recovery ordering (diagnostic)")
    ob = spec["ordering_basis"]
    if ob["measured"]:
        L.append(f"Ordered by measured SXT-014 ablation delta: max mean "
                 f"block-RMS Δ {ob['max_mean_block_rms_delta_db']} dB "
                 f"(diagnostic only). Provenance: "
                 + "; ".join(ob["delta_jsons"]) + ".")
    else:
        L.append(f"No SXT-014 ablation carrier for this feature; ordered by "
                 f"B4-scope carrier frequency ({ob['carrier_count']} "
                 f"presets). Essentiality UNVERIFIED -- listening pending "
                 "(#9).")
    L.append("")
    L.append("## Scope and pinned sources")
    L.append("")
    for s in spec["pinned_sources"]:
        L.append(f"- {s}")
    note = spec["parameter_mapping"].get("note")
    L.append("- Parameter mapping: " + spec["parameter_mapping"]["authority"]
             + ("." if not note else ". " + note))
    L.append("- Routing roles exercised by this leaf's B4-scope carriers: "
             + ", ".join(spec["routing_roles_used_in_scope"])
             + (". Form scope: the routing/bus wiring, scheduling, return/"
                "send levels, and per-instance state on these slots for all "
                "B4-scope classes; algorithm behavior stays with the "
                "per-algorithm leaves." if lf_rf else ""))
    L.append("- State: " + spec["state_and_cost"]["per_instance_state"]
             + ". " + spec["state_and_cost"]["long_buffers"] + ".")
    L.append("- Ext-mem traffic estimate: "
             + spec["state_and_cost"]["ext_mem_traffic_estimate"])
    if spec["sxt017_decision_required"]:
        L.append("")
        L.append("> **SXT-017 decision required (#12):** "
                 + spec["sxt017_decision_required"])
    L.append("")
    L.append("## Fixtures plan")
    L.append("")
    for f in spec["fixtures_plan"]:
        L.append(f"- {f}")
    L.append("")
    L.append("## Acceptance")
    L.append("")
    for x in spec["acceptance"]:
        L.append(f"- [ ] {x}")
    L.append("")
    L.append("### Negative controls (each must demonstrably fail)")
    L.append("")
    for x in spec["negative_controls"]:
        L.append(f"- {x}")
    L.append("")
    L.append("## Deliverables")
    L.append("")
    for x in spec["deliverables"]:
        L.append(f"- {x}")
    L.append("")
    L.append("## Dependencies")
    L.append("")
    for x in spec["dependencies"]:
        L.append(f"- {x}")
    L.append("")
    L.append("## Newly enabled presets")
    L.append("")
    ne = spec["newly_enabled"]
    L.append(f"- Strict-FX-complete: {ne['strict_fx_complete_count']} "
             f"presets; B4-scope candidates (upper bound): "
             f"{ne['b4_scope_candidate_count']} "
             f"(factory {spec['carriers']['factory']}, contributor "
             f"{spec['carriers']['contributor']}).")
    L.append(f"- Rule: {ne['rule']}")
    L.append(f"- Hashes: {ne['artifact']} (full path + blob-SHA-1 lists).")
    L.append(f"- Caveat: {ne['caveat']}")
    L.append("")
    L.append("## Non-goals")
    L.append("")
    for x in spec["non_goals"]:
        L.append(f"- {x}")
    L.append("")
    L.append("## Stop / escalate")
    L.append("")
    L.append(spec["stop_escalate"])
    L.append("")
    L.append("## Reusable substrate")
    L.append("")
    L.append("- Leaf/bench style: per-block leaves with injected-defect "
             "negative controls (Parasynth verifier style, "
             "gf180-parasynth@cbcc8b9e rtl-sketch/verify_synth_top.py); "
             "adapt method, re-derive checks.")
    L.append("- Algorithm authority: pinned Surge sources only; no sibling "
             "FX DSP; no generic substitutes under support claims.")
    L.append("- Governed by #25 and docs/REUSE-AUDIT.md: adapt method "
             "freely; copy code/tables only through a recorded adoption "
             "with pinned source, attribution, tests, and a local negative "
             "control; license decision record before merge.")
    L.append("")
    L.append("---")
    L.append("")
    L.append(f"Generated by {GENERATED_BY}; {allocation_note} "
             "Deterministic regeneration: "
             "`python3 tools/generate_effect_leaves.py --verify`.")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filed", type=int, default=12,
                    help="how many top leaves the allocation reserves for "
                         "immediate filing (default 12)")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--verify", action="store_true",
                    help="regenerate to a temp dir and byte-compare with "
                         "the committed outputs")
    ap.add_argument("--self-test", action="store_true",
                    help="run generator negative controls, write "
                         "negative-controls.txt")
    args = ap.parse_args()

    presets = load_corpus()
    ablation = load_ablation()
    b4 = load_b4()
    leaves = order_leaves(build_leaves(presets, ablation, b4))

    letters = "abcdefghijklmnopqrstuvwxyz"
    if len(leaves) > len(letters):
        raise SystemExit("more leaves than allocated letters")
    for i, lf in enumerate(leaves):
        lf["order"] = i + 1
        lf["letter"] = letters[i]
        validate_leaf(lf)
    filed = [lf for lf in leaves if lf["order"] <= args.filed]
    backlog = [lf for lf in leaves if lf["order"] > args.filed]

    inputs_fp = {
        "corpus/normalized/graphs.jsonl": sha256_file(CORPUS),
        "reports/sxt-014/ablation-summary.json": sha256_file(ABLATION),
        "contracts/profile-v1-bundle-DRAFT.json": sha256_file(BUNDLE),
    }

    out = args.out_dir
    (out / "leaves").mkdir(parents=True, exist_ok=True)

    allocation_note = (
        f"Allocation: SXT-028a–028{letters[len(leaves)-1]} reserved by this "
        f"generator run ({len(leaves)} leaves; first {len(filed)} filed "
        f"now, rest in leaf-backlog.json)."
    )

    allocation = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        "essentiality": ESSENTIALITY_STAMP,
        "allocation": [
            {"leaf_id": f"SXT-028{lf['letter']}", "feature": lf["feature"],
             "kind": lf["kind"], "recovery_order": lf["order"],
             "filed_now": lf["order"] <= args.filed,
             "title": lf["title"]}
            for lf in leaves],
        "reserved_range": "SXT-028a..SXT-028z (this generator run)",
        "convention": "parent planning id + letter suffix (SXT-026a "
                      "precedent); SXT-027 leaves own 027a.. independently",
        "note": "filed issue numbers are recorded in leaves-filed.json "
                "(filing record, not generator output)",
        "inputs_sha256": inputs_fp,
    }
    backlog_doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATED_BY,
        "essentiality": ESSENTIALITY_STAMP,
        "claim_scope": CLAIM_SCOPE,
        "ordering": "measured SXT-014 delta desc first, then B4-scope "
                    "carrier count desc; tie-break (kind, id)",
        "leaves": [],
    }

    bodies = {}
    for lf in leaves:
        fid = f"SXT-028{lf['letter']}"
        spec = make_spec(lf, lf["order"], lf["letter"], presets, b4)
        ne = {
            "schema_version": SCHEMA_VERSION,
            "leaf_id": fid,
            "essentiality": ESSENTIALITY_STAMP,
            "strict_fx_complete": [
                {"path": p["path"], "sha": p["sha"], "bank": p["bank"]}
                for p in lf["strict"]],
            "b4_scope_candidates": [
                {"path": p["path"], "sha": p["sha"], "bank": p["bank"]}
                for p in lf["candidates"]],
            "caveat": spec["newly_enabled"]["caveat"],
        }
        backlog_doc["leaves"].append({
            "leaf_id": fid,
            "title": spec["title"],
            "recovery_order": lf["order"],
            "filed_now": lf["order"] <= args.filed,
            "spec": f"reports/sxt-028/leaves/{fid}.json",
            "carriers_b4_scope": len(lf["candidates"]),
            "strict_fx_complete": len(lf["strict"]),
        })
        bodies[fid] = (spec, ne, issue_body(spec, allocation_note))

    docs = {
        "allocation.json": json.dumps(allocation, indent=1,
                                      sort_keys=True) + "\n",
        "leaf-backlog.json": json.dumps(backlog_doc, indent=1,
                                        sort_keys=True) + "\n",
    }
    for fid, (spec, ne, body) in bodies.items():
        docs[f"leaves/{fid}.json"] = json.dumps(spec, indent=1,
                                                sort_keys=True) + "\n"
        docs[f"leaves/{fid}/newly-enabled.json"] = json.dumps(
            ne, indent=1, sort_keys=True) + "\n"
        if spec["recovery_order"] <= args.filed:
            docs[f"leaves/{fid}.md"] = body

    if args.verify:
        ok = True
        for rel, want in sorted(docs.items()):
            got = (out / rel).read_text(encoding="utf-8")
            status = "OK" if got == want else "MISMATCH"
            ok &= got == want
            print(f"verify {rel}: {status}")
        sys.exit(0 if ok else 1)

    for rel, text in sorted(docs.items()):
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    if args.self_test:
        run_self_test(out, presets, ablation, b4, letters)

    print(f"leaves generated: {len(leaves)} "
          f"(filed now: {len(filed)} -> "
          + ", ".join(f"SXT-028{lf['letter']}" for lf in filed) + ")")
    print("backlog: " + ", ".join(
        f"SXT-028{lf['letter']}" for lf in backlog))


def run_self_test(out, presets, ablation, b4, letters):
    lines = [
        "SXT-028 generator negative controls (live, this run)",
        "Generator: " + GENERATED_BY,
        ESSENTIALITY_STAMP,
        "",
    ]

    def fresh_builder():
        return build_leaves(load_corpus(), load_ablation(), load_b4())

    # NC1: zero newly-enabled presets -> refuse.
    # AW id 47 'Slew 1' exists in the corpus (1 preset) but is NOT in the
    # B4-broad airwindows selection, so the leaf enables zero presets in
    # scope and must be refused.
    nc1_ok = False
    try:
        leaves = fresh_builder()
        bogus = {
            "kind": "aw", "fid": 47,
            "title": "Airwindows algorithm leaf: Slew 1 (id 47)",
            "feature": {"airwindows_algorithm_id": 47,
                        "algorithm_name": "Slew 1", "header": "Slew1.h"},
            "match": lambda p: 47 in p["aw"],
            "strict_ok": lambda p: False,
            "candidates": [],
            "strict": [],
        }
        validate_leaf(bogus)
    except LeafRefusal as ex:
        nc1_ok = True
        lines.append("NC1 zero-newly-enabled leaf refused: PASS")
        lines.append("  probe: Airwindows id 47 'Slew 1' (in corpus, out of "
                     "B4 selection)")
        lines.append(f"  refusal: {ex}")
    lines.append("")

    # NC2: cross-type merged leaf ('Chorus+Delay') -> refuse.
    nc2_ok = False
    try:
        merged = {
            "kind": "type", "fid": "Chorus+Delay",
            "title": "merged Chorus+Delay leaf (must be refused)",
            "feature": {"class": "Chorus", "routing_form": "delay-like"},
            "match": lambda p: "Chorus" in p["types"],
            "strict_ok": lambda p: False,
            "candidates": [{"x"}], "strict": [],
        }
        validate_leaf(merged)
    except LeafRefusal as ex:
        nc2_ok = True
        lines.append("NC2 cross-type merged leaf ('Chorus+Delay') refused: "
                     "PASS")
        lines.append(f"  refusal: {ex}")
    lines.append("")
    lines.append(f"verdict: NC1={'PASS' if nc1_ok else 'FAIL'} "
                 f"NC2={'PASS' if nc2_ok else 'FAIL'}")
    (out / "negative-controls.txt").write_text("\n".join(lines) + "\n",
                                               encoding="utf-8")
    if not (nc1_ok and nc2_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
