#!/usr/bin/env python3
"""SXT-017 DRAFT profile predictor (bundle stage of issue #12).

Deterministically predicts, per corpus entry, whether a candidate feature
bundle would structurally support the preset's ORIGINAL normalized graph:

    supported              every bundle gate passes on the original graph
    adapted-not-predicted  runs only with a disclosed edit class (unison or
                           polylimit reduction); NEVER counted as supported
    unsupported            a required feature/resource is outside the bundle
                           (machine-readable reason codes)
    unresolved             the graph cannot be evaluated yet (loader failure,
                           or declared data-gap policy "unresolved")

THIS IS A DRAFT-STAGE PREDICTION TOOL (issue #12 bundle stage; freeze is
BLOCKED on SXT-013 human listening, SXT-014 listening labels, and SXT-016
probe numbers). It makes NO fidelity claim, NO preset-quality claim, NO
technology claim, and NO hardware claim:

  - cycle closure is NOT a gate: every SXT-015 cycle number is cost profile
    `placeholder-v0` and supports no technology claim; per-preset cost/RAM/
    bandwidth columns are published with a [PENDING-SXT-016] marker instead;
  - "supported" means only "structurally within this DRAFT bundle's declared
    gates/budgets"; it is not a fit claim on cycles (no measured clock basis
    yet) and not a fidelity or listening outcome.

Fail-closed discipline:
  - unknown bundle keys, unknown allowlist names, unknown slate entries, and
    integrity mismatches REFUSE the run (exit 2); nothing is silently ignored;
  - every excluded preset carries machine-readable reasons; adapted presets
    are never merged into the supported count.

Determinism: same graphs bytes + same bundle spec => byte-identical output
(sorted keys, fixed separators, floats rounded to 6 decimals, no timestamps).

Provenance/licensing: original to this repository (Apache-2.0 per LICENSE);
stdlib only. It imports this repository's own SXT-015 accounting model and
reads the committed SXT-011 graphs; no Surge code, tables, or payloads are
copied or embedded.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from model.resources.accounting import MODEL_VERSION, account_graph  # noqa: E402
from model.resources.params import REG  # noqa: E402

TOOL_VERSION = "sxt-017-predict/1.0.0"
BUNDLE_SPEC_SCHEMA = "sxt-017-bundle-spec/1.0.0"

SUPPORTED = "supported"
ADAPTED = "adapted-not-predicted"
UNSUPPORTED = "unsupported"
UNRESOLVED = "unresolved"
ALL_STATUS = (SUPPORTED, ADAPTED, UNSUPPORTED, UNRESOLVED)
ADAPTATION_CODES = ("polylimit_reduction_required", "unison_reduction_required")

ENGINE_PIN = "surge-synthesizer/surge@58914e59c608ed4384ba6002e44c3465c58b2e71"
VALID_SAMPLE_RATE_HZ = 48000
VALID_WORD_LENGTH_POLICIES = ("float32-model-placeholder-pending-sxt-016",)
VALID_SCENE_MODES = (0, 1, 2, 3)
VALID_SCENE_MODE_NAMES = {0: "single", 1: "split", 2: "dual", 3: "chsplit"}

KNOWN_TOP_KEYS = {"schema_version", "artifact", "status", "bundles"}
KNOWN_BUNDLE_KEYS = {"bundle_id", "status", "spec"}
KNOWN_SPEC_KEYS = {
    "oscillator_allowlist", "wavetable_assets", "filter_type_allowlist",
    "waveshaper_policy", "fx_type_allowlist", "airwindows_policy",
    "fx_instance_limit", "scene_modes", "voice_pool_limit", "unison_cap",
    "poly_gate", "sample_rate_hz", "word_length_policy", "budgets",
    "data_gap_policies",
}
KNOWN_BUDGET_KEYS = {
    "on_chip_ram_bytes", "external_writable_bytes",
    "external_bandwidth_bytes_per_s", "cycle_closure",
}
KNOWN_GAP_POLICY_KEYS = {
    "mseg_formula_lfo_contents", "slfo_definitions", "filter_subtypes",
}
VALID_POLY_GATES = ("adapted_beyond_pool",)
VALID_WAVESHAPER_POLICIES = ("none", "all")
VALID_AW_MODES = ("none", "selected", "all_observed")
VALID_GAP_POLICIES = {
    "mseg_formula_lfo_contents": ("unresolved",),
    "slfo_definitions": ("caveat_budget_risk",),
    "filter_subtypes": ("engine_declared_set",),
}
VALID_CYCLE_CLOSURE = ("not_gated_pending_sxt_016",)


class Refuse(Exception):
    """Fail-closed refusal: bad spec, tampered input, unknown key."""


def _r6(x):
    return round(float(x), 6)


def _rel(path_str):
    """Repo-relative display path (byte-deterministic across machines)."""
    p = Path(path_str)
    try:
        return str(p.resolve().relative_to(Path(REPO).resolve()))
    except ValueError:
        return str(p)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _require(cond, msg):
    if not cond:
        raise Refuse(msg)


def load_bundle_file(path):
    """Load + strictly validate the bundle file. Unknown keys REFUSE."""
    raw = json.loads(Path(path).read_text())
    keys = set(raw)
    _require(keys == KNOWN_TOP_KEYS,
             "REFUSING bundle file %s: top-level keys %s; expected exactly %s "
             "(unknown keys are rejected, never ignored)"
             % (path, sorted(keys), sorted(KNOWN_TOP_KEYS)))
    _require(raw["schema_version"] == BUNDLE_SPEC_SCHEMA,
             "REFUSING bundle file %s: schema_version %r != %r"
             % (path, raw["schema_version"], BUNDLE_SPEC_SCHEMA))
    _require(raw["status"] == "DRAFT-NOT-FROZEN",
             "REFUSING bundle file %s: this predictor accepts DRAFT-NOT-FROZEN "
             "bundles only (freeze is SXT-017's human-gated step)" % path)
    _require(isinstance(raw["bundles"], list) and raw["bundles"],
             "REFUSING bundle file %s: 'bundles' must be a non-empty list" % path)
    bundles = {}
    for b in raw["bundles"]:
        _require(set(b) == KNOWN_BUNDLE_KEYS,
                 "REFUSING bundle %r: keys %s; expected exactly %s"
                 % (b.get("bundle_id"), sorted(b), sorted(KNOWN_BUNDLE_KEYS)))
        _require(b["status"] == "DRAFT-NOT-FROZEN",
                 "REFUSING bundle %r: status must be DRAFT-NOT-FROZEN"
                 % b.get("bundle_id"))
        _require(b["bundle_id"] not in bundles,
                 "REFUSING: duplicate bundle_id %r" % b["bundle_id"])
        bundles[b["bundle_id"]] = b["spec"]
    return raw, bundles


def validate_spec(spec, observed):
    """Validate one bundle spec against the exact key set + the vocabulary
    observed in graphs.jsonl. Unknown keys/names/values REFUSE."""
    keys = set(spec)
    _require(keys == KNOWN_SPEC_KEYS,
             "REFUSING bundle spec: keys %s; expected exactly %s (unknown keys "
             "are rejected, never ignored)" % (sorted(keys), sorted(KNOWN_SPEC_KEYS)))
    for field in ("oscillator_allowlist", "fx_type_allowlist"):
        val = spec[field]
        _require(isinstance(val, list) and all(isinstance(x, str) for x in val),
                 "REFUSING: %s must be a list of engine display-name strings" % field)
        unknown = sorted(set(val) - observed[field])
        _require(not unknown,
                 "REFUSING: %s contains names not observed in graphs.jsonl: %s; "
                 "valid names: %s" % (field, unknown, sorted(observed[field])))
    fu = spec["filter_type_allowlist"]
    if isinstance(fu, str):
        _require(fu == "all",
                 "REFUSING: filter_type_allowlist must be 'all' or a list of "
                 "names (got %r)" % fu)
    else:
        _require(isinstance(fu, list) and all(isinstance(x, str) for x in fu),
                 "REFUSING: filter_type_allowlist must be 'all' or a name list")
        unknown = sorted(set(fu) - observed["filter_type_allowlist"])
        _require(not unknown,
                 "REFUSING: filter_type_allowlist contains names not observed in "
                 "graphs.jsonl: %s; valid names: %s"
                 % (unknown, sorted(observed["filter_type_allowlist"])))
    ws = spec["waveshaper_policy"]
    _require(ws in VALID_WAVESHAPER_POLICIES,
             "REFUSING: waveshaper_policy %r not in %s"
             % (ws, VALID_WAVESHAPER_POLICIES))
    aw = spec["airwindows_policy"]
    _require(isinstance(aw, dict) and set(aw) == {"mode", "selected_algorithm_ids"},
             "REFUSING: airwindows_policy must have exactly keys "
             "{mode, selected_algorithm_ids}")
    _require(aw["mode"] in VALID_AW_MODES,
             "REFUSING: airwindows mode %r not in %s" % (aw["mode"], VALID_AW_MODES))
    _require(isinstance(aw["selected_algorithm_ids"], list),
             "REFUSING: selected_algorithm_ids must be a list")
    if aw["mode"] == "selected":
        bad = sorted(set(aw["selected_algorithm_ids"]) - observed["aw_ids"])
        _require(not bad,
                 "REFUSING: airwindows selected ids not observed in graphs.jsonl: %s"
                 % bad)
    else:
        _require(aw["selected_algorithm_ids"] == [],
                 "REFUSING: selected_algorithm_ids must be [] unless mode is "
                 "'selected'")
    lim = spec["fx_instance_limit"]
    _require(isinstance(lim, int) and not isinstance(lim, bool) and 1 <= lim <= 16,
             "REFUSING: fx_instance_limit must be an int in 1..16 (got %r)" % (lim,))
    sm = spec["scene_modes"]
    _require(isinstance(sm, list) and sm and
             all(x in VALID_SCENE_MODES for x in sm) and len(set(sm)) == len(sm),
             "REFUSING: scene_modes must be a duplicate-free subset of %s"
             % (VALID_SCENE_MODES,))
    pool = spec["voice_pool_limit"]
    _require(isinstance(pool, int) and not isinstance(pool, bool) and 1 <= pool <= 32,
             "REFUSING: voice_pool_limit must be an int in 1..32 (got %r)" % (pool,))
    uni = spec["unison_cap"]
    _require(isinstance(uni, int) and not isinstance(uni, bool) and 1 <= uni <= 16,
             "REFUSING: unison_cap must be an int in 1..16 (MAX_UNISON=16; got %r)"
             % (uni,))
    _require(spec["poly_gate"] in VALID_POLY_GATES,
             "REFUSING: poly_gate %r not in %s; any other policy is a contract "
             "revision and must go through a new bundle version"
             % (spec["poly_gate"], VALID_POLY_GATES))
    _require(spec["sample_rate_hz"] == VALID_SAMPLE_RATE_HZ,
             "REFUSING: sample_rate_hz must be %d (engine pin); any rate change "
             "requires a new census and reference baseline (plan section 3)"
             % VALID_SAMPLE_RATE_HZ)
    _require(spec["word_length_policy"] in VALID_WORD_LENGTH_POLICIES,
             "REFUSING: word_length_policy %r not in %s"
             % (spec["word_length_policy"], VALID_WORD_LENGTH_POLICIES))
    budgets = spec["budgets"]
    _require(set(budgets) == KNOWN_BUDGET_KEYS,
             "REFUSING: budgets keys %s; expected exactly %s"
             % (sorted(budgets), sorted(KNOWN_BUDGET_KEYS)))
    for k in ("on_chip_ram_bytes", "external_writable_bytes",
              "external_bandwidth_bytes_per_s"):
        _require(isinstance(budgets[k], int) and budgets[k] > 0,
                 "REFUSING: budgets.%s must be a positive int" % k)
    _require(budgets["cycle_closure"] in VALID_CYCLE_CLOSURE,
             "REFUSING: budgets.cycle_closure must be in %s (placeholder-v0 "
             "cycle numbers support no gate; SXT-016 must replace the profile "
             "first)" % (VALID_CYCLE_CLOSURE,))
    gaps = spec["data_gap_policies"]
    _require(set(gaps) == KNOWN_GAP_POLICY_KEYS,
             "REFUSING: data_gap_policies keys %s; expected exactly %s"
             % (sorted(gaps), sorted(KNOWN_GAP_POLICY_KEYS)))
    for k, allowed in VALID_GAP_POLICIES.items():
        _require(gaps[k] in allowed,
                 "REFUSING: data_gap_policies.%s=%r not in %s"
                 % (k, gaps[k], allowed))
    return spec


def load_graphs(path):
    """Load graphs.jsonl; return (lines, observed vocabulary, file sha256)."""
    lines = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                lines.append(json.loads(ln))
    observed = {
        "oscillator_allowlist": set(), "filter_type_allowlist": set(),
        "fx_type_allowlist": set(), "aw_ids": set(),
    }
    for d in lines:
        if d.get("st") != "normalized" or "g" not in d:
            continue
        g = d["g"]
        for sc in g.get("sc", []):
            for o in sc.get("osc", []):
                observed["oscillator_allowlist"].add(o.get("tn"))
            for fu in sc.get("fu", []):
                observed["filter_type_allowlist"].add(fu.get("tn"))
        for s in g.get("fx", []):
            if s.get("on"):
                observed["fx_type_allowlist"].add(s.get("tn"))
                if "aw" in s:
                    observed["aw_ids"].add(s["aw"])
    for k in observed:
        observed[k].discard(None)
    return lines, observed, _sha256_file(path)


def load_slates(slate_paths, by_path):
    """Load candidate slates; verify every candidate against the graphs.

    Any unknown path or blob-SHA mismatch REFUSES the run (integrity gate)."""
    out = {}
    for sp in slate_paths:
        s = json.loads(Path(sp).read_text())
        label = s.get("artifact") or Path(sp).stem
        cands = s.get("candidates")
        _require(isinstance(cands, list) and cands,
                 "REFUSING slate %s: no candidates list" % sp)
        paths = set()
        for c in cands:
            cid, csha = c.get("id"), c.get("census_blob_sha1")
            _require(cid in by_path,
                     "REFUSING slate %s: candidate %r not present in graphs.jsonl"
                     % (sp, cid))
            _require(by_path[cid]["sha"] == csha,
                     "REFUSING slate %s: census blob SHA mismatch for %r "
                     "(slate %r vs graphs %r)"
                     % (sp, cid, csha, by_path[cid]["sha"]))
            paths.add(cid)
        out[label] = {"label": label, "total": len(paths), "paths": paths}
    return out


def predict_line(line, spec):
    """Evaluate one graphs.jsonl line against one validated bundle spec.

    Returns (status, reasons, columns). Reasons are machine-readable
    {code, detail} objects in fixed evaluation order."""
    reasons = []

    def add(code, **detail):
        item = {"code": code}
        if detail:
            item["detail"] = detail
        reasons.append(item)

    if line.get("st") != "normalized" or "g" not in line:
        add("loader_analysis_failure", **(line.get("why") or {}))
        return UNRESOLVED, reasons, None

    g = line["g"]

    # --- declared data-gap policy (data completeness precedes features) ------
    if any("gap" in l for sc in g.get("sc", []) for l in sc.get("lfo", [])):
        add("mseg_or_formula_contents_not_exported",
            policy=spec["data_gap_policies"]["mseg_formula_lfo_contents"])

    # --- accounting (SXT-015 model; supplies structural accounts + columns) ---
    with REG.override("voice_pool_limit", spec["voice_pool_limit"]):
        acc = account_graph(line, fx_instance_limit=spec["fx_instance_limit"])
    _require(acc["status"] in ("fit", "rejected"),
             "REFUSING: accounting returned %r for %s"
             % (acc["status"], line.get("p")))

    # fail-closed on structure the model cannot account
    for rej in acc["rejections"]:
        if rej["code"] == "scene_mode_unaccountable":
            add("scene_mode_unaccountable", sm=g.get("sm"))
        elif rej["code"] == "event_queue_overflow":
            add("event_queue_overflow")
        # budget_overflow / ext_bandwidth_overflow are NOT gates here: their
        # SXT-015 basis is placeholder pending SXT-016; they are published as
        # columns/caveats instead.

    # --- external audio input dependency --------------------------------------
    if "audio_input" in g.get("dep", []):
        add("audio_input_dependency")

    # --- scene mode gate --------------------------------------------------------
    sm = g.get("sm")
    if sm not in spec["scene_modes"]:
        add("scene_mode_not_in_bundle",
            scene_mode=sm, scene_mode_name=VALID_SCENE_MODE_NAMES.get(sm),
            bundle_scene_modes=sorted(spec["scene_modes"]))

    # --- voice-feature gates (from the accounting scene accounts) ---------------
    osc_bad, wt_needed, uni_max = set(), False, 1
    for scene in acc["voice"]["scenes"]:
        for o in scene["osc_slots"]:
            if not o["active"]:
                continue
            if o["type_name"] not in spec["oscillator_allowlist"]:
                osc_bad.add(o["type_name"])
            if o["wavetable"] and not spec["wavetable_assets"]:
                wt_needed = True
            if o["unison"]:
                uni_max = max(uni_max, o["unison"])
    if osc_bad:
        add("oscillator_family_not_in_bundle",
            families=sorted(osc_bad),
            bundle=sorted(spec["oscillator_allowlist"]))
    if wt_needed:
        add("wavetable_assets_not_in_bundle")

    fu_bad = set()
    for scene in acc["voice"]["scenes"]:
        for f in scene["filter_units"]:
            if f["active"]:
                tn = f["type_name"]
                allowed = (spec["filter_type_allowlist"] == "all"
                           or tn in spec["filter_type_allowlist"])
                if not allowed:
                    fu_bad.add(tn)
    if fu_bad:
        add("filter_algorithm_not_in_bundle", filter_types=sorted(fu_bad))

    if spec["waveshaper_policy"] == "none":
        ws_bad = sorted({s["waveshaper_type"] for s in acc["voice"]["scenes"]
                         if s["waveshaper_active"]})
        if ws_bad:
            add("waveshaper_not_in_bundle", waveshaper_types=ws_bad)

    # --- FX gates (enabled instances; routing-inactive slots hold state but
    # --- never process, matching the SXT-015 accounting rule) -------------------
    aw_mode = spec["airwindows_policy"]["mode"]
    fx_bad, aw_bad = set(), set()
    by_alg = {s["aw"]: s.get("awn") for s in g.get("fx", []) if "aw" in s}
    for e in acc["fx_instances"]:
        if not e["enabled_by_fxd"]:
            continue
        tn = e["class"]
        if tn not in spec["fx_type_allowlist"]:
            fx_bad.add(tn)
        if tn == "Airwindows":
            alg = e.get("airwindows_algorithm")
            if aw_mode == "none" or (
                    aw_mode == "selected"
                    and alg not in spec["airwindows_policy"]["selected_algorithm_ids"]):
                aw_bad.add((alg, by_alg.get(alg)))
    if aw_bad:
        add("airwindows_algorithm_not_selected",
            algorithms=sorted("%s (%s)" % (a, n) for a, n in aw_bad),
            mode=aw_mode)
    if fx_bad:
        add("effect_class_not_in_bundle",
            effect_classes=sorted(fx_bad),
            bundle=sorted(spec["fx_type_allowlist"]))

    # --- instance limit (translated from the SXT-015 accounting rejection) ------
    for rej in acc["rejections"]:
        if rej["code"] == "fx_instance_overflow":
            add("fx_instance_overflow",
                enabled_instances=rej["detail"]["enabled_instances"],
                limit=rej["detail"]["limit"])

    # --- adaptation-class gates (disclosed-edit requirements) -------------------
    if spec["poly_gate"] == "adapted_beyond_pool":
        poly = g.get("poly", REG.polylimit_default)
        if poly > spec["voice_pool_limit"]:
            add("polylimit_reduction_required",
                stored_polylimit=poly,
                bundle_voice_pool=spec["voice_pool_limit"])
    if uni_max > spec["unison_cap"]:
        add("unison_reduction_required",
            max_effective_unison=uni_max,
            bundle_unison_cap=spec["unison_cap"])

    # --- memory capacity/bandwidth gates (bundle-declared budgets) --------------
    mem = acc["memory"]
    if mem["on_chip_state_bytes"] > spec["budgets"]["on_chip_ram_bytes"]:
        add("on_chip_ram_exceeded",
            required_bytes=mem["on_chip_state_bytes"],
            budget_bytes=spec["budgets"]["on_chip_ram_bytes"],
            basis="sxt-015 placeholder state model; pending SXT-016")
    if mem["external_writable_state_bytes"] > spec["budgets"]["external_writable_bytes"]:
        add("external_writable_capacity_exceeded",
            required_bytes=mem["external_writable_state_bytes"],
            budget_bytes=spec["budgets"]["external_writable_bytes"])
    if mem["ext_traffic_bytes_per_s"] > spec["budgets"]["external_bandwidth_bytes_per_s"]:
        add("external_bandwidth_exceeded",
            required_bytes_per_s=mem["ext_traffic_bytes_per_s"],
            budget_bytes_per_s=spec["budgets"]["external_bandwidth_bytes_per_s"],
            basis="placeholder bandwidth budget; pending SXT-016")

    # --- status precedence: unresolved > unsupported > adapted > supported ------
    if any(r["code"] in ("loader_analysis_failure", "scene_mode_unaccountable",
                         "event_queue_overflow") for r in reasons):
        status = UNRESOLVED
    elif any(r["code"] == "mseg_or_formula_contents_not_exported" for r in reasons):
        status = UNRESOLVED
    elif reasons:
        status = UNSUPPORTED
        if all(r["code"] in ADAPTATION_CODES for r in reasons):
            status = ADAPTED
    else:
        status = SUPPORTED

    columns = {
        "cost_cycles_per_frame_placeholder_v0":
            acc["budget"]["cost_cycles_per_frame"]["total"],
        "on_chip_state_bytes": mem["on_chip_state_bytes"],
        "external_writable_state_bytes": mem["external_writable_state_bytes"],
        "ext_traffic_bytes_per_s": mem["ext_traffic_bytes_per_s"],
        "enabled_fx_instances": acc["fx_summary"]["enabled_instances"],
        "worst_case_voices": acc["voice"]["worst_case_voices"],
        "budget_closure_placeholder_v0": acc["budget"]["closure"],
    }
    return status, reasons, columns


def _agg(values):
    if not values:
        return {"n": 0}
    return {"n": len(values), "max": _r6(max(values)),
            "mean": _r6(sum(values) / len(values))}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--graphs", default="corpus/normalized/graphs.jsonl")
    ap.add_argument("--bundle", required=True,
                    help="bundle file (contracts/profile-v1-bundle-DRAFT.json)")
    ap.add_argument("--bundle-id", required=True)
    ap.add_argument("--slate", action="append", default=[],
                    help="candidate slate JSON; repeatable")
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary-only", action="store_true",
                    help="omit the per-preset list (variant summaries)")
    args = ap.parse_args(argv)

    graphs_path = (Path(args.graphs) if Path(args.graphs).is_absolute()
                   else REPO / args.graphs)
    bundle_path = (Path(args.bundle) if Path(args.bundle).is_absolute()
                   else REPO / args.bundle)
    lines, observed, graphs_sha = load_graphs(graphs_path)
    by_path = {d["p"]: d for d in lines}
    _require(len(by_path) == len(lines),
             "REFUSING: duplicate census paths in graphs file")

    raw, bundles = load_bundle_file(bundle_path)
    _require(args.bundle_id in bundles,
             "REFUSING: bundle_id %r not in %s (available: %s)"
             % (args.bundle_id, args.bundle, sorted(bundles)))
    spec = validate_spec(bundles[args.bundle_id], observed)

    slates = load_slates(
        [p if Path(p).is_absolute() else str(REPO / p) for p in args.slate],
        by_path) if args.slate else {}

    presets = []
    totals = {s: 0 for s in ALL_STATUS}
    per_bank = {b: {s: 0 for s in ALL_STATUS} for b in ("factory", "contributor")}
    adaptation_reason_counts = {}
    sup_cols = {"factory": [], "contributor": []}
    all_cols = {"factory": [], "contributor": []}
    caveat_counts = {}
    for d in lines:
        status, reasons, cols = predict_line(d, spec)
        member = sorted(lbl for lbl, s in slates.items() if d["p"] in s["paths"])
        entry = {"path": d["p"], "bank": d["b"], "sha": d["sha"],
                 "status": status, "reasons": reasons}
        if member:
            entry["slates"] = member
        if cols is not None:
            entry["columns"] = {k: (_r6(v) if isinstance(v, float) else v)
                                for k, v in cols.items()}
            all_cols[d["b"]].append(cols)
            if status == SUPPORTED:
                sup_cols[d["b"]].append(cols)
            if cols["budget_closure_placeholder_v0"] == "OVERFLOW":
                key = "budget_closure_placeholder_v0_OVERFLOW_caveat"
                caveat_counts[key] = caveat_counts.get(key, 0) + 1
        presets.append(entry)
        totals[status] += 1
        per_bank[d["b"]][status] += 1
        if status == ADAPTED:
            for r in reasons:
                key = r["code"]
                adaptation_reason_counts[key] = adaptation_reason_counts.get(key, 0) + 1

    slate_cov = {}
    status_by_path = {e["path"]: e["status"] for e in presets}
    for lbl in sorted(slates):
        s = slates[lbl]
        cov = {st: 0 for st in ALL_STATUS}
        sup_paths = []
        for p in sorted(s["paths"]):
            st = status_by_path[p]
            cov[st] += 1
            if st == SUPPORTED:
                sup_paths.append(p)
        slate_cov[lbl] = {
            "slate_size": s["total"],
            "per_status": cov,
            "predicted_supported_count": cov[SUPPORTED],
            "predicted_supported_paths": sup_paths,
            "essentiality": "UNVERIFIED: no SXT-014 listening labels exist; "
                            "predicted coverage says nothing about whether a "
                            "preset is essential or sounds good",
        }

    out = {
        "artifact": "sxt-017-profile-prediction",
        "tool_version": TOOL_VERSION,
        "status": "DRAFT-NOT-FROZEN (issue #12 bundle stage; freeze BLOCKED on "
                  "SXT-013 listening, SXT-014 labels, SXT-016 probes)",
        "bundle_id": args.bundle_id,
        "bundle_spec": spec,
        "claim_scope": "Structural DRAFT prediction only: 'supported' = within "
                       "this bundle's declared gates/budgets on the original "
                       "normalized graph. NOT a fidelity, fit-on-cycles, "
                       "preset-quality, or hardware claim. Adapted presets are "
                       "excluded from supported counts.",
        "provenance": {
            "engine_pin": ENGINE_PIN,
            "graphs_file": _rel(args.graphs),
            "graphs_sha256": graphs_sha,
            "graphs_count": len(lines),
            "accounting_model_version": MODEL_VERSION,
            "accounting_cost_profile": REG.cost_profile,
            "accounting_params_note": "voice_pool_limit overridden to the bundle "
                                      "pool via the declared REG override "
                                      "mechanism (params_digest varies by pool)",
            "bundle_file": _rel(args.bundle),
            "bundle_file_sha256": _sha256_file(bundle_path),
            "slates": sorted(slates),
        },
        "totals": dict(totals),
        "per_bank": per_bank,
        "adaptation_reason_counts": dict(sorted(adaptation_reason_counts.items())),
        "adaptation_note": "adapted-not-predicted presets are excluded from "
                           "every supported count; each requires a disclosed "
                           "edit class (plan section 2 / fidelity policy rule)",
        "columns_basis": {
            "cycles": "SXT-015 accounting, cost profile placeholder-v0 - "
                      "[PENDING-SXT-016] every cycle number is a named "
                      "placeholder; cycles gate nothing in this DRAFT",
            "state_bytes": "SXT-015 placeholder state model (unverified FX "
                           "classes counted at a conservative 1 MiB) - "
                           "[PENDING-SXT-016]",
            "bandwidth": "48 kHz x 4-byte words per output frame - "
                         "[PENDING-SXT-016]",
        },
        "aggregates": {
            "predicted_supported": {
                b: {
                    "cost_cycles_per_frame_placeholder_v0": _agg(
                        [c["cost_cycles_per_frame_placeholder_v0"]
                         for c in sup_cols[b]]),
                    "on_chip_state_bytes": _agg(
                        [c["on_chip_state_bytes"] for c in sup_cols[b]]),
                    "external_writable_state_bytes": _agg(
                        [c["external_writable_state_bytes"]
                         for c in sup_cols[b]]),
                    "ext_traffic_bytes_per_s": _agg(
                        [c["ext_traffic_bytes_per_s"] for c in sup_cols[b]]),
                } for b in ("factory", "contributor")
            },
            "all_entries": {
                b: {
                    "cost_cycles_per_frame_placeholder_v0": _agg(
                        [c["cost_cycles_per_frame_placeholder_v0"]
                         for c in all_cols[b]]),
                    "on_chip_state_bytes": _agg(
                        [c["on_chip_state_bytes"] for c in all_cols[b]]),
                } for b in ("factory", "contributor")
            },
            "caveats": caveat_counts,
        },
        "slate_coverage": slate_cov,
    }
    if args.summary_only:
        out["presets_omitted"] = True
    else:
        out["presets"] = presets

    blob = json.dumps(out, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(blob, encoding="utf-8")

    print("bundle %s: supported %d / adapted-not-predicted %d / unsupported %d / "
          "unresolved %d (factory sup %d/641, contributor sup %d/2920)"
          % (args.bundle_id, totals[SUPPORTED], totals[ADAPTED],
             totals[UNSUPPORTED], totals[UNRESOLVED],
             per_bank["factory"][SUPPORTED],
             per_bank["contributor"][SUPPORTED]))
    for lbl in sorted(slate_cov):
        c = slate_cov[lbl]
        print("  slate %s: predicted supported %d/%d (essentiality UNVERIFIED)"
              % (lbl, c["predicted_supported_count"], c["slate_size"]))
    print("wrote %s (%d bytes)" % (args.out, len(blob)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
