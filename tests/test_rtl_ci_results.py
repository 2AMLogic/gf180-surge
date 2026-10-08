"""Failure controls for tools/check_rtl_ci_results.py (synthetic JUnit XML)."""
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "check_rtl_ci_results.py"


def _xml(cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="p">{cases}</testsuite></testsuites>'


PASS = '<testcase classname="t" name="a"/>'


def _skip(reason: str, name: str = "s") -> str:
    return f'<testcase classname="t" name="{name}"><skipped type="pytest.skip" message="{reason}"/></testcase>'


def run(tmp_path, content):
    p = tmp_path / "r.xml"
    if content is not None:
        p.write_text(content)
    return subprocess.run(
        [sys.executable, "-I", str(TOOL), str(p)], capture_output=True, text=True
    )


def test_clean_pass(tmp_path):
    r = run(tmp_path, _xml(PASS))
    assert r.returncode == 0 and "simulator-dependent skipped: 0" in r.stdout


@pytest.mark.parametrize(
    "reason", ["iverilog not installed", "IVerilog missing", "need VVP", "no Icarus vvp"]
)
def test_simulator_skip_fails(tmp_path, reason):
    r = run(tmp_path, _xml(PASS + _skip(reason)))
    assert r.returncode == 1 and "simulator-dependent skip" in r.stderr


def test_unrelated_skip_is_not_run_but_passes(tmp_path):
    r = run(tmp_path, _xml(PASS + _skip("needs oracle host")))
    assert r.returncode == 0
    assert "NOT_RUN (unrelated skip)" in r.stdout and "skipped: 1" in r.stdout


def test_missing_report_fails(tmp_path):
    assert run(tmp_path, None).returncode == 1


def test_malformed_report_fails(tmp_path):
    assert run(tmp_path, "<testsuites><oops").returncode == 1


def test_wrong_root_fails(tmp_path):
    assert run(tmp_path, "<html/>").returncode == 1


def test_zero_collected_fails(tmp_path):
    r = run(tmp_path, _xml(""))
    assert r.returncode == 1 and "zero tests" in r.stderr


def test_failed_case_not_counted_as_skip(tmp_path):
    fail = '<testcase classname="t" name="f"><failure message="x"/></testcase>'
    r = run(tmp_path, _xml(fail))
    assert r.returncode == 0 and "executed (not skipped): 1" in r.stdout
