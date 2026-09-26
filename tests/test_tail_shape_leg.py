#!/usr/bin/env python3
"""Wet-path tail gate: tail-SHAPE (windowed decay-curve) leg (issue #111).

The pre-#111 gate integrated the residual RMS over the whole declared tail
region, which the loud early tail dominates, so a model that dropped only the
LATE part of a long tail passed every budget and the gate. These tests pin:

  * the decay-curve budget (window, floor, max deviation) is DECLARED in
    compare_audio_reference.PROPOSED_TAIL and is never inferred from silence;
  * the committed SXT-028c alienappears model render keeps passing, while the
    late-tail truncations that used to pass (zeroed from 40% and 60% of the
    declared tail) and a late-tail fast decay now FAIL -- on the new leg,
    while the three global budgets and the whole-region residual leg still
    pass (the new leg does the work);
  * the leg applies to the mono shared comparator and to mono sum, L and R
    of the stereo gate;
  * a reference tail with no window at/above the declared floor cannot be
    shape-graded and fails closed instead of passing vacuously;
  * the committed #111 evidence summary says what the record claims.

Claim scope: comparator behaviour only. Control renders are derived from
committed renders; nothing here is a model-vs-reference, RTL, preset-support,
or sound claim, and no budget is frozen.
"""

import json
import os
import struct
import subprocess
import sys
import wave

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402

CHORUS = os.path.join(REPO, "tools", "compare_chorus_reference.py")
SHARED = os.path.join(REPO, "tools", "compare_audio_reference.py")
SXT = os.path.join(REPO, "reports", "SXT-028c")
SLUG, SEQ = "alienappears", "seq-notes-coverage-v1"
SIDECAR = os.path.join(SXT, "fixtures", "%s__%s.json" % (SLUG, SEQ))
MODEL = os.path.join(SXT, "artifacts", "model__%s__%s.f32.wav" % (SLUG, SEQ))
MONO_REF = os.path.join(REPO, "fixtures", "audio", "behemoth",
                        "seq-notes-coverage-v1-wet.wav")
MONO_SIDECAR = os.path.join(REPO, "fixtures", "audio", "behemoth",
                            "seq-notes-coverage-v1.json")
EVID = os.path.join(REPO, "reports", "tail-shape-leg")

SHAPE_KEYS = ("decay_curve_window_s", "decay_curve_floor_dbfs",
              "decay_curve_max_dev_db")


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
    a = np.asarray(a, dtype="<f4")
    inter = a.T.reshape(-1).tobytes()
    fmt = struct.pack("<HHIIHH", 3, 2, 48000, 48000 * 8, 8, 32)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(inter)) + inter)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)


def write_i16(path, a):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.asarray(a).astype("<i2").tobytes())


def chorus(model_path, out):
    r = subprocess.run([sys.executable, CHORUS, "--slug", SLUG, "--seq", SEQ,
                        "--model", model_path, "--json", str(out)],
                       capture_output=True, text=True, cwd=REPO)
    return r, json.load(open(out))


@pytest.fixture(scope="module")
def region():
    return car.declared_tail_region(SIDECAR, "wet")


# ------------------------------------------------------------- budget -----

def test_shape_budget_is_declared():
    for k in SHAPE_KEYS:
        assert isinstance(car.PROPOSED_TAIL[k], float), k
    assert car.PROPOSED_TAIL["decay_curve_window_s"] > 0
    assert car.PROPOSED_TAIL["decay_curve_max_dev_db"] > 0
    # the pre-#111 residual budget is unchanged
    assert car.PROPOSED_TAIL["tail_rms_rel_db"] == -20.0


def test_floor_is_declared_not_inferred_from_silence():
    """The graded floor is the declared constant whatever the render's own
    noise floor is (two references with very different quiet levels)."""
    sr = 48000
    t = np.arange(sr) / sr
    region = {"tail_offset": 0, "tail_frames": sr, "sidecar": "synthetic",
              "tail_region_source": "synthetic", "sample_rate": sr}
    for noise in (1e-7, 1e-3):
        ref = np.sin(2 * np.pi * 440 * t) * np.exp(-t / 0.2) + noise
        tc = car.tail_check(ref, ref.copy(), region, full_scale=1.0)
        dc = tc["tail_decay_curve"]
        assert dc["floor_dbfs"] == car.PROPOSED_TAIL["decay_curve_floor_dbfs"]
        assert dc["window_frames"] == int(round(
            car.PROPOSED_TAIL["decay_curve_window_s"] * sr))
        assert dc["ok"] is True and tc["ok"] is True


