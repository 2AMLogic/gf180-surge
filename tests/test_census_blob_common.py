"""#493/#633: tests for the shared census-blob / graphs-entry / git-blob helpers.

Tooling-only: checks `tools/_census_blob_common.py` against the committed
census CSV, the committed normalized graphs and git's own blob hashing. Makes
no fidelity, RTL or preset-quality claim.
"""

import csv
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, REPO)

import _census_blob_common as cbc  # noqa: E402
from refusal import Refuse  # noqa: E402


# Leaves converted to the shared census_blob / git_blob_sha1 (#493).
CONVERTED_CENSUS_BLOB = {
    "model/integration/extract_preset_inputs.py",
    "model/oscillators/classic/extract_inputs.py",
    "model/oscillators/sine/extract_inputs.py",
    "model/voice/extract_inputs.py",
    "model/voice/extract_inputs_v2.py",
    "model/voice/extract_kt_inputs.py",
    "model/voice/extract_lfo_inputs.py",
    "model/voice/extract_mw_inputs.py",
    "model/voice/extract_slfo_inputs.py",
    "model/voice/extract_uni_inputs.py",
    "model/voice/playmode/extract_inputs.py",
    "model/voice/render_uni_reference.py",
    "tools/render_leaf48_reference.py",
    "tools/audit_effect_settle_boundaries.py",
}

# Leaves converted to the shared graphs_entry (#633). The fourteen that held a
# private copy; thirteen were byte-identical once the parameter name was
# normalized and tools/extract_distortion_inputs.py had already drifted.
CONVERTED_GRAPHS_ENTRY = {
    "model/oscillators/classic/extract_inputs.py",
    "model/oscillators/sine/extract_inputs.py",
    "model/voice/extract_inputs.py",
    "model/voice/extract_inputs_v2.py",
    "model/voice/extract_lfo_inputs.py",
    "model/voice/extract_slfo_inputs.py",
    "model/voice/extract_uni_inputs.py",
    "model/voice/playmode/extract_inputs.py",
    "tools/extract_distortion_inputs.py",
    "tools/extract_rf_ains34_inputs.py",
    "tools/extract_rf_bins12_inputs.py",
    "tools/extract_rf_global2_inputs.py",
    "tools/extract_rf_global34_inputs.py",
    "tools/extract_rf_send34_inputs.py",
}


def _files_defining(pattern):
    """Tracked *.py files with a module-level definition matching pattern."""
    return set(subprocess.run(
        ["git", "grep", "-l", "-E", pattern, "--", "*.py"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.split())


def _first_row():
    with open(cbc.CENSUS_CSV, newline="", encoding="utf-8") as f:
        return next(csv.DictReader(f))


def test_census_blob_known_preset():
    row = _first_row()
    assert cbc.census_blob(row["path"]) == row["git_blob_sha1"]


def test_census_blob_unknown_preset_refuses():
    """Negative control: an unknown path must raise Refuse, never return None."""
    with pytest.raises(Refuse):
        cbc.census_blob("no/such/preset.fxp")


def _first_graph():
    with open(cbc.GRAPHS, encoding="utf-8") as f:
        return json.loads(f.readline())


def test_graphs_entry_known_preset():
    graph = _first_graph()
    assert cbc.graphs_entry(graph["p"]) == graph


def test_graphs_entry_unknown_preset_refuses():
    """Negative control: an unknown path must raise Refuse, never return None."""
    with pytest.raises(Refuse):
        cbc.graphs_entry("no/such/preset.fxp")


def test_git_blob_sha1_matches_git():
    path = os.path.join(REPO, "refusal.py")
    expected = subprocess.check_output(["git", "hash-object", path], text=True).strip()
    assert cbc.git_blob_sha1(path) == expected


def test_no_local_copies_in_converted_leaves():
    """The converted leaves import the shared helpers instead of defining them.

    One leg per helper family so a reintroduced private copy names the helper
    it drifted from, not just the file.
    """
    for pattern, converted in (
        (r"^def (census_blob|git_blob_sha1)\b", CONVERTED_CENSUS_BLOB),
        (r"^def graphs_entry\b", CONVERTED_GRAPHS_ENTRY),
    ):
        offenders = converted & _files_defining(pattern)
        assert not offenders, (
            f"private copy of {pattern} reintroduced in {sorted(offenders)}")
