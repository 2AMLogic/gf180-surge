"""SXT-028j routing-form leaf tests (pytest): Global FX slots 3-4
(global3 -> global4, the extended rack half of the master global-FX chain).

Covers: the frozen arithmetic/schedule (the global-stage bypass partition,
the `fx_disable` bits 14/15, ring threading), the instance lifecycle
(patch-change reload mid-tail, slot-off, panic/reset), model determinism and
per-instance independence (including the real-corpus SAME-FX-class-in-both-
slots shape), the declared tail span, the declared seam with the landed
global1->global2 sibling leaf, generator consistency of the committed
carrier records (census+graphs cross-check, oracle-independent, fail-closed
on injected drift), negative-control evidence integrity, and the committed
RTL-exactness record (fail-closed on a stale model revision).

ORACLE-DEPENDENT LEGS (per-slot algorithm parameters, wet-audio fixture
renders, model-vs-reference agreement) are NOT run here: they are recorded
as refused/NOT_RUN and are never reported as a pass (AGENTS.md). The same
rule covers a missing iverilog: the RTL-exactness and negative-control
records are asserted only when committed, and a stale record
(model-revision drift) FAILS rather than silently passing.
"""
import copy
import json
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global34"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import rf_global34_model as rm  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028j")
FX_INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")
CARRIER_SLUGS = ("jigsaw", "pixel", "lazy", "string-contrabass", "bassoon")

COEFFS_A = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_B = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
            rm.to_q(-0.35, 29, 32), rm.to_q(0.18, 29, 32))
COEFFS_TAIL = (rm.to_q(0.06, 29, 32), 0, 0,
               rm.to_q(-1.90, 29, 32), rm.to_q(0.945, 29, 32))


def rand_block(rs, amp=0.3):
    return ([rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)],
            [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)])


def loaded_rack(c3=COEFFS_A, c4=COEFFS_B, fx_bypass=rm.FXB_ALL_FX,
                fx_disable=0, occ3=True, occ4=True):
    rack = rm.ExtendedGlobalRack()
    rack.apply_control(fx_bypass, fx_disable, occ3, True, c3, occ4, True, c4)
    return rack


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
    assert rm.FXSLOT_GLOBAL3 == 14 and rm.FXSLOT_GLOBAL4 == 15
    # the GLOBAL stage runs only in ALL_FX and NO_SENDS
    assert rm.GLOBAL_ACTIVE_MODES == (rm.FXB_ALL_FX, rm.FXB_NO_SENDS)
    assert rm.GLOBAL_CHAIN_ORDER == ("global1", "global2", "global3",
                                     "global4")
    assert rm.THIS_LEAF_ROLES == ("global3", "global4")


def test_slot_indices_agree_with_the_committed_corpus_role_table():
    """The slot indices are re-derived from an in-repo artifact (no live
    oracle): every graphs.jsonl record carries the pinned engine's slot
    order by patch fx[] index. Checked across the WHOLE corpus, not just the
    first record, because this leaf owns the highest two slot indices and a
    truncated fx[] list would otherwise go unnoticed."""
    path = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)["g"]
            roles = {fx["i"]: fx["r"] for fx in g["fx"]}
            assert roles[rm.FXSLOT_GLOBAL3] == "global3"
            assert roles[rm.FXSLOT_GLOBAL4] == "global4"
            # the landed sibling leaf's own pinned indices still hold
            assert roles[6] == "global1" and roles[7] == "global2"
            n += 1
    assert n > 3000, f"corpus unexpectedly small ({n} records)"


def test_global_stage_runs_only_in_all_fx_and_no_sends():
    rs = random.Random(1)
    il, ir = rand_block(rs)
    for mode in (rm.FXB_ALL_FX, rm.FXB_NO_SENDS):
        rack = loaded_rack(fx_bypass=mode)
        ol, orr, glob = rack.process_block(il, ir, True)
        assert (ol, orr) != (il, ir), f"mode {mode} must process the bus"
        assert glob is True
    for mode in (rm.FXB_SCENE_FX_ONLY, rm.FXB_NO_FX):
        rack = loaded_rack(fx_bypass=mode)
        ol, orr, glob = rack.process_block(il, ir, True)
        assert ol == il and orr == ir          # bus untouched
        assert glob is True                    # ring flag passes through
        assert rack.slot3.biquad.reg0 == [0, 0]   # no state advanced
        assert rack.slot4.biquad.reg0 == [0, 0]


