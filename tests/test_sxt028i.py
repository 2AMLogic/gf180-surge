"""SXT-028i routing-form leaf tests (pytest): Scene-A insert FX bus, slots 3-4
(ains3 -> ains4, the extended rack half).

Covers: the frozen arithmetic/schedule (the insert-stage bypass partition, the
`fx_disable` bitmask at its EXTENDED-rack bit positions 8/9, ring-out
threading), the instance lifecycle (patch-change reload mid-tail, slot-off,
panic/reset), model determinism and per-instance independence, the declared
tail span, generator consistency of the committed carrier records (census +
graphs cross-check plus the leaf's own B4-scope candidate gate,
oracle-independent, fail-closed on injected drift), negative-control evidence
integrity, and the committed RTL-exactness record (fail-closed on a stale
model revision).

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
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-ains34"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import rf_ains34_model as rm  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028i")
FX_INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")
CARRIER_SLUGS = ("jigsaw", "resurrection", "pixel", "sand-storm",
                 "brass-ensemble")

COEFFS_A = (rm.to_q(0.37, 29, 32), rm.to_q(-0.21, 29, 32),
            rm.to_q(0.11, 29, 32), rm.to_q(0.28, 29, 32),
            rm.to_q(-0.09, 29, 32))
COEFFS_B = (rm.to_q(0.24, 29, 32), rm.to_q(0.33, 29, 32),
            rm.to_q(-0.14, 29, 32), rm.to_q(-0.31, 29, 32),
            rm.to_q(0.22, 29, 32))
COEFFS_TAIL = (rm.to_q(0.06, 29, 32), 0, 0,
               rm.to_q(-1.90, 29, 32), rm.to_q(0.945, 29, 32))


def rand_block(rs, amp=0.3):
    return ([rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)])


def loaded_bus(c3=COEFFS_A, c4=COEFFS_B, fx_bypass=rm.FXB_ALL_FX,
               fx_disable=0, occ3=True, occ4=True):
    bus = rm.SceneAExtendedInsertBus()
    bus.apply_control(fx_bypass, fx_disable, occ3, True, c3, occ4, True, c4)
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
    # EXTENDED rack half: these are slots 8/9, NOT the base half's 0/1
    assert rm.FXSLOT_AINS3 == 8 and rm.FXSLOT_AINS4 == 9
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
    assert roles[rm.FXSLOT_AINS3] == "ains3"
    assert roles[rm.FXSLOT_AINS4] == "ains4"
    # the base half of the SAME scene-A chain is upstream of this leaf and is
    # a declared scope omission -- pinned here only so the composition is
    # visible in the role table
    assert roles[0] == "ains1" and roles[1] == "ains2"
    # and the landed sibling routing leaves' own pinned indices still hold
    assert roles[2] == "bins1" and roles[3] == "bins2"
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
    assert bus.slot3.biquad.reg0 == [0, 0]  # no state was advanced
    assert bus.slot4.biquad.reg0 == [0, 0]


def test_disable_bitmask_gates_the_named_slot_only():
    rs = random.Random(2)
    il, ir = rand_block(rs)
    ref = loaded_bus()
    ol_ref, orr_ref, _ = ref.process_block(il, ir, True)

    # disabling ains3 (bit 8): ains3 must be a no-op, ains4 must still run.
    # This is the real Brass Ensemble.fxp shape (fx_disable = 256).
    a3off = loaded_bus(fx_disable=1 << rm.FXSLOT_AINS3)
    ol1, orr1, _ = a3off.process_block(il, ir, True)
    only4 = loaded_bus(occ3=False)
    ol_exp, orr_exp, _ = only4.process_block(il, ir, True)
    assert (ol1, orr1) == (ol_exp, orr_exp)
    assert (ol1, orr1) != (ol_ref, orr_ref)

    # disabling ains4 (bit 9)
    a4off = loaded_bus(fx_disable=1 << rm.FXSLOT_AINS4)
    ol2, orr2, _ = a4off.process_block(il, ir, True)
    only3 = loaded_bus(occ4=False)
    ol_exp1, orr_exp1, _ = only3.process_block(il, ir, True)
    assert (ol2, orr2) == (ol_exp1, orr_exp1)

    # both extended-half bits (the Brassy Pad / Eww Gross shape): pure
    # pass-through even though both slots are occupied
    both = loaded_bus(fx_disable=(1 << rm.FXSLOT_AINS3) |
                      (1 << rm.FXSLOT_AINS4))
    ol3, orr3, sc3 = both.process_block(il, ir, True)
    assert ol3 == il and orr3 == ir and sc3 is True


def test_every_other_slot_disable_bit_does_not_gate_this_bus():
    """Bit-layout control. This leaf's bits moved to 8/9 (extended rack half),
    so a mask with EVERY other slot bit set must leave this bus ungated -- an
    off-by-N bit-layout error would show up here."""
    rs = random.Random(3)
    il, ir = rand_block(rs)
    ref = loaded_bus()
    ol_ref, orr_ref, _ = ref.process_block(il, ir, True)
    others = 0xFFFF & ~((1 << rm.FXSLOT_AINS3) | (1 << rm.FXSLOT_AINS4))
    bus = loaded_bus(fx_disable=others)
    ol, orr, _ = bus.process_block(il, ir, True)
    assert (ol, orr) == (ol_ref, orr_ref)
    # and the base half's own bits (0/1) in particular do not gate this leaf
    for bit in (0, 1):
        b = loaded_bus(fx_disable=1 << bit)
        obl, obr, _ = b.process_block(il, ir, True)
        assert (obl, obr) == (ol_ref, orr_ref)


def test_scene_not_live_is_a_no_op():
    bus = loaded_bus()
    rs = random.Random(4)
    il, ir = rand_block(rs)
    ol, orr, sc = bus.process_block(il, ir, False)
    assert ol == il and orr == ir and sc is False
    assert bus.slot3.biquad.reg0 == [0, 0]   # never touched
    assert bus.slot4.biquad.reg0 == [0, 0]


# --------------------------------------------------------------------------
# per-instance state and lifecycle
# --------------------------------------------------------------------------

def test_dual_instance_independent_histories():
    bus = loaded_bus()
    rs = random.Random(3)
    for _ in range(20):
        il, ir = rand_block(rs)
        bus.process_block(il, ir, True)
    assert bus.slot3.biquad is not bus.slot4.biquad
    assert bus.slot3.biquad.reg0 != bus.slot4.biquad.reg0
    assert bus.slot3.biquad.reg1 != bus.slot4.biquad.reg1


def test_shared_arithmetic_kernel_with_independent_state():
    """The two instances deliberately share the SAME arithmetic kernel class
    while owning disjoint state (AGENTS.md). Both halves of that sentence are
    asserted, so a future refactor cannot quietly pool the registers."""
    bus = loaded_bus()
    assert type(bus.slot3.biquad) is type(bus.slot4.biquad)
    assert bus.slot3.biquad.reg0 is not bus.slot4.biquad.reg0
    assert bus.slot3.biquad.reg1 is not bus.slot4.biquad.reg1
    rs = random.Random(31)
    for _ in range(5):
        il, ir = rand_block(rs)
        bus.process_block(il, ir, True)
    # mutating one instance's state must not touch the other's
    snapshot4 = copy.deepcopy(bus.slot4.biquad.reg0)
    bus.slot3.biquad.reset()
    assert bus.slot4.biquad.reg0 == snapshot4


def test_patch_change_mid_tail_clears_only_that_slot():
    """`loadFx()` on ains3 mid-tail installs a fresh instance for ains3 ONLY:
    ains4's history (and the scene ring flag) survive."""
    bus = loaded_bus(c3=COEFFS_TAIL)
    rs = random.Random(5)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        bus.process_block(il, ir, True)
    assert bus.slot3.biquad.reg0 != [0, 0]
    before4 = copy.deepcopy(bus.slot4.biquad.reg0)
    assert before4 != [0, 0]

    # reload ains3 only
    bus.apply_control(rm.FXB_ALL_FX, 0, True, True, COEFFS_A,
                      True, False, COEFFS_B)
    assert bus.slot3.biquad.reg0 == [0, 0]      # fresh instance
    assert bus.slot4.biquad.reg0 == before4     # sibling untouched
    assert bus.slot3.biquad.coeffs == COEFFS_A  # new coefficients adopted
    assert bus.sc_ring is True                  # ring flag NOT cleared


