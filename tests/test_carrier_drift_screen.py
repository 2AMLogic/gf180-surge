#!/usr/bin/env python3
"""#423 -- tests for tools/carrier_drift_screen.py.

SCOPE: these use INJECTED loaders and synthetic corpus files in tmp dirs. They
validate the helper's refusal/coverage/gate-selection logic only. They are NOT
live oracle evidence, establish no drift value of any real preset, and a
mocked run can never be written as a record (`write_record` refuses it).
Live screening against the pinned oracle is NOT_RUN here.
"""

import csv
import hashlib
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import carrier_drift_screen as cds  # noqa: E402
import extract_rf_send34_inputs as ex  # noqa: E402

SHA = {n: hashlib.sha1(n.encode()).hexdigest() for n in "abcdefg"}


def graph(name, shape=True, smn="Dual"):
    return {"p": f"p/{name}.fxp", "sha": SHA[name], "b": "t",
            "g": {"smn": smn, "shape": shape}}


def predicate(g):
    return bool(g["g"].get("shape"))


class FakeSession:
    def __init__(self, vals):
        self.vals = vals

    def getParamVal(self, key):
        return self.vals[key]


def fake_patch():
    return {"scenemode": "mode", "scene_active": "act",
            "scene": [{"drift": "dA"}, {"drift": "dB"}]}


class FakeLoader:
    is_live = False

    def __init__(self, table, absent=False):
        self.table, self.absent, self.loaded = table, absent, []

    def open(self):
        if self.absent:
            raise cds.OracleAbsent("no oracle")
        return {"pin": cds.ENGINE_PIN}

    def load(self, rel, sha):
        self.loaded.append(rel)
        v = self.table[rel]
        if isinstance(v, cds.LoadRefusal):
            raise v
        return FakeSession(v), fake_patch(), sha


def vals(mode=1, active=0, a=0.0, b=0.0, native_shape=True):
    return {"mode": mode, "act": active, "dA": a, "dB": b,
            "_shape": native_shape}


def native_shape_check(s, patch, cand):
    return None if s.vals["_shape"] else "native state lacks the shape"


def bypassed_shape_check(s, patch, cand):
    return None


@pytest.fixture
def corpus(tmp_path):
    def build(graphs, census_over=None, manifest_commit=cds.ENGINE_PIN):
        gp = tmp_path / "graphs.jsonl"
        gp.write_text("".join(json.dumps(g) + "\n" for g in graphs))
        rows = {}
        for g in graphs:
            rows[g["p"]] = {"path": g["p"], "git_blob_sha1": g["sha"],
                            "content_verified": "True"}
        for p, over in (census_over or {}).items():
            if over is None:
                rows.pop(p)
            else:
                rows[p].update(over)
        cp = tmp_path / "census.csv"
        with open(cp, "w", newline="") as f:
            w = csv.DictWriter(f, ["path", "git_blob_sha1", "content_verified"])
            w.writeheader()
            w.writerows(rows.values())
        mp = tmp_path / "manifest.json"
        mp.write_text(json.dumps({"engine": {"commit": manifest_commit}}))
        return dict(graphs_path=str(gp), census_csv=str(cp),
                    manifest_path=str(mp))
    return build


def run(corpus_kw, loader, shape_check=native_shape_check, **kw):
    return cds.run_screen("test-shape-v1", predicate, shape_check, loader,
                          **corpus_kw, **kw)


def by_path(doc):
    return {r["path"]: r for r in doc["candidates"]}


def test_exact_shape_selection_and_denominator_order(corpus):
    kw = corpus([graph("a"), graph("b", shape=False), graph("c"),
                 graph("d")])
    cands = cds.enumerate_candidates(predicate, kw["graphs_path"])
    assert [c["path"] for c in cands] == ["p/a.fxp", "p/c.fxp", "p/d.fxp"]
    ld = FakeLoader({f"p/{n}.fxp": vals() for n in "acd"})
    doc = run(kw, ld, expected_count=3)
    assert doc["status"] == "PASS"
    assert doc["shape_predicate_id"] == "test-shape-v1"
    assert [c["path"] for c in doc["candidate_manifest"]] == [
        "p/a.fxp", "p/c.fxp", "p/d.fxp"]
    assert "p/b.fxp" not in ld.loaded
    assert doc["coverage"]["candidates_screened"] == 3
    # deterministic output
    again = run(kw, FakeLoader({f"p/{n}.fxp": vals() for n in "acd"}))
    assert again["candidate_manifest_sha256"] == doc[
        "candidate_manifest_sha256"]
    assert [r["path"] for r in again["candidates"]] == [
        r["path"] for r in doc["candidates"]]


