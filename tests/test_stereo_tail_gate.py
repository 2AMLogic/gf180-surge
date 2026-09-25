#!/usr/bin/env python3
"""Stereo float32 comparator wet-path tail gate + metric decisions (issue #100).

Covers, on the committed SXT-028c / sxt-023 fixtures and model renders:
  * the chorus and fx comparators read the tail region from the fixture
    sidecar's declared values (not a hard-coded window) and refuse
    (NO_VERDICT, exit 2) when the sidecar is missing or does not declare it;
  * the committed model render PASSES while a zeroed tail, a single dropped
    channel tail, and a render truncated at the tail offset FAIL -- the last
    one while all three global budgets still pass (the gate does the work);
  * rms_diff_dbfs under exact agreement is the finite floor and the emitted
    JSON is strict (no -Infinity), for all three emitters;
  * the committed #100 evidence summary still says what the record claims.

Claim scope: comparator behaviour only. Control renders are derived from
committed renders; nothing here is a model-vs-reference, RTL, preset-support,
or sound claim.
"""

import copy
import json
import os
import struct
import subprocess
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402

CHORUS = os.path.join(REPO, "tools", "compare_chorus_reference.py")
FX = os.path.join(REPO, "tools", "compare_fx_reference.py")
SXT = os.path.join(REPO, "reports", "SXT-028c")
SLUG, SEQ = "fmcombo", "seq-notes-coverage-v1"
SIDECAR = os.path.join(SXT, "fixtures", "%s__%s.json" % (SLUG, SEQ))
MODEL = os.path.join(SXT, "artifacts", "model__%s__%s.f32.wav" % (SLUG, SEQ))
FX_REF = os.path.join(REPO, "reports", "sxt-023", "fixtures",
                      "fm_bass_1__seq-notes-coverage-v1-wet.f32.wav")
FX_MODEL = os.path.join(REPO, "reports", "sxt-023", "artifacts",
                        "model__fm_bass_1__seq-notes-coverage-v1.f32.wav")
EVID = os.path.join(REPO, "reports", "stereo-comparator-tail-gate")


def strict(text):
    def bad(tok):
        raise ValueError(tok)
    return json.loads(text, parse_constant=bad)


def read_f32(path):
    with open(path, "rb") as f:
        data = f.read()
    pos, raw = 12, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        sz = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"data":
            raw = data[pos + 8:pos + 8 + sz]
        pos += 8 + sz + (sz & 1)
    return np.frombuffer(raw, dtype="<f4").reshape(-1, 2).T.copy()


def write_f32(path, a):
    inter = np.asarray(a, dtype="<f4").T.reshape(-1).tobytes()
    fmt = struct.pack("<HHIIHH", 3, 2, 48000, 48000 * 8, 8, 32)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(inter)) + inter)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


