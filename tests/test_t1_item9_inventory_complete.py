#!/usr/bin/env python3
"""#624 -- the T1 item 9 inventory lists every member of the classes it
declares, and nothing else.

What this pins, and what it does NOT:

  * PINS: set equality between `signoff/t1-item9-inventory.json`'s
    `testbenches` list and the union of the three classes that inventory's
    own `description` names -- the pytest files under `tests/`, the
    `rtl/lint_manifest.json` files classed `testbench`/`mutant_control`, and
    the scripts keyed in `tests/comparator_registry.json` and
    `tests/negative_controls_registry.json`. Also that the list is sorted
    and carries each path once.
  * DOES NOT: run a bench, check a bench's content, or claim anything about
    RTL exactness, model-vs-reference agreement, synthesis or preset
    quality. This is coverage bookkeeping only: it says the item 9 inventory
    names the right set of files, never that any of them passes.

Why it exists: nothing mechanical enforced the inventory's completeness, so
the gap grew silently by one every time a PR added a test module. `klt
signoff --attest 9 --check` verifies the *listed* paths (each entry's
`content_hash`) and fails on drift, but an unlisted file is simply never
attested, so the item 9 coverage claim under-reported without any job going
red. Measured when this test was added: 117 `tests/test_*.py` on disk and
114 listed, plus `tools/check_provenance_controls.py` keyed `LIVE` in
`tests/negative_controls_registry.json` and unlisted.

The division of labour with the existing gate: **listed means attested.**
This test reads only the inventory and the tree -- never the envelope. The
`signoff` workflow's `klt signoff --attest 9 ... --check` step already fails
when the inventory and the committed envelope disagree (verified for #624 by
adding one entry to the inventory in place and re-running `--check`: exit 3,
reporting both the changed `provenance.input.content_hash` and the 221 ->
222 summary). So a PR that adds a test file has to list it here, and the
existing gate makes it re-derive the envelope.
"""

import fnmatch
import json
import os
import shutil

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INVENTORY_REL = "signoff/t1-item9-inventory.json"
LINT_MANIFEST_REL = "rtl/lint_manifest.json"
REGISTRY_RELS = ("tests/comparator_registry.json",
                 "tests/negative_controls_registry.json")

# The classes the inventory's own `description` declares.
PYTEST_GLOB = "test_*.py"
ATTESTED_LINT_CLASSES = ("testbench", "mutant_control")


# ------------------------------------------------------------- the classes
def pytest_files(root):
    """`tests/**/test_*.py`, repo-relative -- the inventory's first class."""
    found = set()
    base = os.path.join(root, "tests")
    for dirpath, _dirs, names in os.walk(base):
        for name in names:
            if fnmatch.fnmatch(name, PYTEST_GLOB):
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                found.add(rel.replace(os.sep, "/"))
    return found


def lint_manifest_benches(root):
    """`rtl/lint_manifest.json` files classed testbench/mutant_control."""
    with open(os.path.join(root, LINT_MANIFEST_REL), encoding="utf-8") as f:
        manifest = json.load(f)
    return {e["path"] for e in manifest["files"]
            if e["class"] in ATTESTED_LINT_CLASSES}


def registry_scripts(root):
    """Scripts keyed in the comparator and negative-control registries.

    Same key-to-path rule `tests/test_negative_controls_live.py` uses: a
    bare filename is an alias for `tools/<name>`, a key containing "/" is
    already repo-relative (e.g. `model/integration/negative_controls.py`).
    """
    found = set()
    for rel in REGISTRY_RELS:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            scripts = json.load(f)["scripts"]
        for key in scripts:
            found.add(key if "/" in key else "tools/" + key)
    return found


def declared_members(root):
    """Every file the inventory's `description` says it lists."""
    return (pytest_files(root) | lint_manifest_benches(root)
            | registry_scripts(root))


def inventory_entries(root):
    with open(os.path.join(root, INVENTORY_REL), encoding="utf-8") as f:
        return json.load(f)["testbenches"]


# ------------------------------------------------------------------ audit
def audit_inventory(entries, root):
    """Findings for drift between the inventory list and the tree.

    Returned as findings rather than asserted inline so the failure controls
    below can run this same audit against a scratch tree and a doctored
    list.
    """
    findings = []
    if list(entries) != sorted(entries):
        findings.append("the testbenches list is not sorted")
    seen = set()
    for rel in entries:
        if rel in seen:
            findings.append(f"{rel}: listed more than once")
        seen.add(rel)
    members = declared_members(root)
    for rel in sorted(members - seen):
        findings.append(
            f"{rel}: a member of a class the inventory's description "
            "declares, but not listed -- it is never attested")
    for rel in sorted(seen - members):
        findings.append(
            f"{rel}: listed, but a member of none of the three declared "
            "classes (pytest file, lint-manifest testbench/mutant_control, "
            "registered comparator/negative-control script)")
    return findings