def test_denominator_mismatch_blocks_before_native_load(corpus):
    kw = corpus([graph("a"), graph("c")])
    ld = FakeLoader({})
    doc = run(kw, ld, expected_count=3)
    assert doc["status"] == "BLOCKED" and ld.loaded == []
    assert "candidates" not in doc


def test_input_digests_recorded(corpus):
    doc = run(corpus([graph("a")]), FakeLoader({"p/a.fxp": vals()}))
    d = doc["input_digests"]
    assert len(d["graphs_jsonl"]["sha256"]) == 64
    assert len(d["census_per_preset_csv"]["sha256"]) == 64


@pytest.mark.parametrize("over,code", [
    ({"git_blob_sha1": "f" * 40}, cds.R_HASH_MISMATCH),
    ({"git_blob_sha1": "nothex"}, cds.R_BAD_HASH),
    ({"git_blob_sha1": ""}, cds.R_BAD_HASH),
    ({"content_verified": "False"}, cds.R_NOT_VERIFIED),
    (None, cds.R_NO_CENSUS_ROW),
])
def test_provenance_refusal_precedes_native_load_without_drift(
        corpus, over, code):
    kw = corpus([graph("a"), graph("c")], census_over={"p/a.fxp": over})
    ld = FakeLoader({"p/a.fxp": vals(), "p/c.fxp": vals()})
    doc = run(kw, ld)
    r = by_path(doc)["p/a.fxp"]
    assert r["refusal"]["code"] == code
    assert r["determinism_gate"] is None and not r["attempted"]
    assert "p/a.fxp" not in ld.loaded
    assert doc["status"] == "NO_VERDICT"
    assert doc["coverage"]["candidates_in_corpus"] == 2
    assert doc["coverage"]["candidates_attempted"] == 1
    with pytest.raises(AssertionError):
        cds.assert_drift_gate_passed(r)


def test_pinned_blob_mismatch_and_load_failure_stay_in_denominator(corpus):
    kw = corpus([graph("a"), graph("c"), graph("d")])
    ld = FakeLoader({
        "p/a.fxp": cds.LoadRefusal(cds.R_BLOB_MISMATCH, "blob differs"),
        "p/c.fxp": cds.LoadRefusal(cds.R_LOAD_FAILED, "loadPatch failed"),
        "p/d.fxp": vals()})
    doc = run(kw, ld)
    recs = by_path(doc)
    assert recs["p/a.fxp"]["refusal"]["code"] == cds.R_BLOB_MISMATCH
    assert recs["p/c.fxp"]["refusal"]["code"] == cds.R_LOAD_FAILED
    assert recs["p/a.fxp"]["determinism_gate"] is None
    cov = doc["coverage"]
    assert (cov["candidates_in_corpus"], cov["candidates_attempted"],
            cov["candidates_screened"], cov["candidates_refused"]) == (
                3, 3, 1, 2)
    assert doc["status"] == "NO_VERDICT"
    # refusal reason is not a verification-status token
    assert recs["p/a.fxp"]["refusal"]["code"] not in (
        "PASS", "FAIL", "NOT_RUN", "BLOCKED", "NO_VERDICT", "STALE")


def test_native_shape_disagreement_refuses(corpus):
    kw = corpus([graph("a"), graph("c")])
    ld = FakeLoader({"p/a.fxp": vals(native_shape=False), "p/c.fxp": vals()})
    doc = run(kw, ld)
    r = by_path(doc)["p/a.fxp"]
    assert r["refusal"]["code"] == cds.R_SHAPE_MISMATCH
    assert r["determinism_gate"] is None and r["attempted"]


def test_control_bypassed_shape_check_fails_the_shape_control(corpus):
    kw = corpus([graph("a")])

    def shape_control(doc):
        ref = by_path(doc)["p/a.fxp"]["refusal"]
        assert ref is not None and ref["code"] == cds.R_SHAPE_MISMATCH

    bad = vals(native_shape=False)
    shape_control(run(kw, FakeLoader({"p/a.fxp": bad})))      # real: ok
    with pytest.raises(AssertionError):                       # bypassed: caught
        shape_control(run(kw, FakeLoader({"p/a.fxp": bad}),
                          shape_check=bypassed_shape_check))


