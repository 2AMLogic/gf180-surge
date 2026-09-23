"""SXT-028a Airwindows Galactic (id 49) tests (pytest).

Covers: frozen arithmetic helpers, coefficient-plane bounds, model
determinism + per-instance independence, external-memory traffic accounting
(54 words/frame), the buffer requirement, negative-control evidence
integrity, and the committed comparison/RTL-exactness records (fail-closed).
The oracle-dependent reference legs run via tools/render_aw49_reference.py
and tools/compare_aw49_reference.py on the oracle host; here we only check
the committed evidence records for coherence. RTL exactness requires
iverilog (tools/compare_rtl_model_aw49.py) and is checked via its committed
record; a missing oracle/iverilog makes those legs NOT_RUN, never a pass.
"""
import json
import os
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "aw-49"))

import galactic_model as gm  # noqa: E402

SXT = os.path.join(REPO, "reports", "sxt-028a")


# ---------------------------------------------------------------- helpers
def test_rnd_round_half_up_matches_sv_shift():
    assert gm.rnd(15, 4) == 1           # round-half-up: 0.9375 -> 1
    assert gm.rnd(7, 4) == 0            # 0.4375 -> 0
    assert gm.rnd(-1, 4) == 0           # -1 + 8 = 7 >> 4 = 0 (floor)
    assert gm.rnd(-9, 4) == -1
    assert gm.rnd((1 << 31), 31) == 1


def test_sat32_bounds():
    assert gm.sat32(1 << 40) == gm.S32_MAX
    assert gm.sat32(-(1 << 40)) == gm.S32_MIN
    assert gm.sat32(5) == 5


def test_f32_to_s32i_exact_for_loud_values():
    assert gm.f32_to_s32i(0.5) == 1 << 24        # Q6.25
    assert gm.f32_to_s32i(-0.5) == -(1 << 24)
    assert abs(gm.f32_to_s32i(0.001) - int(0.001 * (1 << 25) + 0.5)) <= 1


def test_quoted_delay_constants_and_layout():
    # the twelve designed integers, quoted per decision-records/0006
    assert [gm.DELAY_MULT[n][1] for n in
            ("I", "J", "K", "L", "A", "B", "C", "D", "E", "F", "G", "H")] == \
        [3407.0, 1823.0, 859.0, 331.0, 4801.0, 2909.0, 1153.0, 461.0,
         7607.0, 4217.0, 2269.0, 1597.0]
    assert gm.EXT_WORDS == 126354
    assert gm.AM_WORDS == 257


def test_control_plane_derives_formula_coefficients():
    c = gm.build_control({"a": 0.5, "b": 0.5, "c": 0.5, "d": 1.0, "e": 1.0},
                         {"fpdL": 1, "fpdR": 2})
    assert abs(c["regen_d"] - 0.09375) < 1e-15
    assert abs(c["attenuate_d"] - 0.33325) < 1e-12
    assert abs(c["wet_d"] - 1.0) < 1e-15 and c["wet_active"] is False
    assert c["delays"]["I"] == int(3407.0 * 1.87)
    saved = gm.SAMPLE_RATE
    try:
        gm.SAMPLE_RATE = 96000
        with pytest.raises(NotImplementedError):
            gm.build_control({"a": 0.5, "b": 0.5, "c": 0.5, "d": 1.0,
                              "e": 1.0}, {"fpdL": 1, "fpdR": 2})
    finally:
        gm.SAMPLE_RATE = saved


def test_model_traffic_per_frame_and_determinism():
    c = gm.build_control({"a": 0.5, "b": 0.5, "c": 0.5, "d": 1.0, "e": 1.0},
                         {"fpdL": 101, "fpdR": 202})
    outs = []
    for _ in range(2):
        m = gm.Galactic49Fixed(c)
        blk = [(37 * (i % 32)) % (1 << 25) - (1 << 24) for i in range(32)]
        ol, orr = m.process_block(blk, blk)
        outs.append((ol, orr, m.checkpoint(), m.buffer_digest(),
                     m.ext_reads, m.ext_writes))
    assert outs[0] == outs[1]
    assert outs[0][4] == 32 * 28 and outs[0][5] == 32 * 26  # 1 block


