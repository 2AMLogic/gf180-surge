"""Shell failure control for the rtl-sim pytest/checker step in ci.yml.

GitHub Actions runs a Linux ``run:`` block as ``bash -e {0}``. This test
extracts the exact script of the "Run pytest (JUnit XML) and gate on simulator
skips" step from ``.github/workflows/ci.yml`` and executes it under
``bash -e`` with stub ``python3``/``iverilog``/``vvp`` executables first on
PATH, so the step's own status-capture logic is what is exercised.

Required behavior:
  * a failing pytest still runs the checker, and the step exits with pytest's
    original nonzero status even when the checker succeeds;
  * a checker failure is retained when pytest succeeds.

``OLD_SCRIPT`` is the pre-fix step body (no ``set +e``); the negative control
asserts the same harness detects its defect, so the harness is live.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
STEP_NAME = "Run pytest (JUnit XML) and gate on simulator skips"
CHECKER_MARK = "STUB-CHECKER-RAN"

OLD_SCRIPT = """\
set -uo pipefail
command -v iverilog >/dev/null && command -v vvp >/dev/null || {
  echo "FAIL: iverilog and vvp are both required" >&2; exit 1; }
start=$(date +%s)
python3 -m pytest -q -rs -p no:cacheprovider tests --junitxml=rtl-sim-junit.xml
pytest_rc=$?
echo "pytest exit status: ${pytest_rc}; duration: $(( $(date +%s) - start ))s"
python3 tools/check_rtl_ci_results.py rtl-sim-junit.xml
check_rc=$?
echo "report checker exit status: ${check_rc}"
if [ "${pytest_rc}" -ne 0 ]; then exit "${pytest_rc}"; fi
exit "${check_rc}"
"""

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available"
)


def extract_step_script(text: str, step_name: str) -> str:
    """Return the dedented ``run: |`` block of the named step (stdlib only)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == f"- name: {step_name}":
            break
    else:
        raise AssertionError(f"step {step_name!r} not found in {CI_YML}")
    run_line = lines[i + 1]
    assert run_line.strip() == "run: |", f"expected 'run: |' after step name, got {run_line!r}"
    body = []
    indent = None
    for line in lines[i + 2:]:
        if not line.strip():
            body.append("")
            continue
        cur = len(line) - len(line.lstrip(" "))
        if indent is None:
            indent = cur
        if cur < indent:
            break
        body.append(line[indent:])
    script = "\n".join(body).rstrip() + "\n"
    assert "pytest_rc=$?" in script and "check_rc=$?" in script
    return script


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def run_step(tmp_path: Path, script: str, pytest_rc: int, check_rc: int):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub(
        bindir / "python3",
        'if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pytest" ]; then\n'
        '  echo STUB-PYTEST-RAN; exit "$STUB_PYTEST_RC"\n'
        "fi\n"
        'case "${1:-}" in\n'
        f'  tools/check_rtl_ci_results.py) echo {CHECKER_MARK}; exit "$STUB_CHECK_RC";;\n'
        "esac\n"
        'echo "unexpected python3 call: $*" >&2; exit 97\n',
    )
    _stub(bindir / "iverilog", "exit 0\n")
    _stub(bindir / "vvp", "exit 0\n")
    script_path = tmp_path / "step.sh"
    script_path.write_text(script)
    env = {
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "STUB_PYTEST_RC": str(pytest_rc),
        "STUB_CHECK_RC": str(check_rc),
    }
    # Mirror GitHub's implicit Linux run shell (no `shell:` key): `bash -e {0}`.
    return subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def step_script() -> str:
    return extract_step_script(CI_YML.read_text(), STEP_NAME)


def test_extracted_script_disables_errexit(step_script):
    assert "set +e" in step_script


@pytest.mark.parametrize("pytest_rc", [1, 2, 5])
def test_pytest_failure_still_runs_checker_and_returns_pytest_status(
    tmp_path, step_script, pytest_rc
):
    r = run_step(tmp_path, step_script, pytest_rc=pytest_rc, check_rc=0)
    assert CHECKER_MARK in r.stdout, r.stdout + r.stderr
    assert f"pytest exit status: {pytest_rc};" in r.stdout
    assert "report checker exit status: 0" in r.stdout
    assert r.returncode == pytest_rc


def test_pytest_failure_takes_precedence_over_checker_failure(tmp_path, step_script):
    r = run_step(tmp_path, step_script, pytest_rc=1, check_rc=3)
    assert CHECKER_MARK in r.stdout
    assert "report checker exit status: 3" in r.stdout
    assert r.returncode == 1


def test_checker_failure_retained_when_pytest_passes(tmp_path, step_script):
    r = run_step(tmp_path, step_script, pytest_rc=0, check_rc=1)
    assert CHECKER_MARK in r.stdout
    assert "report checker exit status: 1" in r.stdout
    assert r.returncode == 1


def test_both_pass(tmp_path, step_script):
    r = run_step(tmp_path, step_script, pytest_rc=0, check_rc=0)
    assert CHECKER_MARK in r.stdout
    assert r.returncode == 0


def test_negative_control_old_script_skips_checker(tmp_path):
    """The pre-fix step body must fail the property under the same harness."""
    r = run_step(tmp_path, OLD_SCRIPT, pytest_rc=1, check_rc=0)
    assert "STUB-PYTEST-RAN" in r.stdout
    assert CHECKER_MARK not in r.stdout
    assert "pytest exit status" not in r.stdout
    assert r.returncode == 1