def test_single_mode_checks_active_scene_only(corpus):
    kw = corpus([graph("a"), graph("c")])
    ld = FakeLoader({
        # Single, scene B active, B drifts -> FAIL
        "p/a.fxp": vals(mode=0, active=1, a=0.0, b=0.2),
        # Single, scene A active, B (inactive) drifts -> PASS
        "p/c.fxp": vals(mode=0, active=0, a=0.0, b=0.2)})
    recs = by_path(run(kw, ld))
    ga = recs["p/a.fxp"]["determinism_gate"]
    assert ga["voicing_scenes"] == ["B"] and ga["status"] == "FAIL"
    gc = recs["p/c.fxp"]["determinism_gate"]
    assert gc["voicing_scenes"] == ["A"] and gc["status"] == "PASS"


def test_non_single_scene_b_only_drift_fails(corpus):
    kw = corpus([graph("a")])
    doc = run(kw, FakeLoader({"p/a.fxp": vals(mode=1, a=0.0, b=0.131249994)}))
    r = by_path(doc)["p/a.fxp"]
    assert r["determinism_gate"]["drift_per_voicing_scene"] == {
        "A": 0.0, "B": 0.131249994}
    assert doc["status"] == "PASS"            # coverage complete; not a verdict
    assert doc["observations"]["drift_gate_fail"] == 1
    assert "NOT_ESTABLISHED" in doc["render_eligibility"]
    with pytest.raises(AssertionError):
        cds.assert_drift_gate_passed(r)


def test_nine_decimal_rounding_is_the_existing_semantics(corpus):
    kw = corpus([graph("a"), graph("c")])
    ld = FakeLoader({"p/a.fxp": vals(a=4e-10), "p/c.fxp": vals(a=6e-10)})
    recs = by_path(run(kw, ld))
    assert recs["p/a.fxp"]["determinism_gate"]["status"] == "PASS"
    assert recs["p/c.fxp"]["determinism_gate"]["status"] == "FAIL"


def test_default_gate_is_the_shared_extractor_gate():
    assert cds.DRIFT_GATE is ex.drift_gate


def test_control_gate_checking_only_scene_a_fails_the_control(corpus):
    kw = corpus([graph("a")])
    table = {"p/a.fxp": vals(mode=1, a=0.0, b=0.5)}

    def scene_a_only_gate(s, patch):
        d = round(float(s.getParamVal(patch["scene"][0]["drift"])), 9)
        return {"status": "PASS" if d == 0.0 else "FAIL",
                "drift_per_voicing_scene": {"A": d}}

    def b_only_drift_must_be_ineligible(doc):
        with pytest.raises(AssertionError):
            cds.assert_drift_gate_passed(by_path(doc)["p/a.fxp"])

    b_only_drift_must_be_ineligible(run(kw, FakeLoader(table)))   # real: ok
    with pytest.raises(BaseException) as ei:                      # buggy: caught
        b_only_drift_must_be_ineligible(
            run(kw, FakeLoader(table), gate=scene_a_only_gate))
    assert "DID NOT RAISE" in str(ei.value) or ei.type.__name__ == "Failed"


def test_absent_oracle_is_not_run_and_writes_nothing(corpus, tmp_path):
    kw = corpus([graph("a")])
    doc = run(kw, FakeLoader({}, absent=True))
    assert doc["status"] == "NOT_RUN" and "candidates" not in doc
    out = tmp_path / "rec.json"
    with pytest.raises(cds.Refuse):
        cds.write_record(doc, str(out))
    assert not out.exists()


def test_mocked_run_cannot_be_written_as_live_evidence(corpus, tmp_path):
    doc = run(corpus([graph("a")]), FakeLoader({"p/a.fxp": vals()}))
    assert doc["status"] == "PASS" and doc["live"] is False
    out = tmp_path / "rec.json"
    with pytest.raises(cds.Refuse):
        cds.write_record(doc, str(out))
    assert not out.exists()
    doc["live"] = True      # only a live loader may set this; then it writes
    cds.write_record(doc, str(out))
    assert out.exists()


def test_manifest_pin_mismatch_blocks(corpus):
    kw = corpus([graph("a")], manifest_commit="0" * 40)
    ld = FakeLoader({"p/a.fxp": vals()})
    doc = run(kw, ld)
    assert doc["status"] == "BLOCKED" and ld.loaded == []


def test_missing_predicate_blocks(corpus):
    kw = corpus([graph("a")])
    doc = cds.run_screen("x", None, native_shape_check, FakeLoader({}), **kw)
    assert doc["status"] == "BLOCKED"
