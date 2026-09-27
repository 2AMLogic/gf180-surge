"""SXT-015 FX class accounting table tests (pytest).

Failure controls for two places where the shared class table must track an
SXT-028 leaf's measurement rather than a hand-written figure:

  * the Conditioner **state** promotion out of the shared `no_long_buffer`
    byte placeholder (issue #117, measurement from SXT-028b / issue #54), and
  * the Reverb 2 per-sample external **traffic** row, which SXT-028f
    (issue #58) measured as 29 reads / 17 writes against the table's 40 / 18
    (finding F-028f-2, issue #127). That row is deliberately HELD at the
    conservative over-estimate pending #12; the tests below require the hold
    to be declared, conservative, and tied to the leaf's artifact, and
    separately prove the row is actually consumed by the accounting output.

Two claims are kept apart here and neither is advanced by this file:

  * the SXT-015 accounting table reports what the leaf's frozen model
    actually measured, or an explicitly-recorded conservative hold over it
    (what these tests check), and
  * those models reproduce the pinned Surge engine (a separate, still-unproved
    claim -- see each leaf's own EVIDENCE.md).

Nothing here is an RTL, synthesis, fidelity, preset-support or
preset-quality claim. Python 3 standard library only (pytest as runner).
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "model", "effects", "type-reverb 2"))

from model.resources import fx_classes  # noqa: E402
from model.resources.accounting import account_graph  # noqa: E402
from model.resources.fx_classes import (  # noqa: E402
    _NO_LONG_BUFFER, _NO_LONG_BUFFER_MEASURED,
    _NO_LONG_BUFFER_PLACEHOLDER_BYTES, _PINNED_TX, _RETAINED_OVER_ESTIMATE_TX,
    fx_class_spec, retained_over_estimate,
)
from model.resources.params import REG  # noqa: E402
from reverb2_model import per_sample_transactions  # noqa: E402

SXT028B_BUFFER_REQUIREMENT = os.path.join(
    REPO, "reports", "SXT-028b", "artifacts", "buffer-requirement.json")
SXT028F_BUFFER_REQUIREMENT = os.path.join(
    REPO, "reports", "SXT-028f", "artifacts", "buffer-requirement.json")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
# fixed local profile: this file must not depend on the fixture library, whose
# growth is a separate (recorded) accounting delta.
EVENT_PROFILE = {"max_coincident_events": 8, "peak_events_per_second": 1.0,
                 "source": "test-local fixed profile (not an evidence input)"}

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


# ==========================================================================
# Reverb 2 per-sample external traffic (issue #127, finding F-028f-2)
# ==========================================================================
def _sxt028f():
    with open(SXT028F_BUFFER_REQUIREMENT) as f:
        return json.load(f)


def test_reverb2_measured_traffic_is_the_sxt028f_structural_count():
    """The *measured* leg of the row is the leaf's number, not a copy.

    `per_sample_transactions()` is derived from the pinned structure and is
    cross-checked against the frozen model's own live ext_read/ext_write
    counters by `tests/test_sxt028f.py`. Both the table's retention record
    and the committed artifact must agree with it, so no side can move alone.
    """
    declared = per_sample_transactions()
    assert declared == {"reads": 29, "writes": 17}
    doc = _sxt028f()
    tr = doc["external_traffic"]
    assert tr["measured_matches_structure"] is True, (
        "the SXT-028f artifact does not reconcile with its own model; "
        "regenerate it with tools/reverb2_buffer_report.py")
    assert (tr["reads_per_sample"], tr["writes_per_sample"]) == (29.0, 17.0)
    held = retained_over_estimate("reverb2")
    assert held is not None and held["measured"] == {
        "ext_reads": declared["reads"], "ext_writes": declared["writes"]}, (
        "the retention record's `measured` leg must BE the leaf measurement")
    assert held["field"] == "external_traffic.declared_from_structure"
    assert (tr["declared_from_structure"]["reads"],
            tr["declared_from_structure"]["writes"]) == (29, 17)


def test_reverb2_traffic_row_is_a_declared_conservative_hold():
    """The row may disagree with the measurement only as a RECORDED hold.

    Acceptance option (b) of issue #127: the 40/18 figure may be retained
    only with an explicit reason a reader of the table will see. This pins
    every property that makes it a hold rather than a stale row -- declared,
    conservative, reason stated in numbers, and with an unblocking condition
    -- and it goes green on option (a) too (row corrected, record retired).
    """
    spec = fx_class_spec("Reverb 2")
    row = (spec["ext_reads"], spec["ext_writes"])
    measured = per_sample_transactions()
    held = retained_over_estimate("reverb2")

    if row == (measured["reads"], measured["writes"]):
        # option (a) landed: the hold must be retired with the row
        assert held is None, (
            "the row now equals the measurement; retire "
            "_RETAINED_OVER_ESTIMATE_TX['reverb2'] with it")
        return

    assert held is not None, (
        "the SXT-015 Reverb 2 traffic row (%d reads / %d writes) disagrees "
        "with the SXT-028f measurement (%d / %d) and declares no reason. "
        "Either re-derive it from the leaf or record the retention in "
        "_RETAINED_OVER_ESTIMATE_TX." % (row + (measured["reads"],
                                                measured["writes"])))
    assert held["retained"] == {"ext_reads": row[0], "ext_writes": row[1]}, (
        "the retention record does not describe the row the table carries")
    # CONSERVATIVE, componentwise: a retained UNDER-estimate would make every
    # downstream bandwidth number optimistic and is never an acceptable hold.
    assert held["retained"]["ext_reads"] >= held["measured"]["ext_reads"]
    assert held["retained"]["ext_writes"] >= held["measured"]["ext_writes"]
    assert (held["retained"], held["measured"]) != (held["measured"],
                                                    held["retained"])
    assert held["leaf"] == "SXT-028f"
    assert held["artifact"] == os.path.relpath(SXT028F_BUFFER_REQUIREMENT, REPO)
    assert held["finding"] == "F-028f-2 (issue #127)"
    assert "#12" in held["unblocks_on"], "a hold must name what retires it"
    assert held["record"].startswith("reports/sxt-017/EVIDENCE.md")
    # the reason must state the cost being held back, in numbers, not vibes
    for token in ("ext_bandwidth_fit", "EXCEEDS", "within", "delay::process"):
        assert token in held["reason"], token


def test_reverb2_retention_is_visible_in_the_sxt028f_artifact():
    """A hold recorded only in a Python comment is not visible enough."""
    rec = _sxt028f()["sxt015_reconciliation"]
    held = retained_over_estimate("reverb2")
    if held is None:
        assert rec["traffic_agreement"] is True
        assert rec["traffic_direction"] == "agrees"
        assert rec["traffic_over_estimate_is_deliberate"] is False
        return
    assert rec["traffic_agreement"] is False
    assert rec["traffic_direction"] == "sxt015_over_estimates"
    assert rec["traffic_over_estimate_is_deliberate"] is True
    assert rec["sxt015_reads_per_sample"] == held["retained"]["ext_reads"]
    assert rec["sxt015_writes_per_sample"] == held["retained"]["ext_writes"]
    assert rec["traffic_retention_record"]["unblocks_on"] == held["unblocks_on"]


def test_retained_over_estimate_set_is_exactly_reverb2():
    """Live negative control: the hold is one row, not a tier-wide excuse."""
    assert set(_RETAINED_OVER_ESTIMATE_TX) == {"reverb2"}
    for key, tx in sorted(_PINNED_TX.items()):
        if key in _RETAINED_OVER_ESTIMATE_TX:
            continue
        assert retained_over_estimate(key) is None, key


def test_output_taps_are_not_counted_as_interpolated_reads():
    """The arithmetic error the retired 40/18 row encoded.

    In the pinned `delay::process` only the recirculation read is 2-point
    sub-sample interpolated; the two output taps t1/t2 are plain single
    reads. Interpolating the taps as well would cost 2 extra reads per delay
    line and give 37 reads per sample -- still not 40. The retired 40 is not
    derivable from the structure under EITHER reading, since
    (40 - 1 predelay - 12 allpass) = 27 is not a whole number of reads per
    delay line, which is why it had to be re-derived rather than patched.
    """
    n_allpass, n_delays = 12, 4
    fixed = 1 + n_allpass
    assert per_sample_transactions()["reads"] == fixed + n_delays * 4 == 29
    assert fixed + n_delays * (2 * 2 + 2) == 37      # both taps interpolated
    assert (40 - fixed) % n_delays != 0, (
        "if the retired 40-read row were structurally derivable, it would be "
        "a margin choice rather than a miscount; it is not derivable")


def _reverb2_graph():
    """A real corpus graph carrying at least one processing Reverb 2."""
    with open(GRAPHS) as f:
        for raw in f:
            d = json.loads(raw)
            if d.get("st") != "normalized":
                continue
            if not any(s.get("on") and s.get("tn") == "Reverb 2"
                       for s in d["g"]["fx"]):
                continue
            r = account_graph(d, fx_instance_limit=None,
                              event_profile=EVENT_PROFILE)
            n = sum(1 for i in r["fx_instances"]
                    if i["class"] == "Reverb 2" and i["processes_this_frame"])
            if n:
                return d, n
    raise AssertionError("no corpus graph carries a processing Reverb 2 slot")


def _ext_traffic(graph):
    return account_graph(graph, fx_instance_limit=None,
                         event_profile=EVENT_PROFILE
                         )["memory"]["ext_traffic_bytes_per_frame"]


@pytest.mark.parametrize("d_reads,d_writes", [(-11, -1), (+7, 0), (0, +3),
                                              (+13, +5)])
def test_traffic_row_is_consumed_by_the_accounting_output(d_reads, d_writes):
    """FAILURE CONTROL (issue #127): flip the row by a known delta and the
    accounting output must move by exactly the predicted amount.

    If it does not move, the row is not consumed, the table is decorative,
    and every SXT-016/017 bandwidth column derived from it is unbacked --
    which would also void the whole reason to hold this row conservatively.
    Predicted delta = (dreads + dwrites) words x mem_word_bytes x processing
    Reverb 2 instances.
    """
    graph, n_instances = _reverb2_graph()
    before = _ext_traffic(graph)

    saved = dict(_PINNED_TX["reverb2"])
    try:
        _PINNED_TX["reverb2"] = {
            "ext_reads": saved["ext_reads"] + d_reads,
            "ext_writes": saved["ext_writes"] + d_writes}
        fx_classes._SPEC_CACHE.clear()
        after = _ext_traffic(graph)
    finally:
        _PINNED_TX["reverb2"] = saved
        fx_classes._SPEC_CACHE.clear()

    predicted = (d_reads + d_writes) * REG.mem_word_bytes * n_instances
    assert after - before == predicted, (
        "flipping the reverb2 row by (%+d reads, %+d writes) moved the "
        "accounting output by %d B/frame, not the predicted %d B/frame over "
        "%d processing instance(s): the row is not consumed as claimed"
        % (d_reads, d_writes, after - before, predicted, n_instances))
    if d_reads + d_writes:
        assert after != before, "a non-zero row delta produced no movement"
    assert _ext_traffic(graph) == before, "the restore did not restore"


def test_holding_the_row_keeps_the_committed_traffic_figure_conservative():
    """The hold's whole justification: it cannot make anything read better.

    Correcting the row to the measured 29/17 lowers the per-frame traffic of
    every Reverb 2 instance by exactly 12 words. The retained row must
    therefore be >= the corrected one on the same graph -- never below it.
    """
    graph, n_instances = _reverb2_graph()
    retained = _ext_traffic(graph)
    measured = per_sample_transactions()
    saved = dict(_PINNED_TX["reverb2"])
    try:
        _PINNED_TX["reverb2"] = {"ext_reads": measured["reads"],
                                 "ext_writes": measured["writes"]}
        fx_classes._SPEC_CACHE.clear()
        corrected = _ext_traffic(graph)
    finally:
        _PINNED_TX["reverb2"] = saved
        fx_classes._SPEC_CACHE.clear()
    assert retained >= corrected
    held = retained_over_estimate("reverb2")
    if held is not None:
        over = ((held["retained"]["ext_reads"] - measured["reads"])
                + (held["retained"]["ext_writes"] - measured["writes"]))
        assert retained - corrected == over * REG.mem_word_bytes * n_instances
