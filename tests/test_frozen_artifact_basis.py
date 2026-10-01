#!/usr/bin/env python3
"""#246 -- committed artifacts frozen at a SUPERSEDED basis, on purpose.

What this pins, and what it does NOT:

  * PINS: `docs/frozen-artifact-basis.json` lists every committed artifact
    that records a superseded accounting / input basis deliberately, the
    exact value it is frozen at, the leaf EVIDENCE that declares the freeze,
    and what retires it. Three assertions carry the weight:

      1. each frozen artifact still records exactly its declared value --
         so an artifact that silently drifts off its declared basis (a
         re-emission landed without a recorded decision) FAILS;
      2. each named live basis, re-derived here from the live model and the
         live committed scan, still equals the value the registry says the
         freezes are superseded BY -- so mutating the live `params_digest`
         (or any further basis move) FAILS, forcing a fresh per-artifact
         decision instead of silent accumulation;
      3. no OTHER machine record carries a frozen value without being
         registered -- so a newly-generated artifact cannot quietly inherit
         a retired basis.

  * DOES NOT: establish RTL exactness, model-vs-reference agreement, cycle,
    area, technology, preset-support or preset-quality anything. This is
    evidence bookkeeping: it says which basis a committed record quotes,
    never that the record's verdict is right. Supported-preset delta: 0.

Why it exists: #239 (PR #249) moved the SXT-015 accounting basis
(`sxt-015-accounting/1.0.0` -> `1.1.0`, `params_digest` `646942e9c3887ecb`
-> `a639d3115ae1a0ca`) and re-exported the artifacts that a test holds
current. Six committed artifacts were deliberately NOT regenerated and were
recorded as STALE in `reports/sxt-015/EVIDENCE.md` section 8.5. Every one of
them is self-verifying (checked against its own recorded digests, never
against the live model), so nothing in CI could tell a deliberate freeze
from silent rot. This file is that missing distinction.

A freeze is NOT a currency pin, and the two must not be conflated: a frozen
artifact legitimately names a retired basis and a live-equality assertion on
it would be wrong. What IS asserted live is the basis the freeze is declared
against -- which is what makes the next basis move fail closed.

Original to this repository (Apache-2.0 per `LICENSE`).
"""

import functools
import hashlib
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_REL = os.path.join("docs", "frozen-artifact-basis.json")
DOC_REL = os.path.join("docs", "frozen-artifact-basis.md")
SCAN_REL = os.path.join("reports", "sxt-020", "compile-corpus-scan.json")

if REPO not in sys.path:
    sys.path.insert(0, REPO)


# ------------------------------------------------------------------ helpers
@functools.lru_cache(maxsize=1)
def registry():
    with open(os.path.join(REPO, REGISTRY_REL), encoding="utf-8") as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def tracked_files():
    out = subprocess.run(["git", "-C", REPO, "ls-files", "-z"],
                         capture_output=True, text=True, check=True).stdout
    return tuple(p for p in out.split("\0") if p)


def frozen_entries():
    return tuple(registry()["frozen"])


def resolve(doc, json_path):
    """Resolve a dotted path inside a parsed JSON document.

    Returns the sentinel `KeyError` instance rather than raising so a
    missing path is reported as a drift (the field the freeze names is gone)
    instead of an error that reads like a broken test.
    """
    cur = doc
    for part in json_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, "missing"
        cur = cur[part]
    return cur, "present"


def live_sxt015_accounting():
    from model.resources.accounting import MODEL_VERSION, params_digest
    return {"accounting_model_version": MODEL_VERSION,
            "params_digest": params_digest()}


def live_sxt020_compile_scan():
    with open(os.path.join(REPO, SCAN_REL), "rb") as f:
        return {"compile_scan": hashlib.sha256(f.read()).hexdigest()}


# Every basis the registry may name must have a live re-derivation here. A
# basis without one would be an unchecked value, which is the failure mode
# this file exists to close.
LIVE_BASES = {
    "sxt-015-accounting": live_sxt015_accounting,
    "sxt-020-compile-scan": live_sxt020_compile_scan,
}


