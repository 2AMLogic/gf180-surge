"""SXT-028k Airwindows "Logical" (streamed id 4) leaf tests (pytest).

Covers: algorithm identity (this leaf dispatches exactly id 4), the frozen
word/geometry inventory, the fail-closed refusals, model determinism,
per-instance independence, the four pinned quirks that are easy to "fix"
wrongly, the proof that the compacted 4-word sag ring is bit-exact against a
literal transcription of the pinned 1000-word indexing, the tail definition,
the state/external-memory accounting, the derived-table digest vs the
committed RTL ROM images, the constants-live-in-one-place rule, the
fail-closed extraction records, and the committed negative-control and
RTL-exactness records (frozen-revision pinned, so a stale record FAILS
rather than passing).

Claim discipline (AGENTS.md):
  * Everything asserted here is either a property of the frozen model or a
    property of a committed record. Nothing here is a model-vs-pinned-engine
    agreement claim, a preset-support claim, a cost/fit claim, or a
    musical-quality claim.
  * Oracle-dependent legs do not run in this environment. They SKIP with an
    explicit NOT_RUN message and are never reported as a pass; a test below
    asserts the committed evidence says NOT_RUN/BLOCKED too, and another
    asserts no reference-agreement artifact exists to be mistaken for one.
"""
import hashlib
import json
import math
import os
import random
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AW4 = os.path.join(REPO, "model", "effects", "aw-4")
sys.path.insert(0, REPO)
sys.path.insert(0, AW4)

import logical4_model as M  # noqa: E402
import tables as T  # noqa: E402
from float_transcription import LogicalFloat, GenericCompressorADAPTED  # noqa: E402,E501

RTL = os.path.join(REPO, "rtl", "effects", "aw-4")
SXT = os.path.join(REPO, "reports", "SXT-028k")
INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")

# carrier parameter sets (census-derived; model/effects/fx_inputs/aw-4-*.json)
P_SEL0 = dict(A_threshold=0.596429, B_ratio=0.345714, C_attack=0.13202,
              D_makeup=0.5, E_mix=1.0)                       # dad, 1 stage
P_SEL1 = dict(A_threshold=0.245, B_ratio=0.654286, C_attack=0.288449,
              D_makeup=0.720713, E_mix=1.0)                  # snare, 2 stages
P_SEL2 = dict(A_threshold=0.473214, B_ratio=1.0, C_attack=0.0,
              D_makeup=0.250893, E_mix=1.0)                  # bass, 3 stages


def a48(x):
    return M.q(x, M.F_A)


def f_of(w):
    return w / float(1 << M.F_A)


def noise_blocks(n, seed=11, amp=0.4):
    rs = random.Random(seed)
    return [([a48(rs.uniform(-amp, amp)) for _ in range(M.BLOCK)],
             [a48(rs.uniform(-amp, amp)) for _ in range(M.BLOCK)])
            for _ in range(n)]


def run(model, blocks):
    out = []
    for bl, br in blocks:
        ol, orr = model.process_block(bl, br)
        out.append((ol, orr))
    return out


# --------------------------------------------------------------- identity
def test_algorithm_identity_is_id_4_only():
    """p[0] == 4 selects Logical; this leaf models that id and no other."""
    assert M.AW_STREAMED_ID == 4
    assert M.Logical4Fixed.streamed_id == 4
    assert M.Logical4Fixed.instance_kind == "aw-4"
    assert M.N_PARAMS == 5                     # Logical4 kNumParameters
    # the registry's id++ stream, as cited in the model docstring
    assert "ADClip7 0" in M.__doc__ and "Logical 4" in M.__doc__
    # every committed extraction record is id 4 and says so
    seen = 0
    for name in sorted(os.listdir(INPUTS)):
        if not name.startswith("aw-4-"):
            continue
        rec = json.load(open(os.path.join(INPUTS, name)))
        assert rec["airwindows_streamed_id"] == 4
        assert rec["airwindows_name"] == "Logical"
        assert rec["screens"]["algorithm_identity"].startswith("p[0] == 4")
        for slot in rec["logical_slots"]:
            assert set(slot["params"]) == set(M.PARAM_NAMES)
        seen += 1
    assert seen >= 3


