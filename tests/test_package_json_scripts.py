"""package.json scripts must never be `exit 0` placeholders (#401).

A script that echoes a message and exits 0 without running a check reads as
PASS while being NOT_RUN. CLAUDE.md forbids that.
"""
import json
import re
from pathlib import Path

PACKAGE_JSON = Path(__file__).resolve().parents[1] / "package.json"
_EXIT0 = re.compile(r"(^|[;&|]\s*)exit\s+0\s*$")


def placeholder_scripts(scripts):
    """Names of scripts that only echo and then `exit 0`."""
    bad = []
    for name, cmd in scripts.items():
        if not _EXIT0.search(cmd.strip()):
            continue
        parts = [p.strip() for p in re.split(r"&&|;", cmd)]
        if all(p.startswith("echo") or p.startswith("exit") for p in parts if p):
            bad.append(name)
    return bad


def test_no_exit0_placeholder_scripts():
    scripts = json.loads(PACKAGE_JSON.read_text())["scripts"]
    assert placeholder_scripts(scripts) == []


def test_negative_control_detects_placeholder():
    synthetic = {
        "test": "echo 'No tests configured.' && exit 0",
        "ok": "python3 -m pytest -q tests",
        "lint": "echo 'NOT_RUN' && exit 2",
    }
    assert placeholder_scripts(synthetic) == ["test"]


def test_original_boilerplate_is_flagged():
    synthetic = {
        "check:ci": "echo 'No CI checks configured. Customize this script for your project.' && exit 0",
        "lint": "echo 'No linter configured.' && exit 0",
    }
    assert placeholder_scripts(synthetic) == ["check:ci", "lint"]
