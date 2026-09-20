"""SXT-016 probe package tests (pytest).

Covers: record validation (positive + negative control), emission
refusal of under-specified records, byte-identical determinism of a
regeneration, and sanity of the headline cost relationships.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from probes import probe_fx_eq, probe_scheduler, validate
from probes.emit import write_record
from probes.probe_fx_reverb1 import stability_analysis
from probes.validate import make_invalid_record, validate_record


def test_invalid_record_is_rejected():
    ok, errors = validate_record(make_invalid_record())
    assert not ok
    assert any("clock" in e for e in errors)
    assert any("word_lengths" in e for e in errors)
    assert any("memory_model" in e for e in errors)
    assert any("assumptions" in e for e in errors)


def test_valid_record_passes():
    ok, errors = validate_record(_minimal_valid_record())
    assert ok, errors


def test_emit_refuses_underspecified_record(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        write_record(make_invalid_record(), str(tmp_path))
    assert os.listdir(str(tmp_path)) == []


def test_probe_rerun_is_byte_identical():
    dirs = []
    for _ in range(2):
        d = tempfile.mkdtemp(prefix="sxt016-test-")
        probe_fx_eq.run(os.path.join(d, "eq"))
        probe_scheduler.run(os.path.join(d, "sched"))
        dirs.append(d)
    for name in sorted(os.listdir(dirs[0] + "/eq")):
        a = open(os.path.join(dirs[0], "eq", name), "rb").read()
        b = open(os.path.join(dirs[1], "eq", name), "rb").read()
        assert a == b
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)


def test_every_record_carries_assumptions(tmp_path):
    d = os.path.join(str(tmp_path), "eq")
    paths = probe_fx_eq.run(d)
    assert paths
    for p in paths:
        rec = json.load(open(p))
        ok, errors = validate_record(rec)
        assert ok, (p, errors)
        assert rec["memory_model"]["external"]["name"] in (
            "E1", "E2", "E3", "none")
        assert rec["state_ram_bits"] >= 0


def test_osc_cycles_pinned_structure_exceeds_adaptation_candidates():
    # structural sanity: BLIT convolution costs more than naive playback
    from probes import probe_osc
    d = tempfile.mkdtemp(prefix="sxt016-osc-")
    probe_osc.run(os.path.join(d, "osc"))
    by_kernel = {}
    for fn in os.listdir(os.path.join(d, "osc")):
        r = json.load(open(os.path.join(d, "osc", fn)))
        if r["word_lengths"]["multiplier"] != "M18":
            continue
        if r["word_lengths"]["phase_bits"] != 24:
            continue
        by_kernel[r["kernel"]] = r["cycles_per_sample"]
    assert by_kernel["classic_blit"] > by_kernel["classic_naive_plus_lp"]
    assert by_kernel["wavetable_blit"] > by_kernel["wavetable_direct_interp"]
    assert by_kernel["classic_blit"] > by_kernel["sine_poly_fastmath"]
    shutil.rmtree(d, ignore_errors=True)


def test_reverb_stability_guard_band():
    st = stability_analysis()
    rho = st["rho_nonuniform_power_iteration"]["rho_nonuniform_max"]
    assert 0 < rho < 1
    assert st["required_guard_bits"] >= 1
    assert st["recommended_internal_word_bits"] == 24 + st["required_guard_bits"]


def test_scheduler_reconciles_sxt015_event_model():
    stats = probe_scheduler.load_event_stats()
    assert stats["max_coincident_per_frame"] == 8  # SXT-015: 8


def test_closure_formula_arithmetic():
    from probes.common import closure
    cl = closure(48_000_000, 500, control=10, transfer=8, contention=32)
    assert cl["gross_cycles_per_frame"] == 1000
    assert cl["dsp_budget_cycles_per_frame"] == 1000 * 0.8 - 50
    assert cl["closure"] == "within_budget"
    cl2 = closure(48_000_000, 5000)
    assert cl2["closure"] == "OVERFLOW"


def _minimal_valid_record():
    from probes.common import CLOCK_CANDIDATES_HZ, TECH, closure
    return {
        "probe": "probe_test",
        "kernel": "k",
        "clock_hz_candidates": list(CLOCK_CANDIDATES_HZ),
        "sample_rate_hz": 48000,
        "word_lengths": {"audio_bits": 24, "multiplier": "M18"},
        "has_phase_accumulator": False,
        "memory_model": {"name": "onchip_1rw_sram",
                         "onchip_sram": TECH["onchip_sram"],
                         "external": {"name": "none", "detail": "x"}},
        "assumptions": ["a"],
        "structure_citations": ["c"],
        "ops": {},
        "cycles_per_frame": 10,
        "state_ram_bits": 0,
        "ext_bytes_per_frame": 0,
        "closure_at_clocks": {c: closure(c, 10) for c in CLOCK_CANDIDATES_HZ},
        "sxt015_replacement": {"replaces": "none"},
        "status": "ESTIMATE",
    }
