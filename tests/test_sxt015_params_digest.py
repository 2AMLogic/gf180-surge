"""Regression tests for SXT-015 parameter provenance (issue #248)."""

from model.resources.accounting import params_digest
from model.resources.params import REG


def test_params_digest_tracks_scoped_override_and_restores_afterward():
    baseline = params_digest()
    assert REG.clock_hz == 480_000_000

    with REG.override("clock_hz", 1_000_000):
        overridden = params_digest()
        assert REG.clock_hz == 1_000_000
        assert overridden != baseline

    assert REG.clock_hz == 480_000_000
    assert params_digest() == baseline


def test_to_json_serializes_the_live_overridden_parameter():
    with REG.override("clock_hz", 1_000_000):
        values = {p["name"]: p for p in REG.to_json()}
        assert values["clock_hz"]["value"] == 1_000_000
        assert "OVERRIDDEN" in values["clock_hz"]["estimate_ref"]
