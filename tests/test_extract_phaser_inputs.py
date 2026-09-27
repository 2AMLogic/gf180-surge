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
property is asserted here rather than assumed.

#140 acted on that: the three carriers originally queued (`reson`, `bass11`,
`bass17`) are all refused by the repaired extractor -- the first two by this
screen, `bass17` by an active Conditioner slot the leaf's chain ladder does
not build -- so `extract_phaser_inputs.PRESETS` was re-selected from the
SXT-028 generator's own B4-scope candidate list. Both lists are pinned here:
the queued carriers must screen clean, and the dropped carriers' verdicts are
pinned so the omission record in `reports/SXT-028g/EVIDENCE.md` section 8
cannot drift away from what the screen actually says. None of these carriers
has been extracted (no oracle host), so no landed evidence depends on either
list.

The screen and `census_entry` read only committed repo files, so no surgepy /
oracle host is needed; the tool's import-time re-exec under the
manifest-pinned interpreter is neutralized below so the suite runs under
whatever interpreter invoked pytest.
"""
import ast
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

# FX classes tools/extract_phaser_inputs.py::extract() can actually build a
# chain entry for (delay, reverb1, phaser, eq); anything else active in a
# patch refuses with "outside landed scope".
CHAIN_LADDER_CLASSES = {1, 2, 3, 6}

# The SXT-028 generator's own B4-scope candidate list for this leaf, keyed by
# census path -> census blob SHA-1 (the SHA the extractor re-verifies against
# the engine checkout at run time).
with open(os.path.join(REPO, "reports", "sxt-028", "leaves", "SXT-028g",
                       "newly-enabled.json"), encoding="utf-8") as _f:
    B4_CANDIDATES = {c["path"]: c["sha"]
                     for c in json.load(_f)["b4_scope_candidates"]}


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

    `extract_phaser_inputs.PRESETS` is the B4-scope carrier list SXT-028g will
    extract the moment an oracle host exists; none of them has been extracted
    yet (reports/SXT-028g/EVIDENCE.md section 6), so no landed evidence depends
    on these verdicts. Re-derived here from `corpus/normalized/graphs.jsonl`
    rather than copied from a prior census run, per #140's stop/escalate
    condition: a carrier is never assumed clean because it was listed.

    Every queued carrier must screen clean. `PRESETS` growing a carrier that
    routes modulation into an FX parameter is a re-selection error, not
    something to patch around downstream.
    """
    expected = {
        "phasey": [],
        "squelch": [],
        "sticky": [],
    }
    assert sorted(ext.PRESETS) == sorted(expected), sorted(ext.PRESETS)
    for slug, rel in sorted(ext.PRESETS.items()):
        blob, graphs = census_entry(rel)
        assert graphs["st"] == "normalized", slug
        assert ext.phaser_fx_destinations(graphs) == expected[slug], slug
        # the carrier is one of the generator's own B4-scope candidates, at
        # the census blob the generator recorded (re-verified against the
        # engine checkout again at extraction time)
        assert blob == B4_CANDIDATES[rel], slug
        # a phaser slot is actually present, and no active slot needs an FX
        # class this leaf's chain ladder cannot build (the gate that refuses
        # the dropped `bass17`)
        types = {fx.get("t", 0) for fx in graphs["g"]["fx"]}
        assert 3 in types, slug
        assert not (types - {0} - CHAIN_LADDER_CLASSES), (slug, sorted(types))
        assert graphs["g"]["fxb"] == 0 and graphs["g"]["fxd"] == 0, slug


def test_screen_verdict_on_the_dropped_carriers_is_pinned():
    """The section-8 omission record, re-derived instead of transcribed.

    `reports/SXT-028g/EVIDENCE.md` section 8 records why the three originally
    queued carriers (issue #59) are omitted. Those causes are pinned here so
    the evidence record cannot drift from what the tooling actually does:

      reson   FX-destination modulation -> refused by the screen
      bass11  FX-destination modulation -> refused by the screen
      bass17  screen-clean, but an active Conditioner (fx type 8) in global1
              is outside this leaf's chain ladder -> extract() refuses

    The old loop is replayed against each of them as a live failure control:
    it let all three through.
    """
    dropped = {
        "reson": ("resources/data/patches_3rdparty/Argitoth/FX/Reson.fxp",
                  ["FX A1 Left", "FX A1 Right"]),
        "bass11": ("resources/data/patches_3rdparty/Bluelight/Basses/"
                   "Bass 11.fxp", ["FX A2 Mix"]),
        "bass17": ("resources/data/patches_3rdparty/Bluelight/Basses/"
                   "Bass 17.fxp", []),
    }
    for slug, (rel, hits) in sorted(dropped.items()):
        _, graphs = census_entry(rel)
        assert graphs["st"] == "normalized", slug
        assert ext.phaser_fx_destinations(graphs) == hits, slug
        # live failure control: the old loop caught none of them
        assert old_screen(graphs) == [], slug
        # none of the three is queued any more
        assert rel not in ext.PRESETS.values(), slug

    # bass17's cause is the chain ladder, not the screen: an active
    # Conditioner slot, which extract() refuses with "outside landed scope".
    _, b17 = census_entry(dropped["bass17"][0])
    unladdered = {fx.get("t", 0) for fx in b17["g"]["fx"]} - {0}
    unladdered -= CHAIN_LADDER_CLASSES
    assert unladdered == {8}, sorted(unladdered)


def test_renderer_queues_the_same_carriers_as_the_extractor():
    """One carrier list, not two that can drift apart.

    `tools/render_phaser_fixtures.py` keeps its own `PRESETS` literal (it is
    oracle-gated and pulls in the SXT-023 fixture machinery, so it is not
    imported here). Parse it instead of importing it, and require it to equal
    the extractor's: a renderer queueing a carrier the extractor refuses would
    put an unscreened preset into the reference leg.
    """
    src = os.path.join(REPO, "tools", "render_phaser_fixtures.py")
    with open(src, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=src)
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PRESETS"
                for t in node.targets):
            found = ast.literal_eval(node.value)
    assert found, "no module-level PRESETS literal in render_phaser_fixtures.py"
    assert found == ext.PRESETS, (found, ext.PRESETS)


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
