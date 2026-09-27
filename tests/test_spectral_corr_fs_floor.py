"""Issue #110: the shared full-scale log-floor `spectral_corr` definition.

These tests pin the definition, not any case's verdict:
  * one function, identical in every migrated comparator;
  * unit invariance: the same signal expressed on the int16 bus and on the
    float32 bus gives the same value (the pre-#110 native-unit log1p did not);
  * the declared constants (frame, floor) and the required full_scale;
  * edge semantics (exact agreement, silence, sub-frame renders);
  * failure controls: a silent model, a one-octave pitch error, and a wrong
    full-scale declaration all move the metric.
"""

import os
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402
import compare_chorus_reference as ccr  # noqa: E402
import compare_fx_reference as cfx  # noqa: E402

SR = 48000


def _signal(n=8 * 4096, seed=7):
    t = np.arange(n) / SR
    env = np.exp(-t * 3.0)
    x = 0.4 * env * np.sin(2 * np.pi * 220.0 * t)
    x += 0.1 * env * np.sin(2 * np.pi * 1760.0 * t)
    # a quiet tail region (-80 dBFS-ish) so the floor is exercised
    x[n // 2:] *= 1e-3
    return x


def _ternary(n, seed=0):
    x = (np.arange(n, dtype=np.uint64) + np.uint64(seed)) \
        * np.uint64(0x9E3779B97F4A7C15)
    x ^= x >> np.uint64(31)
    return (x % np.uint64(3)).astype(np.int64) - 1


def test_declared_constants():
    assert car.SPECTRAL_CORR_FRAME == 4096
    assert car.SPECTRAL_CORR_FLOOR_DB == -100.0
    assert car.FULL_SCALE_INT16 == 32767.0
    assert car.FULL_SCALE_F32 == 1.0
    assert "floor -100 dBFS/bin" in car.SPECTRAL_CORR_DEFINITION
    assert "no gating" in car.SPECTRAL_CORR_DEFINITION


def test_full_scale_is_required():
    x = _signal()
    with pytest.raises(TypeError):
        car.spectral_corr(x, x)          # no silent default unit
    with pytest.raises(ValueError):
        car.spectral_corr(x, x, full_scale=0.0)


def test_stereo_tools_use_the_shared_definition():
    x = _signal()
    y = x + 1e-4 * _ternary(len(x))
    shared = car.spectral_corr(x, y, full_scale=car.FULL_SCALE_F32)
    assert ccr.spectral_corr(x, y) == shared
    assert cfx.spectral_corr(x, y) == shared


def test_unit_invariance_int16_vs_float():
    """Same waveform and the same +-1 int16-LSB perturbation, expressed in
    int16 LSB and in float full-scale units: the adopted metric agrees; the
    retired native-unit log1p does not (the #110 finding)."""
    xf = np.round(_signal() * 32767.0) / 32767.0
    pert = _ternary(len(xf)).astype(np.float64)
    yf = xf + pert / 32767.0
    xi, yi = xf * 32767.0, yf * 32767.0
    new_i = car.spectral_corr(xi, yi, full_scale=car.FULL_SCALE_INT16)
    new_f = car.spectral_corr(xf, yf, full_scale=car.FULL_SCALE_F32)
    assert abs(new_i - new_f) < 1e-9
    old_i = car.spectral_corr_legacy_log1p(xi, yi)
    old_f = car.spectral_corr_legacy_log1p(xf, yf)
    assert abs(old_i - old_f) > 1e-3     # the retired definition is unit-bound


def test_exact_agreement_is_one():
    x = _signal()
    assert car.spectral_corr(x, x, full_scale=1.0) == pytest.approx(1.0)


def test_all_floor_spectra():
    z = np.zeros(4 * 4096)
    # both entirely below the floor and identical -> 1.0 (declared semantics)
    assert car.spectral_corr(z, z, full_scale=1.0) == 1.0
    # reference audible, model silent -> the spectral leg fails
    x = _signal(4 * 4096)
    assert car.spectral_corr(x, z, full_scale=1.0) == 0.0


def test_sub_frame_render():
    x = _signal(4096)[:3000]
    assert car.spectral_corr(x, x, full_scale=1.0) == 1.0
    assert car.spectral_corr(x, 0.5 * x, full_scale=1.0) == 0.0


def test_control_octave_error_fails_budget():
    """Failure control: a one-octave pitch error must fail the 0.98 leg."""
    n = 8 * 4096
    t = np.arange(n) / SR
    ref = 0.3 * np.sin(2 * np.pi * 330.0 * t)
    bad = 0.3 * np.sin(2 * np.pi * 660.0 * t)
    assert car.spectral_corr(ref, bad, full_scale=1.0) < \
        car.PROPOSED["spectral_corr_min"]


def test_control_wrong_full_scale_moves_metric():
    """Failure control: declaring the float full scale (1.0) for int16 data
    puts the floor ~90 dB lower and changes the value -- the unit declaration
    is load-bearing, not decorative."""
    xi = np.round(_signal() * 32767.0)
    yi = xi + _ternary(len(xi))
    right = car.spectral_corr(xi, yi, full_scale=car.FULL_SCALE_INT16)
    wrong = car.spectral_corr(xi, yi, full_scale=1.0)
    assert abs(right - wrong) > 1e-4


def test_floor_is_live():
    """Bins below the floor are clamped: perturbations far below -100 dBFS
    per bin in otherwise silent frames do not move the metric."""
    x = _signal()
    x[len(x) // 2:] = 0.0
    y = x.copy()
    y[len(y) // 2:] = 1e-9 * _ternary(len(y) - len(y) // 2)   # ~-180 dBFS
    assert car.spectral_corr(x, y, full_scale=1.0) == pytest.approx(1.0,
                                                                     abs=1e-12)
