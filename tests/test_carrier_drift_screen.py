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
    assert doc["coverage_status"] == "PASS"
    assert doc["drift_gate_status"] == "FAIL"   # drift outcome is separate
    assert "drift_gate_status=FAIL" in doc["status_reason"]
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


# ---------------------------------------------------------------------------
# Coverage status vs drift outcome (never quote coverage PASS as drift-clean)
# ---------------------------------------------------------------------------

def test_drift_gate_status_pass_only_when_complete_and_all_pass(corpus):
    kw = corpus([graph("a"), graph("c")])
    doc = run(kw, FakeLoader({"p/a.fxp": vals(), "p/c.fxp": vals()}))
    assert (doc["status"], doc["coverage_status"],
            doc["drift_gate_status"]) == ("PASS", "PASS", "PASS")
    assert "coverage only" in doc["status_scope"]


def test_drift_gate_status_no_verdict_when_coverage_incomplete(corpus):
    kw = corpus([graph("a"), graph("c")],
                census_over={"p/a.fxp": {"content_verified": "False"}})
    doc = run(kw, FakeLoader({"p/c.fxp": vals()}))
    assert doc["status"] == "NO_VERDICT"
    assert doc["drift_gate_status"] == "NO_VERDICT"   # 1 PASS is not clean


def test_drift_gate_status_fail_dominates_incomplete_coverage(corpus):
    kw = corpus([graph("a"), graph("c")],
                census_over={"p/a.fxp": {"content_verified": "False"}})
    doc = run(kw, FakeLoader({"p/c.fxp": vals(b=0.5)}))
    assert doc["status"] == "NO_VERDICT" and doc["drift_gate_status"] == "FAIL"


# ---------------------------------------------------------------------------
# Unexpected caller exceptions become per-candidate refusals
# ---------------------------------------------------------------------------

def raising_shape_check(s, patch, cand):
    if cand["path"] == "p/a.fxp":
        raise KeyError("shape check bug")


def test_shape_check_exception_is_a_per_candidate_refusal(corpus):
    kw = corpus([graph("a"), graph("c")])
    ld = FakeLoader({"p/a.fxp": vals(), "p/c.fxp": vals()})
    doc = run(kw, ld, shape_check=raising_shape_check)
    recs = by_path(doc)
    assert recs["p/a.fxp"]["refusal"]["code"] == cds.R_SHAPE_CHECK_ERROR
    assert "KeyError" in recs["p/a.fxp"]["refusal"]["detail"]
    assert recs["p/a.fxp"]["determinism_gate"] is None
    assert recs["p/c.fxp"]["screened"]                 # run continued
    assert doc["status"] == "NO_VERDICT"
    assert doc["coverage"]["candidates_refused"] == 1


@pytest.mark.parametrize("bad_gate", [
    lambda s, p: 1 / 0,                                # raises
    lambda s, p: None,                                 # no observation
    lambda s, p: {"status": "MAYBE"},                  # not PASS/FAIL
])
def test_gate_exception_or_malformed_result_is_a_refusal(corpus, bad_gate):
    kw = corpus([graph("a"), graph("c")])
    doc = run(kw, FakeLoader({"p/a.fxp": vals(), "p/c.fxp": vals()}),
              gate=bad_gate)
    for r in doc["candidates"]:
        assert r["refusal"]["code"] == cds.R_GATE_ERROR
        assert r["determinism_gate"] is None and not r["screened"]
    assert doc["status"] == "NO_VERDICT"
    assert doc["drift_gate_status"] == "NO_VERDICT"


def test_unexpected_loader_exception_is_a_refusal(corpus):
    kw = corpus([graph("a"), graph("c")])
    ld = FakeLoader({"p/a.fxp": vals(), "p/c.fxp": vals()})
    orig = ld.load

    def load(rel, sha):
        if rel == "p/a.fxp":
            raise RuntimeError("native crash surrogate")
        return orig(rel, sha)
    ld.load = load
    recs = by_path(run(kw, ld))
    assert recs["p/a.fxp"]["refusal"]["code"] == cds.R_LOAD_ERROR
    assert recs["p/c.fxp"]["screened"]


