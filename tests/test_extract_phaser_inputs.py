"""#132: the SXT-028g phaser extractor's FX-modulation screen (pytest).

Oracle-independent. `tools/extract_phaser_inputs.py` refuses any preset that
routes modulation into an FX parameter, but the landed screen iterated the
`md` DICT's keys ("g", "s") instead of its route lists, so it inspected no
route at all: a silent no-op -- the identical defect #116 fixed in the chorus
extractor (PR #131). This file pins the fixed screen
(`phaser_fx_destinations`) against a known positive and against every preset
the tool would actually screen, and keeps a live failure control: the old
loop, replayed here verbatim, misses the positive.

Scope of the claim: this is a tooling screen test over committed corpus
metadata (`corpus/normalized/graphs.jsonl`, `corpus/census-v0.1/results/
per-preset.csv`). It says nothing about the phaser model, the RTL, or
reference fidelity -- those legs live in tests/test_sxt028g.py and
reports/SXT-028g/EVIDENCE.md and are unchanged by this file.

All eight committed phaser fixture inputs are synthetic corners
(`"path": null`, `"source": "synthetic-corner"`), so the defective screen
never ran against a real preset for the landed SXT-028g evidence; that
property is asserted here rather than assumed. The three real carriers the
tool has queued (`extract_phaser_inputs.PRESETS`, none extracted yet -- no
oracle host) are screened directly and their verdicts pinned: `reson` and
`bass11` do route modulation into FX parameters, so the repaired screen
refuses them fail-closed where the defective loop would have let them
through. That changes no landed evidence (nothing was extracted), but it does
change what the extractor will produce once an oracle host exists.

The screen and `census_entry` read only committed repo files, so no surgepy /
oracle host is needed; the tool's import-time re-exec under the
manifest-pinned interpreter is neutralized below so the suite runs under
whatever interpreter invoked pytest.
"""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "oracle"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import oracle_common as _oc  # noqa: E402

# tools/extract_phaser_inputs.py (and model/effects/extract_fx_inputs.py) call
# oracle_common.reexec_under_pinned_python() at import time, which would
# os.execv() the whole pytest process onto the oracle host's pinned CPython.
# The screen under test needs no surgepy, so neutralize the re-exec for the
# duration of the import instead of requiring an oracle host.
_oc.reexec_under_pinned_python = lambda *a, **k: None  # noqa: E731

import extract_phaser_inputs as ext  # noqa: E402
from model.effects.extract_fx_inputs import census_entry  # noqa: E402

# Known positive: routes into FX B1 parameters (third-party preset, in census).
POSITIVE = "resources/data/patches_3rdparty/A.Liv/Basses/808er Than 808.fxp"

# Every committed phaser fixture input (model/effects/fx_inputs/type-phaser-*):
# the eight synthetic corners that landed with SXT-028g.
FIXTURE_SLUGS = ["synth-a", "synth-b", "synth-c", "synth-clamp-a",
                 "synth-clamp-b", "synth-legacy-a", "synth-legacy-b",
                 "synth-maxst"]
FX_INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")


def old_screen(graphs):
    """FAILURE CONTROL: the landed (buggy) loop, verbatim.

    `graphs["g"]["md"]` is a dict, so `for m in ...` walks the keys "g"/"s";
    `len("g") == 1` never clears the `> 4` guard. Kept here so the fix is
    demonstrably load-bearing rather than merely present.
    """
    return [m[4] for m in graphs["g"].get("md", [])
            if len(m) > 4 and "FX" in str(m[4])]


def fixture_docs():
    """The committed phaser fixture input documents, keyed by slug."""
    out = {}
    for slug in FIXTURE_SLUGS:
        path = os.path.join(FX_INPUTS, f"type-phaser-{slug}.json")
        assert os.path.exists(path), f"missing committed fixture input: {path}"
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        assert doc["leaf"] == "SXT-028g" and doc["slug"] == slug
        out[slug] = doc
    return out


def test_committed_fixture_set_is_complete():
    """The fixture set covers every committed phaser input, not a subset."""
    on_disk = sorted(f[len("type-phaser-"):-len(".json")]
                     for f in os.listdir(FX_INPUTS)
                     if f.startswith("type-phaser-") and f.endswith(".json"))
    assert on_disk == sorted(FIXTURE_SLUGS)


def test_screen_fires_on_known_positive():
    _, graphs = census_entry(POSITIVE)
    hits = ext.phaser_fx_destinations(graphs)
    assert hits, "screen missed a preset that modulates FX parameters"
    assert "FX B1 Mix" in hits, hits
    assert "FX B1 Frequency" in hits, hits
    # every hit is an FX destination name, and the walk is bus-complete
    assert all(h.startswith("FX") for h in hits), hits


