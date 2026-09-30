"""SXT-036 (#70) per-instance STATE tests (pytest, no iverilog required).

Covers the fourth increment's oracle-independent machinery: the three
stimulus preconditions that decide whether a state/timing control can fire,
the coverage census that measures them, the new RTL mutation anchors, and
the scene-A-only destination class (the "state is never shared across
scenes" half of this leaf's per-instance rule).

These are claim-(1)-side unit tests: they establish nothing about
model-vs-pinned-engine agreement (NOT_RUN on this host, #96) and nothing
about fidelity or sound quality.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import vel_negative_controls as vnc            # noqa: E402
import vel_state_coverage as vsc               # noqa: E402
import run_vel_model as rvm                    # noqa: E402

TB_VEL = os.path.join(REPO, "rtl", "voice", "tb_vel.sv")


def _blk(b, create=(), release=(), voices=()):
    return {"b": b, "create": list(create), "release": list(release),
            "voices": [{"slot": s, "vel_words": list(w)} for s, w in voices]}


# ------------------------------------------------- precondition measurement -
def test_slot_reuse_needs_a_nonzero_release_velocity_first():
    """Reuse after a ZERO release velocity is not a re-initialization test."""
    trace = {"blocks": [
        _blk(0, create=[0], voices=[(0, (100, 0))]),
        _blk(1, release=[0], voices=[(0, (100, 0))]),      # relvel word 0
        _blk(2, create=[0], voices=[(0, (200, 0))]),       # reuse, but stale=0
    ]}
    pre = vsc.trace_preconditions(trace)
    assert pre["slot_reuse_after_nonzero_release_velocity_blocks"] == 0
    assert pre["slot_reuse"] is False
    assert pre["release_blocks_with_nonzero_relvel_word"] == 0
    assert pre["release_word"] is False


def test_slot_reuse_is_detected_after_a_nonzero_release_velocity():
    trace = {"blocks": [
        _blk(0, create=[0], voices=[(0, (100, 0))]),
        _blk(1, release=[0], voices=[(0, (100, 55))]),
        _blk(2, voices=[(0, (100, 55))]),
        _blk(3, create=[0], voices=[(0, (200, 0))]),
    ]}
    pre = vsc.trace_preconditions(trace)
    assert pre["slot_reuse_after_nonzero_release_velocity_blocks"] == 1
    assert pre["slot_reuse"] is True
    assert pre["release_word"] is True


def test_release_word_requires_the_voice_to_run_that_block():
    """A release recorded with no control pass cannot show a late latch."""
    trace = {"blocks": [_blk(0, create=[0], voices=[(0, (100, 0))]),
                        _blk(1, release=[0], voices=[])]}
    pre = vsc.trace_preconditions(trace)
    assert pre["release_blocks_with_nonzero_relvel_word"] == 0
    assert pre["release_word"] is False


def test_per_instance_needs_distinct_concurrent_source_words():
    same = {"blocks": [_blk(0, voices=[(0, (100, 0)), (1, (100, 0))])]}
    diff = {"blocks": [_blk(0, voices=[(0, (100, 0)), (1, (200, 0))])]}
    assert vsc.trace_preconditions(same)["per_instance"] is False
    assert vsc.trace_preconditions(diff)["per_instance"] is True


def test_controls_and_census_share_one_precondition_implementation():
    """The census and the control driver must never disagree (#70)."""
    assert vnc.trace_preconditions is vsc.trace_preconditions


# ----------------------------------------------------- RTL mutation anchors -
def test_every_declared_mutant_anchor_still_exists_in_the_rtl():
    """A mutant whose anchor drifted would silently become a no-op control."""
    tb = open(TB_VEL, encoding="utf-8").read()
    for name, subs in vnc.MUTANTS.items():
        for needle, _rep in subs:
            assert tb.count(needle) >= 1, (name, needle)


def test_every_declared_mutant_actually_changes_the_rtl():
    tb = open(TB_VEL, encoding="utf-8").read()
    for name, subs in vnc.MUTANTS.items():
        m = tb
        for needle, rep in subs:
            m = m.replace(needle, rep)
        assert m != tb, name


def test_state_mutants_declare_the_precondition_they_need():
    """A state/timing mutant with no precondition could be reported as a
    pass on a stimulus that cannot make it fire."""
    assert set(vnc.MUTANT_PRECONDITION) == {
        "shared-slot", "stale-slot-reinit", "release-one-block-late"}
    for name, key in vnc.MUTANT_PRECONDITION.items():
        assert name in vnc.MUTANTS
        assert key in vsc.PRECONDITIONS


def test_stale_slot_reinit_mutant_drops_the_ctor_clear_only():
    """The re-initialization mutant must not also disturb the velocity
    latch -- otherwise it would be testing something else."""
    tb = open(TB_VEL, encoding="utf-8").read()
    m = tb
    for needle, rep in vnc.MUTANTS["stale-slot-reinit"]:
        m = m.replace(needle, rep)
    # the per-construction clear is gone; the power-on reset loop (a
    # different thing) is deliberately left alone
    assert "vel_q[s]    = vel_rom(ctrl_mem[base+2]);\n          relvel_q[s] = 0;" \
        not in m
    assert "for (s = 0; s < NSLOTS; s++) begin vel_q[s] = 0; relvel_q[s] = 0;" in m
    assert m.count("vel_q[s]    = vel_rom(ctrl_mem[base+2]);") == 1
    assert m.count("relvel_q[s] = vel_rom(ctrl_mem[base+4]);") >= 1


def test_release_one_block_late_mutant_moves_the_latch_after_the_pass():
    tb = open(TB_VEL, encoding="utf-8").read()
    m = tb
    for needle, rep in vnc.MUTANTS["release-one-block-late"]:
        m = m.replace(needle, rep)
    # the latch must now sit after the per-voice control pass, i.e. after the
    # $fwrite of the route sums and immediately before the stride advance
    latch = m.index("if (ctrl_mem[base+3][0]) relvel_q[s] = vel_rom")
    assert latch > m.index('$fwrite(fd, "S %0d')
    assert latch < m.index("ci += STRIDE;")
    assert m.count("ci += STRIDE;") == 1


# ------------------------------------------- scene-A-only destination class -
def test_frozen_destination_class_is_scene_a_only():
    assert set(rvm.DEST_CODE) == {308, 309, 310, 298}
    assert all(name.startswith("A ") for name in rvm.DEST_NAME.values())


def test_the_carriers_scene_b_route_is_outside_the_frozen_class():
    """'House Of Chords.fxp' carries ms_velocity -> 502 'B Osc 1 Sync' in
    scene B; the R2 refusal control replays exactly that route."""
    audit = json.load(open(os.path.join(
        REPO, "reports", "SXT-036", "artifacts",
        "carrier-route-audit.json"), encoding="utf-8"))
    hoc = [v for k, v in audit["audit"].items() if "House Of Chords" in k][0]
    route = [r for r in hoc["routes"] if r["dest_id"] == 502][0]
    assert route["modsource_id"] == rvm.VELOCITY_SRC
    assert route["scene_index"] == 1
    assert route["in_frozen_class"] is False
    assert 502 not in rvm.DEST_CODE


# --------------------------------------------------------- coverage census --
def test_static_screen_reads_release_velocities_from_the_committed_files():
    p = os.path.join(REPO, "model", "voice", "sequences",
                     "sxt036-vel-overlap-v1.json")
    st = vsc.static_screen(p)
    assert st["nonzero_release_velocities"] == 5
    assert st["release_preconditions_impossible"] is False
    assert st["max_gated_overlap"] >= 2


def test_committed_shared_fixtures_barely_exercise_release_velocity():
    """Re-derived, not quoted: a shared fixture with no nonzero release
    velocity can never satisfy either release-velocity precondition."""
    import glob
    withrel = []
    for p in sorted(glob.glob(os.path.join(vsc.SHARED_DIR, "*.json"))):
        try:
            st = vsc.static_screen(p)
        except (json.JSONDecodeError, KeyError):
            continue
        if st["note_ons"] and st["nonzero_release_velocities"]:
            withrel.append(st["id"])
    assert withrel == ["seq-notes-holds-v1"]


def test_recorded_state_coverage_artifact_matches_the_census_contract():
    art = os.path.join(REPO, "reports", "SXT-036", "artifacts",
                       "state-coverage.json")
    d = json.load(open(art, encoding="utf-8"))
    assert d["oracle_dependent_items"] == {"2": "NOT_RUN", "5": "NOT_RUN"}
    assert set(d["preconditions"]) == set(vsc.PRECONDITIONS)
    # the recorded gap is a coverage statement, not a control verdict
    assert "per_instance" in d["shared_fixture_gaps"]
    assert "slot_reuse" in d["shared_fixture_gaps"]
    assert d["dynamic"]["sxt036-vel-overlap-v1"]["slot_reuse"] is True