def test_disable_bitmask_gates_the_named_slot_only():
    rs = random.Random(2)
    il, ir = rand_block(rs)
    ref = loaded_rack()
    ol_ref, orr_ref, _ = ref.process_block(il, ir, True)

    # disabling global3 (bit 14): global3 must be a no-op, global4 still runs
    g3off = loaded_rack(fx_disable=1 << rm.FXSLOT_GLOBAL3)
    ol1, orr1, _ = g3off.process_block(il, ir, True)
    only4 = loaded_rack(occ3=False)
    ol_exp, orr_exp, _ = only4.process_block(il, ir, True)
    assert (ol1, orr1) == (ol_exp, orr_exp)
    assert (ol1, orr1) != (ol_ref, orr_ref)

    # disabling global4 (bit 15)
    g4off = loaded_rack(fx_disable=1 << rm.FXSLOT_GLOBAL4)
    ol2, orr2, _ = g4off.process_block(il, ir, True)
    only3 = loaded_rack(occ4=False)
    ol_exp1, orr_exp1, _ = only3.process_block(il, ir, True)
    assert (ol2, orr2) == (ol_exp1, orr_exp1)

    # real-corpus shape (Bassoon.fxp): BOTH bits set -> full pass-through
    both = loaded_rack(fx_disable=(1 << rm.FXSLOT_GLOBAL3) |
                       (1 << rm.FXSLOT_GLOBAL4))
    ol3, orr3, _ = both.process_block(il, ir, True)
    assert ol3 == il and orr3 == ir

    # a bit belonging to ANOTHER slot (global1 = 6) must not gate this rack
    other = loaded_rack(fx_disable=1 << 6)
    ol4, orr4, _ = other.process_block(il, ir, True)
    assert (ol4, orr4) == (ol_ref, orr_ref)


def test_ring_not_live_is_a_no_op():
    rack = loaded_rack()
    rs = random.Random(4)
    il, ir = rand_block(rs)
    ol, orr, glob = rack.process_block(il, ir, False)
    assert ol == il and orr == ir and glob is False
    assert rack.slot3.biquad.reg0 == [0, 0]   # never touched
    assert rack.slot4.biquad.reg0 == [0, 0]


def test_unoccupied_slot_does_not_consume_the_ring_flag():
    """`glob` is reassigned only when a slot actually runs; an empty or
    disabled global3 must pass the upstream flag through to global4."""
    rack = loaded_rack(occ3=False)
    rs = random.Random(5)
    il, ir = rand_block(rs)
    ol, orr, glob = rack.process_block(il, ir, True)
    assert glob is True
    assert rack.slot3.biquad.reg0 == [0, 0]
    assert rack.slot4.biquad.reg0 != [0, 0]   # global4 still ran


# --------------------------------------------------------------------------
# per-instance state and lifecycle
# --------------------------------------------------------------------------

def test_dual_instance_independent_histories():
    rack = loaded_rack()
    rs = random.Random(3)
    for _ in range(20):
        il, ir = rand_block(rs)
        rack.process_block(il, ir, True)
    assert rack.slot3.biquad is not rack.slot4.biquad
    assert rack.slot3.biquad.reg0 != rack.slot4.biquad.reg0
    assert rack.slot3.biquad.reg1 != rack.slot4.biquad.reg1


def test_same_class_slots_still_keep_independent_histories():
    """The real-corpus shape (String Contrabass.fxp: Airwindows Galactic in
    BOTH global3 and global4). Identical arithmetic in both slots is exactly
    where a pooled-state implementation hides best."""
    rack = loaded_rack(c3=COEFFS_A, c4=COEFFS_A)
    rs = random.Random(21)
    for _ in range(12):
        il, ir = rand_block(rs)
        rack.process_block(il, ir, True)
    assert rack.slot3.biquad is not rack.slot4.biquad
    # the two instances see DIFFERENT inputs (slot4 sees slot3's output), so
    # identical coefficients must still leave different histories
    assert rack.slot3.biquad.reg0 != rack.slot4.biquad.reg0