def test_slot_off_mid_tail_releases_only_that_instance():
    bus = loaded_bus(c3=COEFFS_TAIL)
    rs = random.Random(6)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        bus.process_block(il, ir, True)
    before3 = copy.deepcopy(bus.slot3.biquad.reg0)
    bus.apply_control(rm.FXB_ALL_FX, 0, True, False, COEFFS_TAIL,
                      False, False, COEFFS_B)
    assert bus.slot4.occupied is False
    assert bus.slot4.biquad.reg0 == [0, 0]
    assert bus.slot3.biquad.reg0 == before3


def test_panic_reset_clears_both_instances_and_the_ring_memory():
    bus = loaded_bus(c3=COEFFS_TAIL)
    rs = random.Random(7)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        bus.process_block(il, ir, True)
    assert bus.sc_ring is True
    bus.panic_reset()
    assert bus.checkpoint() == ((0, 0), (0, 0), (0, 0), (0, 0))
    assert bus.sc_ring is False
    assert bus.slot3.occupied and bus.slot4.occupied   # patch still loaded


def test_coefficient_change_without_reload_keeps_state():
    bus = loaded_bus()
    rs = random.Random(8)
    for _ in range(2):
        il, ir = rand_block(rs)
        bus.process_block(il, ir, True)
    keep = copy.deepcopy(bus.slot3.biquad.reg0)
    bus.apply_control(rm.FXB_ALL_FX, 0, True, False, COEFFS_B,
                      True, False, COEFFS_A)
    assert bus.slot3.biquad.reg0 == keep
    assert bus.slot3.biquad.coeffs == COEFFS_B


