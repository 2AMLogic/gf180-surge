"""#382: unit tests for tools/diagnose_carrier_variation.py.

PINS: variant isolation (each variant starts from the original and changes
only its declared factor), read-back accounting, control routing
(stable original dry bus / failed positive control / always-stable classifier
vs Lap Harp -> NO_VERDICT or FAIL; missing oracle -> BLOCKED), and that a
missing observation can never become PASS.

DOES NOT: run the oracle or establish the diagnostic result.  That result is
NOT_RUN / BLOCKED until a batch run returns shard files; synthetic inputs
here establish classifier behaviour only.
"""
import copy
import importlib.util
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "dcv", os.path.join(REPO, "tools", "diagnose_carrier_variation.py"))
dcv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dcv)

SEQS = dcv.SEQUENCES


def bus(n):
    hs = [f"h{i % n}" for i in range(dcv.REPS)]
    return dcv.bus_summary(hs)


def entry(dry_n, wet_n=2, effective=True, dep=()):
    before = {"a": 1.0, "b": 2.0}
    after = {"a": 0.0 if effective else 1.0, "b": 2.0}
    for d in dep:
        before[d], after[d] = 0.0, 1.0
    return {"dry": bus(dry_n), "wet": bus(wet_n),
            "readback": {"declared": {"a": {"before": 1.0,
                                            "after": after["a"]}},
                         "candidates_before": before,
                         "candidates_after": after}}


def good_shards(stable_factor=None):
    s = {"positive_control": [
            {"slug": k, "gate_3x": "PASS", "byte_identical": True}
            for k in dcv.POSITIVE_CONTROLS],
         "flake_control": {q: {"dry": bus(1), "wet": bus(2)} for q in SEQS},
         "variants": {"original": {q: entry(5) for q in SEQS}}}
    for v in dcv.build_variants()[1:]:
        n = 1 if v["id"] == stable_factor else 4
        s["variants"][v["id"]] = {q: entry(n) for q in SEQS}
    return s


# ---- isolation ----------------------------------------------------------

def test_matrix_is_one_factor_from_original():
    vs = dcv.build_variants()
    assert dcv.validate_matrix(vs) == []
    assert vs[0]["id"] == "original" and vs[0]["factors"] == []
    assert all(v["start_from"] == "original" and len(v["factors"]) == 1
               for v in vs[1:])
    kinds = {f["kind"] for f in dcv.FACTORS}
    assert kinds == {"osc_type", "unison", "noise_level", "noise_colour",
                     "drift", "lfo_random"}


def test_accumulated_or_two_factor_variant_is_rejected():
    vs = dcv.build_variants()
    bad = copy.deepcopy(vs)
    bad[3]["factors"].append(vs[4]["factors"][0])
    assert any("exactly 1" in m for m in dcv.validate_matrix(bad))
    chained = copy.deepcopy(vs)
    chained[2]["start_from"] = chained[1]["id"]
    assert any("does not start from the original" in m
               for m in dcv.validate_matrix(chained))
    assert dcv.validate_matrix(vs[1:]) != []  # original must be first


def test_plan_freezes_reps_jobs_and_covers_both_sequences():
    p = dcv.plan()
    assert p["reps_per_bus"] == 20 and p["gate_reps"] == 3
    ids = [s["job_id"] for s in p["shards"]]
    assert len(set(ids)) == len(ids)
    for v in p["variants"]:
        for q in SEQS:
            assert f"novuo:{v['id']}:{q}" in ids
    assert "positive-controls" in ids
    assert all(s["output"].startswith("reports/sxt-012/diagnostics/novuo/")
               for s in p["shards"])
    assert p["status"] == "NOT_RUN"


