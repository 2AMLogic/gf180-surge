#!/usr/bin/env python3
"""#258 — `Refuse` has one definition, and the two exceptions stay visible.

What this pins, and what it does NOT:

  * PINS: the tracked tree contains exactly one canonical
    `class Refuse(Exception)` (in `refusal.py`) plus the two allowlisted
    self-hashed frozen models, and every other module that names `Refuse`
    at module scope is bound to that one class object.
  * DOES NOT: say anything about whether any particular refusal is correct,
    whether a refusal message is accurate, or whether any model/RTL claim
    holds. This is a single-source-of-truth bookkeeping check only.

The allowlist is two files whose `model_revision()` is a SHA-256 over their
own source, pinned by committed evidence records; editing them invalidates
those records (see `refusal.py` for the full reason). The allowlist is
written out here so that growing it is a visible diff, not a silent drift.
"""

import ast
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import refusal  # noqa: E402

DEFINITION_RE = re.compile(r"^class Refuse\(Exception\):", re.MULTILINE)

# path -> why this file may not import the shared class
ALLOWLIST = {
    "model/effects/type-phaser/phaser_model.py":
        "model_revision() is a sha256 of this file, pinned by "
        "reports/SXT-028g/rtl-exactness.json",
    "model/effects/aw-4/logical4_model.py":
        "model_revision() is a sha256 of this file + tables.py, pinned by "
        "reports/SXT-028k/ records",
}


def tracked_python_files():
    out = subprocess.run(["git", "-C", REPO, "ls-files", "*.py"],
                         capture_output=True, text=True, check=True).stdout
    return sorted(p for p in out.splitlines() if p)


def local_definitions(paths):
    found = []
    for rel in paths:
        with open(os.path.join(REPO, rel), encoding="utf-8") as f:
            if DEFINITION_RE.search(f.read()):
                found.append(rel)
    return found


def test_the_scan_sees_a_nonempty_tree():
    """Coverage leg: a scan over zero files would vacuously 'pass' below."""
    paths = tracked_python_files()
    assert len(paths) > 200, len(paths)
    assert "refusal.py" in paths


def test_only_the_canonical_module_and_the_allowlist_define_refuse():
    paths = tracked_python_files()
    defs = set(local_definitions(paths)) - {"refusal.py"}
    assert defs == set(ALLOWLIST), (
        "a local `class Refuse(Exception)` outside the allowlist: "
        f"{sorted(defs - set(ALLOWLIST))}; "
        f"missing from the tree: {sorted(set(ALLOWLIST) - defs)}. "
        "Import `Refuse` from refusal.py instead, or extend ALLOWLIST here "
        "with the reason.")


def test_the_allowlisted_files_are_the_self_hashed_frozen_models():
    """The stated reason is checked, not merely asserted in a comment."""
    for rel in ALLOWLIST:
        with open(os.path.join(REPO, rel), encoding="utf-8") as f:
            src = f.read()
        assert "def model_revision(" in src, rel
        assert "sha256" in src, rel


def test_the_canonical_class_is_a_bare_marker():
    assert issubclass(refusal.Refuse, Exception)
    assert refusal.Refuse.__mro__[1] is Exception
    own = {k for k in vars(refusal.Refuse)
           if not (k.startswith("__") and k.endswith("__"))}
    assert own == set(), own
    e = refusal.Refuse("out of scope")
    assert str(e) == "out of scope"


def test_every_other_module_binds_the_one_class():
    """Module-level `Refuse` names resolve to `refusal.Refuse` by source.

    Static, not import-based: importing every tool would need the pinned
    oracle. A module either defines `Refuse` locally (allowlist above),
    imports it, or re-exports another module's attribute of that name
    (`Refuse = other.Refuse`); nothing else may introduce the name.
    """
    offenders = []
    for rel in tracked_python_files():
        if rel == "refusal.py" or rel in ALLOWLIST:
            continue
        with open(os.path.join(REPO, rel), encoding="utf-8") as f:
            src = f.read()
        if "Refuse" not in src:
            continue
        tree = ast.parse(src, rel)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Refuse":
                offenders.append((rel, "local class"))
            if isinstance(node, ast.Assign):
                aliases_refuse = (isinstance(node.value, ast.Attribute)
                                  and node.value.attr == "Refuse")
                for t in node.targets:
                    if (isinstance(t, ast.Name) and t.id == "Refuse"
                            and not aliases_refuse):
                        offenders.append((rel, "rebinding assignment"))
    assert offenders == [], offenders


@pytest.mark.parametrize("injected", [
    "class Refuse(Exception):\n    pass\n",
    'class Refuse(Exception):\n    """a local copy"""\n',
])
def test_negative_control_the_detector_fires_on_a_reintroduced_copy(
        tmp_path, injected):
    """The control this check exists for: a new local copy must be caught."""
    p = tmp_path / "sneaky_tool.py"
    p.write_text("import os\n\n\n" + injected, encoding="utf-8")
    assert DEFINITION_RE.search(p.read_text(encoding="utf-8")) is not None


def test_negative_control_the_detector_is_not_always_firing():
    p = os.path.join(REPO, "tests", "test_shared_refuse.py")
    with open(p, encoding="utf-8") as f:
        assert DEFINITION_RE.search(f.read()) is None
