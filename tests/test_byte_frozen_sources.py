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
names superseded bytes (most of them do today; the registry's
`current_bytes_recorded` flags say which).
"""

import ast
import copy
import fnmatch
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


NUMBER_WORDS = {w: i for i, w in enumerate((
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve"))}

# Whole-registry count statements (#326). Each pattern must match exactly
# once, and each named group must equal the count derived from the JSON:
# `total` = len(historical_provenance), `false`/`true` = entries whose
# current_bytes_recorded is False/True. #269-scoped counts ("these eight",
# "seven of the eight") are deliberately NOT listed: they describe #269's
# ruling, not the registry as it stands.
DOC_COUNT_PATTERNS = (
    (r"of the (?P<total>\w+) scripts below, \*\*(?P<false>\w+)\*\* have "
     r"current bytes"),
    r"(?P<true>\w+) are exceptions:",
    r"The remaining (?P<false>\w+) stay `false`",
    (r"whole-registry counts at the top of\s+this section — (?P<total>\w+) "
     r"entries, (?P<false>\w+) `false`, (?P<true>\w+) exceptions"),
)
NOTE_COUNT_PATTERNS = (
    r"(?P<false>\w+) of these (?P<total>\w+) scripts have drifted",
    r"; (?P<true>\w+) are exceptions\.",
    r"For the (?P<false>\w+) entries that still read false",
)
# What every resolvable entry's disposition must say (the #126 shape).
COST_CAVEAT = {"json": "cost is no longer zero", "md": "cost no longer zero"}


def doc_table_rows(doc):
    """path -> disposition cell, for the historical-provenance table."""
    rows = {}
    for line in doc.splitlines():
        m = re.match(r"\| `([^`]+)` \| `(?:script|tool)_sha256` \| (.*) \|$",
                     line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


def audit_prose(reg, doc):
    """Findings where the registry's prose disagrees with its own data.

    Counts: every whole-registry count word in the .md and in
    `historical_provenance_note` must equal the number derived from
    `historical_provenance`. Dispositions: every entry whose stamp is
    resolvable (`current_bytes_recorded: true`) must carry the #126 cost
    caveat, and name a re-render, in both its JSON field and its .md row --
    the note claims "their per-entry dispositions record that".
    """
    entries = provenance(reg)
    want = {"total": len(entries),
            "false": sum(not e["current_bytes_recorded"] for e in entries),
            "true": sum(bool(e["current_bytes_recorded"]) for e in entries)}
    findings = []
    for where, text, patterns in (
            ("md", doc, DOC_COUNT_PATTERNS),
            ("historical_provenance_note", reg["historical_provenance_note"],
             NOTE_COUNT_PATTERNS)):
        for pat in patterns:
            hits = list(re.finditer(pat, text, flags=re.IGNORECASE))
            if len(hits) != 1:
                findings.append(f"{where}: count statement /{pat}/ matched "
                                f"{len(hits)} times, expected exactly 1")
                continue
            for key, word in hits[0].groupdict().items():
                got = NUMBER_WORDS.get(word.lower())
                if got != want[key]:
                    findings.append(
                        f"{where}: {hits[0].group(0)!r} says {key}={word}, "
                        f"the registry has {want[key]}")
    rows = doc_table_rows(doc)
    for e in entries:
        if e["path"] not in rows:
            findings.append(f"md: no table row for {e['path']}")
            continue
        if not e["current_bytes_recorded"]:
            continue
        for where, text in (("json", e["lint_finding_disposition"]),
                            ("md", rows[e["path"]])):
            if COST_CAVEAT[where] not in text or "re-render" not in text:
                findings.append(
                    f"{where}: {e['path']} has a resolvable stamp but its "
                    "disposition lacks the #126 cost caveat / re-render path")
    return findings


# ------------------------------------------- attested-inventory counts (#649)
# `attested_inventories` describes the two `klt signoff --attest` envelopes:
# how many files each content-hashes, how those files break down by class, how
# many checks the envelope carries in total, and how many of the inventory's
# files also have a live_pins row. Nothing re-derived those numbers, so every
# one of them had drifted (#649). Derivation, per entry:
#
#   content_hashed_checks -> len(inventory[inventory_key])
#   content_hashed_classes -> the same list, each path assigned to exactly one
#                             declared class key
#   total_checks          -> the committed envelope's attestation.check_count
#                            (NEVER recomputed here: klt owns check shaping,
#                            and `klt signoff --check` keeps the envelope
#                            honest against the inventory)
#   also_listed_as_live_pins -> live_pins rows all of whose `covers` paths are
#                               inventory entries
#
# The prose restatements in the .md and in `attested_inventories_note` are
# held to the same derived values, so a renumbering cannot drift in only one
# of the three places.

# group name -> the `content_hashed_classes` key it restates.
INVENTORY_CLASS_GROUPS = {
    9: {"tests": "tests/", "rtl": "rtl/*.sv", "tools": "tools/*.py"},
    10: {},
}
# Derived scalars every pattern below may reference: `hashed`
# (content_hashed_checks), `total` (total_checks), `live_pins`
# (also_listed_as_live_pins), `remainder` (hashed - live_pins), plus the
# class groups above. Each pattern must match exactly once in its text, so a
# deleted sentence is a finding rather than a silent pass.
INVENTORY_DOC_PATTERNS = {
    9: (
        r"The (?P<live_pins>\w+) `T1 item 9` rows are testbench",
        (r"They are (?P<live_pins>\w+) of the (?P<hashed>\w+) files that "
         r"attestation content-hashes"),
        r"for the other (?P<remainder>\w+), for the item 10 hygiene files",
        (r"\| (?P<hashed>\w+) of (?P<total>\w+) checks: (?P<tests>\w+) under "
         r"`tests/`, (?P<rtl>\w+) `rtl/\*\.sv` benches and mutant controls, "
         r"(?P<tools>\w+) `tools/\*\.py`"),
        r"The (?P<live_pins>\w+) `T1 item 9` rows in the \[Live pins\]",
        r"The other (?P<remainder>\w+) item 9 files",
        r"and the (?P<live_pins>\w+) item 9 rows\.",
        r"The (?P<live_pins>\w+) item 9 rows sit in both camps",
    ),
    10: (
        r"\| (?P<hashed>\w+) of (?P<total>\w+) checks: `README\.md`",
        r"the (?P<hashed>\w+) item 10 hygiene files",
    ),
}
INVENTORY_NOTE_PATTERNS = {
    9: (r"The (?P<live_pins>\w+) item 9 rows in live_pins",),
    10: (),
}
# registry field -> the key `derive_inventory_counts` returns it under.
INVENTORY_SCALAR_FIELDS = {
    "content_hashed_checks": "hashed",
    "total_checks": "total",
    "also_listed_as_live_pins": "live_pins",
}
# For rebuilding a word-spelled count in a prose control, so no mutant
# carries a literal of its own (#658 review).
NUMBER_WORD = {i: w for w, i in NUMBER_WORDS.items()}


def squash(text):
    """Collapse whitespace runs, so a reflowed sentence still matches."""
    return re.sub(r"\s+", " ", text)


def as_number(token):
    """A count written as digits or as a number word; None if neither."""
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token.lower())


def load_json(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return json.load(f)


def class_matches(path, keys):
    """Which declared class keys claim `path` (a directory prefix, a glob,
    or an exact path). Exactly one is required."""
    hits = []
    for key in keys:
        if key.endswith("/"):
            matched = path.startswith(key)
        elif "*" in key:
            matched = fnmatch.fnmatchcase(path, key)
        else:
            matched = path == key
        if matched:
            hits.append(key)
    return hits


def derive_inventory_counts(reg, entry, files=None):
    """Re-derive one `attested_inventories` entry's numbers from the sources
    of truth, with the structural findings that derivation turns up.

    Returns `(derived, counted, findings)`: the scalars every count
    statement is held to (`hashed`, `total`, `live_pins`, `remainder`, plus
    the entry's prose class groups); the per-class tallies, keyed by the
    entry's own `content_hashed_classes` keys; and findings for a duplicate
    inventory path, an envelope stale against its inventory, a path no
    declared class claims, or a live pin only half-listed.

    Split out of `audit_attested_inventories` so a control can perturb a
    value *relative to the derived one*. A control carrying today's absolute
    counts stops exercising the audit the moment the baseline moves -- and
    fails as though the audit itself had broken, which is exactly what the
    rebase onto #650 produced (#658 review).

    `files` overrides the on-disk JSON for named paths, so a control can
    perturb an inventory or an envelope without touching the tree.
    """
    files = files or {}

    def read(rel):
        return files[rel] if rel in files else load_json(rel)

    findings = []
    item = entry["t1_item"]
    paths = read(entry["inventory"])[entry["inventory_key"]]
    attestation = read(entry["envelope"])["attestation"]
    hashed_paths = [c["path"] for c in attestation["checks"]
                    if "content_hash" in c]

    if len(set(paths)) != len(paths):
        findings.append(f"item {item}: {entry['inventory']} lists "
                        f"{len(paths)} paths but only "
                        f"{len(set(paths))} distinct ones")
    if len(hashed_paths) != len(paths):
        findings.append(
            f"item {item}: {entry['envelope']} content-hashes "
            f"{len(hashed_paths)} files, {entry['inventory']} lists "
            f"{len(paths)} -- the envelope is stale against its inventory")

    # content_hashed_classes: every path in exactly one declared class.
    keys = sorted(entry["content_hashed_classes"])
    counted = dict.fromkeys(keys, 0)
    for path in paths:
        hits = class_matches(path, keys)
        if len(hits) != 1:
            findings.append(
                f"item {item}: {path} matches {len(hits)} of the "
                f"content_hashed_classes keys ({hits or 'none'}); "
                "every inventory path must match exactly one")
            continue
        counted[hits[0]] += 1

    # also_listed_as_live_pins: rows wholly inside this inventory.
    inside, pathset = 0, set(paths)
    for row in live_pins(reg):
        covered = [rel for rel in row["covers"] if rel in pathset]
        if not covered:
            continue
        if len(covered) == len(row["covers"]):
            inside += 1
        else:
            findings.append(
                f"item {item}: live pin {row['pin']} straddles the "
                f"inventory -- {covered} are listed, "
                f"{sorted(set(row['covers']) - pathset)} are not")

    derived = {"hashed": len(paths),
               "total": attestation["check_count"],
               "live_pins": inside}
    derived["remainder"] = derived["hashed"] - derived["live_pins"]
    for group, key in INVENTORY_CLASS_GROUPS[item].items():
        derived[group] = counted[key]
    return derived, counted, findings


def item9_entry(reg):
    """The `attested_inventories` entry the item 9 controls perturb."""
    return next(e for e in reg["attested_inventories"] if e["t1_item"] == 9)


def audit_attested_inventories(reg, doc, files=None):
    """Findings where `attested_inventories` disagrees with the inventories,
    the envelopes, the registry's own live_pins rows, or the prose.

    `files` overrides the on-disk JSON for named paths, so a control can
    perturb an inventory or an envelope without touching the tree.
    """
    findings = []
    for entry in reg["attested_inventories"]:
        item = entry["t1_item"]
        derived, counted, structural = derive_inventory_counts(
            reg, entry, files)
        findings += structural

        for field, key in INVENTORY_SCALAR_FIELDS.items():
            if entry[field] != derived[key]:
                findings.append(f"item {item}: {field} says {entry[field]}, "
                                f"the inventories give {derived[key]}")
        for key in sorted(counted):
            if entry["content_hashed_classes"][key] != counted[key]:
                findings.append(
                    f"item {item}: content_hashed_classes[{key!r}] says "
                    f"{entry['content_hashed_classes'][key]}, the inventory "
                    f"gives {counted[key]}")

        for where, text, patterns in (
                ("md", doc, INVENTORY_DOC_PATTERNS[item]),
                ("attested_inventories_note", reg["attested_inventories_note"],
                 INVENTORY_NOTE_PATTERNS[item])):
            text = squash(text)
            for pat in patterns:
                hits = list(re.finditer(pat, text))
                if len(hits) != 1:
                    findings.append(
                        f"item {item}: {where}: count statement /{pat}/ "
                        f"matched {len(hits)} times, expected exactly 1")
                    continue
                for group, token in hits[0].groupdict().items():
                    if as_number(token) != derived[group]:
                        findings.append(
                            f"item {item}: {where}: {hits[0].group(0)!r} says "
                            f"{group}={token}, the inventories give "
                            f"{derived[group]}")
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


def read_doc():
    with open(os.path.join(REPO, DOC_REL), encoding="utf-8") as f:
        return f.read()


def test_the_prose_counts_and_dispositions_match_the_registry():
    """#326: a renumbering or a missing cost caveat cannot drift silently."""
    assert audit_prose(registry(), read_doc()) == []


def test_the_attested_inventory_counts_match_the_inventories():
    """#649: every `attested_inventories` number is re-derived here.

    Historical, measured at #649's base (290fe05), not a live claim: the
    block there claimed 218/221/45 and 114/59/44/1 for item 9 while the
    inventory held 223 files (118/59/45/1), the envelope 226 checks, and
    the registry 46 item 9 live_pins rows -- and the .md contradicted
    itself, saying both "46" and "45" for the same row count. Nothing
    asserted any of it, so it drifted by one on every PR that added a test
    module. The current numbers live in the registry and the prose only;
    this test and its controls derive theirs.
    """
    assert audit_attested_inventories(registry(), read_doc()) == []


@pytest.mark.parametrize("field", [
    "content_hashed_checks", "total_checks", "also_listed_as_live_pins"])
def test_control_a_perturbed_inventory_count_is_a_finding(field):
    """#649 control 1: a scalar one off the derived value fires, naming it.

    Perturbed against the *derived* count, not against whatever the
    committed registry happens to say, so the control still exercises the
    audit when the baseline is itself stale (#658 review).
    """
    reg = copy.deepcopy(registry())
    entry = item9_entry(reg)
    derived = derive_inventory_counts(reg, entry)[0]
    entry[field] = derived[INVENTORY_SCALAR_FIELDS[field]] + 1
    findings = audit_attested_inventories(reg, read_doc())
    expected = (f"item 9: {field} says {entry[field]}, the inventories give "
                f"{derived[INVENTORY_SCALAR_FIELDS[field]]}")
    assert expected in findings, (expected, findings)


@pytest.mark.parametrize("klass", ["tests/", "rtl/*.sv", "tools/*.py",
                                   "model/integration/negative_controls.py"])
def test_control_a_perturbed_class_count_is_a_finding(klass):
    """#649 control 1, class leg: each class breakdown is derived too.

    Perturbed against the derived tally, for the reason above.
    """
    reg = copy.deepcopy(registry())
    entry = item9_entry(reg)
    counted = derive_inventory_counts(reg, entry)[1]
    entry["content_hashed_classes"][klass] = counted[klass] + 1
    findings = audit_attested_inventories(reg, read_doc())
    expected = (f"item 9: content_hashed_classes[{klass!r}] says "
                f"{counted[klass] + 1}, the inventory gives {counted[klass]}")
    assert expected in findings, (expected, findings)


def _item9_with_scratch_entry():
    """An in-memory item 9 inventory + envelope that gained one test module.

    In memory on purpose: a real `tests/test_zz_scratch.py` would also trip
    `tests/test_t1_item9_inventory_complete.py` (#624) and make the
    committed envelope STALE, so the control would not isolate the counts.
    The envelope is doctored alongside the inventory -- that is the real
    drift this gate closes: a contributor adds a test, re-attests (as the
    registry's own `obligation` field requires), and leaves the counts
    behind.
    """
    entry = item9_entry(registry())
    inv = copy.deepcopy(load_json(entry["inventory"]))
    env = copy.deepcopy(load_json(entry["envelope"]))
    scratch = "tests/test_zz_scratch.py"
    assert scratch not in inv[entry["inventory_key"]]
    inv[entry["inventory_key"]].append(scratch)
    env["attestation"]["checks"].append(
        {"check": "content_hash", "role": "testbench", "path": scratch,
         "content_hash": "0" * 64, "passed": True})
    env["attestation"]["check_count"] += 1
    return {entry["inventory"]: inv, entry["envelope"]: env}


def test_control_a_new_inventory_entry_is_a_finding():
    """#649 control 2: the drift this issue is about, end to end.

    Stated as a relation -- one more file under `tests/`, one more check in
    the envelope, the registry left behind -- rather than as this week's
    absolute counts, so a renumbering re-counts the registry and the prose
    only, never a third copy here (#658 review).
    """
    files = _item9_with_scratch_entry()
    reg = registry()
    entry = item9_entry(reg)
    before, counted_before, _ = derive_inventory_counts(reg, entry)
    after, counted_after, _ = derive_inventory_counts(reg, entry, files)
    assert after["hashed"] == before["hashed"] + 1, (before, after)
    assert after["total"] == before["total"] + 1, (before, after)
    assert counted_after["tests/"] == counted_before["tests/"] + 1

    findings = audit_attested_inventories(reg, read_doc(), files)
    for expected in (
            f"item 9: content_hashed_checks says "
            f"{entry['content_hashed_checks']}, the inventories give "
            f"{after['hashed']}",
            f"item 9: total_checks says {entry['total_checks']}, "
            f"the inventories give {after['total']}",
            f"item 9: content_hashed_classes['tests/'] says "
            f"{entry['content_hashed_classes']['tests/']}, "
            f"the inventory gives {counted_after['tests/']}"):
        assert expected in findings, (expected, findings)

    # Updating the registry's own counts is not enough: the prose restates
    # them, so the .md and the note stay findings until they are updated too.
    reg = copy.deepcopy(registry())
    entry = item9_entry(reg)
    entry["content_hashed_checks"] = after["hashed"]
    entry["total_checks"] = after["total"]
    entry["content_hashed_classes"]["tests/"] = counted_after["tests/"]
    remaining = audit_attested_inventories(reg, read_doc(), files)
    assert remaining, "the prose leg did not survive the registry fix"
    assert all(": md: " in f or ": attested_inventories_note: " in f
               for f in remaining), remaining


@pytest.mark.parametrize("doctor", ["md_digit", "note_digit", "drop_md_row",
                                    "md_word"])
def test_control_a_perturbed_prose_count_is_a_finding(doctor):
    """#649 control 3: the restatements in the .md and the note are gated.

    Each mutant rebuilds its sentence from the derived counts, so a
    renumbering cannot quietly turn a doctor into a no-op (#658 review).
    """
    reg, doc = copy.deepcopy(registry()), read_doc()
    rows = derive_inventory_counts(reg, item9_entry(reg))[0]["live_pins"]
    item10 = next(e for e in reg["attested_inventories"]
                  if e["t1_item"] == 10)
    hygiene = derive_inventory_counts(reg, item10)[0]["hashed"]
    if doctor == "md_digit":
        doc = doc.replace(f"The {rows} item 9 rows sit in both camps",
                          f"The {rows - 1} item 9 rows sit in both camps")
    elif doctor == "note_digit":
        reg["attested_inventories_note"] = \
            reg["attested_inventories_note"].replace(
                f"The {rows} item 9 rows in live_pins",
                f"The {rows - 1} item 9 rows in live_pins")
    elif doctor == "drop_md_row":
        doc = doc.replace(f"The {rows} item 9 rows sit in both camps", "")
    else:
        # The item 10 count is spelled as a word; both forms are resolved.
        doc = doc.replace(f"the {NUMBER_WORD[hygiene]} item 10 hygiene files",
                          f"the {NUMBER_WORD[hygiene - 1]} item 10 "
                          "hygiene files")
    assert doc != read_doc() or reg != registry(), "the mutant did not apply"
    findings = audit_attested_inventories(reg, doc)
    assert findings, f"the {doctor} leg did not fire"


def test_control_an_inventory_path_matching_no_class_is_a_finding():
    """#649 edge case: a path no declared class claims cannot pass."""
    entry = item9_entry(registry())
    inv = copy.deepcopy(load_json(entry["inventory"]))
    inv[entry["inventory_key"]].append("docs/not-a-testbench.md")
    findings = audit_attested_inventories(registry(), read_doc(),
                                          {entry["inventory"]: inv})
    assert any("matches 0 of the content_hashed_classes keys" in f
               for f in findings), findings


def test_control_a_straddling_live_pin_is_a_finding():
    """#649 edge case: a live pin half in an inventory is not countable."""
    reg = copy.deepcopy(registry())
    row = next(e for e in reg["live_pins"]
               if e["leaf"].startswith("T1 item 9"))
    row["covers"] = row["covers"] + ["model/effects/aw-49/galactic_model.py"]
    findings = audit_attested_inventories(reg, read_doc())
    assert any("straddles the inventory" in f for f in findings), findings


@pytest.mark.parametrize("doctor", [
    "md_count_word", "note_count_word", "drop_md_caveat", "drop_json_caveat",
    "drop_count_sentence", "flip_flag"])
def test_control_the_prose_audit_fires_on_a_doctored_copy(doctor):
    """The #326 failure control, on in-memory copies only."""
    reg, doc = copy.deepcopy(registry()), read_doc()
    slfo = next(e for e in reg["historical_provenance"]
                if e["path"] == "fixtures/render_slfo_fixture.py")
    if doctor == "md_count_word":
        mutant = doc.replace("The remaining eight stay", "The remaining seven stay")
        assert mutant != doc, "the mutant did not apply"
        doc = mutant
    elif doctor == "note_count_word":
        note = reg["historical_provenance_note"]
        reg["historical_provenance_note"] = note.replace(
            "eight of these ten", "seven of these ten")
        assert reg["historical_provenance_note"] != note
    elif doctor == "drop_md_caveat":
        row = doc_table_rows(doc)[slfo["path"]]
        doc = doc.replace(row, "cleanable — no finding as of SXT-041 (#75)")
    elif doctor == "drop_json_caveat":
        slfo["lint_finding_disposition"] = \
            "cleanable; no lint finding as of SXT-041 (#75)"
    elif doctor == "drop_count_sentence":
        mutant = re.sub(r"The remaining \w+ stay `false`\.", "", doc)
        assert mutant != doc, "the mutant did not apply"
        doc = mutant
    else:
        # A flag flip moves the derived counts; the unchanged prose must
        # then disagree with them.
        slfo["current_bytes_recorded"] = False
    findings = audit_prose(reg, doc)
    assert findings, f"the {doctor} prose leg did not fire"


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
