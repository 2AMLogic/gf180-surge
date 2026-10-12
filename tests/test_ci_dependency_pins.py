"""Contract test for the CI dependency manifest (issue #354).

Checks: both ci.yml install sites use requirements-ci.txt, the manifest has
exact == pins for numpy and pytest, and a live negative control proves the
checker rejects floating/mismatched manifests and workflows. It does not
compare report stamps (see docs/numpy-stamp-inventory.md) and makes no
numeric-fidelity claim.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "requirements-ci.txt"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
REQUIRED = ("numpy", "pytest")
EXACT = re.compile(r"^([A-Za-z0-9_.-]+)==(\d+(?:\.\d+)+)\s*(?:#.*)?$")


def manifest_problems(text):
    pins, problems = {}, []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = EXACT.match(line)
        if not m:
            problems.append(f"not an exact == pin: {line!r}")
            continue
        pins[m.group(1).lower()] = m.group(2)
    for name in REQUIRED:
        if name not in pins:
            problems.append(f"missing exact pin for {name}")
    return problems


def workflow_problems(text):
    problems = []
    installs = [l.strip() for l in text.splitlines() if "pip install" in l]
    if len(installs) != 2:
        problems.append(f"expected 2 pip install sites, found {len(installs)}")
    for l in installs:
        if "-r requirements-ci.txt" not in l:
            problems.append(f"install site does not use manifest: {l!r}")
    return problems


def test_manifest_exact_pins():
    assert manifest_problems(MANIFEST.read_text()) == []


def test_ci_install_sites_use_manifest():
    assert workflow_problems(CI_YML.read_text()) == []


@pytest.mark.parametrize("bad", [
    "numpy\npytest==9.1.1\n",
    "numpy>=2.4\npytest==9.1.1\n",
    "numpy==2.4.*\npytest==9.1.1\n",
    "numpy==2.4.2\n",
    "pytest==9.1.1\n",
])
def test_negative_control_manifest_rejected(bad):
    assert manifest_problems(bad), "checker accepted a floating/incomplete manifest"


def test_negative_control_workflow_rejected():
    live = CI_YML.read_text()
    floating = live.replace("-r requirements-ci.txt", "numpy pytest")
    assert floating != live
    assert workflow_problems(floating), "checker accepted floating install"