def test_patch_change_mid_tail_clears_only_that_slot():
    """`loadFx()` on global3 mid-tail installs a fresh instance for global3
    ONLY: global4's history (and the ring flag) survive."""
    rack = loaded_rack(c3=COEFFS_TAIL)
    rs = random.Random(6)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        rack.process_block(il, ir, True)
    assert rack.slot3.biquad.reg0 != [0, 0]
    before4 = copy.deepcopy(rack.slot4.biquad.reg0)
    assert before4 != [0, 0]

    rack.apply_control(rm.FXB_ALL_FX, 0, True, True, COEFFS_A,
                       True, False, COEFFS_B)
    assert rack.slot3.biquad.reg0 == [0, 0]      # fresh instance
    assert rack.slot4.biquad.reg0 == before4     # sibling untouched
    assert rack.slot3.biquad.coeffs == COEFFS_A  # new coefficients adopted


def test_slot_off_mid_tail_releases_only_that_instance():
    rack = loaded_rack(c3=COEFFS_TAIL)
    rs = random.Random(7)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        rack.process_block(il, ir, True)
    before3 = copy.deepcopy(rack.slot3.biquad.reg0)
    rack.apply_control(rm.FXB_ALL_FX, 0, True, False, COEFFS_TAIL,
                       False, False, COEFFS_B)
    assert rack.slot4.occupied is False
    assert rack.slot4.biquad.reg0 == [0, 0]
    assert rack.slot3.biquad.reg0 == before3


def test_panic_reset_clears_both_instances_and_the_ring_memory():
    rack = loaded_rack(c3=COEFFS_TAIL)
    rs = random.Random(8)
    for _ in range(3):
        il, ir = rand_block(rs, 0.05)
        rack.process_block(il, ir, True)
    assert rack.glob_ring is True
    rack.panic_reset()
    assert rack.checkpoint() == ((0, 0), (0, 0), (0, 0), (0, 0))
    assert rack.glob_ring is False
    assert rack.slot3.occupied and rack.slot4.occupied   # patch still loaded


def test_coefficient_change_without_reload_keeps_state():
    rack = loaded_rack()
    rs = random.Random(9)
    for _ in range(2):
        il, ir = rand_block(rs)
        rack.process_block(il, ir, True)
    keep = copy.deepcopy(rack.slot3.biquad.reg0)
    rack.apply_control(rm.FXB_ALL_FX, 0, True, False, COEFFS_B,
                       True, False, COEFFS_A)
    assert rack.slot3.biquad.reg0 == keep
    assert rack.slot3.biquad.coeffs == COEFFS_B


def test_lifecycle_runs_even_while_the_stage_is_bypassed():
    """The engine's load/unload path is control-rate: a slot-off issued while
    fx_bypass skips the global stage must still release the instance."""
    rack = loaded_rack(c3=COEFFS_TAIL)
    rs = random.Random(10)
    for _ in range(2):
        il, ir = rand_block(rs, 0.05)
        rack.process_block(il, ir, True)
    assert rack.slot4.biquad.reg0 != [0, 0]
    rack.apply_control(rm.FXB_NO_FX, 0, True, False, COEFFS_TAIL,
                       False, False, COEFFS_B)
    assert rack.slot4.occupied is False
    assert rack.slot4.biquad.reg0 == [0, 0]


def test_model_determinism():
    runs = []
    for _ in range(2):
        rack = loaded_rack()
        rs = random.Random(11)
        out = []
        glob = True
        for _b in range(10):
            il, ir = rand_block(rs)
            ol, orr, glob = rack.process_block(il, ir, glob)
            out.append((ol, orr, glob))
        runs.append((out, rack.checkpoint()))
    assert runs[0] == runs[1]


# --------------------------------------------------------------------------
# declared seam with the landed global1 -> global2 segment
# --------------------------------------------------------------------------

