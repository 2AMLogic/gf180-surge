"""SXT-028l routing-form leaf tests (pytest): Send buses 3-4 (send3 / send4,
the extended rack half of the engine's four send buses).

Covers: the frozen arithmetic/schedule (the send stage's single active bypass
mode, the `fx_disable` bits 12/13, the per-bus `sendused` flags, the
scene-accumulation and return-mix order-independence that this PARALLEL form
is built on), the send-form gain plane (per-scene send gains + per-slot
return gain, including the real-corpus return-muted shape), the instance
lifecycle (patch-change reload mid-tail, slot-off, panic/reset), model
determinism and per-instance independence (including the real-corpus
SAME-FX-class-in-both-buses shape), the declared tail span, the declared
seams (a future `rf-send12` base half; composition with the four landed
routing leaves), generator consistency of the committed carrier records
(census+graphs cross-check, oracle-independent, fail-closed on injected
drift), the SXT-011 send-level data gap (recorded, never fabricated),
negative-control evidence integrity, and the committed RTL-exactness record
(fail-closed on a stale model revision).

ORACLE-DEPENDENT LEGS (per-slot algorithm parameters, wet-audio fixture
renders, model-vs-reference agreement) are NOT run here: they are recorded
as refused/NOT_RUN and are never reported as a pass (AGENTS.md). The
loader-default send-level probe for buses 3/4 is additionally BLOCKED on the
SXT-017 data-gap decision (#12). The same rule covers a missing iverilog:
the RTL-exactness and negative-control records are asserted only when
committed, and a stale record (model-revision drift) FAILS rather than
silently passing.
"""
import copy
import json
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-send34"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import rf_send34_model as rm  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028l")
FX_INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")
CARRIER_SLUGS = ("trance", "batbrass", "dystopia", "strynth",
                 "closeout-sale", "random-bass-fx")

COEFFS_A = (rm.to_q(0.4, 29, 32), rm.to_q(-0.15, 29, 32), rm.to_q(0.08, 29, 32),
            rm.to_q(0.25, 29, 32), rm.to_q(-0.12, 29, 32))
COEFFS_B = (rm.to_q(0.2, 29, 32), rm.to_q(0.3, 29, 32), rm.to_q(-0.1, 29, 32),
            rm.to_q(-0.35, 29, 32), rm.to_q(0.18, 29, 32))
COEFFS_TAIL = (rm.to_q(0.06, 29, 32), 0, 0,
               rm.to_q(-1.90, 29, 32), rm.to_q(0.945, 29, 32))

LEVELS_A = (rm.gain_from_level(0.8), rm.gain_from_level(0.5),
            rm.gain_from_level(1.0))
LEVELS_B = (rm.gain_from_level(0.3), rm.gain_from_level(0.9),
            rm.gain_from_level(0.7))
LEVELS_MUTED_RETURN = (rm.gain_from_level(0.8), rm.gain_from_level(0.5),
                       rm.gain_from_level(0.0))


def rand_arr(rs, amp=0.3):
    return [rm.to_q(amp * rs.uniform(-1, 1), 21, 32) for _ in range(rm.BLOCK)]


def rand_stim(rs, amp=0.3):
    """(sa_l, sa_r, sb_l, sb_r, main_l, main_r)."""
    return tuple(rand_arr(rs, amp) for _ in range(6))


def silent_scene_stim(rs, amp=0.3):
    z = [0] * rm.BLOCK
    return (list(z), list(z), list(z), list(z),
            rand_arr(rs, amp), rand_arr(rs, amp))


def loaded_rack(c3=COEFFS_A, c4=COEFFS_B, lv3=LEVELS_A, lv4=LEVELS_B,
                fx_bypass=rm.FXB_ALL_FX, fx_disable=0, scene_b=True,
                occ3=True, occ4=True):
    rack = rm.ExtendedSendRack()
    rack.apply_control(fx_bypass, fx_disable, scene_b,
                       occ3, True, c3, lv3, occ4, True, c4, lv4)
    return rack


# --------------------------------------------------------------------------
# frozen constants / schedule
# --------------------------------------------------------------------------

def test_frozen_constants_and_layout():
    assert rm.BLOCK == 32
    assert rm.A_FRAC == 21 and rm.A_BITS == 32
    assert rm.C_FRAC == 29 and rm.C_BITS == 32
    assert rm.G_FRAC == 30 and rm.G_BITS == 32
    assert rm.R_BITS == 80
    assert rm.FXB_ALL_FX == 0 and rm.FXB_NO_SENDS == 1
    assert rm.FXB_SCENE_FX_ONLY == 2 and rm.FXB_NO_FX == 3
    assert (rm.FXSLOT_SEND1, rm.FXSLOT_SEND2) == (4, 5)
    assert (rm.FXSLOT_SEND3, rm.FXSLOT_SEND4) == (12, 13)
    assert rm.N_SEND_SLOTS == 4
    # the SEND stage runs in ALL_FX only -- the strictest of the engine's
    # three routing-stage partitions
    assert rm.SEND_ACTIVE_MODES == (rm.FXB_ALL_FX,)
    assert rm.SEND_RACK_ORDER == ("send1", "send2", "send3", "send4")
    assert rm.THIS_LEAF_ROLES == ("send3", "send4")