def test_sibling_algorithm_ids_are_out_of_scope():
    """Nothing in this leaf dispatches or models another streamed id."""
    src = open(os.path.join(AW4, "logical4_model.py")).read()
    assert "AW_STREAMED_ID = 4" in src
    # no dispatch table / id switch exists at all: one algorithm per leaf
    assert not re.search(r"streamed_id\s*==\s*(?!4\b)\d+", src)


# -------------------------------------------------------------- inventory
def test_frozen_word_formats_and_geometry():
    assert (M.F_A, M.F_C, M.F_T, M.F_S, M.F_K) == (35, 53, 43, 54, 31)
    # s96 carries exactly one more fraction bit than c96 so /offset(=2) is
    # exact -- the reason the sag accumulator can add the line word unshifted
    assert M.F_S == M.F_C + 1
    assert M.SAMPLE_RATE == 48000 and M.BLOCK == 32
    assert M.SUBBLOCK == 4                     # BLOCK_SIZE >> subblock_factor
    assert M.OVERALLSCALE == (1.0 / 44100.0) * 48000.0
    assert M.SAG_OFFSET == int(M.SAG_DEPTH * M.OVERALLSCALE) == 2
    assert M.RING == 4                         # taps of age 2 and 3 only
    assert (M.N_STAGES, M.N_CH) == (3, 2)
    assert M.LINE_WORDS == 1000 and M.LINE_MIRROR == 499 and M.GCOUNT_MAX == 499
    # the reciprocal is two exact integer steps, not a float divide
    assert M.RECIP_NUM == 1 << (2 * M.F_T)
    assert M.CALC_SHIFT == 2 * M.F_T - M.F_C == 33


def test_quoted_constants_match_the_decision_record():
    """Every quoted literal is in DR-0015's inventory table."""
    dr = open(os.path.join(REPO, "decision-records",
                           "0015-airwindows-logical-quoted-constants.md")).read()
    for lit in ("0.618033988749894848204586", "0.000782", "0.000819",
                "0.000857", "0.0445556", "0.003300223685324102874217",
                "2.42", "0.000001", "1.57079633", "36.0", "2.99999"):
        assert lit in dr, lit
    assert M.FP_OLD == 0.618033988749894848204586
    assert M.FP_NEW == 1.0 - M.FP_OLD
    assert (M.SPEED_A, M.SPEED_B, M.SPEED_C) == (0.000782, 0.000819, 0.000857)
    assert M.INTENSITY == 0.0445556
    assert M.POWER_SAG == 0.003300223685324102874217
    assert M.BR_MAX == T.BR_MAX == 1.57079633   # the pinned literal, not pi/2
    assert M.BR_MAX != math.pi / 2
    assert M.HARD_CLIP == 36.0 and M.RATIO_CLAMP == 2.99999


def test_rtl_holds_no_quoted_constant_of_its_own():
    """DR-0015 s2: constants live in the model and are streamed to the RTL.

    A second copy in the SystemVerilog could drift silently; the exactness
    claim would then be checking the RTL against a model that no longer says
    the same thing.
    """
    sv = ""
    for name in sorted(os.listdir(RTL)):
        if name.endswith(".sv"):
            sv += open(os.path.join(RTL, name)).read()
    body = "\n".join(ln for ln in sv.splitlines()
                     if not ln.lstrip().startswith("//"))
    for lit in ("0.618033988749894848204586", "0.0445556",
                "0.003300223685324102874217", "0.000782", "0.000819",
                "0.000857", "2.99999"):
        assert lit not in body, "quoted constant duplicated in RTL: " + lit


# --------------------------------------------------------- fail-closed API
def test_sample_rate_other_than_48k_is_refused():
    with pytest.raises(M.Refuse):
        M.build_control(P_SEL1, sample_rate=44100)


def test_missing_null_and_out_of_range_params_are_refused():
    bad = dict(P_SEL1)
    del bad["E_mix"]
    with pytest.raises(M.Refuse):
        M.build_control(bad)
    bad = dict(P_SEL1, E_mix=None)
    with pytest.raises(M.Refuse):
        M.build_control(bad)
    bad = dict(P_SEL1, E_mix=1.5)
    with pytest.raises(M.Refuse):
        M.build_control(bad)


