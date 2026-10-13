"""SXT-028d routing-form leaf tests (pytest): Global FX slot 2 (second
concurrent global-FX instance).

Covers: frozen arithmetic/schedule (fx_bypass gate, fx_disable bitmask,
ring-out threading), model determinism + per-instance independence, the
committed carrier routing/scheduling metadata (census+graphs cross-check,
oracle-independent), negative-control evidence integrity, and the committed
RTL-exactness record (fail-closed). A missing iverilog/oracle makes the
corresponding leg NOT_RUN, never a pass.
"""
import json
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global2"))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "oracle"))

import carrier_drift_screen as cds  # noqa: E402
import rf_global2_model as rm  # noqa: E402
import screen_rf_global2_carriers as scr  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028d")

COEFFS_A = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_B = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
            rm.to_q(-0.35, 29, 32), rm.to_q(0.18, 29, 32))


def rand_block(rs, amp=0.3):
    return ([rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)])


def test_frozen_constants_and_layout():
    assert rm.BLOCK == 32
    assert rm.A_FRAC == 21 and rm.A_BITS == 32
    assert rm.C_FRAC == 29 and rm.C_BITS == 32
    assert rm.R_BITS == 80
    assert rm.FXB_ALL_FX == 0 and rm.FXB_NO_SENDS == 1
    assert rm.FXB_SCENE_FX_ONLY == 2 and rm.FXB_NO_FX == 3
    assert rm.FXSLOT_GLOBAL1 == 6 and rm.FXSLOT_GLOBAL2 == 7


def test_bypass_gate_skips_processing():
    """fx_bypass in {SCENE_FX_ONLY, NO_FX} must pass the bus through
    unchanged and leave the ring flag untouched."""
    st = rm.RoutingState()
    st.slot1.load(*COEFFS_A)
    st.slot2.load(*COEFFS_B)
    rs = random.Random(1)
    il, ir = rand_block(rs)
    for mode in (rm.FXB_SCENE_FX_ONLY, rm.FXB_NO_FX):
        st.fx_bypass = mode
        ol, orr, glob = st.process_block(il, ir, True)
        assert ol == il and orr == ir
        assert glob is True   # glob_in echoed back unmodified


def test_disable_bitmask_gates_correct_slot():
    st_ref = rm.RoutingState()
    st_ref.slot1.load(*COEFFS_A)
    st_ref.slot2.load(*COEFFS_B)
    rs = random.Random(2)
    il, ir = rand_block(rs)
    ol_ref, orr_ref, _ = st_ref.process_block(il, ir, True)

    # disabling slot1 (bit 6): slot1 must be a no-op, slot2 must still run
    st1 = rm.RoutingState()
    st1.slot1.load(*COEFFS_A)
    st1.slot2.load(*COEFFS_B)
    st1.fx_disable = 1 << rm.FXSLOT_GLOBAL1
    ol1, orr1, _ = st1.process_block(il, ir, True)
    only_slot2 = rm.RoutingState()
    only_slot2.slot2.load(*COEFFS_B)
    ol_expect, orr_expect, _ = only_slot2.process_block(il, ir, True)
    assert (ol1, orr1) == (ol_expect, orr_expect)
    assert (ol1, orr1) != (ol_ref, orr_ref)


def test_dual_instance_independent_histories():
    st = rm.RoutingState()
    st.slot1.load(*COEFFS_A)
    st.slot2.load(*COEFFS_B)
    rs = random.Random(3)
    for _ in range(20):
        il, ir = rand_block(rs)
        st.process_block(il, ir, True)
    assert st.slot1.biquad.reg0 != st.slot2.biquad.reg0
    assert st.slot1.biquad is not st.slot2.biquad


def test_ring_out_no_op_when_not_live():
    st = rm.RoutingState()
    st.slot1.load(*COEFFS_A)
    st.slot2.load(*COEFFS_B)
    rs = random.Random(4)
    il, ir = rand_block(rs)
    ol, orr, glob = st.process_block(il, ir, False)
    assert ol == il and orr == ir and glob is False
    assert st.slot1.biquad.reg0 == [0, 0]   # never touched


def test_model_determinism():
    outs = []
    for _ in range(2):
        st = rm.RoutingState()
        st.slot1.load(*COEFFS_A)
        st.slot2.load(*COEFFS_B)
        rs = random.Random(7)
        o = []
        glob = True
        for _b in range(10):
            il, ir = rand_block(rs)
            ol, orr, glob = st.process_block(il, ir, glob)
            o.append((ol, orr, glob))
        outs.append((o, st.checkpoint()))
    assert outs[0] == outs[1]


