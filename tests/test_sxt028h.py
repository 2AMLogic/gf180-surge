"""SXT-028h routing-form leaf tests (pytest): Scene-B insert FX bus, slots 1-2
(bins1 -> bins2).

Covers: the frozen arithmetic/schedule (the insert-stage bypass partition, the
`fx_disable` bitmask, ring-out threading), the instance lifecycle
(patch-change reload mid-tail, slot-off, panic/reset), model determinism and
per-instance independence, the declared tail span, generator consistency of
the committed carrier records (census+graphs cross-check, oracle-independent,
fail-closed on injected drift), negative-control evidence integrity, and the
committed RTL-exactness record (fail-closed on a stale model revision).

ORACLE-DEPENDENT LEGS (per-slot algorithm parameters, wet-audio fixture
renders, model-vs-reference agreement) are NOT run here: they are recorded as
refused/NOT_RUN and are never reported as a pass (AGENTS.md). The same rule
covers a missing iverilog: the RTL-exactness and negative-control records are
asserted only when committed, and a stale record (model-revision drift) FAILS
rather than silently passing.
"""
import copy
import json
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-bins12"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import rf_bins12_model as rm  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028h")
FX_INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")
CARRIER_SLUGS = ("novuo", "acoordion-basses", "shore")

COEFFS_A = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_B = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
            rm.to_q(-0.35, 29, 32), rm.to_q(0.18, 29, 32))
COEFFS_TAIL = (rm.to_q(0.06, 29, 32), 0, 0,
               rm.to_q(-1.90, 29, 32), rm.to_q(0.945, 29, 32))


def rand_block(rs, amp=0.3):
    return ([rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)])


def loaded_bus(c1=COEFFS_A, c2=COEFFS_B, fx_bypass=rm.FXB_ALL_FX,
               fx_disable=0, occ1=True, occ2=True):
    bus = rm.SceneBInsertBus()
    bus.apply_control(fx_bypass, fx_disable, occ1, True, c1, occ2, True, c2)
    return bus


# --------------------------------------------------------------------------
# frozen constants / schedule
# --------------------------------------------------------------------------

def test_frozen_constants_and_layout():
    assert rm.BLOCK == 32
    assert rm.A_FRAC == 21 and rm.A_BITS == 32
    assert rm.C_FRAC == 29 and rm.C_BITS == 32
    assert rm.R_BITS == 80
    assert rm.FXB_ALL_FX == 0 and rm.FXB_NO_SENDS == 1
    assert rm.FXB_SCENE_FX_ONLY == 2 and rm.FXB_NO_FX == 3
    assert rm.FXSLOT_BINS1 == 2 and rm.FXSLOT_BINS2 == 3
    # the insert stage runs in every mode EXCEPT fxb_no_fx
    assert rm.INSERT_ACTIVE_MODES == (rm.FXB_ALL_FX, rm.FXB_NO_SENDS,
                                      rm.FXB_SCENE_FX_ONLY)


def test_slot_indices_agree_with_the_committed_corpus_role_table():
    """The slot indices are re-derived from an in-repo artifact (no live
    oracle): every graphs.jsonl record carries the pinned engine's slot order
    by patch fx[] index."""
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              encoding="utf-8") as f:
        g = json.loads(f.readline())["g"]
    roles = {fx["i"]: fx["r"] for fx in g["fx"]}
    assert roles[rm.FXSLOT_BINS1] == "bins1"
    assert roles[rm.FXSLOT_BINS2] == "bins2"
    # and the sibling routing leaf's own pinned indices still hold
    assert roles[6] == "global1" and roles[7] == "global2"


