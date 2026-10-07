"""SXT-030 (#316) external-memory service/stall instrumentation (pytest).

Simulation only. Maps each Acceptance bullet of #316 to an assertion:

  * in-budget run: STALL_FRAMES == 0, no strobe, comparison PASS
  * M2 over-subscription: all three witnesses fire and agree on the frames
  * M1 ladder: the stalling rung is recorded; the ladder reaches a stall
  * deadline-miss output is the held sample, and the silence mutant FAILs
  * zero-counter mutants are refused (NO_VERDICT), never passed
  * the never-engaging M2 throttle mutant FAILs
  * edge cases: stall in frame 0, FIRST_STALL_FRAME stickiness, saturation,
    counter reset

Simulator-dependent tests are SKIPPED with a NOT_RUN reason when iverilog is
absent -- a skip, never a silent pass. The gate-logic and mutant-shape tests
need no simulator.
"""
import copy
import json
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import make_sxt030_mutants as mk  # noqa: E402
from tools import sxt030_stall_bench as bench  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAVE_IVERILOG = shutil.which("iverilog") is not None and \
    shutil.which("vvp") is not None
needs_sim = pytest.mark.skipif(
    not HAVE_IVERILOG,
    reason="NOT_RUN: iverilog/vvp not available; SXT-030 simulation not "
           "executed (not a pass)")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    return bench.run_all(str(tmp_path_factory.mktemp("sxt030")))


# ------------------------------------------------------------ no simulator
def test_committed_mutants_are_exact_generated_mutations():
    src = open(bench.DUT).read()
    for name, spec in mk.MUTANTS.items():
        path = os.path.join(mk.RTL_DIR, name)
        assert open(path).read() == mk.render(name, src), name
        body = open(path).read().split("module ext_mem_instr")[1]
        for old, new in spec["replacements"]:
            assert body.count(new) == 1 and old not in body, (name, old)
    # the real design carries each mutation site exactly once
    for site in (mk.HOLD, mk.COUNT, mk.LATCH):
        assert src.count(site) == 1


def test_predictor_makes_a_held_sample_detectable():
    prev = None
    for n in range(256):
        cur = bench.predict(n)
        assert 0 not in cur                    # normal path never silent
        assert cur != prev                     # a held frame is visible
        prev = cur
    assert bench.HOLD_RESET != 0
    assert bench.predict(0) != (bench.HOLD_RESET, bench.HOLD_RESET)


def test_ladder_matches_procedure_table():
    # §9.2 M1 ladder; L1 = #12's modeled worst case 696 B per 48 kHz frame
    assert [w for _, w in bench.LADDER] == [0, 174, 348, 696, 1392, 2784]
    assert dict(bench.LADDER)["L1"] * 4 == 696
    assert dict(bench.LADDER)["L1"] * 4 * 48000 == 33408000
    # M2's tight window is provably below the fixture's need
    assert bench.M2_TIGHT_WINDOW < bench.FIX_WORDS * (bench.MEM_LAT + 1)


def _w(**kw):
    w = {"integrity": [], "counters": {
            "STALL_FRAMES": 0, "STALL_CYCLES_MAX": 0, "FIRST_STALL_FRAME": 0,
            "FIRST_STALL_VALID": 0, "OUTPUT_FAULT": 0,
            "STALL_FRAMES_SATURATED": 0},
         "counters_fire": False, "strobe_frames": [], "stall_led_pin": 0,
         "strobe_fire": False, "residual_frames": [], "dropout_frames": [],
         "comparison": "PASS", "audio_fire": False, "silent": False,
         "held_policy_violations": []}
    w.update(kw)
    return w


def _stalled(frames=(3, 4)):
    f = list(frames)
    return _w(counters={"STALL_FRAMES": len(f), "STALL_CYCLES_MAX": 9,
                        "FIRST_STALL_FRAME": f[0], "FIRST_STALL_VALID": 1,
                        "OUTPUT_FAULT": 1, "STALL_FRAMES_SATURATED": 0},
              counters_fire=True, strobe_frames=f, stall_led_pin=1,
              strobe_fire=True, residual_frames=f, comparison="FAIL",
              audio_fire=True)


