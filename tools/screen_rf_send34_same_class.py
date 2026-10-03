#!/usr/bin/env python3
"""SXT-028l / #322: screen every same-FX-class dual-occupant send3/send4
preset in the committed corpus through the pinned engine's per-scene drift
determinism gate, and record which (if any) can carry a REPEATABLE render of
that routing shape once #12 clears.

Why this exists. #155 item 1a measured `Strynth.fxp` -- the only committed
carrier of the same-class dual-instance shape for routing form rf-send34 --
at scene drift 0.131249994 in both voicing scenes, so no render of it is
repeatable (the harness never seeds engine RNG, oracle/manifest.json). #322
asks for a drift-0 carrier of the SAME shape or, failing that, a bounded
coverage gap. Nothing here zeroes a drift value, seeds RNG, renders audio, or
substitutes a different shape.

What it does:
  1. Enumerates the candidates from corpus/normalized/graphs.jsonl with the
     exact predicate reports/SXT-028l/artifacts/corpus-occupancy.json counts
     (`send3.on && send4.on && send3.tn == send4.tn`) and REFUSES if the count
     disagrees with that record (the denominator must be the committed one).
  2. Re-verifies each candidate's census blob sha1 against the graph and the
     census `content_verified` flag (fail-closed).
  3. LIVE (pinned oracle): checks the engine version carries the pin,
     re-verifies the `.fxp` blob sha1 inside the pinned checkout,
     `loadPatch()`es it (native loader: the normalized state is the
     authoritative one), cross-checks the live FX type at slots 12/13 against
     the graph, and runs `extract_rf_send34_inputs.drift_gate()` -- the SAME
     function the extractor's live leg uses, so a replacement is screened the
     same way the committed carriers are.
  4. Records the routing features that make up Strynth.fxp's shape (scene B
     instantiated, neither slot disabled, neither return muted) and applies a
     declared, mechanical selection rule to name the render carrier; refuses
     if the extractor's CARRIERS does not carry that selection.
  5. Audits SIBLING routing-form leaves' declared carriers (and SXT-028g's
     queued phaser carriers) through the same gate (#322 work item 4). A
     nonzero drift there is a measured finding ROUTED to a follow-up issue,
     never fixed here.

COVERAGE (how many candidates exist / were screened) is reported separately
from the VERDICT (how many have drift 0). The render itself stays BLOCKED on
#12 in every outcome, and drift 0 is necessary, not sufficient, for a
repeatable render (see `drift_gate`).

Writes reports/SXT-028l/artifacts/same-class-carrier-screen.json -- only when
the live leg actually ran; without the oracle the committed record is left
untouched (it is an oracle host's evidence) and the run reports NOT_RUN.

Exit codes: 0 screen ran and a drift-0 candidate carrying the full shape was
selected; 3 screen ran and NO such candidate exists (bounded coverage gap --
record it, never relax the shape); 1 refusal; 2 NOT_RUN (pinned oracle
absent).

Run under the oracle's own interpreter:
  ORACLE_PREBUILT=1 oracle/fetch-and-build.sh   # prints the exports below
  ORACLE_SURGE_DIR=... LD_LIBRARY_PATH=... "$ORACLE_PYTHON" \\
      tools/screen_rf_send34_same_class.py

Original to this repository (Apache-2.0); imports the GPL engine at runtime
only.
"""

import json
import os
import platform
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, REPO)

import extract_rf_send34_inputs as ex  # noqa: E402
from refusal import Refuse  # noqa: E402

ARTIFACTS = os.path.join(REPO, "reports", "SXT-028l", "artifacts")
OUT = os.path.join(ARTIFACTS, "same-class-carrier-screen.json")
RNG_IMPACT = os.path.join(REPO, "reports", "SXT-028-rng", "artifacts",
                          "coverage-impact.json")

SELECTION_RULE = (
    "Among candidates whose drift gate PASSES, keep those that carry EVERY "
    "routing feature of the Strynth.fxp shape -- same FX class in send3 and "
    "send4 (the predicate), scene B instantiated (non-Single scene mode, so "
    "scene B feeds both buses), neither slot disabled by fx_disable bits "
    "12/13, neither return muted -- then take the one with the FEWEST "
    "fx_disable bits set anywhere (the most of the complete wet chain "
    "active), ties broken by corpus path. The FX class itself is NOT part of "
    "the routing shape (this leaf is form scope, not algorithm scope; "
    "model/effects/rf-rf-send34/README.md).")

