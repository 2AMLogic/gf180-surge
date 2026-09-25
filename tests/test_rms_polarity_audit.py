"""SXT-095 tests: the corrected rms_diff_dbfs budget predicate must never be
re-inverted, in either the shared comparator (tools/compare_audio_reference.py,
fixed in PR #92) or the audit tool that recomputes it from committed JSON
(tools/audit_rms_polarity.py, issue #95).

Synthetic-pair coverage (issue #95 acceptance):
  * "silent-diff" case: a nearly-silent MODEL against a loud reference (the
    exact scenario named in the issue background -- "a nearly-silent model
    (diff ~= the reference, loud) 'passed'" under the old, inverted
    predicate). The diff waveform is loud (~= the reference) and MUST FAIL
    the -46 dBFS budget.
  * "quiet-diff" case: model closely tracks the reference (small residual).
    The diff waveform is quiet and MUST PASS the -46 dBFS budget.
  * "loud-diff" case: model is dominated by noise unrelated to the
    reference. The diff waveform is loud and MUST FAIL the -46 dBFS budget.

Each case is checked two ways:
  1. directly against tools.audit_rms_polarity.rms_leg_passes (the audit's
     own recompute predicate), and
  2. end-to-end through the actual, shipped tools/compare_audio_reference.py
     on synthetic WAV pairs, so a future re-inversion of the *real* fixed
     file (not just a copy of its logic) is caught.

If the predicate is ever re-inverted (`<=` -> `>=`) in either file, every
assertion in this module flips and the suite fails.
"""

import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tools.audit_rms_polarity import (  # noqa: E402
    SHARED_COMPARATOR_KEYS,
    audit_row,
    find_rows,
    rms_leg_passes,
)

COMPARE_AUDIO = os.path.join(REPO, "tools", "compare_audio_reference.py")
BUDGET_DBFS = -46.0


def _write_wav(path, samples, sr=48000):
    clipped = [max(-32768, min(32767, int(round(s)))) for s in samples]
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(struct.pack("<%dh" % len(clipped), *clipped))


def _sine(n, amp, freq=440.0, sr=48000, phase=0.0):
    return [amp * math.sin(2 * math.pi * freq * i / sr + phase)
            for i in range(n)]


def _lcg_noise(n, amp, seed=12345):
    # Deterministic, dependency-free pseudo-noise (no numpy needed here).
    out = []
    x = seed
    for _ in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        out.append(amp * (2.0 * (x / 0x7FFFFFFF) - 1.0))
    return out


# ---------------------------------------------------------------------------
# 1. Direct predicate tests (audit tool's own recompute logic)
# ---------------------------------------------------------------------------

def test_predicate_silent_model_diff_fails():
    # Diff ~= the (loud) reference: rms_diff_dbfs close to 0 dBFS.
    assert rms_leg_passes(-3.0, BUDGET_DBFS) is False


def test_predicate_quiet_diff_passes():
    # Diff well below the -46 dBFS budget.
    assert rms_leg_passes(-61.66, BUDGET_DBFS) is True
    assert rms_leg_passes(-46.0, BUDGET_DBFS) is True  # boundary: <=, not <


def test_predicate_loud_diff_fails():
    assert rms_leg_passes(-5.0, BUDGET_DBFS) is False


def test_audit_row_recomputes_rms_leg_and_flags_flip():
    # A synthetic row shaped exactly like tools/compare_audio_reference.py's
    # output, carrying the OLD (inverted-predicate) flag baked in, as a
    # committed pre-fix JSON would.
    row = {
        "frames": 1000,
        "ref_peak_lsb": 3000.0,
        "model_peak_lsb": 3000.0,
        "max_abs_diff_lsb": 100.0,
        "rms_diff_lsb": 20.0,
        "rms_diff_dbfs": -33.3,  # louder than -46 -> should FAIL
        "rms_diff_at_shift0_lsb": 20.0,
        "best_shift": 0,
        "rms_diff_at_best_shift_lsb": 20.0,
        "spectral_corr": 0.999,
        "proposed_budgets": {
            "max_abs_diff_lsb": 3500,
            "rms_diff_dbfs": BUDGET_DBFS,
            "spectral_corr_min": 0.98,
        },
        # Old inverted predicate (`>=`) recorded this as True (a bug).
        "proposed_budget_results": {
            "max_abs_diff_lsb": True,
            "rms_diff_dbfs": True,
            "spectral_corr": True,
        },
        "verdict": "PASS (PENDING-FREEZE: budgets are proposals, not frozen policy)",
    }
    result = audit_row("synthetic.json", "$", row)
    assert result["old_rms_flag"] is True
    assert result["correct_rms_flag"] is False
    assert result["rms_flag_flipped"] is True
    # max-abs and spectral legs are untouched and both already True here, so
    # the overall verdict flips PASS -> FAIL once only the rms leg is fixed.
    assert result["old_verdict_pass"] is True
    assert result["recomputed_verdict_pass"] is False
    assert result["verdict_flipped"] is True


