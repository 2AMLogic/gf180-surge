#!/usr/bin/env python3
"""#122: FX modulation RNG waveforms — decision, evidence and enforcement.

Asserts the COMMITTED record, not a re-derivation of it: the tools that
produce it are separately re-runnable (see reports/SXT-028-rng/EVIDENCE.md
§Reproduce). What is checked here is that the record is internally
consistent, that no leg that did not run is reported as a pass, that the
fail-closed refusal is still live at both enforcement points, and that the
coverage cost is published as a REDUCTION rather than deducted.
"""

import csv
import hashlib
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-phaser"))

import phaser_model as pm  # noqa: E402
from phaser_model import PhaserParams, Refuse  # noqa: E402
from corners import CORNERS  # noqa: E402

RNG_ROOT = os.path.join(REPO, "reports", "SXT-028-rng")
CHAR = os.path.join(RNG_ROOT, "artifacts", "rng-characterization.json")
IMPACT = os.path.join(RNG_ROOT, "artifacts", "coverage-impact.json")
NC = os.path.join(RNG_ROOT, "negative-controls", "negative-controls.json")
GATE_NC = os.path.join(RNG_ROOT, "negative-controls",
                       "coverage-gate-control.txt")
DR = os.path.join(REPO, "decision-records",
                  "0013-fx-modulation-rng-stream.md")
STATUS_VOCAB = {"PASS", "FAIL", "NOT_RUN", "BLOCKED", "NO_VERDICT", "STALE"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# the characterisation (acceptance item 1)
# --------------------------------------------------------------------------

def test_characterization_record_exists_and_uses_the_status_vocabulary():
    d = load(CHAR)
    legs = d["legs"]
    assert set(legs) == {"source_inventory", "seed_reproducibility",
                         "distribution_portability"}
    for name, leg in legs.items():
        assert leg["status"] in (STATUS_VOCAB | {"PARTIAL"}), (name, leg)


def test_the_reproducibility_question_is_answered_not_assumed():
    """A verdict must come from the probe, with its detector controls OK."""
    leg = load(CHAR)["legs"]["seed_reproducibility"]
    if leg["status"] == "NOT_RUN":
        pytest.skip("probe not run on the host that produced the record")
    assert leg["status"] in ("FAIL", "PASS"), leg["status"]
    controls = [c for c in leg["checks"] if "DETECTOR CONTROL" in c["check"]]
    assert len(controls) >= 2, "a verdict with no detector control"
    assert all(c["status"] == "CONTROL-OK" for c in controls), controls
    # every non-control check must be a real observation
    for c in leg["checks"]:
        assert isinstance(c["observed"], bool)


def test_committed_finding_is_not_pinnable():
    d = load(CHAR)
    assert d["finding"]["stream_is_pinnable"] is False
    assert len(d["finding"]["obstructions"]) >= 4
    assert d["legs"]["seed_reproducibility"]["status"] == "FAIL"


def test_distribution_portability_is_not_reported_as_a_pass():
    leg = load(CHAR)["legs"]["distribution_portability"]
    assert leg["status"] == "NOT_RUN"
    assert "reason" in leg and leg["reason"]


def test_survey_covers_the_consumers_the_issue_named_plus_the_flanger():
    d = load(CHAR)
    names = {e["fx_type_name"]: e for e in d["fx_survey"]}
    assert "Phaser" in names and names["Phaser"]["generator"] == \
        "fxmodcontrol_owned_rng"
    # the issue asked the survey to look for other FXModControl consumers;
    # the Flanger turned out to use the SHARED storage generator instead
    assert "Flanger" in names
    assert names["Flanger"]["generator"] == "surgestorage_shared_rngGen"
    assert names["Neuron"]["generator"] == "fxmodcontrol_owned_rng"
    # a class verified to reach no RNG must be recorded as such, not omitted
    assert names["Vocoder"]["rng_dependence"] == "none"
    # unsurveyed classes are named, never silently treated as clean
    unsurveyed = {n["fx_type_name"] for n in d["not_surveyed"]}
    assert {"Airwindows", "Nimbus"} <= unsurveyed


def test_every_cited_pinned_file_carries_a_hash_and_a_commit():
    for rec in load(CHAR)["legs"]["source_inventory"]["files"]:
        assert "@" in rec["tree"], rec
        assert len(rec["expected_sha256"]) == 64, rec
        assert rec["status"] in ("VERIFIED", "NOT_RUN", "MISMATCH")
        assert rec["status"] != "MISMATCH", rec


# --------------------------------------------------------------------------
# the fail-closed refusal stays live (SXT-028g is NOT re-opened)
# --------------------------------------------------------------------------

def test_rng_waveforms_are_still_refused_at_both_enforcement_points():
    for wave in (pm.MOD_NOISE, pm.MOD_SNH):
        with pytest.raises(Refuse):
            PhaserParams(dict(CORNERS["synth-a"], mod_wave_i=wave))
    src = open(os.path.join(REPO, "tools", "extract_phaser_inputs.py"),
               encoding="utf-8").read()
    import ast
    waves = None
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign) and node.targets
                and getattr(node.targets[0], "id", None)
                == "DETERMINISTIC_WAVES"):
            waves = ast.literal_eval(node.value)
    assert waves is not None
    assert tuple(waves) == tuple(pm.DETERMINISTIC_WAVES)
    assert not ({pm.MOD_NOISE, pm.MOD_SNH} & set(waves))


