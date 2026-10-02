#!/usr/bin/env python3
"""#254 -- the byte-frozen source registry is complete and current.

What this pins, and what it does NOT:

  * PINS: `docs/byte-frozen-sources.json` lists every source file whose
    sha256 is re-derived live from the current bytes and compared against a
    committed evidence record (a *live pin*), every file whose digest a
    committed record carries, and every script that stamps a one-shot
    `script_sha256`/`tool_sha256` provenance digest of itself (*historical
    provenance*). The registry's own digests are recomputed here, so an edit
    to any covered file fails this file as well as the owning leaf's test.
  * DOES NOT: establish RTL exactness, model-vs-reference agreement, or any
    preset claim. This is evidence bookkeeping only: it says which bytes a
    committed record pins, never that the record's verdict is right.

Why it exists: the freeze was written down only in a commit message
(`2b268c7`), so the same ruff/pyflakes dead-code findings in these files were
proposed for removal twice (#147/PR #152, #252) and declined twice. Removing
one of those findings moves the pin, which silently turns a committed
`status: PASS` record STALE. `model/effects/aw-49/galactic_model.py` was the
one live pin with no freshness test at all -- dropping its unused `import sys`
moved `frozen_revision()` with zero test failures. That gap is closed by
`tests/test_sxt028a.py`; this file makes the whole set discoverable and
keeps the registry from drifting silently.

The two classes must not be conflated: a live pin must always equal the
current bytes, while a `script_sha256` stamp is historical and legitimately
names superseded bytes (every one of them does today).
"""

import ast
import copy
import functools
import hashlib
import json
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_REL = os.path.join("docs", "byte-frozen-sources.json")
DOC_REL = os.path.join("docs", "byte-frozen-sources.md")
RECORD_SUFFIXES = (".json", ".txt", ".md", ".csv")


# ------------------------------------------------------------------ helpers
@functools.lru_cache(maxsize=1)
def tracked_files():
    out = subprocess.run(["git", "-C", REPO, "ls-files", "-z"],
                         capture_output=True, text=True, check=True).stdout
    return tuple(p for p in out.split("\0") if p)


def tracked_python():
    """Tracked python outside tests/ -- the sources a pin can cover.

    `tests/` is excluded on purpose: a test that *checks* a pin names the
    same idiom as the pin itself, and a test file is never pinned.
    """
    return tuple(p for p in tracked_files()
                 if p.endswith(".py") and not p.startswith("tests/"))


@functools.lru_cache(maxsize=1)
def record_corpus():
    """Every committed text record, read once (the pins live inside these)."""
    out = {}
    for rel in tracked_files():
        if rel.endswith(RECORD_SUFFIXES):
            with open(os.path.join(REPO, rel), encoding="utf-8",
                      errors="replace") as f:
                out[rel] = f.read()
    return out


def records_containing(text):
    return sorted(rel for rel, body in record_corpus().items()
                  if text in body)


def word_pattern(word):
    """The decimal revision word as a standalone number (not a substring)."""
    return re.compile(rf"(?<![0-9]){int(word)}(?![0-9])")


def sha256_of(rels):
    """sha256 over the named files' bytes, concatenated in the given order."""
    h = hashlib.sha256()
    for rel in rels:
        with open(os.path.join(REPO, rel), "rb") as f:
            h.update(f.read())
    return h.hexdigest()


@functools.lru_cache(maxsize=1)
def registry():
    with open(os.path.join(REPO, REGISTRY_REL), encoding="utf-8") as f:
        return json.load(f)


def live_pins(reg=None):
    return (reg or registry())["live_pins"]


def provenance(reg=None):
    return (reg or registry())["historical_provenance"]


def covered_files(reg=None):
    return {rel for e in live_pins(reg) for rel in e["covers"]}


# -------------------------------------------------------------- detectors
def self_hash_sites_in(src, rel):
    """(function name, covered files) for every self-hashing revision pin.

    A pin site is a module-level function whose name ends in `revision` and
    whose body hashes file bytes (`sha256` over `__file__`/`_HERE` paths).
    The files it covers are the `.py` names it reads, in source order, or
    the module itself when it hashes only `__file__`.
    """
    found = []
    if "sha256" not in src:
        return found
    for node in ast.parse(src, rel).body:
        if not (isinstance(node, ast.FunctionDef)
                and node.name.endswith("revision")):
            continue
        seg = ast.get_source_segment(src, node) or ""
        if "sha256" not in seg:
            continue
        if "__file__" not in seg and "_HERE" not in seg:
            continue
        names = [n.value for n in ast.walk(node)
                 if isinstance(n, ast.Constant)
                 and isinstance(n.value, str) and n.value.endswith(".py")]
        covers = [os.path.join(os.path.dirname(rel), n) for n in names]
        found.append((node.name, covers or [rel]))
    return found


