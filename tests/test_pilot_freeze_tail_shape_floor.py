#!/usr/bin/env python3
"""Pilot-freeze decision for the int16 tail-shape-leg floor (issue #160).

Issue #111 added the windowed decay-curve (tail-shape) leg to the wet-path
tail gate with a single declared floor `decay_curve_floor_dbfs = -100.0` dBFS.
On the mono int16 bus that floor sits BELOW one int16 LSB RMS (-90.3 dBFS), so
the lowest graded windows are quantization-dominated (finding F1: the #93
`full-tail-within-budget` control shows 0.79 dB of the 1.0 dB budget from
+-1 LSB dither alone).

Issue #160 recorded the decision: keep ONE declared floor, -100.0 dBFS, for
every bus, and document the int16 quantization-dominated regime instead of
raising the floor (decision-records/0016). These tests pin the decision to the
code, so the two cannot drift apart silently:

  * the shipped constants still equal the values the decision names;
  * the policy draft section 2.5 and decision record 0016 declare the same
    numbers, and section 2.5 cites the record;
  * the floor really is ONE declared full-scale constant applied identically
    to every bus (no per-bus branch);
  * the int16 quantization-band arithmetic the decision rests on recomputes
    from the shipped constants;
  * the live negative control for the rationale: raising the int16 floor out
    of the +-1 LSB band (-80.0 dBFS) DISABLES the landed #111 negative control
    `mono/koala2/zero-late-tail-from-44%`. If that ever stops being true, the
    recorded rationale must be re-argued rather than quietly relied on.

Claim scope: comparator behaviour and recorded-decision consistency only.
The control render is built from a committed reference render, so nothing here
is a model-vs-reference, RTL, preset-support, or sound claim, and no budget is
frozen: the values remain [PROPOSED-TO-BE-FROZEN-AT-PILOT].
"""

import json
import os
import re
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import compare_audio_reference as car  # noqa: E402

POLICY = os.path.join(REPO, "contracts", "fidelity-policy-DRAFT.md")
DR = os.path.join(REPO, "decision-records",
                  "0016-int16-tail-shape-leg-floor.md")
DR_INDEX = os.path.join(REPO, "decision-records", "README.md")
EVIDENCE = os.path.join(REPO, "reports", "pilot-freeze-tail-shape-floor",
                        "EVIDENCE.md")
PROBE_JSON = os.path.join(REPO, "reports", "pilot-freeze-tail-shape-floor",
                          "artifacts", "floor-probe.json")

DECIDED_FLOOR_DBFS = -100.0
DECIDED_MAX_DEV_DB = 1.0
KOALA_WET = os.path.join(REPO, "fixtures", "audio", "koala2",
                         "seq-notes-coverage-v1-wet.wav")
KOALA_SIDECAR = os.path.join(REPO, "fixtures", "audio", "koala2",
                             "seq-notes-coverage-v1.json")


def read(path):
    with open(path) as f:
        return f.read()


def normalize_minus(s):
    """The prose files use U+2212; the code uses ASCII '-'."""
    return s.replace("−", "-")


# ------------------------------------------------- the decision vs the code --

def test_shipped_constants_equal_the_decided_values():
    assert car.PROPOSED_TAIL["decay_curve_floor_dbfs"] == DECIDED_FLOOR_DBFS
    assert car.PROPOSED_TAIL["decay_curve_max_dev_db"] == DECIDED_MAX_DEV_DB


def test_policy_draft_declares_the_decided_floor_and_cites_the_record():
    body = normalize_minus(read(POLICY))
    assert "decay_curve_floor_dbfs" in body
    assert "-100.0" in body
    assert "decay_curve_max_dev_db" in body
    # The decision and its rationale live in section 2.5.
    sec = body.split("### 2.5")[1].split("### 2.6")[0]
    assert "issue #160" in sec
    assert "decision-records/0016" in sec
    # The traded-off failure mode is named, not implied.
    assert "quantization" in sec.lower()
    assert "-90.3" in sec


def test_decision_record_exists_and_is_indexed():
    body = normalize_minus(read(DR))
    for token in ("SXT-017", "#160", "#111", "-100.0", "-90.3",
                  "Decision", "Consequences"):
        assert token in body, token
    # The record must state which option was chosen and that no code constant
    # moved.
    assert "one declared floor" in body.lower()
    index = normalize_minus(read(DR_INDEX))
    assert "0016-int16-tail-shape-leg-floor.md" in index


def test_probe_record_is_committed_and_overall_pass():
    body = read(EVIDENCE)
    assert "0.79" in body
    assert normalize_minus(body).count("-100.0") >= 1
    probe = json.load(open(PROBE_JSON))
    assert probe["overall"] == "PASS"
    assert probe["shipped_proposed_tail"]["decay_curve_floor_dbfs"] == \
        DECIDED_FLOOR_DBFS
    declared = [r for r in probe["legs"]["3"]["rows"]
                if r["floor_dbfs"] == DECIDED_FLOOR_DBFS]
    assert declared, "the probe must grade the declared floor"
    assert all(r["as_required"] for r in declared), \
        "a landed control changed status at the declared floor"
    # The recorded conflict: at least one raised floor flips a landed control.
    assert probe["legs"]["3"]["raised_floors_that_flip_a_landed_control"]


# --------------------------------------- one declared floor, every bus, dBFS --

