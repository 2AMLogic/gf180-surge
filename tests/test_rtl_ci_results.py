"""Failure controls for tools/check_rtl_ci_results.py (synthetic JUnit XML).

Skip-policy controls (#345) plus required-case coverage controls (#356): a
committed inventory of simulator-dependent pytest node IDs must be present
in the pytest collection and executed (not skipped) in the JUnit report.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_rtl_ci_results.py"
INVENTORY = ROOT / "tests" / "rtl_sim_required_cases.txt"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"

# Synthetic required cases: a plain function, a class method, and two
# parameter ids of one function (stable identity per parameter).
REQ = [
    "tests/test_fake_sim.py::test_rtl_exact",
    "tests/test_fake_sim.py::TestMutant::test_caught",
    "tests/test_fake_sim.py::test_matcher[lp12]",
    "tests/test_fake_sim.py::test_matcher[lp24]",
]
UNRELATED = "tests/test_other.py::test_a"


def _case(nodeid: str, body: str = "") -> str:
    path, br, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += br + params
    cls, name = ".".join(names[:-1]), names[-1]
    return f'<testcase classname="{cls}" name="{name}">{body}</testcase>'


def _skipped(reason: str) -> str:
    return f'<skipped type="pytest.skip" message="{reason}"/>'


def _xml(cases: str) -> str:
    return f'<?xml version="1.0"?><testsuites><testsuite name="p">{cases}</testsuite></testsuites>'


def _all_required(**override) -> str:
    return "".join(_case(n, override.get(n, "")) for n in REQ)


PASS = _case(UNRELATED)


def _collected(ids) -> str:
    return "\n".join(ids) + f"\n\n{len(ids)} tests collected in 0.01s\n"


def run(tmp_path, content, inventory=None, collected=None, extra=()):
    p = tmp_path / "r.xml"
    if content is not None:
        p.write_text(content)
    inv = tmp_path / "inv.txt"
    inv.write_text("# synthetic\n" + "\n".join(REQ if inventory is None else inventory) + "\n")
    col = tmp_path / "collected.txt"
    col.write_text(_collected(REQ + [UNRELATED] if collected is None else collected))
    return subprocess.run(
        [sys.executable, "-I", str(TOOL), str(p),
         "--inventory", str(inv), "--collected", str(col), *extra],
        capture_output=True, text=True,
    )


# ------------------------------------------------ skip policy (#345)

def test_clean_pass(tmp_path):
    r = run(tmp_path, _xml(PASS + _all_required()))
    assert r.returncode == 0, r.stderr
    assert "simulator-dependent skipped: 0" in r.stdout
    for line in ("required: 4", "required in collection: 4",
                 "required present in report: 4", "required executed: 4",
                 "required skipped: 0", "required missing: 0"):
        assert line in r.stdout


@pytest.mark.parametrize(
    "reason", ["iverilog not installed", "IVerilog missing", "need VVP", "no Icarus vvp"]
)
def test_simulator_skip_fails(tmp_path, reason):
    r = run(tmp_path, _xml(PASS + _all_required() + _case("tests/test_x.py::s", _skipped(reason))))
    assert r.returncode == 1 and "simulator-dependent skip" in r.stderr


def test_unrelated_skip_is_not_run_but_passes(tmp_path):
    """Acceptance 4 (second half): an unrelated oracle skip stays NOT_RUN and
    does not by itself fail the coverage gate."""
    skip = _case("tests/test_x.py::s", _skipped("needs oracle host"))
    r = run(tmp_path, _xml(PASS + _all_required() + skip))
    assert r.returncode == 0, r.stderr
    assert "NOT_RUN (unrelated skip)" in r.stdout and "skipped: 1" in r.stdout


def test_missing_report_fails(tmp_path):
    assert run(tmp_path, None).returncode == 1


def test_malformed_report_fails(tmp_path):
    assert run(tmp_path, "<testsuites><oops").returncode == 1


def test_wrong_root_fails(tmp_path):
    assert run(tmp_path, "<html/>").returncode == 1


def test_zero_collected_fails(tmp_path):
    r = run(tmp_path, _xml(""))
    assert r.returncode == 1 and "zero tests" in r.stderr


def test_failed_case_not_counted_as_skip(tmp_path):
    """Agreement is pytest's exit status, not this gate: a failed required
    case is present and executed for coverage (acceptance 6 is the CI step's
    independent pytest status, see tests/test_rtl_ci_step_errexit.py)."""
    fail = '<failure message="x"/>'
    r = run(tmp_path, _xml(_all_required(**{REQ[0]: fail})))
    assert r.returncode == 0, r.stderr
    assert "executed (not skipped): 4" in r.stdout
    assert "required executed: 4" in r.stdout


# ------------------------------------------- required coverage (#356)

@pytest.mark.parametrize("dropped", REQ)
def test_removed_required_case_fails_and_is_named(tmp_path, dropped):
    """Acceptance 2: otherwise-passing report minus one required case."""
    cases = "".join(_case(n) for n in REQ if n != dropped)
    r = run(tmp_path, _xml(PASS + cases))
    assert r.returncode == 1
    assert f"required case missing from JUnit report: {dropped}" in r.stderr
    assert "required missing: 1" in r.stdout
    assert "simulator-dependent skipped: 0" in r.stdout  # skip policy alone is blind


def test_only_unrelated_passing_case_fails(tmp_path):
    """Acceptance 3: a single unrelated passing case no longer suffices."""
    r = run(tmp_path, _xml(PASS))
    assert r.returncode == 1
    assert "required missing: 4" in r.stdout
    assert r.stderr.count("required case missing from JUnit report") == 4


def test_only_unrelated_case_fails_against_committed_inventory(tmp_path):
    """Acceptance 3 with the real default inventory (no --inventory)."""
    p = tmp_path / "r.xml"
    p.write_text(_xml(PASS))
    col = tmp_path / "c.txt"
    col.write_text(_collected([UNRELATED]))
    r = subprocess.run([sys.executable, "-I", str(TOOL), str(p), "--collected", str(col)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "stale inventory entry" in r.stderr
    assert "required case missing from JUnit report" in r.stderr


@pytest.mark.parametrize("reason", ["oracle host unavailable", "flaky on CI", ""])
def test_required_case_skipped_without_sim_words_fails(tmp_path, reason):
    """Acceptance 4: the skip reason's spelling is irrelevant for required cases."""
    r = run(tmp_path, _xml(PASS + _all_required(**{REQ[1]: _skipped(reason)})))
    assert r.returncode == 1
    assert f"required case skipped: {REQ[1]}" in r.stderr
    assert "required skipped: 1" in r.stdout
    assert "simulator-dependent skipped: 0" in r.stdout