# ------------------------------------------------------------ scratch tree
def scratch_tree(tmp_path):
    """A copy of just the inputs the audit reads, writable by the controls.

    Only names matter to the audit, so the pytest files are created empty;
    the lint manifest, both registries and the inventory are copied byte for
    byte.
    """
    root = tmp_path / "repo"
    for rel in sorted(pytest_files(REPO)):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for rel in (LINT_MANIFEST_REL, INVENTORY_REL) + REGISTRY_RELS:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(REPO, rel), dest)
    return root


def write_inventory(root, entries):
    path = root / INVENTORY_REL
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    doc["testbenches"] = list(entries)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


# ------------------------------------------------------------- the contract
def test_the_scan_sees_a_nonempty_tree():
    """Coverage leg: an empty scan would make every audit below vacuous."""
    assert len(pytest_files(REPO)) > 100, len(pytest_files(REPO))
    assert len(lint_manifest_benches(REPO)) > 50, \
        len(lint_manifest_benches(REPO))
    assert len(registry_scripts(REPO)) > 40, len(registry_scripts(REPO))
    # The two key shapes the registries actually use must both resolve.
    scripts = registry_scripts(REPO)
    assert "tools/check_provenance_controls.py" in scripts
    assert "model/integration/negative_controls.py" in scripts
    assert os.path.basename(__file__) in \
        {os.path.basename(p) for p in pytest_files(REPO)}


def test_the_inventory_lists_every_declared_member_and_nothing_else():
    """The whole point: an unlisted bench or a stray entry fails here.

    A finding means the item 9 coverage claim no longer matches the tree.
    The fix is to correct `signoff/t1-item9-inventory.json` and re-derive
    the envelope in the same change (`klt signoff --attest 9`), never to
    relax this audit.
    """
    assert audit_inventory(inventory_entries(REPO), REPO) == []


def test_every_listed_path_exists_on_disk():
    """Listed means attested, so a listed path that is gone is a stale
    claim -- `klt --attest 9` would refuse it, but say so here too."""
    missing = [rel for rel in inventory_entries(REPO)
               if not os.path.exists(os.path.join(REPO, rel))]
    assert missing == [], missing


def test_this_test_is_itself_listed():
    """#624's own rule, pinned: the completeness test is a pytest file, so
    it is a member of the first class and must be attested like any other."""
    rel = "tests/" + os.path.basename(__file__)
    assert rel in inventory_entries(REPO)


# -------------------------------------------------------- failure controls
def test_control_the_audit_is_not_always_firing(tmp_path):
    """Non-vacuity for the three controls below: the scratch tree plus the
    committed inventory must be clean, or they would fire on anything."""
    root = scratch_tree(tmp_path)
    assert audit_inventory(inventory_entries(root), root) == []


def test_control_a_removed_inventory_entry_is_reported(tmp_path):
    root = scratch_tree(tmp_path)
    entries = inventory_entries(root)
    dropped = "tests/test_byte_frozen_sources.py"
    assert dropped in entries
    kept = [rel for rel in entries if rel != dropped]
    write_inventory(root, kept)
    findings = audit_inventory(inventory_entries(root), root)
    assert any(f.startswith(dropped + ":") and "not listed" in f
               for f in findings), findings


def test_control_a_new_unlisted_test_file_is_reported(tmp_path):
    """A dummy test file fails the audit until it is listed."""
    root = scratch_tree(tmp_path)
    dummy = "tests/test_zz_scratch.py"
    (root / dummy).write_text("", encoding="utf-8")

    findings = audit_inventory(inventory_entries(root), root)
    assert any(f.startswith(dummy + ":") and "not listed" in f
               for f in findings), findings

    write_inventory(root, sorted(inventory_entries(root) + [dummy]))
    assert audit_inventory(inventory_entries(root), root) == []


def test_control_an_entry_outside_the_declared_classes_is_reported(tmp_path):
    """The audit is set equality, not containment: a path that belongs to
    none of the three classes must not be smuggled into the inventory."""
    root = scratch_tree(tmp_path)
    stray = "tools/zz_not_a_declared_class.py"
    write_inventory(root, sorted(inventory_entries(root) + [stray]))
    findings = audit_inventory(inventory_entries(root), root)
    assert any(f.startswith(stray + ":") and "none of the three" in f
               for f in findings), findings


@pytest.mark.parametrize("doctor", ["unsorted", "duplicate"])
def test_control_list_hygiene_is_reported(doctor, tmp_path):
    """Sorted-and-once-each is part of the contract, so break each leg."""
    root = scratch_tree(tmp_path)
    entries = inventory_entries(root)
    if doctor == "unsorted":
        broken = list(reversed(entries))
        expected = "not sorted"
    else:
        broken = sorted(entries + [entries[0]])
        expected = "listed more than once"
    write_inventory(root, broken)
    findings = audit_inventory(inventory_entries(root), root)
    assert any(expected in f for f in findings), findings
