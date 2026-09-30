"""SXT-015 `REG.override()` / `params_digest()` contract tests (issue #248).

`ParamRegistry.override()` mutates the live `self._p` dict, but
`ParamRegistry.to_json()` -- the sole input to `accounting.params_digest()`
-- iterates the module-level `PARAMS` list, never `self._p`. The digest is
therefore, and remains, deliberately OVERRIDE-BLIND: a declared
`REG.override()` experiment never moves `params_digest()`.

That is a decision, not a defect: the docstring on `override()` now says so.
The rule that replaces the old (false) "params_digest changes accordingly"
claim is: every account computed under a declared override must record the
override EXPLICITLY in its own output. These tests are the failure control
issue #248 requires -- they prove a synthetic overridden account is
distinguishable from a baseline account by the mechanism actually in force
(an explicit field), and that a bare digest comparison could NOT tell them
apart.

No cycle, area, technology, fidelity, preset-support, or preset-quality
claim. Bookkeeping-provenance hygiene only.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from model.resources.accounting import account_graph, params_digest  # noqa: E402
from model.resources.params import REG  # noqa: E402

GRAPHS = os.path.join(REPO, "corpus", "normalized", "graphs.jsonl")
NC_BUDGET_OVERFLOW = os.path.join(
    REPO, "reports", "sxt-015", "negative-control", "nc-budget-overflow.json")
EVENT_PROFILE = {"max_coincident_events": 8, "peak_events_per_second": 1.0,
                 "source": "test-local fixed profile (not an evidence input)"}


def _first_normalized_graph():
    with open(GRAPHS) as f:
        for raw in f:
            d = json.loads(raw)
            if d.get("st") == "normalized":
                return d
    raise AssertionError("no normalized graph in corpus/normalized/graphs.jsonl")


def test_override_mutates_the_live_value():
    """Sanity: the override mechanism itself does what its name says."""
    before = REG.clock_hz
    with REG.override("clock_hz", 1000000):
        assert REG.clock_hz == 1000000
    assert REG.clock_hz == before, "override must fully restore on exit"


def test_params_digest_is_override_blind():
    """The documented (post-#248) behavior: a declared override does NOT
    move params_digest(). This is the decision this issue records, not a
    latent bug -- keep this test green if that decision ever gets revisited
    on purpose, but revisit the docstring in the same change."""
    baseline_digest = params_digest()
    with REG.override("clock_hz", 1000000):
        overridden_digest = params_digest()
    assert overridden_digest == baseline_digest, (
        "params_digest moved under a REG.override(); either the digest "
        "mechanism changed (update ParamRegistry.override()'s docstring and "
        "this test to match) or this is a regression")


def test_overridden_account_is_distinguishable_from_baseline_by_an_explicit_field():
    """FAILURE CONTROL (issue #248 acceptance).

    A synthetic account produced under a declared override must be
    distinguishable from the baseline account by the mechanism this
    decision chose (an explicit field in the account's own output) -- NOT
    by params_digest, which is deliberately blind to it. If this test
    cannot tell the two accounts apart, the decision was not implemented.
    """
    graph = _first_normalized_graph()
    baseline = account_graph(graph, fx_instance_limit=None,
                             event_profile=EVENT_PROFILE)
    overridden_pool = baseline["limits"]["voice_pool"] - 1
    assert overridden_pool >= 1
    with REG.override("voice_pool_limit", overridden_pool):
        overridden = account_graph(graph, fx_instance_limit=None,
                                   event_profile=EVENT_PROFILE)

    # The digest alone cannot tell the two accounts apart (by design).
    assert baseline["params_digest"] == overridden["params_digest"], (
        "this test's premise (digest blindness) no longer holds; see "
        "test_params_digest_is_override_blind")

    # The explicit field DOES tell them apart -- this is the mechanism the
    # decision actually relies on.
    assert baseline["limits"]["voice_pool"] != overridden["limits"]["voice_pool"]
    assert overridden["limits"]["voice_pool"] == overridden_pool


def test_live_control_account_corpus_records_its_own_override():
    """One of the two live override users named by issue #248: the SXT-015
    negative control 3 (`tools/account_corpus.py`) computes an account under
    `REG.override("clock_hz", ...)` and must record the overridden value in
    its own committed output -- not rely on params_digest to reveal it."""
    with open(NC_BUDGET_OVERFLOW) as f:
        nc = json.load(f)
    assert nc["clock_hz_overridden"] == 1000000, (
        "the committed negative control no longer records its own "
        "clock_hz override explicitly")
    assert nc["rejections"][0]["detail"]["clock_hz"] == 1000000, (
        "the account's own rejection detail must also carry the "
        "overridden value, independent of the prose field above")


def test_live_control_profile_predict_records_its_own_override():
    """The other live override user: `tools/profile_predict.py` computes
    every per-preset account under `REG.override("voice_pool_limit", ...)`.
    The committed prediction artifacts must record the effective pool
    explicitly (bundle_spec + per-preset worst_case_voices), and the
    provenance note must not claim params_digest moves under it."""
    b1 = json.load(open(os.path.join(
        REPO, "reports", "sxt-017", "predictions", "B1-core-narrow.json")))
    b3 = json.load(open(os.path.join(
        REPO, "reports", "sxt-017", "predictions", "B3-ext-voice-fx.json")))

    note = b1["provenance"]["accounting_params_note"]
    assert "params_digest" not in note or "does NOT move" in note, (
        "the provenance note must not claim params_digest varies by pool "
        "(it does not -- the digest is override-blind); see "
        "ParamRegistry.override()'s docstring")

    # Two bundles with different declared voice_pool_limit must show a
    # different effective pool somewhere in their own committed output --
    # the explicit record this decision relies on, independent of digest.
    assert (b1["bundle_spec"]["voice_pool_limit"]
            != b3["bundle_spec"]["voice_pool_limit"]), (
        "fixture assumption violated: pick two committed bundles with "
        "distinct voice_pool_limit")
    for d in (b1, b3):
        supported = [p for p in d.get("presets", [])
                    if p["status"] == "supported"]
        assert supported, d["bundle_id"]
        for p in supported[:5]:
            assert (p["columns"]["worst_case_voices"]
                    <= d["bundle_spec"]["voice_pool_limit"])
