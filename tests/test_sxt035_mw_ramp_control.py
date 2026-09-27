"""SXT-035 C2 control-plane discriminator tests (pytest, issue #163).

The `smoothing-bypass` negative control used to rest entirely on a 0.0026
margin of the whole-render `spectral_corr` leg (its rms leg never
discriminated at all, and the windowed-rms variant does not discriminate
either on this intentionally-clipped fixture). This module covers the
replacement: a control-plane check of the smoothed modwheel word's
blocks-to-converge after each CC dispatch, read from `model_trace.json`.

No oracle, no iverilog, and no model render required -- the traces are
synthesised here from the declared `voice_model.Modwheel` smoother itself.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm  # noqa: E402
from tools.mw_negative_controls import (  # noqa: E402
    DECLARED_RAMP_BLOCKS,
    MIN_RAMP_BLOCKS,
    mw_cc_dispatches,
    mw_ramp_profile,
    ramp_discriminator,
)

NC_JSON = os.path.join(REPO, "reports", "sxt-035", "artifacts",
                       "negative-controls.json")


def write_trace(tmp_path, smoothing, total_blocks=1400):
    """Synthesise a model_trace.json with the runner's mw record layout.

    `smoothing=True` steps the declared FAST_LINE smoother once per block
    (model/voice/run_mw_model.py: modsource step at the END of the control
    pass); `smoothing=False` is the `--no-smoothing` mutant (value jumps to
    target inside set_target, process_block is a no-op).
    """
    mw = vm.Modwheel()
    by_block = {b: (cc, t) for b, cc, t in mw_cc_dispatches()}
    blocks = []
    for b in range(total_blocks):
        if b in by_block:
            cc = by_block[b][0]
            if smoothing:
                mw.set_target(cc)
            else:
                mw.target = vm.qint(cc / 127.0)
                mw.value = mw.target
                mw.startingpoint = mw.value
        pre = mw.value
        if smoothing:
            mw.process_block()
        blocks.append({"b": b, "mw_pre": pre, "mw_value": mw.value})
    run_dir = tmp_path / ("smoothed" if smoothing else "bypassed")
    run_dir.mkdir()
    with open(run_dir / "model_trace.json", "w", encoding="utf-8") as f:
        json.dump({"format": "test-stub", "blocks": blocks}, f)
    return str(run_dir)


def test_fixture_declares_the_cc_dispatches_the_discriminator_reads():
    disp = mw_cc_dispatches()
    assert [cc for _, cc, _ in disp] == [32, 64, 96, 127, 0]
    # run_mw_model dispatches an event at block ceil(t / BLOCK_SIZE).
    assert [b for b, _, _ in disp] == [300, 450, 600, 750, 1050]
    assert [t for _, _, t in disp][-2] == vm.qint(1.0)


def test_declared_fast_line_ramp_matches_the_smoother_constant():
    # da = (target - startingpoint) * inv once per block, so any dispatch
    # needs 1/inv blocks regardless of step size.
    assert DECLARED_RAMP_BLOCKS == pytest.approx(54.42, abs=0.01)
    assert MIN_RAMP_BLOCKS == 27


def test_smoothed_trace_ramps_and_does_not_trip_the_discriminator(tmp_path):
    run_dir = write_trace(tmp_path, smoothing=True)
    per, mn = mw_ramp_profile(run_dir)
    assert [p["ramp_blocks"] for p in per] == [54, 54, 54, 54, 54]
    assert mn == 54
    trips, detail = ramp_discriminator(run_dir)
    assert trips is False
    assert detail["min_ramp_blocks"] == 54
    assert detail["threshold_blocks"] == MIN_RAMP_BLOCKS


def test_bypassed_trace_converges_instantly_and_trips_the_discriminator(
        tmp_path):
    run_dir = write_trace(tmp_path, smoothing=False)
    per, mn = mw_ramp_profile(run_dir)
    assert [p["ramp_blocks"] for p in per] == [0, 0, 0, 0, 0]
    assert mn == 0
    trips, detail = ramp_discriminator(run_dir)
    assert trips is True
    # The margin is 54 blocks of separation, not a 0.0026 metric margin.
    assert detail["margin_blocks"] == MIN_RAMP_BLOCKS
    assert detail["declared_ramp_blocks"] == pytest.approx(54.42, abs=0.01)


def test_discriminator_reads_no_audio_and_no_spectral_metric(tmp_path):
    """A trace alone is enough -- no wav, no reference, no spectral_corr."""
    run_dir = write_trace(tmp_path, smoothing=False)
    assert not [f for f in os.listdir(run_dir) if f.endswith(".wav")]
    trips, _ = ramp_discriminator(run_dir)
    assert trips is True


def test_missing_trace_is_reported_as_unavailable_not_as_a_trip(tmp_path):
    trips, detail = ramp_discriminator(str(tmp_path))
    assert trips is False
    assert detail is None


@pytest.mark.skipif(not os.path.exists(NC_JSON), reason="record not built")
def test_committed_record_carries_the_control_plane_leg_for_c2():
    with open(NC_JSON, encoding="utf-8") as f:
        rec = json.load(f)
    c2 = rec["smoothing-bypass"]
    assert c2["control_ok"] is True
    assert "mw-ramp" in c2["beyond_model_error_via"]
    ramp = c2["mw_ramp"]
    assert ramp["discriminator_trips"] is True
    assert ramp["min_ramp_blocks"] == 0
    assert ramp["margin_blocks"] == MIN_RAMP_BLOCKS
    # Failure control: the unmutated baseline must NOT trip the same leg.
    base = rec["baseline"]["mw_ramp"]
    assert base["discriminator_trips"] is False
    assert base["min_ramp_blocks"] >= MIN_RAMP_BLOCKS
    # C2 must not depend on the thin whole-render spectral margin any more.
    assert c2["control_ok_without_spectral_leg"] is True