def test_slot_indices_agree_with_the_committed_corpus_role_table():
    """The slot indices are re-derived from an in-repo artifact (no live
    oracle): every graphs.jsonl record carries the pinned engine's slot order
    by patch fx[] index. Checked across the WHOLE corpus, not just the first
    record, because a truncated fx[] list would otherwise go unnoticed."""
    path = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)["g"]
            roles = {fx["i"]: fx["r"] for fx in g["fx"]}
            assert roles[rm.FXSLOT_SEND3] == "send3"
            assert roles[rm.FXSLOT_SEND4] == "send4"
            assert roles[rm.FXSLOT_SEND1] == "send1"
            assert roles[rm.FXSLOT_SEND2] == "send2"
            n += 1
    assert n > 3000, f"corpus unexpectedly small ({n} records)"


def test_send_stage_runs_only_in_all_fx():
    rs = random.Random(1)
    stim = rand_stim(rs)
    rack = loaded_rack()
    res = rack.process_block(*stim, True, True)
    assert (res[0], res[1]) != (stim[4], stim[5]), "ALL_FX must mix the sends"
    assert res[6] is True and res[7] is True
    for mode in (rm.FXB_NO_SENDS, rm.FXB_SCENE_FX_ONLY, rm.FXB_NO_FX):
        rack = loaded_rack(fx_bypass=mode)
        res = rack.process_block(*stim, True, True)
        assert res[0] == stim[4] and res[1] == stim[5]   # main bus untouched
        assert all(v == 0 for arr in res[2:6] for v in arr)  # no bus formed
        assert res[6] is False and res[7] is False
        assert rack.slot3.biquad.reg0 == [0, 0]          # no state advanced
        assert rack.slot4.biquad.reg0 == [0, 0]


def test_disable_bitmask_gates_the_named_bus_only():
    rs = random.Random(2)
    stim = rand_stim(rs)
    ref = loaded_rack().process_block(*stim, True, True)

    # disabling send3 (bit 12): bus 3 contributes nothing, bus 4 still does
    b3off = loaded_rack(fx_disable=1 << rm.FXSLOT_SEND3)
    got = b3off.process_block(*stim, True, True)
    only4 = loaded_rack(occ3=False).process_block(*stim, True, True)
    assert (got[0], got[1]) == (only4[0], only4[1])
    assert (got[0], got[1]) != (ref[0], ref[1])
    assert all(v == 0 for arr in got[2:4] for v in arr)   # wet3 discarded
    assert any(v != 0 for arr in got[4:6] for v in arr)   # wet4 alive

    # disabling send4 (bit 13)
    b4off = loaded_rack(fx_disable=1 << rm.FXSLOT_SEND4)
    got4 = b4off.process_block(*stim, True, True)
    only3 = loaded_rack(occ4=False).process_block(*stim, True, True)
    assert (got4[0], got4[1]) == (only3[0], only3[1])

    # real-corpus shape (Closeout Sale.fxp, fx_disable = 13107): BOTH bits set
    both = loaded_rack(fx_disable=13107)
    gotb = both.process_block(*stim, True, True)
    assert gotb[0] == stim[4] and gotb[1] == stim[5]      # nothing returned

    # a bit belonging to ANOTHER slot (send1 = 4) must not gate this rack
    other = loaded_rack(fx_disable=1 << rm.FXSLOT_SEND1)
    goto = other.process_block(*stim, True, True)
    assert (goto[0], goto[1]) == (ref[0], ref[1])


def test_unoccupied_bus_contributes_nothing():
    """A SEND slot is not a pass-through: an unoccupied bus is discarded, not
    mixed back dry. (An unoccupied INSERT slot passes its audio through --
    that difference is the point of this routing form.)"""
    rs = random.Random(3)
    stim = rand_stim(rs)
    rack = loaded_rack(occ3=False, occ4=False)
    res = rack.process_block(*stim, True, True)
    assert res[0] == stim[4] and res[1] == stim[5]
    assert all(v == 0 for arr in res[2:6] for v in arr)


def test_main_bus_passes_through_bit_exactly():
    """With no bus running, the return mix (main_in << G_FRAC, rounded back
    down) must reproduce the main bus EXACTLY -- no gain, no rounding drift."""
    rs = random.Random(4)
    for _ in range(8):
        stim = rand_stim(rs, 0.9)
        rack = loaded_rack(occ3=False, occ4=False)
        res = rack.process_block(*stim, True, True)
        assert res[0] == stim[4]
        assert res[1] == stim[5]


def test_zero_return_gain_mutes_the_return_but_state_still_advances():
    """Real-corpus shape (Random Bass FX.fxp: return_level 0.0 on BOTH send
    buses). The buses run -- their occupants' histories advance -- but they
    return silence into the main bus."""
    rs = random.Random(5)
    stim = rand_stim(rs)
    rack = loaded_rack(lv3=LEVELS_MUTED_RETURN, lv4=LEVELS_MUTED_RETURN)
    res = rack.process_block(*stim, True, True)
    assert rm.gain_from_level(0.0) == 0
    assert res[0] == stim[4] and res[1] == stim[5]        # nothing returned
    assert any(v != 0 for arr in res[2:6] for v in arr)   # buses did run
    assert rack.slot3.biquad.reg0 != [0, 0]               # state advanced
    assert rack.slot4.biquad.reg0 != [0, 0]