def test_extraction_records_fail_closed():
    for slug in ("ancient-fm", "piercing", "rounded"):
        d = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs",
                                        f"rf-rf-global2-{slug}.json")))
        assert d["applicability"]["routing_metadata_verified"] is True
        assert d["preset"]["census_blob_sha1_verified"] == \
            d["preset"]["graphs_blob_sha1_verified"]
        # oracle-dependent leg is honestly refused in this environment, not
        # fabricated as a pass
        assert d["oracle_extraction"]["attempted"] is True
        if not d["oracle_extraction"]["ok"]:
            assert d["applicability"]["complete_wet_render_possible"] is False
    ancient = json.load(open(os.path.join(
        REPO, "model", "effects", "fx_inputs", "rf-rf-global2-ancient-fm.json")))
    assert ancient["dual_instance_concurrent"] is True
    rounded = json.load(open(os.path.join(
        REPO, "model", "effects", "fx_inputs", "rf-rf-global2-rounded.json")))
    assert rounded["dual_instance_concurrent"] is False
    assert rounded["global1"]["occupied"] is False


def test_negative_controls_all_fail_their_checks():
    p = os.path.join(SXT, "negative-controls", "negative-controls.json")
    if not os.path.exists(p):
        pytest.skip("negative-controls.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert len(d["controls"]) == 5
    for c in d["controls"]:
        assert c["ok"] is True and "CONTROL-OK" in c["verdict"], c["control"]


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == rm.model_revision(), "stale record"
    assert len(d["cases"]) == 10
    for c in d["cases"]:
        assert c["exact"] is True, c["case"]
        assert c["mismatches"] == 0, c["case"]
        assert c["revision_pin"]["ok"] is True, c["case"]


def test_state_cost_record_no_external_memory_claimed():
    p = os.path.join(SXT, "artifacts", "state-cost.json")
    if not os.path.exists(p):
        pytest.skip("state-cost.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["external_writable_memory"]["words_total"] == 0
    assert d["external_traffic"]["words_per_sample"] == 0
    assert "PENDING-SXT-016" in d["ext_mem_traffic_estimate"]


def test_named_compute_gap_recorded_in_evidence():
    """The oracle-dependent gap must be documented, not silently absent."""
    p = os.path.join(SXT, "EVIDENCE.md")
    if not os.path.exists(p):
        pytest.skip("EVIDENCE.md not committed (NOT_RUN)")
    text = open(p).read()
    assert "NOT_RUN" in text
    assert "oracle" in text.lower()


# --------------------------------------------------------------------------
# #425: recorded same-shape drift-0 carrier screen + eligibility consistency.
# These tests check the COMMITTED live record's internal consistency and the
# screen's refusal/selection logic with injected (non-live) fakes. They are
# NOT live-oracle evidence; the live run is the committed
# reports/SXT-028d/artifacts/carrier-drift-screen.json (re-run:
# tools/screen_rf_global2_carriers.py under the pinned oracle).
# --------------------------------------------------------------------------

SCREEN = os.path.join(SXT, "artifacts", "carrier-drift-screen.json")


def load_screen():
    if not os.path.exists(SCREEN):
        pytest.skip("carrier-drift-screen.json not committed (NOT_RUN)")
    return json.load(open(SCREEN))


def derive_gate_status(gate):
    """Verdict derived ONLY from the recorded per-scene drift values."""
    drifts = gate["drift_per_voicing_scene"]
    assert set(drifts) == set(gate["voicing_scenes"]), "voicing scene mismatch"
    return "PASS" if all(v == 0.0 for v in drifts.values()) else "FAIL"


def check_record_consistent(rec):
    """A candidate's recorded gate status must equal the status derived from
    its recorded drift values, and eligibility must follow from it."""
    if not rec["screened"]:
        assert rec["determinism_gate"] is None and rec["refusal"]
        return
    gate = rec["determinism_gate"]
    assert gate["status"] == derive_gate_status(gate), rec["path"]


def check_original_eligibility(shape_rec):
    orig = shape_rec["original_result"]
    check_record_consistent(orig)
    el = shape_rec["original_eligibility"]
    if derive_gate_status(orig["determinism_gate"]) == "FAIL":
        assert el["render_eligible"] is False, "failed original made eligible"
        assert el["drift_screen"] == "FAIL"
    else:
        assert el["drift_screen"] == "PASS"
        assert el["render_eligible"] != True  # noqa: E712 - never asserted


def test_screen_record_is_live_and_covers_denominator():
    d = load_screen()
    assert d["live"] is True and d["issue"] == "#425"
    assert [s["shape"]["slug"] for s in d["shapes"]] == \
        [x["slug"] for x in scr.SHAPES]
    for s, sh in zip(d["shapes"], scr.SHAPES):
        r = s["run"]
        assert r["live"] is True
        assert r["engine"]["provenance"]["mode"] in (
            "source_checkout", "manifest_prebuilt_artifact")
        assert r["coverage"]["candidates_in_corpus"] == sh["expected_count"]
        # coverage and drift verdict are reported separately
        assert r["coverage_status"] in ("PASS", "NO_VERDICT")
        assert r["drift_gate_status"] in ("PASS", "FAIL", "NO_VERDICT")
        assert len(r["candidates"]) == sh["expected_count"]
        for c in r["candidates"]:
            check_record_consistent(c)
            assert c["screened"] is False or c["native_state"] is not None


def test_denominator_matches_live_corpus_predicate():
    d = load_screen()
    for s, sh in zip(d["shapes"], scr.SHAPES):
        cands = cds.enumerate_candidates(scr.make_predicate(sh))
        assert [c["path"] for c in cands] == \
            [c["path"] for c in s["run"]["candidates"]]
        assert [c["path"] for c in cands] == \
            [c["path"] for c in s["run"]["candidate_manifest"]]
        assert sh["path"] in [c["path"] for c in cands], \
            "original must satisfy its own declared shape"


def test_affected_originals_stay_non_render_eligible():
    d = load_screen()
    by = {s["shape"]["slug"]: s for s in d["shapes"]}
    for slug in ("ancient-fm", "rounded"):
        check_original_eligibility(by[slug])
        assert by[slug]["original_eligibility"]["render_eligible"] is False
        # the original is preserved in the denominator, never dropped
        assert by[slug]["original_result"]["path"] == by[slug]["shape"]["path"]


def test_selection_reproduces_from_recorded_gates():
    d = load_screen()
    for s in d["shapes"]:
        cands = s["run"]["candidates"]
        orig = next(c for c in cands if c["path"] == s["shape"]["path"])
        otypes = orig["native_state"]["fx_type_ids"]
        ranked, selected = scr.select_replacement(cands, s["shape"]["path"],
                                                  otypes)
        assert s["selection"]["eligible_same_shape_drift0_ranked"] == ranked
        assert s["selection"]["selected_addition"] == selected
        assert s["selection"]["outcome"] == (
            "REPLACEMENT_SELECTED" if selected else "BOUNDED_GAP")
        assert s["shape"]["path"] not in ranked
        for p in ranked:
            rec = next(c for c in cands if c["path"] == p)
            assert derive_gate_status(rec["determinism_gate"]) == "PASS"


def test_extractor_eligibility_matches_screen_record():
    d = load_screen()
    by = {s["shape"]["slug"]: s for s in d["shapes"]}
    for slug in ("ancient-fm", "rounded"):
        ex_rec = json.load(open(os.path.join(
            REPO, "model", "effects", "fx_inputs",
            f"rf-rf-global2-{slug}.json")))["render_eligibility"]
        assert ex_rec["drift_screen"] == derive_gate_status(
            ex_rec["determinism_gate"])
        assert ex_rec["determinism_gate"]["drift_per_voicing_scene"] == \
            by[slug]["original_result"]["determinism_gate"][
                "drift_per_voicing_scene"]
        assert ex_rec["render_eligible"] is False
    piercing = json.load(open(os.path.join(
        REPO, "model", "effects", "fx_inputs",
        "rf-rf-global2-piercing.json")))["render_eligibility"]
    assert piercing["drift_screen"] == derive_gate_status(
        piercing["determinism_gate"])
    assert piercing["render_eligible"] != True  # noqa: E712


def test_mutation_nonzero_drift_original_made_eligible_fails():
    """Mutation control: flipping a nonzero-drift original to PASS/eligible
    must be caught by the consistency checks."""
    d = load_screen()
    s = next(x for x in d["shapes"] if x["shape"]["slug"] == "ancient-fm")
    check_original_eligibility(s)           # unmutated: consistent
    bad = json.loads(json.dumps(s))
    bad["original_result"]["determinism_gate"]["status"] = "PASS"
    with pytest.raises(AssertionError):
        check_original_eligibility(bad)
    with pytest.raises(AssertionError):
        cds.assert_drift_gate_passed(s["original_result"])
    bad2 = json.loads(json.dumps(s))
    bad2["original_eligibility"]["render_eligible"] = True
    with pytest.raises(AssertionError):
        check_original_eligibility(bad2)


def _rec(path, drifts, types=(0,) * 6 + (9, 9), screened=True):
    gate = None
    if screened:
        gate = {"status": "PASS" if all(v == 0.0 for v in drifts.values())
                else "FAIL", "drift_per_voicing_scene": drifts,
                "voicing_scenes": sorted(drifts)}
    return {"path": path, "screened": screened, "determinism_gate": gate,
            "refusal": None if screened else {"code": "x"},
            "native_state": {"fx_type_ids": list(types)}}


def test_scene_b_only_drift_fails_gate():
    class S:
        vals = {"mode": 2, "act": 0, "dA": 0.0, "dB": 0.25}

        def getParamVal(self, k):
            return self.vals[k]
    patch = {"scenemode": "mode", "scene_active": "act",
             "scene": [{"drift": "dA"}, {"drift": "dB"}]}
    g = cds.DRIFT_GATE(S(), patch)
    assert g["status"] == "FAIL" and g["drift_per_voicing_scene"]["A"] == 0.0
    with pytest.raises(AssertionError):
        cds.assert_drift_gate_passed({"path": "x", "screened": True,
                                      "determinism_gate": g})


def test_no_eligible_candidate_is_bounded_gap():
    cands = [_rec("a", {"A": 0.1}), _rec("b", {"A": 0.0}, screened=False),
             _rec("orig", {"A": 0.0})]
    ranked, selected = scr.select_replacement(cands, "orig", [0] * 6 + [9, 9])
    assert ranked == [] and selected is None


def test_selection_is_deterministic_and_excludes_original():
    otypes = [0] * 6 + [14, 9]
    cands = [_rec("z", {"A": 0.0}, types=(0,) * 6 + (14, 9)),
             _rec("b", {"A": 0.0}, types=(0,) * 6 + (1, 1)),
             _rec("a", {"A": 0.0}, types=(0,) * 6 + (1, 1)),
             _rec("orig", {"A": 0.0}, types=tuple(otypes))]
    ranked, selected = scr.select_replacement(cands, "orig", otypes)
    assert ranked == ["z", "a", "b"] and selected == "z"
    assert scr.select_replacement(list(reversed(cands)), "orig",
                                  otypes) == (ranked, selected)


def test_missing_oracle_is_not_run_and_writes_nothing(tmp_path):
    class Absent:
        is_live = False

        def open(self):
            raise cds.OracleAbsent("no oracle")
    doc = scr.screen_all(Absent())
    assert doc["status"] == "NOT_RUN" and doc["live"] is False
    out = tmp_path / "x.json"
    with pytest.raises(Exception):
        cds.write_record(doc, str(out))
    assert not out.exists()


def test_injected_loader_run_is_never_writable_as_live_evidence(tmp_path):
    class Fake:
        is_live = False

        def open(self):
            return {"pin": cds.ENGINE_PIN}

        def load(self, rel, sha):
            raise cds.LoadRefusal(cds.R_LOAD_FAILED, "fake")
    sh = scr.SHAPES[1]
    rec = scr.screen_shape(sh, Fake())
    r = rec["run"]
    assert r["coverage"]["candidates_screened"] == 0
    assert r["drift_gate_status"] == "NO_VERDICT"
    assert rec["selection"]["outcome"] == "BOUNDED_GAP"
    assert rec["original_eligibility"]["render_eligible"] is False
    with pytest.raises(Exception):
        cds.write_record(r, str(tmp_path / "y.json"))


def test_shape_check_refuses_native_disagreement():
    sh = scr.SHAPES[0]
    cand = cds.enumerate_candidates(scr.make_predicate(sh))[0]
    ntypes = [fx.get("t", 0) for fx in cand["graph"]["fx"]]

    class S:
        def __init__(self, types, fxb=0):
            self.types, self.fxb = types, fxb

        def getParamVal(self, k):
            if isinstance(k, tuple):
                return self.types[k[1]]
            return {"fxb": self.fxb, "fxd": 0, "mode": 0, "act": 0}[k]
    patch = {"fx": [{"type": ("t", i)} for i in range(len(ntypes))],
             "fx_bypass": "fxb", "fx_disable": "fxd", "scenemode": "mode",
             "scene_active": "act"}
    native = {}
    chk = scr.make_shape_check(sh, native)
    assert chk(S(ntypes), patch, cand) is None
    wrong = list(ntypes)
    wrong[6] = 0          # type mismatch vs graphs.jsonl
    assert chk(S(wrong), patch, cand)
    assert chk(S(ntypes, fxb=2), patch, cand)   # fx_bypass not All FX


def test_original_not_matching_its_shape_blocks():
    bad = dict(scr.SHAPES[1], path=scr.SHAPES[0]["path"])  # dual != g1-off
    with pytest.raises(cds.RunBlocked):
        scr.screen_shape(bad, object())