# ------------------------------------------------------------ registry shape
def test_registry_shape_is_well_formed():
    reg = registry()
    for key in ("artifact", "audit", "bases", "claim", "doc", "frozen",
                "issue", "machine_record_suffixes", "narrative_records",
                "retires_stale_record"):
        assert key in reg, f"registry is missing required key {key!r}"
    assert reg["audit"] == "tests/test_frozen_artifact_basis.py"
    assert reg["doc"] == DOC_REL.replace(os.sep, "/")
    assert os.path.isfile(os.path.join(REPO, DOC_REL)), \
        "the registry names a human-readable doc that does not exist"
    assert frozen_entries(), "registry lists no frozen artifacts"

    tracked = set(tracked_files())
    seen = set()
    for e in frozen_entries():
        where = e.get("path", "<no path>")
        assert e["path"] in tracked, f"{where}: not a tracked file"
        assert (e["path"], e["leaf"]) not in seen, f"{where}: duplicate entry"
        seen.add((e["path"], e["leaf"]))
        assert e["declared_in"] in tracked, \
            f"{where}: declared_in {e['declared_in']} is not a tracked file"
        assert e["why"].strip(), f"{where}: records no reason for the freeze"
        assert e["retired_by"].strip(), \
            f"{where}: names nothing that retires the freeze"
        assert e["frozen_values"], f"{where}: freezes no value"
        for fv in e["frozen_values"]:
            assert fv["basis"] in reg["bases"], \
                f"{where}: unknown basis {fv['basis']!r}"
            assert fv["field"] in reg["bases"][fv["basis"]]["live_values"], \
                (f"{where}: field {fv['field']!r} has no live value under "
                 f"basis {fv['basis']!r}")
            assert fv["json_path"] and fv["value"]

    for basis_id, basis in reg["bases"].items():
        assert basis_id in LIVE_BASES, (
            f"basis {basis_id!r} has no live re-derivation in this audit; "
            "an unchecked basis value is exactly the gap #246 closed")
        assert set(basis["live_values"]) == set(LIVE_BASES[basis_id]()), (
            f"basis {basis_id!r}: registry fields "
            f"{sorted(basis['live_values'])} != re-derived fields "
            f"{sorted(LIVE_BASES[basis_id]())}")
        assert basis["live_moved_by"].strip() and basis["what"].strip()
        assert basis["live_source"].strip()


# -------------------------------------- 1. the artifacts have not drifted
@pytest.mark.parametrize("entry", frozen_entries(),
                         ids=[e["path"] for e in frozen_entries()])
def test_frozen_artifact_still_records_its_declared_basis(entry):
    """A frozen artifact must still record EXACTLY its declared value.

    This is the assertion a silent re-emission trips: regenerating one of
    these artifacts without recording the decision moves the value here and
    fails, rather than quietly replacing a declared freeze with an
    undeclared one.
    """
    with open(os.path.join(REPO, entry["path"]), encoding="utf-8") as f:
        doc = json.load(f)
    drift = []
    for fv in entry["frozen_values"]:
        got, state = resolve(doc, fv["json_path"])
        if state == "missing":
            drift.append(f"{fv['json_path']}: FIELD MISSING (declared "
                         f"frozen at {fv['value']})")
        elif got != fv["value"]:
            drift.append(f"{fv['json_path']}: declared frozen at "
                         f"{fv['value']}, file records {got}")
    assert not drift, (
        f"{entry['path']} has moved off its declared frozen basis:\n  "
        + "\n  ".join(drift)
        + "\n\nIf the move was deliberate, update docs/frozen-artifact-basis"
          ".json AND the declaration in " + entry["declared_in"]
        + " in the same change (and re-pin every digest that record carries "
          "for this artifact). If it was not, restore the committed file.")


# ------------------- 2. the live basis the freezes are declared against
@pytest.mark.parametrize("basis_id", sorted(LIVE_BASES))
def test_live_basis_still_equals_the_value_the_freezes_cite(basis_id):
    """The failure control: a further basis move must FAIL, not accumulate.

    A freeze is declared *relative to* a named live basis ("frozen at
    1.0.0 / 646942e9c3887ecb, superseded by 1.1.0 / a639d3115ae1a0ca"). If
    the live basis moves again -- e.g. `params_digest` changes because the
    parameter registry moved -- every declaration's "superseded by" clause
    stops describing reality and each artifact needs a fresh decision. So
    the live value is re-derived here and compared against the registry:
    mutating the live `params_digest` fails this test for every basis field
    the frozen artifacts cite.
    """
    recorded = registry()["bases"][basis_id]["live_values"]
    live = LIVE_BASES[basis_id]()
    moved = {k: (recorded[k], live[k]) for k in recorded
             if recorded[k] != live.get(k)}
    assert not moved, (
        f"live basis {basis_id!r} has moved past the value the freezes in "
        "docs/frozen-artifact-basis.json are declared against: "
        + "; ".join(f"{k}: registry {a} -> live {b}"
                    for k, (a, b) in sorted(moved.items()))
        + ". Every frozen entry citing this basis needs a fresh decision "
          "(re-emit, or re-declare the freeze against the new basis) before "
          "the registry is updated."
    )