def test_scene_b_inactive_removes_the_scene_b_contribution():
    """In Single scene mode the engine never instantiates scene B, so only
    scene A feeds the send buses (all three issue-named carriers are
    Single-mode patches)."""
    rs = random.Random(6)
    stim = rand_stim(rs)
    dual = loaded_rack(scene_b=True).process_block(*stim, True, True)
    single = loaded_rack(scene_b=False).process_block(*stim, True, True)
    assert (dual[0], dual[1]) != (single[0], single[1])
    # with scene B silent, the two agree again: the gate really is "scene B's
    # contribution", not an unrelated switch
    z = [0] * rm.BLOCK
    stim_no_b = (stim[0], stim[1], list(z), list(z), stim[4], stim[5])
    d2 = loaded_rack(scene_b=True).process_block(*stim_no_b, True, True)
    s2 = loaded_rack(scene_b=False).process_block(*stim_no_b, True, True)
    assert (d2[0], d2[1]) == (s2[0], s2[1])


def test_scene_accumulation_is_order_independent_by_construction():
    """The bus is formed with ONE rounding and ONE saturation over the whole
    scene sum, so swapping which scene is accumulated first cannot change the
    result. Verified, not merely asserted (the frozen model's docstring makes
    this a declared design property)."""
    rs = random.Random(7)
    sa, sb = rand_arr(rs), rand_arr(rs)
    lv = rm.SendBusLevels(*LEVELS_A)
    swapped = rm.SendBusLevels(lv.send_gain_b, lv.send_gain_a, lv.return_gain)
    rack = loaded_rack()
    assert rack.form_bus(sa, sb, lv) == rack.form_bus(sb, sa, swapped)


def test_return_mix_is_order_independent_by_construction():
    """The two returns are summed into ONE wide accumulator and reduced once,
    so bus3-then-bus4 and bus4-then-bus3 are the same number. This is what
    BOUNDS this leaf's wrong-order control (see EVIDENCE section 3): the
    observable permutation axis is slot-content-vs-bus-gain, not summation
    order."""
    rs = random.Random(8)
    stim = rand_stim(rs)
    a = loaded_rack(c3=COEFFS_A, c4=COEFFS_B, lv3=LEVELS_A, lv4=LEVELS_B)
    b = loaded_rack(c3=COEFFS_B, c4=COEFFS_A, lv3=LEVELS_B, lv4=LEVELS_A)
    ra = a.process_block(*stim, True, True)
    rb = b.process_block(*stim, True, True)
    # identical contribution SET, summed in the opposite order
    assert (ra[0], ra[1]) == (rb[0], rb[1])


def test_sendused_false_is_a_state_no_op():
    rs = random.Random(9)
    stim = rand_stim(rs)
    rack = loaded_rack()
    res = rack.process_block(*stim, False, False)
    assert res[6] is False and res[7] is False
    assert rack.slot3.biquad.reg0 == [0, 0]
    assert rack.slot4.biquad.reg0 == [0, 0]
    # the formed (unprocessed) bus is still returned -- in the engine's own
    # use `sendused` false means nothing was mixed INTO the bus, so this adds
    # silence; the contract is pinned here rather than left implicit
    assert any(v != 0 for arr in res[2:6] for v in arr)


# --------------------------------------------------------------------------
# per-instance state and lifecycle
# --------------------------------------------------------------------------

def test_dual_instance_independent_histories():
    rack = loaded_rack()
    rs = random.Random(10)
    for _ in range(20):
        rack.process_block(*rand_stim(rs), True, True)
    assert rack.slot3.biquad is not rack.slot4.biquad
    assert rack.slot3.biquad.reg0 != rack.slot4.biquad.reg0
    assert rack.slot3.biquad.reg1 != rack.slot4.biquad.reg1


def test_same_class_buses_still_keep_independent_histories():
    """The real-corpus shape (Strynth.fxp: Nimbus in BOTH send3 and send4).
    Identical arithmetic in both buses is exactly where a pooled-state
    implementation hides best."""
    rack = loaded_rack(c3=COEFFS_A, c4=COEFFS_A)
    rs = random.Random(11)
    for _ in range(12):
        rack.process_block(*rand_stim(rs), True, True)
    assert rack.slot3.biquad is not rack.slot4.biquad
    # the two instances see DIFFERENT bus signals (different send gains), so
    # identical coefficients must still leave different histories
    assert rack.slot3.biquad.reg0 != rack.slot4.biquad.reg0


def test_patch_change_mid_tail_clears_only_that_slot():
    """`loadFx()` on send3 mid-tail installs a fresh instance for send3 ONLY:
    send4's history survives."""
    rack = loaded_rack(c3=COEFFS_TAIL, c4=COEFFS_TAIL)
    rs = random.Random(12)
    for _ in range(3):
        rack.process_block(*rand_stim(rs, 0.05), True, True)
    assert rack.slot3.biquad.reg0 != [0, 0]
    before4 = copy.deepcopy(rack.slot4.biquad.reg0)
    assert before4 != [0, 0]

    rack.apply_control(rm.FXB_ALL_FX, 0, True,
                       True, True, COEFFS_A, LEVELS_A,
                       True, False, COEFFS_B, LEVELS_B)
    assert rack.slot3.biquad.reg0 == [0, 0]      # fresh instance
    assert rack.slot4.biquad.reg0 == before4     # sibling untouched
    assert rack.slot3.biquad.coeffs == COEFFS_A  # new coefficients adopted


