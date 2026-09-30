"""SXT-036 (#70) parameter-corner tests (pytest, no iverilog required).

Covers the oracle-independent machinery this leaf froze for its declared
parameter corners: the velocity quantizer over its whole 128-entry domain, the
rounding-tie property the tie corner relies on, the fail-closed range
derivation from `corpus/normalized/graphs.jsonl`, the corner route tables, the
checkpoint-word accounting (including the 32-bit boundary the over-range control
demonstrates), and the presence of the RTL mutation anchors the controls need.

These are claim-(1)-side unit tests: they establish nothing about
model-vs-pinned-engine agreement (NOT_RUN on this host, #96) and nothing about
fidelity or sound quality.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "model", "voice"))

import voice_model as vm                      # noqa: E402
import vel_param_corners as vpc               # noqa: E402
import vel_negative_controls as vnc           # noqa: E402

FQ = vm.FQ
ONE = vm.ONE


# ----------------------------------------------------- source-word domain ---
def test_vel_q_matches_float_quantizer_over_whole_domain():
    """The 128-entry velocity table is exact everywhere, not just at corners."""
    for midi in range(128):
        assert vpc.vel_q(midi) == vm.qint(midi / 127.0), midi


def test_vel_q_endpoints_and_monotonicity():
    assert vpc.vel_q(0) == 0
    assert vpc.vel_q(127) == ONE == 1 << 21
    words = [vpc.vel_q(m) for m in range(128)]
    assert all(b > a for a, b in zip(words, words[1:]))


def test_corner_velocities_give_odd_words_for_the_tie():
    """Velocities 1/63/126 give ODD Q10.21 words; 127 gives exactly 2^21.

    An odd source word is what makes a depth of exactly +-0.5 an exact
    round-half-up tie, so the tie corner depends on this property.
    """
    for midi in (1, 63, 126):
        assert vpc.vel_q(midi) % 2 == 1, midi
    assert vpc.vel_q(127) % 2 == 0


def test_half_depth_is_an_exact_rounding_tie_and_rounding_rule_bites():
    depth_q = 1 << (FQ - 1)                      # 0.5 in Q10.21
    assert vm.qint(0.5) == depth_q
    for midi in (1, 63, 126):
        src = vpc.vel_q(midi)
        p = depth_q * src
        assert p % (1 << FQ) == 1 << (FQ - 1)    # exactly on the .5 boundary
        rounded = (p + (1 << (FQ - 1))) >> FQ
        truncated = p >> FQ
        assert rounded == truncated + 1          # the tie discriminates
        assert vm.qmul(depth_q, src) == rounded  # frozen model rounds half up
        # negative depth: round-half-up goes toward +inf, truncation does not
        assert vm.qmul(-depth_q, src) == ((-p) + (1 << (FQ - 1))) >> FQ
        assert vm.qmul(-depth_q, src) == (-p >> FQ) + 1


# ------------------------------------------------------- derived ranges -----
@pytest.fixture(scope="module")
def ranges():
    return vpc.derive_ranges(0.005)


def test_derived_extents_agree_across_the_corpus(ranges):
    """Each destination's extent is derived by agreement, not asserted."""
    expected = {308: 130.0, 309: 1.0, 310: 192.0, 298: 96.0}
    for dest, want in expected.items():
        e = ranges["extents"][dest]
        assert e["rows"] > 100, (dest, e["rows"])
        assert e["relative_spread"] < 0.005
        assert vpc.rounded_extent(e["extent"]) == want
        assert abs(e["extent"] - want) / want < 0.005


def test_observed_source_depth_range_is_full_scale(ranges):
    for src in ("ms_velocity", "ms_releasevelocity"):
        o = ranges["observed_source_normalized_range"][src]
        assert o["rows"] > 0
        assert o["min"] == pytest.approx(-1.0)
        assert o["max"] == pytest.approx(1.0)


def test_release_velocity_has_no_corpus_route_to_fegmod_or_vca(ranges):
    """Recorded fact behind the corner table's declared fallback."""
    assert ranges["observed_in_class"]["ms_releasevelocity->310"]["rows"] == 0
    assert ranges["observed_in_class"]["ms_releasevelocity->298"]["rows"] == 0
    assert ranges["observed_in_class"]["ms_velocity->308"]["rows"] > 0


def test_range_derivation_refuses_a_sha256_pin_mismatch(monkeypatch):
    """Fail-closed control: a driver that cannot refuse proves nothing."""
    monkeypatch.setattr(vpc, "GRAPHS_SHA256", "0" * 64)
    with pytest.raises(vpc.Refuse):
        vpc.derive_ranges(0.005)


def test_range_derivation_refuses_an_impossible_tolerance(monkeypatch):
    with pytest.raises(vpc.Refuse):
        vpc.derive_ranges(1e-12)


# --------------------------------------------------------- corner tables ----
def test_corner_tables_cover_the_frozen_class(ranges):
    for kind, _note, _exact in vpc.CORNERS:
        rows = vpc.corner_table(kind, ranges["extents"],
                                ranges["observed_in_class"])
        assert len(rows) == 8, kind
        assert {r["dest_id"] for r in rows} == set(vpc.FROZEN_CLASS), kind
        assert {r["modsource_id"] for r in rows} == {1, 30}, kind


