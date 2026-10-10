"""SXT-029 (#22) coverage publication: republishability of reports/coverage-v1/.

The apparatus documents itself as deterministic ("same committed inputs =>
byte-identical outputs") and fail-closed ("a stale/missing leaf evidence must
DOWNGRADE affected presets"). Issue #125 recorded the failure mode those two
sentences allow when nobody checks them: three leaf evidence records were
legitimately edited after the last publication, their pins were never revised,
and the *committed* `coverage.json` / `per-preset.csv` kept asserting gates
(including `PASS` fx-gate cells) that their own inputs no longer supported --
for days, invisibly, because nothing re-derived the artifact.

These tests are that missing check. They assert bookkeeping only: nothing here
establishes any leaf's RTL-vs-model or model-vs-reference verdict, and nothing
here is a preset-support, fidelity, or sound claim.
"""
import csv
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import oracle_common as oc  # noqa: E402

COV = os.path.join(REPO, "reports", "coverage-v1")
TABLE = os.path.join(COV, "leaf-verification.json")
TOOL = os.path.join(REPO, "tools", "publish_coverage.py")
LEDGER = os.path.join(COV, "integration-ledger.json")
sys.path.insert(0, os.path.join(REPO, "tools"))

import publish_coverage as pc  # noqa: E402


def load_table():
    with open(TABLE, encoding="utf-8") as f:
        return json.load(f)


def pinned_records(table):
    """(section_key, entry_key, path, sha256) for every pin in the table."""
    out = []
    for section in ("gates", "leaves", "routing_leaves", "airwindows_leaves"):
        for key, entry in (table.get(section) or {}).items():
            if not isinstance(entry, dict):
                continue
            for item in entry.get("evidence") or []:
                out.append((section, key, item["path"], item["sha256"]))
    return out


def publish(outdir, leaf_table=None, integration_ledger=None):
    cmd = [sys.executable, TOOL, "--outdir", outdir]
    if leaf_table is not None:
        cmd += ["--leaf-table", leaf_table]
    if integration_ledger is not None:
        cmd += ["--integration-ledger", integration_ledger]
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)


def read_rows(outdir):
    with open(os.path.join(outdir, "per-preset.csv"), newline="",
              encoding="utf-8") as f:
        return {r["path"]: r for r in csv.DictReader(f)}


# --------------------------------------------------------------- pin integrity

def test_every_evidence_pin_matches_its_file():
    """No pin in the ledger may be STALE against the file it pins.

    The publisher downgrades a stale leaf (correctly), so a drifted pin does
    not fail the tool -- it silently hardens the published gates instead, and
    the committed artifact stops matching its own inputs. Asserting every pin
    here is what makes that drift visible at the moment it is introduced,
    rather than at the next unrelated leaf's PR (the #125 failure mode).
    """
    table = load_table()
    records = pinned_records(table)
    assert records, "no evidence pins found -- table shape changed"
    stale = []
    for section, key, rel, pin in records:
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            stale.append(f"{section}[{key}] {rel}: MISSING")
            continue
        got = oc.sha256_file(path)
        if got != pin:
            stale.append(
                f"{section}[{key}] {rel}: table says {pin}, file hashes {got}")
    assert not stale, (
        "stale evidence pin(s); re-pin to the current file (and record which "
        "edit moved it in leaf-verification.json::evidence_pin_revisions) or "
        "restore the file, then republish reports/coverage-v1/:\n  "
        + "\n  ".join(stale))


def test_pin_revisions_record_is_coherent():
    """Every recorded re-pin must describe the pin the table actually carries."""
    table = load_table()
    revisions = table.get("evidence_pin_revisions", [])
    by_path = {}
    for _section, _key, rel, pin in pinned_records(table):
        by_path.setdefault(rel, set()).add(pin)
    for rev in revisions:
        rel = rev["path"]
        assert rel in by_path, f"re-pin recorded for unpinned path {rel}"
        assert by_path[rel] == {rev["sha256"]}, (
            f"re-pin record for {rel} does not match the table pin(s) "
            f"{sorted(by_path[rel])}")
        assert rev["previous_sha256"] != rev["sha256"], (
            f"re-pin record for {rel} records no movement")
        assert rev["moved_by"].strip(), f"re-pin for {rel} names no edit"
        assert rev["decision"].strip(), f"re-pin for {rel} records no decision"


