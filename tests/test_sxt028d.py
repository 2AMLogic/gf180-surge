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

import rf_global2_model as rm  # noqa: E402

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
