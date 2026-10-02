"""SXT-041 scene-LFO (SLFO) slice tests (pytest).

Covers the SCENE SCHEDULING this leaf freezes — one instance set per scene,
the `getNonReleasedVoices(scene) == 0` attack/release gate, the one-block
scene-route latch, the unconditional six-instance advance, the frozen
destination-class gate — plus the committed sidecar's structural invariants
and the exactness comparator's mismatch detection. Requires neither the
oracle nor iverilog.

The per-instance ARITHMETIC is SXT-032's frozen core and is tested by
tests/test_sxt032_lfo.py; these tests deliberately do not re-test it.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import lfo_model as lm  # noqa: E402
import slfo_model as sm  # noqa: E402
from tools.compare_slfo_rtl_model import compare  # noqa: E402

SIDECAR = os.path.join(REPO, "model", "voice", "attacky_slfo_inputs.json")
SIDECAR_FAST = os.path.join(REPO, "model", "voice",
                            "attacky_slfo_fast_inputs.json")
OVERLAP_SEQ = os.path.join(REPO, "model", "voice", "sequences",
                           "sxt041-slfo-overlap-v1.json")


@pytest.fixture(autouse=True)
def _no_mutants():
    sm.reset_mutants()
    yield
    sm.reset_mutants()


def make_params(**over):
    d = {"shape": 0, "rate": 0.0, "start_phase": 0.0, "magnitude": 1.0,
         "deform": 0.0, "trigmode": 1, "unipolar": 0, "delay": -8.0,
         "attack": -8.0, "hold": -8.0, "decay": 0.0, "sustain": 1.0,
         "release": 5.0}
    d.update(over)
    return sm.SlfoParams(d)


def make_bank(**over):
    """Six instances; instance 1 is differentiated like the real fixture."""
    params = [make_params(**over) for _ in range(sm.N_SCENE_LFOS)]
    params[1] = make_params(shape=2, rate=1.0, **over)
    return sm.SceneLfoBank(params)


# --------------------------------------------------------------- identity
def test_pinned_modsource_ids_and_counts():
    assert sm.MS_SLFO1 == 23                 # ModulationSource.h
    assert sm.N_SCENE_LFOS == 6
    assert sm.SCENE_LFO_BASE == 6            # scene.lfo[6..11]
    assert sm.FROZEN_DESTS == ("cutoff", "reso")


def test_bank_refuses_wrong_instance_count():
    with pytest.raises(RuntimeError, match="exactly 6"):
        sm.SceneLfoBank([make_params()] * 5)


# ------------------------------------------------- S2/S3 scene event gate
def test_attack_gate_only_when_no_gated_voice():
    bank = make_bank()
    assert bank.note_on(0) is True           # first note: 0 gated voices
    assert bank.note_on(1) is False          # legato: a gated voice exists
    assert bank.note_on(3) is False
    assert bank.attacks == 1


def test_release_gate_only_when_last_gate_cleared():
    bank = make_bank()
    bank.note_on(0)
    assert bank.note_off(2) is False         # other voices still gated
    assert bank.note_off(1) is False
    assert bank.note_off(0) is True          # last gate cleared
    assert bank.releases == 1


def test_attack_and_release_apply_to_all_six_instances():
    bank = make_bank()
    assert all(i.env_state == lm.EG_STUCK for i in bank.inst)
    bank.note_on(0)
    # delay/attack/hold all at val_min -> the instant-envelope path lands in
    # lfoeg_decay for every instance, routed or not
    assert all(i.env_state == lm.EG_DECAY for i in bank.inst)
    assert all(i.ever_attacked for i in bank.inst)
    for _ in range(4):
        bank.block_pass([])
    bank.note_off(0)
    assert all(i.env_state == lm.EG_RELEASE for i in bank.inst)


def test_per_note_retrigger_mutant_attacks_on_every_note():
    sm.MUTANT_PER_NOTE_RETRIGGER = True
    bank = make_bank()
    for gated in (0, 1, 2, 3):
        assert bank.note_on(gated) is True
    assert bank.attacks == 4                 # the engine would have 1


# ---------------------------------------------- S5 unconditional advance
def test_all_six_advance_every_block_even_with_no_voices():
    bank = make_bank()
    before = [i.phase for i in bank.inst]
    for _ in range(10):
        bank.block_pass([], gated_voices=0)   # no voices at all
    after = [i.phase for i in bank.inst]
    assert bank.processed_blocks == 10
    assert all(a != b for a, b in zip(after, before))


def test_gated_process_mutant_freezes_the_bank_without_voices():
    sm.MUTANT_GATED_PROCESS = True
    bank = make_bank()
    before = [i.phase for i in bank.inst]
    for _ in range(10):
        bank.block_pass([], gated_voices=0)
    assert [i.phase for i in bank.inst] == before
    assert bank.processed_blocks == 0


# ------------------------------------------------- S4 one-block route latch
def test_route_consumes_the_previous_block_output():
    bank = make_bank()
    bank.note_on(0)
    routes = [(0, sm.DEST_CUTOFF,
               lm.qint_21(1.0))]
    seen = []
    outs = []
    for _ in range(6):
        seen.append(bank.block_pass(routes)[0])
        outs.append(bank.inst[0].output)
    # block N's applied sum is block N-1's instance output (first is the
    # pre-roll zero), i.e. the applied series is the output series delayed
    assert seen[0] == 0
    assert seen[1:] == outs[:-1]


def test_zero_delay_mutant_consumes_the_current_block_output():
    sm.MUTANT_ZERO_DELAY_ROUTE = True
    bank = make_bank()
    bank.note_on(0)
    routes = [(0, sm.DEST_CUTOFF, lm.qint_21(1.0))]
    seen = []
    outs = []
    for _ in range(6):
        seen.append(bank.block_pass(routes)[0])
        outs.append(bank.inst[0].output)
    assert seen == outs
    assert seen[0] != 0                       # no pre-roll zero any more


def test_route_sums_split_by_destination_class():
    bank = make_bank()
    bank.note_on(0)
    bank.block_pass([])                      # prime the latch
    routes = [(0, sm.DEST_CUTOFF, lm.qint_21(2.0)),
              (1, sm.DEST_RESO, lm.qint_21(0.25))]
    # the latch AS CONSUMED by this block (block_pass re-latches afterwards)
    consumed = list(bank.route_out)
    cut, reso = bank.block_pass(routes)
    assert cut == lm.qmul(lm.qint_21(2.0), consumed[0], lm.FQ, lm.FQ, lm.FQ)
    assert reso == lm.qmul(lm.qint_21(0.25), consumed[1], lm.FQ, lm.FQ, lm.FQ)
    assert cut != 0 and reso != 0            # the split is not vacuous


def test_destination_class_gate_is_fail_closed():
    bank = make_bank()
    with pytest.raises(RuntimeError, match="outside the SXT-041 frozen"):
        bank.block_pass([(0, "pitch", lm.qint_21(1.0))])


# ------------------------------------- S1 per-instance state never merged
def test_per_instance_state_never_merged():
    bank = make_bank()
    bank.note_on(0)
    for _ in range(300):
        bank.block_pass([])
    # instance 1 is a square at 2 Hz, the rest sine at 1 Hz
    assert bank.inst[0].phase != bank.inst[1].phase
    assert len({i.phase for i in bank.inst}) == 2
    assert len({i.output for i in bank.inst}) >= 2


def test_shared_instance_mutant_merges_all_six():
    sm.MUTANT_SHARED_INSTANCE = True
    bank = make_bank()
    bank.note_on(0)
    for _ in range(300):
        bank.block_pass([])
    assert len({i.phase for i in bank.inst}) == 1
    assert len({i.output for i in bank.inst}) == 1


# ----------------------------------------------------- fail-closed params
def test_fail_closed_param_gates():
    for bad in ({"shape": 4}, {"shape": 7}, {"shape": 8}, {"shape": 9}):
        with pytest.raises(RuntimeError, match="frozen"):
            make_params(**bad)
    with pytest.raises(RuntimeError, match="lm_random"):
        make_params(trigmode=2)
    with pytest.raises(RuntimeError, match="frozen slice"):
        make_params(shape=0, deform=0.3)
    with pytest.raises(RuntimeError, match=r"outside pinned"):
        make_params(attack=9.0)


# ------------------------------------------------------- committed sidecar
def test_committed_sidecars_are_structurally_sound():
    for path, variant in ((SIDECAR, "base"), (SIDECAR_FAST, "fast")):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        assert d["issue"] == "SXT-041"
        assert d["variant"] == variant
        assert d["engine"]["commit"] == \
            "58914e59c608ed4384ba6002e44c3465c58b2e71"
        assert d["engine"]["ms_slfo1_id"] == sm.MS_SLFO1
        assert d["engine"]["scene_lfo_base_index"] == sm.SCENE_LFO_BASE
        assert d["engine"]["sample_rate"] == 48000
        assert d["engine"]["block_size"] == 32
        assert len(d["slfo_defs"]) == sm.N_SCENE_LFOS
        # the routes must be scene-level and inside the frozen classes
        assert d["fixture_routes"], "no declared fixture routes"
        for r in d["fixture_routes"]:
            assert r["modsource_id"] == sm.MS_SLFO1 + r["slfo_instance"]
            assert r["dest_name"] in ("A Filter 1 Cutoff",
                                      "A Filter 1 Resonance")
        assert "modulation_scene" in d["route_list"]
        # every definition must survive the frozen gates
        for i, defn in enumerate(d["slfo_defs"]):
            sm.SlfoParams(defn)
        # at least two DISTINCT definitions, else instance separation is not
        # observable on this fixture
        assert len({json.dumps(x, sort_keys=True)
                    for x in d["slfo_defs"]}) >= 2
        # parameter corners: declared ranges present and observed values in
        # range
        pc = d["parameter_corners"]
        for name, rng in pc["engine_declared_ranges"].items():
            for v in pc["observed_scene_lfo_values"][name]:
                assert rng["min"] <= v <= rng["max"], (name, v, rng)


def test_overlap_sequence_exercises_the_scene_gate():
    """The declared sequence must actually contain legato overlap.

    Without overlap the attack/release gate is indistinguishable from
    per-note retriggering and C3 would be a degenerate control.
    """
    with open(OVERLAP_SEQ, encoding="utf-8") as f:
        seq = json.load(f)
    gated = 0
    attacks = 0
    releases = 0
    overlapping_note_ons = 0
    for e in seq["events"]:
        if e["type"] == "note_on":
            if gated == 0:
                attacks += 1
            else:
                overlapping_note_ons += 1
            gated += 1
        elif e["type"] == "note_off":
            gated -= 1
            if gated == 0:
                releases += 1
    assert gated == 0
    assert overlapping_note_ons >= 3
    assert attacks == 2 and releases == 2      # vs 5/5 for a voice LFO


# --------------------------------------------------- comparator behaviour
def _trace(route_sums=(7, 9), out=3):
    return {"blocks": [{
        "b": 0,
        "slfo": [{"index": i, "phase": 1 + i, "env_state": 4,
                  "env_phase": 2, "env_val": 5, "output": out}
                 for i in range(sm.N_SCENE_LFOS)],
        "slfo_route_sums": list(route_sums),
        "slfo_route_out": [out] * sm.N_SCENE_LFOS,
    }]}


def _tb_from(trace):
    blk = trace["blocks"][0]
    lines = {(0, r["index"]): dict(b=0, index=r["index"], **{
        k: r[k] for k in ("phase", "env_state", "env_phase", "env_val",
                          "output")}) for r in blk["slfo"]}
    return (lines, {0: list(blk["slfo_route_sums"])},
            {0: list(blk["slfo_route_out"])})


def test_comparator_passes_on_identical_traces():
    tr = _trace()
    checked, fails = compare(tr, _tb_from(tr))
    assert not fails
    assert checked["slfo_checkpoints"] == sm.N_SCENE_LFOS
    assert checked["route_sums"] == 1 and checked["route_latches"] == 1


def test_comparator_detects_route_sum_mismatch():
    tr = _trace()
    tb = _tb_from(tr)
    tb[1][0][0] += 1
    _checked, fails = compare(tr, tb)
    assert any("route_sum[0]" in f for f in fails)


def test_comparator_detects_route_latch_mismatch():
    """The latch leg is what catches a dropped one-block scene-route delay."""
    tr = _trace()
    tb = _tb_from(tr)
    tb[2][0][1] += 5
    _checked, fails = compare(tr, tb)
    assert any("route_out[1]" in f for f in fails)


def test_comparator_detects_per_instance_divergence():
    tr = _trace()
    tb = _tb_from(tr)
    tb[0][(0, 3)]["phase"] += 1
    _checked, fails = compare(tr, tb)
    assert any("slfo 3 phase" in f for f in fails)


def test_comparator_detects_missing_checkpoint_lines():
    tr = _trace()
    tb = _tb_from(tr)
    del tb[0][(0, 5)]
    _checked, fails = compare(tr, tb)
    assert any("missing L line" in f for f in fails)