def test_gate_branches_on_synthetic_witnesses():
    inb = _w()
    assert bench.nc1_gate(inb, _stalled())["verdict"] == "PASS"
    # counters fire but the audio comparison passes: too weak, not a PASS
    weak = _stalled()
    weak.update(residual_frames=[], comparison="PASS", audio_fire=False)
    assert bench.nc1_gate(inb, weak)["verdict"] == "FAIL"
    # degraded with zero counters -> refused
    zero = _w(residual_frames=[3], comparison="FAIL", audio_fire=True)
    assert bench.nc1_gate(inb, zero)["verdict"] == "NO_VERDICT"
    silent_zero = _w(dropout_frames=[3], silent=True)
    assert bench.nc1_gate(inb, silent_zero)["verdict"] == "NO_VERDICT"
    # a degraded in-budget take with zero counters is refused too
    assert bench.nc1_gate(zero, _stalled())["verdict"] == "NO_VERDICT"
    # integrity failure -> refused
    bad = _stalled()
    bad["integrity"] = ["BUILD_ID mismatch"]
    assert bench.nc1_gate(inb, bad)["verdict"] == "NO_VERDICT"
    # witnesses disagree on the frame range
    dis = _stalled()
    dis["strobe_frames"] = [3, 5]
    assert bench.nc1_gate(inb, dis)["verdict"] == "FAIL"
    # silence with counters firing violates the policy
    sil = _stalled()
    sil.update(dropout_frames=[3, 4], silent=True)
    assert bench.nc1_gate(inb, sil)["verdict"] == "FAIL"
    held = _stalled()
    held["held_policy_violations"] = [3]
    assert bench.nc1_gate(inb, held)["verdict"] == "FAIL"
    # an in-budget take that stalls cannot anchor the control
    assert bench.nc1_gate(_stalled(), _stalled())["verdict"] == "FAIL"
    # nothing fires at all: over-subscription was never achieved
    assert bench.nc1_gate(inb, _w())["verdict"] == "FAIL"


def test_committed_record_names_current_sources_and_no_hw_claim():
    rec = json.load(open(bench.RESULTS))
    for rel, digest in rec["sources_sha256"].items():
        assert bench.sha256_file(os.path.join(REPO, rel)) == digest, \
            "STALE: %s changed since bench-results.json was written" % rel
    assert rec["scope"].startswith("SIMULATION ONLY")
    ev = open(os.path.join(REPO, "reports", "SXT-030", "EVIDENCE.md")).read()
    for row in ("Live hardware measurement", "FPGA synthesis",
                "Latency / underrun"):
        line = [ln for ln in ev.splitlines() if ln.startswith("| " + row)]
        assert line and "NOT_RUN" in line[0], row


# ------------------------------------------------------------ simulation
@needs_sim
def test_in_budget_run(results):
    t = results["takes"]["in_budget"]
    assert t["integrity"] == []
    assert t["counters"]["STALL_FRAMES"] == 0
    assert t["strobe_frames"] == [] and t["stall_led_pin"] == 0
    assert t["counters"]["OUTPUT_FAULT"] == 0
    assert t["comparison"] == "PASS"
    assert t["counters"]["FRAME_COUNT"] == 24
    assert t["counters"]["EXT_WORDS_RD"] == 24 * 4
    assert t["counters"]["EXT_WORDS_WR"] == 24 * 2
    # per-instance tagging: two instances, two separate histories
    assert t["counters"]["EXT_WORDS_WR_TAG"] == [24, 24, 0]


@needs_sim
def test_m2_all_three_witnesses_fire_and_agree(results):
    t = results["takes"]["m2_throttle"]
    cmd = t["commanded_frames"]
    assert t["integrity"] == []
    assert t["counters_fire"] and t["strobe_fire"] and t["audio_fire"]
    assert t["strobe_frames"] == t["residual_frames"] == cmd
    assert t["counters"]["FIRST_STALL_FRAME"] == cmd[0]
    assert t["counters"]["STALL_FRAMES"] == len(cmd)
    assert t["counters"]["STALL_CYCLES_MAX"] > 0
    assert results["gates"]["NC1_M2"]["verdict"] == "PASS"