class FakeSurge:
    """Binding stand-in: params on a dict; optional loader side-effect."""

    def __init__(self, dependent=False, ineffective=False, exposed=True):
        self.vals = {}
        self.dependent, self.ineffective, self.exposed = \
            dependent, ineffective, exposed
        scene = []
        for sc in range(2):
            oscs = [{"type": ("t", sc, o), "drift": ("d", sc, o),
                     "p": [("p", sc, o, i) for i in range(12)]}
                    for o in range(3)]
            scene.append({"osc": oscs, "level_noise": ("n", sc),
                          "noise_colour": ("nc", sc),
                          "lfo": [{"shape": ("lfo", sc, i)} for i in range(6)]})
        self.patch = {"scene": scene}
        for h in self._all(self.patch):
            self.vals[h] = 5.0

    def _all(self, o):
        if isinstance(o, tuple):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from self._all(v)
        elif isinstance(o, list):
            for v in o:
                yield from self._all(v)

    def getPatch(self):
        if not self.exposed:
            return {"scene": [{"osc": [{} for _ in range(3)]} for _ in range(2)]}
        return self.patch

    def getParamVal(self, h):
        return self.vals[h]

    def setParamVal(self, h, v):
        if self.ineffective:
            return
        self.vals[h] = v
        if self.dependent and h[0] == "t":  # type change resets its params
            self.vals[("p", h[1], h[2], 0)] = 0.0


class Consts:
    ot_sine = 1.0
    ls_sine = 0.0
    ls_noise = 5.0
    ls_snh = 6.0


def test_apply_factor_changes_only_declared_params():
    for f in dcv.FACTORS:
        s = FakeSurge()
        rb = dcv.apply_factor(s, Consts, f)
        assert rb["applied"]
        changed = {k for k in rb["candidates_before"]
                   if rb["candidates_after"][k] != rb["candidates_before"][k]}
        assert changed <= set(rb["declared"]), (f["id"], changed)
        iso = dcv.isolation_audit(rb)
        assert iso["effective"] or f["kind"] == "lfo_random"


def test_original_applies_nothing():
    s = FakeSurge()
    rb = dcv.apply_factor(s, Consts, None)
    assert rb["applied"] is False and rb["declared"] == {}
    assert rb["candidates_before"] == rb["candidates_after"]


def test_ineffective_setter_and_not_exposed_are_recorded_not_hidden():
    f = next(x for x in dcv.FACTORS if x["id"] == "drift_all_osc")
    rb = dcv.apply_factor(FakeSurge(ineffective=True), Consts, f)
    assert dcv.isolation_audit(rb)["effective"] is False
    rb = dcv.apply_factor(FakeSurge(exposed=False), Consts, f)
    iso = dcv.isolation_audit(rb)
    assert iso["not_exposed"] and rb.get("limit")


def test_loader_dependent_change_is_disclosed():
    f = next(x for x in dcv.FACTORS if x["id"] == "osc_type_s0_o0")
    rb = dcv.apply_factor(FakeSurge(dependent=True), Consts, f)
    iso = dcv.isolation_audit(rb)
    assert iso["loader_dependent_changes"] == ["s0.o0.p0"]


def test_loader_dependent_surfaces_in_limits():
    s = good_shards("drift_all_osc")
    s["variants"]["unison_voices_s0_o0"] = {
        q: entry(4, dep=("x",)) for q in SEQS}
    r = dcv.evaluate(s)
    assert any("unison_voices_s0_o0" in m and "not isolated" in m
               for m in r["limits"])


# ---- classification and controls ---------------------------------------

def test_identifies_contributing_factor_when_isolated_removal_is_stable():
    r = dcv.evaluate(good_shards("drift_all_osc"))
    assert r["status"] == "PASS"
    assert r["contributing_factors"] == ["drift_all_osc"]
    assert "not a determinism claim" in r["conclusion"]
    assert set(r["factors_tried"]) == {f["id"] for f in dcv.FACTORS}


def test_no_stable_factor_is_bounded_no_verdict_listing_all_tried():
    r = dcv.evaluate(good_shards(None))
    assert r["status"] == "NO_VERDICT" and r["conclusion"] is None
    for f in dcv.FACTORS:
        assert f["id"] in r["reason"]


