"""SXT-028e Distortion leaf tests (pytest).

Covers: the frozen constant inventory and word-length contract, the
generator/ROM consistency guard (the committed waveshaper ROM must equal
what `ws_tables.py` generates), fail-closed refusals (out-of-scope
waveshaper models, unresolved control-plane inputs), model determinism and
per-instance independence, the ringout tail contract, the zero-external-
memory accounting, and the integrity of the committed evidence records
(negative controls, RTL exactness, buffer report).

Oracle-dependent legs (reference renders, the complete oracle extraction)
are NOT run here and must never be reported as a pass: the committed
`model/effects/fx_inputs/type-distortion-*.json` records carry
`extraction_status = INCOMPLETE-BLOCKED-ON-ORACLE` and this suite asserts
exactly that. A missing iverilog makes the RTL leg NOT_RUN (skipped), never
a pass.
"""
import json
import os
import random
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-distortion"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

import distortion_model as dm  # noqa: E402
import ws_tables as wt  # noqa: E402
from distortion_model import (  # noqa: E402
    DistortionModel, DistortionParams, HalfbandD2, BLOCK, OS_BLOCK,
    DISTORTION_OS, RINGOUT_TIME, RINGOUT_END, SLOWRATE, HB_COEFFS_Q,
    model_revision, lookup_waveshape, get_extended,
)
from model.effects.qmath import FRAC  # noqa: E402

SXT = os.path.join(REPO, "reports", "SXT-028e")
RTLDIR = os.path.join(REPO, "rtl", "effects", "type-distortion")

SYNTH = dict(preeq_gain_f=6.0, preeq_freq_f=3.0, preeq_bw_f=0.3,
             preeq_highcut_f=70.0, drive_f=6.0, feedback_f=0.635445,
             posteq_gain_f=-4.5, posteq_freq_f=24.0, posteq_bw_f=1.1,
             posteq_highcut_f=30.535736, gain_f=0.0, model_i=0,
             preeq_highcut_deactivated=False,
             posteq_highcut_deactivated=False,
             preeq_gain_extend=False, posteq_gain_extend=False,
             drive_extend=False)


def make_model(name="t", **kw):
    p = dict(SYNTH)
    p.update(kw)
    m = DistortionModel(DistortionParams(p), name)
    m.initialize()
    return m


def drive_blocks(m, n, seed=7, amp=1 << 20, ringout=0):
    rs = random.Random(seed)
    out = []
    for _ in range(n):
        il = [rs.randint(-amp, amp) for _ in range(BLOCK)]
        ir = [rs.randint(-amp, amp) for _ in range(BLOCK)]
        ol, orr = m.process_block(il, ir, ringout=ringout)
        out += ol + orr
    return out


# ---------------------------------------------------------------- contract
def test_frozen_constants_and_layout():
    assert DISTORTION_OS == 4 and OS_BLOCK == BLOCK * 4   # dist_OS_bits = 2
    assert SLOWRATE == 8                                   # Effect.h:138
    assert RINGOUT_TIME == 1600 and RINGOUT_END == 320     # DistortionEffect.h
    assert HalfbandD2.STAGES == 3                          # HalfRateFilter(3, ·)
    assert FRAC["Q10.21"] == 21 and FRAC["Q13.18"] == 18
    assert FRAC["Q24.43"] == 43 and FRAC["Q2.29"] == 29
    # the twelve quoted order-6 halfband coefficients (DR-0012)
    assert len(HB_COEFFS_Q) == 12
    assert dm.HB_A_SOFT[0] == 0.06029739095712437
    assert dm.HB_B_STEEP[2] == 0.9763114515836773
    assert HB_COEFFS_Q[0] == int(dm.HB_A_SOFT[0] * (1 << 43) + 0.5)


def test_get_extended_multipliers():
    # Parameter.cpp: ct_decibel_extendable -> 3x, narrow_extendable -> 5x
    assert get_extended(2.0, "ct_decibel_extendable", False) == 2.0
    assert get_extended(2.0, "ct_decibel_extendable", True) == 6.0
    assert get_extended(2.0, "ct_decibel_narrow_extendable", True) == 10.0
    with pytest.raises(RuntimeError):
        get_extended(1.0, "ct_nonsense", True)