# ------------------------------------------------------- republishability

def test_committed_artifacts_are_republishable(tmp_path):
    """Re-running the publisher on the committed tree must reproduce the
    committed coverage.json and per-preset.csv byte-for-byte."""
    outdir = str(tmp_path / "out")
    r = publish(outdir)
    assert r.returncode == 0, f"publisher refused: {r.stderr}"
    for name in ("coverage.json", "per-preset.csv"):
        fresh = os.path.join(outdir, name)
        committed = os.path.join(COV, name)
        assert oc.sha256_file(fresh) == oc.sha256_file(committed), (
            f"reports/coverage-v1/{name} is not reproducible from the "
            "committed inputs; re-run `python3 tools/publish_coverage.py` and "
            "commit the result (no --control-allow-input-drift, no "
            "--leaf-table override)")


def test_published_artifact_claims_no_unearned_support():
    """The published ledger may never report a supported preset while the
    fidelity-freeze gate is unmet -- coverage is not a fidelity claim."""
    with open(os.path.join(COV, "coverage.json"), encoding="utf-8") as f:
        cov = json.load(f)
    gate = cov["leaf_ledger"]["gates"]["fidelity_freeze"]
    if gate["status"] != "PASS" or gate["evidence_state"] != "OK":
        assert cov["totals"]["supported"] == 0, (
            "supported > 0 with the fidelity-freeze gate unmet/stale")
    rows = read_rows(COV)
    assert len(rows) == 3561, f"corpus row count moved: {len(rows)}"
    for path, row in rows.items():
        if row["headline_status"] == "supported":
            assert row["fidelity_contract_gate"] == "PASS", path
            for col in ("voice_leaf_gate", "fx_leaves_gate",
                        "wavetable_leaf_gate", "routing_leaves_gate"):
                assert row[col] in ("", "PASS"), (path, col, row[col])
            # #384: leaf agreement is not complete-preset qualification
            assert row["integration_gate"] == "PASS", path
            assert row["integration_record"], path
    # no committed integration record is PASS, so nothing can be supported
    assert cov["integration_gate"]["rows_pass"] == 0
    assert cov["totals"]["supported"] == 0
    assert cov["denominators"]["corpus_total"] == 3561
    assert cov["denominators"]["per_bank"] == {"contributor": 2920,
                                               "factory": 641}


# ------------------------------------------- integration ledger (#384)

