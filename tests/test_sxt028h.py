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

# Corpus presets whose FX set includes types the two committed artifacts SPELL
# differently (census "FrequencyShifter"/"RingModulator" vs engine display
# "Freq Shift"/"Ring Mod"). Not carriers of this leaf -- they are the inputs
# to the issue #154 spelling-vs-content regression test below.
SPELLING_DIVERGENT_PRESETS = (
    "resources/data/patches_3rdparty/Kinsey Dulcet/Percussion/"
    "Closeout Sale @ Electro Percussion Warehouse.fxp",
    "resources/data/patches_3rdparty/Slowboat/FX/Random Bass FX.fxp",
)

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

    # a DIFFERENT FX in an occupied slot is CONTENT drift, not a spelling
    # difference, and must still refuse (issue #154: the type-set comparison
    # is now id-based, so this is the control that it did not go soft)
    table = ex.census_fx_table()
    bad_graph_type = copy.deepcopy(graph)
    on_slots = [fx for fx in bad_graph_type["g"]["fx"] if fx.get("on", 0)]
    present = {fx["t"] for fx in on_slots}
    on_slots[0]["t"] = next(i for i in range(1, len(table))
                            if i not in present)
    with pytest.raises(ex.Refuse):
        ex.cross_check(row, bad_graph_type)

    # an FX type id the census table cannot name is a REFUSAL too, never a
    # silently dropped slot
    unmappable = copy.deepcopy(graph)
    for fx in unmappable["g"]["fx"]:
        if fx.get("on", 0):
            fx["t"] = len(table)
            break
    with pytest.raises(ex.Refuse):
        ex.cross_check(row, unmappable)

    with pytest.raises(ex.Refuse):
        ex.extract_one({"slug": "x", "path": carrier["path"],
                        "declared_sha1": "0" * 40})


def test_cross_check_compares_fx_type_content_not_spelling():
    """Issue #154 regression: the census CSV and the normalized graph spell
    several FX types differently -- the census uses its own parser table
    ("FrequencyShifter", "RingModulator"), the graph carries the ENGINE's
    live display name ("Freq Shift", "Ring Mod") -- while naming the SAME
    stored type id. The cross-check must agree on content and must not refuse
    on spelling. The old space-strip-only NAME comparison is exercised inline
    as the live control: it must still disagree on these presets, otherwise
    this test would no longer be testing the hazard."""
    import extract_rf_bins12_inputs as ex
    table = ex.census_fx_table()
    assert table[7] == "FrequencyShifter" and table[13] == "RingModulator"

    saw_freq_shift = saw_ring_mod = False
    for rel in SPELLING_DIVERGENT_PRESETS:
        row = ex.census_row(rel)
        graph = ex.graphs_entry(rel)
        on_slots = [fx for fx in graph["g"]["fx"] if fx.get("on", 0)]
        display = {fx.get("tn") for fx in on_slots}
        ids = {fx.get("t") for fx in on_slots}
        saw_freq_shift |= 7 in ids and "Freq Shift" in display
        saw_ring_mod |= 13 in ids and "Ring Mod" in display

        census_names = sorted({"".join(t.split())
                               for t in row["stored_nonoff_fx_types"].split(";")
                               if t})
        old_graph_names = sorted({"".join(str(fx.get("tn")).split())
                                  for fx in on_slots})
        assert census_names != old_graph_names, (
            f"{rel} no longer exercises the spelling divergence this "
            f"regression test targets")

        rec = ex.cross_check(row, graph)     # must NOT refuse
        assert rec["census_vs_graphs_drift_count"] == 0
        assert rec["values"]["nonoff_fx_type_set"] == census_names
        assert rec["engine_display_names_context"] == sorted(display)
    assert saw_freq_shift, "FrequencyShifter/Freq Shift pair not exercised"
    assert saw_ring_mod, "RingModulator/Ring Mod pair not exercised"


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


# --------------------------------------------------------------------------
# #424: same-shape drift-zero carrier screen (tools/screen_rf_bins12_carriers.py)
#
# These tests check the COMMITTED live screen record for internal consistency
# and exercise the eligibility logic with mutation controls. They do not
# re-run the pinned oracle (that is the live screen; see EVIDENCE.md) and a
# drift-gate PASS never implies render eligibility.
# --------------------------------------------------------------------------

SCREEN_JSON = os.path.join(SXT, "artifacts", "carrier-drift-screen.json")