def test_reload_does_not_disturb_the_bus_gain_plane():
    """The gain plane is BUS state, not occupant state."""
    rack = loaded_rack()
    rs = random.Random(13)
    rack.process_block(*rand_stim(rs), True, True)
    assert rack.levels3.as_tuple() == LEVELS_A
    rack.apply_control(rm.FXB_ALL_FX, 0, True,
                       True, True, COEFFS_B, LEVELS_A,
                       True, True, COEFFS_A, LEVELS_B)
    assert rack.slot3.biquad.reg0 == [0, 0]            # instance reloaded
    assert rack.levels3.as_tuple() == LEVELS_A         # gains untouched
    assert rack.levels4.as_tuple() == LEVELS_B


def test_slot_off_mid_tail_releases_only_that_instance():
    rack = loaded_rack(c3=COEFFS_TAIL, c4=COEFFS_TAIL)
    rs = random.Random(14)
    for _ in range(3):
        rack.process_block(*rand_stim(rs, 0.05), True, True)
    before3 = copy.deepcopy(rack.slot3.biquad.reg0)
    rack.apply_control(rm.FXB_ALL_FX, 0, True,
                       True, False, COEFFS_TAIL, LEVELS_A,
                       False, False, COEFFS_B, LEVELS_B)
    assert rack.slot4.occupied is False
    assert rack.slot4.biquad.reg0 == [0, 0]
    assert rack.slot3.biquad.reg0 == before3


def test_panic_reset_clears_both_instances_and_the_ring_memory():
    rack = loaded_rack(c3=COEFFS_TAIL, c4=COEFFS_TAIL)
    rs = random.Random(15)
    for _ in range(3):
        rack.process_block(*rand_stim(rs, 0.05), True, True)
    assert rack.send_ring == [True, True]
    gains_before = (rack.levels3.as_tuple(), rack.levels4.as_tuple())
    rack.panic_reset()
    assert rack.checkpoint() == ((0, 0), (0, 0), (0, 0), (0, 0))
    assert rack.send_ring == [False, False]
    assert rack.slot3.occupied and rack.slot4.occupied   # patch still loaded
    assert (rack.levels3.as_tuple(), rack.levels4.as_tuple()) == gains_before


def test_coefficient_change_without_reload_keeps_state():
    rack = loaded_rack()
    rs = random.Random(16)
    for _ in range(2):
        rack.process_block(*rand_stim(rs), True, True)
    keep = copy.deepcopy(rack.slot3.biquad.reg0)
    rack.apply_control(rm.FXB_ALL_FX, 0, True,
                       True, False, COEFFS_B, LEVELS_A,
                       True, False, COEFFS_A, LEVELS_B)
    assert rack.slot3.biquad.reg0 == keep
    assert rack.slot3.biquad.coeffs == COEFFS_B


def test_lifecycle_runs_even_while_the_stage_is_bypassed():
    """The engine's load/unload path is control-rate: a slot-off issued while
    fx_bypass skips the send stage must still release the instance."""
    rack = loaded_rack(c3=COEFFS_TAIL, c4=COEFFS_TAIL)
    rs = random.Random(17)
    for _ in range(2):
        rack.process_block(*rand_stim(rs, 0.05), True, True)
    assert rack.slot4.biquad.reg0 != [0, 0]
    rack.apply_control(rm.FXB_NO_SENDS, 0, True,
                       True, False, COEFFS_TAIL, LEVELS_A,
                       False, False, COEFFS_B, LEVELS_B)
    assert rack.slot4.occupied is False
    assert rack.slot4.biquad.reg0 == [0, 0]


def test_model_determinism():
    runs = []
    for _ in range(2):
        rack = loaded_rack()
        rs = random.Random(18)
        out = []
        for _b in range(10):
            res = rack.process_block(*rand_stim(rs), True, True)
            out.append(res)
        runs.append((out, rack.checkpoint()))
    assert runs[0] == runs[1]


def test_gain_from_level_is_the_declared_cubed_mapping():
    """`gain = level**3` (amp_to_linear cubed), quantized to Q1.30 at CONTROL
    rate -- the semantic already pinned in-repo by the landed SXT-024 Reverb1
    send path. Never applied at audio rate."""
    assert rm.gain_from_level(1.0) == rm.to_g(1.0) == 1 << rm.G_FRAC
    assert rm.gain_from_level(0.0) == 0
    for lvl in (0.1, 0.25, 0.5, 0.8, 0.95):
        assert rm.gain_from_level(lvl) == rm.to_q(lvl ** 3, rm.G_FRAC,
                                                  rm.G_BITS)
    # monotone and strictly below unity inside (0, 1)
    assert 0 < rm.gain_from_level(0.5) < rm.gain_from_level(0.8) < (1 << 30)


# --------------------------------------------------------------------------
# declared seams
# --------------------------------------------------------------------------

