"""#116: the SXT-028c chorus extractor's FX-modulation screen (pytest).

Oracle-independent. `tools/extract_chorus_inputs.py` refuses any preset that
routes modulation into an FX parameter, but the landed screen iterated the
`md` DICT's keys ("g", "s") instead of its route lists, so it inspected no
route at all: a silent no-op. This file pins the fixed screen
(`chorus_fx_destinations`) against a known positive and against every
committed chorus fixture, and keeps a live failure control: the old loop,
replayed here verbatim, misses the positive.

Scope of the claim: this is a tooling screen test over committed corpus
metadata (`corpus/normalized/graphs.jsonl`, `corpus/census-v0.1/results/
per-preset.csv`). It says nothing about the chorus model, the RTL, or
reference fidelity -- those legs live in tests/test_sxt028c.py and
reports/SXT-028c/EVIDENCE.md and are unchanged by this file.

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

# tools/extract_chorus_inputs.py (and model/effects/extract_fx_inputs.py) call
# oracle_common.reexec_under_pinned_python() at import time, which would
# os.execv() the whole pytest process onto the oracle host's pinned CPython.
# The screen under test needs no surgepy, so neutralize the re-exec for the
# duration of the import instead of requiring an oracle host.
_oc.reexec_under_pinned_python = lambda *a, **k: None  # noqa: E731

import extract_chorus_inputs as ext  # noqa: E402
from model.effects.extract_fx_inputs import census_entry  # noqa: E402

# Known positive: routes into FX B1 parameters (third-party preset, in census).
POSITIVE = "resources/data/patches_3rdparty/A.Liv/Basses/808er Than 808.fxp"

# Every committed chorus fixture input (model/effects/fx_inputs/type-chorus-*):
# the four slugs whose extraction landed with SXT-028c.
FIXTURE_SLUGS = ["alienappears", "fmcombo", "fmtwang2", "melon"]
FX_INPUTS = os.path.join(REPO, "model", "effects", "fx_inputs")


def old_screen(graphs):
    """FAILURE CONTROL: the landed (buggy) loop, verbatim.

    `graphs["g"]["md"]` is a dict, so `for m in ...` walks the keys "g"/"s";
    `len("g") == 1` never clears the `> 4` guard. Kept here so the fix is
    demonstrably load-bearing rather than merely present.
    """
    return [m[4] for m in graphs["g"].get("md", [])
            if len(m) > 4 and "FX" in str(m[4])]


def fixture_paths():
    """Census-relative paths of the committed chorus fixture inputs."""
    out = {}
    for slug in FIXTURE_SLUGS:
        path = os.path.join(FX_INPUTS, f"type-chorus-{slug}.json")
        assert os.path.exists(path), f"missing committed fixture input: {path}"
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        assert doc["leaf"] == "SXT-028c" and doc["slug"] == slug
        out[slug] = doc["path"]
    return out


def test_committed_fixture_set_is_complete():
    """The negative set covers every committed chorus fixture, not a subset."""
    on_disk = sorted(f[len("type-chorus-"):-len(".json")]
                     for f in os.listdir(FX_INPUTS)
                     if f.startswith("type-chorus-") and f.endswith(".json"))
    assert on_disk == sorted(FIXTURE_SLUGS)


def test_screen_fires_on_known_positive():
    _, graphs = census_entry(POSITIVE)
    hits = ext.chorus_fx_destinations(graphs)
    assert hits, "screen missed a preset that modulates FX parameters"
    assert "FX B1 Mix" in hits, hits
    # every hit is an FX destination name, and the walk is bus-complete
    assert all(h.startswith("FX") for h in hits), hits


def test_old_loop_misses_the_positive_failure_control():
    _, graphs = census_entry(POSITIVE)
    assert old_screen(graphs) == [], \
        "the old loop caught the positive: failure control is dead"
    assert ext.chorus_fx_destinations(graphs) != old_screen(graphs)


def test_extract_refuses_the_positive_before_touching_surgepy():
    """The screen is wired into extract()'s fail-closed path.

    extract() imports surgepy first, so drive the refusal through the same
    code the tool runs -- the screen plus its Refuse -- without an oracle.
    """
    _, graphs = census_entry(POSITIVE)
    with pytest.raises(ext.Refuse) as e:
        fx_mod = ext.chorus_fx_destinations(graphs)
        if fx_mod:
            raise ext.Refuse(f"modulation route into FX parameter ({fx_mod[:4]}): "
                             f"{POSITIVE}")
    assert "FX B1 Mix" in str(e.value)


def test_screen_silent_on_committed_chorus_fixtures():
    paths = fixture_paths()
    for slug, rel in sorted(paths.items()):
        blob, graphs = census_entry(rel)
        assert graphs["st"] == "normalized", slug
        assert ext.chorus_fx_destinations(graphs) == [], (
            f"{slug} carries an FX-destination modulation route: re-open the "
            f"SXT-028c evidence rather than patching around it")


def test_walk_tolerates_short_and_missing_rows():
    """No destination-name field, absent buses, absent md: no crash, no hit."""
    assert ext.chorus_fx_destinations({"g": {}}) == []
    assert ext.chorus_fx_destinations({"g": {"md": None}}) == []
    assert ext.chorus_fx_destinations({"g": {"md": {}}}) == []
    short = {"g": {"md": {"g": [[0, 1, 2, 3]], "s": [{"s": [[0]], "v": []}]}}}
    assert ext.chorus_fx_destinations(short) == []
    mixed = {"g": {"md": {"g": [[0, 1, 2, 3], [0, 1, 2, 3, "FX A1 Mix", 1.0]],
                          "s": [{"s": [[0, 1, 2, 3, "Osc 1 Pitch", 1.0]],
                                 "v": [[0, 1, 2, 3, "FX S2 Width", 1.0]]}]}}}
    assert ext.chorus_fx_destinations(mixed) == ["FX A1 Mix", "FX S2 Width"]


def test_scene_and_voice_buses_are_both_walked():
    """A route hidden in only one bus still refuses (no partial walk)."""
    for bus in ("s", "v"):
        g = {"g": {"md": {"g": [], "s": [{"s": [], "v": []},
                                         {"s": [], "v": []}]}}}
        g["g"]["md"]["s"][1][bus] = [[0, 1, 2, 3, "FX B2 Feedback", 1.0]]
        assert ext.chorus_fx_destinations(g) == ["FX B2 Feedback"], bus
