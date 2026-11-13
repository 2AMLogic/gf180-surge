"""Contract test for the CI dependency manifest (issues #354, #621).

Checks: every workflow that pip-installs Python packages does so from a pinned
manifest, the manifest has exact == pins for numpy and pytest, and live
negative controls prove the checker rejects floating/mismatched manifests and
workflows. It does not compare report stamps (see docs/numpy-stamp-inventory.md)
and makes no numeric-fidelity claim.

Workflows are discovered from the tree rather than named one at a time, so a
workflow added later is covered without editing this file (#621: the
slow-controls job floated numpy/pytest for a month because the checker read
ci.yml alone). Coverage and agreement are asserted separately: the census below
fails when the set of install sites changes, so the agreement check can never
pass vacuously.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = "requirements-ci.txt"
MANIFEST = ROOT / MANIFEST_REL
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIRED = ("numpy", "pytest")
EXACT = re.compile(r"^([A-Za-z0-9_.-]+)==(\d+(?:\.\d+)+)\s*(?:#.*)?$")

# Workflows allowed to install a manifest other than requirements-ci.txt, and
# the exact manifest each may install. signoff.yml installs the klayout-tools
# pin, which lives in signoff/requirements.txt only (one place). An install
# from an unlisted manifest -- or from no manifest at all -- is a failure, so
# adopting a new one is a deliberate edit here, not a silent drift.
ALLOWED_OTHER_MANIFESTS = {
    "signoff.yml": "signoff/requirements.txt",
}

# Coverage census: every workflow with pip install sites, and how many. This is
# coverage, not agreement -- it says which sites the agreement test below reads,
# so a site that is added, removed, or renamed out of view fails visibly instead
# of shrinking the checked set to nothing.
EXPECTED_SITES = {
    "ci.yml": 2,
    "signoff.yml": 1,
    "slow-controls.yml": 1,
}


def workflow_texts():
    """Every workflow file in the tree, keyed by file name."""
    paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    return {p.name: p.read_text() for p in paths}


def install_sites(text):
    return [l.strip() for l in text.splitlines() if "pip install" in l]


def site_census(texts):
    return {n: len(s) for n, t in texts.items() if (s := install_sites(t))}


def workflow_problems(name, text):
    """Install sites in one workflow that do not use a pinned manifest."""
    problems = []
    allowed = ALLOWED_OTHER_MANIFESTS.get(name)
    for line in install_sites(text):
        if f"-r {MANIFEST_REL}" in line:
            continue
        if allowed and f"-r {allowed}" in line:
            continue
        problems.append(f"{name}: install site does not use a pinned manifest: {line!r}")
    return problems


def all_workflow_problems(texts):
    return [p for name, text in sorted(texts.items())
            for p in workflow_problems(name, text)]


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


def test_manifest_exact_pins():
    assert manifest_problems(MANIFEST.read_text()) == []


def test_install_site_census():
    """Coverage: which install sites exist. Reported apart from agreement."""
    assert site_census(workflow_texts()) == EXPECTED_SITES


def test_all_install_sites_use_pinned_manifest():
    """Agreement: every discovered site installs from a pinned manifest."""
    assert all_workflow_problems(workflow_texts()) == []


@pytest.mark.parametrize("bad", [
    "numpy\npytest==9.1.1\n",
    "numpy>=2.4\npytest==9.1.1\n",
    "numpy==2.4.*\npytest==9.1.1\n",
    "numpy==2.4.2\n",
    "pytest==9.1.1\n",
])
def test_negative_control_manifest_rejected(bad):
    assert manifest_problems(bad), "checker accepted a floating/incomplete manifest"


@pytest.mark.parametrize("name", ["ci.yml", "slow-controls.yml"])
def test_negative_control_floating_install_rejected(name):
    """Live control against each site that installs requirements-ci.txt.

    Reverting the #621 change alone -- restoring the literal `numpy pytest`
    install in slow-controls.yml -- must fail the agreement check.
    """
    live = (WORKFLOWS / name).read_text()
    floating = live.replace(f"-r {MANIFEST_REL}", "numpy pytest")
    assert floating != live, (
        f"{name} has no {MANIFEST_REL} install to mutate: this control went "
        f"vacuous because the site stopped using the pinned manifest")
    assert workflow_problems(name, floating), "checker accepted floating install"


def test_negative_control_other_manifest_not_allowlisted_rejected():
    """The signoff.yml allowance is per-file, not a global escape hatch."""
    borrowed = "        run: pip install -r signoff/requirements.txt\n"
    assert workflow_problems("ci.yml", borrowed), \
        "checker accepted a manifest not allow-listed for this workflow"
    assert workflow_problems("signoff.yml", borrowed) == [], \
        "allow-listed manifest should be accepted in its own workflow"


@pytest.mark.parametrize("mutation", ["drop", "add"])
def test_negative_control_census_detects_site_drift(mutation):
    """The coverage census must fail when a site disappears or appears."""
    texts = workflow_texts()
    if mutation == "drop":
        texts["slow-controls.yml"] = texts["slow-controls.yml"].replace(
            "pip install", "pip__install")
    else:
        texts["slow-controls.yml"] += "\n        run: pip install -r requirements-ci.txt\n"
    assert site_census(texts) != EXPECTED_SITES, \
        "census accepted a changed set of install sites"
