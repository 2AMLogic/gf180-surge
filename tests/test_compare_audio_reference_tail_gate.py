#!/usr/bin/env python3
"""Issue #93 (SXT-028c follow-up): tail-region gate in the shared comparator
tools/compare_audio_reference.py.

Covers: the wet-path (--fixture-meta) verdict requires BOTH budget-pass and
tail-pass (never one without the other), a silent/truncated tail FAILS even
when the whole-render budget alone would pass, the tail region is sourced
only from the fixture's own declared render.duration_s/render.tail_s (never
from silence detection), and the dry (no --fixture-meta) path is completely
unaffected -- this is the regression guard: if the wet-path gate is ever
re-wired to also touch the dry path, or the tail check is ever weakened to
accept a silent tail, this test must fail.
"""
import json
import os
import struct
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402

SR = 48000


def _write_wav_stereo_f32(path, stereo):
    nch, frames = stereo.shape
    data = np.ascontiguousarray(stereo.T, dtype="<f4").tobytes()
    byte_rate = SR * nch * 4
    block_align = nch * 4
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, nch, SR, byte_rate,
                                 block_align, 32)
    hdr += b"data" + struct.pack("<I", len(data))
    with open(path, "wb") as f:
        f.write(hdr + data)


def _write_wav_mono16(path, mono_int16):
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(mono_int16.astype("<i2").tobytes())


def _synth_fixture(duration_s=3.0, tail_s=1.0, seed=1):
    """A deterministic stereo signal: broadband body, then an exponentially
    decaying (but non-silent) tail -- representative of an effect return
    (reverb/delay/chorus tail), not a hard cutoff."""
    n = int(round(duration_s * SR))
    tail_n = int(round(tail_s * SR))
    body_n = n - tail_n
    rs = np.random.RandomState(seed)
    body = 0.2 * rs.standard_normal(body_n)
    t = np.arange(tail_n) / SR
    tail = 0.15 * np.exp(-t / (tail_s * 0.4)) * rs.standard_normal(tail_n)
    mono = np.concatenate([body, tail]).astype(np.float64)
    stereo = np.stack([mono, mono * 0.9])
    return stereo.astype(np.float32)


def _fixture_meta(tmp_path, duration_s, tail_s):
    meta = {"render": {"duration_s": duration_s, "tail_s": tail_s}}
    p = tmp_path / "fixture.json"
    p.write_text(json.dumps(meta))
    return str(p)


def _run_wet(tmp_path, ref, mod, duration_s=3.0, tail_s=1.0, capsys=None):
    ref_p = str(tmp_path / "ref-wet.f32.wav")
    mod_p = str(tmp_path / "model-wet.f32.wav")
    _write_wav_stereo_f32(ref_p, ref)
    _write_wav_stereo_f32(mod_p, mod)
    meta_p = _fixture_meta(tmp_path, duration_s, tail_s)
    out_json = str(tmp_path / "out.json")

    class Args:
        pass
    a = Args()
    a.ref, a.model, a.json, a.fixture_meta = ref_p, mod_p, out_json, meta_p
    rc = car.main_wet(a)
    with open(out_json) as f:
        metrics = json.load(f)
    return rc, metrics


def test_full_tail_waveform_passes_tail_check(tmp_path):
    ref = _synth_fixture()
    mod = ref.copy()  # exact match, including the declared tail
    rc, metrics = _run_wet(tmp_path, ref, mod)
    assert metrics["tail_check"]["ok"] is True
    assert metrics["tail_check"]["tail_present"] is True
    assert metrics["proposed_budget_results"]["max_abs_diff_lsb"] is True
    assert metrics["verdict"].startswith("PASS")