def test_declared_seam_with_a_future_send12_base_half():
    """This leaf declares send1/send2 as the base half of the same rack. No
    `rf-send12`-class leaf exists in this repository yet; if one lands, the
    two must agree on the shared slot table and the bus word format. The test
    states the seam either way instead of leaving the absence implicit."""
    assert rm.BASE_HALF_ROLES == ("send1", "send2")
    base_dir = os.path.join(REPO, "model", "effects", "rf-rf-send12")
    if not os.path.isdir(base_dir):
        return  # declared-but-unlanded seam; nothing to cross-check yet
    sys.path.insert(0, base_dir)
    import rf_send12_model as base  # noqa: PLC0415
    assert (base.FXSLOT_SEND1, base.FXSLOT_SEND2) == (4, 5)
    assert (base.A_FRAC, base.A_BITS) == (rm.A_FRAC, rm.A_BITS)


def test_composes_with_the_landed_insert_and_global_routing_leaves():
    """Topology check across the landed routing forms: scene-A inserts
    (rf-rf-ains34) and scene-B inserts (rf-rf-bins12) feed THIS leaf's send
    buses, and this leaf's main-bus output feeds the global rack
    (rf-rf-global34). Nothing about the other leaves is re-claimed here; the
    point is that the five routing forms share one bus word format and that
    all SIX slot instances keep independent histories.

    The scene sum used to build the main bus is declared STIMULUS (computing
    it is nobody's landed scope yet), not a modeled stage.
    """
    sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-ains34"))
    sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-bins12"))
    sys.path.insert(0, os.path.join(REPO, "model", "effects", "rf-rf-global34"))
    import rf_ains34_model as ains    # noqa: PLC0415
    import rf_bins12_model as bins    # noqa: PLC0415
    import rf_global34_model as glob  # noqa: PLC0415

    # all five routing forms must agree on the bus/coefficient word formats
    for mod in (ains, bins, glob):
        assert (mod.A_FRAC, mod.A_BITS) == (rm.A_FRAC, rm.A_BITS)
        assert (mod.C_FRAC, mod.C_BITS) == (rm.C_FRAC, rm.C_BITS)
        assert mod.BLOCK == rm.BLOCK
    # ... and the slot table they share
    assert (ains.FXSLOT_AINS3, ains.FXSLOT_AINS4) == (8, 9)
    assert (bins.FXSLOT_BINS1, bins.FXSLOT_BINS2) == (2, 3)
    assert (glob.FXSLOT_GLOBAL3, glob.FXSLOT_GLOBAL4) == (14, 15)

    coeffs = [
        (rm.to_q(0.30, 29, 32), rm.to_q(-0.11, 29, 32), rm.to_q(0.05, 29, 32),
         rm.to_q(0.21, 29, 32), rm.to_q(-0.09, 29, 32)),
        (rm.to_q(0.24, 29, 32), rm.to_q(0.13, 29, 32), rm.to_q(-0.07, 29, 32),
         rm.to_q(-0.19, 29, 32), rm.to_q(0.11, 29, 32)),
        (rm.to_q(0.35, 29, 32), rm.to_q(-0.21, 29, 32), rm.to_q(0.09, 29, 32),
         rm.to_q(0.27, 29, 32), rm.to_q(-0.15, 29, 32)),
        (rm.to_q(0.18, 29, 32), rm.to_q(0.26, 29, 32), rm.to_q(-0.12, 29, 32),
         rm.to_q(-0.31, 29, 32), rm.to_q(0.16, 29, 32)),
    ]
    scene_a = ains.SceneAExtendedInsertBus()
    scene_a.apply_control(0, 0, True, True, coeffs[0], True, True, coeffs[1])
    scene_b = bins.SceneBInsertBus()
    scene_b.apply_control(0, 0, True, True, coeffs[2], True, True, coeffs[3])
    sends = loaded_rack()
    globals_ = glob.ExtendedGlobalRack()
    globals_.apply_control(0, 0, True, True, COEFFS_A, True, True, COEFFS_B)

    rs = random.Random(19)
    chain_out = []
    for _b in range(8):
        raw_a_l, raw_a_r = rand_arr(rs), rand_arr(rs)
        raw_b_l, raw_b_r = rand_arr(rs), rand_arr(rs)
        sa_l, sa_r, _ = scene_a.process_block(raw_a_l, raw_a_r, True)
        sb_l, sb_r, _ = scene_b.process_block(raw_b_l, raw_b_r, True)
        # declared STIMULUS: the scene sum (nobody's landed scope yet)
        main_l = [rm.sat_s(x + y, rm.A_BITS) for x, y in zip(sa_l, sb_l)]
        main_r = [rm.sat_s(x + y, rm.A_BITS) for x, y in zip(sa_r, sb_r)]
        res = sends.process_block(sa_l, sa_r, sb_l, sb_r, main_l, main_r,
                                  True, True)
        gl, gr, _ = globals_.process_block(res[0], res[1], True)
        chain_out.append((gl, gr))

    assert any(v != 0 for gl, gr in chain_out for v in gl + gr)
    histories = [tuple(scene_a.slot3.biquad.reg0),
                 tuple(scene_a.slot4.biquad.reg0),
                 tuple(scene_b.slot1.biquad.reg0),
                 tuple(scene_b.slot2.biquad.reg0),
                 tuple(sends.slot3.biquad.reg0),
                 tuple(sends.slot4.biquad.reg0),
                 tuple(globals_.slot3.biquad.reg0),
                 tuple(globals_.slot4.biquad.reg0)]
    assert all(h != (0, 0) for h in histories)
    assert len(set(histories)) == 8, "eight slots must keep EIGHT histories"


