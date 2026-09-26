"""SXT-028b Conditioner leaf tests (pytest).

Oracle-independent. Covers: frozen constants and the pinned-source facts
the model encodes (fixed leaf-126 detector read, ring-out schedule, float32
coefficient chain), the two lifecycle paths (fresh re-spawn vs engine
suspend), process_only_control passthrough, per-instance independence,
look-ahead latency, limiter gain reduction, tail coverage, the RTL<->model
control-word boundary, the fixture-corner provenance, the extraction
tool's pure fail-closed logic, and the committed evidence records
(fail-closed: a stale or failing record fails the test).

The model-vs-reference leg needs the pinned oracle (surgepy) and is NOT_RUN
here; nothing in this file claims reference agreement. A live RTL re-run
needs iverilog and is skipped (NOT_RUN) when it is absent -- never passed.
"""
import json
import os
import random
import re
import shutil
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-conditioner"))

import conditioner_model as cm  # noqa: E402
from conditioner_model import (  # noqa: E402
    ConditionerModel, ConditionerParams, BLOCK, LOOKAHEAD, ONE_C,
    CTRL_WORDS, FLAG_CONTROL_ONLY, FLAG_FRESH, FLAG_SUSPEND, FLAG_HP_ON,
    model_revision, tail_coverage_check, attack_release_f32,
)
import conditioner_corners as corners  # noqa: E402
import extract_conditioner_inputs as ext  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028b")
TB = os.path.join(REPO, "rtl", "effects", "type-conditioner", "tb_conditioner.sv")
P = corners.defaults()
LOUD = dict(P, threshold_db=-24.0, attack_f=1.0, release_f=-1.0)


def model(params=P, name="t"):
    m = ConditionerModel(ConditionerParams(dict(params)), name)
    m.initialize()
    return m


def noise(rs, amp):
    return [rs.randint(-amp, amp) for _ in range(BLOCK)]


def test_frozen_constants_match_pinned_source():
    assert cm.LOOKAHEAD == 128 and cm.LA_READ_INDEX == 126
    assert cm.RINGOUT_DECAY_BLOCKS == 100 and cm.RINGOUT_INIT == 10000000
    assert cm.TAIL_PROCESS_BLOCKS == 99 and cm.TAIL_SPAN_SAMPLES == 3168
    assert (cm._BASS_SCFREQ, cm._TREBLE_SCFREQ, cm._EQ_BW, cm._HP_Q) == \
        (-2.5, 4.75, 2.0, 0.4)
    assert CTRL_WORDS == 22


def test_float32_coefficient_chain_is_exact_ieee():
    np = pytest.importorskip("numpy", reason="NOT_RUN: numpy absent")
    for a in (-1.0, -0.37, 0.0, 0.533929, 1.0):
        x = np.float32(a)
        am = np.float32(1.0) + np.float32(0.9) * x
        want = np.float32(0.001) * am * am
        rm = np.float32(1.0) + np.float32(0.9) * x
        want_r = np.float32(0.0001) * rm * rm
        got = attack_release_f32(a, a)
        assert got == (float(want), float(want_r)), a


def test_rtl_constants_match_model():
    from model.effects.delay.delay_model import D_LP, D_LPINV
    src = open(TB).read()
    m = re.search(r"DLP_C\s*=\s*64'sh([0-9a-f]+)", src)
    mi = re.search(r"DLPI_C\s*=\s*64'sh([0-9a-f]+)", src)
    assert int(m.group(1), 16) == D_LP and int(mi.group(1), 16) == D_LPINV
    assert "64'sh0000080000000000" in src and ONE_C == 1 << 43
    assert "LA_READ_INDEX = 126" in src


def test_detector_reads_fixed_leaf_only():
    """Only the sample written at bufpos == 126 reaches the detector: a loud
    burst anywhere else in the 128-sample cycle never reduces gain."""
    m = model(LOUD)
    rs = random.Random(1)
    loud = 1 << 22
    # cycle 0: bufpos 0..127; the leaf at 126 is written in block 3, k = 30
    for b in range(4):
        il = noise(rs, loud) if b < 3 else [loud] * 30 + [0, 0]
        m.process_block(il, il)
    for _ in range(8):
        m.process_block([0] * BLOCK, [0] * BLOCK)
    assert m.st.lamax[126] == 0 and m.st.gain == ONE_C
    m2 = model(LOUD)
    for b in range(4):
        il = [0] * BLOCK if b < 3 else [0] * 30 + [loud, 0]
        m2.process_block(il, il)
    for _ in range(8):
        m2.process_block([0] * BLOCK, [0] * BLOCK)
    assert m2.st.gain < ONE_C


