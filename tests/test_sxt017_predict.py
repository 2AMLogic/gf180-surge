"""SXT-017 bundle-stage tests (issue #12 bundle stage; run by CI).

Covers the automatable guarantees only:
  - committed prediction artifacts are byte-current with a re-run
    (determinism + no drift),
  - every headline artifact covers all 3,561 entries (641 factory +
    2,920 contributor) with a partition of statuses, and honors the
    publishing rule: adapted-not-predicted is never counted as supported,
  - fail-closed behavior: unknown bundle keys, unknown allowlist names,
    frozen-status bundles, and tampered slates REFUSE (exit 2),
  - negative control NC1: inflating the FX instance budget (x2) in a /tmp
    bundle spec CHANGES the predicted supportable set (sensitivity).

These tests make NO claim about sound fidelity, preset quality, preset
support, or any frozen profile. No engine tree is required or used.

Python 3 standard library only (pytest as runner).
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "profile_predict.py"
BUNDLE_FILE = REPO / "contracts" / "profile-v1-bundle-DRAFT.json"
SLATES = [
    REPO / "reports" / "sxt-013" / "candidates" / "slate-256-balanced.json",
    REPO / "reports" / "sxt-013" / "candidates" / "slate-256-factory-lean.json",
    REPO / "reports" / "sxt-013" / "candidates" / "slate-256-contributor-lean.json",
]
HEADLINE = [
    "B1-core-narrow", "B2-core-wet-plan3", "B3-ext-voice-fx", "B4-broad",
    "R0-ceiling-reference",
]
DECLARED_REASON_CODES = {
    "loader_analysis_failure", "mseg_or_formula_contents_not_exported",
    "audio_input_dependency", "scene_mode_not_in_bundle",
    "oscillator_family_not_in_bundle", "wavetable_assets_not_in_bundle",
    "filter_algorithm_not_in_bundle", "waveshaper_not_in_bundle",
    "effect_class_not_in_bundle", "airwindows_algorithm_not_selected",
    "fx_instance_overflow", "event_queue_overflow", "scene_mode_unaccountable",
    "on_chip_ram_exceeded", "external_writable_capacity_exceeded",
    "external_bandwidth_exceeded", "polylimit_reduction_required",
    "unison_reduction_required",
}


def run_predict(bundle_file, bundle_id, out, extra=()):
    cmd = [sys.executable, str(TOOL), "--bundle", str(bundle_file),
           "--bundle-id", bundle_id, "--out", str(out)]
    for s in SLATES:
        cmd += ["--slate", str(s)]
    return subprocess.run(cmd + list(extra),
                          capture_output=True, text=True, cwd=REPO)


def write_tmp_bundle(bundle_ids_specs, tmp_path, name="bundle.json"):
    raw = json.loads(BUNDLE_FILE.read_text())
    raw["bundles"] = [
        {"bundle_id": bid, "status": "DRAFT-NOT-FROZEN", "spec": spec}
        for bid, spec in bundle_ids_specs
    ]
    p = tmp_path / name
    p.write_text(json.dumps(raw, sort_keys=True, indent=1))
    return p


def spec_of(bundle_id):
    raw = json.loads(BUNDLE_FILE.read_text())
    for b in raw["bundles"]:
        if b["bundle_id"] == bundle_id:
            return copy.deepcopy(b["spec"])
    raise AssertionError(bundle_id)


def headline_artifact(bundle_id):
    return json.loads(
        (REPO / "reports" / "sxt-017" / "predictions" / (bundle_id + ".json"))
        .read_text())


def test_committed_artifacts_are_current(tmp_path):
    """Re-running the predictor must reproduce the committed B4 artifact
    byte-identically (determinism + committed-state freshness)."""
    out = tmp_path / "B4.json"
    r = run_predict(BUNDLE_FILE, "B4-broad", out)
    assert r.returncode == 0, r.stderr
    committed = (REPO / "reports" / "sxt-017" / "predictions" / "B4-broad.json")
    assert out.read_bytes() == committed.read_bytes(), (
        "committed predictions/B4-broad.json is stale; regenerate with "
        "tools/profile_predict.py")


def test_coverage_all_entries():
    for bid in HEADLINE:
        d = headline_artifact(bid)
        assert len(d["presets"]) == 3561
        banks = {"factory": 0, "contributor": 0}
        statuses = {"supported": 0, "adapted-not-predicted": 0,
                    "unsupported": 0, "unresolved": 0}
        for p in d["presets"]:
            banks[p["bank"]] += 1
            statuses[p["status"]] += 1
        assert banks == {"factory": 641, "contributor": 2920}, bid
        assert sum(statuses.values()) == 3561
        assert statuses == d["totals"], bid
        for bank in ("factory", "contributor"):
            assert sum(d["per_bank"][bank].values()) == (
                641 if bank == "factory" else 2920)


def test_adapted_never_counted_as_supported():
    for bid in HEADLINE:
        d = headline_artifact(bid)
        assert d["totals"]["supported"] == (
            d["per_bank"]["factory"]["supported"]
            + d["per_bank"]["contributor"]["supported"])
        # the adaptation breakdown must account for every adapted entry
        assert sum(d["adaptation_reason_counts"].values()) == \
            d["totals"]["adapted-not-predicted"]
        for p in d["presets"]:
            if p["status"] == "adapted-not-predicted":
                codes = {r["code"] for r in p["reasons"]}
                assert codes <= {"polylimit_reduction_required",
                                 "unison_reduction_required"}
            if p["status"] == "supported":
                assert p["reasons"] == []


def test_reason_codes_are_declared():
    for bid in HEADLINE:
        d = headline_artifact(bid)
        for p in d["presets"]:
            for r in p["reasons"]:
                assert r["code"] in DECLARED_REASON_CODES, (bid, r)


def test_slate_coverage_consistent_with_presets():
    slate_labels = {"slate-256-balanced", "slate-256-factory-lean",
                    "slate-256-contributor-lean"}
    for bid in HEADLINE:
        d = headline_artifact(bid)
        assert set(d["slate_coverage"]) == slate_labels
        for lbl, cov in d["slate_coverage"].items():
            assert cov["slate_size"] == 256
            sup = {p["path"] for p in d["presets"]
                   if p["status"] == "supported" and lbl in p.get("slates", [])}
            assert len(sup) == cov["predicted_supported_count"]
            assert sorted(sup) == cov["predicted_supported_paths"]
            assert cov["essentiality"].startswith("UNVERIFIED")


def test_unknown_bundle_key_rejected(tmp_path):
    spec = spec_of("B4-broad")
    spec["fx_instance_limt"] = 8  # typo'd key must REFUSE, never be ignored
    p = write_tmp_bundle([("B4-broad", spec)], tmp_path)
    r = run_predict(p, "B4-broad", tmp_path / "out.json")
    assert r.returncode == 2
    assert "fx_instance_limt" in r.stderr


def test_unknown_allowlist_name_rejected(tmp_path):
    spec = spec_of("B4-broad")
    spec["oscillator_allowlist"] = ["Classic", "Sine", "WavetableX"]
    p = write_tmp_bundle([("B4-broad", spec)], tmp_path)
    r = run_predict(p, "B4-broad", tmp_path / "out.json")
    assert r.returncode == 2
    assert "WavetableX" in r.stderr


def test_non_draft_status_refused(tmp_path):
    spec = spec_of("B4-broad")
    p = write_tmp_bundle([("B4-broad", spec)], tmp_path)
    raw = json.loads(p.read_text())
    raw["status"] = "FROZEN"
    p.write_text(json.dumps(raw, sort_keys=True, indent=1))
    r = run_predict(p, "B4-broad", tmp_path / "out.json")
    assert r.returncode == 2
    assert "DRAFT-NOT-FROZEN" in r.stderr


def test_tampered_slate_refused(tmp_path):
    slate = json.loads(SLATES[0].read_text())
    slate["candidates"][7]["census_blob_sha1"] = "0" * 40
    p = tmp_path / "tampered-slate.json"
    p.write_text(json.dumps(slate, sort_keys=True, indent=1))
    r = run_predict(BUNDLE_FILE, "B4-broad", tmp_path / "out.json",
                    extra=["--slate", str(p)])
    assert r.returncode == 2
    assert "mismatch" in r.stderr


def test_negative_control_inflated_budget_changes_supported_set(tmp_path):
    """Issue #12 acceptance: a deliberately inflated budget must change the
    supportable set, else the comparison is not sensitive."""
    base_spec = spec_of("VAR-B4-inst4")
    inflated = copy.deepcopy(base_spec)
    assert inflated["fx_instance_limit"] == 4
    inflated["fx_instance_limit"] = 8  # deliberate budget inflation (x2)
    bp = write_tmp_bundle([("VAR-B4-inst4", base_spec)], tmp_path, "base.json")
    ip = write_tmp_bundle([("VAR-B4-inst4", inflated)], tmp_path, "inflated.json")
    rb = run_predict(bp, "VAR-B4-inst4", tmp_path / "base-out.json",
                     extra=["--summary-only"])
    ri = run_predict(ip, "VAR-B4-inst4", tmp_path / "inflated-out.json",
                     extra=["--summary-only"])
    assert rb.returncode == 0 and ri.returncode == 0, rb.stderr + ri.stderr
    base = json.loads((tmp_path / "base-out.json").read_text())
    infl = json.loads((tmp_path / "inflated-out.json").read_text())
    assert base["totals"]["supported"] != infl["totals"]["supported"]
    # and the inflated set must equal the committed limit-8 artifact totals
    assert infl["totals"] == headline_artifact("B4-broad")["totals"]