def test_insert_stage_runs_in_every_mode_but_no_fx():
    rs = random.Random(1)
    il, ir = rand_block(rs)
    for mode in (rm.FXB_ALL_FX, rm.FXB_NO_SENDS, rm.FXB_SCENE_FX_ONLY):
        bus = loaded_bus(fx_bypass=mode)
        ol, orr, sc = bus.process_block(il, ir, True)
        assert (ol, orr) != (il, ir), f"mode {mode} must process the bus"
        assert sc is True
    bus = loaded_bus(fx_bypass=rm.FXB_NO_FX)
    ol, orr, sc = bus.process_block(il, ir, True)
    assert ol == il and orr == ir          # bus untouched
    assert sc is True                      # ring flag passes through
    assert bus.slot1.biquad.reg0 == [0, 0]  # no state was advanced
    assert bus.slot2.biquad.reg0 == [0, 0]


def test_disable_bitmask_gates_the_named_slot_only():
    rs = random.Random(2)
    il, ir = rand_block(rs)
    ref = loaded_bus()
    ol_ref, orr_ref, _ = ref.process_block(il, ir, True)

    # disabling bins1 (bit 2): bins1 must be a no-op, bins2 must still run
    b1off = loaded_bus(fx_disable=1 << rm.FXSLOT_BINS1)
    ol1, orr1, _ = b1off.process_block(il, ir, True)
    only2 = loaded_bus(occ1=False)
    ol_exp, orr_exp, _ = only2.process_block(il, ir, True)
    assert (ol1, orr1) == (ol_exp, orr_exp)
    assert (ol1, orr1) != (ol_ref, orr_ref)

    # disabling bins2 (bit 3)
    b2off = loaded_bus(fx_disable=1 << rm.FXSLOT_BINS2)
    ol2, orr2, _ = b2off.process_block(il, ir, True)
    only1 = loaded_bus(occ2=False)
    ol_exp1, orr_exp1, _ = only1.process_block(il, ir, True)
    assert (ol2, orr2) == (ol_exp1, orr_exp1)

    # a bit belonging to ANOTHER slot (global1 = 6) must not gate this bus
    other = loaded_bus(fx_disable=1 << 6)
    ol3, orr3, _ = other.process_block(il, ir, True)
    assert (ol3, orr3) == (ol_ref, orr_ref)


def test_scene_not_live_is_a_no_op():
    bus = loaded_bus()
    rs = random.Random(4)
    il, ir = rand_block(rs)
    ol, orr, sc = bus.process_block(il, ir, False)
    assert ol == il and orr == ir and sc is False
    assert bus.slot1.biquad.reg0 == [0, 0]   # never touched
    assert bus.slot2.biquad.reg0 == [0, 0]


# --------------------------------------------------------------------------
# per-instance state and lifecycle
# --------------------------------------------------------------------------

def test_dual_instance_independent_histories():
    bus = loaded_bus()
    rs = random.Random(3)
    for _ in range(20):
        il, ir = rand_block(rs)
        bus.process_block(il, ir, True)
    assert bus.slot1.biquad is not bus.slot2.biquad
    assert bus.slot1.biquad.reg0 != bus.slot2.biquad.reg0
    assert bus.slot1.biquad.reg1 != bus.slot2.biquad.reg1


def test_patch_change_mid_tail_clears_only_that_slot():
    """`loadFx()` on bins1 mid-tail installs a fresh instance for bins1 ONLY:
    bins2's history (and the scene ring flag) survive."""
    bus = loaded_bus(c1=COEFFS_TAIL)
    rs = random.Random(5)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        bus.process_block(il, ir, True)
    assert bus.slot1.biquad.reg0 != [0, 0]
    before2 = copy.deepcopy(bus.slot2.biquad.reg0)
    assert before2 != [0, 0]

    # reload bins1 only
    bus.apply_control(rm.FXB_ALL_FX, 0, True, True, COEFFS_A,
                      True, False, COEFFS_B)
    assert bus.slot1.biquad.reg0 == [0, 0]      # fresh instance
    assert bus.slot2.biquad.reg0 == before2     # sibling untouched
    assert bus.slot1.biquad.coeffs == COEFFS_A  # new coefficients adopted