# #322 work item 4: sibling routing-form leaves whose extractors declare their
# carriers the same way, plus SXT-028g's queued phaser render carriers. Read
# from each module's own declaration rather than copied here.
SIBLING_SOURCES = (
    ("SXT-028d", "rf-global2", "#56", "extract_rf_global2_inputs", "CARRIERS"),
    ("SXT-028h", "rf-bins12", "#60", "extract_rf_bins12_inputs", "CARRIERS"),
    ("SXT-028i", "rf-ains34", "#61", "extract_rf_ains34_inputs", "CARRIERS"),
    ("SXT-028j", "rf-global34", "#62", "extract_rf_global34_inputs",
     "CARRIERS"),
    ("SXT-028g", "type-phaser", "#59", "extract_phaser_inputs", "PRESETS"),
)

# Where the sibling FAILs measured below are owned (filed by #322 work item 4).
SIBLING_FINDING_ISSUE = ("#331 (SXT-028h/028d/028g: declared render carriers "
                         "fail the per-scene drift gate)")

# Sibling leaves NOT re-measured here because they already carry a declared,
# committed drift/repeatability treatment for every drift-bearing preset they
# touch (verified by reading the cited files at this commit).
SIBLINGS_WITH_DECLARED_TREATMENT = {
    "SXT-028c (chorus)": "tools/render_chorus_fixtures.py: issue-named "
                         "carriers refused at extraction (drift != 0); "
                         "Drone Bee refused by the 3x bit-identical render "
                         "gate",
    "SXT-028f (reverb 2)": "tools/render_reverb2_fixtures.py + "
                           "reports/SXT-028f/EVIDENCE.md: Novuo et al. "
                           "REFUSED by the 3x gate; policy question open as "
                           "#310",
    "SXT-028e-sse (distortion SSE)": "tools/render_distortion_sse_fixtures.py: "
                                     "Trance Pluck refused by the static "
                                     "screens (drift)",
    "aw-49 (Airwindows)": "tools/render_aw49_reference.py: declared "
                          "'conditioned-on-tap' repeatability class for "
                          "drift > 0 fixtures (no 3x gate claimed)",
    "SXT-012 pilot fixtures": "fixtures/README.md 'Repeatability and known "
                              "engine variation' + "
                              "reports/sxt-012/repeatability.json",
    "voice/oscillator leaves": "model/oscillators/*/fixture_config.py, "
                               "model/voice/playmode/fixture_config.py: a "
                               "declared `drift_zero` component-fixture "
                               "adaptation (not a preset render)",
}


def _bits(mask):
    return [b for b in range(32) if (mask >> b) & 1]