def test_lifecycle_runs_even_while_the_audio_stage_is_bypassed():
    """The engine's load/unload path is control-rate: a reload pulse while
    `fx_bypass == no_fx` still installs a fresh instance."""
    bus = loaded_bus(c3=COEFFS_TAIL)
    rs = random.Random(9)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        bus.process_block(il, ir, True)
    assert bus.slot3.biquad.reg0 != [0, 0]
    bus.apply_control(rm.FXB_NO_FX, 0, True, True, COEFFS_A,
                      True, False, COEFFS_B)
    assert bus.slot3.biquad.reg0 == [0, 0]
    assert bus.slot3.biquad.coeffs == COEFFS_A


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
    import compare_rtl_model_rf_ains34 as cmp_rtl
    signal = cmp_rtl.TAIL_SIGNAL_BLOCKS
    span = cmp_rtl.TAIL_SPAN_BLOCKS
    bus = loaded_bus(c3=COEFFS_TAIL)
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
    bus = loaded_bus(c3=COEFFS_TAIL)
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
    for slot in (bus.slot3, bus.slot4):
        assert slot.ext_reads == 0 and slot.ext_writes == 0


# --------------------------------------------------------------------------
# generator consistency / fail-closed extraction
# --------------------------------------------------------------------------

def test_carrier_records_match_the_extractor_output():
    """Committed carrier records must be exactly what the extractor produces
    now (no stale artifact, no hand edit)."""
    import extract_rf_ains34_inputs as ex
    for carrier in ex.CARRIERS:
        path = os.path.join(FX_INPUTS, f"rf-rf-ains34-{carrier['slug']}.json")
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
                          "`python3 tools/extract_rf_ains34_inputs.py`")


def test_extraction_records_fail_closed():
    for slug in CARRIER_SLUGS:
        d = json.load(open(os.path.join(FX_INPUTS,
                                        f"rf-rf-ains34-{slug}.json")))
        assert d["leaf"] == "SXT-028i" and d["roles"] == ["ains3", "ains4"]
        assert d["applicability"]["routing_metadata_verified"] is True
        assert d["preset"]["census_blob_sha1_verified"] == \
            d["preset"]["graphs_blob_sha1_verified"]
        assert d["preset"]["leaf_b4_candidate_sha1_verified"] == \
            d["preset"]["census_blob_sha1_verified"]
        assert d["cross_check"]["census_vs_graphs_drift_count"] == 0
        # scene A exists in every scene mode -- unlike the sibling bins leaf
        assert d["scene_context"]["scene_a_instantiated"] is True
        # return_level is stored per slot but not consumed by the insert path
        assert d["ains3"]["return_level_consumed_by_insert_path"] is False
        assert d["ains4"]["return_level_consumed_by_insert_path"] is False
        # oracle-dependent leg is honestly refused in this environment, not
        # fabricated as a pass
        assert d["oracle_extraction"]["attempted"] is True
        if not d["oracle_extraction"]["ok"]:
            assert d["applicability"]["complete_wet_render_possible"] is False