def test_refusal_codes_are_distinct_and_not_status_tokens():
    codes = [cds.R_NO_CENSUS_ROW, cds.R_BAD_HASH, cds.R_HASH_MISMATCH,
             cds.R_NOT_VERIFIED, cds.R_BLOB_MISMATCH, cds.R_LOAD_FAILED,
             cds.R_SHAPE_MISMATCH, cds.R_NOT_ATTEMPTED, cds.R_LOAD_ERROR,
             cds.R_SHAPE_CHECK_ERROR, cds.R_GATE_ERROR]
    assert len(set(codes)) == len(codes)
    assert not set(codes) & {"PASS", "FAIL", "NOT_RUN", "BLOCKED",
                             "NO_VERDICT", "STALE"}


# ---------------------------------------------------------------------------
# PinnedSurgepyLoader provenance: full pin, clean tree, submodules, runtime,
# build, binding -- all BEFORE loadPatch. Injected git/oracle_common only:
# plumbing controls, not a live-engine run.
# ---------------------------------------------------------------------------

PIN = cds.ENGINE_PIN
# Same 9-char prefix as the pin, different commit: getVersion() would carry
# the prefix, so only full-HEAD verification can tell them apart.
PREFIX_TWIN = PIN[:9] + "0" * 31
SUBS = [{"path": "libs/one", "commit": "1" * 40},
        {"path": "libs/two", "commit": "2" * 40}]
NESTED = [{"path": "libs/two/inner", "commit": "3" * 40}]
PY = "3.11.16"
PLAT = "linux-x86_64"
PREBUILT_SHA = "d" * 64


def oracle_manifest():
    return {"engine": {"commit": PIN},
            "submodules": SUBS, "nested_submodules_observed": NESTED,
            "build": {"python_version": PY,
                      "products": {"surgepy_module":
                                   "build-py311/src/surge-python/x.so"}},
            "prebuilt": {PLAT: {"artifact": "a.tar.gz",
                                "sha256": PREBUILT_SHA,
                                "python": {"version": PY}}}}


class FakeGit:
    """Fake `git -C cwd args` for a pinned checkout; mutate to inject faults."""

    def __init__(self, engine):
        self.engine = os.path.realpath(engine)
        self.heads = {self.engine: PIN}
        self.heads.update({os.path.join(self.engine, s["path"]): s["commit"]
                           for s in SUBS + NESTED})
        self.links = {s["path"]: s["commit"] for s in SUBS}
        self.status = ""
        self.toplevel_override = {}
        self.calls = []

    def __call__(self, args, cwd):
        cwd = os.path.realpath(cwd)
        self.calls.append((cwd, tuple(args)))
        if args[:2] == ["rev-parse", "--show-toplevel"]:
            if cwd in self.toplevel_override:
                return 0, self.toplevel_override[cwd]
            return (0, cwd) if cwd in self.heads else (128, "")
        if args == ["rev-parse", "HEAD"]:
            return (0, self.heads[cwd]) if cwd in self.heads else (128, "")
        if args[0] == "rev-parse" and args[1].startswith("HEAD:"):
            p = args[1][5:]
            return (0, self.links[p]) if p in self.links else (128, "")
        if args[0] == "status":
            return 0, self.status
        raise AssertionError(f"unexpected git call {args}")


class FakeSurge:
    def __init__(self, log):
        self.log = log

    def loadPatch(self, path):
        self.log.append(path)
        return True

    def getPatch(self):
        return fake_patch()


class FakeSurgepy:
    def __init__(self, version="1.4.0.nightly." + PIN[:9]):
        self.version, self.loaded = version, []

    def getVersion(self):
        return self.version

    def createSurge(self, sr):
        assert sr == cds.SAMPLE_RATE
        return FakeSurge(self.loaded)


class FakeOC:
    def __init__(self, engine, surgepy, build_rel="build-py311",
                 module_path=None):
        self.engine, self.surgepy, self.build_rel = engine, surgepy, build_rel
        self.module_path = module_path or os.path.join(
            engine, "build-py311", "src", "surge-python", "x.so")
        self.imported = False

    def engine_dir(self):
        return self.engine

    def build_dir(self):
        return os.path.join(self.engine, self.build_rel)

    def import_surgepy(self):
        self.imported = True
        return self.surgepy

    def binding_provenance(self, m):
        assert m is self.surgepy
        return {"module_path": self.module_path, "module_sha256": "e" * 64,
                "build_dir": self.build_dir()}

    def apply_engine_env(self):
        pass

    def git_blob_sha1(self, path):
        return SHA["a"]