# --------------------------------------------------------------------------
# declared tail span
# --------------------------------------------------------------------------

def test_declared_tail_span_carries_audio_and_truncation_loses_it():
    """With `sendused` still live and the SCENE buses gone silent, the
    occupants' registers must keep producing audio across the declared tail
    span; a render truncated at the end of the scene input drops real
    samples."""
    import compare_rtl_model_rf_send34 as cmp_rtl
    signal = cmp_rtl.TAIL_SIGNAL_BLOCKS
    span = cmp_rtl.TAIL_SPAN_BLOCKS
    rack = loaded_rack(c3=COEFFS_TAIL, c4=COEFFS_TAIL)
    rs = random.Random(20)
    tail_energy = []
    for b in range(signal + span):
        stim = (rand_stim(rs, 0.05) if b < signal
                else silent_scene_stim(rs, 0.05))
        res = rack.process_block(*stim, True, True)
        if b >= signal:
            tail_energy.append(sum(abs(v) for arr in res[2:6] for v in arr))
    assert len(tail_energy) == span
    assert all(e > 0 for e in tail_energy), tail_energy
    # decaying: the last tail block is much quieter than the first
    assert tail_energy[-1] < tail_energy[0]


def test_reset_mid_tail_kills_the_tail():
    rack = loaded_rack(c3=COEFFS_TAIL, c4=COEFFS_TAIL)
    rs = random.Random(21)
    for _ in range(2):
        rack.process_block(*rand_stim(rs, 0.05), True, True)
    rack.panic_reset()
    z = [0] * rm.BLOCK
    res = rack.process_block(list(z), list(z), list(z), list(z),
                             list(z), list(z), True, True)
    assert all(v == 0 for arr in res[:6] for v in arr)


def test_no_external_memory_traffic_from_this_leaf():
    rack = loaded_rack()
    rs = random.Random(22)
    for _ in range(4):
        rack.process_block(*rand_stim(rs), True, True)
    for slot in (rack.slot3, rack.slot4):
        assert slot.ext_reads == 0 and slot.ext_writes == 0


# --------------------------------------------------------------------------
# generator consistency / fail-closed extraction
# --------------------------------------------------------------------------

def test_carrier_records_match_the_extractor_output():
    """Committed carrier records must be exactly what the extractor produces
    now (no stale artifact, no hand edit)."""
    import extract_rf_send34_inputs as ex
    for carrier in ex.CARRIERS:
        path = os.path.join(FX_INPUTS, f"rf-rf-send34-{carrier['slug']}.json")
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
                          "`python3 tools/extract_rf_send34_inputs.py`")


def test_extraction_records_fail_closed():
    for slug in CARRIER_SLUGS:
        d = json.load(open(os.path.join(FX_INPUTS,
                                        f"rf-rf-send34-{slug}.json")))
        assert d["leaf"] == "SXT-028l"
        assert d["roles"] == ["send3", "send4"]
        assert d["applicability"]["routing_metadata_verified"] is True
        assert d["preset"]["census_blob_sha1_verified"] == \
            d["preset"]["graphs_blob_sha1_verified"]
        assert d["cross_check"]["census_vs_graphs_drift_count"] == 0
        assert d["slot_index_check"]["verified_indices"]["12"] == "send3"
        assert d["slot_index_check"]["verified_indices"]["13"] == "send4"
        # unlike the insert/global forms, THIS form consumes return_level
        assert d["send3"]["return_level_consumed_by_send_path"] is True
        assert d["send4"]["return_level_consumed_by_send_path"] is True
        # oracle-dependent leg is honestly refused in this environment, not
        # fabricated as a pass
        assert d["oracle_extraction"]["attempted"] is True
        if not d["oracle_extraction"]["ok"]:
            assert d["applicability"]["complete_wet_render_possible"] is False


def test_send_level_gap_is_recorded_and_never_fabricated():
    """The SXT-011 exposure gap: no .fxp stores the per-scene send levels for
    buses 3/4 and surgepy does not expose them. Every carrier record must say
    so explicitly -- `null`, never a guessed loader default -- and route the
    decision to #12."""
    for slug in CARRIER_SLUGS:
        d = json.load(open(os.path.join(FX_INPUTS,
                                        f"rf-rf-send34-{slug}.json")))
        gap = d["send_level_gap"]
        assert gap["send3_send4_levels_stored"] is None
        assert gap["blocking_issue"].startswith("#12")
        assert "control-plane stimulus" in gap["consumed_by_this_leaf_as"]
        # the two EXPOSED levels (buses 1/2) are recorded as context
        assert all(len(levels) == 2 for levels in
                   gap["exposed_levels_per_scene"])
    scan = os.path.join(SXT, "artifacts", "send-level-gap.json")
    if not os.path.exists(scan):
        pytest.skip("send-level-gap.json not committed (NOT_RUN)")
    s = json.load(open(scan))
    assert s["engine_send_buses"] == 4
    assert s["levels_exposed_per_scene"] == 2
    assert s["gap_holds_across_the_whole_corpus"] is True
    assert s["send_array_length_histogram"] == {"2": s["scene_records_scanned"]}
    assert s["status"].startswith("BLOCKED")