def discover_self_hash_pins():
    """pin id -> covered files, derived from the tree (not the registry)."""
    out = {}
    for rel in tracked_python():
        with open(os.path.join(REPO, rel), encoding="utf-8") as f:
            src = f.read()
        for name, covers in self_hash_sites_in(src, rel):
            out[f"{rel}::{name}()"] = covers
    return out


def discover_self_stamping_scripts():
    """Scripts that stamp a one-shot provenance digest of their own bytes."""
    out = {}
    for rel in tracked_python():
        with open(os.path.join(REPO, rel), encoding="utf-8") as f:
            src = f.read()
        if "__file__" not in src:
            continue
        for field in ("tool_sha256", "script_sha256"):
            if f'"{field}"' in src:
                out[rel] = field
                break
    return out


def discover_recorded_sources():
    """Tracked sources whose CURRENT bytes are hashed into some record."""
    out = {}
    for rel in tracked_python():
        digest = sha256_of([rel])
        if records_containing(digest):
            out[rel] = digest
    return out


# ----------------------------------------------------------------- audits
def audit_live_pins(reg):
    """Findings for every live pin whose digest no longer matches the tree.

    Returned as findings rather than asserted inline so the negative
    controls below can run this same audit against a doctored registry.
    """
    findings = []
    for e in live_pins(reg):
        missing = [rel for rel in e["covers"]
                   if not os.path.exists(os.path.join(REPO, rel))]
        if missing:
            findings.append(f"{e['pin']}: covered file(s) missing {missing}")
            continue
        got = sha256_of(e["covers"])
        if got != e["sha256"]:
            findings.append(
                f"{e['pin']}: registry says {e['sha256']}, the tree hashes "
                f"{got} -- the committed record(s) {e['recorded_in']} are "
                "STALE against these bytes")
            continue
        if not e["recorded_in"]:
            findings.append(f"{e['pin']}: no committed record listed")
        for rel in e["recorded_in"]:
            if e["sha256"] not in record_corpus().get(rel, ""):
                findings.append(
                    f"{e['pin']}: {rel} does not carry {e['sha256']}")
        for rel in e.get("recorded_word_in", []):
            pat = word_pattern(e["revision_word"])
            if not pat.search(record_corpus().get(rel, "")):
                findings.append(
                    f"{e['pin']}: {rel} does not carry revision word "
                    f"{e['revision_word']}")
    return findings


def audit_completeness(reg):
    """Findings for drift between the tree's pin sites and the registry."""
    findings = []
    declared = {e["pin"]: e["covers"] for e in live_pins(reg)
                if e["mechanism"] == "self_hash"}
    discovered = discover_self_hash_pins()
    for pin, covers in sorted(discovered.items()):
        if pin not in declared:
            findings.append(
                f"undeclared self-hash pin site {pin} covering {covers}")
        elif declared[pin] != covers:
            findings.append(
                f"{pin}: registry says it covers {declared[pin]}, the source "
                f"hashes {covers}")
    for pin in sorted(set(declared) - set(discovered)):
        findings.append(f"registry names a pin site absent from the tree: "
                        f"{pin}")

    known = covered_files(reg) | {e["path"] for e in provenance(reg)}
    for rel, digest in sorted(discover_recorded_sources().items()):
        if rel not in known:
            findings.append(
                f"{rel}: its current bytes ({digest[:12]}...) are hashed "
                f"into {records_containing(digest)} but it is not in the "
                "registry")

    declared_prov = {e["path"]: e["stamped_field"] for e in provenance(reg)}
    discovered_prov = discover_self_stamping_scripts()
    for rel, field in sorted(discovered_prov.items()):
        if rel not in declared_prov:
            findings.append(f"undeclared self-stamping script {rel} "
                            f"({field})")
        elif declared_prov[rel] != field:
            findings.append(
                f"{rel}: registry says {declared_prov[rel]}, source stamps "
                f"{field}")
    for rel in sorted(set(declared_prov) - set(discovered_prov)):
        findings.append(f"registry names a self-stamping script that no "
                        f"longer stamps itself: {rel}")
    return findings


