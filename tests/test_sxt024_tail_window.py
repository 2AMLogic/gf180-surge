#!/usr/bin/env python3
"""SXT-024 comparator tail-window refusal path + transparency legs (issue #108).

Covers `tools/compare_reverb_model.py`'s BESPOKE, sequence-derived tail
window -- the window `tail_rms_rel` / `decay_curve` / `band_energy` /
`stereo_corr` are graded over -- as distinct from the shared declared-region
`tail_gate` that issue #100 added alongside it (covered by
tests/test_stereo_tail_gate.py):

  * `sequence_tail_start()` derives the window from DECLARED data only and
    REFUSES (car.TailRegionError -> NO_VERDICT, exit 2) when it cannot: a
    missing sequence fixture, an events list with no note_on/note_off, a
    non-integral event index, and a start at/after the end of the loaded
    render (a STALE sequence). Before #108 the no-note-event case raised an
    unhandled ValueError from max() on an empty generator.
  * the refusal is end-to-end: `cmd_case` returns 2 and writes no comparison
    record when the sequence cannot define the window.
  * the committed fixture still defines the window for every committed
    sxt-024 wet trace (live negative control for the refusal: it must not
    fire on good data).
  * the transparency legs `tail_window.tail_present` /
    `tail_window.model_tail_present` are emitted with shape parity to
    `compare_audio_reference.tail_check`, and are NOT entries in `checks` --
    a dropped tail is caught by the graded `tail_rms_rel` residual, and
    presence alone is demonstrably the weaker leg.

Claim scope: comparator behaviour only. Nothing here is a model-vs-reference,
RTL-exactness, preset-support, or sound claim.
"""

import argparse
import json
import os
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "model", "effects", "reverb1"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402
import compare_reverb_model as crm  # noqa: E402

TRACES = crm.TRACES
WET_CASES = ("click-wet", "preset-notes-coverage-wet", "hardreset-midpatch-wet",
             "reset-midpatch-wet")


def write_seq(tmp_path, events, name="seq.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"id": "synthetic", "sample_rate": 48000,
                             "events": events}))
    return str(p)


# --------------------------------------------------------------------------
# sequence_tail_start: declared data only, refuse otherwise
# --------------------------------------------------------------------------

def test_committed_sequence_defines_the_window():
    """Live negative control for the refusal: good data must NOT refuse."""
    t0, win = crm.sequence_tail_start(crm.SEQ_COV, 729600)
    assert t0 == 153600 + crm.TAIL_GUARD_SAMPLES == 158400
    assert win["tail_offset"] == 158400
    assert win["tail_frames"] == 729600 - 158400
    assert win["last_event_sample"] == 153600
    assert win["guard_samples"] == crm.TAIL_GUARD_SAMPLES
    assert win["tail_region_sequence"] == \
        "fixtures/sequences/seq-notes-coverage-v1.json"
    # declared provenance, never silence-inferred
    assert "last note_on/note_off" in win["tail_region_source"]


@pytest.mark.parametrize("case", WET_CASES)
def test_committed_traces_all_admit_the_window(case):
    frames = np.load(os.path.join(TRACES, case + ".npy")).shape[1]
    if case.startswith("click"):
        win = crm.tail_window(crm.CLICK_TAIL_START, frames, "test")
        assert win["tail_offset"] == crm.CLICK_TAIL_START
    else:
        t0, win = crm.sequence_tail_start(crm.SEQ_COV, frames)
        assert 0 < t0 < frames
    assert win["tail_frames"] > 0


def test_missing_sequence_fixture_refuses(tmp_path):
    with pytest.raises(car.TailRegionError) as e:
        crm.sequence_tail_start(str(tmp_path / "absent.json"), 729600)
    assert "missing" in str(e.value)


def test_no_note_event_refuses_instead_of_valueerror(tmp_path):
    """The exact pre-#108 crash: max() over an empty generator."""
    seq = write_seq(tmp_path, [{"type": "tempo", "t": 0}])
    with pytest.raises(car.TailRegionError) as e:
        crm.sequence_tail_start(seq, 729600)
    assert "no note_on/note_off event" in str(e.value)


def test_empty_events_list_refuses(tmp_path):
    with pytest.raises(car.TailRegionError):
        crm.sequence_tail_start(write_seq(tmp_path, []), 729600)


def test_no_events_key_refuses(tmp_path):
    p = tmp_path / "noevents.json"
    p.write_text(json.dumps({"id": "synthetic"}))
    with pytest.raises(car.TailRegionError) as e:
        crm.sequence_tail_start(str(p), 729600)
    assert "'events' list" in str(e.value)


def test_non_integral_event_index_refuses(tmp_path):
    seq = write_seq(tmp_path, [{"type": "note_on", "t": 0},
                               {"type": "note_off", "t": 12.5}])
    with pytest.raises(car.TailRegionError) as e:
        crm.sequence_tail_start(seq, 729600)
    assert "non-integral" in str(e.value)