def test_the_refusal_is_not_always_firing():
    for wave in pm.DETERMINISTIC_WAVES:
        PhaserParams(dict(CORNERS["synth-a"], mod_wave_i=wave))


def test_the_frozen_phaser_model_was_not_edited_by_this_issue():
    """SXT-028g's model revision is pinned by its committed RTL record; this
    issue records a contract reason, it does not touch the frozen model."""
    rec = load(os.path.join(REPO, "reports", "SXT-028g",
                            "rtl-exactness.json"))
    assert rec["model_revision"] == pm.model_revision()


# --------------------------------------------------------------------------
# negative controls (acceptance item 3)
# --------------------------------------------------------------------------

def test_negative_controls_all_fired():
    d = load(NC)
    assert d["result"] == "PASS"
    by = {c["control"].split()[0]: c for c in d["controls"]}
    assert set(by) == {"NC-R1", "NC-R2", "NC-R3", "NC-R4"}
    for c in d["controls"]:
        assert c["ok"] is True, c


def test_the_adapted_substitute_is_refused_from_original_preset_coverage():
    c = next(x for x in load(NC)["controls"] if x["control"].startswith("NC-R1"))
    assert c["coverage_class"] == "ADAPTED"
    assert c["counts_toward_original_preset_coverage"] is False
    assert c["legs"]["coverage_gate_refuses_substitute"] is True
    # and the gate is not always-refusing
    assert c["legs"]["coverage_gate_accepts_frozen_detector_control"] is True
    # the substitute is materially different from anything in scope AND from
    # another arbitrary seed of itself -- the stream is a free choice
    m = c["metrics"]
    assert m["max_abs_diff_vs_nearest_in_scope_shape_lsb"] > \
        m["declared_threshold_lsb"]
    assert m["max_abs_diff_between_two_substitute_seeds_lsb"] > \
        m["declared_threshold_lsb"]
    # no model-vs-reference statement is smuggled in
    assert c["reference_anchored_leg"]["status"] == "NOT_RUN"


def test_the_coverage_gate_control_is_recorded_and_passed():
    txt = open(GATE_NC, encoding="utf-8").read()
    assert "NC-RNG-EXCLUSION" in txt
    assert "RESULT: PASS" in txt
    assert "denominator unchanged" in txt


# --------------------------------------------------------------------------
# the coverage reduction (acceptance item 2b / 4)
# --------------------------------------------------------------------------

def test_coverage_impact_is_measured_from_the_committed_graphs():
    d = load(IMPACT)
    graphs = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
    assert d["inputs"]["corpus/normalized/graphs.jsonl"] == sha256_file(graphs)
    assert d["inputs"][
        "reports/SXT-028-rng/artifacts/rng-characterization.json"] == \
        sha256_file(CHAR)
    assert d["corpus"]["denominator"] == 3561
    assert 0 < d["corpus"]["affected_presets"] <= 3561
    assert d["corpus"]["affected_presets_including_disabled_slots"] >= \
        d["corpus"]["affected_presets"]


def test_every_affected_preset_names_its_class_and_census_blob():
    d = load(IMPACT)
    assert len(d["affected_presets"]) == d["corpus"]["affected_presets"]
    for rec in d["affected_presets"]:
        assert len(rec["census_blob_sha1"]) == 40, rec
        assert rec["bank"] in ("factory", "contributor")
        assert rec["classes"], rec


def test_the_named_issue_scope_is_reported_separately_from_the_family():
    s = load(IMPACT)["scopes"]
    assert s["issue_122_named_scope"]["affected_presets"] <= \
        s["fx_modulation_rng_family"]["affected_presets"] <= \
        s["all_unpinnable_rng_classes"]["affected_presets"]


def test_slate_denominators_are_unchanged():
    for name, s in load(IMPACT)["slates"].items():
        assert s["denominator"] == 256, name
        assert len(s["affected_paths"]) == s["affected"], name


