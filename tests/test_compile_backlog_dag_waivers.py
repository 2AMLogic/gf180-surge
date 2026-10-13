"""#409 -- PASS-with-non-PASS-prerequisite monotonicity rule of the DAG check.

Pins: validate() rejects a PASS node with a non-PASS prerequisite unless it
carries a scoped prerequisite_waivers entry, and rejects stale, misdirected
and empty-reason waivers (live negative controls on copies of docs/dag.json).
Does NOT establish any fidelity, synthesis or hardware claim; board
bookkeeping only.
"""

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import compile_backlog_dag as cbd  # noqa: E402


@pytest.fixture()
def dag():
    return copy.deepcopy(cbd.load_dag(cbd.DAG_PATH))


def _node(dag, node_id):
    return next(n for n in dag["nodes"] if n["id"] == node_id)


def _fail(dag):
    with pytest.raises(cbd.ValidationError) as exc:
        cbd.validate(dag)
    return str(exc.value)


def test_committed_dag_validates(dag):
    cbd.validate(dag)


def test_every_waived_node_is_pass_with_nonpass_prereq(dag):
    by_id = {n["id"]: n for n in dag["nodes"]}
    waived = [n for n in dag["nodes"] if n.get("prerequisite_waivers")]
    assert {n["id"] for n in waived} == {13, 14, 15, 17, 20, 21, 22}
    for n in waived:
        assert n["status"] == "PASS"
        for w in n["prerequisite_waivers"]:
            assert by_id[w["node"]]["status"] != "PASS"


def test_nc_a_missing_waiver_fails_naming_node_and_prerequisite(dag):
    del _node(dag, 22)["prerequisite_waivers"]
    msg = _fail(dag)
    assert "node 22" in msg and "prerequisite 18" in msg


def test_nc_a_partial_waivers_fail(dag):
    n = _node(dag, 21)
    n["prerequisite_waivers"] = [w for w in n["prerequisite_waivers"] if w["node"] != 16]
    msg = _fail(dag)
    assert "node 21" in msg and "prerequisite 16" in msg


def test_nc_b_waiver_naming_pass_prerequisite_fails(dag):
    n = _node(dag, 13)
    pass_dep = next(
        d for d in _node(dag, 20)["depends_on"] if _node(dag, d)["status"] == "PASS"
    )
    n["depends_on"].append(pass_dep)
    n["prerequisite_waivers"].append({"node": pass_dep, "reason": "x"})
    msg = _fail(dag)
    assert "node 13" in msg and "stale waiver" in msg


def test_nc_c_empty_reason_fails(dag):
    _node(dag, 22)["prerequisite_waivers"][0]["reason"] = "  "
    msg = _fail(dag)
    assert "node 22" in msg and "non-empty 'reason'" in msg


def test_waiver_for_non_dependency_fails(dag):
    _node(dag, 22)["prerequisite_waivers"].append({"node": 12, "reason": "x"})
    msg = _fail(dag)
    assert "node 22" in msg and "not in depends_on" in msg


def test_waiver_on_non_pass_node_fails(dag):
    blocked = next(n for n in dag["nodes"] if n["status"] == "BLOCKED")
    blocked["prerequisite_waivers"] = []
    assert "only valid on PASS nodes" in _fail(dag)


def test_waived_edges_render_distinctly(dag):
    by_id = cbd.validate(dag)
    assert "PASS (waived: #12)" in cbd.node_table(by_id)
    graph = cbd.mermaid_graph(by_id)
    assert "n12 -.-> n13" in graph
    assert "n12 --> n13" not in graph