def test_slot_off_mid_tail_releases_only_that_instance():
    bus = loaded_bus(c1=COEFFS_TAIL)
    rs = random.Random(6)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        bus.process_block(il, ir, True)
    before1 = copy.deepcopy(bus.slot1.biquad.reg0)
    bus.apply_control(rm.FXB_ALL_FX, 0, True, False, COEFFS_TAIL,
                      False, False, COEFFS_B)
    assert bus.slot2.occupied is False
    assert bus.slot2.biquad.reg0 == [0, 0]
    assert bus.slot1.biquad.reg0 == before1


def test_panic_reset_clears_both_instances_and_the_ring_memory():
    bus = loaded_bus(c1=COEFFS_TAIL)
    rs = random.Random(7)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        bus.process_block(il, ir, True)
    assert bus.sc_ring is True
    bus.panic_reset()
    assert bus.checkpoint() == ((0, 0), (0, 0), (0, 0), (0, 0))
    assert bus.sc_ring is False
    assert bus.slot1.occupied and bus.slot2.occupied   # patch still loaded


def test_coefficient_change_without_reload_keeps_state():
    bus = loaded_bus()
    rs = random.Random(8)
    for _ in range(2):
        il, ir = rand_block(rs)
        bus.process_block(il, ir, True)
    keep = copy.deepcopy(bus.slot1.biquad.reg0)
    bus.apply_control(rm.FXB_ALL_FX, 0, True, False, COEFFS_B,
                      True, False, COEFFS_A)
    assert bus.slot1.biquad.reg0 == keep
    assert bus.slot1.biquad.coeffs == COEFFS_B


def test_model_determinism():
    runs = []
    for _ in range(2):
        bus = loaded_bus()
        rs = random.Random(9)
        out = []
        sc = True
        for _b in range(10):
            il, ir = rand_block(rs)
            ol, orr, sc = bus.process_block(il, ir, sc)
            out.append((ol, orr, sc))
        runs.append((out, bus.checkpoint()))
    assert runs[0] == runs[1]


# --------------------------------------------------------------------------
# declared tail span
# --------------------------------------------------------------------------

def test_declared_tail_span_carries_audio_and_truncation_loses_it():
    """With the scene still live and the input gone silent, the occupant's
    registers must keep producing audio across the declared tail span; a
    render truncated at the end of the input drops real samples."""
    import compare_rtl_model_rf_bins12 as cmp_rtl
    signal = cmp_rtl.TAIL_SIGNAL_BLOCKS
    span = cmp_rtl.TAIL_SPAN_BLOCKS
    bus = loaded_bus(c1=COEFFS_TAIL)
    rs = random.Random(10)
    tail_energy = []
    for b in range(signal + span):
        il, ir = (rand_block(rs, 0.05) if b < signal
                  else ([0] * rm.BLOCK, [0] * rm.BLOCK))
        ol, orr, _ = bus.process_block(il, ir, True)
        if b >= signal:
            tail_energy.append(sum(abs(v) for v in ol + orr))
    assert len(tail_energy) == span
    assert all(e > 0 for e in tail_energy), tail_energy
    # monotone-ish decay: the last tail block is much quieter than the first
    assert tail_energy[-1] < tail_energy[0]


def test_reset_mid_tail_kills_the_tail():
    bus = loaded_bus(c1=COEFFS_TAIL)
    rs = random.Random(11)
    for _ in range(2):
        il, ir = rand_block(rs, 0.05)
        bus.process_block(il, ir, True)
    bus.panic_reset()
    ol, orr, _ = bus.process_block([0] * rm.BLOCK, [0] * rm.BLOCK, True)
    assert all(v == 0 for v in ol + orr)


def test_no_external_memory_traffic_from_this_leaf():
    bus = loaded_bus()
    rs = random.Random(12)
    for _ in range(4):
        il, ir = rand_block(rs)
        bus.process_block(il, ir, True)
    for slot in (bus.slot1, bus.slot2):
        assert slot.ext_reads == 0 and slot.ext_writes == 0