def test_a_freeze_is_never_silently_a_currency_pin():
    """A frozen value must differ from the live one -- else retire the entry.

    If a frozen value ever equals the live value, the artifact is no longer
    frozen at a superseded basis and the registry would be describing a
    freeze that does not exist. Fail closed and force the entry's removal.
    """
    reg = registry()
    not_frozen = []
    for e in frozen_entries():
        for fv in e["frozen_values"]:
            live = reg["bases"][fv["basis"]]["live_values"][fv["field"]]
            if live == fv["value"]:
                not_frozen.append(
                    f"{e['path']}::{fv['json_path']} = {fv['value']} is the "
                    f"LIVE {fv['basis']}/{fv['field']} value")
    assert not not_frozen, (
        "registry entries that are current, not frozen -- retire them:\n  "
        + "\n  ".join(not_frozen))


# -------------------------------- 3. the freeze is declared where it counts
@pytest.mark.parametrize("entry", frozen_entries(),
                         ids=[e["path"] for e in frozen_entries()])
def test_each_freeze_is_declared_in_its_leaf_evidence(entry):
    """The owning leaf's EVIDENCE must say so, in its own words.

    The registry is bookkeeping; the leaf report is where a reader of that
    leaf's verdict finds out that one of its artifacts quotes a retired
    basis on purpose. A registry entry whose EVIDENCE does not name the
    artifact and the frozen value is not a declaration.
    """
    with open(os.path.join(REPO, entry["declared_in"]), encoding="utf-8") as f:
        text = f.read()
    missing = []
    if os.path.basename(entry["path"]) not in text:
        missing.append(f"does not name the artifact {entry['path']}")
    for fv in entry["frozen_values"]:
        if fv["value"] not in text:
            missing.append(f"does not name the frozen value {fv['value']}")
    if REGISTRY_REL.replace(os.sep, "/") not in text:
        missing.append("does not point at " + REGISTRY_REL.replace(os.sep, "/"))
    assert not missing, (
        f"{entry['declared_in']} is named as the declaration for "
        f"{entry['path']} but it " + "; it ".join(missing))


# ------------------------------------- 4. nothing drifts in unregistered
def test_no_unregistered_machine_record_carries_a_frozen_value():
    """A frozen value may appear ONLY in a registered artifact.

    This is what keeps the next generated artifact from quietly inheriting a
    retired basis the way these six did: the moment a new machine record
    quotes one of these values, it is either registered with a decision or
    this test fails. Prose records are excluded by construction (see
    `narrative_records_note` in the registry) -- a narrative may legitimately
    quote a retired basis.
    """
    reg = registry()
    suffixes = tuple(reg["machine_record_suffixes"])
    allowed_anywhere = set(reg["narrative_records"])
    by_value = {}
    for e in frozen_entries():
        for fv in e["frozen_values"]:
            by_value.setdefault(fv["value"], set()).add(e["path"])

    offenders = []
    for rel in tracked_files():
        if not rel.endswith(suffixes) or rel in allowed_anywhere:
            continue
        with open(os.path.join(REPO, rel), encoding="utf-8",
                  errors="replace") as f:
            body = f.read()
        for value, owners in by_value.items():
            if value in body and rel not in owners:
                offenders.append(f"{rel} quotes frozen value {value} "
                                 f"(registered for: {sorted(owners)})")
    assert not offenders, (
        "unregistered machine record(s) carrying a superseded basis -- "
        "register them with a decision in docs/frozen-artifact-basis.json "
        "or regenerate them against the live basis:\n  "
        + "\n  ".join(sorted(offenders)))


def test_the_sxt015_stale_record_points_at_this_registry():
    """The STALE record this issue retires must route a reader here.

    `reports/sxt-015/EVIDENCE.md` section 8.5 is where the six artifacts were
    first recorded as STALE. If it still reads as an open STALE finding with
    no disposition, the freeze is invisible from the place that raised it.
    """
    rel = registry()["retires_stale_record"].split(" ")[0]
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        text = f.read()
    assert REGISTRY_REL.replace(os.sep, "/") in text, (
        f"{rel} does not point at {REGISTRY_REL}; the STALE record it "
        "carries would read as undispositioned")
    for e in frozen_entries():
        assert os.path.basename(e["path"]) in text, (
            f"{rel} does not name {e['path']}, which the registry says it "
            "recorded as STALE")
