"""SXT-015 FX class accounting table tests (pytest).

Failure control for the Conditioner promotion out of the shared
`no_long_buffer` byte placeholder (issue #117, measurement from SXT-028b /
issue #54).

Two claims are kept apart here and neither is advanced by this file:

  * the SXT-015 accounting table reports the byte count that SXT-028b's
    frozen model actually measured (what these tests check), and
  * the Conditioner model reproduces the pinned Surge engine (a separate,
    still-unproved claim -- see `reports/SXT-028b/EVIDENCE.md`).

Nothing here is an RTL, synthesis, fidelity, preset-support or
preset-quality claim. Python 3 standard library only (pytest as runner).
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from model.resources.fx_classes import (  # noqa: E402
    _NO_LONG_BUFFER, _NO_LONG_BUFFER_MEASURED,
    _NO_LONG_BUFFER_PLACEHOLDER_BYTES, fx_class_spec,
)

SXT028B_BUFFER_REQUIREMENT = os.path.join(
    REPO, "reports", "SXT-028b", "artifacts", "buffer-requirement.json")

# Every `no_long_buffer` class that has NOT had an SXT-028 leaf land yet.
# This list is the live negative control for "only Conditioner moved": if a
# future change sweeps the whole tier instead of one class, these fail.
UNMEASURED_NO_LONG_BUFFER = [
    "EQ", "Graphic EQ", "Ring Mod", "Mid-Side Tool", "Waveshaper",
    "Distortion", "Freq Shift", "Phaser", "Resonator", "Combulator",
    "Audio In", "Ensemble",
]


def _buffer_requirement():
    with open(SXT028B_BUFFER_REQUIREMENT) as f:
        return json.load(f)


def assert_no_drift(table_bytes, artifact):
    """The one comparison this file exists to make (reused by the control)."""
    measured = artifact["on_chip_state"]["bytes"]
    assert table_bytes == measured, (
        "SXT-015 Conditioner state_bytes (%r) has drifted from SXT-028b's "
        "measured on_chip_state.bytes (%r) in %s; re-derive the table entry "
        "from the artifact rather than editing either side by hand"
        % (table_bytes, measured, SXT028B_BUFFER_REQUIREMENT))


def test_conditioner_state_bytes_match_sxt028b_measurement():
    """The accounting number IS the SXT-028b measurement, not a copy of it.

    If either side moves independently -- the table is hand-edited, or
    `tools/conditioner_buffer_report.py` re-measures a different figure --
    this fails instead of letting SXT-017 budgets quietly use a stale byte
    count.
    """
    artifact = _buffer_requirement()
    assert_no_drift(fx_class_spec("Conditioner")["state_bytes"], artifact)
    # Guard the guard: a placeholder equal to the measurement would make the
    # assertion above vacuous.
    assert (artifact["on_chip_state"]["bytes"]
            != _NO_LONG_BUFFER_PLACEHOLDER_BYTES)


def test_conditioner_carries_the_pinned_sxt028b_model_revision():
    doc = _buffer_requirement()
    ref = fx_class_spec("Conditioner")["pinned_reference"]
    assert ref is not None, "measured entry must name its provenance"
    assert ref["leaf"] == doc["leaf"] == "SXT-028b"
    assert ref["model_revision"] == doc["model_revision"], (
        "pinned SXT-028b model revision in the SXT-015 table does not match "
        "the revision recorded in the artifact the bytes were read from")
    assert ref["artifact"] == os.path.relpath(SXT028B_BUFFER_REQUIREMENT, REPO)
    assert ref["field"] == "on_chip_state.bytes"
    # The measured figure is not a placeholder any more, so the class must no
    # longer be flagged unverified -- but it stays on-chip, no ext traffic.
    assert fx_class_spec("Conditioner")["flags"] == []
    assert fx_class_spec("Conditioner")["tier"] == "no_long_buffer"
    assert fx_class_spec("Conditioner")["external"] is False
    assert fx_class_spec("Conditioner")["ext_reads"] == 0
    assert fx_class_spec("Conditioner")["ext_writes"] == 0


def test_conditioner_justification_names_the_look_ahead_line():
    """The old text claimed 'no delay line'; the pinned effect has one."""
    just = _NO_LONG_BUFFER["Conditioner"]
    assert "no delay line" not in just, (
        "the pinned ConditionerEffect has a 128-sample stereo look-ahead "
        "line; 'no delay line' is the wrong headline fact")
    assert "look-ahead" in just and "128" in just
    assert "2,048 B" in just, "name the writable line size the leaf measured"
    assert (_buffer_requirement()["on_chip_state"]["writable_line_bytes"]
            == 2048)


@pytest.mark.parametrize("tn", UNMEASURED_NO_LONG_BUFFER)
def test_other_no_long_buffer_classes_keep_the_placeholder(tn):
    """Live negative control: only Conditioner's number changed."""
    spec = fx_class_spec(tn)
    assert spec["tier"] == "no_long_buffer"
    assert spec["state_bytes"] == _NO_LONG_BUFFER_PLACEHOLDER_BYTES == 8192
    assert spec["flags"] == ["class_state_unverified"]
    assert spec["pinned_reference"] is None
    assert spec["external"] is False
    assert spec["ext_reads"] == 0 and spec["ext_writes"] == 0
    assert "deferred to SXT-028" in spec["ref"]


def test_measured_promotion_set_is_exactly_conditioner():
    """A second class may only be promoted with its own leaf + test update."""
    assert set(_NO_LONG_BUFFER_MEASURED) == {"Conditioner"}
    assert (set(_NO_LONG_BUFFER)
            == set(UNMEASURED_NO_LONG_BUFFER) | {"Conditioner"})


def test_drift_between_table_and_artifact_is_detected():
    """Live negative control: the drift check must demonstrably FAIL.

    Runs the very same comparison the test above runs, against three
    deliberately broken inputs. A silently-passing drift check would be
    worse than no check at all.
    """
    artifact = _buffer_requirement()
    table_bytes = fx_class_spec("Conditioner")["state_bytes"]

    # (a) the artifact drifts: a re-measurement moves the byte count.
    drifted = json.loads(json.dumps(artifact))
    drifted["on_chip_state"]["bytes"] = artifact["on_chip_state"]["bytes"] + 1
    with pytest.raises(AssertionError):
        assert_no_drift(table_bytes, drifted)

    # (b) the table drifts: someone hand-edits the accounting entry.
    with pytest.raises(AssertionError):
        assert_no_drift(table_bytes + 1, artifact)

    # (c) the table is reverted to the shared 8,192 B placeholder.
    with pytest.raises(AssertionError):
        assert_no_drift(_NO_LONG_BUFFER_PLACEHOLDER_BYTES, artifact)