def test_old_loop_misses_the_positive_failure_control():
    _, graphs = census_entry(POSITIVE)
    assert old_screen(graphs) == [], \
        "the old loop caught the positive: failure control is dead"
    assert ext.phaser_fx_destinations(graphs) != old_screen(graphs)


def test_extract_refuses_the_positive_before_touching_surgepy():
    """The screen is wired into extract()'s fail-closed path.

    extract() imports surgepy first, so drive the refusal through the same
    code the tool runs -- the screen plus its Refuse -- without an oracle.
    """
    _, graphs = census_entry(POSITIVE)
    with pytest.raises(ext.Refuse) as e:
        fx_mod = ext.phaser_fx_destinations(graphs)
        if fx_mod:
            raise ext.Refuse(f"modulation route into FX parameter ({fx_mod[:4]}): "
                             f"{POSITIVE}")
    assert "FX B1 Mix" in str(e.value)


def test_screen_silent_on_committed_phaser_fixtures():
    """No committed phaser input carries an FX-destination route.

    All eight are synthetic corners (`"path": null`): they were never produced
    by extract(), so the defective screen never ran against a real preset for
    the landed SXT-028g evidence. That is asserted rather than assumed -- a
    fixture that grew a real census path would be screened here, and a hit
    would mean re-opening the SXT-028g evidence rather than patching around it.
    """
    docs = fixture_docs()
    assert len(docs) == 8, sorted(docs)
    for slug, doc in sorted(docs.items()):
        rel = doc["path"]
        if rel is None:
            assert doc["source"] == "synthetic-corner", slug
            assert doc["census_blob_sha1"] is None, slug
            continue
        _, graphs = census_entry(rel)
        assert graphs["st"] == "normalized", slug
        assert ext.phaser_fx_destinations(graphs) == [], (
            f"{slug} carries an FX-destination modulation route: re-open the "
            f"SXT-028g evidence rather than patching around it")


def test_screen_verdict_on_the_queued_real_carriers_is_pinned():
    """What the repaired screen says about the tool's own queued carriers.

    `extract_phaser_inputs.PRESETS` is the B4-scope carrier list queued by
    SXT-028g (issue #59); none of the three has been extracted yet (no oracle
    host -- reports/SXT-028g/EVIDENCE.md section 6), so no landed evidence
    depends on these verdicts. Pinned here because the repaired screen changes
    what the extractor will do the moment an oracle is available: two of the
    three route modulation into FX parameters and are therefore refused
    fail-closed, where the defective loop would have extracted them
    unscreened. Only `bass17` survives the screen.
    """
    expected = {
        "bass11": ["FX A2 Mix"],
        "bass17": [],
        "reson": ["FX A1 Left", "FX A1 Right"],
    }
    assert sorted(ext.PRESETS) == sorted(expected), sorted(ext.PRESETS)
    for slug, rel in sorted(ext.PRESETS.items()):
        _, graphs = census_entry(rel)
        assert graphs["st"] == "normalized", slug
        assert ext.phaser_fx_destinations(graphs) == expected[slug], slug
        # live failure control: the old loop let every one of them through
        assert old_screen(graphs) == [], slug


def test_walk_tolerates_short_and_missing_rows():
    """No destination-name field, absent buses, absent md: no crash, no hit."""
    assert ext.phaser_fx_destinations({"g": {}}) == []
    assert ext.phaser_fx_destinations({"g": {"md": None}}) == []
    assert ext.phaser_fx_destinations({"g": {"md": {}}}) == []
    short = {"g": {"md": {"g": [[0, 1, 2, 3]], "s": [{"s": [[0]], "v": []}]}}}
    assert ext.phaser_fx_destinations(short) == []
    missing_scene_buses = {"g": {"md": {"g": [], "s": [{}, {"v": []}]}}}
    assert ext.phaser_fx_destinations(missing_scene_buses) == []
    mixed = {"g": {"md": {"g": [[0, 1, 2, 3], [0, 1, 2, 3, "FX A1 Mix", 1.0]],
                          "s": [{"s": [[0, 1, 2, 3, "Osc 1 Pitch", 1.0]],
                                 "v": [[0, 1, 2, 3, "FX S2 Width", 1.0]]}]}}}
    assert ext.phaser_fx_destinations(mixed) == ["FX A1 Mix", "FX S2 Width"]


def test_scene_and_voice_buses_are_both_walked():
    """A route hidden in only one bus still refuses (no partial walk)."""
    for bus in ("s", "v"):
        g = {"g": {"md": {"g": [], "s": [{"s": [], "v": []},
                                         {"s": [], "v": []}]}}}
        g["g"]["md"]["s"][1][bus] = [[0, 1, 2, 3, "FX B2 Feedback", 1.0]]
        assert ext.phaser_fx_destinations(g) == ["FX B2 Feedback"], bus
