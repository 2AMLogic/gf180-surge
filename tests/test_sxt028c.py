"""SXT-028c Chorus leaf tests (pytest).

Covers: frozen arithmetic/constant inventory, model determinism + per-
instance independence, tail decay, external-memory traffic accounting
(49 words/sample), the SXT-015 reconciliation, the padding-copy wrap-read
semantics, negative-control evidence integrity, and the committed
comparison/RTL-exactness records (fail-closed). Oracle-dependent legs
(reference renders, extractions) run on the oracle host via
tools/render_chorus_fixtures.py / tools/extract_chorus_inputs.py; here we
only check the committed evidence records for coherence. A missing
iverilog/oracle makes those legs NOT_RUN, never a pass.
"""
import gzip
import json
import math
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-chorus"))
sys.path.insert(0, os.path.join(REPO, "model", "effects"))

import chorus_model as cm  # noqa: E402
from chorus_model import (  # noqa: E402
    ChorusModel, ChorusParams, LINE_LEN, VOICES, VOICE_PAN, LP_TIME,
    LPINV_TIME, BLOCK, MAX_DELAY, FIRIPOL_N, model_revision,
)

SXT = os.path.join(REPO, "reports", "SXT-028c")
SYNTH = {"time_f": -6.0, "rate_f": -2.0, "depth_f": 0.3, "feedback_f": 0.5,
         "lowcut_f": -36.0, "highcut_f": 36.0, "mix_f": 1.0, "width_f": 0.0}


def make_model(name="t"):
    m = ChorusModel(ChorusParams(dict(SYNTH)), name)
    m.initialize()
    return m


def test_frozen_constants_and_layout():
    assert LINE_LEN == (1 << 18) + 12          # mono line incl. padding
    assert VOICES == 4                          # Effect.cpp:86 ChorusEffect<4>
    assert FIRIPOL_N == 12
    # engine lag pair is float32: lp = 0.001f, lpinv = (float)(1 - 0.001f)
    assert LP_TIME == int(0.0010000000474974513 * (1 << 43) + 0.5)
    assert LPINV_TIME == int(0.9990000128746033 * (1 << 43) + 0.5)
    # voicepan sqrt law with gainscale 1/sqrt(4); voice 0 is hard-left
    assert VOICE_PAN[0] == (131072, 0) and VOICE_PAN[3] == (0, 131072)
    assert VOICE_PAN[1] == (107020, 75674) and VOICE_PAN[2] == (75674, 107020)


def test_model_determinism_and_state():
    outs = []
    for _ in range(2):
        m = make_model()
        rs = random.Random(7)
        o = []
        for _b in range(32):
            il = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
            ir = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
            o.append(m.process_block(il, ir))
        outs.append((o, m.st.checkpoint(), m.st.ext_reads, m.st.ext_writes))
    assert outs[0] == outs[1]
    # 48 reads/sample (4 voices x 12 taps), 32 writes/block + padding copy
    assert outs[0][2] == 32 * BLOCK * VOICES * FIRIPOL_N
    assert outs[0][3] == 32 * BLOCK + FIRIPOL_N


def test_dual_instance_independent_histories():
    pa = dict(SYNTH)
    pb = {"time_f": -4.5, "rate_f": -3.2, "depth_f": 0.6, "feedback_f": 0.15,
          "lowcut_f": -18.0, "highcut_f": 55.0, "mix_f": 0.45, "width_f": -3.0}
    ma = ChorusModel(ChorusParams(pa), "a"); ma.initialize()
    mb = ChorusModel(ChorusParams(pb), "b"); mb.initialize()
    rs = random.Random(3)
    for _ in range(40):
        il = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
        ir = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
        ma.process_block(il, ir)
        mb.process_block(ir, il)
    assert ma.st.line_hash != mb.st.line_hash
    assert ma.st.line is not mb.st.line
    assert ma.st.wpos == mb.st.wpos  # same schedule, different content


def test_padding_copy_wrap_read_semantics():
    """The engine refreshes line[2^18..2^18+11] from line[0..11] when
    wpos == 0; the model reproduces that staleness exactly."""
    m = make_model()
    m.initialize()
    assert all(v == 0 for v in m.st.line[MAX_DELAY:])
    rs = random.Random(9)
    il = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
    ir = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
    m.process_block(il, ir)   # wpos == 0: padding copy must fire
    assert m.st.line[MAX_DELAY:] == m.st.line[:FIRIPOL_N]
    assert m.st.line[MAX_DELAY] == (il[0] + ir[0])  # mono fbblock, fb path 0
    # wpos != 0 afterwards: padding stays stale while line[0..] moves on
    il2 = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
    ir2 = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
    m.process_block(il2, ir2)
    assert m.st.line[MAX_DELAY] == (il[0] + ir[0])


def test_tail_decays_and_temposync_formula():
    m = make_model()
    rs = random.Random(4)
    for _ in range(32):
        blk = [rs.randint(-(1 << 22), 1 << 22) for _ in range(BLOCK)]
        m.process_block(blk, blk)
    # silence: the first ~31 blocks still carry the ~1000-sample tail; the
    # tail must be decayed by the end (fb loop gain << 1)
    for _ in range(96):
        ol, orr = m.process_block([0] * BLOCK, [0] * BLOCK)
    late = max(max(abs(v) for v in ol), max(abs(v) for v in orr))
    assert late < (1 << 17)
    # temposync: ratio paths are pure control-plane formulas
    p = ChorusParams(dict(SYNTH, ts_time=True, ts_rate=True,
                          ts_ratio=0.8, ts_ratio_mod=1.25))
    m2 = ChorusModel(p, "ts"); m2.initialize()
    assert m2.p.ts_ratio == 0.8 and m2.p.ts_ratio_mod == 1.25