def test_audit_row_no_flip_when_other_leg_already_fails():
    row = {
        "frames": 1000,
        "ref_peak_lsb": 3000.0,
        "model_peak_lsb": 3000.0,
        "max_abs_diff_lsb": 100.0,
        "rms_diff_lsb": 20.0,
        "rms_diff_dbfs": -50.0,  # correctly passes -46 either way
        "rms_diff_at_shift0_lsb": 20.0,
        "best_shift": 0,
        "rms_diff_at_best_shift_lsb": 20.0,
        "spectral_corr": 0.90,  # already below the 0.98 min -> FAIL regardless
        "proposed_budgets": {
            "max_abs_diff_lsb": 3500,
            "rms_diff_dbfs": BUDGET_DBFS,
            "spectral_corr_min": 0.98,
        },
        "proposed_budget_results": {
            "max_abs_diff_lsb": True,
            "rms_diff_dbfs": True,
            "spectral_corr": False,
        },
        "verdict": "FAIL against proposed budgets",
    }
    result = audit_row("synthetic.json", "$", row)
    assert result["rms_flag_flipped"] is False
    assert result["old_verdict_pass"] is False
    assert result["recomputed_verdict_pass"] is False
    assert result["verdict_flipped"] is False


def test_find_rows_ignores_channels_wrapper():
    # compare_chorus_reference.py / compare_fx_reference.py wrap their own,
    # already-correct rms leg (own "proposed_budget_results"/"verdict") at
    # the TOP level, alongside a "channels" dict of PER-CHANNEL metrics that
    # carry no budget/verdict of their own (real schema, confirmed against
    # reports/SXT-028c/artifacts/*.json). find_rows must not mistake either
    # the wrapper or its per-channel metrics for a shared-comparator row.
    per_channel = {
        "frames": 0, "ref_peak_lsb": 0, "model_peak_lsb": 0,
        "max_abs_diff_lsb": 0, "rms_diff_lsb": 0, "rms_diff_dbfs": 0,
        "rms_diff_at_shift0_lsb": 0, "best_shift": 0,
        "rms_diff_at_best_shift_lsb": 0, "spectral_corr": 0,
    }
    wrapped = {
        "leaf": "SXT-028c",
        "channels": {"L": dict(per_channel), "R": dict(per_channel),
                     "mono": dict(per_channel)},
        "proposed_budgets": {"rms_diff_dbfs": -46.0},
        "proposed_budget_results": {"rms_diff_dbfs": True},
        "verdict": "PASS",
    }
    assert find_rows(wrapped) == []

    flat_row = {k: 0 for k in SHARED_COMPARATOR_KEYS}
    flat_row["proposed_budgets"] = {"rms_diff_dbfs": -46.0}
    flat_row["proposed_budget_results"] = {"rms_diff_dbfs": True}
    flat_row["verdict"] = "PASS"
    assert find_rows(flat_row) == [("$", flat_row)]


# ---------------------------------------------------------------------------
# 2. End-to-end: the actual, shipped tools/compare_audio_reference.py
# ---------------------------------------------------------------------------

def _run_compare(ref_wav, model_wav):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_json = tf.name
    try:
        r = subprocess.run(
            [sys.executable, COMPARE_AUDIO, "--ref", ref_wav,
             "--model", model_wav, "--json", out_json],
            capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, r.stderr
        with open(out_json) as f:
            return json.load(f)
    finally:
        os.unlink(out_json)


def test_shared_comparator_silent_model_fails_rms_budget(tmp_path):
    n = 48000
    ref = _sine(n, amp=8000.0)
    model = [0.0] * n  # nearly-silent model -> diff ~= the (loud) reference
    ref_wav = str(tmp_path / "ref.wav")
    model_wav = str(tmp_path / "model.wav")
    _write_wav(ref_wav, ref)
    _write_wav(model_wav, model)

    metrics = _run_compare(ref_wav, model_wav)
    assert metrics["rms_diff_dbfs"] > BUDGET_DBFS, metrics["rms_diff_dbfs"]
    assert metrics["proposed_budget_results"]["rms_diff_dbfs"] is False
    assert metrics["verdict"].startswith("FAIL")


def test_shared_comparator_quiet_diff_passes_rms_budget(tmp_path):
    n = 48000
    ref = _sine(n, amp=8000.0)
    # Tiny residual (a few LSB of noise) riding on the same signal.
    noise = _lcg_noise(n, amp=1.5)
    model = [r + e for r, e in zip(ref, noise)]
    ref_wav = str(tmp_path / "ref.wav")
    model_wav = str(tmp_path / "model.wav")
    _write_wav(ref_wav, ref)
    _write_wav(model_wav, model)

    metrics = _run_compare(ref_wav, model_wav)
    assert metrics["rms_diff_dbfs"] <= BUDGET_DBFS, metrics["rms_diff_dbfs"]
    assert metrics["proposed_budget_results"]["rms_diff_dbfs"] is True


def test_shared_comparator_loud_diff_fails_rms_budget(tmp_path):
    n = 48000
    ref = _sine(n, amp=500.0)
    # Model dominated by loud, reference-unrelated noise.
    model = _lcg_noise(n, amp=6000.0, seed=999)
    ref_wav = str(tmp_path / "ref.wav")
    model_wav = str(tmp_path / "model.wav")
    _write_wav(ref_wav, ref)
    _write_wav(model_wav, model)

    metrics = _run_compare(ref_wav, model_wav)
    assert metrics["rms_diff_dbfs"] > BUDGET_DBFS, metrics["rms_diff_dbfs"]
    assert metrics["proposed_budget_results"]["rms_diff_dbfs"] is False
    assert metrics["verdict"].startswith("FAIL")