def test_full_scale_corner_uses_the_derived_extents(ranges):
    rows = vpc.corner_table("full-scale-positive", ranges["extents"],
                            ranges["observed_in_class"])
    depths = {(r["modsource_id"], r["dest_id"]): r["depth_raw"] for r in rows}
    assert depths[(1, 308)] == 130.0
    assert depths[(30, 310)] == 192.0
    assert depths[(1, 298)] == 96.0
    assert depths[(30, 309)] == 1.0


def test_observed_extreme_corner_records_its_fallbacks(ranges):
    fallbacks = []
    vpc.corner_table("observed-corpus-extreme", ranges["extents"],
                     ranges["observed_in_class"], fallbacks)
    # release velocity has no corpus route to 310 or 298: both must be recorded
    assert len(fallbacks) == 2
    assert all("no route with this source exists" in f for f in fallbacks)


def test_unknown_corner_kind_refuses(ranges):
    with pytest.raises(vpc.Refuse):
        vpc.corner_table("not-a-corner", ranges["extents"],
                         ranges["observed_in_class"])


# --------------------------------------------- checkpoint-word accounting ---
def _trace(depth_raw, vel_words, dest_id=310):
    """Minimal model-trace shape for trace_stats()."""
    return {
        "vel_routes": [{"source_id": 1, "dest_id": dest_id,
                        "depth_raw": depth_raw},
                       {"source_id": 30, "dest_id": dest_id,
                        "depth_raw": depth_raw}],
        "blocks": [{"b": 0, "voices": [
            {"slot": 0, "vel_words": list(vel_words),
             "vel_route_sums": [0, 0, vm.qmul(vm.qint(depth_raw), vel_words[0])
                                + vm.qmul(vm.qint(depth_raw), vel_words[1]), 0]}
        ]}],
    }


def test_declared_worst_case_corner_fits_the_32bit_checkpoint_word(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_trace(192.0, (ONE, ONE))))
    st = vpc.trace_stats(str(p))
    assert st["worst_abs_route_sum"] == 2 * vm.qint(192.0) == 805306368
    assert st["fits_32bit_checkpoint_word"] is True
    assert st["checkpoint_word_headroom_x"] == pytest.approx(2.666, abs=1e-3)
    assert st["saturated_qmul_terms"] == 0


def test_over_range_depth_breaks_the_checkpoint_word(tmp_path):
    """The boundary the over-range control demonstrates in simulation."""
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_trace(3 * 192.0, (ONE, ONE))))
    st = vpc.trace_stats(str(p))
    assert st["worst_abs_route_sum"] > (1 << 31) - 1
    assert st["fits_32bit_checkpoint_word"] is False


def test_trace_stats_counts_exact_ties(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(_trace(0.5, (vpc.vel_q(1), vpc.vel_q(63)))))
    st = vpc.trace_stats(str(p))
    assert st["exact_rounding_ties"] == 2         # both source words are odd


# --------------------------------------------------- RTL mutation anchors ---
def test_lifted_rom_carries_the_rounding_term():
    tb = open(vpc.TB_VEL, encoding="utf-8").read()
    rom = vpc.lift_rom(tb)
    assert "function automatic signed [31:0] vel_rom" in rom
    assert "+ 64'd127" in rom                    # the round-half-up term
    assert rom.rstrip().endswith("endfunction")


def test_control_mutation_anchors_still_exist_in_the_rtl():
    """A mutant whose anchor has drifted would silently become a no-op."""
    tb = open(vpc.TB_VEL, encoding="utf-8").read()
    for name in ("rom-floor", "round-trunc", "shared-slot"):
        for needle, _rep in vnc.MUTANTS[name]:
            assert tb.count(needle) >= 1, (name, needle)


def test_rom_floor_mutation_changes_most_of_the_table():
    """The exhaustive-ROM control must be able to fail on most entries."""
    floored = [(m * (1 << (FQ + 1))) // 254 for m in range(128)]
    differing = sum(1 for m in range(128) if floored[m] != vpc.vel_q(m))
    assert differing == 63


# ---------------------------------------------------------- corner stimulus -
def test_corner_stimulus_drives_the_source_corners_and_overlaps():
    path = os.path.join(REPO, "model", "voice", "sequences",
                        vpc.SEQ + ".json")
    seq = json.load(open(path, encoding="utf-8"))
    assert seq["schema_version"] == 1
    ons = [e for e in seq["events"] if e["type"] == "note_on"]
    offs = [e for e in seq["events"] if e["type"] == "note_off"]
    assert {e["velocity"] for e in ons} == {1, 63, 64, 126, 127}
    assert {e["velocity"] for e in offs} == {0, 1, 63, 126, 127}
    # MIDI note-on velocity 0 is a note-off; deliberately absent (needs oracle)
    assert all(e["velocity"] > 0 for e in ons)
    # one voice carries velocity 127 AND release velocity 127 (worst-case sum)
    both_max = [e["note"] for e in ons if e["velocity"] == 127]
    assert any(e["note"] in both_max and e["velocity"] == 127 for e in offs)
    # voices overlap: some note_on happens before an earlier note's note_off
    first_off = min(e["t"] for e in offs)
    assert sum(1 for e in ons if e["t"] < first_off) >= 2