def corpus_candidates():
    """Every committed corpus preset carrying the same-class dual-instance
    shape, in corpus order. Pure function of graphs.jsonl."""
    out = []
    with open(ex.GRAPHS, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            fx = {e.get("r"): e for e in g["g"]["fx"]}
            a, b = fx.get("send3", {}), fx.get("send4", {})
            if not (a.get("on", 0) and b.get("on", 0)
                    and a.get("tn") == b.get("tn")):
                continue
            fxd = g["g"].get("fxd", 0)
            out.append({
                "path": g["p"],
                "graphs_blob_sha1": g.get("sha"),
                "fx_class": a.get("tn"),
                "fx_type_id": a.get("t"),
                "scene_mode": g["g"].get("smn"),
                "scene_b_instantiated": g["g"].get("smn") != "Single",
                "fx_bypass_name": g["g"].get("fxbn"),
                "send_stage_runs": g["g"].get("fxb", 0) == 0,
                "fx_disable_mask": fxd,
                "fx_disable_bits": _bits(fxd),
                "send3_disabled": bool((fxd >> ex.FXSLOT_SEND3) & 1),
                "send4_disabled": bool((fxd >> ex.FXSLOT_SEND4) & 1),
                "send3_return_level": a.get("rl"),
                "send4_return_level": b.get("rl"),
            })
    return out


def check_denominator(cands):
    """The candidate count must equal what the committed occupancy record
    counts for the same predicate -- recomputed AND as committed."""
    fresh = ex.corpus_occupancy()["both_buses_occupied_same_fx_class"]
    with open(ex.OCCUPANCY, encoding="utf-8") as f:
        committed = json.load(f)["both_buses_occupied_same_fx_class"]
    if not (len(cands) == fresh == committed):
        raise Refuse(f"same-class candidate count {len(cands)} disagrees with "
                     f"corpus-occupancy.json (fresh {fresh}, committed "
                     f"{committed}); refusing to screen a different "
                     f"denominator")
    return {"candidates_enumerated": len(cands),
            "corpus_occupancy_fresh": fresh,
            "corpus_occupancy_committed": committed}


def census_check(cand):
    row = ex.census_row(cand["path"])
    if row["git_blob_sha1"] != cand["graphs_blob_sha1"]:
        raise Refuse(f"census/graphs blob sha1 mismatch for {cand['path']}: "
                     f"census={row['git_blob_sha1']} "
                     f"graphs={cand['graphs_blob_sha1']}")
    if row["content_verified"] != "True":
        raise Refuse(f"census content not verified: {cand['path']}")
    return row["git_blob_sha1"]


def rng_survey_context():
    """Per-path lookup into the committed SXT-028-rng coverage-impact record.
    CONTEXT only: it is not part of the drift gate and not a verdict."""
    if not os.path.exists(RNG_IMPACT):
        return None, None
    with open(RNG_IMPACT, encoding="utf-8") as f:
        d = json.load(f)
    by_path = {a["path"]: [c["fx_type_name"] for c in a["classes"]]
               for a in d["affected_presets"]}
    not_surveyed = sorted(n["fx_type_name"] for n in d.get("not_surveyed", [])
                          if n.get("status") == "NOT_RUN")
    return by_path, not_surveyed


def open_oracle():
    """(surgepy, oc) or raises _NotRun. A pinned-oracle mismatch REFUSES."""
    try:
        import oracle_common as oc  # noqa: PLC0415
        surgepy = oc.import_surgepy()
    except Exception as e:  # environment-dependent
        raise _NotRun(f"surgepy unavailable (pinned oracle not built or not "
                      f"installed in this environment): {e}") from e
    oc.apply_engine_env()
    version = surgepy.getVersion()
    if ex.ENGINE_PIN[:9] not in version:
        raise Refuse(f"live surgepy reports {version!r}, which does not carry "
                     f"the pinned commit {ex.ENGINE_PIN[:9]}")
    return surgepy, oc


class _NotRun(Exception):
    pass


def live_load(surgepy, oc, rel, declared_sha1):
    abs_path = os.path.join(oc.engine_dir(), rel)
    if not os.path.exists(abs_path):
        raise Refuse(f"pinned engine checkout does not carry {rel}")
    on_disk = oc.git_blob_sha1(abs_path)
    if on_disk != declared_sha1:
        raise Refuse(f"pinned-checkout blob sha1 mismatch for {rel}: "
                     f"on disk={on_disk} declared={declared_sha1}")
    s = surgepy.createSurge(ex.SAMPLE_RATE)
    if not s.loadPatch(abs_path):
        raise Refuse(f"loadPatch failed in the pinned engine: {rel}")
    return s, s.getPatch(), on_disk


def screen_candidate(surgepy, oc, cand, census_sha1, rng_by_path):
    s, patch, on_disk = live_load(surgepy, oc, cand["path"], census_sha1)
    live_types = {}
    for role, slot in (("send3", ex.FXSLOT_SEND3), ("send4", ex.FXSLOT_SEND4)):
        tid = round(s.getParamVal(patch["fx"][slot]["type"]))
        if tid != cand["fx_type_id"]:
            raise Refuse(f"live {role} fx type {tid} disagrees with "
                         f"graphs.jsonl {cand['fx_type_id']} for "
                         f"{cand['path']}")
        live_types[role] = {"type_id": tid,
                            "type_display": s.getParamDisplay(
                                patch["fx"][slot]["type"])}
    gate = ex.drift_gate(s, patch)
    full_shape = (cand["scene_b_instantiated"] and cand["send_stage_runs"]
                  and not cand["send3_disabled"]
                  and not cand["send4_disabled"]
                  and cand["send3_return_level"] != 0.0
                  and cand["send4_return_level"] != 0.0)
    rec = dict(cand)
    rec.update({
        "census_blob_sha1_verified": census_sha1,
        "pinned_checkout_blob_sha1": on_disk,
        "live_send_slot_types": live_types,
        "determinism_gate": gate,
        "carries_every_strynth_routing_feature": full_shape,
    })
    if rng_by_path is not None:
        rec["sxt028_rng_survey_context"] = {
            "listed_as_affected": cand["path"] in rng_by_path,
            "affected_classes": rng_by_path.get(cand["path"], []),
            "note": "CONTEXT ONLY (reports/SXT-028-rng/artifacts/"
                    "coverage-impact.json); not part of the drift gate",
        }
    return rec


def select(screened):
    pool = [c for c in screened
            if c["determinism_gate"]["status"] == "PASS"
            and c["carries_every_strynth_routing_feature"]]
    pool.sort(key=lambda c: (len(c["fx_disable_bits"]), c["path"]))
    return pool[0] if pool else None


def occupant_class_bound(chosen, strynth, screened):
    """State, from the measured data, whether the selected carrier also keeps
    Strynth.fxp's OCCUPANT CLASS (not part of the routing shape, but part of
    what Strynth exercised), and whether any drift-0 candidate could have."""
    if chosen is None or strynth is None:
        return []
    if chosen["fx_class"] == strynth["fx_class"]:
        return [(f"The selected carrier keeps Strynth.fxp's occupant class "
                 f"({chosen['fx_class']}) as well as its routing shape.")]
    same_cls = [c for c in screened if c["fx_class"] == strynth["fx_class"]
                and c["determinism_gate"]["status"] == "PASS"]
    same_cls_full = [c["path"] for c in same_cls
                     if c["carries_every_strynth_routing_feature"]]
    return [(
        f"The selected carrier hosts {chosen['fx_class']}, not "
        f"{strynth['fx_class']}, in both buses: the routing shape is the "
        f"same, the occupant class Strynth.fxp exercised is not. Drift-0 "
        f"candidates with {strynth['fx_class']} in both buses: "
        f"{[c['path'] for c in same_cls]}; of those, carrying every Strynth "
        f"routing feature (scene B feeding both buses, neither slot "
        f"disabled, neither return muted): {same_cls_full}.")]


def sibling_audit(surgepy, oc):
    """#322 work item 4: run the same gate over sibling leaves' declared
    carriers. Findings are ROUTED (see EVIDENCE.md §0g), never fixed here."""
    out = []
    for leaf, form, issue, mod_name, attr in SIBLING_SOURCES:
        mod = __import__(mod_name)
        decl = getattr(mod, attr)
        if isinstance(decl, dict):      # SXT-028g PRESETS: {slug: path}
            items = [{"slug": k, "path": v, "declared_sha1": None}
                     for k, v in decl.items()]
        else:
            items = [{"slug": c["slug"], "path": c["path"],
                      "declared_sha1": c.get("declared_sha1")} for c in decl]
        for it in items:
            sha = it["declared_sha1"] or ex.census_row(it["path"])[
                "git_blob_sha1"]
            s, patch, _ = live_load(surgepy, oc, it["path"], sha)
            gate = ex.drift_gate(s, patch)
            out.append({"leaf": leaf, "routing_form_or_leaf": form,
                        "leaf_issue": issue,
                        "declared_in": f"tools/{mod_name}.py::{attr}",
                        "slug": it["slug"], "path": it["path"],
                        "determinism_gate": gate})
    return out


def main():
    cands = corpus_candidates()
    try:
        denom = check_denominator(cands)
        census = {c["path"]: census_check(c) for c in cands}
    except Refuse as e:
        print(f"REFUSED: {e}")
        return 1
    try:
        surgepy, oc = open_oracle()
    except _NotRun as e:
        print(f"same-class screen: NOT_RUN ({e}); {OUT} left untouched")
        return 2
    except Refuse as e:
        print(f"REFUSED: {e}")
        return 1

    rng_by_path, rng_not_surveyed = rng_survey_context()
    try:
        screened = [screen_candidate(surgepy, oc, c, census[c["path"]],
                                     rng_by_path) for c in cands]
        siblings = sibling_audit(surgepy, oc)
    except Refuse as e:
        print(f"REFUSED: {e}")
        return 1

    passing = [c["path"] for c in screened
               if c["determinism_gate"]["status"] == "PASS"]
    failing = [c["path"] for c in screened
               if c["determinism_gate"]["status"] != "PASS"]
    chosen = select(screened)

    carriers_by_path = {c["path"]: c for c in ex.CARRIERS}
    if chosen is not None:
        adopted = carriers_by_path.get(chosen["path"])
        if adopted is None or "#322" not in adopted["carrier_source"]:
            print(f"REFUSED: the selection rule names {chosen['path']}, but "
                  f"tools/extract_rf_send34_inputs.py::CARRIERS does not "
                  f"carry it as the #322 addition")
            return 1
    strynth = next((c for c in screened if c["path"].endswith(
        "Exquis MPE/Strings/Strynth.fxp")), None)

    doc = {
        "schema_version": 1,
        "leaf": "SXT-028l",
        "routing_form": "rf-send34",
        "issue": "#322",
        "shape": ex.SAME_CLASS_SHAPE,
        "claim_scope": "ENGINE-SIDE drift screen only. Nothing was rendered. "
                       "Establishes NO model-vs-engine agreement, NO "
                       "preset-support claim, NO musical-quality claim and "
                       "NO repeatability claim: drift 0 is a necessary, not "
                       "a sufficient, condition for a repeatable render.",
        "engine": {"pin": ex.ENGINE_PIN,
                   "surgepy_version": surgepy.getVersion(),
                   "sample_rate": ex.SAMPLE_RATE,
                   "oracle_surge_dir": oc.engine_dir()},
        "host": {"platform": platform.platform(),
                 "machine": platform.machine(),
                 "python": platform.python_version()},
        "coverage": {
            "what": "how many same-class dual-occupant presets the corpus "
                    "holds and how many were screened live -- reported "
                    "separately from the verdict below",
            "candidates_in_corpus": len(cands),
            "candidates_screened": len(screened),
            "candidates_not_screened": len(cands) - len(screened),
            "denominator_check": denom,
        },
        "verdict": {
            "what": "how many screened candidates have per-scene drift 0 in "
                    "every voicing scene (extract_rf_send34_inputs."
                    "drift_gate)",
            "drift_zero": len(passing),
            "drift_nonzero": len(failing),
            "drift_zero_paths": passing,
            "drift_nonzero_paths": failing,
        },
        "candidates": screened,
        "selection_rule": SELECTION_RULE,
        "selected_render_carrier": None if chosen is None else {
            "path": chosen["path"],
            "slug": carriers_by_path[chosen["path"]]["slug"],
            "carrier_source": carriers_by_path[chosen["path"]]
            ["carrier_source"],
        },
        "strynth_finding_retained": None if strynth is None else {
            "path": strynth["path"],
            "determinism_gate": strynth["determinism_gate"]["status"],
            "drift_per_voicing_scene":
                strynth["determinism_gate"]["drift_per_voicing_scene"],
            "kept_in_extractor_carriers":
                strynth["path"] in carriers_by_path,
            "render_eligible": strynth["determinism_gate"]["status"] == "PASS",
        },
        "outcome": ("CARRIER_ADOPTED" if chosen is not None else
                    "BOUNDED_GAP"),
        "same_class_render_leg": "BLOCKED (#12) -- the render of this shape "
                                 "needs the SXT-017 send-level decision in "
                                 "every outcome; an eligible carrier is not a "
                                 "rendered one",
        "bounds": occupant_class_bound(chosen, strynth, screened) + [
            ("drift 0 does not exclude other engine RNG paths (free-running "
             "oscillator phase, RNG-driven FX classes; fixtures/README.md, "
             "oracle/manifest.json fx_modulation_randomness, #310); only the "
             "empirical 3x render gate of the (BLOCKED, #12) render leg can."),
        ] + ([(f"The SXT-028-rng survey lists these FX classes NOT_RUN: "
               f"{rng_not_surveyed}.")] if rng_not_surveyed else []),
        "sibling_render_carrier_audit": {
            "what": "#322 work item 4: sibling leaves' declared carriers "
                    "through the same drift gate. A FAIL here is a measured "
                    "finding ROUTED to a follow-up issue (EVIDENCE.md §0g), "
                    "never fixed in this leaf.",
            "carriers": siblings,
            "failing": [f"{r['leaf']}:{r['slug']}" for r in siblings
                        if r["determinism_gate"]["status"] != "PASS"],
            "routed_to": SIBLING_FINDING_ISSUE,
            "not_re_measured_declared_treatment":
                SIBLINGS_WITH_DECLARED_TREATMENT,
        },
    }
    os.makedirs(ARTIFACTS, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {OUT}")
    print(f"coverage: {len(screened)}/{len(cands)} same-class candidates "
          f"screened; verdict: {len(passing)} drift 0, {len(failing)} "
          f"nonzero")
    for c in screened:
        print(f"  {c['determinism_gate']['status']:4} "
              f"{c['determinism_gate']['drift_per_voicing_scene']} "
              f"{c['fx_class']:7} {c['scene_mode']:6} {c['path']}")
    print(f"outcome: {doc['outcome']}"
          + (f" -> {chosen['path']}" if chosen else ""))
    print(f"sibling audit FAIL: {doc['sibling_render_carrier_audit']['failing']}")
    return 0 if chosen is not None else 3


if __name__ == "__main__":
    sys.exit(main())