def test_extraction_refuses_a_corpus_that_closes_the_gap():
    """Live control for the gap record: if a graph record ever carried four
    per-scene send levels, the gap this leaf's contract rests on would be
    closed upstream and the extractor must REFUSE rather than reinterpret."""
    import extract_rf_send34_inputs as ex
    graph = ex.graphs_entry(ex.CARRIERS[0]["path"])
    ex.send_level_check(graph)              # the real record passes
    mutated = copy.deepcopy(graph)
    for sc in mutated["g"]["sc"]:
        sc["send"] = sc["send"] + [0.0, 0.0]
    with pytest.raises(ex.Refuse):
        ex.send_level_check(mutated)


def test_carrier_set_covers_the_shapes_the_acceptance_needs():
    """The issue's three named carriers DO reach the dual-instance shape here
    (unlike the sibling global-rack leaf): Batbrass.fxp occupies both send
    buses. The three added carriers cover the same-class, both-disabled and
    return-muted shapes."""
    named = {}
    for slug in ("trance", "batbrass", "dystopia"):
        d = json.load(open(os.path.join(FX_INPUTS,
                                        f"rf-rf-send34-{slug}.json")))
        assert "issue-named" in d["carrier_source"]
        named[slug] = d
    assert named["batbrass"]["dual_instance_concurrent"] is True
    assert named["trance"]["dual_instance_concurrent"] is False
    assert named["dystopia"]["dual_instance_concurrent"] is False
    assert all(d["scene_context"]["scene_b_instantiated"] is False
               for d in named.values()), "all three named carriers are Single"

    strynth = json.load(open(os.path.join(FX_INPUTS,
                                          "rf-rf-send34-strynth.json")))
    assert "added by this leaf" in strynth["carrier_source"]
    assert strynth["dual_instance_concurrent"] is True
    assert strynth["same_class_both_buses"] is True
    assert strynth["scene_context"]["scene_b_instantiated"] is True

    closeout = json.load(open(os.path.join(
        FX_INPUTS, "rf-rf-send34-closeout-sale.json")))
    assert closeout["both_slots_disabled"] is True
    assert closeout["patch_level"]["fx_disable_mask"] == 13107
    assert (13107 >> 12) & 1 and (13107 >> 13) & 1

    muted = json.load(open(os.path.join(
        FX_INPUTS, "rf-rf-send34-random-bass-fx.json")))
    assert muted["send3"]["return_muted"] is True
    assert muted["send4"]["return_muted"] is True


def test_extraction_refuses_injected_drift():
    """Live control for the fail-closed claim: a census/graphs disagreement,
    a blob-sha mismatch, and a corrupted slot-index/role table must all
    REFUSE, not be papered over."""
    import extract_rf_send34_inputs as ex
    carrier = ex.CARRIERS[0]
    row = ex.census_row(carrier["path"])
    graph = ex.graphs_entry(carrier["path"])
    ex.cross_check(row, graph)          # clean pair passes
    ex.role_index_check(graph)          # clean role table passes

    bad = dict(row)
    bad["stored_fx_disable"] = "4096"   # drift in fx_disable
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad, graph)

    bad2 = dict(row)
    bad2["stored_nonoff_fx_slot_count"] = "99"
    with pytest.raises(ex.Refuse):
        ex.cross_check(bad2, graph)

    # a DIFFERENT FX in an occupied slot is content drift, not a spelling
    # difference, and must still refuse
    bad_graph_type = copy.deepcopy(graph)
    for fx in bad_graph_type["g"]["fx"]:
        if fx.get("r") == "send3":
            fx["t"] = 1     # Delay instead of the stored type
    with pytest.raises(ex.Refuse):
        ex.cross_check(row, bad_graph_type)

    bad_graph = copy.deepcopy(graph)
    for fx in bad_graph["g"]["fx"]:
        if fx["r"] == "send4":
            fx["i"] = 11               # wrong slot index
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
                                       "SXT-028l.json")))
    assert spec["leaf_id"] == "SXT-028l"
    assert spec["feature"]["roles"] == ["send3", "send4"]
    assert spec["feature"]["routing_form"] == "rf-send34"
    for rel in ("model/effects/rf-rf-send34",
                "rtl/effects/rf-rf-send34",
                "reports/SXT-028l",
                "tests/test_sxt028l.py"):
        assert os.path.exists(os.path.join(REPO, rel)), rel
    spec_paths = {c["path"] for c in spec["carriers"]["top_presets"]}
    import extract_rf_send34_inputs as ex
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
    # the shapes this leaf claims really exist in the corpus
    assert d["both_buses_occupied"] > 0
    assert d["both_buses_occupied_same_fx_class"] > 0
    assert d["fx_disable_both_bits_set"] > 0
    assert d["occupied_bus_with_return_level_zero"] > 0
    assert d["non_single_scene_mode_with_a_send34_occupant"] > 0


# --------------------------------------------------------------------------
# committed evidence records (fail-closed; never a false pass)
# --------------------------------------------------------------------------