def test_lookahead_latency_is_128_samples():
    m = model(dict(P, width_f=1.0))
    imp = [0] * BLOCK
    imp[5] = 1 << 20
    outs = []
    for b in range(8):
        ol, _ = m.process_block(imp if b == 0 else [0] * BLOCK, [0] * BLOCK)
        outs += ol
    nz = [i for i, v in enumerate(outs) if v != 0]
    assert nz and nz[0] == 5 + LOOKAHEAD


def test_limiter_engages_and_releases():
    m = model(LOUD)
    rs = random.Random(2)
    for _ in range(40):
        a = noise(rs, 1 << 22)
        m.process_block(a, a)
    assert m.st.gain < ONE_C // 2
    for _ in range(200):
        m.process_block([0] * BLOCK, [0] * BLOCK)
    assert m.st.gain > m.st.filtered_lamax2 // (1 << 40)  # recovering


def test_control_only_is_exact_passthrough_and_advances_envelope():
    m = model(LOUD)
    rs = random.Random(3)
    for _ in range(10):
        a = noise(rs, 1 << 22)
        m.process_block(a, a)
    ring = [list(x) for x in m.st.delayed]
    fl2 = m.st.filtered_lamax2
    il, ir = noise(rs, 999), noise(rs, 999)
    ol, orr = m.process_only_control(il, ir)
    assert (ol, orr) == (il, ir)
    assert m.st.delayed == ring and m.st.filtered_lamax2 != fl2
    assert m.ctrl[-1] & FLAG_CONTROL_ONLY


def test_ringout_schedule():
    m = model()
    assert m.st.ringout == cm.RINGOUT_INIT
    z = [0] * BLOCK
    assert m.process_ringout(z, z, False)[2] is False     # fresh, no input
    assert m.process_ringout(z, z, True)[2] is True
    flags = [m.process_ringout(z, z, False)[2] for _ in range(101)]
    assert flags[:99] == [True] * 99 and flags[99:] == [False, False]


def test_fresh_vs_suspend_lifecycle():
    rs = random.Random(4)
    p = dict(P, bass_db=6.0, treble_db=-6.0, width_f=0.5)
    m = model(p)
    for _ in range(12):
        a, b = noise(rs, 1 << 21), noise(rs, 1 << 21)
        m.process_block(a, b)
    regs = (list(m.st.band1.reg0), m.st.ampL.target)
    m.suspend()   # engine suspend(): limiter cleared, biquads + lipols kept
    assert m.st.delayed == [[0] * LOOKAHEAD] * 2 and m.st.bufpos == 0
    assert (list(m.st.band1.reg0), m.st.ampL.target) == regs
    m.process_block([0] * BLOCK, [0] * BLOCK)
    assert m.ctrl[-1] & FLAG_SUSPEND
    m.initialize()  # patch load: fresh object
    assert m.st.band1.reg0 == [0, 0] and m.st.ampL.target == 0
    m.process_block([0] * BLOCK, [0] * BLOCK)
    assert m.ctrl[-1] & FLAG_FRESH and not m.ctrl[-1] & FLAG_SUSPEND


def test_dual_instance_independent_histories():
    ma, mb = model(LOUD, "a"), model(dict(LOUD, width_f=0.8, threshold_db=-12.0,
                                          hpwidth_deactivated=False,
                                          hpwidth_semitones=0.0), "b")
    solo = model(LOUD, "solo")
    rs = random.Random(5)
    for _ in range(20):
        a, b = noise(rs, 1 << 22), noise(rs, 1 << 22)
        oa = ma.process_block(a, b)
        mb.process_block(noise(rs, 1 << 21), noise(rs, 1 << 21))
        assert solo.process_block(a, b) == oa   # b's traffic never leaks into a
    assert ma.st.delayed is not mb.st.delayed
    assert ma.st.ring_hash != mb.st.ring_hash
    assert mb.ctrl[-1] & FLAG_HP_ON and not ma.ctrl[-1] & FLAG_HP_ON


def test_tail_coverage_check():
    assert tail_coverage_check(141, 39) == (True, 140)
    assert tail_coverage_check(139, 39) == (False, 140)


def test_corners_provenance_fail_closed():
    cs = corners.all_corners()
    names = [n for n, _, _ in cs]
    assert names[:3] == ["loader-defaults", "extreme-min", "extreme-max"]
    fx = {n: prov for n, _, prov in cs[3:]}
    assert set(fx) == {"doomsday-slot06", "piercing-slot07", "aoe-slot00",
                       "computerlanguage1-slot00"}
    for n, prov in fx.items():
        assert prov["census_blob_sha1"].startswith(
            corners.ISSUE_BLOB_PREFIX[n.split("-")[0]])
        assert "ASSUMED" in prov["deactivated_flags"]