# ------------------------------------------------------- non-vacuity legs
def test_the_scans_see_a_nonempty_tree():
    """Coverage leg: scans over an empty tree would vacuously 'pass'."""
    assert len(tracked_python()) > 200, len(tracked_python())
    assert len(record_corpus()) > 500, len(record_corpus())
    assert "model/effects/aw-49/galactic_model.py" in tracked_python()
    assert "reports/sxt-028a/rtl-exactness.json" in record_corpus()


def test_registry_is_well_formed():
    reg = registry()
    assert reg["schema_version"] == 1
    assert reg["doc"] == DOC_REL.replace(os.sep, "/")
    assert live_pins(reg) and provenance(reg)
    seen = set()
    for e in live_pins(reg):
        assert e["mechanism"] in ("self_hash", "manifest_entry"), e["pin"]
        assert e["pin"] not in seen, e["pin"]
        seen.add(e["pin"])
        assert len(e["sha256"]) == 64, e["pin"]
        assert e["covers"], e["pin"]
        assert e["leaf"].strip(), e["pin"]


# --------------------------------------------------- the live-pin contract
def test_every_live_pin_still_hashes_to_its_recorded_digest():
    """The whole point: an edit to any covered file fails here.

    Any finding below means a committed record that still says `PASS` is now
    STALE. The fix is never to re-pin this registry on its own -- re-run the
    leaf's comparator/control tooling and re-commit the records named in
    `recorded_in` in the same change (docs/byte-frozen-sources.md).
    """
    assert audit_live_pins(registry()) == []


def test_every_live_pin_names_an_existing_freshness_check():
    for e in live_pins():
        rel = e["freshness_test"]
        path = os.path.join(REPO, rel)
        assert os.path.exists(path), f"{e['pin']}: missing {rel}"
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert "revision" in src or "sha256" in src, \
            f"{rel} asserts no live digest for {e['pin']}"


def test_the_sxt028a_pin_now_has_a_leaf_freshness_test():
    """#254's first outcome, pinned here as well as in tests/test_sxt028a.py.

    SXT-028a was the one live pin whose leaf test never compared the record
    against `frozen_revision()`.
    """
    entry = next(e for e in live_pins()
                 if e["covers"] == ["model/effects/aw-49/galactic_model.py"])
    assert entry["freshness_test"] == "tests/test_sxt028a.py"
    with open(os.path.join(REPO, "tests", "test_sxt028a.py"),
              encoding="utf-8") as f:
        src = f.read()
    assert "gm.frozen_revision()" in src
    assert "model_frozen_revision" in src
    assert "expected_revision" in src


# ------------------------------------------------------ the two classes
def test_historical_provenance_carries_no_live_equality_claim():
    """`script_sha256` is stamped once; it must not be asserted live.

    Records with superseded stamps are committed on purpose, so a
    live-equality assertion here would be wrong -- and would fail today.
    """
    for e in provenance():
        assert "sha256" not in e, e["path"]
        assert os.path.exists(os.path.join(REPO, e["path"])), e["path"]
        recorded = bool(records_containing(sha256_of([e["path"]])))
        assert recorded == e["current_bytes_recorded"], (
            f"{e['path']}: registry says current_bytes_recorded="
            f"{e['current_bytes_recorded']}, the tree says {recorded}. "
            "Update the registry entry (this is provenance drift, not a "
            "stale pin -- see docs/byte-frozen-sources.md).")


def test_no_file_is_both_a_live_pin_and_historical_provenance():
    both = covered_files() & {e["path"] for e in provenance()}
    assert both == set(), both


# ------------------------------------------------------ registry currency
def test_the_registry_matches_the_tree():
    """No silent drift: a new pin site or stamp must land in the registry."""
    assert audit_completeness(registry()) == []


def test_the_documentation_names_every_registry_entry():
    with open(os.path.join(REPO, DOC_REL), encoding="utf-8") as f:
        doc = f.read()
    assert REGISTRY_REL.replace(os.sep, "/") in doc
    for rel in sorted(covered_files() | {e["path"] for e in provenance()}):
        assert rel in doc, f"{rel} is in the registry but not in {DOC_REL}"