def test_floor_is_one_full_scale_constant_shared_by_every_bus():
    """Same dBFS-shaped tail on an int16 bus and on a Q10.21 bus grades the
    same. The floor is a declared FULL-SCALE constant; it is not a function of
    the bus LSB (that is exactly the per-bus option issue #160 rejected).
    """
    sr = 48000
    n = sr // 2
    t = np.arange(n) / float(sr)
    shape = 10.0 ** ((-20.0 - 200.0 * t) / 20.0)      # -20 dBFS decaying away
    noise = np.sin(2 * np.pi * 997.0 * t) * shape     # deterministic

    def graded(full_scale):
        x = noise * full_scale
        dc = car.tail_decay_curve(x, x, sr, full_scale)
        return dc["graded_windows"], dc["total_windows"], dc["floor_dbfs"]

    a = graded(car.INT16_FULL_SCALE)
    b = graded(1.0 / 2.0 ** -21)
    c = graded(1.0 / 2.0 ** -23)
    assert a == b == c
    assert a[2] == DECIDED_FLOOR_DBFS


def test_int16_quantization_band_arithmetic():
    """The band the decision documents recomputes from the shipped constants."""
    dev = car.PROPOSED_TAIL["decay_curve_max_dev_db"]
    one_lsb_dbfs = 20.0 * np.log10(1.0 / car.INT16_FULL_SCALE)
    assert one_lsb_dbfs == pytest.approx(-90.3, abs=0.05)
    # A +-1 LSB model difference alone exceeds the budget below these levels.
    incoherent = 1.0 / np.sqrt(10.0 ** (dev / 10.0) - 1.0)
    coherent = 1.0 / (10.0 ** (dev / 20.0) - 1.0)
    inc_dbfs = 20.0 * np.log10(incoherent / car.INT16_FULL_SCALE)
    coh_dbfs = 20.0 * np.log10(coherent / car.INT16_FULL_SCALE)
    assert inc_dbfs == pytest.approx(-84.4, abs=0.1)
    assert coh_dbfs == pytest.approx(-72.0, abs=0.1)
    # The declared floor is inside the band, which is the finding (F1/#160).
    assert car.PROPOSED_TAIL["decay_curve_floor_dbfs"] < one_lsb_dbfs < coh_dbfs
    # Both band edges appear in the recorded decision.
    dr = normalize_minus(read(DR))
    assert "-84.4" in dr and "-72.0" in dr


# ---------------------------------- live control for the recorded rationale --

@pytest.mark.skipif(not os.path.exists(KOALA_WET),
                    reason="committed Koala 2 wet fixture missing")
def test_raising_the_int16_floor_disables_a_landed_negative_control():
    """The reason the floor was NOT raised, exercised rather than asserted.

    `mono/koala2/zero-late-tail-from-44%` (#111) FAILs only on the tail-shape
    leg, through a single graded window at about -82 dBFS. Raise the floor to
    -80.0 dBFS to clear the +-1 LSB band and that window stops being graded:
    the landed FAIL becomes a PASS. A decision that flips a landed negative
    control is the issue's stop/escalate condition, so the floor stays put.
    """
    region = car.declared_tail_region(KOALA_SIDECAR, "wet")
    off, length = region["tail_offset"], region["tail_frames"]
    ref, sr = car.read_wav(KOALA_WET)
    assert sr == 48000
    mod = ref.astype(np.int64).copy()
    mod[off + int(length * 0.44):off + length] = 0

    def gate(floor):
        budget = dict(car.PROPOSED_TAIL)
        budget["decay_curve_floor_dbfs"] = floor
        return car.tail_check(ref, mod, region, budget=budget,
                              full_scale=car.INT16_FULL_SCALE)

    at_declared = gate(DECIDED_FLOOR_DBFS)
    assert at_declared["tail_rms_rel_ok"], \
        "the control must fail on the SHAPE leg, not the residual leg"
    assert not at_declared["tail_decay_curve_ok"]
    assert not at_declared["ok"]

    raised = gate(-80.0)
    assert raised["tail_decay_curve_ok"], \
        "expected the raised floor to stop grading the defect window"
    assert raised["ok"]
    assert (raised["tail_decay_curve"]["graded_windows"]
            < at_declared["tail_decay_curve"]["graded_windows"])


@pytest.mark.skipif(not os.path.exists(KOALA_WET),
                    reason="committed Koala 2 wet fixture missing")
def test_int16_dither_control_margin_is_quantization_not_tail_shape():
    """Finding F1 reproduces: +-1 LSB alone spends 0.79 dB of the 1.0 dB
    budget, in windows within about 11 dB of one int16 LSB RMS. The margin is
    therefore NOT evidence of tail-shape headroom on the int16 bus.
    """
    region = car.declared_tail_region(KOALA_SIDECAR, "wet")
    off, length = region["tail_offset"], region["tail_frames"]
    ref, sr = car.read_wav(KOALA_WET)
    i = np.arange(off, off + length // 2, dtype=np.int64)
    mod = ref.astype(np.int64).copy()
    mod[off:off + length // 2] += ((i * 2654435761) % 3).astype(np.int64) - 1
    tc = car.tail_check(ref, mod, region, full_scale=car.INT16_FULL_SCALE)
    dc = tc["tail_decay_curve"]
    assert tc["ok"], "the #93 within-budget control must still PASS"
    assert dc["max_dev_db"] == pytest.approx(0.79, abs=0.02)
    one_lsb_dbfs = 20.0 * np.log10(1.0 / car.INT16_FULL_SCALE)
    worst_ref = dc["worst_window"]["ref_dbfs"]
    assert worst_ref - one_lsb_dbfs < 11.0, \
        "the worst window should sit close to one int16 LSB RMS"


def test_policy_and_decision_still_declare_nothing_frozen():
    for path in (POLICY, DR):
        body = read(path)
        assert "PROPOSED-TO-BE-FROZEN-AT-PILOT" in body
    assert re.search(r"NOT\s+FROZEN", read(POLICY))