def test_seam_composes_with_the_landed_global12_segment():
    """The declared seam: this leaf consumes the bus and ring flag the
    landed sibling leaf (model/effects/rf-rf-global2/, SXT-028d) produced.
    Composing the two landed models gives the full four-slot global chain,
    and all FOUR instances must keep independent histories."""
    sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global2"))
    import rf_global2_model as up   # noqa: PLC0415

    # the two leaves must agree about the slot table they share
    assert up.FXSLOT_GLOBAL1 == 6 and up.FXSLOT_GLOBAL2 == 7
    assert (rm.FXSLOT_GLOBAL3, rm.FXSLOT_GLOBAL4) == (14, 15)
    # ... and about the bus/coefficient word formats at the seam
    assert (up.A_FRAC, up.A_BITS) == (rm.A_FRAC, rm.A_BITS)
    assert (up.C_FRAC, up.C_BITS) == (rm.C_FRAC, rm.C_BITS)

    upstream = up.RoutingState()
    upstream.slot1.load(*COEFFS_A)
    upstream.slot2.load(*COEFFS_B)
    rack = loaded_rack(c3=COEFFS_B, c4=COEFFS_A)

    rs = random.Random(12)
    glob = True
    chain_out = []
    for _b in range(8):
        il, ir = rand_block(rs)
        ul, ur, glob = upstream.process_block(il, ir, glob)
        ol, orr, glob = rack.process_block(ul, ur, glob)
        chain_out.append((ol, orr))

    # the chain really did something at every stage
    assert any(v != 0 for ol, orr in chain_out for v in ol + orr)
    histories = [tuple(upstream.slot1.biquad.reg0),
                 tuple(upstream.slot2.biquad.reg0),
                 tuple(rack.slot3.biquad.reg0),
                 tuple(rack.slot4.biquad.reg0)]
    assert all(h != (0, 0) for h in histories)
    assert len(set(histories)) == 4, "four slots must keep FOUR histories"

    # and the seam is ordered: swapping which segment runs first changes the
    # result (the chain is not commutative across the seam)
    upstream2 = up.RoutingState()
    upstream2.slot1.load(*COEFFS_A)
    upstream2.slot2.load(*COEFFS_B)
    rack2 = loaded_rack(c3=COEFFS_B, c4=COEFFS_A)
    rs = random.Random(12)
    glob = True
    swapped_out = []
    for _b in range(8):
        il, ir = rand_block(rs)
        ol, orr, glob = rack2.process_block(il, ir, glob)
        ul, ur, glob = upstream2.process_block(ol, orr, glob)
        swapped_out.append((ul, ur))
    assert swapped_out != chain_out


# --------------------------------------------------------------------------
# declared tail span
# --------------------------------------------------------------------------

def test_declared_tail_span_carries_audio_and_truncation_loses_it():
    """With the ring flag still live and the input gone silent, the
    occupant's registers must keep producing audio across the declared tail
    span; a render truncated at the end of the input drops real samples."""
    import compare_rtl_model_rf_global34 as cmp_rtl
    signal = cmp_rtl.TAIL_SIGNAL_BLOCKS
    span = cmp_rtl.TAIL_SPAN_BLOCKS
    rack = loaded_rack(c3=COEFFS_TAIL)
    rs = random.Random(13)
    tail_energy = []
    for b in range(signal + span):
        il, ir = (rand_block(rs, 0.05) if b < signal
                  else ([0] * rm.BLOCK, [0] * rm.BLOCK))
        ol, orr, _ = rack.process_block(il, ir, True)
        if b >= signal:
            tail_energy.append(sum(abs(v) for v in ol + orr))
    assert len(tail_energy) == span
    assert all(e > 0 for e in tail_energy), tail_energy
    # decaying: the last tail block is much quieter than the first
    assert tail_energy[-1] < tail_energy[0]


def test_reset_mid_tail_kills_the_tail():
    rack = loaded_rack(c3=COEFFS_TAIL)
    rs = random.Random(14)
    for _ in range(2):
        il, ir = rand_block(rs, 0.05)
        rack.process_block(il, ir, True)
    rack.panic_reset()
    ol, orr, _ = rack.process_block([0] * rm.BLOCK, [0] * rm.BLOCK, True)
    assert all(v == 0 for v in ol + orr)


def test_no_external_memory_traffic_from_this_leaf():
    rack = loaded_rack()
    rs = random.Random(15)
    for _ in range(4):
        il, ir = rand_block(rs)
        rack.process_block(il, ir, True)
    for slot in (rack.slot3, rack.slot4):
        assert slot.ext_reads == 0 and slot.ext_writes == 0


# --------------------------------------------------------------------------
# generator consistency / fail-closed extraction
# --------------------------------------------------------------------------

def test_carrier_records_match_the_extractor_output():
    """Committed carrier records must be exactly what the extractor produces
    now (no stale artifact, no hand edit)."""
    import extract_rf_global34_inputs as ex
    for carrier in ex.CARRIERS:
        path = os.path.join(FX_INPUTS,
                            f"rf-rf-global34-{carrier['slug']}.json")
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
        assert od == fr, (f"{path} is stale - regenerate with "
                          "`python3 tools/extract_rf_global34_inputs.py`")