def test_no_window_above_floor_fails_closed():
    """A reference tail wholly below the declared floor cannot be
    shape-graded: FAIL, never a vacuous pass."""
    sr = 48000
    region = {"tail_offset": 0, "tail_frames": sr, "sidecar": "synthetic",
              "tail_region_source": "synthetic", "sample_rate": sr}
    ref = np.full(sr, 1e-7)          # -140 dBFS, present but below -100
    tc = car.tail_check(ref, ref.copy(), region, full_scale=1.0)
    assert tc["tail_present"] is True
    assert tc["tail_decay_curve"]["graded_windows"] == 0
    assert tc["tail_decay_curve"]["ok"] is False
    assert tc["ok"] is False
    assert "floor" in tc["reason"]


def test_model_extra_late_energy_fails():
    """The deviation is two-sided: a model tail that fails to decay also
    fails the shape leg."""
    sr = 48000
    t = np.arange(2 * sr) / sr
    region = {"tail_offset": 0, "tail_frames": 2 * sr, "sidecar": "synthetic",
              "tail_region_source": "synthetic", "sample_rate": sr}
    ref = np.sin(2 * np.pi * 440 * t) * np.exp(-t / 0.15)
    mod = ref + 1e-4 * np.sin(2 * np.pi * 440 * t)
    tc = car.tail_check(ref, mod, region, full_scale=1.0)
    assert tc["tail_decay_curve"]["ok"] is False and tc["ok"] is False


# ------------------------------------------- stereo gate, committed data --

def test_committed_model_keeps_passing(tmp_path, region):
    r, j = chorus(MODEL, tmp_path / "base.json")
    # the chorus tool exits 0 on any graded verdict; the verdict field decides
    assert r.returncode == 0 and j["verdict"].startswith("PASS"), j["verdict"]
    for c in (j["tail_check"], j["tail_check_lr"]["L"],
              j["tail_check_lr"]["R"]):
        dc = c["tail_decay_curve"]
        assert dc["ok"] is True and dc["graded_windows"] > 0
        assert dc["max_dev_db"] <= car.PROPOSED_TAIL["decay_curve_max_dev_db"]


@pytest.mark.parametrize("frac", [0.4, 0.6])
def test_late_tail_truncation_fails_on_the_shape_leg(tmp_path, region, frac):
    """The #111 KNOWN-GAP probes: zeroing only the late tail used to PASS
    every budget and the gate. It must now FAIL, and the new leg must be the
    one that fails it (budgets and the whole-region residual leg pass)."""
    off, length = region["tail_offset"], region["tail_frames"]
    m = read_f32(MODEL)
    m[:, off + int(length * frac):off + length] = 0.0
    p = tmp_path / "late.f32.wav"
    write_f32(p, m)
    r, j = chorus(str(p), tmp_path / "late.json")
    assert r.returncode == 0 and j["verdict"].startswith("FAIL"), j["verdict"]
    assert all(j["proposed_budget_results"].values())
    tc = j["tail_check"]
    assert tc["tail_rms_rel_ok"] is True
    assert tc["tail_decay_curve"]["ok"] is False
    assert j["tail_gate_ok"] is False


def test_late_tail_fast_decay_fails_on_the_shape_leg(tmp_path, region):
    off, length = region["tail_offset"], region["tail_frames"]
    s0 = off + int(length * 0.4)
    m = read_f32(MODEL).astype(np.float64)
    t = np.arange(off + length - s0) / 48000.0
    m[:, s0:off + length] *= np.exp(-t / 0.2)
    p = tmp_path / "fast.f32.wav"
    write_f32(p, m)
    r, j = chorus(str(p), tmp_path / "fast.json")
    assert r.returncode == 0 and j["verdict"].startswith("FAIL")
    assert j["tail_check"]["tail_decay_curve"]["ok"] is False