def _screen_modules():
    import carrier_drift_screen as cds
    import extract_rf_bins12_inputs as ex
    import screen_rf_bins12_carriers as scr
    return cds, ex, scr


def _graph_records():
    _cds, _ex, scr = _screen_modules()
    out = {}
    with open(os.path.join(REPO, "corpus", "normalized", "graphs.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            out[g["p"]] = g
    return out


def audit_screen_record(rec):
    """Raise AssertionError unless the screen record is self-consistent:
    complete denominator, per-candidate verdicts that agree with an
    INDEPENDENT recomputation from the recorded per-scene drift, and the
    selection equal to the deterministic rule."""
    cds, ex, scr = _screen_modules()
    assert rec["live"] is True and rec["status"] in ("PASS", "NO_VERDICT")
    for slug, shape in rec["shapes"].items():
        spec = scr.SHAPES[slug]
        run = shape["run"]
        cands = run["candidates"]
        assert run["live"] is True
        assert run["coverage"]["candidates_in_corpus"] == len(cands) \
            == spec["expected_count"]
        for c in cands:
            if not c["screened"]:
                continue
            gate, nat = c["determinism_gate"], c["native_state"]
            re = ex.recompute_drift_eligibility(
                nat["scene_mode_id"], nat["scene_active"],
                gate["drift_per_voicing_scene"])
            assert re["voicing_scenes"] == gate["voicing_scenes"], c["path"]
            assert re["drift_gate_eligible"] == (gate["status"] == "PASS"), \
                f"{c['path']}: recorded {gate['status']} disagrees with " \
                f"recomputed {re}"
        orig = shape["original"]
        oc = next(c for c in cands if c["path"] == spec["original_path"])
        assert orig["drift_eligible"] == (
            oc["determinism_gate"]["status"] == "PASS")
        assert shape["selection"]["selected_addition"] == \
            scr.select_replacement(spec["original_path"], cands)
    return True


def test_screen_record_is_complete_and_self_consistent():
    rec = json.load(open(SCREEN_JSON))
    assert audit_screen_record(rec) is True
    cds, ex, scr = _screen_modules()
    graphs = _graph_records()
    for slug, shape in rec["shapes"].items():
        spec = scr.SHAPES[slug]
        pred = scr.make_predicate(spec)
        # the denominator is exactly the corpus records matching the
        # predicate, in corpus order -- nothing sampled or dropped
        want = [p for p, g in graphs.items() if pred(g)]
        assert [m["path"] for m in shape["run"]["candidate_manifest"]] == want
        cov = shape["run"]["coverage"]
        assert cov["candidates_attempted"] == cov["candidates_screened"] \
            == len(want) and cov["candidates_refused"] == 0
        # every screened candidate carries its preset hash and native state
        for c in shape["run"]["candidates"]:
            assert c["graphs_blob_sha1"] == graphs[c["path"]]["sha"]
            assert c["native_state"]["bins1_type_id"] is not None
        # originals are preserved, with their historical nonzero drift
        # reproduced by the live screen (re-measured, not copied)
        assert shape["original"]["in_denominator"] is True
        assert shape["original"]["drift_gate"] == "FAIL"
        assert shape["original"]["drift_eligible"] is False
        assert shape["original"]["render_eligibility"] == "NOT_ESTABLISHED"


def test_declared_shapes_match_carriers_and_additions():
    cds, ex, scr = _screen_modules()
    rec = json.load(open(SCREEN_JSON))
    graphs = _graph_records()
    for c in ex.CARRIERS:
        spec = scr.SHAPES[c["shape_slug"]]
        assert spec["original_path"] == c["path"]
        assert spec["original_sha1"] == c["declared_sha1"]
        # the explicit predicate accepts the original's own graph record ...
        assert scr.make_predicate(spec)(graphs[c["path"]]) is True
        assert c["role"] == "original"
    # ... and rejects a one-field mutation of it (occupancy / bypass)
    for c in ex.CARRIERS:
        spec = scr.SHAPES[c["shape_slug"]]
        pred = scr.make_predicate(spec)
        g = copy.deepcopy(graphs[c["path"]])
        g["g"]["fxb"] = 1
        assert pred(g) is False
        g = copy.deepcopy(graphs[c["path"]])
        g["g"]["fxd"] = 4
        assert pred(g) is False
        g = copy.deepcopy(graphs[c["path"]])
        for fx in g["g"]["fx"]:
            if fx["r"] == "bins2":
                fx["on"] = 0 if fx["on"] else 1
        assert pred(g) is False
    # additions are exactly the committed deterministic selections
    assert [a["path"] for a in ex.ADDITIONS] == [
        rec["shapes"][a["shape_slug"]]["selection"]["selected_addition"]
        for a in ex.ADDITIONS]
    for a in ex.ADDITIONS:
        assert a["role"] == "addition"
        assert a["declared_sha1"] == graphs[a["path"]]["sha"]
        assert ex.carrier_eligibility(a, rec)["drift_gate_eligible"] is True
        assert a["path"] not in {c["path"] for c in ex.CARRIERS}


def test_committed_carrier_records_carry_recorded_eligibility():
    cds, ex, scr = _screen_modules()
    rec = json.load(open(SCREEN_JSON))
    for c in ex.CARRIERS + ex.ADDITIONS:
        d = json.load(open(os.path.join(FX_INPUTS,
                                        f"rf-rf-bins12-{c['slug']}.json")))
        assert d["drift_eligibility"] == ex.carrier_eligibility(c, rec)
        assert d["carrier_role"] == c["role"]
        if c["role"] == "original":
            assert d["drift_eligibility"]["non_render_eligible"] is True
        assert d["drift_eligibility"]["render_eligibility"] == \
            "NOT_ESTABLISHED"
        live = d["oracle_extraction"].get("live")
        if live:
            # the live observation recorded in the carrier file is the one in
            # the screen record (same native drift)
            shape = rec["shapes"][c["shape_slug"]]
            cand = next(x for x in shape["run"]["candidates"]
                        if x["path"] == c["path"])
            assert live["record"]["determinism_gate"] == \
                cand["determinism_gate"]


# -- mutation controls ------------------------------------------------------

def test_mutating_a_nonzero_drift_original_to_eligible_is_detected():
    """A hand edit that marks a nonzero-drift original eligible must FAIL, in
    both forms: flipping the verdict only, and zeroing the drift value only."""
    cds, ex, scr = _screen_modules()
    rec = json.load(open(SCREEN_JSON))
    carrier = ex.CARRIERS[0]
    spec = scr.SHAPES[carrier["shape_slug"]]
    assert ex.carrier_eligibility(carrier, rec)["drift_gate_eligible"] is False

    def cand_of(r):
        return next(c for c in
                    r["shapes"][carrier["shape_slug"]]["run"]["candidates"]
                    if c["path"] == spec["original_path"])

    flipped = copy.deepcopy(rec)
    cand_of(flipped)["determinism_gate"]["status"] = "PASS"
    with pytest.raises(ex.Refuse):
        ex.carrier_eligibility(carrier, flipped)
    with pytest.raises(AssertionError):
        audit_screen_record(flipped)
    with pytest.raises(AssertionError):
        cds.assert_drift_gate_passed(cand_of(rec))   # honest record: refuses

    zeroed = copy.deepcopy(rec)
    g = cand_of(zeroed)["determinism_gate"]
    g["drift_per_voicing_scene"] = {k: 0.0 for k in
                                    g["drift_per_voicing_scene"]}
    with pytest.raises(ex.Refuse):   # status FAIL, recomputed PASS
        ex.carrier_eligibility(carrier, zeroed)
    with pytest.raises(AssertionError):
        audit_screen_record(zeroed)

    # mutating the verdict string of the extractor's own output is caught by
    # the stale-record comparison as well
    d = json.load(open(os.path.join(FX_INPUTS,
                                    f"rf-rf-bins12-{carrier['slug']}.json")))
    d["drift_eligibility"]["drift_gate_eligible"] = True
    assert d["drift_eligibility"] != ex.carrier_eligibility(carrier, rec)


def test_single_mode_with_scene_b_active_checks_scene_b_only():
    cds, ex, scr = _screen_modules()
    f = ex.recompute_drift_eligibility
    # Single (id 0), scene B active: only B is a voicing scene
    r = f(0, 1, {"A": 0.0, "B": 0.25})
    assert r["voicing_scenes"] == ["B"] and r["drift_gate_eligible"] is False
    # drift confined to the NON-voicing scene A does not matter
    assert f(0, 1, {"A": 0.9, "B": 0.0})["drift_gate_eligible"] is True
    # B active but only A was recorded: cannot be shown to be 0
    r = f(0, 1, {"A": 0.0})
    assert r["missing_scenes"] == ["B"] and r["drift_gate_eligible"] is False
    # the shared live gate agrees on the same native state
    s, patch = _fake_session(scene_mode=0, scene_active=1,
                             drift={0: 0.9, 1: 0.0})
    g = cds.DRIFT_GATE(s, patch)
    assert g["voicing_scenes"] == ["B"] and g["status"] == "PASS"
    s, patch = _fake_session(scene_mode=0, scene_active=1,
                             drift={0: 0.0, 1: 0.25})
    assert cds.DRIFT_GATE(s, patch)["status"] == "FAIL"


def test_non_single_scene_b_only_drift_fails_both_scenes_checked():
    cds, ex, scr = _screen_modules()
    f = ex.recompute_drift_eligibility
    for mode in (1, 2, 3):
        r = f(mode, 0, {"A": 0.0, "B": 0.083664998})
        assert r["voicing_scenes"] == ["A", "B"]
        assert r["drift_gate_eligible"] is False
        assert f(mode, 0, {"A": 0.0, "B": 0.0})["drift_gate_eligible"] is True
        # B missing -> ineligible, not silently treated as 0
        assert f(mode, 0, {"A": 0.0})["drift_gate_eligible"] is False
    # nine-decimal read-back rounding is explicit: 4e-10 rounds to 0
    assert f(2, 0, {"A": 4e-10, "B": 0.0})["drift_gate_eligible"] is True
    assert f(2, 0, {"A": 1e-9, "B": 0.0})["drift_gate_eligible"] is False
    s, patch = _fake_session(scene_mode=2, scene_active=0,
                             drift={0: 0.0, 1: 0.083664998})
    g = cds.DRIFT_GATE(s, patch)
    assert g["voicing_scenes"] == ["A", "B"] and g["status"] == "FAIL"


class _FakeParam:
    def __init__(self, v):
        self.v = v


class _FakeSession:
    def __init__(self, vals):
        self.vals = vals

    def getParamVal(self, p):
        return self.vals[id(p)]


def _fake_session(scene_mode=2, scene_active=0, drift=None, b1=2, b2=0,
                  fxb=0, fxd=0):
    drift = drift or {0: 0.0, 1: 0.0}
    ps = {}

    def mk(v):
        p = _FakeParam(v)
        ps[id(p)] = v
        return p
    patch = {"scenemode": mk(scene_mode), "scene_active": mk(scene_active),
             "fx_bypass": mk(fxb), "fx_disable": mk(fxd),
             "scene": [{"drift": mk(drift[0])}, {"drift": mk(drift[1])}],
             "fx": [{"type": mk(0)} for _ in range(16)]}
    patch["fx"][2]["type"] = mk(b1)
    patch["fx"][3]["type"] = mk(b2)
    return _FakeSession(ps), patch


class _FakeLoader:
    """Injected non-live loader serving one prepared native state."""
    is_live = False

    def __init__(self, session_patch):
        self.sp = session_patch

    def open(self):
        return {"fake": True}

    def load(self, rel, sha1):
        return self.sp[0], self.sp[1], sha1


def test_bypassed_native_shape_check_is_detected():
    """A native state whose shape disagrees with the predicate must be refused
    by the real shape check (no drift value); a bypassed check would instead
    let the candidate through to the gate -- the control demonstrates that
    difference and that the real check is what stops it."""
    cds, ex, scr = _screen_modules()
    spec = scr.SHAPES["shore"]            # bins1-only, scene mode 2
    graph = _graph_records()[spec["original_path"]]
    cand = {"path": spec["original_path"],
            "graphs_blob_sha1": spec["original_sha1"], "graph": graph["g"]}
    # native state: bins2 occupied (graph says empty) -> shape disagreement
    bad = _fake_session(scene_mode=2, b1=graph["g"]["fx"][2]["t"], b2=9)
    rec = cds.screen_candidate(_FakeLoader(bad), cand,
                               scr.make_shape_check(spec), cds.DRIFT_GATE)
    assert rec["screened"] is False and rec["determinism_gate"] is None
    assert rec["refusal"]["code"] == cds.R_SHAPE_MISMATCH
    assert "bins2" in rec["refusal"]["detail"]
    # the bypassed check screens the same disagreeing state
    byp = cds.screen_candidate(_FakeLoader(bad), cand,
                               lambda s, p, c: None, cds.DRIFT_GATE)
    assert byp["screened"] is True and byp["determinism_gate"] is not None
    assert byp["screened"] != rec["screened"]
    # a wrong scene mode / fx_disable / fx_bypass is also refused
    for kw in ({"scene_mode": 0}, {"fxd": 4}, {"fxb": 3}):
        st = _fake_session(b1=graph["g"]["fx"][2]["t"], b2=0, **kw)
        r = cds.screen_candidate(_FakeLoader(st), cand,
                                 scr.make_shape_check(spec), cds.DRIFT_GATE)
        assert r["refusal"]["code"] == cds.R_SHAPE_MISMATCH, kw
    # a matching native state passes the check and reaches the gate
    ok = _fake_session(scene_mode=2, b1=graph["g"]["fx"][2]["t"], b2=0)
    r = cds.screen_candidate(_FakeLoader(ok), cand,
                             scr.make_shape_check(spec), cds.DRIFT_GATE)
    assert r["screened"] is True and r["refusal"] is None


def test_unavailable_oracle_is_not_run_and_preserves_live_evidence(
        tmp_path, monkeypatch):
    cds, ex, scr = _screen_modules()

    class Absent:
        is_live = False

        def open(self):
            raise cds.OracleAbsent("no oracle here")

    doc = scr.build_record(Absent(), slugs=["shore"])
    assert doc["status"] == "NOT_RUN" and doc["live"] is False
    assert doc["shapes"]["shore"]["selection"]["status"] == "NOT_RUN"
    with pytest.raises(ex.Refuse):          # never written as oracle evidence
        cds.write_record(doc, str(tmp_path / "x.json"))

    # an injected (mock) loader's PASS record is not live evidence either
    spec = scr.SHAPES["shore"]
    graph = _graph_records()[spec["original_path"]]
    ok = _fake_session(scene_mode=2, b1=graph["g"]["fx"][2]["t"], b2=0)
    mock = scr.build_record(_FakeLoader(ok), slugs=["shore"])
    assert mock["live"] is False
    with pytest.raises(ex.Refuse):
        cds.write_record(mock, str(tmp_path / "y.json"))

    # CLI: a pre-existing live record is left byte-identical on NOT_RUN
    out = tmp_path / "carrier-drift-screen.json"
    out.write_bytes(open(SCREEN_JSON, "rb").read())
    before = out.read_bytes()
    monkeypatch.setattr(cds, "PinnedSurgepyLoader", Absent)
    assert scr.main(["--out", str(out)]) == 2
    assert out.read_bytes() == before

    # extractor: oracle absent -> NOT_RUN live leg; the prior LIVE observation
    # in the carrier record is retained, not overwritten
    carrier = ex.CARRIERS[0]
    committed = json.load(open(os.path.join(
        FX_INPUTS, f"rf-rf-bins12-{carrier['slug']}.json")))
    if not committed["oracle_extraction"].get("live"):
        pytest.skip("committed carrier record has no live observation")
    fresh = ex.extract_one(carrier)
    ex._LIVE["v"] = (None, "NOT_RUN: pinned oracle unavailable (test)")
    try:
        fresh = ex.extract_one(carrier)
    finally:
        ex._LIVE.pop("v", None)
    assert fresh["oracle_extraction"]["live"] is None
    assert fresh["oracle_extraction"]["ok"] is False
    merged = ex.merge_prior_live(fresh, committed)
    kept = merged["oracle_extraction"]
    assert kept["live"] == committed["oracle_extraction"]["live"]
    assert kept["retained_from_prior_live_run"] is True
    assert kept["current_run"]["status"] == "NOT_RUN"
    # without prior live evidence nothing is invented
    bare = ex.merge_prior_live(ex.extract_one(carrier), {})
    assert bare["oracle_extraction"].get("live") in (None,) or \
        bare["oracle_extraction"]["live"]["live"] is True


def test_selection_rule_is_deterministic_and_gap_is_bounded():
    cds, ex, scr = _screen_modules()
    rec = json.load(open(SCREEN_JSON))
    spec = scr.SHAPES["shore"]
    cands = rec["shapes"]["shore"]["run"]["candidates"]
    pick = scr.select_replacement(spec["original_path"], cands)
    assert pick == scr.select_replacement(spec["original_path"],
                                          list(reversed(cands)))
    passing = sorted(c["path"] for c in cands
                     if c["determinism_gate"]["status"] == "PASS")
    assert pick == passing[0]
    # no eligible candidate -> bounded gap (None), never the failed original
    failing_only = [c for c in cands
                    if c["determinism_gate"]["status"] != "PASS"]
    assert scr.select_replacement(spec["original_path"], failing_only) is None
    unscreened = copy.deepcopy(cands)
    for c in unscreened:
        c["screened"] = False
    assert scr.select_replacement(spec["original_path"], unscreened) is None
