"""SXT-024 Reverb1 tests (pytest).

Covers: frozen arithmetic helpers, coefficient-plane quantization bounds,
model determinism and checkpoint shape, external-memory traffic accounting
(34 words/frame), the buffer-requirement invariants, and the committed
comparison/negative-control evidence files' integrity (fail-closed: a
missing or self-inconsistent evidence file fails). The RTL exactness suite
itself requires iverilog and runs via tools/run_reverb_rtl.py; here we only
check its committed evidence record for coherence.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "model", "effects", "reverb1"))

import reverb1_fixed as rf  # noqa: E402
import coefficient_plane as cp  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SXT = os.path.join(REPO, "reports", "sxt-024")


def test_rnd_round_half_up_matches_sv_shift():
    # (x + 2^(f-1)) >>> f with floor semantics, negative values included
    assert rf.rnd(15, 4) == 1
    assert rf.rnd(7, 4) == 0
    assert rf.rnd(-1, 4) == 0            # -1 + 8 = 7 >> 4 = 0
    assert rf.rnd(-9, 4) == -1           # -9 + 8 = -1 >> 4 = -1 (floor)
    assert rf.rnd(1 << 31, 31) == 1


def test_sat32_bounds():
    assert rf.sat32(1 << 40) == rf.S32_MAX
    assert rf.sat32(-(1 << 40)) == rf.S32_MIN
    assert rf.sat32(5) == 5


def test_q31_quantization():
    assert rf.q31(1.0) == (1 << 31) - 1  # saturated at +1.0
    assert rf.q31(0.5) == 1 << 30
    assert abs(rf.q31(0.70710678) - int(0.70710678 * (1 << 31))) <= 1


def test_coefficient_plane_tables_are_cited_constants():
    # the four shape tables must match the pinned loadpreset tables
    assert len(cp.DELAY_TIME_TABLES) == 4
    for shape, tab in cp.DELAY_TIME_TABLES.items():
        assert len(tab) == 16
        assert all(780000 <= v <= 2720000 for v in tab), shape
    # roomsize rescale per pinned loadpreset(): (int)(2*roomsize * v)
    dt = cp.delay_times(0, 0.5)
    assert dt[0] == int(1.0 * 1339934)
    pan_l, pan_r = cp.pan_gains()
    # t=0: xbp=-1 -> pan_L = sqrt(0.995), pan_R = sqrt(0.005)
    assert abs(pan_l[0] - 0.9974969) < 1e-6 and abs(pan_r[0] - 0.0707107) < 1e-6


def test_model_reset_and_traffic_per_frame():
    params = {"predelay": -4.0, "shape": 0.0, "roomsize": 0.5,
              "decaytime": 0.0, "damping": 0.2, "lowcut": -24.0,
              "freq1": 0.0, "gain1": 0.0, "highcut": 64.0, "mix": 0.5,
              "width": 0.0}
    c = cp.build(params)
    m = rf.Reverb1Fixed(c)
    blk = [0] * rf.BLOCK
    m.process_block(blk, blk)
    assert m.ext_reads == 17 * rf.BLOCK
    assert m.ext_writes == 17 * rf.BLOCK
    m.reset()
    assert m.ext_reads == 0 and m.ext_writes == 0
    assert m.delay_pos == 0 and all(v == 0 for v in m.out_tap)
    ck = m.checkpoint()
    assert set(ck) == {"delay_pos", "out_tap", "regs"}
    assert len(ck["regs"]) == 6 and sum(len(r) for r in ck["regs"]) == 12


def test_model_deterministic_and_checkpoint_stable():
    params = {"predelay": -4.0, "shape": 1.0, "roomsize": 0.7,
              "decaytime": 1.0, "damping": 0.3, "lowcut": -30.0,
              "freq1": 1.0, "gain1": 3.0, "highcut": 40.0, "mix": 0.8,
              "width": 2.0}
    c = cp.build(params)
    outs = []
    for _ in range(2):
        m = rf.Reverb1Fixed(c)
        blk = [(37 * (i % 32)) % 8000000 - 4000000 for i in range(rf.BLOCK)]
        ol, orr = m.process_block(blk, blk)
        outs.append((ol, orr, m.checkpoint(), m.buffer_digest()))
    assert outs[0] == outs[1]


def test_ext_memory_hook_addresses_within_region():
    params = {"predelay": -4.0, "shape": 2.0, "roomsize": 1.0,
              "decaytime": 2.0, "damping": 0.5, "lowcut": -24.0,
              "freq1": 0.0, "gain1": 0.0, "highcut": 72.0, "mix": 1.0,
              "width": 0.0}
    c = cp.build(params)
    m = rf.Reverb1Fixed(c)
    seen = []
    m.attach_ext_memory(lambda a: (seen.append(("R", a)) or m._ext(a)),
                        lambda a, v: (seen.append(("W", a)) or m._ext(a, v)))
    m.process_block([1000] * rf.BLOCK, [-1000] * rf.BLOCK)
    taps = [a for d, a in seen if a < rf.TAP_WORDS]
    pd = [a for d, a in seen if a >= rf.TAP_WORDS]
    # 16 reads + 16 writes per sample hit the tap region; 1+1 the predelay
    assert len(taps) == 32 * rf.BLOCK and len(pd) == 2 * rf.BLOCK
    assert all(0 <= a < rf.TAP_WORDS + rf.MAX_REV_DLY for a in
               [a for _, a in seen])


def test_committed_evidence_files_are_coherent():
    # comparison records: every committed case's checks all true (or the
    # case carries an explicit status/finding)
    comp = os.path.join(SXT, "comparison")
    for fn in os.listdir(comp):
        if not fn.endswith(".json"):
            continue
        d = json.load(open(os.path.join(comp, fn)))
        if str(d.get("status", "")).startswith("BLOCKED"):
            # documented limitation record (e.g. the loadPatch oracle probe):
            # must carry a finding, never silent
            assert d.get("finding"), fn
            continue
        if "checks" not in d:
            raise AssertionError(f"{fn}: missing checks")
        for k, v in d["checks"].items():
            if v is False and not ("proposed_budget_finding" in d
                                   and k == "tail_rms_rel"):
                raise AssertionError(f"{fn}: check {k} is False without a "
                                     f"recorded finding")
            if v is None and not fn.startswith("sweep-t60"):
                # sweep-t60 records NOT_RUN fits as None by design (documented
                # in the comparison module docstring); no other case may
                raise AssertionError(f"{fn}: check {k} is None (NOT_RUN "
                                     f"must be recorded as a finding, not "
                                     f"in checks)")
    # negative controls: all must be CONTROL-OK
    for fn in os.listdir(os.path.join(SXT, "negative-controls")):
        d = json.load(open(os.path.join(SXT, "negative-controls", fn)))
        assert "CONTROL-OK" in d.get("verdict", ""), fn
    # RTL exactness record: status PASS and mutant failed
    rtl = json.load(open(os.path.join(SXT, "rtl-exactness.json")))
    assert rtl["status"] == "PASS"
    assert "CONTROL-OK" in rtl["mutant_control"]["verdict"]
    for c in rtl["cases"]:
        assert c["exact"] is True, c["case"]
        assert c["rtl_measured_traffic"]["words_per_frame"] % 34 == 0
    # buffer requirement: total words and traffic reconcile
    br = json.load(open(os.path.join(SXT, "buffer-requirement.json")))
    taps = br["external_writable_memory"]["composite_taps"]["words"]
    pd = br["external_writable_memory"]["predelay_line"]["words"]
    assert taps == 16 * 32768 and pd == 32768
    assert taps + pd == 557056
    assert br["external_traffic"]["words_per_sample_32bit"] == 34.0
    assert br["sxt016_reconciliation"]["agreement"] is True
    # stability: worst-case rho < 1 and headroom respected
    sa = json.load(open(os.path.join(SXT, "stability-analysis.json")))
    assert sa["worst_case"]["rho"] < 1.0
    assert sa["empirical_worst_case_140s"]["peak_state_q4_28"] < (1 << 31)