def test_input_beyond_the_declared_envelope_is_refused():
    m = M.Logical4Fixed(M.build_control(P_SEL1), "envelope")
    hot = a48(M.INPUT_ENVELOPE * 1.01)
    with pytest.raises(M.Refuse):
        m.process_block([hot] * M.BLOCK, [0] * M.BLOCK)


# ----------------------------------------------------- pinned-quirk proofs
def test_compacted_sag_ring_matches_pinned_indexing():
    """The 4-word ring is bit-exact against the literal 1000-word indexing.

    Two full gcount periods (1000+ samples), so BOTH wrap samples (gcount
    498 and 499, where the pinned tap is 3 samples old, not 2) are crossed
    more than once. This is what licenses reporting 818 B of state instead
    of a 6000-word allocation.
    """
    ctrl = M.build_control(P_SEL2)
    m = M.Logical4Fixed(ctrl, "pinned", pinned_lines=True)
    blocks = noise_blocks(40, seed=5)          # 1280 samples
    run(m, blocks)
    assert m.pinned_mismatch == 0
    assert m.st.tap_age3_hits > 0, "the age-3 wrap path was never exercised"


def test_pinned_tap_age_is_2_except_at_the_two_wrap_samples():
    ages = {g: M.pinned_tap_age(g) for g in range(M.GCOUNT_MAX + 1)}
    threes = sorted(g for g, a in ages.items() if a == 3)
    assert threes == [498, 499]
    assert all(a == 2 for g, a in ages.items() if g not in (498, 499))


def test_quirk_q2_stage_c_right_positive_target_is_never_written():
    """targetposCR keeps its constructor value 1.0 forever (calcpos == 1)."""
    ctrl = M.build_control(P_SEL2)
    assert ctrl["ratioselector"] == 2, "stage C must be active for this quirk"
    m = M.Logical4Fixed(ctrl, "q2")
    run(m, noise_blocks(8, seed=3))
    assert m.st.t_pos[2][1] == M.ONE_T          # untouched
    assert m.st.t_pos[2][0] != M.ONE_T          # written twice per sample
    assert m.st.t_neg[2][1] != M.ONE_T          # negative side is normal


def test_quirk_q4_stage_c_divisor_is_not_the_attack_complement():
    ctrl = M.build_control(P_SEL2)
    rem, div = ctrl["d"]["remainder"], ctrl["d"]["divisor"]
    for s in (0, 1):
        assert abs((rem[s] + div[s]) - 1.0) < 1e-15    # complementary pair
    assert abs((rem[2] + div[2]) - 1.0) > 1e-9         # stage C is not


def test_quirk_q1_and_q2_are_load_bearing_in_the_rtl_record():
    """Fixing either quirk must FAIL the RTL exactness check."""
    rec = json.load(open(os.path.join(SXT, "rtl-exactness.json")))
    byname = {c["control"]: c for c in rec["mutant_controls"]}
    for nc in ("NC_FIX_Q1", "NC_FIX_Q2"):
        assert byname[nc]["exact"] is False
        assert byname[nc]["ok"] is True


# ---------------------------------------------------------- model behaviour
def test_model_is_deterministic():
    blocks = noise_blocks(6, seed=21)
    a = run(M.Logical4Fixed(M.build_control(P_SEL1), "a"), blocks)
    b = run(M.Logical4Fixed(M.build_control(P_SEL1), "b"), blocks)
    assert a == b
    # no RNG-seeded or wall-clock state exists in this algorithm at all
    src = open(os.path.join(AW4, "logical4_model.py")).read()
    assert "random" not in src and "time(" not in src


def test_dual_instance_independent_histories():
    """Two concurrent slots keep disjoint state (AGENTS.md per-instance rule).

    Instance A is driven alone; instance B is driven with a different signal
    at the same time. A's output and state digest must be identical to a
    solo run -- i.e. B cannot reach into A.
    """
    blocks_a = noise_blocks(6, seed=31)
    blocks_b = noise_blocks(6, seed=32, amp=0.9)
    solo = M.Logical4Fixed(M.build_control(P_SEL1), "solo")
    out_solo = run(solo, blocks_a)

    a = M.Logical4Fixed(M.build_control(P_SEL1), "a")
    b = M.Logical4Fixed(M.build_control(P_SEL2), "b")
    out_a = []
    for (al, ar), (bl, br) in zip(blocks_a, blocks_b):
        out_a.append(a.process_block(al, ar))
        b.process_block(bl, br)
    assert out_a == out_solo
    assert a.st.digest() == solo.st.digest()
    assert a.st.digest() != b.st.digest()