def test_integration_ledger_is_pinned_and_honest():
    """The committed integration ledger is a pinned structural input, every
    record's pins re-hash, every record names its own preset's graph and
    placement/order identity, and no record is synthetic."""
    assert pc.STRUCTURAL_INPUTS[pc.INTEGRATION_LEDGER_DEFAULT] == \
        oc.sha256_file(LEDGER)
    with open(LEDGER, encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["schema_version"] == pc.INTEGRATION_SCHEMA
    assert doc["required_aspects"] == pc.INTEGRATION_ASPECTS
    graphs = {}
    with open(os.path.join(REPO, pc.GRAPH_DEFAULT), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                graphs[e["p"]] = e
    stale = []
    for rec in doc["records"]:
        assert not rec.get("synthetic"), rec["record_id"]
        e = graphs[rec["path"]]
        assert (rec["bank"], rec["blob_sha1"]) == (e["b"], e["sha"])
        assert rec["normalized_graph_sha256"] == pc.graph_sha256(e["g"])
        assert rec["fx_placement_order"] == pc.fx_placement_order(e["g"])
        pins = [rec[k] for k in pc.INTEGRATION_PINNED_FIELDS] + rec["evidence"]
        if rec["fidelity_policy"] is not None:
            pins.append(rec["fidelity_policy"])
        for item in pins:
            path = os.path.join(REPO, item["path"])
            if not os.path.exists(path) or oc.sha256_file(path) != item["sha256"]:
                stale.append(f"{rec['record_id']}: {item['path']}")
        # while #12 is open no record can name a frozen policy
        assert rec["fidelity_policy"] is None, rec["record_id"]
        if rec["qualification_scope"] == "adapted":
            assert rec["adaptation"].strip()
    assert not stale, "stale integration pin(s):\n  " + "\n  ".join(stale)


def test_adapted_integration_cannot_authorize_original_support():
    """The historical SXT-025 dry-bus run is recorded as ADAPTED; it is
    visible on the row but never qualifies the original preset."""
    rows = read_rows(COV)
    hb = rows["resources/data/patches_3rdparty/Rozzer/Bells/Hell's Bells.fxp"]
    assert hb["headline_status"] != "supported"
    assert hb["integration_gate"] != "PASS"
    assert hb["integration_record"] == "sxt-026a-hells-bells-original-voice"
    assert ("integration_adapted_only:sxt-025-hells-bells-drybus-adapted"
            in hb["reasons"])
    assert "integration_rtl_vs_model_NOT_RUN:" in hb["reasons"]


def test_integration_gate_is_load_bearing_and_fails_closed(tmp_path):
    """Failure controls (#384), against a declared synthetic world in which
    every component gate and the freeze gate PASS: without a matching
    integration PASS record nothing is supported; with one per preset the
    set is restored; each single-record mutation of one victim removes
    exactly that preset with the expected gate value and named reason."""
    import coverage_negative_controls as ncc
    cf = ncc.counterfactual_table(tmp_path / "cf" / "counterfactual.json")
    synth = ncc.ledger_for(cf)
    ledger = json.loads(synth.read_text(encoding="utf-8"))

    base = str(tmp_path / "base")
    assert publish(base, str(cf), str(synth)).returncode == 0
    b = read_rows(base)
    s0 = {p for p, r in b.items() if r["headline_status"] == "supported"}
    assert s0

    none = str(tmp_path / "none")
    assert publish(none, str(cf)).returncode == 0
    n = read_rows(none)
    assert not {p for p, r in n.items() if r["headline_status"] == "supported"}
    for p in s0:
        assert n[p]["integration_gate"] in ("NOT_RUN", "NO_VERDICT"), p
        assert n[p]["fidelity_contract_gate"] == "PASS", p

    by0 = {p: {"blob_sha1": r["blob_sha1"]} for p, r in b.items()}
    v, w = ncc._victims(by0, s0, ledger)
    idx = {rec["path"]: i for i, rec in enumerate(ledger["records"])}
    for name, mutate, want, reason in ncc._mutations(
            ledger["records"][idx[v]], ledger["records"][idx[w]]):
        doc = json.loads(json.dumps(ledger))
        if mutate(doc["records"][idx[v]]) is None:
            del doc["records"][idx[v]]
        led = tmp_path / f"ledger-{name}.json"
        led.write_text(json.dumps(doc), encoding="utf-8")
        out = str(tmp_path / f"out-{name}")
        r = publish(out, str(cf), str(led))
        assert r.returncode == 0, (name, r.stderr)
        rows = read_rows(out)
        s1 = {p for p, x in rows.items() if x["headline_status"] == "supported"}
        assert s1 == s0 - {v}, name
        assert rows[v]["integration_gate"] == want, (name, rows[v]["integration_gate"])
        assert reason in rows[v]["reasons"], name


# ------------------------------------------------------------ failure control

def test_stale_pin_downgrades_affected_presets(tmp_path):
    """Failure control: corrupting one pin must downgrade the presets that
    depend on it to STALE in the *published artifact*, never leave them PASS.

    This is the negative control the apparatus documents, asserted against the
    real committed table (the counterfactual-world version lives in
    tools/coverage_negative_controls.py).
    """
    good_out = str(tmp_path / "good")
    assert publish(good_out).returncode == 0
    good = read_rows(good_out)
    baseline_pass = {p for p, r in good.items() if r["fx_leaves_gate"] == "PASS"}
    assert baseline_pass, (
        "no preset holds fx_leaves_gate PASS, so this control cannot observe a "
        "downgrade -- the control is not live and must be re-targeted")

    table = load_table()
    ev = table["leaves"]["fx:EQ"]["evidence"]
    assert len(ev) == 1
    tampered_path = tmp_path / "leaf-verification-tampered.json"
    ev[0]["sha256"] = "0" * 64
    tampered_path.write_text(json.dumps(table, indent=2, sort_keys=True),
                             encoding="utf-8")

    bad_out = str(tmp_path / "bad")
    r = publish(bad_out, leaf_table=str(tampered_path))
    assert r.returncode == 0, f"publisher refused: {r.stderr}"
    bad = read_rows(bad_out)

    # Only rows whose fx gate was actually reached can be downgraded: a row
    # whose structural status precedes the leaf gates carries an empty cell,
    # which is never a pass and needs no downgrade.
    affected = {p for p in good
                if "EQ" in (good[p]["fx_required"] or "").split(";")
                and good[p]["fx_leaves_gate"] != ""}
    assert affected, "no preset requires EQ -- control cannot be evaluated"
    downgraded = [p for p in affected if bad[p]["fx_leaves_gate"] == "STALE"]
    assert len(downgraded) == len(affected), (
        f"only {len(downgraded)}/{len(affected)} EQ presets downgraded")
    for p in affected:
        assert bad[p]["fx_leaves_gate"] != "PASS", p
        assert "stale_leaf:" in bad[p]["reasons"], p
    assert baseline_pass & affected, (
        "the corrupted pin covers no preset that previously held PASS -- "
        "the control would not detect a kept-PASS regression")
    with open(os.path.join(bad_out, "coverage.json"), encoding="utf-8") as f:
        bad_cov = json.load(f)
    assert bad_cov["leaf_ledger"]["leaves"]["fx:EQ"]["evidence_state"] == "STALE"
    assert bad_cov["totals"]["supported"] == 0


# ------------------------------------- evidence-backed readiness (#432)

def _eq_rows_pass(rows):
    return {p for p, r in rows.items()
            if "EQ" in (r["fx_required"] or "").split(";")
            and r["fx_leaves_gate"] == "PASS"}


@pytest.mark.parametrize("mode", ["absent", "null", "empty"])
def test_ready_leaf_without_evidence_is_never_pass(tmp_path, mode):
    """Removing / nulling / emptying the evidence of a landed PASS/PASS leaf
    must not leave any reached gate PASS (it used to: the empty-list shortcut
    in evidence_state returned OK)."""
    good = str(tmp_path / "good")
    assert publish(good).returncode == 0
    baseline = _eq_rows_pass(read_rows(good))
    assert baseline, "no reached EQ PASS gate -- control not live"
    table = load_table()
    if mode == "absent":
        del table["leaves"]["fx:EQ"]["evidence"]
    elif mode == "null":
        table["leaves"]["fx:EQ"]["evidence"] = None
    else:
        table["leaves"]["fx:EQ"]["evidence"] = []
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps(table), encoding="utf-8")
    out = str(tmp_path / "out")
    r = publish(out, leaf_table=str(tp))
    assert r.returncode == 0, r.stderr
    rows = read_rows(out)
    for p in baseline:
        assert rows[p]["fx_leaves_gate"] == "NO_VERDICT", p
        assert "leaf_evidence_missing:fx:EQ" in rows[p]["reasons"], p
        assert rows[p]["headline_status"] != "supported", p
    with open(os.path.join(out, "coverage.json"), encoding="utf-8") as f:
        cov = json.load(f)
    assert cov["leaf_ledger"]["leaves"]["fx:EQ"]["evidence_state"] == "MISSING"


@pytest.mark.parametrize("bad", ["oops", [{"path": 1}],
                                 [{"path": "x", "sha256": "ab"}]])
def test_malformed_evidence_refuses_before_output(tmp_path, bad):
    table = load_table()
    table["leaves"]["fx:EQ"]["evidence"] = bad
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps(table), encoding="utf-8")
    out = tmp_path / "out"
    r = publish(str(out), leaf_table=str(tp))
    assert r.returncode == 2, r.stderr
    assert not (out / "coverage.json").exists()
    assert not (out / "per-preset.csv").exists()


