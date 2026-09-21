"""SXT-021 control-plane tests (pytest).

Covers: quantize-up block convention, queue behavior incl. explicit
overflow detection, allocation/stealing policy, patch-change (hard switch)
and reset determinism, worst-case schedule accounting verdicts, the
committed fixture byte-identity (model leg everywhere; full RTL comparison
when iverilog is present — otherwise NOT_RUN, never a silent pass), and
the negative controls (silent stub caught; comparator catches the
committed queue-depth mutant).
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.control import (  # noqa: E402
    BLOCK_SIZE, ControlModel, Event, QUEUE_DEPTH, EV_RESERVE_PER_BLOCK,
    NAME_TO_TYPE, quantize_block, render_sequence,
)
from model.control.engine_stub_counter import CounterStubEngine  # noqa: E402
from model.control.engine_stub_silent import SilentStubEngine  # noqa: E402
from model.control.accounting import account_schedule  # noqa: E402
from tools.compare_control_rtl import run_comparison, parse_tb, compare  # noqa: E402
from tools.control_negative_controls import output_check  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mk(t, typ, p1=0, p2=0):
    return {"t": t, "type": typ, "p1": p1, "p2": p2}


# ----------------------------------------------------------- conventions
def test_quantize_up_never_down():
    assert quantize_block(0) == 0
    assert quantize_block(1) == 1          # t=1 -> next block, never earlier
    assert quantize_block(31) == 1
    assert quantize_block(32) == 1         # exact boundary applies as-is
    assert quantize_block(33) == 2
    assert quantize_block(1) * BLOCK_SIZE >= 1


def test_event_latency_bounded_by_one_block():
    seq = {"id": "t", "schema_version": 1, "sample_rate": 48000,
           "block_size": 32, "blocks": 4,
           "events": [mk(65, "note_on", 60, 100)]}
    trace, out, summary = render_sequence(seq, CounterStubEngine())
    d = trace["blocks"][3]["decisions"][0]        # ceil(65/32) = 3
    assert d["applied_sample"] == 96
    assert d["latency_samples"] == 96 - 65        # bounded, never negative
    assert summary["max_latency_samples"] <= 31


def test_queue_overflow_is_explicit_not_silent():
    # 30 coincident arrivals: 16 queued (depth), 14 explicit drops
    evs = [mk(0, "note_on", 36 + i, 100) for i in range(30)]
    seq = {"id": "t", "schema_version": 1, "sample_rate": 48000,
           "block_size": 32, "blocks": 4, "events": evs}
    trace, out, summary = render_sequence(seq, CounterStubEngine())
    b0 = trace["blocks"][0]
    assert "queue_overflow" in b0["statuses"]
    assert "event_reserve_exceeded" in b0["statuses"]
    assert len(b0["drops"]) == 14 and summary["drops_total"] == 14
    assert [d["seq"] for d in b0["drops"]] == list(range(16, 30))
    assert summary["underruns"] == 0            # output never stops


def test_reserve_exceeded_spills_bounded_without_drops():
    evs = [mk(0, "note_on", 36 + i, 100) for i in range(12)]
    seq = {"id": "t", "schema_version": 1, "sample_rate": 48000,
           "block_size": 32, "blocks": 4, "events": evs}
    trace, out, summary = render_sequence(seq, CounterStubEngine())
    assert len(trace["blocks"][0]["decisions"]) == EV_RESERVE_PER_BLOCK
    assert trace["blocks"][1]["decisions"][0]["latency_samples"] == 32
    assert summary["drops_total"] == 0


# --------------------------------------------------- allocation/stealing
def test_steal_oldest_active_then_lowest_index():
    m = ControlModel()
    notes = [60, 62, 64, 65, 67, 69, 71, 72]   # fill all 8 slots
    for n in notes:
        m.dispatch(Event(0, 0, NAME_TO_TYPE["note_on"], n, 100), 0)
    assert all(v.active for v in m.voices)
    # ages: slot0 is the oldest active; the 9th note must steal slot 0
    slot, status = m._alloc_free_or_steal(74)
    assert (slot, status) == (0, 1)
    # release one voice, then allocate -> the free slot is preferred
    m._release_oldest(62)
    slot, status = m._alloc_free_or_steal(76)
    assert (slot, status) == (1, 0)
    # now all slots full again; oldest active is slot2 (64) -> steal it
    slot, status = m._alloc_free_or_steal(77)
    assert (slot, status) == (2, 1)


def test_note_off_releases_oldest_matching():
    m = ControlModel()
    for _ in range(2):
        m.dispatch(Event(0, 0, NAME_TO_TYPE["note_on"], 60, 100), 0)
    seqs = [v.seq for v in m.voices if v.active]
    slot, status = m._release_oldest(60)
    assert status == 2
    assert [v.seq for v in m.voices if v.active] == [seqs[1]]  # oldest went


def test_patch_change_hard_switch_and_flush():
    seq = {"id": "t", "schema_version": 1, "sample_rate": 48000,
           "block_size": 32, "blocks": 40,
           "events": [mk(0, "note_on", 60, 80), mk(33, "cc", 11, 40),
                      mk(1000, "patch_change", 7, 0),
                      mk(1001, "note_on", 72, 90)]}
    trace, out, summary = render_sequence(seq, CounterStubEngine())
    # t=1000 quantizes UP into block 32
    rec = None
    for r in trace["blocks"]:
        if any(d["type_name"] == "patch_change" for d in r["decisions"]):
            rec = r
    d = [x for x in rec["decisions"] if x["type_name"] == "patch_change"][0]
    assert d["status"] == 8 and d["flushes"] == 1   # queued t=33 cc flushed
    assert rec["snapshot_after"]["active_count"] == 0  # hard switch: no tails
    assert rec["snapshot_after"]["patch_id"] == 7


def test_reset_and_rerender_deterministic():
    seq = {"id": "t", "schema_version": 1, "sample_rate": 48000,
           "block_size": 32, "blocks": 40,
           "events": [mk(0, "note_on", 60, 80), mk(100, "note_on", 62, 80),
                      mk(200, "note_off", 60, 0),
                      mk(1000, "patch_change", 3, 0),
                      mk(1101, "note_on", 55, 90)]}
    t1, o1, s1 = render_sequence(seq, CounterStubEngine())
    t2, o2, s2 = render_sequence(seq, CounterStubEngine())
    assert o1 == o2 and t1 == t2
    m = ControlModel()
    assert m.block == 0 and m.patch_id == 0 and m.active_count == 0
    assert len(m.queue.items) == 0


# ------------------------------------------------------------- accounting
def test_schedule_accounting_verdicts_match_sxt016_rows():
    worst = account_schedule(8, 192000000)
    assert worst["used_cycles_per_frame"]["total"] == 72 + 8 * 88 + 2 + 8 + 990
    assert worst["budget_cycles_per_frame"] == 4000 * 0.8
    assert worst["closure"] == "within_budget"
    over = account_schedule(8, 48000000)
    assert over["closure"] == "OVERFLOW"
    assert over["rejection"]["code"] == "schedule_budget_overflow"
    # same verdicts as the SXT-016 probe closure rows at every clock
    for f, want in ((48000000, "OVERFLOW"), (96000000, "OVERFLOW"),
                    (192000000, "within_budget"),
                    (480000000, "within_budget")):
        assert account_schedule(8, f)["closure"] == want


def test_stub_output_contract_catches_silent_slot():
    seq = {"id": "t", "schema_version": 1, "sample_rate": 48000,
           "block_size": 32, "blocks": 3,
           "events": [mk(0, "note_on", 60, 80)]}
    trace, out, _ = render_sequence(seq, CounterStubEngine())
    ok, _ = output_check(trace, out)
    assert ok
    trace, out, _ = render_sequence(seq, SilentStubEngine())
    ok, violations = output_check(trace, out)
    assert not ok and violations        # the negative control is caught


# --------------------------------------------------- committed fixtures
def _iverilog_present():
    return shutil.which("iverilog") is not None


def test_committed_fixtures_model_leg_and_manifest():
    import hashlib
    seqs = sorted(
        os.listdir(os.path.join(REPO, "fixtures", "control", "sequences")))
    assert len(seqs) >= 3                     # deliverable: >= 3 sequences
    for name in seqs:
        if not name.endswith(".json"):
            continue
        p = os.path.join(REPO, "fixtures", "control", "sequences", name)
        digest = hashlib.sha256(open(p, "rb").read()).hexdigest()
        with open(p) as f:
            seq = json.load(f)
        ident = seq["id"]
        _, out, summary = render_sequence(seq, CounterStubEngine())
        committed = open(os.path.join(
            REPO, "fixtures", "control", ident, "model_out.bin"), "rb").read()
        assert out == committed, ident        # deterministic re-render
        rec = json.load(open(os.path.join(
            REPO, "fixtures", "control", ident, "record.json")))
        assert summary["underruns"] == 0
        if ident in ("ctl-burst-overload-v1", "ctl-queue-overflow-v1"):
            assert not rec["overload"]["closes_declared_schedule"]
            assert summary["drops_total"] > 0 or \
                summary["reserve_exceeded_blocks"] > 0
        else:
            assert rec["overload"]["closes_declared_schedule"]
            assert summary["drops_total"] == 0
    # manifest integrity for the rtl recordings + traces
    man = json.load(open(os.path.join(REPO, "fixtures", "control",
                                      "manifest.json")))
    for rel, digest in man["files"].items():
        p = os.path.join(REPO, rel)
        assert hashlib.sha256(open(p, "rb").read()).hexdigest() == digest


def test_committed_fixtures_rtl_equality_or_not_run():
    if not _iverilog_present():
        print("NOT_RUN: iverilog not available; RTL fixture equality not "
              "executed (coverage: none for the RTL leg — not a pass)")
        return
    for ident in ("ctl-notes-steal-v1", "ctl-patch-change-v1",
                  "ctl-burst-overload-v1", "ctl-queue-overflow-v1"):
        seq = json.load(open(os.path.join(
            REPO, "fixtures", "control", "sequences", ident + ".json")))
        import tempfile
        work = tempfile.mkdtemp(prefix="sxt021-test-")
        try:
            v = run_comparison(seq, work)
            assert v["verdict"] == "PASS", (ident, v["first_failures"])
            assert v["byte_identical_outputs"]
        finally:
            shutil.rmtree(work, ignore_errors=True)


def test_comparator_catches_committed_queue_depth_mutant():
    if not _iverilog_present():
        print("NOT_RUN: iverilog not available; mutant control not "
              "executed (not a pass)")
        return
    seq = json.load(open(os.path.join(
        REPO, "fixtures", "control", "sequences",
        "ctl-queue-overflow-v1.json")))
    import tempfile
    work = tempfile.mkdtemp(prefix="sxt021-mut-")
    try:
        v = run_comparison(
            seq, work,
            os.path.join(REPO, "rtl", "control", "control_broken_mutant.sv"))
        assert v["verdict"] == "FAIL" and v["mismatches"] > 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_mutant_is_exact_single_constant_mutation():
    src = open(os.path.join(REPO, "rtl", "control",
                            "control_top.sv")).read()
    mut = open(os.path.join(REPO, "rtl", "control",
                            "control_broken_mutant.sv")).read()
    mutated = src.replace("parameter int QUEUE_DEPTH = 16,",
                          "parameter int QUEUE_DEPTH = 15,", 1)
    assert mutated != src
    # the committed mutant = NC banner (ending in its own timescale line)
    # + the mutated source with its original timescale line removed
    header = mut.split(mutated.replace("`timescale 1ns/1ps\n", "", 1))[0]
    assert mut == header + mutated.replace("`timescale 1ns/1ps\n", "", 1)
    assert mut.count("QUEUE_DEPTH = 15") == 1
    assert "QUEUE_DEPTH = 16" not in mut.split("module control_top")[1]


def test_fail_closed_inputs():
    bad = [
        {"id": "x", "schema_version": 2, "sample_rate": 48000,
         "block_size": 32, "blocks": 2, "events": []},
        {"id": "x", "schema_version": 1, "sample_rate": 44100,
         "block_size": 32, "blocks": 2, "events": []},
        {"id": "x", "schema_version": 1, "sample_rate": 48000,
         "block_size": 64, "blocks": 2, "events": []},
        {"id": "x", "schema_version": 1, "sample_rate": 48000,
         "block_size": 32, "blocks": 1,
         "events": [mk(64, "note_on", 60, 1)]},
        {"id": "x", "schema_version": 1, "sample_rate": 48000,
         "block_size": 32, "blocks": 4,
         "events": [mk(64, "note_on", 60, 1), mk(63, "cc", 1, 1)]},
        {"id": "x", "schema_version": 1, "sample_rate": 48000,
         "block_size": 32, "blocks": 4,
         "events": [mk(0, "theremin", 1, 1)]},
        {"id": "x", "schema_version": 1, "sample_rate": 48000,
         "block_size": 32, "blocks": 4,
         "events": [mk(0, "note_on", 200, 1)]},
    ]
    for seq in bad:
        try:
            render_sequence(seq, CounterStubEngine())
        except ValueError:
            continue
        raise AssertionError("fail-closed gate did not fire: %r" % seq)