def test_extraction_records_fail_closed():
    for slug in CARRIER_SLUGS:
        d = json.load(open(os.path.join(FX_INPUTS,
                                        f"rf-rf-global34-{slug}.json")))
        assert d["leaf"] == "SXT-028j"
        assert d["roles"] == ["global3", "global4"]
        assert d["applicability"]["routing_metadata_verified"] is True
        assert d["preset"]["census_blob_sha1_verified"] == \
            d["preset"]["graphs_blob_sha1_verified"]
        assert d["cross_check"]["census_vs_graphs_drift_count"] == 0
        assert d["slot_index_check"]["verified_indices"]["14"] == "global3"
        assert d["slot_index_check"]["verified_indices"]["15"] == "global4"
        # return_level is stored per slot but not consumed by the global path
        assert d["global3"]["return_level_consumed_by_global_path"] is False
        # oracle-dependent leg is honestly refused in this environment, not
        # fabricated as a pass
        assert d["oracle_extraction"]["attempted"] is True
        if not d["oracle_extraction"]["ok"]:
            assert d["applicability"]["complete_wet_render_possible"] is False


def test_issue_named_carriers_do_not_cover_the_dual_instance_shape():
    """A finding this leaf must not paper over: all three B4-scope carriers
    the issue names occupy global3 ONLY, so none of them exercises the
    concurrent dual-instance shape the acceptance checklist requires. The
    two added shape carriers do."""
    named = {}
    for slug in ("jigsaw", "pixel", "lazy"):
        d = json.load(open(os.path.join(FX_INPUTS,
                                        f"rf-rf-global34-{slug}.json")))
        assert "issue-named" in d["carrier_source"]
        named[slug] = d
        assert d["global3"]["occupied"] is True
        assert d["global4"]["occupied"] is False
        assert d["dual_instance_concurrent"] is False
    contrabass = json.load(open(os.path.join(
        FX_INPUTS, "rf-rf-global34-string-contrabass.json")))
    assert "added by this leaf" in contrabass["carrier_source"]
    assert contrabass["dual_instance_concurrent"] is True
    assert contrabass["same_class_both_slots"] is True
    assert contrabass["global3"]["airwindows_sub_id"] == \
        contrabass["global4"]["airwindows_sub_id"]
    bassoon = json.load(open(os.path.join(FX_INPUTS,
                                          "rf-rf-global34-bassoon.json")))
    assert bassoon["dual_instance_concurrent"] is True
    assert bassoon["both_slots_disabled"] is True
    assert bassoon["patch_level"]["fx_disable_mask"] == (1 << 14) | (1 << 15)


def test_extraction_refuses_injected_drift():
    """Live control for the fail-closed claim: a census/graphs disagreement,
    a blob-sha mismatch, and a corrupted slot-index/role table must all
    REFUSE, not be papered over."""
    import extract_rf_global34_inputs as ex
    carrier = ex.CARRIERS[0]
    row = ex.census_row(carrier["path"])
    graph = ex.graphs_entry(carrier["path"])
    ex.cross_check(row, graph)          # clean pair passes
    ex.role_index_check(graph)          # clean role table passes

    bad = dict(row)
    bad["stored_fx_disable"] = "49152"  # drift in fx_disable
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad, graph)

    bad2 = dict(row)
    bad2["stored_nonoff_fx_slot_count"] = "99"
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad2, graph)

    bad_graph = copy.deepcopy(graph)
    for fx in bad_graph["g"]["fx"]:
        if fx["r"] == "global4":
            fx["i"] = 13               # wrong slot index
    with pytest.raises(ex.Refuse):
        ex.role_index_check(bad_graph)

    with pytest.raises(ex.Refuse):
        ex.extract_one({"slug": "x", "path": carrier["path"],
                        "declared_sha1": "0" * 40,
                        "carrier_source": "test"})