def test_xfail_of_required_case_fails(tmp_path):
    xf = '<skipped type="pytest.xfail" message="expected"/>'
    r = run(tmp_path, _xml(_all_required(**{REQ[0]: xf})))
    assert r.returncode == 1 and f"required case skipped: {REQ[0]}" in r.stderr


def test_renamed_test_leaves_stale_entry_that_fails(tmp_path):
    """Acceptance 5: the test was renamed in collection (and so in the
    report) but the inventory was not updated."""
    renamed = "tests/test_fake_sim.py::test_rtl_exact_v2"
    ids = [renamed if n == REQ[0] else n for n in REQ]
    r = run(tmp_path, _xml("".join(_case(n) for n in ids)), collected=ids)
    assert r.returncode == 1
    assert f"stale inventory entry (not in pytest collection): {REQ[0]}" in r.stderr


def test_excluded_from_collection_fails_even_if_report_has_it(tmp_path):
    """Acceptance 5: collection and report must both agree with the inventory."""
    ids = [n for n in REQ if n != REQ[2]] + [UNRELATED]
    r = run(tmp_path, _xml(PASS + _all_required()), collected=ids)
    assert r.returncode == 1
    assert f"stale inventory entry (not in pytest collection): {REQ[2]}" in r.stderr
    assert "required in collection: 3" in r.stdout


def test_parameter_ids_are_matched_exactly(tmp_path):
    """Parameterized identity: lp24 does not satisfy lp12, and a new param id
    in the report is not silently accepted in place of an inventoried one."""
    ids = [n for n in REQ if not n.endswith("[lp12]")] + ["tests/test_fake_sim.py::test_matcher[lpmoog]"]
    r = run(tmp_path, _xml("".join(_case(n) for n in ids)))
    assert r.returncode == 1
    assert "required case missing from JUnit report: tests/test_fake_sim.py::test_matcher[lp12]" in r.stderr
    assert "required executed: 3" in r.stdout


def test_parameter_id_with_dots_and_slashes(tmp_path):
    nid = "tests/test_fake_sim.py::test_p[a.b/c-1::x]"
    r = run(tmp_path, _xml(_case(nid)), inventory=[nid], collected=[nid])
    assert r.returncode == 0, r.stderr


def test_duplicate_report_testcase_for_required_case_fails(tmp_path):
    r = run(tmp_path, _xml(PASS + _all_required() + _case(REQ[3])))
    assert r.returncode == 1
    assert f"required case appears 2 times in JUnit report: {REQ[3]}" in r.stderr