def test_buffer_requirement_record():
    br = json.load(open(os.path.join(SXT, "artifacts",
                                     "buffer-requirement.json")))
    assert br["external_writable_memory"]["words_total"] == LINE_LEN
    assert br["external_writable_memory"]["bytes_total"] == LINE_LEN * 4
    assert br["sxt015_reconciliation"]["agreement"] is True
    wp = br["external_traffic"]["words_per_sample_32bit"]
    assert abs(wp - 49.0) < 0.01          # 48 reads + 1 write (+ amortized)
    assert br["external_traffic"]["reads_per_sample"] == VOICES * 12
    assert br["on_chip_small_state"]["bits"] < 4096


def test_reference_comparisons_recorded_and_coherent():
    comp = os.path.join(SXT, "artifacts")
    files = sorted(f for f in os.listdir(comp)
                   if f.startswith("compare-") and f.endswith(".json"))
    assert len(files) == 6, files
    for fn in files:
        d = json.load(open(os.path.join(comp, fn)))
        assert d["verdict"].startswith("PASS"), fn
        assert "PENDING-FREEZE" in d["verdict"], fn          # never frozen
        assert d["proposed_budget_results"]["max_abs_diff_lsb"] is True, fn
        assert d["proposed_budget_results"]["rms_diff_dbfs"] is True, fn
        # issue #100: declared-region tail gate (mono + L + R), not the old
        # hard-coded 2.0 s reference-presence check
        assert d["schema_version"] == 2, fn
        assert d["tail_gate_ok"] is True, fn
        tc = d["tail_check"]
        sc = json.load(open(os.path.join(REPO, tc["tail_region_sidecar"])))
        tail = int(round(sc["render"]["tail_s"] * sc["render"]["sample_rate"]))
        assert tc["tail_frames"] == tail, fn
        assert tc["tail_offset"] == sc["render"]["frames"] - tail, fn
        for c in (tc, d["tail_check_lr"]["L"], d["tail_check_lr"]["R"]):
            assert c["tail_region_covered"] and c["tail_present"], fn
            assert c["model_tail_present"] and c["ok"], fn
            assert c["tail_rms_rel_db"] <= d["proposed_tail_budget"][
                "tail_rms_rel_db"], fn


def test_extraction_records_fail_closed():
    for slug in ("fmcombo", "fmtwang2", "alienappears"):
        d = json.load(open(os.path.join(REPO, "model", "effects", "fx_inputs",
                                        f"type-chorus-{slug}.json")))
        assert d["applicability"]["complete_wet_render_possible"] is True
        assert d["drifts_asserted_zero"] == [0.0]
    ref = open(os.path.join(SXT, "artifacts", "extract-refusals.txt")).read()
    assert "novuo" in ref and "ancient_fm" in ref and "piercing" in ref
    rr = open(os.path.join(SXT, "artifacts", "render-refusals.txt")).read()
    assert "melon" in rr and "dronebee" in rr


def test_negative_controls_all_fail_their_checks():
    d = json.load(open(os.path.join(SXT, "negative-controls",
                                    "negative-controls.json")))
    assert d["status"] == "PASS"
    assert len(d["controls"]) >= 6
    for c in d["controls"]:
        assert c["ok"] is True and "CONTROL-OK" in c["verdict"], c["control"]


def test_rtl_exactness_record():
    p = os.path.join(SXT, "rtl-exactness.json")
    if not os.path.exists(p):
        pytest.skip("rtl-exactness.json not committed (NOT_RUN)")
    d = json.load(open(p))
    assert d["status"] == "PASS"
    assert d["model_revision"] == model_revision(), "stale record"
    for c in d["cases"]:
        assert c["exact"] is True, c["case"]
        assert c["revision_pin"]["ok"] is True, c["case"]
    for m in d["mutant_controls"]:
        assert m["exact"] is False and "CONTROL-OK" in m["verdict"], \
            m["case"]


def test_canonical_traces_present_for_reproduction():
    art = os.path.join(SXT, "artifacts")
    # the canonical legs' model truth + the RTL replay stimulus for the
    # notes carriers (poly-8 stimulus regenerable via the documented
    # runner command)
    for slug, seq, need_hex in (
            ("fmcombo", "seq-notes-coverage-v1", True),
            ("fmtwang2", "seq-notes-coverage-v1", True),
            ("alienappears", "seq-notes-coverage-v1", True),
            ("fmcombo", "seq-poly-8-v1", False),
            ("fmtwang2", "seq-poly-8-v1", False),
            ("alienappears", "seq-poly-8-v1", False)):
        assert os.path.exists(os.path.join(
            art, f"trace_{slug}__{seq}.json.gz")), (slug, seq)
        if need_hex:
            assert os.path.exists(os.path.join(
                art, "rtl", f"{slug}__{seq}_in.hex")), (slug, seq)
            assert os.path.exists(os.path.join(
                art, "rtl", f"{slug}__{seq}_ctrl.hex")), (slug, seq)