def test_leaf_spec_declares_this_routing_form():
    """Generator consistency: the committed leaf spec names exactly the roles
    and deliverable paths this leaf implements, and every issue-named carrier
    is covered by the extractor."""
    spec = json.load(open(os.path.join(REPO, "reports", "sxt-028", "leaves",
                                       "SXT-028j.json")))
    assert spec["leaf_id"] == "SXT-028j"
    assert spec["feature"]["roles"] == ["global3", "global4"]
    assert spec["feature"]["routing_form"] == "rf-global34"
    for rel in ("model/effects/rf-rf-global34",
                "rtl/effects/rf-rf-global34",
                "reports/SXT-028j",
                "tests/test_sxt028j.py"):
        assert os.path.exists(os.path.join(REPO, rel)), rel
    spec_paths = {c["path"] for c in spec["carriers"]["top_presets"]}
    import extract_rf_global34_inputs as ex
    tool_paths = {c["path"] for c in ex.CARRIERS}
    # every issue-named carrier must be extracted; extra shape carriers are
    # allowed but must be labeled as additions
    assert spec_paths <= tool_paths
    for c in ex.CARRIERS:
        if c["path"] not in spec_paths:
            assert c["carrier_source"].startswith("added by this leaf")


def test_corpus_occupancy_record_is_coverage_not_support():
    p = os.path.join(SXT, "artifacts", "corpus-occupancy.json")
    if not os.path.exists(p):
        pytest.skip("corpus-occupancy.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert "NOT a support claim" in d["claim_scope"]
    assert d["presets_scanned"] > 3000
    # the dual-instance shape this leaf claims really exists in the corpus
    assert d["both_slots_occupied"] > 0
    assert d["both_slots_occupied_same_fx_class"] > 0
    assert d["fx_disable_both_bits_set"] > 0


# --------------------------------------------------------------------------
# committed evidence records (fail-closed; never a false pass)
# --------------------------------------------------------------------------

def test_revision_pin_refuses_a_stale_harness():
    """Unit-level guard for the stale-stub control (needs no iverilog)."""
    import compare_rtl_model_rf_global34 as cmp_rtl
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
    # the shared-state control must also cover the same-class shape
    shared = [c for c in d["controls"] if c["control"].startswith("NC-D")][0]
    assert any("SAME-class" in leg["leg"] for leg in shared["legs"])


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == rm.model_revision(), "stale record"
    names = {c["case"] for c in d["cases"]}
    for required in ("both-slots-all-fx", "both-slots-no-sends",
                     "bypass-scene-fx-only-skips-block",
                     "bypass-no-fx-skips-block", "slot3-disabled-bit14",
                     "slot4-disabled-bit15", "both-slots-disabled-bits14-15",
                     "same-class-dual-occupants", "tail-span-silent-input",
                     "slot3-reload-mid-tail", "slot4-off-mid-tail",
                     "panic-reset-mid-tail", "saturating-full-scale",
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
    same = [c for c in d["cases"]
            if c["case"] == "same-class-dual-occupants"][0]
    assert same["dual_instance"]["identical_coefficients_in_both_slots"]
    assert same["dual_instance"]["final_histories_differ"] is True


def test_oracle_status_record_is_measured_not_asserted():
    p = os.path.join(SXT, "artifacts", "oracle-status.json")
    if not os.path.exists(p):
        pytest.skip("oracle-status.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["oracle_status"] in ("AVAILABLE", "UNAVAILABLE")
    assert d["legs"], "the oracle-gated legs must be enumerated"
    for name, legrec in d["legs"].items():
        if d["oracle_status"] == "UNAVAILABLE":
            assert legrec["status"] == "NOT_RUN", name
            assert legrec["reason"], name
        else:
            assert legrec["status"] in ("RUNNABLE", "NOT_RUN"), name
    # the probe must record what it actually found, not a bare assertion
    assert "surgepy_importable" in d["probe"]
    assert "engine_dir_present" in d["probe"]


def test_state_cost_record_no_external_memory_claimed():
    p = os.path.join(SXT, "artifacts", "state-cost.json")
    if not os.path.exists(p):
        pytest.skip("state-cost.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["external_writable_memory"]["words_total"] == 0
    assert d["external_traffic"]["words_per_sample"] == 0
    assert "PENDING-SXT-016" in d["ext_mem_traffic_estimate"]
    assert d["cost_closure"]["status"] == "[PENDING-SXT-016]"
    assert d["model_revision"] == rm.model_revision(), "stale record"
    # the derived inventory must match the frozen model's own word widths
    per = d["on_chip_small_state"]["per_instance"]
    assert per["tdf2_history_bits"] == 4 * rm.R_BITS
    assert per["coefficient_register_bits"] == 5 * rm.C_BITS


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
