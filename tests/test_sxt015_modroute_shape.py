"""SXT-015 modulation-row SHAPE tests (pytest; stdlib only).

Decision #239, fed by SXT-036's (#70) measured law
`route evaluations = routes x per-voice control passes`: the accounting
charges a modulation row by the scope it is EVALUATED in --

  * a global-list or scene-list row once per frame, and
  * a voice-list row once per worst-case live voice per frame,

with `cyc_modroute_frame` unchanged at 15 cycles per row EVALUATION. These
tests exist because the failure mode this decision invites is a change that
*claims* a new shape while leaving every account numerically identical (the
issue's own failure control), or one that scales the wrong rows, or scales by
something other than the live-voice count. Each of those is checked here
against the live model, and the committed decision record is required to be
re-derivable rather than hand-maintained.

Claim scope: this is bookkeeping-model arithmetic. `cyc_modroute_frame` is
still a `placeholder` value that NO SXT-016 probe pins, so nothing here is a
cycle, area, technology, timing, fidelity, preset-support or preset-quality
claim, and a `placeholder-v0` closure verdict is not a support claim in
either direction.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from model.resources.accounting import (  # noqa: E402
    _count_modroutes, _modroute_evaluations, _split_modroutes, account_graph,
    params_digest,
)
from model.resources.params import REG  # noqa: E402
from tools.account_corpus import (  # noqa: E402
    modroute_shape_decision, scan_corpus,
)

SXT015 = os.path.join(REPO, "reports", "sxt-015")
DECISION = os.path.join(SXT015, "decision-239-modroute-shape.json")
CORPUS_ACCOUNTING = os.path.join(SXT015, "corpus-accounting.json")
NC_SHAPE = os.path.join(SXT015, "negative-control", "nc-modroute-shape.json")
GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")

# fixed local profile: these tests must not depend on the fixture library,
# whose growth is a separate (recorded) accounting delta.
EVENT_PROFILE = {"max_coincident_events": 8, "peak_events_per_second": 1.0,
                 "source": "test-local fixed profile (not an evidence input)"}


def _row(dest="A Filter 1 Cutoff"):
    """A declared modulation row. Filter destinations on purpose: osc and
    waveshaper activity is read from these same rows, so a filter row moves
    the modulation term and nothing else."""
    return [1, 0, 0, 308, dest, 1.0, 1.0]


def _graph(n_global=0, n_scene=0, n_voice=0, poly=16):
    """Minimal normalized graph carrying a declared modulation-row split."""
    scene = {"osc": [], "mix": {}, "fu": [], "ws": {}, "lfo": []}
    return {
        "p": "synthetic/modroute-shape", "sha": "0" * 40, "b": "contributor",
        "st": "normalized",
        "g": {
            "sm": 0, "smn": "Single", "sa": 0, "poly": poly,
            "sc": [json.loads(json.dumps(scene)) for _ in range(2)],
            "fx": [], "fxd": 0, "fxb": 0, "wta": [], "dep": [],
            "md": {"g": [_row() for _ in range(n_global)],
                   "s": [{"s": [_row() for _ in range(n_scene)],
                          "v": [_row() for _ in range(n_voice)]},
                         {"s": [], "v": []}]},
        },
    }


def _account(**kw):
    return account_graph(_graph(**kw), fx_instance_limit=None,
                         event_profile=EVENT_PROFILE)


# ------------------------------------------------------------- pure split ----
@pytest.mark.parametrize("g,s,v", [(0, 0, 0), (1, 0, 0), (0, 2, 0),
                                   (0, 0, 3), (2, 4, 4), (1, 1, 1)])
def test_the_split_partitions_the_rows_and_totals_to_the_row_counter(g, s, v):
    graph = _graph(n_global=g, n_scene=s, n_voice=v)["g"]
    split = _split_modroutes(graph)
    assert split["rows_per_frame"] == g + s
    assert split["rows_per_voice"] == v
    assert split["rows_total"] == g + s + v
    # the row COUNT definition is unchanged by the decision
    assert split["rows_total"] == _count_modroutes(graph)


@pytest.mark.parametrize("worst", [1, 2, 8, 16, 32])
def test_evaluations_scale_voice_rows_only_and_never_go_below_the_row_count(
        worst):
    graph = _graph(n_global=2, n_scene=4, n_voice=4)["g"]
    assert _modroute_evaluations(graph, worst) == 6 + 4 * worst
    # monotone: the new shape can never charge LESS than the retired
    # once-per-frame shape, so no account can get cheaper
    assert _modroute_evaluations(graph, worst) >= _count_modroutes(graph)


def test_a_graph_with_no_voice_rows_is_voice_count_independent():
    graph = _graph(n_global=1, n_scene=5)["g"]
    counts = {_modroute_evaluations(graph, w) for w in (1, 2, 16, 32)}
    assert counts == {6}


# ------------------------------------------------- the accounting consumes ---
def test_the_accounted_term_is_evaluations_times_the_constant():
    acct = _account(n_global=2, n_scene=4, n_voice=4)
    mr = acct["budget"]["modulation_rows"]
    assert mr["worst_case_voices"] == 16
    assert mr["row_evaluations_per_frame"] == 6 + 4 * 16
    assert mr["cycles_per_row_evaluation"] == REG.cyc_modroute_frame
    assert (acct["budget"]["cost_cycles_per_frame"]["modulation"]
            == mr["row_evaluations_per_frame"] * REG.cyc_modroute_frame)


@pytest.mark.parametrize("d_scene,d_voice", [(1, 0), (0, 1), (3, 0), (0, 3),
                                             (2, 2)])
def test_the_shape_is_consumed_row_class_by_row_class(d_scene, d_voice):
    """A voice row must cost worst_voices x the constant and a scene row
    exactly the constant. A model that scaled every row (or none) moves by a
    different amount and fails here."""
    base = _account(n_global=1, n_scene=1, n_voice=1)
    moved = _account(n_global=1, n_scene=1 + d_scene, n_voice=1 + d_voice)
    worst = base["budget"]["modulation_rows"]["worst_case_voices"]
    expected = (d_scene + d_voice * worst) * REG.cyc_modroute_frame
    assert (moved["budget"]["cost_cycles_per_frame"]["modulation"]
            - base["budget"]["cost_cycles_per_frame"]["modulation"]
            == expected)


def test_the_failure_control_of_the_issue_actually_fires():
    """Issue #239's failure control: a control graph with voice rows and more
    than one worst-case voice must produce a DIFFERENT modulation term than
    the retired shape; with one live voice the two must coincide."""
    def retired(acc, graph):
        return (_split_modroutes(graph["g"])["rows_total"]
                * REG.cyc_modroute_frame)

    many = _graph(n_voice=3, poly=16)
    one = _graph(n_voice=3, poly=1)
    a_many = account_graph(many, event_profile=EVENT_PROFILE)
    a_one = account_graph(one, event_profile=EVENT_PROFILE)
    assert a_many["voice"]["worst_case_voices"] == 16
    assert a_one["voice"]["worst_case_voices"] == 1
    assert (a_many["budget"]["cost_cycles_per_frame"]["modulation"]
            != retired(a_many, many))
    assert (a_one["budget"]["cost_cycles_per_frame"]["modulation"]
            == retired(a_one, one))


# ------------------------------------------------- committed control record --
def test_the_committed_negative_control_record_fired():
    nc = json.load(open(NC_SHAPE, encoding="utf-8"))
    assert nc["outcome"] == "PASS"
    assert nc["checks"] and all(nc["checks"].values())
    v16 = nc["arms"]["voice_rows_poly16"]
    v1 = nc["arms"]["voice_rows_poly1"]
    s16 = nc["arms"]["scene_rows_poly16"]
    # re-derive each arm's arithmetic rather than trusting the record
    assert v16["accounted_modulation_cycles_per_frame"] == (
        v16["rows"]["rows_charged_once_per_frame"]
        + 16 * v16["rows"]["rows_charged_once_per_live_voice"]
    ) * REG.cyc_modroute_frame
    assert (v16["accounted_modulation_cycles_per_frame"]
            > v16["retired_shape_cycles_per_frame"])
    assert (v1["accounted_modulation_cycles_per_frame"]
            == v1["retired_shape_cycles_per_frame"])
    assert s16["rows"]["rows_charged_once_per_live_voice"] == 0
    assert (s16["accounted_modulation_cycles_per_frame"]
            == s16["retired_shape_cycles_per_frame"])


def test_the_negative_control_summary_still_reports_every_control_passing():
    s = json.load(open(os.path.join(SXT015, "negative-control",
                                    "summary.json"), encoding="utf-8"))
    assert s["all_pass"] is True
    controls = {c["control"] for c in s["controls"]}
    assert "modroute_voice_rows_charged_per_live_voice" in controls


# ------------------------------------------------ committed decision record --
def test_the_committed_decision_record_is_re_derivable():
    """The flip enumeration is generated, never hand-maintained: a re-scan
    must reproduce the committed record exactly."""
    committed = json.load(open(DECISION, encoding="utf-8"))
    records, _ep = scan_corpus()
    fresh = modroute_shape_decision(records)
    assert fresh == committed


def test_every_flip_is_toward_rejection_and_is_explained_by_voice_rows():
    d = json.load(open(DECISION, encoding="utf-8"))
    assert d["status_flipped_toward_fit"] == []
    assert d["status_flipped_count"] == len(d["status_flipped"])
    assert d["status_flipped_count"] > 0, (
        "a decision that flips nothing anywhere in the corpus has not "
        "changed the shape it claims to change")
    for f in d["status_flipped"]:
        assert f["direction"] == "fit -> rejected", f["path"]
        assert f["rows_charged_once_per_live_voice"] > 0, f["path"]
        assert f["worst_case_voices"] > 1, f["path"]
        # the flip is the budget crossing, not some other rejection appearing
        assert f["other_rejection_codes"] == [], f["path"]
        assert (f["total_cycles_retired_shape"]
                <= f["dsp_budget_cycles_per_frame"]
                < f["total_cycles_this_shape"]), f["path"]
        assert (f["modulation_cycles_this_shape"]
                > f["modulation_cycles_retired_shape"]), f["path"]


def test_the_decision_record_names_the_unchanged_constant():
    d = json.load(open(DECISION, encoding="utf-8"))
    assert d["cyc_modroute_frame"] == REG.cyc_modroute_frame == 15
    assert d["params_digest"] == params_digest()
    assert d["cost_profile"] == REG.cost_profile == "placeholder-v0"


def test_the_committed_corpus_scan_was_re_exported_for_this_shape():
    """Freshness tripwire on the two fields this decision moved."""
    c = json.load(open(CORPUS_ACCOUNTING, encoding="utf-8"))
    d = json.load(open(DECISION, encoding="utf-8"))
    assert c["params_digest"] == params_digest()
    assert c["model_version"] == d["model_version"]
    assert (c["budget_closure_placeholder_v0"]["within_budget"]
            == c["status_counts"]["fit"])