def test_dual_instance_independent_histories():
    c0 = gm.build_control({"a": 0.5, "b": 0.5, "c": 0.5, "d": 1.0, "e": 1.0},
                          {"fpdL": 101, "fpdR": 202})
    c1 = gm.build_control({"a": 0.2, "b": 0.7, "c": 0.4, "d": 0.8, "e": 0.9},
                          {"fpdL": 303, "fpdR": 404})
    m0 = gm.Galactic49Fixed(c0, mem_base=0)
    m1 = gm.Galactic49Fixed(c1, mem_base=gm.EXT_WORDS)
    rs = np.random.RandomState(9)
    for _ in range(16):
        blk = list(map(int, rs.randint(-(1 << 24), 1 << 24, 32)))
        m0.process_block(blk, blk)
        m1.process_block(blk[::-1], blk)
    assert m0.buffer_digest() != m1.buffer_digest()
    assert m0.mem_base != m1.mem_base
    # disjoint addressing
    seen = []
    m1.attach_ext_memory(lambda a: seen.append(a) or 0, lambda a, v: seen.append(a))
    blk = [1 << 20] * 32
    m1.process_block(blk, blk)
    assert all(gm.EXT_WORDS <= a < 2 * gm.EXT_WORDS for a in seen)


def test_tail_decays_to_silence():
    c = gm.build_control({"a": 0.5, "b": 0.5, "c": 0.5, "d": 1.0, "e": 1.0},
                         {"fpdL": 101, "fpdR": 202})
    m = gm.Galactic49Fixed(c)
    rs = np.random.RandomState(4)
    for _ in range(64):
        blk = list(map(int, rs.randint(-(1 << 24), 1 << 24, 32)))
        m.process_block(blk, blk)
    late = 0.0
    for _ in range(250):   # 8 s tail
        ol, orr = m.process_block([0] * 32, [0] * 32)
        late = max(late, max(abs(v) for v in ol + orr))
    assert late < (1 << 20)   # < 2^-5 after 8 s (loop bounded; tails decay
    # to silence - measured envelope in EVIDENCE.md)


# ------------------------------------------------- committed evidence
def test_committed_reference_comparisons_coherent():
    comp = os.path.join(SXT, "artifacts")
    files = [f for f in os.listdir(comp)
             if f.startswith("compare-") and f.endswith(".json")]
    assert files, "no committed reference comparisons"
    for fn in files:
        d = json.load(open(os.path.join(comp, fn)))
        assert d["verdict"].startswith("PASS"), fn
        assert d["achieved"]["max_abs_diff"] <= d["proposed_budgets"][
            "max_abs_diff"], fn
        assert d["state_diagnostics"]["countM_agree"] is True, fn
        assert d["tail"]["tail_present"] is True, fn


def test_negative_controls_all_fail_their_checks():
    d = json.load(open(os.path.join(SXT, "negative-controls",
                                    "negative-controls.json")))
    assert d["status"] == "PASS"
    assert len(d["controls"]) >= 5
    for c in d["controls"]:
        assert c["ok"] is True and "CONTROL-OK" in c["verdict"], c["control"]


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    for c in d["cases"]:
        assert c["exact"] is True, c["case"]
        assert c["revision_pin"]["ok"] is True, c["case"]
    for m in d["mutant_controls"]:
        assert m["exact"] is False and "CONTROL-OK" in m["verdict"], \
            m["case"]


def test_buffer_report_matches_model():
    br = gm.buffer_report()
    assert br["external_writable_memory"]["words_total"] == gm.EXT_WORDS
    assert br["external_traffic_per_frame"]["words"] == 54
    assert br["external_traffic_per_frame"]["reads"] == 28
    assert br["external_traffic_per_frame"]["writes"] == 26
    d = json.load(open(os.path.join(SXT, "artifacts",
                                    "buffer-requirement.json")))
    assert d["external_writable_memory"]["words_total"] == gm.EXT_WORDS


def test_headroom_evidence():
    d = json.load(open(os.path.join(SXT, "artifacts", "headroom.json")))
    assert d["q6_25_saturations_full_canonical"] == 0
    assert d["peak_internal_state_q6_25"] < 32.0


def test_neutrality_gates_in_sidecars():
    fdir = os.path.join(SXT, "fixtures")
    sidecars = [f for f in os.listdir(fdir) if f.endswith(".json")]
    assert len(sidecars) >= 5
    for fn in sidecars:
        d = json.load(open(os.path.join(fdir, fn)))
        g = d["neutrality_gate"]
        assert g["probe_deterministic_taps_off_x2"] is True, fn
        assert g["probe_taps_on_eq_taps_off"] is True, fn
        assert g["cross_build_baseline_eq"] is True, fn


def test_extraction_applicability_fail_closed():
    for slug in ("temple", "unity", "fmod09"):
        d = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs",
                                        f"aw-49-{slug}.json")))
        assert d["applicability"]["complete_wet_render_possible"] is False
        assert d["aw49_slot"] >= 0
        assert d["repeatability_class"]["bit_identical"] is False
    assert not os.path.exists(os.path.join(REPO, "model", "effects",
                                           "fx_inputs", "aw-49-sine_lead.json"))