def test_single_channel_late_tail_drop_is_seen_per_channel(region):
    off, length = region["tail_offset"], region["tail_frames"]
    ref = read_f32(os.path.join(SXT, "fixtures",
                                "%s__%s-wet.f32.wav" % (SLUG, SEQ)))
    m = read_f32(MODEL)
    m[1, off + int(length * 0.6):off + length] = 0.0
    mono, lr, ok, reason = car.stereo_tail_gate(ref, m, region, 2.0 ** -21)
    assert ok is False
    assert lr["R"]["tail_decay_curve"]["ok"] is False
    assert lr["L"]["tail_decay_curve"]["ok"] is True
    assert "R:" in reason


# ---------------------------------------------------- mono shared tool ----

def test_mono_shared_tool_applies_the_shape_leg(tmp_path):
    ref, _ = car.read_wav(MONO_REF)
    region = car.declared_tail_region(MONO_SIDECAR, "wet")
    off, length = region["tail_offset"], region["tail_frames"]
    base = tmp_path / "self.wav"
    write_i16(base, ref)
    r = subprocess.run([sys.executable, SHARED, "--path", "wet", "--sidecar",
                        MONO_SIDECAR, "--ref", MONO_REF, "--model", str(base),
                        "--json", str(tmp_path / "self.json")],
                       capture_output=True, text=True, cwd=REPO)
    j = json.load(open(tmp_path / "self.json"))
    assert r.returncode == 0 and j["verdict"].startswith("PASS")
    assert j["tail_check"]["tail_decay_curve"]["ok"] is True
    m = ref.copy()
    m[off + int(length * 0.6):off + length] = 0
    late = tmp_path / "late.wav"
    write_i16(late, m)
    r = subprocess.run([sys.executable, SHARED, "--path", "wet", "--sidecar",
                        MONO_SIDECAR, "--ref", MONO_REF, "--model", str(late),
                        "--json", str(tmp_path / "late.json")],
                       capture_output=True, text=True, cwd=REPO)
    j = json.load(open(tmp_path / "late.json"))
    assert r.returncode == 1 and j["verdict"].startswith("FAIL")
    assert j["tail_check"]["tail_decay_curve"]["ok"] is False
    assert j["proposed_tail_budget"] == car.PROPOSED_TAIL


# ------------------------------------------------------ committed record --

def test_committed_evidence_summary_is_current():
    p = os.path.join(EVID, "artifacts", "checks-summary.json")
    s = json.load(open(p))
    assert s["issue"] == 111 and s["overall"] == "PASS"
    assert s["proposed_tail_budget"] == car.PROPOSED_TAIL
    rr = s["legs"]["landed_verdict_rerun"]
    assert rr["status"] == "PASS"
    assert rr["verdict_status_changes"] == 0
    names = {c["case"] for c in rr["cases"]}
    assert len([n for n in names if n.startswith("SXT-028c")]) == 6
    assert len([n for n in names if n.startswith("sxt-023")]) == 3
    assert len([n for n in names if n.startswith("sxt-024")]) == 3
    assert len([n for n in names if n.startswith("#93")]) >= 5
    ctl = s["legs"]["late_tail_controls"]
    assert ctl["status"] == "PASS"
    got = {c["control"]: c for c in ctl["controls"]}
    for name in ("stereo/zero-late-tail-from-40%",
                 "stereo/zero-late-tail-from-60%"):
        assert got[name]["observed"] == "FAIL", name
        assert got[name]["pre111_tool_status"] == "PASS", name
        assert got[name]["tail_rms_rel_ok"] is True, name
        assert got[name]["tail_decay_curve_ok"] is False, name
    assert got["stereo/baseline"]["observed"] == "PASS"
    assert got["mono/behemoth/baseline"]["observed"] == "PASS"
    controls = [c for c in ctl["controls"] if c["result"] != "CHARACTERIZATION"]
    assert controls and all(c["result"] == "CONTROL-OK" for c in controls)
    # the mono path has its own shape-leg-only controls
    assert any(n.startswith("mono/") for n in ctl["shape_leg_load_bearing"])
    # the floor's limit is recorded as a characterization, never a control
    chars = [c for c in ctl["controls"] if c["result"] == "CHARACTERIZATION"]
    assert chars and all(c["zeroed_span_ref_dbfs"] <
                         car.PROPOSED_TAIL["decay_curve_floor_dbfs"]
                         for c in chars)