# --------------------------------------------------------------------------
# the published coverage record carries the reduction, not a deduction
# --------------------------------------------------------------------------

def test_published_coverage_publishes_the_reduction():
    cov = load(os.path.join(REPO, "reports", "coverage-v1", "coverage.json"))
    ex = cov["fx_rng_exclusion"]
    assert ex["gate_active"] is True
    assert ex["gate_value"] == "BLOCKED"
    assert ex["corpus_denominator"] == 3561
    assert cov["denominators"]["corpus_total"] == 3561
    assert ex["corpus_affected"] == load(IMPACT)["corpus"]["affected_presets"]
    assert any("#122" in o["decision"] for o in cov["open_decisions"])


def test_no_affected_preset_is_reported_supported():
    affected = {r["path"] for r in load(IMPACT)["affected_presets"]}
    blocked = 0
    with open(os.path.join(REPO, "reports", "coverage-v1", "per-preset.csv"),
              newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["path"] not in affected:
                continue
            blocked += 1
            assert row["fx_rng_gate"] == "BLOCKED", row["path"]
            assert row["headline_status"] != "supported", row["path"]
            assert "rng_stream_unpinnable:" in row["reasons"], row["path"]
    assert blocked == len(affected)


def test_the_gate_input_is_pinned_by_the_coverage_tool():
    import publish_coverage as pc
    assert pc.RNG_EXCLUSION_DEFAULT in pc.STRUCTURAL_INPUTS
    assert pc.STRUCTURAL_INPUTS[pc.RNG_EXCLUSION_DEFAULT] == sha256_file(IMPACT)
    assert "fx_rng_gate" in pc.CSV_COLUMNS


# --------------------------------------------------------------------------
# the decision record and the manifest
# --------------------------------------------------------------------------

def test_decision_record_is_present_indexed_and_routed():
    body = open(DR, encoding="utf-8").read()
    assert "RECORDED CONTRACT REVISION" in body
    assert "#12" in body and "SXT-017" in body
    for rel in ("reports/SXT-028-rng/EVIDENCE.md",
                "reports/SXT-028-rng/artifacts/rng-characterization.json",
                "reports/SXT-028-rng/artifacts/coverage-impact.json"):
        assert rel in body, rel
    index = open(os.path.join(REPO, "decision-records", "README.md"),
                 encoding="utf-8").read()
    assert "0013-fx-modulation-rng-stream.md" in index


def test_manifest_records_the_characterisation_without_changing_a_pin():
    m = load(os.path.join(REPO, "oracle", "manifest.json"))
    rec = m["runtime"]["fx_modulation_randomness"]
    assert rec["issue"] == "#122"
    assert rec["status"] == "MEASURED NOT REPRODUCIBLE"
    assert set(rec["generators"]) == {"FXModControl::rng",
                                      "SurgeStorage::rngGen",
                                      "chowdsp std::random_device"}
    # the engine pin and the no-seed-override policy are untouched
    assert m["engine"]["commit"] == \
        "58914e59c608ed4384ba6002e44c3465c58b2e71"
    assert m["runtime"]["randomness"].startswith("No seed override is applied")


def test_evidence_record_exists_and_separates_the_three_claims():
    body = open(os.path.join(RNG_ROOT, "EVIDENCE.md"),
                encoding="utf-8").read()
    for token in ("NOT_RUN", "NO_VERDICT", "decision-records/0013",
                  "#12", "ADAPTED"):
        assert token in body, token


# --------------------------------------------------------------------------
# the tools are re-runnable and fail closed
# --------------------------------------------------------------------------

def test_coverage_impact_tool_refuses_a_shrunken_corpus(tmp_path):
    """The silent-exclusion guard (NC-R3) in-line, so it is exercised by the
    test suite and not only by the controls runner."""
    root = tmp_path / "repo"
    for rel in ("corpus/normalized/graphs.jsonl",
                "reports/SXT-028-rng/artifacts/rng-characterization.json",
                "reports/sxt-013/candidates/slate-256-balanced.json",
                "reports/sxt-013/candidates/slate-256-contributor-lean.json",
                "reports/sxt-013/candidates/slate-256-factory-lean.json"):
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(open(os.path.join(REPO, rel), "rb").read())
    graphs = root / "corpus/normalized/graphs.jsonl"
    lines = graphs.read_text(encoding="utf-8").splitlines()
    graphs.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools",
                                      "fx_rng_coverage_impact.py"),
         "--repo-root", str(root), "--out", "out/impact.json"],
        capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "corpus entries" in r.stderr
    assert not (root / "out/impact.json").exists()