def test_extraction_pure_logic_fail_closed():
    g = corners.graphs_line(
        "resources/data/patches_3rdparty/A.Liv/Basses/808er Than 808.fxp")
    assert ext.slot_mod_hits(g, "bins1")            # screen really fires
    for slug, rel in corners.FIXTURE_PRESETS.items():
        gl = corners.graphs_line(rel)
        for f in gl["g"]["fx"]:
            if f.get("t") == ext.FX_TYPE_CONDITIONER:
                assert ext.slot_mod_hits(gl, f["r"]) == [], slug
    flags = {"fx7_p0": {"deactivated_absent": False, "deactivated": True},
             "fx7_p1": {"deactivated_absent": False, "deactivated": False},
             "fx7_p8": {"deactivated_absent": False, "deactivated": False}}
    assert ext.resolve_deactivated(flags, 6, 20) == {
        "bass_deactivated": True, "treble_deactivated": False,
        "hpwidth_deactivated": False}
    assert ext.resolve_deactivated({}, 6, 15) == {
        "bass_deactivated": False, "treble_deactivated": False,
        "hpwidth_deactivated": True}
    with pytest.raises(ext.Refuse):
        ext.resolve_deactivated({}, 6, 20)
    out = os.path.join(REPO, "model", "effects", "fx_inputs")
    assert not any(f.startswith("type-conditioner-") for f in os.listdir(out)), \
        "extraction outputs present: EVIDENCE.md must be updated from BLOCKED"


def test_buffer_requirement_record():
    d = json.load(open(os.path.join(SXT, "artifacts", "buffer-requirement.json")))
    assert d["model_revision"] == model_revision(), "stale record"
    assert d["external_memory"]["classification"] == "ON-CHIP"
    assert d["external_memory"]["external_traffic_bytes_per_sample"] == 0.0
    assert d["state_memory_traffic"]["reads_per_sample"] == 3.0
    assert d["state_memory_traffic"]["writes_per_sample"] == 3.0
    assert d["on_chip_state"]["writable_line_bytes"] == 2048
    r = d["sxt015_reconciliation"]
    assert r["placeholder_conservative"] and r["external_classification_agrees"]
    # The embedded sxt015_state_bytes is re-derived live from fx_class_spec on
    # every regeneration (tools/conditioner_buffer_report.py); it must track
    # the table, not a frozen number, or the committed artifact silently goes
    # stale the next time the table changes (issue #134).
    from model.resources.fx_classes import fx_class_spec
    assert r["sxt015_state_bytes"] == fx_class_spec("Conditioner")["state_bytes"]


def test_negative_controls_record():
    d = json.load(open(os.path.join(SXT, "negative-controls",
                                    "negative-controls.json")))
    assert d["model_revision"] == model_revision(), "stale record"
    assert d["status"] == "PASS" and len(d["controls"]) == 7
    for c in d["controls"]:
        assert c["ok"] is True and "CONTROL-OK" in c["verdict"], c["control"]


def test_rtl_exactness_record():
    d = json.load(open(os.path.join(SXT, "rtl-exactness.json")))
    assert d["model_revision"] == model_revision(), "stale record"
    assert d["status"] == "PASS"
    assert len(d["cases"]) == 4
    for c in d["cases"]:
        assert c["status"] == "PASS" and c["mismatches"] == 0, c["case"]
        assert c["revision_pin"]["ok"], c["case"]
    life = d["cases"][0]
    assert life["tail_coverage"]["ok"]
    cov = life["coverage"]
    assert cov["control_only_blocks"] > 0 and cov["suspends"] == 1
    assert cov["fresh_respawns"] == 1 and cov["min_gain"] < 1.0
    ctl = {c["control"]: c for c in d["controls"]}
    assert set(ctl) == {"mutant-shared", "mutant-nolimiter", "permuted-slots",
                        "stale-stub", "dropped-tail"}
    for c in ctl.values():
        assert c["ok"] is True and "CONTROL-OK" in c["verdict"], c["control"]
    assert ctl["stale-stub"]["check_result"].startswith("REFUSED")
    assert ctl["dropped-tail"]["mismatches"] == 0          # data matched...
    assert ctl["dropped-tail"]["tail_coverage"]["ok"] is False  # ...tail not


@pytest.mark.skipif(shutil.which("iverilog") is None,
                    reason="NOT_RUN: iverilog absent")
def test_rtl_smoke_live(tmp_path):
    import compare_rtl_model_conditioner as c
    rev8 = model_revision()[:8]
    cn = {n: p for n, p, _ in corners.all_corners()}
    present = [True] * 5 + [False] * 2
    exps, ih, ch, _, _, _ = c.build_case(
        "smoke", [cn["doomsday-slot06"], c.SYNTH_B], present,
        {4: {0: "suspend", 1: "fresh"}}, 9, str(tmp_path))
    tr = c.run_sim(c.TB, str(tmp_path), 2, len(present), ih, ch, rev8)
    assert c.judge("smoke", exps, tr, 2, len(present), rev8)["status"] == "PASS"