# --------------------------------------------------------------------------
# generator consistency / fail-closed extraction
# --------------------------------------------------------------------------

def test_carrier_records_match_the_extractor_output():
    """Committed carrier records must be exactly what the extractor produces
    now (no stale artifact, no hand edit)."""
    import extract_rf_bins12_inputs as ex
    for carrier in ex.CARRIERS:
        path = os.path.join(FX_INPUTS, f"rf-rf-bins12-{carrier['slug']}.json")
        assert os.path.exists(path), path
        on_disk = json.load(open(path))
        fresh = ex.extract_one(carrier)
        # the oracle leg's free-text reason is environment-dependent; compare
        # everything else exactly and the oracle leg structurally.
        assert on_disk["oracle_extraction"]["attempted"] is True
        od = dict(on_disk)
        fr = dict(fresh)
        od.pop("oracle_extraction")
        fr.pop("oracle_extraction")
        assert od == fr, (f"{path} is stale — regenerate with "
                          "`python3 tools/extract_rf_bins12_inputs.py`")


def test_extraction_records_fail_closed():
    for slug in CARRIER_SLUGS:
        d = json.load(open(os.path.join(FX_INPUTS,
                                        f"rf-rf-bins12-{slug}.json")))
        assert d["leaf"] == "SXT-028h" and d["roles"] == ["bins1", "bins2"]
        assert d["applicability"]["routing_metadata_verified"] is True
        assert d["preset"]["census_blob_sha1_verified"] == \
            d["preset"]["graphs_blob_sha1_verified"]
        assert d["cross_check"]["census_vs_graphs_drift_count"] == 0
        assert d["scene_context"]["scene_b_instantiated"] is True
        # return_level is stored per slot but not consumed by the insert path
        assert d["bins1"]["return_level_consumed_by_insert_path"] is False
        # oracle-dependent leg is honestly refused in this environment, not
        # fabricated as a pass
        assert d["oracle_extraction"]["attempted"] is True
        if not d["oracle_extraction"]["ok"]:
            assert d["applicability"]["complete_wet_render_possible"] is False
    novuo = json.load(open(os.path.join(FX_INPUTS,
                                        "rf-rf-bins12-novuo.json")))
    assert novuo["dual_instance_concurrent"] is True
    assert novuo["bins1"]["occupied"] and novuo["bins2"]["occupied"]
    shore = json.load(open(os.path.join(FX_INPUTS, "rf-rf-bins12-shore.json")))
    assert shore["dual_instance_concurrent"] is False
    assert shore["bins2"]["occupied"] is False


def test_extraction_refuses_injected_drift():
    """Live control for the fail-closed claim: a census/graphs disagreement
    and a blob-sha mismatch must both REFUSE, not be papered over."""
    import extract_rf_bins12_inputs as ex
    carrier = ex.CARRIERS[0]
    row = ex.census_row(carrier["path"])
    graph = ex.graphs_entry(carrier["path"])
    ex.cross_check(row, graph)          # clean pair passes

    bad = dict(row)
    bad["stored_fx_bypass"] = "3"       # drift in fx_bypass
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad, graph)

    bad2 = dict(row)
    bad2["stored_nonoff_fx_slot_count"] = "99"
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad2, graph)

    with pytest.raises(ex.Refuse):
        ex.extract_one({"slug": "x", "path": carrier["path"],
                        "declared_sha1": "0" * 40})


def test_leaf_spec_declares_this_routing_form():
    """Generator consistency: the committed leaf spec names exactly the roles
    and deliverable paths this leaf implements."""
    spec = json.load(open(os.path.join(REPO, "reports", "sxt-028", "leaves",
                                       "SXT-028h.json")))
    assert spec["leaf_id"] == "SXT-028h"
    assert spec["feature"]["roles"] == ["bins1", "bins2"]
    assert spec["feature"]["routing_form"] == "rf-bins12"
    for rel in ("model/effects/rf-rf-bins12",
                "rtl/effects/rf-rf-bins12",
                "reports/SXT-028h",
                "tests/test_sxt028h.py"):
        assert os.path.exists(os.path.join(REPO, rel)), rel
    carrier_paths = {c["path"] for c in spec["carriers"]["top_presets"]}
    import extract_rf_bins12_inputs as ex
    assert {c["path"] for c in ex.CARRIERS} == carrier_paths


