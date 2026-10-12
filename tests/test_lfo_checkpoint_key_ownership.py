"""Issue #455: LFO checkpoint keys must be unique and model-owned before an
RTL exactness PASS (SXT-032 voice LFO, SXT-041 scene LFO).

Synthetic traces only: no simulator, no oracle.  These are parser/comparison
and report-boundary controls, not evidence about the RTL or the model.
"""
import json
import os
import sys
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import tools.compare_lfo_rtl_model as lfo  # noqa: E402
import tools.compare_slfo_rtl_model as slfo  # noqa: E402
from _rtl_compile_common import LeafInputError  # noqa: E402

NS = 6

LFO_MODEL = {"blocks": [{"b": 0, "voices": [{
    "slot": 0,
    "lfo": [{"index": 0, "phase": 1, "env_state": 1, "env_phase": 2,
             "env_val": 3, "output": 4}],
    "lfo_route_sums": [5, 6]}]}]}
LFO_GOOD = ["L 0 0 0 1 1 2 3 4", "S 0 0 5 6"]

SLFO_MODEL = {"blocks": [{
    "b": 0,
    "slfo": [{"index": i, "phase": 1 + i, "env_state": 4, "env_phase": 2,
              "env_val": 5, "output": 3} for i in range(NS)],
    "slfo_route_sums": [7, 9],
    "slfo_route_out": [3] * NS}]}
SLFO_GOOD = (["L 0 %d %d 4 2 5 3" % (i, 1 + i) for i in range(NS)]
             + ["S 0 7 9", "O 0 3 3 3 3 3 3"])


def _w(tmp_path, rows):
    p = tmp_path / "trace.txt"
    p.write_text("\n".join(rows) + "\n")
    return str(p)


def _lfo_cmp(tmp_path, rows):
    tb = lfo.parse_tb(_w(tmp_path, rows))
    return lfo.compare(LFO_MODEL, tb)


def _slfo_cmp(tmp_path, rows):
    tb = slfo.parse_tb(_w(tmp_path, rows))
    return slfo.compare(SLFO_MODEL, tb)


# ------------------------------------------------------------ valid traces
def test_lfo_unique_matching_trace_keeps_counts(tmp_path):
    checked, fails = _lfo_cmp(tmp_path, LFO_GOOD)
    assert not fails
    assert checked == {"lfo_checkpoints": 1, "lfo_fields": 5, "route_sums": 1}


def test_lfo_order_independent_valid_trace(tmp_path):
    _, fails = _lfo_cmp(tmp_path, list(reversed(LFO_GOOD)))
    assert not fails


def test_slfo_unique_matching_trace_keeps_counts(tmp_path):
    checked, fails = _slfo_cmp(tmp_path, SLFO_GOOD)
    assert not fails
    assert checked["slfo_checkpoints"] == NS
    assert checked["slfo_fields"] == 5 * NS
    assert checked["route_sums"] == 1 and checked["route_latches"] == 1


def test_slfo_order_independent_valid_trace(tmp_path):
    _, fails = _slfo_cmp(tmp_path, list(reversed(SLFO_GOOD)))
    assert not fails


# --------------------------------------------------------------- duplicates
LFO_DUPS = {
    "L-identical": ["L 0 0 0 1 1 2 3 4"],
    "L-wrong-first": ["L 0 0 0 99 1 2 3 4"],
    "S-identical": ["S 0 0 5 6"],
    "S-wrong-first": ["S 0 0 50 60"],
}


@pytest.mark.parametrize("name", sorted(LFO_DUPS))
@pytest.mark.parametrize("wrong_first", [True, False])
def test_lfo_duplicate_key_refused(tmp_path, name, wrong_first):
    extra = LFO_DUPS[name]
    rows = extra + LFO_GOOD if wrong_first else LFO_GOOD + extra
    with pytest.raises(LeafInputError) as ei:
        lfo.parse_tb(_w(tmp_path, rows))
    assert "duplicate" in ei.value.reason
    assert name[0] in ei.value.reason


@pytest.mark.parametrize("kind,bad", [
    ("L", "L 0 %d %d 9 9 9 9"), ("S", "S 0 99 99"), ("O", "O 0 9 9 9 9 9 9")])
@pytest.mark.parametrize("wrong_first", [True, False])
def test_slfo_duplicate_key_refused(tmp_path, kind, bad, wrong_first):
    row = bad % (2, 99) if kind == "L" else bad
    rows = [row] + SLFO_GOOD if wrong_first else SLFO_GOOD + [row]
    with pytest.raises(LeafInputError) as ei:
        slfo.parse_tb(_w(tmp_path, rows))
    assert "duplicate" in ei.value.reason
    assert (": %s " % kind) in ei.value.reason


def test_slfo_identical_duplicate_refused(tmp_path):
    with pytest.raises(LeafInputError):
        slfo.parse_tb(_w(tmp_path, SLFO_GOOD + [SLFO_GOOD[0]]))