def test_stale_sequence_past_the_render_end_refuses(tmp_path):
    """A last note event at/after the render end leaves no tail to grade."""
    seq = write_seq(tmp_path, [{"type": "note_off", "t": 729600}])
    with pytest.raises(car.TailRegionError) as e:
        crm.sequence_tail_start(seq, 729600)
    assert "at or past the end" in str(e.value)
    # boundary: exactly one frame of tail is still gradeable
    seq_ok = write_seq(tmp_path, [{"type": "note_off",
                                   "t": 729600 - crm.TAIL_GUARD_SAMPLES - 1}],
                       name="ok.json")
    t0, win = crm.sequence_tail_start(seq_ok, 729600)
    assert win["tail_frames"] == 1


def test_tail_window_rejects_a_negative_start():
    with pytest.raises(car.TailRegionError) as e:
        crm.tail_window(-1, 100, "synthetic")
    assert "negative" in str(e.value)


# --------------------------------------------------------------------------
# end-to-end refusal (NO_VERDICT, exit 2) and no record written
# --------------------------------------------------------------------------

def test_cmd_case_refuses_end_to_end_on_a_sequence_with_no_note_event(
        tmp_path, monkeypatch, capsys):
    out_dir = tmp_path / "out"
    monkeypatch.setattr(crm, "SEQ_COV",
                        write_seq(tmp_path, [{"type": "tempo", "t": 0}]))
    rc = crm.cmd_case(argparse.Namespace(case="preset-notes-coverage-wet",
                                         out_dir=str(out_dir)))
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "NO_VERDICT (refused)"
    assert "no note_on/note_off event" in payload["reason"]
    # a refusal must not overwrite or invent a comparison record
    assert not out_dir.exists() or not list(out_dir.iterdir())


def test_cmd_case_refuses_end_to_end_on_a_stale_sequence(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(crm, "SEQ_COV",
                        write_seq(tmp_path, [{"type": "note_off", "t": 10 ** 9}]))
    rc = crm.cmd_case(argparse.Namespace(case="preset-notes-coverage-wet",
                                         out_dir=str(tmp_path / "out")))
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "NO_VERDICT (refused)"
    assert "at or past the end" in payload["reason"]


# --------------------------------------------------------------------------
# transparency legs: shape parity, and NOT a new verdict
# --------------------------------------------------------------------------

def _synthetic(n=48000 * 3, t0=48000):
    rng = np.random.default_rng(1024)
    env = np.exp(-np.arange(n) / 24000.0)
    wl = rng.standard_normal(n) * env * 0.1
    wr = rng.standard_normal(n) * env * 0.1
    return (wl, wr), t0


def test_transparency_legs_present_and_shape_matches_shared_tail_check():
    (wl, wr), t0 = _synthetic()
    res = crm.check_wet("synthetic", (wl, wr), (wl.copy(), wr.copy()), t0)
    tw = res["tail_window"]
    # the two legs the shared comparator's tail_check reports
    assert set(("tail_present", "model_tail_present", "tail_offset",
                "tail_frames", "tail_region_source")) <= set(tw)
    assert tw["tail_present"] is True and tw["model_tail_present"] is True
    assert tw["tail_offset"] == t0 and tw["tail_frames"] == len(wl) - t0
    # transparency only: no new graded check, and the identical prediction
    # still passes every existing one
    assert "tail_window" not in res["checks"]
    assert not set(res["checks"]) & set(tw)
    assert all(res["checks"].values()), res["checks"]


def test_window_provenance_is_merged_without_shadowing_the_measured_bounds():
    (wl, wr), t0 = _synthetic()
    win = crm.tail_window(t0, len(wl), "declared synthetic window", extra_key=7)
    res = crm.check_wet("synthetic", (wl, wr), (wl.copy(), wr.copy()), t0,
                        window=win)
    assert res["tail_window"]["tail_region_source"] == "declared synthetic window"
    assert res["tail_window"]["extra_key"] == 7
    assert res["tail_window"]["tail_offset"] == t0


def test_silent_model_tail_is_flagged_AND_fails_the_graded_residual():
    """The failure control the transparency leg does not replace."""
    (wl, wr), t0 = _synthetic()
    pl, pr = wl.copy(), wr.copy()
    pl[t0:] = 0.0
    pr[t0:] = 0.0
    with np.errstate(invalid="ignore"):
        # a fully silent tail has no stereo correlation to compute
        res = crm.check_wet("synthetic-dropped-tail", (wl, wr), (pl, pr), t0)
    assert res["tail_window"]["tail_present"] is True
    assert res["tail_window"]["model_tail_present"] is False
    # the graded residual is what produces the FAIL, not the presence leg
    assert res["checks"]["tail_rms_rel"] is False
    assert res["tail_rms_rel_db"] == pytest.approx(0.0, abs=1e-6)


def test_partially_truncated_tail_keeps_presence_true_but_still_fails():
    """Why presence is NOT promoted to a check: it is the weaker leg.

    Mirrors the committed nc-b-tail-truncation control (model_tail_present
    true, tail_rms_rel -7.32 dB -> FAIL).
    """
    (wl, wr), t0 = _synthetic()
    pl, pr = wl.copy(), wr.copy()
    pl[t0 + 24000:] = 0.0
    pr[t0 + 24000:] = 0.0
    res = crm.check_wet("synthetic-late-truncation", (wl, wr), (pl, pr), t0)
    assert res["tail_window"]["model_tail_present"] is True
    assert res["checks"]["tail_rms_rel"] is False