def test_executed_plus_skipped_duplicate_fails(tmp_path):
    r = run(tmp_path, _xml(_all_required() + _case(REQ[0], _skipped("x"))))
    assert r.returncode == 1 and "appears 2 times" in r.stderr


def test_duplicate_inventory_entry_fails(tmp_path):
    r = run(tmp_path, _xml(PASS + _all_required()), inventory=REQ + [REQ[0]])
    assert r.returncode == 1 and "duplicate inventory entry" in r.stderr
    assert "NO_VERDICT" in r.stdout


@pytest.mark.parametrize("bad", [
    "test_fake_sim.py::test_rtl_exact",            # not under tests/
    "tests/test_fake_sim.py",                       # no test name
    "tests/test_fake_sim.py::test a",               # whitespace
    "tests/test_fake_sim::test_rtl_exact",          # not a .py path
    "tests/test_fake_sim.py::test_*",               # wildcard
    "tests.test_fake_sim::test_rtl_exact",          # JUnit form, not a node ID
])
def test_malformed_inventory_entry_fails(tmp_path, bad):
    r = run(tmp_path, _xml(PASS + _all_required()), inventory=REQ + [bad])
    assert r.returncode == 1 and "malformed inventory entry" in r.stderr


def test_empty_inventory_fails(tmp_path):
    r = run(tmp_path, _xml(PASS + _all_required()), inventory=[])
    assert r.returncode == 1 and "inventory is empty" in r.stderr


def test_missing_collection_listing_fails(tmp_path):
    p = tmp_path / "r.xml"
    p.write_text(_xml(PASS + _all_required()))
    inv = tmp_path / "inv.txt"
    inv.write_text("\n".join(REQ) + "\n")
    r = subprocess.run([sys.executable, "-I", str(TOOL), str(p), "--inventory", str(inv),
                        "--collected", str(tmp_path / "nope.txt")],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "collection listing unreadable" in r.stderr


def test_collection_listing_without_ids_fails(tmp_path):
    r = run(tmp_path, _xml(PASS + _all_required()), collected=[])
    assert r.returncode == 1 and "no node IDs" in r.stderr


def test_duplicate_collected_id_fails(tmp_path):
    r = run(tmp_path, _xml(PASS + _all_required()), collected=REQ + REQ[:1] + [UNRELATED])
    assert r.returncode == 1 and "duplicate node ID in collection listing" in r.stderr


def test_ambiguous_identity_fails(tmp_path):
    """tests/a/b.py::t and tests/a.b.py::t mangle to the same JUnit identity;
    the gate refuses to guess which one the report row belongs to."""
    req = "tests/a/b.py::test_t"
    other = "tests/a.b.py::test_t"
    r = run(tmp_path, _xml(_case(req)), inventory=[req], collected=[req, other])
    assert r.returncode == 1 and "ambiguous JUnit identity" in r.stderr


def test_collected_option_is_mandatory(tmp_path):
    p = tmp_path / "r.xml"
    p.write_text(_xml(PASS))
    r = subprocess.run([sys.executable, "-I", str(TOOL), str(p)], capture_output=True, text=True)
    assert r.returncode != 0 and "--collected" in r.stderr


# ------------------------------------ committed inventory and CI wiring

def _inventory_entries():
    return [ln.strip() for ln in INVENTORY.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def test_committed_inventory_is_well_formed():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import check_rtl_ci_results as c
    finally:
        sys.path.pop(0)
    entries, errors = c.load_inventory(str(INVENTORY))
    assert not errors
    assert entries == _inventory_entries()
    assert len(entries) >= 1


def test_committed_inventory_matches_live_collection():
    """A rename/removal of an inventoried test fails here in every pytest
    job, not only in rtl-sim (collection does not need the simulator)."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    collected = {ln.strip() for ln in r.stdout.splitlines() if "::" in ln}
    stale = [e for e in _inventory_entries() if e not in collected]
    assert not stale, f"stale inventory entries: {stale}"


def test_ci_step_passes_inventory_and_collection():
    text = CI_YML.read_text()
    assert "pytest --collect-only -q -p no:cacheprovider tests > rtl-sim-collected.txt" in text
    assert "--inventory tests/rtl_sim_required_cases.txt" in text
    assert "--collected rtl-sim-collected.txt" in text
    # Collection must precede the gated run so the checker sees it.
    assert text.index("> rtl-sim-collected.txt") < text.index("--junitxml=rtl-sim-junit.xml")
