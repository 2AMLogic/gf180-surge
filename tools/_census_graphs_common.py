#!/usr/bin/env python3
"""Shared census-vs-graphs zero-drift cross-check for the routing-form
carrier extractors (`tools/extract_rf_*_inputs.py`).

Every routing-form leaf re-verifies the SAME seven fields between the two
independently-derived committed corpus artifacts -- the static census CSV
(`corpus/census-v0.1/results/per-preset.csv`) and the surgepy-derived
normalized graph (`corpus/normalized/graphs.jsonl`) -- before it will emit a
carrier record: blob sha1, stored revision, scene mode, fx_bypass, fx_disable,
the non-off FX slot count and the non-off FX TYPE SET. Any disagreement is a
REFUSAL, never a silently-preferred source.

WHY THIS MODULE EXISTS (issue #154). Four extractors each carried a private
copy of that comparison and the copies had diverged on the one field that is
genuinely hard: the FX type set. Three copies compared the census CSV's FX
NAMES against the graph's engine DISPLAY names after stripping whitespace,
which resolves `Reverb 2` -> `Reverb2` and `Spring Reverb` -> `SpringReverb`
but NOT `Freq Shift` -> `FrequencyShifter` or `Ring Mod` -> `RingModulator`.
Those two pairs name the same stored type id, so a name-vs-name comparison
refuses on SPELLING rather than on CONTENT -- a spurious refusal that removed
legitimate corpus carriers (`closeout-sale`, `random-bass-fx`) from a leaf's
fixture set and would recur for every future leaf whose carriers use
Frequency Shifter (190 corpus presets) or Ring Modulator (40).

The single implementation here compares CONTENT: the graph's stored type IDS
are mapped through the census parser's OWN committed `FX` table
(`corpus/census-v0.1/census.py`) and compared against the census CSV's names,
so both sides speak one in-repo naming authority. There is no alias list, no
fuzzy or substring matching, and no weakening of the fail-closed contract: a
genuinely different FX type id in a slot still refuses, and a type id outside
the census table refuses rather than being dropped. The engine's live display
names are retained alongside as context only
(`cross_check.engine_display_names_context`), never as a comparison key.

Scope of the claim this module supports: it is a TOOLING cross-check between
two committed corpus artifacts. It establishes nothing about RTL-vs-frozen-
model exactness, nothing about model-vs-pinned-Surge agreement, and nothing
about preset support, coverage or musical quality.

Original to this repository (Apache-2.0).
"""

import os

__all__ = [
    "CROSS_CHECK_FIELDS",
    "FX_TYPE_NAME_AUTHORITY",
    "census_fx_table",
    "cross_check",
    "norm_type_name",
    "nonoff_fx_type_sets",
]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CENSUS_PY = os.path.join(REPO, "corpus", "census-v0.1", "census.py")

FX_TYPE_NAME_AUTHORITY = (
    "corpus/census-v0.1/census.py FX table, applied to the graph's stored "
    "type ids (content comparison, not spelling)"
)

#: the fields every routing-form extractor cross-checks, in record order
CROSS_CHECK_FIELDS = ("blob_sha1", "stored_revision", "scene_mode",
                      "fx_bypass", "fx_disable", "nonoff_fx_slot_count",
                      "nonoff_fx_type_set")

_CENSUS_FX_TABLE = None


def census_fx_table():
    """The census parser's own static FX-type table (`corpus/census-v0.1/
    census.py` `FX`), indexed by stored type id.

    Loaded from the committed census source itself rather than copied here,
    so the cross-check's naming authority cannot drift away from the artifact
    it is checking.
    """
    global _CENSUS_FX_TABLE
    if _CENSUS_FX_TABLE is None:
        import importlib.util  # noqa: PLC0415
        spec = importlib.util.spec_from_file_location("sxt_census_fx_table",
                                                      CENSUS_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CENSUS_FX_TABLE = list(mod.FX)
    return _CENSUS_FX_TABLE


def norm_type_name(name):
    """Whitespace-insensitive form of an FX type name.

    Both sides of the comparison are now named through the same census table,
    so this is belt-and-braces rather than the comparison's substance -- it is
    retained so a purely cosmetic whitespace change in that table could never
    turn into a refusal.
    """
    return "".join(str(name).split())


def nonoff_fx_type_sets(row, on_slots, *, refuse):
    """Return `(census_types, graph_types)` as comparable sorted name lists.

    `row` is the census CSV row; `on_slots` are the graph's non-off fx
    entries. The graph side is derived from each slot's stored type ID mapped
    through `census_fx_table()` -- NOT from the engine display name in
    `fx["tn"]`. Raises `refuse` if a stored type id is missing, non-integer,
    or outside the census table (fail-closed: an unmappable id is a refusal,
    never a dropped slot).
    """
    table = census_fx_table()
    census_types = {norm_type_name(t)
                    for t in row["stored_nonoff_fx_types"].split(";") if t}
    graph_types = set()
    for fx in on_slots:
        tid = fx.get("t")
        if not isinstance(tid, int) or not 0 <= tid < len(table):
            raise refuse(f"graphs.jsonl fx type id {tid!r} outside the "
                         f"census FX table (0..{len(table) - 1})")
        graph_types.add(norm_type_name(table[tid]))
    return sorted(census_types), sorted(graph_types)


def cross_check(row, graph, *, refuse):
    """Zero-drift assertion between the two committed artifacts.

    Returns the per-field comparison record for the caller to embed as
    `cross_check`; raises `refuse` on ANY disagreement.
    """
    g = graph["g"]
    on_slots = [fx for fx in g["fx"] if fx.get("on", 0)]
    census_types, graph_types = nonoff_fx_type_sets(row, on_slots,
                                                    refuse=refuse)
    checks = {
        "blob_sha1": (row["git_blob_sha1"], graph.get("sha")),
        "stored_revision": (int(row["stored_revision"]), graph.get("rev")),
        "scene_mode": (row["scene_mode"], g.get("smn")),
        "fx_bypass": (int(row["stored_fx_bypass"]), g.get("fxb")),
        "fx_disable": (int(row["stored_fx_disable"]), g.get("fxd")),
        "nonoff_fx_slot_count": (int(row["stored_nonoff_fx_slot_count"]),
                                 len(on_slots)),
        "nonoff_fx_type_set": (census_types, graph_types),
    }
    disagreements = [k for k, (a, b) in checks.items() if a != b]
    if disagreements:
        detail = "; ".join(
            f"{k}: census={checks[k][0]!r} graphs={checks[k][1]!r}"
            for k in disagreements)
        raise refuse(f"census-vs-graphs drift on {disagreements}: {detail}")
    return {"fields_compared": sorted(checks),
            "census_vs_graphs_drift_count": 0,
            "values": {k: checks[k][0] for k in checks},
            "fx_type_name_authority": FX_TYPE_NAME_AUTHORITY,
            "engine_display_names_context":
                sorted({fx.get("tn") for fx in on_slots})}
