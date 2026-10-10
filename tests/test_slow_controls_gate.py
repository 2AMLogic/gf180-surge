"""Failure control for tools/check_slow_controls_results.py (#415).

A skipped LIVE slow control (the NC_LIVE_SLOW unset shape) must turn the gate
red; a skipped needs-oracle control must not; a missing case must fail.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_slow_controls_results as g  # noqa: E402

REG = json.loads((ROOT / "tests" / "negative_controls_registry.json").read_text())


def _healthy():
    out = {f"{g.EXEC}[{n}]": ("PASS" if e["status"] == "LIVE" else "NOT_RUN")
           for n, e in REG["scripts"].items()}
    out[g.BUDGET] = "PASS"
    return out


def test_healthy_report_passes():
    _, bad = g.evaluate(REG, _healthy())
    assert bad == []


def test_skipped_slow_control_fails():
    o = _healthy()
    o[f"{g.EXEC}[chorus_negative_controls.py]"] = "NOT_RUN"
    assert g.evaluate(REG, o)[1]


def test_skipped_budget_noop_fails():
    o = _healthy()
    o[g.BUDGET] = "NOT_RUN"
    assert g.evaluate(REG, o)[1]


def test_missing_case_fails():
    o = _healthy()
    del o[f"{g.EXEC}[reverb_negative_controls.py]"]
    assert g.evaluate(REG, o)[1]


def test_needs_oracle_skip_allowed_not_counted_pass():
    lines, bad = g.evaluate(REG, _healthy())
    assert bad == []
    assert any(l.startswith("NOT_RUN") and "needs-oracle" in l for l in lines)
    assert not any("PASS" in l and "needs-oracle" in l for l in lines)


def test_missing_or_skipped_sxt025_integration_case_fails():
    key = f"{g.EXEC}[model/integration/negative_controls.py]"
    assert key in _healthy(), "registry must carry the SXT-025 integration row"
    o = _healthy()
    o[key] = "NOT_RUN"
    assert g.evaluate(REG, o)[1]
    del o[key]
    assert g.evaluate(REG, o)[1]