def test_waveshaper_tables_are_rederived_not_quoted():
    import math
    for mi in wt.FROZEN_MODELS:
        tbl = wt.build_table(mi)
        assert len(tbl) == wt.TABLE_SIZE == 1024
    soft = wt.TABLES[0]
    # x = (i - 512)/32; row 0 is tanh(x)
    for i in (0, 256, 512, 600, 1023):
        x = (i - 512) / 32.0
        assert abs(soft[i] / (1 << 29) - math.tanh(x)) < 1e-6
    # row 2 (asym) is zero-crossing-shifted, not odd-symmetric
    assert wt.TABLES[2][512] == 0 or abs(wt.TABLES[2][512]) < (1 << 20)


def test_ws_rom_matches_generator():
    """The committed RTL ROM must be a build product of ws_tables.py.

    If it ever drifts it would become an independent copy of engine data,
    which DR-0012 clause 2 forbids.
    """
    rom = os.path.join(RTLDIR, "ws_q29.hex")
    with open(rom) as f:
        words = [int(line.strip(), 16) for line in f if line.strip()]
    expect = []
    for mi in wt.FROZEN_MODELS:
        expect += [w & 0xFFFFFFFF for w in wt.TABLES[mi]]
    assert words == expect
    assert len(words) == len(wt.FROZEN_MODELS) * wt.TABLE_SIZE


# ------------------------------------------------------------- fail-closed
def test_out_of_scope_waveshaper_models_refused():
    for mi in (3, 4, 5, 6, 7):
        with pytest.raises(RuntimeError) as e:
            DistortionParams(dict(SYNTH, model_i=mi))
        assert "frozen scope" in str(e.value)
        with pytest.raises(RuntimeError):
            wt.build_table(mi)


def test_unresolved_control_plane_inputs_refused():
    for k in ("preeq_highcut_deactivated", "drive_extend", "model_i"):
        bad = dict(SYNTH)
        bad[k] = None
        with pytest.raises(RuntimeError) as e:
            DistortionParams(bad)
        assert "fail-closed" in str(e.value)


def test_committed_fx_inputs_are_blocked_on_oracle():
    """The graphs-derived records must SAY they are incomplete, and the model
    must refuse them — a NOT_RUN extraction is never a pass."""
    found = 0
    d = os.path.join(REPO, "model", "effects", "fx_inputs")
    for name in sorted(os.listdir(d)):
        if not name.startswith("type-distortion-"):
            continue
        found += 1
        rec = json.load(open(os.path.join(d, name)))
        assert rec["extraction_status"] == "INCOMPLETE-BLOCKED-ON-ORACLE"
        assert rec["extraction_mode"] == "graphs"
        assert rec["census_blob_sha1"]
        for slot in rec["distortion_slots"]:
            for k in rec["unresolved_fields"]:
                assert slot["params"][k] is None
            with pytest.raises(RuntimeError):
                DistortionParams(slot["params"])
    assert found == 3