def test_bypass_mix_zero_is_exactly_dry():
    ctrl = M.build_control(dict(P_SEL1, E_mix=0.0))
    m = M.Logical4Fixed(ctrl, "bypass")
    for bl, br in noise_blocks(4, seed=41):
        ol, orr = m.process_block(bl, br)
        assert ol == bl and orr == br


def test_reset_restores_the_constructor_state_and_drops_the_tail():
    m = M.Logical4Fixed(M.build_control(P_SEL1), "reset")
    fresh = M.Logical4Fixed(M.build_control(P_SEL1), "fresh")
    run(m, noise_blocks(4, seed=51))
    assert m.st.digest() != fresh.st.digest()
    m.reset()
    assert m.st.digest() == fresh.st.digest()


def test_patch_change_mid_tail_keeps_every_history():
    """The engine mutates FxStorage in place; the instance is not rebuilt."""
    m = M.Logical4Fixed(M.build_control(P_SEL1), "patch")
    run(m, noise_blocks(4, seed=61))
    before = m.st.digest()
    m.set_control(M.build_control(P_SEL2))
    assert m.st.digest() == before             # state survives the change


def test_tail_is_gain_recovery_not_amplitude_ringout():
    """Logical emits silence into silence: an amplitude gate would read
    'no tail'. The declared window is the control-bank recovery span."""
    ctrl = M.build_control(P_SEL1)
    m = M.Logical4Fixed(ctrl, "tail")
    run(m, noise_blocks(8, seed=71, amp=0.9))
    hot = m.st.digest()
    zero = [0] * M.BLOCK
    ol, orr = m.process_block(zero, zero)
    assert ol == zero and orr == zero          # no audible ringout at all
    assert m.st.digest() != hot                # but the gain state IS moving

    n = M.tail_window_samples(ctrl)
    slowest = min(ctrl["d"]["remainder"][:ctrl["ratioselector"] + 1])
    assert n == math.ceil(5.0 / slowest)
    assert M.tail_window_blocks(ctrl) == (n + M.BLOCK - 1) // M.BLOCK
    assert n > M.BLOCK, "a one-block render cannot contain this tail"


def test_tail_window_record_matches_the_model():
    rec = json.load(open(os.path.join(SXT, "artifacts", "tail-window.json")))
    assert rec["decades"] == 5.0
    assert "gain" in rec["definition"].lower()
    for _key, w in rec["windows"].items():
        assert w["tail_window_samples"] == math.ceil(
            5.0 / min(w["remainders_active"]))
        assert len(w["remainders_active"]) == w["ratioselector"] + 1
        assert w["tail_window_blocks"] == (w["tail_window_samples"] + 31) // 32


# ------------------------------------------------------- state accounting
def test_state_inventory_and_zero_external_memory():
    inv = M.state_inventory()
    assert inv["external_writable_memory_bytes"] == 0
    assert inv["bits_total"] == 6538 and inv["bytes_total"] == 818
    by = {f["field"]: f for f in inv["fields"]}
    assert by["control{A,B}{pos,neg} (c96)"]["count"] == 4 * 3 * 2 == 24
    assert by["target{pos,neg} (t64)"]["count"] == 2 * 3 * 2 == 12
    assert by["sag line rings (c96)"]["count"] == 3 * 2 * M.RING == 24
    rep = M.buffer_report()
    assert rep["external_traffic"] == {"reads_per_frame": 0,
                                       "writes_per_frame": 0,
                                       "bytes_per_s_per_instance": 0}
    assert rep["cost_closure"]["status"] == "[PENDING-SXT-016]"
    assert "flash" in rep["flash_note"].lower()


def test_state_cost_artifact_is_regenerable_and_current():
    art = json.load(open(os.path.join(SXT, "artifacts", "state-cost.json")))
    live = M.buffer_report()
    assert art["model_revision"] == M.model_revision(), (
        "state-cost.json is STALE: regenerate it against the frozen model")
    for k in ("external_writable_memory", "external_traffic",
              "on_chip_state_exact", "cost_closure"):
        assert art[k] == live[k]


