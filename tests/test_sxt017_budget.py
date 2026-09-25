"""Tests for the SXT-017 stage-2 cost-closure gate (issue #12).

Claim scope: these tests check the TOOL's arithmetic, refusals, determinism,
and cross-artifact consistency. They establish no fidelity, support,
preset-quality, technology, or hardware claim, and they do not freeze
anything.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from probes.worked_bundle import build_bundle, fx_kernel_map  # noqa: E402
from tools import profile_budget as pb  # noqa: E402
from tools.profile_predict import Refuse  # noqa: E402

COST_CLOSURE = REPO / "reports/sxt-017/cost-closure.json"
PREDICTIONS = REPO / "reports/sxt-017/predictions"
BUNDLE_FILE = "contracts/profile-v1-bundle-DRAFT.json"
SLATES = ["reports/sxt-013/candidates/slate-256-balanced.json",
          "reports/sxt-013/candidates/slate-256-factory-lean.json",
          "reports/sxt-013/candidates/slate-256-contributor-lean.json"]


@pytest.fixture(scope="module")
def doc():
    return json.loads(COST_CLOSURE.read_text())


def _run(argv):
    """Run the tool as a subprocess; return CompletedProcess."""
    return subprocess.run([sys.executable, "tools/profile_budget.py"] + argv,
                          cwd=REPO, capture_output=True, text=True)


# --------------------------------------------------------------------------
# verdict semantics: the lower-bound/placeholder asymmetry is the whole point
# --------------------------------------------------------------------------
def test_conclusive_overflow_needs_only_the_probe_priced_lower_bound():
    # probe-only alone busts the budget => conclusive, whatever else is true
    assert pb._verdict(100.0, 100.0, 50.0, True) == pb.VERDICT_OVERFLOW_CONCLUSIVE
    assert pb._verdict(100.0, 100.0, 50.0, False) == pb.VERDICT_OVERFLOW_CONCLUSIVE


def test_placeholder_only_overflow_is_not_conclusive():
    assert pb._verdict(40.0, 100.0, 50.0, True) == pb.VERDICT_OVERFLOW_PLACEHOLDER


def test_no_fit_claim_while_unpriced_components_remain():
    """Plan section 5: no fit claim without a measured schedule. A bundle
    that merely fails to overflow is NOT a fit."""
    assert pb._verdict(10.0, 20.0, 50.0, True) == pb.VERDICT_NO_VERDICT
    assert pb._verdict(10.0, 20.0, 50.0, False) == pb.VERDICT_WITHIN


def test_lanes_required_is_a_floor_and_refuses_a_nonpositive_budget():
    assert pb._lanes_required(100.0, 50.0) == 2
    assert pb._lanes_required(101.0, 50.0) == 3
    # a non-positive DSP budget cannot be closed by any lane count
    assert pb._lanes_required(100.0, 0.0) is None
    assert pb._lanes_required(100.0, -198.0) is None


# --------------------------------------------------------------------------
# probe-index selection must be explicit, never filename-order dependent
# --------------------------------------------------------------------------
def test_probe_index_pins_exactly_one_record_per_key():
    idx, origin = pb.load_probe_index(REPO / "reports/sxt-016/probes",
                                      phase_bits=32)
    assert idx and len(idx) == len(origin)
    for (probe, kernel, mult), fn in origin.items():
        if "__ph" in fn:
            assert "__ph32__" in fn, (probe, kernel, mult, fn)


def test_probe_index_phase_pin_is_load_bearing():
    i32, _ = pb.load_probe_index(REPO / "reports/sxt-016/probes", 32)
    i16, _ = pb.load_probe_index(REPO / "reports/sxt-016/probes", 16)
    k = ("probe_osc", "classic_blit", "M32")
    # SXT-016 finding: phase width moves RAM, not cycles. Both must hold.
    assert i32[k]["cycles_per_sample"] == i16[k]["cycles_per_sample"]
    assert i32[k]["state_ram_bits"] != i16[k]["state_ram_bits"]


def test_missing_probe_directory_refuses():
    with pytest.raises(Refuse):
        pb.load_probe_index(REPO / "reports/sxt-016/no-such-probes", 32)


# --------------------------------------------------------------------------
# memory implementation is a real dimension, and E1 stays the default
# --------------------------------------------------------------------------
def test_fx_kernel_map_default_is_e1_and_unknown_model_refuses():
    assert fx_kernel_map() == fx_kernel_map("E1")
    assert fx_kernel_map("E3")["Delay"] == "delay_stereo_ext_E3"
    with pytest.raises(KeyError):
        fx_kernel_map("E9")


def test_memory_model_changes_the_cost_of_a_delay_bearing_preset():
    idx, _ = pb.load_probe_index(REPO / "reports/sxt-016/probes", 32)
    line = None
    with open(REPO / "corpus/normalized/graphs.jsonl") as f:
        for raw in f:
            d = json.loads(raw)
            if d.get("p", "").endswith("Leads/Koala 2.fxp"):
                line = d
                break
    assert line is not None, "Koala 2 (single Delay slot) must be in the census"
    e1 = build_bundle("x", line, idx, "M32", fx_instance_limit=8, e_model="E1")
    e3 = build_bundle("x", line, idx, "M32", fx_instance_limit=8, e_model="E3")
    assert (e1["totals"]["fx_cycles_per_frame"]
            > e3["totals"]["fx_cycles_per_frame"]), \
        "E1 (no burst, 24 cyc/word) must cost more than E3 (burst, 2 cyc/word)"


# --------------------------------------------------------------------------
# committed artifact: current, self-consistent, and consistent with stage 1
# --------------------------------------------------------------------------
def test_committed_cost_closure_is_current():
    out = REPO / "reports/sxt-017/.cost-closure-regen.json"
    try:
        argv = ["--bundle", BUNDLE_FILE]
        for s in SLATES:
            argv += ["--slate", s]
        argv += ["--primary-slate", "slate-256-balanced", "--out", str(out)]
        r = _run(argv)
        assert r.returncode == 0, r.stderr
        assert out.read_bytes() == COST_CLOSURE.read_bytes(), \
            "committed reports/sxt-017/cost-closure.json is stale; re-run the tool"
    finally:
        out.unlink(missing_ok=True)


def test_supported_counts_agree_with_the_bundle_stage_artifacts(doc):
    """Stage 2 must not silently re-derive a different supported set."""
    for b in doc["bundles"]:
        stage1 = json.loads((PREDICTIONS / (b["bundle_id"] + ".json")).read_text())
        assert b["predicted_supported_count"] == stage1["totals"]["supported"], \
            b["bundle_id"]
        for label, cov in b["slate_coverage"].items():
            assert (cov["predicted_supported_count"]
                    == stage1["slate_coverage"][label]["predicted_supported_count"])


def test_every_grid_row_names_clock_memory_and_basis(doc):
    """Plan section 5: no fit claim without clock + memory implementation +
    basis. A row that does not name all three is not a budget."""
    for b in doc["bundles"]:
        assert b["grid"], b["bundle_id"]
        for g in b["grid"]:
            assert g["clock_hz"] in (48_000_000, 96_000_000, 192_000_000,
                                     480_000_000)
            assert g["memory_implementation"] in ("E1", "E2", "E3")
            assert g["memory_implementation_assumption"].startswith("A-EXT-")
            assert g["multiplier_assumption"].startswith("A-DSP-")
            assert "ESTIMATE" in g["basis"] and "NOT a measurement" in g["basis"]
            assert g["verdict"] in (pb.VERDICT_WITHIN, pb.VERDICT_NO_VERDICT,
                                    pb.VERDICT_OVERFLOW_CONCLUSIVE,
                                    pb.VERDICT_OVERFLOW_PLACEHOLDER)


def test_probe_only_total_is_never_above_the_mixed_total(doc):
    for b in doc["bundles"]:
        for g in b["grid"]:
            assert (g["worst_probe_only_cycles_per_frame"]
                    <= g["worst_mixed_cycles_per_frame"] + 1e-6), b["bundle_id"]


def test_no_bundle_carries_a_fit_claim_and_stop_escalate_is_recorded(doc):
    """The committed result is a STOP/ESCALATE, and must stay visibly so."""
    assert doc["budget_scale"] == 1.0 and doc["is_negative_control"] is False
    assert all(not b["fit_claimable"] for b in doc["bundles"])
    assert doc["selected_bundle_fit_claim"] is False
    assert doc["stop_escalate"] is True
    assert "preferred_preset_goal_missed" in doc["stop_escalate_reasons"]
    assert doc["goal_test"]["goal_met"] is False
    assert doc["goal_test"]["threshold"] == 205


def test_adapted_presets_are_absent_from_every_supported_count(doc):
    """Stage 2 inherits the bundle stage's partition; adapted never counts."""
    for b in doc["bundles"]:
        stage1 = json.loads((PREDICTIONS / (b["bundle_id"] + ".json")).read_text())
        t = stage1["totals"]
        assert sum(t.values()) == 3561
        assert b["predicted_supported_count"] == t["supported"]
        assert t["adapted-not-predicted"] > 0
        assert b["predicted_supported_count"] != (
            t["supported"] + t["adapted-not-predicted"])