@needs_sim
def test_deadline_miss_holds_the_previous_sample_not_silence(results):
    t = results["takes"]["m2_throttle"]
    assert not t["silent"] and t["dropout_frames"] == []
    assert t["held_policy_violations"] == []
    assert t["stuck_frames"] == t["commanded_frames"]
    c = results["controls"]["silence_on_miss"]
    assert c["gate"]["verdict"] == "FAIL"
    assert c["over_take"]["silent"]
    assert any("silent" in r for r in c["gate"]["reasons"])


@needs_sim
def test_m1_ladder_reaches_a_stall_and_records_the_rung(results):
    lad = results["ladder"]
    rungs = {r["rung"]: r for r in lad["rungs"]}
    assert lad["first_stalling_rung"] is not None
    assert rungs[lad["first_stalling_rung"]]["stall_frames"] > 0
    # every rung below the stalling one ran clean, and the ladder climbed
    # through L1 (the 696 B/frame modeled worst case)
    assert "L1" in rungs
    for r in lad["rungs"][:-1]:
        assert r["stall_frames"] == 0 and r["comparison"] == "PASS"
    assert results["gates"]["NC1_M1"]["verdict"] == "PASS"


@needs_sim
def test_zero_counter_builds_are_refused(results):
    for name in ("zero_counters", "silence_zero_counters"):
        c = results["controls"][name]
        assert c["gate"]["verdict"] == "NO_VERDICT", name
        assert c["over_take"]["counters"]["STALL_FRAMES"] == 0
        assert c["over_take"]["audio_fire"]       # output did degrade
    assert results["controls"]["silence_zero_counters"]["over_take"]["silent"]


@needs_sim
def test_never_engaging_throttle_fails(results):
    c = results["controls"]["throttle_never_engages"]
    assert c["gate"]["verdict"] == "FAIL"
    assert not c["over_take"]["counters_fire"]


@needs_sim
def test_build_id_mismatch_is_refused(results):
    assert results["controls"]["build_id_mismatch"]["gate"]["verdict"] == \
        "NO_VERDICT"


@needs_sim
def test_every_control_meets_its_expected_verdict(results):
    for name, c in results["controls"].items():
        assert c["control_status"] == "PASS", (name, c["gate"])


@needs_sim
def test_edge_stall_in_frame0(results):
    t = results["takes"]["edge_stall_in_frame0"]
    assert t["counters"]["FIRST_STALL_FRAME"] == 0
    assert t["counters"]["FIRST_STALL_VALID"] == 1
    assert t["strobe_frames"] == [0, 1, 2]
    assert t["held_policy_violations"] == [] and not t["silent"]


@needs_sim
def test_edge_first_stall_frame_is_sticky_across_bursts(results):
    t = results["takes"]["edge_two_bursts"]
    assert t["strobe_frames"] == [3, 4, 9, 10, 11]
    assert t["counters"]["FIRST_STALL_FRAME"] == 3
    assert t["counters"]["STALL_FRAMES"] == 5
    assert results["gates"]["NC1_edge_two_bursts"]["verdict"] == "PASS"


@needs_sim
def test_edge_stall_frames_saturates(results):
    t = results["takes"]["edge_saturation_stall_w3"]
    assert len(t["strobe_frames"]) == 12
    assert t["counters"]["STALL_FRAMES"] == 7          # 3-bit saturation
    assert t["counters"]["STALL_FRAMES_SATURATED"] == 1


@needs_sim
def test_counters_clear_on_reset_in_every_real_take(results):
    # take integrity includes "post-take reset clears every counter/status"
    for name, t in results["takes"].items():
        assert t["integrity"] == [], name


@needs_sim
def test_committed_results_are_current(results):
    rec = json.load(open(bench.RESULTS))
    fresh = json.loads(json.dumps(bench.results_record(copy.deepcopy(
        results)), sort_keys=True))
    assert rec == fresh, ("STALE: reports/SXT-030/bench-results.json; "
                          "re-run python3 tools/sxt030_stall_bench.py --write")