def test_no_fit_or_cost_verdict_is_claimed():
    art = json.load(open(os.path.join(SXT, "artifacts", "state-cost.json")))
    assert art["cost_closure"]["status"] == "[PENDING-SXT-016]"
    ev = open(os.path.join(SXT, "EVIDENCE.md")).read()
    assert "[PENDING-SXT-016]" in ev


# ------------------------------------------------------------ frozen tables
def test_tables_are_derived_and_match_the_committed_rtl_roms():
    sin_t, omc_t = T.build_sin(), T.build_omc()
    assert len(sin_t) == len(omc_t) == T.TABLE_WORDS == 806
    assert T.MAX_INDEX == 804
    assert sin_t[0] == 0 and omc_t[0] == 0
    for name, tbl in (("sin_q31.hex", sin_t), ("omc_q31.hex", omc_t)):
        lines = [ln.strip() for ln in
                 open(os.path.join(RTL, name)).read().split("\n")
                 if ln.strip() and not ln.strip().startswith("//")]
        assert len(lines) == len(tbl), name
        for got, want in zip(lines, tbl):
            assert int(got, 16) == want, name


def test_table_digest_is_over_the_table_words():
    d = T.tables_digest()
    assert len(d) == 64
    h = hashlib.sha256()
    for t in (T.SIN_Q31, T.OMC_Q31):
        for v in t:
            h.update((v & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little"))
    assert d == h.hexdigest()


def test_model_revision_covers_model_and_tables():
    """The stale-stub control depends on this: editing either file must
    invalidate every committed pin."""
    rev = M.model_revision()
    assert len(rev) == 64
    h = hashlib.sha256()
    for p in ("logical4_model.py", "tables.py"):
        h.update(open(os.path.join(AW4, p), "rb").read())
    assert rev == h.hexdigest()
    assert M.revision_word() == int(rev[:8], 16)


# ------------------------------------------------ structural cross-check
def test_fixed_model_tracks_the_double_transcription_within_the_band():
    """DIAGNOSTIC ONLY -- this is NOT a reference-agreement check.

    A second double-precision transcription of the same pinned structure.
    A swapped bank, a missed clamp or a wrong stage gate diverges far beyond
    the declared quantization band; agreement here says nothing whatever
    about the pinned Surge engine (that leg is NOT_RUN).
    """
    ctrl = M.build_control(P_SEL1)
    fx = M.Logical4Fixed(ctrl, "fx")
    fl = LogicalFloat(ctrl)
    worst = 0.0
    for bl, br in noise_blocks(6, seed=81, amp=0.3):
        ol, orr = fx.process_block(bl, br)
        fl_l, fl_r = fl.process_block([f_of(v) for v in bl],
                                      [f_of(v) for v in br])
        for got, want in zip(ol + orr, fl_l + fl_r):
            worst = max(worst, abs(f_of(got) - want))
    assert worst < 1e-3, worst


def test_generic_substitute_is_labelled_adapted():
    g = GenericCompressorADAPTED(M.build_control(P_SEL1))
    assert g.is_adapted is True
    assert "generic" in g.adapted_reason.lower()


def test_float_transcription_is_never_cited_as_a_reference():
    for rel in ("EVIDENCE.md",):
        text = open(os.path.join(SXT, rel)).read()
        assert "float_transcription" not in text or "NOT" in text.upper()
    doc = open(os.path.join(AW4, "float_transcription.py")).read()
    assert "THIS IS NOT THE ORACLE" in doc


# ------------------------------------------------------ extraction records
def test_extraction_records_are_fail_closed():
    slugs = [n for n in sorted(os.listdir(INPUTS)) if n.startswith("aw-4-")]
    assert len(slugs) >= 3
    for name in slugs:
        rec = json.load(open(os.path.join(INPUTS, name)))
        s = rec["screens"]
        assert s["census_blob_reverified"] is True
        assert s["census_vs_graphs_sha_drift"] == 0          # drift asserted 0
        assert s["fx_parameter_modulation_on_own_slots"] == 0
        assert s["unmappable_fx_modulation_destinations"] == 0
        assert rec["fx_parameter_modulation"]["on_this_leafs_slots"] == []
        # no complete-wet claim is made anywhere
        assert rec["complete_wet_render_possible"] is False
        assert rec["extraction_status"].startswith("COMPLETE-FOR-MODEL")
        assert rec["model_revision"] == M.model_revision(), (
            name + " is STALE against the frozen model")
        assert "no support, fidelity or musical-quality claim" \
            in rec["claim_scope"]
        # the record round-trips into the frozen model
        for slot in rec["logical_slots"]:
            ctrl = M.build_control(slot["params"])
            assert ctrl["ratioselector"] == slot["derived"]["ratioselector"]
            assert M.tail_window_samples(ctrl) == slot["tail_window_samples"]


def test_dual_instance_carrier_exists_in_the_corpus():
    """The per-instance acceptance case is a real preset, not just synthetic."""
    hits = []
    for name in sorted(os.listdir(INPUTS)):
        if not name.startswith("aw-4-"):
            continue
        rec = json.load(open(os.path.join(INPUTS, name)))
        if rec["concurrent_logical_instances"] >= 2:
            hits.append((rec["slug"], len(rec["logical_slots"])))
    assert hits, "no dual-instance carrier recorded"
    for _slug, n in hits:
        assert n >= 2


def test_oracle_mode_refusal_transcript_is_recorded():
    txt = open(os.path.join(SXT, "artifacts",
                            "extract-refusals-oracle.txt")).read()
    assert "mode=oracle" in txt
    assert txt.count("REFUSED") >= 3
    assert "refuses rather than inventing it" in txt


# --------------------------------------------------- committed verdicts
def test_rtl_exactness_record_is_pass_and_current():
    rec = json.load(open(os.path.join(SXT, "rtl-exactness.json")))
    assert rec["leaf"] == "SXT-028k" and rec["issue"] == 63
    assert rec["model_revision"] == M.model_revision(), (
        "rtl-exactness.json is STALE against the frozen model: re-run "
        "tools/compare_rtl_model_aw4.py")
    assert rec["tables_digest"] == T.tables_digest()
    assert rec["status"] == "PASS"
    assert "NOT a reference-fidelity claim" in rec["claim"]
    sels = set()
    for case in rec["cases"]:
        assert case["exact"] is True, case["case"]
        assert case["mismatches"]["outputs"] == 0
        assert case["mismatches"]["checkpoint_fields"] == 0
        assert case["checked"]["outputs"] > 0
        assert case["revision_pin"]["ok"] is True
        sels.update(case["ratioselector"].values())
    assert {0, 1, 2} <= sels, "all three stage counts must be exercised"
    # a dual-instance case and a reset case exist
    names = {c["case"] for c in rec["cases"]}
    assert any(n.startswith("dual") for n in names)
    assert any("reset" in n for n in names)
    assert any("tail" in n for n in names)


def test_rtl_mutants_are_live_and_all_fail():
    rec = json.load(open(os.path.join(SXT, "rtl-exactness.json")))
    got = {c["control"] for c in rec["mutant_controls"]}
    assert {"NC_SHARED_STATE", "NC_SWAP_STAGES", "NC_TAIL_KILL",
            "NC_FIX_Q1", "NC_FIX_Q2"} <= got
    for c in rec["mutant_controls"]:
        assert c["exact"] is False, c["control"]
        assert c["ok"] is True
        assert (c["mismatches"]["outputs"]
                + c["mismatches"]["checkpoint_fields"]) > 0
        bs = c.get("declared_blind_spot")
        if bs is not None:
            assert "why" in bs and isinstance(bs["detected_here"], bool)
    assert rec["stale_pin_control"]["ok"] is True
    assert rec["stale_pin_control"]["status"] == "REFUSED-STALE"


def test_clean_rtl_build_defines_no_defect_macro():
    core = open(os.path.join(RTL, "logical4_core.sv")).read()
    mut = open(os.path.join(RTL, "logical4_mutants.sv")).read()
    for nc in ("NC_SHARED_STATE", "NC_SWAP_STAGES", "NC_TAIL_KILL",
               "NC_FIX_Q1", "NC_FIX_Q2"):
        assert "`define " + nc not in core
        assert "`define " + nc not in mut
    # a mutant build with no defect selected must refuse to simulate
    assert "no negative-control defect selected" in mut
    assert '`include "logical4_core.sv"' in mut


def test_model_side_negative_controls_all_live_and_failing():
    rec = json.load(open(os.path.join(SXT, "negative-controls",
                                      "negative-controls.json")))
    assert rec["status"] == "PASS"
    assert rec["model_revision"] == M.model_revision(), (
        "negative-controls.json is STALE: re-run "
        "tools/aw4_negative_controls.py")
    assert "MODEL-VS-MODEL only" in rec["claim_scope"]
    assert rec["thresholds"]["source"].startswith("[PROPOSED]")
    joined = " ".join(c["control"] for c in rec["controls"]).upper()
    for required in ("NC-A", "NC-B", "NC-C", "NC-D", "NC-E"):
        assert required in joined, required
    for c in rec["controls"]:
        assert c["ok"] is True, c["control"]
        assert "CONTROL-OK" in json.dumps(c), c["control"]
    # every issue-required control class is present and named
    assert "WRONG ORDER" in joined and "SHARED" in joined
    assert "GENERIC SUBSTITUTE" in joined and "DROPPED TAIL" in joined
    assert "STALE" in joined


def test_generic_substitute_control_refuses_original_preset_coverage():
    rec = json.load(open(os.path.join(SXT, "negative-controls",
                                      "negative-controls.json")))
    blob = json.dumps(rec).upper()
    assert "ADAPTED" in blob
    assert "COVERAGE" in blob


# ------------------------------------------- the reference leg is NOT_RUN
def test_model_vs_reference_leg_is_not_run_and_not_claimed():
    st = json.load(open(os.path.join(SXT, "artifacts", "oracle-status.json")))
    assert st["oracle_status"] == "UNAVAILABLE"
    for leg in st["legs"].values():
        assert leg["status"] in ("NOT_RUN", "BLOCKED")
    # no agreement artifact may exist while the leg has not run
    for root, _dirs, files in os.walk(SXT):
        for f in files:
            assert not f.startswith("compare-"), os.path.join(root, f)
    ev = open(os.path.join(SXT, "EVIDENCE.md")).read()
    assert "NOT_RUN" in ev
    assert "[PROPOSED, not frozen]" in ev or "[PROPOSED" in ev


def test_evidence_record_keeps_the_three_claims_separate():
    ev = open(os.path.join(SXT, "EVIDENCE.md")).read()
    for token in ("PASS", "NOT_RUN", "BLOCKED", "[PENDING-SXT-016]"):
        assert token in ev, token
    assert "musical" in ev.lower()
    # coverage is reported separately from agreement
    assert "coverage" in ev.lower()
    assert "supported" in ev.lower()


@pytest.mark.skipif(not os.environ.get("ORACLE_SURGE_DIR"),
                    reason="NOT_RUN: no pinned Surge oracle reachable "
                           "(ORACLE_SURGE_DIR unset); the model-vs-reference "
                           "leg did not run and is not a pass")
def test_model_vs_pinned_engine_agreement():  # pragma: no cover - oracle host
    pytest.fail(
        "an oracle host is present: render the fixtures and record "
        "model-vs-reference agreement in reports/SXT-028k/ before claiming "
        "anything here (tools/extract_aw4_inputs.py --mode oracle first)")


def test_license_decision_record_exists_before_merge():
    dr = os.path.join(REPO, "decision-records",
                      "0015-airwindows-logical-quoted-constants.md")
    assert os.path.exists(dr)
    text = open(dr).read()
    assert "MIT" in text and "Chris Johnson" in text
    idx = open(os.path.join(REPO, "decision-records", "README.md")).read()
    assert "0015-airwindows-logical-quoted-constants.md" in idx


def test_no_airwindows_or_surge_source_is_copied_into_the_repo():
    """Structure is cited, never copied (AGENTS.md licensing rule).

    Citing a pinned function by name in prose is fine; a transcribed C++
    body is not. These needles only appear in copied source.
    """
    needles = ("void Logical4::", "vst_strncpy", "AudioEffectX(",
               "audioMasterCallback audioMaster)", "VstInt32 sampleFrames")
    paths = []
    for root, dirs, files in os.walk(AW4):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        paths += [os.path.join(root, f) for f in files]
    paths += [os.path.join(RTL, f) for f in os.listdir(RTL)
              if f.endswith(".sv")]
    for p in paths:
        text = open(p, errors="ignore").read()
        for n in needles:
            assert n not in text, "%s in %s" % (n, p)