def chorus(tmp_path, model=MODEL, sidecar=None, tag="out"):
    out = tmp_path / ("%s.json" % tag)
    cmd = [sys.executable, CHORUS, "--slug", SLUG, "--seq", SEQ,
           "--model", str(model), "--json", str(out)]
    if sidecar:
        cmd += ["--sidecar", str(sidecar)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    return r, (strict(out.read_text()) if out.exists() else {})


@pytest.fixture(scope="module")
def region():
    return car.declared_tail_region(SIDECAR, "wet")


def test_region_is_the_declared_sidecar_region(region):
    sc = json.load(open(SIDECAR))
    tail = int(round(sc["render"]["tail_s"] * sc["render"]["sample_rate"]))
    assert region["tail_frames"] == tail == 120000     # 2.5 s, not 2.0 s
    assert region["tail_offset"] == sc["render"]["frames"] - tail


def test_committed_model_passes_with_full_gate(tmp_path, region):
    r, j = chorus(tmp_path)
    assert r.returncode == 0
    assert j["verdict"].startswith("PASS") and "PENDING-FREEZE" in j["verdict"]
    tc = j["tail_check"]
    assert tc["tail_offset"] == region["tail_offset"]
    assert tc["tail_frames"] == region["tail_frames"]
    assert j["tail_gate_ok"] is True
    assert set(j["tail_check_lr"]) == {"L", "R"}


def test_zeroed_tail_fails(tmp_path, region):
    m = read_f32(MODEL)
    off, n = region["tail_offset"], region["tail_frames"]
    m[:, off:off + n] = 0.0
    r, j = chorus(tmp_path, write_f32(tmp_path / "drop.f32.wav", m))
    assert j["verdict"].startswith("FAIL")
    assert j["tail_gate_ok"] is False
    assert j["tail_check"]["model_tail_present"] is False


def test_single_channel_dropped_tail_fails(tmp_path, region):
    m = read_f32(MODEL)
    off, n = region["tail_offset"], region["tail_frames"]
    m[1, off:off + n] = 0.0
    r, j = chorus(tmp_path, write_f32(tmp_path / "dropr.f32.wav", m))
    assert j["verdict"].startswith("FAIL")
    assert j["tail_check_lr"]["R"]["model_tail_present"] is False
    assert j["tail_check_lr"]["L"]["ok"] is True


def test_truncated_render_fails_on_gate_alone(tmp_path, region):
    m = read_f32(MODEL)[:, :region["tail_offset"]]
    r, j = chorus(tmp_path, write_f32(tmp_path / "trunc.f32.wav", m))
    assert all(j["proposed_budget_results"].values())   # budgets vacuous
    assert j["tail_check"]["tail_region_covered"] is False
    assert j["verdict"].startswith("FAIL")


def test_chorus_refuses_without_declared_region(tmp_path):
    r, j = chorus(tmp_path, sidecar=tmp_path / "nope.json", tag="missing")
    assert r.returncode == 2 and j["verdict"].startswith("NO_VERDICT")
    sc = json.load(open(SIDECAR))
    bad = copy.deepcopy(sc)
    del bad["render"]["tail_s"]
    p = tmp_path / "undeclared.json"
    p.write_text(json.dumps(bad))
    r, j = chorus(tmp_path, sidecar=p, tag="undeclared")
    assert r.returncode == 2 and j["verdict"].startswith("NO_VERDICT")
    stale = copy.deepcopy(sc)
    stale["render"]["frames"] -= 48000
    p = tmp_path / "stale.json"
    p.write_text(json.dumps(stale))
    r, j = chorus(tmp_path, sidecar=p, tag="stale")
    assert r.returncode == 2 and "STALE" in j["reason"]


def test_fx_tool_gated_and_refusing(tmp_path):
    out = tmp_path / "fx.json"
    r = subprocess.run([sys.executable, FX, "--ref", FX_REF, "--model",
                        FX_MODEL, "--json", str(out)],
                       capture_output=True, text=True, cwd=REPO)
    j = strict(out.read_text())
    assert r.returncode == 0 and j["verdict"].startswith("PASS")
    assert j["tail_gate_ok"] is True and j["tail_check"]["tail_frames"] == 120000
    out2 = tmp_path / "fx-refused.json"
    r = subprocess.run([sys.executable, FX, "--ref", FX_REF, "--model",
                        FX_MODEL, "--sidecar", str(tmp_path / "nope.json"),
                        "--json", str(out2)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 2
    assert strict(out2.read_text())["verdict"].startswith("NO_VERDICT")


def test_rms_diff_dbfs_exact_agreement_is_finite_floor(tmp_path):
    assert car.rms_dbfs(0.0, 32767.0) == car.RMS_DIFF_DBFS_FLOOR == -300.0
    assert car.rms_dbfs(1.0, 32767.0) == pytest.approx(-90.309, abs=1e-3)
    ref = os.path.join(SXT, "fixtures", "%s__%s-wet.f32.wav" % (SLUG, SEQ))
    r, j = chorus(tmp_path, model=ref, tag="exact")
    assert j["channels"]["mono"]["rms_diff_dbfs"] == -300.0
    assert j["verdict"].startswith("PASS")


def test_no_committed_report_json_carries_nonstandard_tokens():
    import glob
    for p in glob.glob(os.path.join(REPO, "reports", "**", "*.json"),
                       recursive=True):
        strict(open(p).read())


def test_committed_evidence_summary_is_current():
    s = json.load(open(os.path.join(EVID, "artifacts", "checks-summary.json")))
    assert s["issue"] == 100 and s["overall"] == "PASS"
    legs = s["legs"]
    rerun = legs["sxt028c_rerun"]
    assert rerun["status"] == "PASS" and len(rerun["cases"]) == 6
    for c in rerun["cases"]:
        assert c["status_before"] == c["status_after"] == "PASS"
        assert c["verdict_status_changed"] is False and c["unexplained"] == 0
    ctl = legs["stereo_tail_controls"]
    assert ctl["status"] == "PASS"
    assert all(c["result"] == "CONTROL-OK" for c in ctl["controls"])
    assert legs["rms_diff_dbfs_floor"]["status"] == "PASS"
    other = legs["other_stereo_comparators_rerun"]
    assert other["status"] == "PASS"
    for c in other["sxt023"]:
        assert c["verdict_status_changed"] is False
    for c in other["sxt024"]:
        assert c["committed_pass"] == c["gated_pass"]
        assert c["gate_only_addition"] is True