def test_silent_tail_waveform_fails_where_full_tail_passes(tmp_path):
    """The acceptance-#5 regression guard: a model whose tail region has
    been zeroed (silent) must FAIL the verdict on the SAME fixture that
    passes when its tail is intact -- the primary (whole-render) budget
    alone must not be enough to paper over a silent tail."""
    ref = _synth_fixture()

    d_full = tmp_path / "full"
    d_full.mkdir()
    rc1, metrics_full = _run_wet(d_full, ref, ref.copy())

    d_silent = tmp_path / "silent"
    d_silent.mkdir()
    silent_tail_mod = ref.copy()
    tail_n = int(round(1.0 * SR))
    silent_tail_mod[:, -tail_n:] = 0.0
    rc2, metrics_silent = _run_wet(d_silent, ref, silent_tail_mod)

    assert metrics_full["tail_check"]["ok"] is True
    assert metrics_full["verdict"].startswith("PASS")

    assert metrics_silent["tail_check"]["ok"] is False
    assert "FAIL" in metrics_silent["verdict"]
    assert "tail-region check" in metrics_silent["verdict"]


def test_dropped_tail_truncation_fails_verdict(tmp_path):
    """A model render truncated before the declared tail span (dropped
    tail, not just silenced) must also FAIL -- caught by the model's tail
    window being incomplete, not by a magnitude threshold."""
    ref = _synth_fixture(duration_s=3.0, tail_s=1.0)
    tail_n = int(round(1.0 * SR))
    truncated_mod = ref[:, : ref.shape[1] - tail_n]  # 1.0s short of the ref
    rc, metrics = _run_wet(tmp_path, ref, truncated_mod, duration_s=3.0,
                           tail_s=1.0)
    assert metrics["tail_check"]["ok"] is False
    assert metrics["tail_check"]["tail_frames_model_available"] < \
        metrics["tail_check"]["tail_frames_declared"]
    assert "FAIL" in metrics["verdict"]


def test_tail_region_sourced_from_fixture_metadata_only(tmp_path):
    """offset_s/length_s must come from render.duration_s - render.tail_s /
    render.tail_s in the fixture sidecar, not be silence-derived."""
    ref = _synth_fixture(duration_s=4.0, tail_s=1.5)
    rc, metrics = _run_wet(tmp_path, ref, ref.copy(), duration_s=4.0,
                           tail_s=1.5)
    assert metrics["tail_region"]["offset_s"] == pytest.approx(2.5)
    assert metrics["tail_region"]["length_s"] == pytest.approx(1.5)
    assert metrics["tail_region"]["source"] == \
        "fixture_meta:render.duration_s-render.tail_s"


def test_fixture_meta_missing_declared_fields_refuses(tmp_path):
    """A fixture sidecar without render.duration_s/render.tail_s must be
    REFUSED (exit 2), never silently guessed at (e.g. via silence
    detection)."""
    ref = _synth_fixture()
    ref_p = str(tmp_path / "ref-wet.f32.wav")
    mod_p = str(tmp_path / "model-wet.f32.wav")
    _write_wav_stereo_f32(ref_p, ref)
    _write_wav_stereo_f32(mod_p, ref.copy())
    meta_p = tmp_path / "bad-fixture.json"
    meta_p.write_text(json.dumps({"render": {}}))

    class Args:
        pass
    a = Args()
    a.ref, a.model, a.json, a.fixture_meta = ref_p, mod_p, None, str(meta_p)
    rc = car.main_wet(a)
    assert rc == 2


def test_dry_path_has_no_tail_gate_and_no_tail_fields(tmp_path):
    """Acceptance #1: dry comparisons (no --fixture-meta) are unaffected --
    no tail_check field, no tail gate, budgets/verdict computed exactly as
    before #93."""
    rs = np.random.RandomState(3)
    n = SR  # 1.0 s
    ref = (rs.standard_normal(n) * 3000).astype(np.int16)
    mod = ref.copy()
    ref_p = str(tmp_path / "ref.wav")
    mod_p = str(tmp_path / "model.wav")
    _write_wav_mono16(ref_p, ref)
    _write_wav_mono16(mod_p, mod)
    out_json = str(tmp_path / "out.json")

    class Args:
        pass
    a = Args()
    a.ref, a.model, a.json = ref_p, mod_p, out_json
    rc = car.main_dry(a)
    assert rc == 0
    with open(out_json) as f:
        metrics = json.load(f)
    assert "tail_check" not in metrics
    assert "tail_region" not in metrics
    assert metrics["verdict"].startswith("PASS")
