"""Failure controls for the slow comparator required-case gate (#416).

tests/slow_comparator_required_cases.txt is checked by
tools/check_rtl_ci_results.py in .github/workflows/slow-controls.yml. These
tests pin that inventory to the LIVE-IN-CI registry and show, on synthetic
JUnit XML, that the gate rejects missing, skipped and malformed evidence. A
failed case is gated by pytest's own exit status, which the workflow step
propagates independently (asserted on the workflow text below).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_rtl_ci_results.py"
INVENTORY = ROOT / "tests" / "slow_comparator_required_cases.txt"
REGISTRY = ROOT / "tests" / "comparator_registry.json"
WORKFLOW = ROOT / ".github" / "workflows" / "slow-controls.yml"
LIVE = "tests/test_compare_rtl_model_live.py"
REPRO = "test_comparator_reproduces_committed_verdict"
CONTROL = "test_failure_control_mutated_rtl_fails_the_scratch_run"


def _inventory():
    return [ln.strip() for ln in INVENTORY.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]


def _live_scripts():
    reg = json.loads(REGISTRY.read_text())["scripts"]
    return sorted(n for n, e in reg.items() if e["status"] == "LIVE-IN-CI")


def _case(nodeid, body=""):
    path, br, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += br + params
    return (f'<testcase classname="{".".join(names[:-1])}" '
            f'name="{names[-1]}">{body}</testcase>')


def _xml(cases):
    return ('<?xml version="1.0"?><testsuites><testsuite name="p">'
            + cases + '</testsuite></testsuites>')


HELPER = _case(f"{LIVE}::test_registry_is_well_formed")


def _run(tmp_path, content, collected=None):
    rep = tmp_path / "r.xml"
    if content is not None:
        rep.write_text(content)
    col = tmp_path / "collected.txt"
    ids = _inventory() + [f"{LIVE}::test_registry_is_well_formed"]
    col.write_text("\n".join(ids if collected is None else collected) + "\n")
    return subprocess.run(
        [sys.executable, "-I", str(TOOL), str(rep), "--inventory",
         str(INVENTORY), "--collected", str(col)],
        capture_output=True, text=True)


def test_inventory_covers_every_live_comparator_rerun_and_control():
    want = {f"{LIVE}::{t}[{n}]" for n in _live_scripts() for t in (REPRO, CONTROL)}
    assert len(_live_scripts()) == 4 and len(want) == 8
    assert set(_inventory()) == want and len(_inventory()) == 8


def test_all_present_and_executed_passes(tmp_path):
    r = _run(tmp_path, _xml(HELPER + "".join(_case(n) for n in _inventory())))
    assert r.returncode == 0, r.stderr
    assert "required executed: 8" in r.stdout


@pytest.mark.parametrize("drop", range(8))
def test_any_single_absent_case_fails(tmp_path, drop):
    """The measured gap: only registry/helper tests run, nothing skipped."""
    inv = _inventory()
    present = inv[:drop] + inv[drop + 1:]
    r = _run(tmp_path, _xml(HELPER + "".join(_case(n) for n in present)))
    assert r.returncode == 1
    assert f"required case missing from JUnit report: {inv[drop]}" in r.stderr


def test_helper_only_report_fails(tmp_path):
    r = _run(tmp_path, _xml(HELPER))
    assert r.returncode == 1 and "required missing: 8" in r.stdout


def test_skipped_required_case_fails(tmp_path):
    skip = '<skipped type="pytest.skip" message="NOT_RUN: slow comparator"/>'
    cases = "".join(_case(n, skip if i == 0 else "")
                    for i, n in enumerate(_inventory()))
    r = _run(tmp_path, _xml(HELPER + cases))
    assert r.returncode == 1 and "required case skipped" in r.stderr


def test_missing_and_malformed_report_fail(tmp_path):
    assert _run(tmp_path, None).returncode == 1
    assert _run(tmp_path, "<testsuites><oops").returncode == 1


def test_renamed_test_leaves_stale_inventory_entry(tmp_path):
    inv = _inventory()
    r = _run(tmp_path, _xml(HELPER + "".join(_case(n) for n in inv)),
             collected=inv[1:])
    assert r.returncode == 1 and "stale inventory entry" in r.stderr


def test_workflow_gates_inventory_and_preserves_pytest_status():
    text = WORKFLOW.read_text()
    step = text[text.index("slow RTL-vs-model comparator re-runs"):
                text.index("Upload JUnit report")]
    assert "--inventory tests/slow_comparator_required_cases.txt" in step
    assert "--collected comparator-live-collected.txt" in step
    assert 'exit "${pytest_rc}"' in step and 'exit "${check_rc}"' in step
    assert 'if [ "${collect_rc}" -ne 0 ]' in step
    assert 'grep -q "<skipped"' not in step