# --------------------------------------------------------------------------
# committed evidence records (fail-closed; never a false pass)
# --------------------------------------------------------------------------

def test_revision_pin_refuses_a_stale_harness():
    """Unit-level guard for the stale-stub control (needs no iverilog)."""
    import compare_rtl_model_rf_bins12 as cmp_rtl
    live = rm.model_revision()
    assert cmp_rtl.revision_pin_ok(live) is True
    assert cmp_rtl.revision_pin_ok(None) is True     # no pin asserted
    assert cmp_rtl.revision_pin_ok(f"{int(live, 16) ^ 1:064x}") is False


def test_negative_controls_all_fail_their_checks():
    p = os.path.join(SXT, "negative-controls", "negative-controls.json")
    if not os.path.exists(p):
        pytest.skip("negative-controls.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == rm.model_revision(), "stale record"
    assert len(d["controls"]) == 5
    for c in d["controls"]:
        assert c["ok"] is True and "CONTROL-OK" in c["verdict"], c["control"]
        assert c["legs"], c["control"]
        for leg in c["legs"]:
            # a leg may be NOT_RUN (missing tool) but must never be BROKEN
            assert leg["status"] in ("CONTROL-OK", "NOT_RUN"), leg
    assert len({c["control"] for c in d["controls"]}) == 5
    adapted = [c for c in d["controls"]
               if c.get("coverage_label") == "ADAPTED"]
    assert adapted, "the generic-substitute control must be labeled ADAPTED"
    assert adapted[0]["counts_toward_original_preset_coverage"] is False


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == rm.model_revision(), "stale record"
    names = {c["case"] for c in d["cases"]}
    for required in ("both-slots-all-fx", "both-slots-scene-fx-only",
                     "bypass-no-fx-skips-block", "slot1-disabled-bit2",
                     "slot2-disabled-bit3", "tail-span-silent-input",
                     "slot1-reload-mid-tail", "panic-reset-mid-tail",
                     "random-control-stream"):
        assert required in names, required
    for c in d["cases"]:
        assert c["exact"] is True, c["case"]
        assert c["mismatches"] == 0, c["case"]
        assert c["revision_pin"]["ok"] is True, c["case"]
        assert c["checked"]["outputs"] == 64 * c["blocks"]
        assert c["checked"]["checkpoints"] == c["blocks"]
    tail = [c for c in d["cases"] if c["case"] == "tail-span-silent-input"][0]
    assert tail["tail"]["declared_tail_span_blocks"] >= 4
    assert tail["tail"]["blocks_with_nonzero_output"] == tail["blocks"]


def test_state_cost_record_no_external_memory_claimed():
    p = os.path.join(SXT, "artifacts", "state-cost.json")
    if not os.path.exists(p):
        pytest.skip("state-cost.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["external_writable_memory"]["words_total"] == 0
    assert d["external_traffic"]["words_per_sample"] == 0
    assert "PENDING-SXT-016" in d["ext_mem_traffic_estimate"]


def test_evidence_keeps_the_claims_separate():
    p = os.path.join(SXT, "EVIDENCE.md")
    if not os.path.exists(p):
        pytest.skip("EVIDENCE.md not committed (NOT_RUN)")
    text = open(p).read()
    assert "NOT_RUN" in text
    assert "oracle" in text.lower()
    assert "PENDING-SXT-016" in text
    assert "PROPOSED" in text            # budgets are not frozen
    # no support/quality claim may be asserted by this record
    low = text.lower()
    assert "preset-support claim" in low
    assert "musical-quality claim" in low
    assert "not_run** (oracle unavailable" in low   # budgets NOT_RUN, not PASS