def _first_key(table, section):
    return next(iter(table[section]))


@pytest.mark.parametrize("section", ["routing_leaves", "airwindows_leaves"])
@pytest.mark.parametrize("bad", ["oops", {}, [{"path": "x", "sha256": "z" * 64}]])
def test_canonical_mapping_still_validates_section_evidence(tmp_path, section, bad):
    """A canonical_leaf supplies readiness but must not bypass the entry's own
    evidence shape check: malformed evidence REFUSEs (exit 2), no output."""
    table = load_table()
    key = _first_key(table, section)
    table[section][key]["canonical_leaf"] = "fx:EQ"
    table[section][key]["evidence"] = bad
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps(table), encoding="utf-8")
    out = tmp_path / "out"
    r = publish(str(out), leaf_table=str(tp))
    assert r.returncode == 2, r.stderr
    assert "Traceback" not in r.stderr
    assert not (out / "coverage.json").exists()
    assert not (out / "per-preset.csv").exists()


def test_non_hex_sha256_pin_refuses_but_wellformed_mismatch_is_stale(tmp_path):
    table = load_table()
    pin = table["leaves"]["fx:EQ"]["evidence"][0]
    pin["sha256"] = "z" * 64
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps(table), encoding="utf-8")
    out = tmp_path / "out"
    r = publish(str(out), leaf_table=str(tp))
    assert r.returncode == 2, r.stderr
    assert not (out / "coverage.json").exists()
    # Control: a well-formed but wrong digest still publishes, as STALE.
    pin["sha256"] = "0" * 64
    tp.write_text(json.dumps(table), encoding="utf-8")
    out2 = str(tmp_path / "out2")
    assert publish(out2, leaf_table=str(tp)).returncode == 0
    with open(os.path.join(out2, "coverage.json"), encoding="utf-8") as f:
        cov = json.load(f)
    assert cov["leaf_ledger"]["leaves"]["fx:EQ"]["evidence_state"] == "STALE"


