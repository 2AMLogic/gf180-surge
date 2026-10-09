"""#310 / F-028f-3: SXT-012 fixture policy for source-nonrepeatable presets.

Pins the option-A disposition (decision-records/0019) against the committed
#126 records.  Integrity checks only: no oracle step runs here, so the
census, the voice-path bisection and any new refusal stay NOT_RUN.
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(REPO, "reports", "SXT-028f", "artifacts",
                    "determinism-gate.json")
SCREEN = os.path.join(REPO, "reports", "SXT-028f", "artifacts",
                      "carrier-screen.json")
DR = os.path.join(REPO, "decision-records",
                  "0019-source-nondeterministic-carrier-policy.md")
NAMED = ("grant_me", "novuo", "harp")


def _load(p):
    with open(p) as f:
        return json.load(f)


def check_census_controls(classify, gate):
    """Return the list of control failures for a candidate classifier.

    classify(slug, stress_rows) -> True if the classifier calls the carrier
    repeatable.  A sound classifier must call the bimodal control and the
    named carriers NOT repeatable.  Empty list == controls satisfied.
    """
    rows = {}
    for r in gate["stress_screen"]:
        rows.setdefault(r["slug"], []).append(r)
    failures = []
    if classify("lapharp", rows["lapharp"]):
        failures.append("bimodal control lapharp classified repeatable")
    for slug in NAMED:
        if classify(slug, rows[slug]):
            failures.append(f"refused carrier {slug} classified repeatable")
    return failures


def stress_classifier(slug, rows):
    # repeatable only if every stress row has one dry and one wet buffer
    return all(r["distinct_dry_buffers"] == 1
               and r["distinct_wet_buffers"] == 1 for r in rows)


def test_named_carriers_remain_refused_with_unstable_dry_bus():
    gate = _load(GATE)
    res = [r for r in gate["results"] if r["slug"] in NAMED]
    assert len(res) == 6
    assert all(r["status"] == "REFUSED" for r in res)
    for r in res:
        assert len(set(r["repeat_sha256"])) == 3
    for r in gate["stress_screen"]:
        if r["slug"] in NAMED:
            assert r["distinct_dry_buffers"] > 1
            assert r["stable"] is False


def test_gate_not_softened_and_screen_counts_preserved():
    gate = _load(GATE)
    assert gate["repeats"] == 3
    rg = _load(SCREEN)["render_gate"]
    assert (rg["attempted"], rg["passing"]) == (49, 10)
    assert "bit-identical" in gate["gate"]


def test_positive_control_rederives_byte_identically():
    pcs = _load(GATE)["positive_control"]
    assert len(pcs) >= 3
    for pc in pcs:
        assert pc["byte_identical"] is True
        assert pc["committed_wet_sha256"] == pc["rederived_wet_sha256"]


def test_bimodal_control_is_present():
    rows = [r for r in _load(GATE)["stress_screen"] if r["slug"] == "lapharp"]
    assert any(r["distinct_wet_buffers"] > 1 for r in rows)
    assert any(r["distinct_wet_buffers"] == 1 for r in rows)


def test_sound_classifier_satisfies_controls():
    assert check_census_controls(stress_classifier, _load(GATE)) == []


def test_always_pass_classifier_fails_controls():
    """Live negative control: marking every carrier repeatable must fail."""
    fails = check_census_controls(lambda s, r: True, _load(GATE))
    assert len(fails) == 4  # lapharp + three named carriers


def test_single_3x_pass_classifier_fails_bimodal_control():
    """A '3x passed once' classifier is exposed by the Lap Harp row that
    passes the 3x gate but not the stress screen."""
    gate = _load(GATE)
    # lapharp's seq-poly-8 row is stable: a last-row-wins classifier
    # calls it repeatable and must be caught by the bimodal control.
    assert any("bimodal" in f for f in
               check_census_controls(lambda s, r: r[-1]["stable"], gate))


def test_decision_record_states_option_a_and_limits():
    t = open(DR).read()
    assert "Option A" in t
    for s in ("NOT_RUN", "Options B", "never counted toward original-preset",
              "Lap Harp", "positive control", "ONE committed command"):
        assert s.lower() in t.lower(), s
    idx = open(os.path.join(REPO, "decision-records", "README.md")).read()
    assert "0019-source-nondeterministic-carrier-policy.md" in idx


def test_policy_is_linked_from_evidence_and_fixture_readme():
    for rel in ("fixtures/README.md", "reports/sxt-012/EVIDENCE.md",
                "reports/SXT-028f/EVIDENCE.md"):
        assert "0019-source-nondeterministic-carrier-policy" in \
            open(os.path.join(REPO, rel)).read(), rel