@pytest.mark.parametrize("rel", ["AGENTS.md", "CLAUDE.md"])
def test_the_agent_instructions_point_at_the_registry(rel):
    """The failure this issue is about: the rule was undiscoverable.

    Both prior removal attempts were made by agents working from these two
    files plus a lint run, so the pointer has to live here.
    """
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        text = f.read()
    assert DOC_REL.replace(os.sep, "/") in text


# ---------------------------------------------------- negative controls
def test_control_the_documented_mutant_moves_the_galactic_pin():
    """The exact #252 mutant: dropping the unused `import sys`.

    Done in memory -- the file itself must not be touched. Before #254 this
    edit passed every test; it must now be detectable.
    """
    rel = "model/effects/aw-49/galactic_model.py"
    entry = next(e for e in live_pins() if e["covers"] == [rel])
    with open(os.path.join(REPO, rel), "rb") as f:
        original = f.read()
    assert hashlib.sha256(original).hexdigest() == entry["sha256"]
    mutant = original.replace(b"import sys\n", b"", 1)
    assert mutant != original, "the mutant did not apply"
    moved = hashlib.sha256(mutant).hexdigest()
    assert moved != entry["sha256"]
    assert not records_containing(moved), \
        "the mutant's digest is already recorded; the control is void"


@pytest.mark.parametrize("doctor,expect", [
    ("digest", "STALE against these bytes"),
    ("record", "does not carry"),
    ("word", "does not carry revision word"),
])
def test_control_the_live_pin_audit_fires_on_a_doctored_registry(
        doctor, expect):
    reg = copy.deepcopy(registry())
    if doctor == "digest":
        reg["live_pins"][0]["sha256"] = "0" * 64
    elif doctor == "record":
        reg["live_pins"][0]["recorded_in"].append("README.md")
    else:
        entry = next(e for e in reg["live_pins"] if "recorded_word_in" in e)
        entry["revision_word"] += 1
    findings = audit_live_pins(reg)
    assert findings, f"the {doctor} audit leg did not fire"
    assert any(expect in f for f in findings), findings


@pytest.mark.parametrize("doctor", ["drop_pin", "wrong_covers", "drop_prov",
                                    "phantom_pin"])
def test_control_the_completeness_audit_fires_on_registry_drift(doctor):
    reg = copy.deepcopy(registry())
    if doctor == "drop_pin":
        dropped = next(e for e in reg["live_pins"]
                       if e["mechanism"] == "self_hash")
        reg["live_pins"] = [e for e in reg["live_pins"] if e is not dropped]
    elif doctor == "wrong_covers":
        entry = next(e for e in reg["live_pins"]
                     if e["mechanism"] == "self_hash")
        entry["covers"] = ["refusal.py"]
    elif doctor == "drop_prov":
        reg["historical_provenance"] = reg["historical_provenance"][1:]
    else:
        reg["live_pins"].append({
            "pin": "model/nonexistent.py::model_revision()",
            "leaf": "none", "mechanism": "self_hash",
            "covers": ["model/nonexistent.py"], "sha256": "0" * 64,
            "recorded_in": [], "freshness_test": "tests/test_sxt028a.py"})
    assert audit_completeness(reg), f"the {doctor} leg did not fire"


def test_control_the_completeness_audit_is_not_always_firing():
    """The paired positive leg for the controls above."""
    assert audit_completeness(registry()) == []
    assert audit_live_pins(registry()) == []


def test_control_the_pin_site_detector_fires_and_discriminates():
    """The AST detector must catch a new pin site and ignore a plain hash."""
    pinned = (
        "import hashlib, os\n"
        "_HERE = os.path.dirname(__file__)\n"
        "\n"
        "def model_revision():\n"
        "    h = hashlib.sha256()\n"
        "    for n in ('a_model.py', 'b_tables.py'):\n"
        "        h.update(open(os.path.join(_HERE, n), 'rb').read())\n"
        "    return h.hexdigest()\n")
    assert self_hash_sites_in(pinned, "model/new/a_model.py") == [
        ("model_revision", ["model/new/a_model.py",
                            "model/new/b_tables.py"])]
    plain = ("import hashlib\n"
             "\n"
             "def digest_of(data):\n"
             "    return hashlib.sha256(data).hexdigest()\n")
    assert self_hash_sites_in(plain, "tools/plain.py") == []
    with open(os.path.join(REPO, "tests", "test_byte_frozen_sources.py"),
              encoding="utf-8") as f:
        assert self_hash_sites_in(f.read(),
                                  "tests/test_byte_frozen_sources.py") == []