def test_carrier_set_covers_the_shapes_this_leaf_claims():
    """The three issue-named carriers each occupy only ONE of ains3/ains4, so
    the carrier set must also carry a concurrent dual-occupancy preset and a
    routing-level-disabled preset, both drawn from this leaf's own B4-scope
    candidate list."""
    def rec(slug):
        return json.load(open(os.path.join(FX_INPUTS,
                                           f"rf-rf-ains34-{slug}.json")))

    # named-by-issue carriers: single-occupied shapes
    for slug, occ3, occ4 in (("jigsaw", False, True),
                             ("resurrection", False, True),
                             ("pixel", True, False)):
        d = rec(slug)
        assert "named" in d["carrier_source"]
        assert d["ains3"]["occupied"] is occ3
        assert d["ains4"]["occupied"] is occ4
        assert d["dual_instance_concurrent"] is False

    # added carriers: the dual-occupancy and disabled-slot shapes
    sand = rec("sand-storm")
    assert "added by this leaf" in sand["carrier_source"]
    assert sand["dual_instance_concurrent"] is True
    assert sand["ains3"]["type_name"] != sand["ains4"]["type_name"], \
        "two DIFFERENT occupant classes is the shared-arithmetic case"
    assert sand["ains3"]["fx_disable_bit"] is False
    assert sand["ains4"]["fx_disable_bit"] is False

    brass = rec("brass-ensemble")
    assert "added by this leaf" in brass["carrier_source"]
    assert brass["dual_instance_concurrent"] is True
    # fx_disable = 256 == bit 8 == ains3 disabled while occupied
    assert brass["patch_level"]["fx_disable_mask"] == 1 << rm.FXSLOT_AINS3
    assert brass["ains3"]["fx_disable_bit"] is True
    assert brass["ains4"]["fx_disable_bit"] is False


def test_extraction_refuses_injected_drift():
    """Live control for the fail-closed claim: a census/graphs disagreement, a
    blob-sha mismatch and an out-of-scope preset must all REFUSE, not be
    papered over."""
    import extract_rf_ains34_inputs as ex
    carrier = ex.CARRIERS[0]
    row = ex.census_row(carrier["path"])
    graph = ex.graphs_entry(carrier["path"])
    ex.cross_check(row, graph)          # clean pair passes

    bad = dict(row)
    bad["stored_fx_bypass"] = "3"       # drift in fx_bypass
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad, graph)

    bad2 = dict(row)
    bad2["stored_fx_disable"] = "512"   # drift in the ains4 disable bit
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad2, graph)

    bad3 = dict(row)
    bad3["stored_nonoff_fx_slot_count"] = "99"
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad3, graph)

    with pytest.raises(ex.Refuse):
        ex.extract_one({"slug": "x", "path": carrier["path"],
                        "declared_sha1": "0" * 40, "source": "test"})


def test_extraction_refuses_a_preset_outside_this_leafs_b4_scope():
    """A preset that is NOT one of this leaf's declared B4-scope candidates
    must be refused even when its census/graphs records are perfectly clean --
    carriers may not be pulled in from outside the leaf's declared scope."""
    import extract_rf_ains34_inputs as ex
    outside = "resources/data/patches_3rdparty/A.Liv/Leads/Novuo.fxp"
    row = ex.census_row(outside)        # exists and is clean in the census
    assert row["content_verified"] == "True"
    with pytest.raises(ex.Refuse):
        ex.b4_candidate(outside)
    with pytest.raises(ex.Refuse):
        ex.extract_one({"slug": "outside", "path": outside,
                        "declared_sha1": row["git_blob_sha1"],
                        "source": "test"})


def test_leaf_spec_declares_this_routing_form():
    """Generator consistency: the committed leaf spec names exactly the roles
    and deliverable paths this leaf implements, and every carrier the issue
    named is present in the extractor's carrier set."""
    spec = json.load(open(os.path.join(REPO, "reports", "sxt-028", "leaves",
                                       "SXT-028i.json")))
    assert spec["leaf_id"] == "SXT-028i"
    assert spec["feature"]["roles"] == ["ains3", "ains4"]
    assert spec["feature"]["routing_form"] == "rf-ains34"
    for rel in ("model/effects/rf-rf-ains34",
                "rtl/effects/rf-rf-ains34",
                "reports/SXT-028i",
                "tests/test_sxt028i.py"):
        assert os.path.exists(os.path.join(REPO, rel)), rel
    named = {c["path"] for c in spec["carriers"]["top_presets"]}
    import extract_rf_ains34_inputs as ex
    ours = {c["path"] for c in ex.CARRIERS}
    assert named <= ours, f"issue-named carriers missing: {named - ours}"
    # every extra carrier must come from this leaf's own B4-scope list
    for extra in ours - named:
        ex.b4_candidate(extra)


# --------------------------------------------------------------------------
# committed evidence records (fail-closed; never a false pass)
# --------------------------------------------------------------------------

def test_revision_pin_refuses_a_stale_harness():
    """Unit-level guard for the stale-stub control (needs no iverilog)."""
    import compare_rtl_model_rf_ains34 as cmp_rtl
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