def test_revision_pin_refuses_a_stale_harness():
    """Unit-level guard for the stale-stub control (needs no iverilog)."""
    import compare_rtl_model_rf_send34 as cmp_rtl
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
    prefixes = {c["control"].split()[0] for c in d["controls"]}
    for required in ("NC-A", "NC-B", "NC-C", "NC-D", "NC-E"):
        assert required in prefixes, required
    for c in d["controls"]:
        assert c["ok"] is True and "CONTROL-OK" in c["verdict"], c["control"]
        assert c["legs"], c["control"]
        for leg in c["legs"]:
            # a leg may be NOT_RUN (missing tool) but must never be BROKEN
            assert leg["status"] in ("CONTROL-OK", "NOT_RUN"), leg
    assert len({c["control"] for c in d["controls"]}) == len(d["controls"])
    adapted = [c for c in d["controls"]
               if c.get("coverage_label") == "ADAPTED"]
    assert adapted, "the generic-substitute control must be labeled ADAPTED"
    assert adapted[0]["counts_toward_original_preset_coverage"] is False
    # the shared-state control must also cover the same-class shape
    shared = [c for c in d["controls"] if c["control"].startswith("NC-D")][0]
    assert any("SAME-class" in leg["leg"] for leg in shared["legs"])
    # the wrong-order control must record its parallel-form bound
    order = [c for c in d["controls"] if c["control"].startswith("NC-C")][0]
    bound = order["recorded_bound"]
    assert bound["return_summation_is_order_independent_by_construction"] \
        is True
    assert bound["identical_content_and_identical_gains_is_an_identity"] is True


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == rm.model_revision(), "stale record"
    names = {c["case"] for c in d["cases"]}
    for required in ("both-buses-all-fx", "bypass-no-sends-skips-stage",
                     "bypass-scene-fx-only-skips-stage",
                     "bypass-no-fx-skips-stage", "bus3-disabled-bit12",
                     "bus4-disabled-bit13", "both-buses-disabled-corpus-mask",
                     "same-class-dual-occupants",
                     "scene-b-inactive-single-mode",
                     "zero-return-level-both-buses",
                     "sendused-false-passthrough",
                     "tail-span-silent-scenes", "bus3-reload-mid-tail",
                     "bus4-off-mid-tail", "panic-reset-mid-tail",
                     "saturating-full-scale", "random-control-stream"):
        assert required in names, required
    for c in d["cases"]:
        assert c["exact"] is True, c["case"]
        assert c["mismatches"] == 0, c["case"]
        assert c["revision_pin"]["ok"] is True, c["case"]
        assert c["checked"]["outputs"] == 64 * c["blocks"]
        assert c["checked"]["wet"] == 128 * c["blocks"]
        assert c["checked"]["checkpoints"] == c["blocks"]
    tail = [c for c in d["cases"] if c["case"] == "tail-span-silent-scenes"][0]
    assert tail["tail"]["declared_tail_span_blocks"] >= 4
    assert tail["tail"]["blocks_with_nonzero_wet_output"] == tail["blocks"]
    same = [c for c in d["cases"]
            if c["case"] == "same-class-dual-occupants"][0]
    assert same["dual_instance"]["identical_coefficients_in_both_buses"]
    assert same["dual_instance"]["distinct_gain_planes"] is True
    assert same["dual_instance"]["final_histories_differ"] is True


def test_oracle_status_record_is_measured_not_asserted():
    p = os.path.join(SXT, "artifacts", "oracle-status.json")
    if not os.path.exists(p):
        pytest.skip("oracle-status.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["oracle_status"] in ("AVAILABLE", "UNAVAILABLE")
    assert d["legs"], "the oracle-gated legs must be enumerated"
    for name, legrec in d["legs"].items():
        if name == "send-level-default-probe":
            # an available oracle does NOT unblock the SXT-017 data-gap leg
            assert legrec["status"] == "BLOCKED", name
            continue
        if d["oracle_status"] == "UNAVAILABLE":
            assert legrec["status"] == "NOT_RUN", name
            assert legrec["reason"], name
        else:
            assert legrec["status"] in ("RUNNABLE", "NOT_RUN"), name
    # the probe must record what it actually found, not a bare assertion
    assert "surgepy_importable" in d["probe"]
    assert "engine_dir_present" in d["probe"]
    assert d["fixture_freeze_gates"]["sxt017_send_level_data_gap"] == \
        "BLOCKED (#12)"


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
    assert d["on_chip_small_state"]["per_bus_gain_plane_bits"] == 3 * rm.G_BITS


def test_evidence_keeps_the_claims_separate():
    p = os.path.join(SXT, "EVIDENCE.md")
    if not os.path.exists(p):
        pytest.skip("EVIDENCE.md not committed (NOT_RUN)")
    text = open(p).read()
    assert "NOT_RUN" in text
    assert "BLOCKED" in text
    assert "oracle" in text.lower()
    assert "PENDING-SXT-016" in text
    assert "PROPOSED" in text            # budgets are not frozen
    # no support/quality claim may be asserted by this record
    low = text.lower()
    assert "preset-support claim" in low
    assert "musical-quality claim" in low
    assert "not_run** (oracle unavailable" in low   # budgets NOT_RUN, not PASS
    assert "#12" in text                 # the data-gap decision is routed