# ------------------------------------------------------ extra / missing keys
@pytest.mark.parametrize("extra", [
    "L 99 0 0 1 1 2 3 4",    # extra block
    "L 0 7 0 1 1 2 3 4",     # extra voice slot
    "L 0 0 3 1 1 2 3 4",     # extra instance
    "S 99 0 5 6",
    "S 0 7 5 6",
])
def test_lfo_extra_key_fails_despite_matching_rest(tmp_path, extra):
    checked, fails = _lfo_cmp(tmp_path, LFO_GOOD + [extra])
    assert any("unowned" in f for f in fails), fails
    # compared coverage is unchanged by the unowned record
    assert checked["lfo_checkpoints"] == 1 and checked["route_sums"] == 1


@pytest.mark.parametrize("extra", [
    "L 99 0 1 4 2 5 3",
    "L 0 %d 1 4 2 5 3" % NS,
    "S 99 7 9",
    "O 99 3 3 3 3 3 3",
])
def test_slfo_extra_key_fails_despite_matching_rest(tmp_path, extra):
    checked, fails = _slfo_cmp(tmp_path, SLFO_GOOD + [extra])
    assert any("unowned" in f for f in fails), fails
    assert checked["slfo_checkpoints"] == NS


def test_lfo_missing_keys_fail(tmp_path):
    for rows in (LFO_GOOD[1:], LFO_GOOD[:1]):
        _, fails = _lfo_cmp(tmp_path, rows)
        assert any("missing" in f for f in fails)


@pytest.mark.parametrize("drop", ["L 0 3", "S 0", "O 0"])
def test_slfo_missing_keys_fail(tmp_path, drop):
    rows = [r for r in SLFO_GOOD if not r.startswith(drop)]
    _, fails = _slfo_cmp(tmp_path, rows)
    assert any("missing" in f for f in fails)


# ------------------------------------------ CLI / report boundary (stubbed)
def _run_lfo(monkeypatch, tmp_path, rows):
    import _rtl_compile_common as rcc
    run_dir = str(tmp_path)
    (tmp_path / "model_trace.json").write_text(json.dumps(LFO_MODEL))
    trace = _w(tmp_path, rows)
    sim = types.SimpleNamespace(sim_fails=[], trace=trace, stdout_tail="")
    monkeypatch.setattr(rcc, "compile_and_run", lambda *a, **k: sim)
    out = str(tmp_path / "v.json")
    monkeypatch.setattr(sys, "argv", ["c", "--run-dir", run_dir, "--out", out])
    rc = lfo.main()
    return rc, json.load(open(out))


def _run_slfo(monkeypatch, tmp_path, rows):
    run_dir = str(tmp_path)
    (tmp_path / "model_trace.json").write_text(json.dumps(SLFO_MODEL))
    trace = _w(tmp_path, rows)
    sim = types.SimpleNamespace(sim_fails=[], trace=trace, stdout_tail="")
    monkeypatch.setattr(slfo, "compile_and_run", lambda *a, **k: sim)
    out = str(tmp_path / "v.json")
    monkeypatch.setattr(sys, "argv", ["c", "--run-dir", run_dir, "--out", out])
    rc = slfo.main()
    return rc, json.load(open(out))


@pytest.mark.parametrize("runner,good", [(_run_lfo, LFO_GOOD),
                                         (_run_slfo, SLFO_GOOD)])
def test_cli_unique_trace_passes(monkeypatch, tmp_path, runner, good):
    rc, d = runner(monkeypatch, tmp_path, good)
    assert rc == 0 and d["verdict"] == "PASS" and d["comparison"] == "PASS"


@pytest.mark.parametrize("runner,rows", [
    # NEGATIVE CONTROL: wrong phase followed by the correct same-key row
    (_run_lfo, ["L 0 0 0 99 1 2 3 4"] + LFO_GOOD),
    (_run_slfo, ["L 0 2 99 4 2 5 3"] + SLFO_GOOD),
])
def test_cli_wrong_then_correct_duplicate_is_refused(monkeypatch, tmp_path,
                                                     runner, rows):
    rc, d = runner(monkeypatch, tmp_path, rows)
    assert rc != 0
    assert d["verdict"] == "FAIL" and d["comparison"] == "NOT_RUN"
    assert "duplicate" in d["input_error"]["reason"]
    assert all(v == 0 for v in d["checked"].values())


@pytest.mark.parametrize("runner,rows", [
    # NEGATIVE CONTROL: extra block checkpoint, all other values matching
    (_run_lfo, LFO_GOOD + ["L 99 0 0 1 1 2 3 4"]),
    (_run_slfo, SLFO_GOOD + ["L 99 0 1 4 2 5 3"]),
])
def test_cli_extra_block_checkpoint_fails(monkeypatch, tmp_path, runner,
                                          rows):
    rc, d = runner(monkeypatch, tmp_path, rows)
    assert rc != 0
    assert d["verdict"] == "FAIL" and d["comparison"] == "FAIL"
    assert "unowned" in d["first_failures"][0]
    assert d["checked"][next(iter(d["checked"]))] > 0   # compared coverage kept
