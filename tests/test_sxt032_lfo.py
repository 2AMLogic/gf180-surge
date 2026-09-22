"""SXT-032 LFO slice tests (pytest).

Covers: frozen LFO fixed-point arithmetic (phase wrap, warp lookup bounds),
the LFO-EG state machine, waveform evaluation, per-instance state separation,
fail-closed parameter gates, the runner's negative-control switches, and the
exactness comparator's mismatch detection — without requiring the oracle or
iverilog.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import lfo_model as lm  # noqa: E402
from tools.compare_lfo_rtl_model import compare, parse_tb  # noqa: E402


def make_params(**over):
    d = {"shape": 0, "rate": 0.0, "start_phase": 0.0, "magnitude": 1.0,
         "deform": 0.0, "trigmode": 1, "unipolar": 0, "delay": -8.0,
         "attack": -8.0, "hold": -8.0, "decay": 0.0, "sustain": 1.0,
         "release": 5.0}
    d.update(over)
    return lm.LfoParams(d)


def test_warp_sine_lookup_bounds_and_symmetry():
    # x = 2 (phase 0) -> table index wraps to T[0..1] ~ sin(-pi) ~ 0
    hi = lm.warp_sine_lookup(lm.W_ONE << 1)
    assert abs(hi) < 64                      # |sin(pi)|*2^21 << 1 LSB slack
    # x = 1 (phase 0.25) -> sin(pi/2) = 1.0
    mid = lm.warp_sine_lookup(lm.W_ONE)
    assert abs(mid - (1 << lm.FQ)) <= 64
    # x = 0 -> 0 ; x = -1 -> -1.0
    assert abs(lm.warp_sine_lookup(0)) < 64
    assert abs(lm.warp_sine_lookup(-lm.W_ONE) + (1 << lm.FQ)) <= 64


def test_sine_lfo_full_cycle_and_phase_wrap():
    p = make_params()
    lfo = lm.Lfo(p, 0)
    lfo.attack()
    vals = [lfo.process_block() for _ in range(1510)]
    # rate 0 = 1 Hz: envrate(0) = 64/96000 per block -> period 1500 blocks
    assert 0 <= lfo.phase < (1 << lm.F_PHASE)          # wrapped, in range
    assert 0 < vals[0] < (1 << 16)                     # just after sin(0)
    assert vals[375] > (1 << 20)                       # near +1 at quarter
    assert vals[750] < 0 and abs(vals[750]) < (1 << 16)  # past zero, falling


def test_lfo_eg_instant_decay_to_sustain():
    p = make_params(sustain=0.5)
    lfo = lm.Lfo(p, 0)
    lfo.attack()
    assert lfo.env_state == lm.EG_DECAY       # delay/attack/hold at min
    assert lfo.env_val == 1 << lm.F_PHASE     # decay starts from full scale
    for _ in range(2000):                     # decay 0 -> ~1 s ramp
        lfo.process_block()
    assert lfo.env_state == lm.EG_STUCK
    assert lfo.env_val == p.env["sustain"]


def test_lfo_eg_release_gated_by_release_param():
    stuck = make_params(release=8.0)          # val_max: release() is a no-op
    l1 = lm.Lfo(stuck, 0)
    l1.attack()
    l1.release()
    assert l1.env_state != lm.EG_RELEASE
    active = make_params(release=5.0)
    l2 = lm.Lfo(active, 0)
    l2.attack()
    l2.process_block()
    l2.release()
    assert l2.env_state == lm.EG_RELEASE
    out0 = l2.output
    prev = l2.env_val
    decaying = True
    for _ in range(60000):                    # release 5.0 -> ~32 s tail
        l2.process_block()
        if l2.env_state == lm.EG_RELEASE:
            decaying &= l2.env_val <= prev
            prev = l2.env_val
    assert decaying and l2.output == 0 and out0 != 0


def test_per_instance_state_never_merged():
    a = make_params(rate=2.0)
    b = make_params(rate=-3.0)
    la, lb = lm.Lfo(a, 0), lm.Lfo(b, 1)
    la.attack()
    lb.attack()
    for _ in range(64):
        la.process_block()
        lb.process_block()
    assert la.phase != lb.phase               # distinct rates diverge
    assert la.output != lb.output


def test_fail_closed_param_gates():
    for bad in ({"shape": 4}, {"shape": 7}, {"shape": 8}, {"shape": 9},
                {"trigmode": 2}):
        try:
            make_params(**bad)
            raise AssertionError(f"{bad} should have been refused")
        except RuntimeError:
            pass
    try:
        make_params(shape=1, deform=-0.17)    # type_3 bend needs runtime sin
        raise AssertionError("tri deform should have been refused")
    except RuntimeError:
        pass
    make_params(shape=2, deform=0.3)          # square deform is in scope


def test_keytrigger_phase_restart_and_shape_adjustment():
    p = make_params(shape=1, start_phase=0.1)  # tri, bipolar: +0.25 at attack
    lfo = lm.Lfo(p, 0)
    for _ in range(50):
        lfo.process_block()
    lfo.attack()                              # re-attack restarts + adjustment
    expected = (int(0.1 * (1 << lm.F_PHASE))
                + ((1 << lm.F_PHASE) >> 2)) % (1 << lm.F_PHASE)
    assert lfo.phase == expected


def test_free_running_mutant_derives_phase_from_clock():
    p = make_params(rate=0.0)
    lm.MUTANT_FREE_RUNNING = True
    try:
        lm.BLOCK_CLOCK = 1500                 # exactly one period in
        lfo = lm.Lfo(p, 0)
        lfo.attack()
        # t=0-anchored phase after exactly one period is back at start (0)
        assert lfo.phase < 128 or lfo.phase > (1 << lm.F_PHASE) - 128
        lm.BLOCK_CLOCK = 375                  # quarter period
        lfo2 = lm.Lfo(p, 0)
        lfo2.attack()
        assert lfo2.output == 0               # fresh instance, not processed
        quarter = int(0.25 * (1 << lm.F_PHASE))
        assert abs(lfo2.phase - quarter) < 128
        assert lfo2.phase != lfo.phase
    finally:
        lm.MUTANT_FREE_RUNNING = False
        lm.BLOCK_CLOCK = 0


def test_comparator_detects_route_sum_mismatch():
    model_trace = {"blocks": [{"b": 0, "voices": [{
        "slot": 0, "lfo": [{"index": 0, "phase": 715827, "env_state": 4,
                            "env_phase": 95444, "env_val": 536404660,
                            "output": 25718}],
        "lfo_route_sums": [1671670, 12859]}]}]}
    tb_l = {(0, 0, 0): dict(zip(
        ["b", "slot", "index", "phase", "env_state", "env_phase", "env_val",
         "output"], [0, 0, 0, 715827, 4, 95444, 536404660, 25718]))}
    tb_s = {(0, 0): [1671670, 12858]}         # 1 LSB off on reso sum
    checked, fails = compare(model_trace, (tb_l, tb_s))
    assert checked["route_sums"] == 1 and fails


def test_comparator_passes_on_identical_traces():
    model_trace = {"blocks": [{"b": 0, "voices": [{
        "slot": 0, "lfo": [{"index": 0, "phase": 715827, "env_state": 4,
                            "env_phase": 95444, "env_val": 536404660,
                            "output": 25718}],
        "lfo_route_sums": [1671670, 12859]}]}]}
    row = dict(zip(["b", "slot", "index", "phase", "env_state", "env_phase",
                    "env_val", "output"],
                   [0, 0, 0, 715827, 4, 95444, 536404660, 25718]))
    checked, fails = compare(model_trace, ({(0, 0, 0): row},
                                           {(0, 0): [1671670, 12859]}))
    assert not fails and checked["lfo_checkpoints"] == 1