# --------------------------------------------------------------------------
# negative control: budget sensitivity, and the refusals that protect it
# --------------------------------------------------------------------------
def test_inflated_budget_changes_the_selected_bundle(tmp_path):
    """Issue #12 acceptance item 5. If this ever fails, the comparison is not
    sensitive to the budget and must be fixed, not re-baselined."""
    base_argv = ["--bundle", BUNDLE_FILE, "--bundle-id", "B1-core-narrow",
                 "--bundle-id", "B4-broad", "--slate", SLATES[0],
                 "--primary-slate", "slate-256-balanced"]
    r1 = _run(base_argv + ["--out", str(tmp_path / "s1.json")])
    assert r1.returncode == 0, r1.stderr
    r2 = _run(["--budget-scale", "40", "--negative-control"] + base_argv
              + ["--out", str(tmp_path / "s40.json")])
    assert r2.returncode == 0, r2.stderr
    d1 = json.loads((tmp_path / "s1.json").read_text())
    d40 = json.loads((tmp_path / "s40.json").read_text())
    assert d1["selected_bundle"] != d40["selected_bundle"], \
        "inflating the budget did not change the selection"
    assert d1["selected_bundle"] == "B1-core-narrow"
    assert d40["selected_bundle"] == "B4-broad"
    # ... and inflation still buys no fit claim (recorded finding NC-B5)
    assert d40["selected_bundle_fit_claim"] is False


def test_budget_scale_without_acknowledgement_refuses(tmp_path):
    r = _run(["--budget-scale", "40", "--out", str(tmp_path / "x.json")])
    assert r.returncode == 2 and "REFUSING" in r.stderr


def test_control_run_may_not_write_into_the_evidence_tree(tmp_path):
    r = _run(["--budget-scale", "40", "--negative-control",
              "--out", "reports/sxt-017/cost-closure.json"])
    assert r.returncode == 2 and "REFUSING" in r.stderr
    # the committed artifact is untouched
    assert json.loads(COST_CLOSURE.read_text())["budget_scale"] == 1.0


def test_unknown_bundle_id_refuses(tmp_path):
    r = _run(["--bundle-id", "B9-does-not-exist",
              "--out", str(tmp_path / "x.json")])
    assert r.returncode == 2 and "REFUSING" in r.stderr


def test_committed_negative_control_record_reports_all_controls():
    text = (REPO / "reports/sxt-017/negative-controls-budget.txt").read_text()
    for nc in ("NC-B1", "NC-B2", "NC-B3", "NC-B4", "NC-B5"):
        assert nc in text
    assert "NC-B1 PASS" in text
    assert "FAIL" not in text.replace("failure", "")