@pytest.fixture
def engine(tmp_path):
    root = tmp_path / "engine"
    for s in SUBS + NESTED:
        (root / s["path"]).mkdir(parents=True)
    (root / "p").mkdir()
    (root / "p" / "a.fxp").write_bytes(b"x")
    mp = tmp_path / "oracle-manifest.json"
    mp.write_text(json.dumps(oracle_manifest()))
    return str(root), str(mp)


def make_loader(engine, git=None, surgepy=None, python_version=PY, **oc_kw):
    root, mp = engine
    sp = surgepy or FakeSurgepy()
    oc = FakeOC(root, sp, **oc_kw)
    ld = cds.PinnedSurgepyLoader(oc=oc, manifest_path=mp,
                                 git=git or FakeGit(root),
                                 platform_key=PLAT,
                                 python_version=python_version)
    return ld, oc, sp


def test_loader_positive_control_full_provenance_opens_and_loads(engine):
    ld, _oc, sp = make_loader(engine)
    info = ld.open()
    prov = info["provenance"]
    assert prov["mode"] == cds.PROV_SOURCE and prov["engine_head"] == PIN
    assert prov["tracked_tree_clean"] is True
    assert [s["commit"] for s in prov["submodules_verified"]] == [
        s["commit"] for s in SUBS]
    assert prov["nested_submodules"][0]["status"] == "verified"
    assert info["binding"]["module_sha256"] == "e" * 64
    ld.load("p/a.fxp", SHA["a"])
    assert sp.loaded == [os.path.join(engine[0], "p/a.fxp")]


def _break_head(g):
    g.heads[g.engine] = PREFIX_TWIN


def _dirty(g):
    g.status = " M src/common/dsp/Oscillator.cpp"


def _dirty_submodule(g):
    g.status = " m libs/one"


def _sub_drift(g):
    g.heads[os.path.join(g.engine, "libs/one")] = "9" * 40


def _gitlink_drift(g):
    g.links["libs/two"] = "8" * 40


def _sub_uninitialized(g):
    g.toplevel_override[os.path.join(g.engine, "libs/one")] = g.engine


def _nested_drift(g):
    g.heads[os.path.join(g.engine, "libs/two/inner")] = "7" * 40


@pytest.mark.parametrize("fault", [
    _break_head, _dirty, _dirty_submodule, _sub_drift, _gitlink_drift,
    _sub_uninitialized, _nested_drift])
def test_loader_prefix_match_with_wrong_or_dirty_source_blocks(engine, fault):
    """Negative control: getVersion() carries the pin prefix (the old
    prefix-only check would accept), but the source is wrong/dirty/drifted:
    open() must BLOCK before any import or loadPatch."""
    g = FakeGit(engine[0])
    fault(g)
    ld, oc, sp = make_loader(engine, git=g)
    assert PIN[:9] in sp.getVersion()           # prefix check alone passes
    with pytest.raises(cds.RunBlocked):
        ld.open()
    assert not oc.imported and sp.loaded == []
    with pytest.raises(cds.Refuse):
        ld.load("p/a.fxp", SHA["a"])            # no load without open()
    assert sp.loaded == []


def test_loader_reviewer_control_custom_build_prefix_refuses(engine, tmp_path):
    """The Judge's control: getVersion()='custom-build-58914e59c' with an
    unverified checkout must not open."""
    sp = FakeSurgepy("custom-build-" + PIN[:9])
    ld, _oc, _ = make_loader(engine, surgepy=sp,
                            git=lambda args, cwd: (128, ""))
    with pytest.raises(cds.RunBlocked):
        ld.open()
    absent = cds.PinnedSurgepyLoader(
        oc=FakeOC(str(tmp_path / "does-not-exist"), sp),
        manifest_path=engine[1], git=FakeGit(engine[0]),
        platform_key=PLAT, python_version=PY)
    with pytest.raises(cds.OracleAbsent):
        absent.open()
    assert sp.loaded == []