def test_tail_control_has_a_live_rtl_leg_the_baseline_case_misses():
    """The dropped-tail control carries a live RTL mutant (stage skipped on a
    silent block). Its evidence value is that the TAIL case catches it while
    the non-silent baseline case does not -- that asymmetry is what makes the
    declared tail span load-bearing, so it is asserted rather than described."""
    p = os.path.join(SXT, "negative-controls", "negative-controls.json")
    if not os.path.exists(p):
        pytest.skip("negative-controls.json not committed (NOT_RUN)")
    d = json.load(open(p))
    tail = [c for c in d["controls"] if c["control"].startswith("NC-B")][0]
    rtl_legs = [l for l in tail["legs"] if "RTL" in l["leg"]]
    assert rtl_legs, "NC-B must carry a live RTL leg"
    leg = rtl_legs[0]
    if leg["status"] == "NOT_RUN":
        pytest.skip("live RTL tail mutant NOT_RUN (no iverilog)")
    m = leg["metrics"]
    assert m["case"] == "tail-span-silent-input"
    assert m["mismatches"] > 0, "the tail case must catch the tail-killing RTL"
    assert m["undetected_case_mismatches"] == 0, \
        "the baseline case is expected NOT to catch it; if it now does, the " \
        "asymmetry claim in reports/SXT-028i/EVIDENCE.md is stale"
    assert m["undetected_case_samples_compared"] > 0


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == rm.model_revision(), "stale record"
    names = {c["case"] for c in d["cases"]}
    for required in ("both-slots-all-fx", "both-slots-scene-fx-only",
                     "bypass-no-fx-skips-block", "ains3-disabled-bit8",
                     "ains4-disabled-bit9", "both-disabled-bits8and9",
                     "other-slot-disable-bits-do-not-gate",
                     "ains3-unoccupied-ains4-only",
                     "ains4-unoccupied-ains3-only",
                     "tail-span-silent-input", "slot3-reload-mid-tail",
                     "slot4-off-mid-tail", "panic-reset-mid-tail",
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


def test_rtl_exactness_record_is_not_vacuous():
    """Integer equality between two silently-zero traces would also read
    "exact". Every case that is SUPPOSED to produce audio must record nonzero
    output in every block, and the pass-through cases must record exactly the
    audio they were handed -- so a silent-stub model/RTL pair cannot satisfy
    this record on agreement alone."""
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    by_case = {c["case"]: c for c in d["cases"]}
    for name, c in by_case.items():
        assert "nonzero_output_blocks" in c, name
        assert c["nonzero_output_blocks"] > 0, f"{name} compares only silence"

    # Cases that must carry audio in EVERY block: the processing cases, and the
    # bypass/disable pass-through cases (whose output is the nonzero input).
    fully_audible = {
        "both-slots-all-fx", "both-slots-no-sends", "both-slots-scene-fx-only",
        "bypass-no-fx-skips-block", "ains3-disabled-bit8",
        "ains4-disabled-bit9", "both-disabled-bits8and9",
        "other-slot-disable-bits-do-not-gate", "ains4-unoccupied-ains3-only",
        "ains3-unoccupied-ains4-only", "scene-not-live-passthrough",
        "scene-live-goes-false-mid-run", "tail-span-silent-input",
        "slot4-off-mid-tail", "saturating-full-scale",
        "random-control-stream",
    }
    for name in fully_audible:
        c = by_case[name]
        assert c["nonzero_output_blocks"] == c["blocks"], name

    # The two lifecycle cases are DELIBERATELY silent after their event, and
    # that silence is itself the acceptance behavior (a fresh instance / a
    # panic kills the tail). Asserted positively, with the reason, so neither
    # the record nor the claim can drift:
    #   slot3-reload-mid-tail: ains3 is reloaded at block 3, so its own tail
    #     stops there; block 3 still carries audio because ains4's independent
    #     history is NOT cleared by a sibling slot's reload (that is the
    #     per-instance-isolation behavior), and blocks 4..7 are silent.
    #   panic-reset-mid-tail: state_reset fires BEFORE block 4, so blocks 0..3
    #     ring and blocks 4..7 are silent -- both instances dropped at once.
    for name, expected_nonzero in (("slot3-reload-mid-tail", 4),
                                   ("panic-reset-mid-tail", 4)):
        c = by_case[name]
        assert name not in fully_audible
        assert c["nonzero_output_blocks"] == expected_nonzero, name
        assert c["nonzero_output_blocks"] < c["blocks"], name
    assert set(by_case) == fully_audible | {"slot3-reload-mid-tail",
                                            "panic-reset-mid-tail"}


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