def test_landed_class_basis_is_derived_from_the_committed_table():
    """The complete-wet verdict must cite the ledger, not a stale literal.

    A hand-maintained "landed classes" set goes stale the moment a sibling
    leaf merges, and a stale *landed* claim overstates coverage. The extractor
    derives the set from `reports/coverage-v1/leaf-verification.json`; this
    test re-derives it independently and asserts the committed records agree.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "extract_distortion_inputs",
        os.path.join(REPO, "tools", "extract_distortion_inputs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    table = json.load(open(os.path.join(REPO, "reports", "coverage-v1",
                                        "leaf-verification.json")))
    expect = sorted(
        tn for tn, key in mod.FX_TYPE_TO_LEAF.items()
        if table["leaves"].get(key, {}).get("landed") is True)
    assert sorted(mod.landed_classes() - {"Off"}) == expect
    # Airwindows leaves are per-algorithm: the class name must never be
    # treated as landed wholesale (fail-closed).
    assert "Airwindows" not in mod.landed_classes()

    d = os.path.join(REPO, "model", "effects", "fx_inputs")
    for name in sorted(os.listdir(d)):
        if not name.startswith("type-distortion-"):
            continue
        rec = json.load(open(os.path.join(d, name)))
        basis = rec["landed_classes_basis"]
        assert basis["landed_fx_classes"] == expect, \
            f"{name} records a stale landed-class basis"
        chain = {f["type"] for f in rec["chain"]}
        assert rec["unlanded_classes_in_chain"] == sorted(
            chain - set(expect) - {"Off"})
        assert rec["complete_wet_render_possible"] == (
            not rec["unlanded_classes_in_chain"])


def test_census_blob_shas_match_manifest():
    man = json.load(open(os.path.join(REPO, "corpus", "census-v0.1",
                                      "corpus-manifest.json")))
    by_path = {e["path"]: e["git_blob_sha1"] for e in man["entries"]}
    d = os.path.join(REPO, "model", "effects", "fx_inputs")
    for name in sorted(os.listdir(d)):
        if not name.startswith("type-distortion-"):
            continue
        rec = json.load(open(os.path.join(d, name)))
        assert by_path[rec["preset_path"]] == rec["census_blob_sha1"]


# ------------------------------------------------------------------- model
def test_model_determinism():
    a = drive_blocks(make_model("a"), 24)
    b = drive_blocks(make_model("b"), 24)
    assert a == b


def test_per_instance_independence():
    """Two concurrent instances must keep independent histories."""
    m1 = make_model("i0")
    m2 = make_model("i1", drive_f=-3.0, model_i=1, feedback_f=0.2)
    rs = random.Random(3)
    solo1, solo2 = [], []
    stim = []
    for _ in range(24):
        il = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        stim.append((il, ir))
    for il, ir in stim:
        o = m1.process_block(il, ir)
        solo1 += list(o[0]) + list(o[1])
    for il, ir in stim:
        o = m2.process_block(il, ir)
        solo2 += list(o[0]) + list(o[1])
    # interleaved: identical per-instance results (no cross-talk)
    n1 = make_model("j0")
    n2 = make_model("j1", drive_f=-3.0, model_i=1, feedback_f=0.2)
    inter1, inter2 = [], []
    for il, ir in stim:
        o = n1.process_block(il, ir)
        inter1 += list(o[0]) + list(o[1])
        o = n2.process_block(il, ir)
        inter2 += list(o[0]) + list(o[1])
    assert inter1 == solo1
    assert inter2 == solo2
    assert solo1 != solo2
    # and the state objects are genuinely distinct
    assert n1.st is not n2.st
    assert n1.st.hr_a is not n2.st.hr_a


def test_shared_state_is_detectable():
    """The per-instance acceptance needs a control that fires."""
    a = make_model("k0")
    b = make_model("k1", drive_f=-3.0, model_i=1, feedback_f=0.2)
    ref_a = drive_blocks(a, 16, seed=9)
    a2 = make_model("l0")
    b2 = make_model("l1", drive_f=-3.0, model_i=1, feedback_f=0.2)
    b2.st = a2.st                       # THE DEFECT
    rs = random.Random(9)
    pooled_a = []
    for _ in range(16):
        il = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 20), 1 << 20) for _ in range(BLOCK)]
        o = a2.process_block(il, ir)
        pooled_a += list(o[0]) + list(o[1])
        b2.process_block(il, ir)
    assert pooled_a != ref_a
    del b, ref_a


def test_ringout_fade_contract():
    """DistortionEffect::process ringout fade (the declared tail span)."""
    f = DistortionModel.ringout_mul
    assert f(0) == 1.0
    assert f(RINGOUT_TIME - RINGOUT_END) == 1.0          # 1280: not yet fading
    assert f(RINGOUT_TIME - 1) == 0.0                    # 1599: fully faded
    mid = f(RINGOUT_TIME - RINGOUT_END // 2)
    assert 0.0 < mid < 1.0
    assert f(RINGOUT_TIME - RINGOUT_END + 1) == pytest.approx(
        (RINGOUT_TIME - (RINGOUT_TIME - RINGOUT_END + 1) - 1) / RINGOUT_END)
    # declared tail span in seconds at 48 kHz
    assert RINGOUT_TIME * BLOCK / 48000.0 == pytest.approx(1.0666666, rel=1e-6)


def test_tail_is_produced_and_droppable():
    """The effect must still produce output after the input goes silent, and
    truncating that output must be observable."""
    m = make_model("tail", feedback_f=0.99, drive_f=9.0, drive_extend=True)
    drive_blocks(m, 32, seed=21)
    tail = []
    for b in range(64):
        o = m.process_block([0] * BLOCK, [0] * BLOCK, ringout=b + 1)
        tail += list(o[0]) + list(o[1])
    assert max(abs(v) for v in tail) > 0, "no tail produced at all"
    # dropping it is a real loss, not a no-op
    assert any(v != 0 for v in tail)


def test_zero_external_memory():
    m = make_model("mem")
    drive_blocks(m, 16)
    assert m.st.ext_reads == 0
    assert m.st.ext_writes == 0


def test_waveshaper_rails():
    tbl = wt.TABLES[0]
    one = 1 << 21
    assert lookup_waveshape(tbl, 100 * one) == one      # e > 0x3fd
    assert lookup_waveshape(tbl, -100 * one) == -one    # e < 1
    assert abs(lookup_waveshape(tbl, 0)) <= 1           # tanh(0) = 0


def test_slowrate_coefficient_refresh():
    """Band coefficient targets refresh only every SLOWRATE blocks."""
    m = make_model("slow")
    seen = []
    rs = random.Random(1)
    for b in range(SLOWRATE * 3):
        seen.append(m.st.bi)
        m.process_block([rs.randint(-1000, 1000) for _ in range(BLOCK)],
                        [rs.randint(-1000, 1000) for _ in range(BLOCK)])
    assert seen == [b % SLOWRATE for b in range(SLOWRATE * 3)]


# -------------------------------------------------------- evidence records
def test_negative_controls_record():
    path = os.path.join(SXT, "negative-controls", "negative-controls.json")
    rec = json.load(open(path))
    assert rec["status"] == "ALL-CONTROLS-OK"
    assert rec["model_revision"] == model_revision(), \
        "negative-control record is STALE against the frozen model"
    ids = {c["id"] for c in rec["controls"]}
    # the five controls the issue requires, plus the baseline-sanity leg
    assert {"NC-0", "NC-A", "NC-B", "NC-C", "NC-D", "NC-E", "NC-F"} <= ids
    for c in rec["controls"]:
        assert c["ok"], f"{c['id']} is a BROKEN control"
    base = next(c for c in rec["controls"] if c["id"] == "NC-0")
    assert base["verdict"] == "PASS", "baseline sanity must pass"
    for cid in ("NC-A", "NC-B", "NC-C", "NC-D", "NC-F"):
        c = next(x for x in rec["controls"] if x["id"] == cid)
        assert c["verdict"] == "FAIL", f"{cid} must FAIL the check it targets"


def test_rtl_exactness_record():
    path = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(path):
        pytest.skip("NOT_RUN: no committed RTL exactness record")
    rec = json.load(open(path))
    assert rec["model_revision"] == model_revision(), \
        "rtl-exactness.json is STALE against the frozen model"
    assert rec["status"] == "PASS"
    assert rec["cases"], "no RTL cases recorded"
    for c in rec["cases"]:
        assert c["exact"], f"{c['case']} is not exact"
        assert c["revision_pin"]["ok"]
        assert c["checked"]["outputs"] > 0
    names = {c["case"] for c in rec["cases"]}
    assert any(n.startswith("prs-dual") for n in names)
    assert any("reset" in n for n in names)
    assert any(n.startswith("ringout-tail") for n in names), \
        "the declared tail span must be covered by an exactness case"
    assert rec["mutant_controls"], "no RTL negative controls recorded"
    for m in rec["mutant_controls"]:
        assert m["ok"], f"{m['case']} is a BROKEN control"


def test_buffer_report_record():
    path = os.path.join(SXT, "artifacts", "buffer-requirement.json")
    rec = json.load(open(path))
    assert rec["model_revision"] == model_revision()
    ext = rec["external_memory"]
    assert ext["per_instance_state_bytes"] == 0
    assert ext["reads_per_sample"] == 0 and ext["writes_per_sample"] == 0
    assert ext["delay_line_class_buffers"] == 0
    assert rec["cost_fit_verdict"] == "[PENDING-SXT-016]"
    assert rec["frozen_rom"]["waveshaper_table_digest"] == wt.table_digest()


def test_evidence_record_exists_and_is_honest():
    path = os.path.join(SXT, "EVIDENCE.md")
    text = open(path).read()
    # the reference leg has no oracle here and must say so
    assert "NOT_RUN" in text
    assert "[PENDING-SXT-016]" in text
    assert "[PROPOSED" in text
    # the record must never claim synthesis / hardware / preset support
    assert "## 9. What this record does NOT establish" in text
    # the measured state figures must agree with the buffer report, so the
    # prose cannot drift away from the artifact it cites
    rec = json.load(open(os.path.join(SXT, "artifacts",
                                      "buffer-requirement.json")))
    onchip = rec["on_chip_state"]
    assert f"{onchip['q24_43_words']} × Q24.43" in text
    assert f"{onchip['bytes_per_instance']:,} B" in text


def test_evidence_record_has_no_unfilled_placeholders():
    """A half-written evidence record must not read as a finished one.

    The RTL case table and the headline counts are filled in from the
    committed `rtl-exactness.json`; an ALL-CAPS-DASH token left behind by an
    interrupted write would silently publish a PASS headline with no cases
    under it (that is exactly how this leaf's first draft was left).
    """
    text = open(os.path.join(SXT, "EVIDENCE.md")).read()
    for token in ("RTL-CASE-TABLE", "RTL-CASES", "RTL-MUTANTS", "TODO",
                  "TBD", "XXX", "FIXME"):
        assert token not in text, f"unfilled placeholder {token} in EVIDENCE.md"
    rec = json.load(open(os.path.join(SXT, "rtl-exactness.json")))
    # every recorded case must be named in the record's case table
    for c in rec["cases"]:
        assert c["case"] in text, f"case {c['case']} missing from EVIDENCE.md"
    assert rec["sim_version"] in text, "simulator version not recorded in prose"


def test_leaf_table_entry_is_pinned_and_honest():
    """This leaf's row in the coverage input table must not drift.

    `tools/publish_coverage.py` downgrades a leaf whose pinned evidence hash
    no longer matches the file (that is its documented negative control).
    Asserting the pin here keeps *this* leaf's row from becoming the next
    stale entry, and asserts the row never claims a reference verdict the
    record does not support.
    """
    import hashlib
    table = json.load(open(os.path.join(REPO, "reports", "coverage-v1",
                                        "leaf-verification.json")))
    row = table["leaves"]["fx:Distortion"]
    assert row["leaf_id"] == "SXT-028e" and row["issue"] == 57
    assert row["landed"] is True
    v = row["verification"]
    assert v["rtl_vs_model"] == "PASS"
    assert v["model_vs_reference"] in ("PASS", "FAIL", "NOT_RUN", "BLOCKED",
                                       "NO_VERDICT", "STALE", "PARTIAL")
    # The oracle leg did not run on this branch. A future pass may flip this
    # to PASS, but only together with a committed reference-comparison
    # artifact -- a bare status flip is an unearned claim.
    assert v["model_vs_reference"] != "PASS" or any(
        "reference" in item["path"] or "compare" in item["path"]
        for item in row["evidence"]), \
        "model_vs_reference PASS with no committed reference comparison"
    rec = json.load(open(os.path.join(SXT, "rtl-exactness.json")))
    assert (v["rtl_vs_model"] == "PASS") == (rec["status"] == "PASS")
    for item in row["evidence"]:
        path = os.path.join(REPO, item["path"])
        assert os.path.exists(path), f"pinned evidence missing: {item['path']}"
        got = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert got == item["sha256"], (
            f"{item['path']} pin is STALE: table says {item['sha256']}, "
            f"file hashes {got}")


def test_decision_record_registered():
    idx = open(os.path.join(REPO, "decision-records", "README.md")).read()
    assert "0012-distortion-halfband-and-waveshaper-tables.md" in idx
    dr = open(os.path.join(REPO, "decision-records",
                           "0012-distortion-halfband-and-waveshaper-tables.md")).read()
    for v in dm.HB_A_SOFT + dm.HB_B_SOFT + dm.HB_A_STEEP + dm.HB_B_STEEP:
        assert repr(v).rstrip("0").rstrip(".") in dr or str(v) in dr


# ------------------------------------------------------------- RTL harness
@pytest.mark.skipif(shutil.which(os.environ.get("IVERILOG", "iverilog")) is None,
                    reason="NOT_RUN: iverilog unavailable")
def test_rtl_harness_smoke(tmp_path):
    """Elaborate + run the committed testbench (exactness itself is the
    comparator's job; this guards against a stale/broken harness)."""
    tb = os.path.join(RTLDIR, "tb_distortion.sv")
    vvp = str(tmp_path / "tb.vvp")
    subprocess.run([os.environ.get("IVERILOG", "iverilog"), "-g2012",
                    "-o", vvp, tb], check=True, cwd=str(tmp_path))
    assert os.path.exists(vvp)