@pytest.mark.parametrize("kw,needle", [
    ({"python_version": "3.12.1"}, "Python"),
    ({"build_rel": "build-py314"}, "build dir"),
    ({"module_path": "/elsewhere/surgepy.so"}, "outside"),
    ({"surgepy": FakeSurgepy("1.4.0.nightly.deadbeef0")}, "pinned commit"),
])
def test_loader_runtime_build_binding_mismatch_blocks(engine, kw, needle):
    ld, _oc, sp = make_loader(engine, **kw)
    with pytest.raises(cds.RunBlocked) as ei:
        ld.open()
    assert needle in str(ei.value)
    assert sp.loaded == []


def test_loader_block_surfaces_as_blocked_run_without_evidence(
        corpus, engine, tmp_path):
    kw = corpus([graph("a")])
    g = FakeGit(engine[0])
    _break_head(g)
    ld, _oc, sp = make_loader(engine, git=g)
    doc = run(kw, ld)
    assert doc["status"] == "BLOCKED" and doc["live"] is False
    assert "candidates" not in doc and sp.loaded == []
    out = tmp_path / "rec.json"
    with pytest.raises(cds.Refuse):
        cds.write_record(doc, str(out))
    assert not out.exists()


def _prebuilt(tmp_path, stamp=PREBUILT_SHA, pin=PIN, plat=PLAT):
    d = tmp_path / "cache" / pin / plat
    (d / "p").mkdir(parents=True)
    (d / "p" / "a.fxp").write_bytes(b"x")
    if stamp is not None:
        (d / cds.PREBUILT_STAMP).write_text(stamp + "\n")
    mp = tmp_path / "oracle-manifest.json"
    mp.write_text(json.dumps(oracle_manifest()))
    return str(d), str(mp)


def no_git(args, cwd):
    return 128, ""


def test_loader_prebuilt_artifact_opens_with_explicit_scope(tmp_path):
    ld, _oc, _sp = make_loader(_prebuilt(tmp_path), git=no_git)
    prov = ld.open()["provenance"]
    assert prov["mode"] == cds.PROV_PREBUILT
    assert prov["artifact_sha256"] == PREBUILT_SHA
    assert "NOT re-verified live" in prov["source_tree_verification"]


@pytest.mark.parametrize("kw", [
    {"stamp": "0" * 64},                 # different artifact
    {"stamp": None},                     # foreign directory, no stamp
    {"pin": PREFIX_TWIN},                # installed under another commit
    {"plat": "darwin-arm64"},            # wrong platform layout
])
def test_loader_prebuilt_mismatch_blocks(tmp_path, kw):
    ld, oc, sp = make_loader(_prebuilt(tmp_path, **kw), git=no_git)
    with pytest.raises(cds.RunBlocked):
        ld.open()
    assert not oc.imported and sp.loaded == []


def test_verify_provenance_with_real_git(tmp_path):
    """Exercises the real `git` invocations (HEAD + dirty detection) on a
    throwaway repo; the manifest pin is re-pointed only inside the verifier
    call, the module-level ENGINE_PIN check is satisfied separately."""
    import shutil
    import subprocess
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "r"
    repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for c in (["init", "-q"], ["add", "-A"],
              ["commit", "-q", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", str(repo), *c], check=True, env=env)
    (repo / "f.txt").write_text("a")
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "f"],
                   check=True, env=env)
    head = cds.run_git(["rev-parse", "HEAD"], str(repo))[1]
    man = {"engine": {"commit": head}, "submodules": [],
           "build": {"python_version": PY}}
    prov = cds._verify_source_checkout(str(repo), man, cds.run_git)
    assert prov["engine_head"] == head
    man_wrong = {**man, "engine": {"commit": PREFIX_TWIN}}
    with pytest.raises(cds.RunBlocked):
        cds._verify_source_checkout(str(repo), man_wrong, cds.run_git)
    (repo / "f.txt").write_text("b")
    with pytest.raises(cds.RunBlocked) as ei:
        cds._verify_source_checkout(str(repo), man, cds.run_git)
    assert "modified tracked" in str(ei.value)