def test_unlanded_placeholders_stay_non_pass_with_empty_evidence():
    """Empty evidence is legitimate on an unlanded placeholder and must stay
    so: the committed entries carry no pins and none authorizes PASS."""
    table = load_table()
    for section in ("routing_leaves", "airwindows_leaves"):
        for key, lf in table[section].items():
            if not lf.get("landed"):
                assert not lf.get("evidence"), (section, key)
    rows = read_rows(COV)
    assert not any(r["headline_status"] == "supported" for r in rows.values())


def test_pass_gate_without_evidence_is_not_pass(tmp_path):
    table = load_table()
    table["gates"]["fidelity_freeze"]["status"] = "PASS"
    table["gates"]["fidelity_freeze"]["evidence"] = []
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps(table), encoding="utf-8")
    out = str(tmp_path / "out")
    assert publish(out, leaf_table=str(tp)).returncode == 0
    rows = read_rows(out)
    gated = [r for r in rows.values() if r["fidelity_contract_gate"]]
    assert gated
    for r in gated:
        assert r["fidelity_contract_gate"] == "NO_VERDICT"
        assert "gate_evidence_missing:fidelity_freeze" in r["reasons"]
        assert r["headline_status"] != "supported"


def test_unknown_canonical_leaf_refuses(tmp_path):
    table = load_table()
    table["routing_leaves"]["ains3"]["canonical_leaf"] = "no-such-leaf"
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps(table), encoding="utf-8")
    r = publish(str(tmp_path / "out"), leaf_table=str(tp))
    assert r.returncode == 2 and "canonical_leaf" in r.stderr


def _ncc_scratch(monkeypatch, tmp_path):
    import coverage_negative_controls as ncc
    monkeypatch.setattr(ncc, "NC_ROOT", tmp_path / "nc")
    return ncc


def test_live_control_empty_list_shortcut_fails_targeted_assertion(
        monkeypatch, tmp_path):
    """The real publisher passes the ordinary-leaf scenario; a temporary copy
    restoring the empty-list shortcut fails its TARGETED assertion."""
    ncc = _ncc_scratch(monkeypatch, tmp_path)
    ncc.scenario_ordinary(tmp_path / "real", ncc.TOOL, [])
    mut = ncc._mutant_tool("empty", "if require and not pins:", "if False:")
    with pytest.raises(AssertionError, match=ncc.TARGETED):
        ncc.scenario_ordinary(tmp_path / "mut", mut, [])


def test_live_control_stale_false_fallback_fails_targeted_assertion(
        monkeypatch, tmp_path):
    ncc = _ncc_scratch(monkeypatch, tmp_path)
    old = "    return build_leaf_state(repo, lf, owner)\n"
    mut = ncc._mutant_tool(
        "fallback", old,
        f'    if section == "routing_leaves":\n        {ncc.FALLBACK}\n' + old)
    with pytest.raises(AssertionError, match=ncc.TARGETED):
        ncc.scenario_section(tmp_path / "mut", mut, "routing_leaves", "local", [])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