def test_stable_on_only_one_sequence_is_not_identified():
    s = good_shards(None)
    s["variants"]["drift_all_osc"][SEQS[0]] = entry(1)
    assert dcv.evaluate(s)["status"] == "NO_VERDICT"


def test_ineffective_intervention_cannot_be_identified():
    s = good_shards(None)
    s["variants"]["drift_all_osc"] = {
        q: entry(1, effective=False) for q in SEQS}
    assert dcv.evaluate(s)["status"] == "NO_VERDICT"


def test_NEG_stable_original_dry_bus_is_no_verdict():
    s = good_shards("drift_all_osc")
    s["variants"]["original"] = {q: entry(1) for q in SEQS}
    r = dcv.evaluate(s)
    assert r["status"] == "NO_VERDICT" and "F-028f-3" in r["reason"]


def test_NEG_failed_positive_control_is_no_verdict():
    for mutate in (lambda r: r.update(byte_identical=False),
                   lambda r: r.update(gate_3x="FAIL")):
        s = good_shards("drift_all_osc")
        mutate(s["positive_control"][1])
        r = dcv.evaluate(s)
        assert r["status"] == "NO_VERDICT"
        assert "positive-control" in r["reason"]
    s = good_shards("drift_all_osc")
    s["positive_control"].pop()
    assert dcv.evaluate(s)["status"] == "NO_VERDICT"
    s["positive_control"] = None
    assert dcv.evaluate(s)["status"] == "NO_VERDICT"


def test_NEG_always_stable_classifier_fails_lap_harp_control():
    rows = [{"sequence": q, "dry": bus(1), "wet": bus(2)} for q in SEQS]
    always = lambda row: True  # noqa: E731
    assert dcv.classify_control(rows, always)["status"] == "FAIL"
    assert dcv.classify_control(rows)["status"] == "PASS"
    assert dcv.classify_control([])["status"] == "NO_VERDICT"


def test_NEG_lap_harp_reported_stable_blocks_the_verdict():
    s = good_shards("drift_all_osc")
    s["flake_control"] = {q: {"dry": bus(1), "wet": bus(1)} for q in SEQS}
    r = dcv.evaluate(s)
    assert r["status"] == "NO_VERDICT" and "Lap Harp" in r["reason"]


def test_missing_observations_never_become_pass():
    s = good_shards("drift_all_osc")
    del s["variants"]["noise_level_s1"][SEQS[1]]
    r = dcv.evaluate(s)
    assert r["status"] == "NO_VERDICT"
    assert "noise_level_s1" in r["incomplete_factors"]
    s = good_shards("drift_all_osc")
    del s["variants"]["original"]
    assert dcv.evaluate(s)["status"] == "NO_VERDICT"
    assert not dcv.bus_stable(None) and not dcv.bus_stable({})
    assert not dcv.bus_stable(dcv.bus_summary([]))


def test_missing_oracle_is_blocked_with_actual_error(tmp_path):
    p = dcv.plan()
    r = dcv.assemble(p, base=str(tmp_path),
                     probe=lambda: (False, "engine checkout not found: /x"))
    assert r["status"] == "BLOCKED"
    assert "engine checkout not found: /x" in r["reason"]
    assert r["conclusion"] is None
    assert r["status"] in dcv.STATUSES


def test_no_shards_and_oracle_present_is_not_run(tmp_path):
    r = dcv.assemble(dcv.plan(), base=str(tmp_path),
                     probe=lambda: (True, None))
    assert r["status"] == "NOT_RUN" and r["conclusion"] is None


def test_probe_blocked_in_this_environment_or_ok():
    ok, err = dcv.probe_oracle()
    assert ok or err  # an unavailable oracle must carry its actual error


def test_render_shard_refuses_when_oracle_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(dcv, "probe_oracle", lambda: (False, "no engine"))
    p = dcv.plan()
    try:
        dcv.render_shard(p["shards"][0], p, str(tmp_path / "x.json"))
    except dcv.Blocked as e:
        assert "no engine" in str(e)
    else:
        raise AssertionError("expected Blocked")
    assert not (tmp_path / "x.json").exists()
