"""Failure control for tools/check_slow_controls_results.py (#415, #463).

A skipped LIVE slow control (the NC_LIVE_SLOW unset shape) must turn the gate
red; a skipped needs-oracle control must not; a missing case must fail.
#463: required cases are matched by full JUnit (classname, name) identity and
must appear exactly once -- a skipped-then-passing duplicate pair, a passing
same-name testcase from another module, and an unsupported report root must
all fail, exercised through the real XML parser and CLI, independently of
report order.
"""
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_slow_controls_results as g  # noqa: E402

REG = json.loads((ROOT / "tests" / "negative_controls_registry.json").read_text())
CLS = g.EXPECTED_CLASSNAME


# ---- synthetic JUnit builders (pytest's emitted shape) ----

def _healthy_entries():
    """Ordered (classname, name, kind) testcase records of a healthy report.

    kind: "pass" (executed, no result element), "skip", "fail".
    """
    entries = [(CLS, f"{g.EXEC}[{n}]", "pass" if e["status"] == "LIVE" else "skip")
               for n, e in sorted(REG["scripts"].items())]
    entries.append((CLS, g.BUDGET, "pass"))
    return entries


def _write_report(path: Path, entries, root_tag="testsuites") -> Path:
    root = ET.Element(root_tag)
    suite = ET.SubElement(root, "testsuite", name="pytest", tests=str(len(entries)))
    for cls, name, kind in entries:
        tc = ET.SubElement(suite, "testcase", classname=cls, name=name)
        if kind == "skip":
            ET.SubElement(tc, "skipped", type="pytest.skip",
                          message="NOT_RUN (synthetic; not a pass)")
        elif kind == "fail":
            ET.SubElement(tc, "failure", message="synthetic failure")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _retype(entries, name, kind):
    return [(c, n, kind if n == name else k) for c, n, k in entries]


def _reclass(entries, name, cls):
    return [(cls if n == name else c, n, k) for c, n, k in entries]


def _drop(entries, name):
    return [(c, n, k) for c, n, k in entries if n != name]


def _exec_name(script):
    return f"{g.EXEC}[{script}]"


def _parse(tmp_path, entries, root_tag="testsuites"):
    path = _write_report(tmp_path / "junit.xml", entries, root_tag)
    return g._records(path)


def _cli(path: Path):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_slow_controls_results.py"),
         str(path)], capture_output=True, text=True)


# ---- healthy acceptance case ----

def test_healthy_report_passes(tmp_path):
    lines, bad = g.evaluate(REG, _parse(tmp_path, _healthy_entries()))
    assert bad == []
    live_pass = [l for l in lines if l.startswith("LIVE") and "PASS" in l]
    assert len(live_pass) == sum(1 for e in REG["scripts"].values()
                                 if e["status"] == "LIVE") + 1  # + budget control


def test_cli_healthy_report_exits_zero(tmp_path):
    path = _write_report(tmp_path / "junit.xml", _healthy_entries())
    r = _cli(path)
    assert r.returncode == 0, r.stderr
    assert "PASS: every LIVE control" in r.stdout


# ---- existing skip/missing semantics, through the real parser ----

def test_skipped_slow_control_fails(tmp_path):
    entries = _retype(_healthy_entries(),
                      _exec_name("chorus_negative_controls.py"), "skip")
    assert g.evaluate(REG, _parse(tmp_path, entries))[1]


def test_skipped_budget_noop_fails(tmp_path):
    entries = _retype(_healthy_entries(), g.BUDGET, "skip")
    assert g.evaluate(REG, _parse(tmp_path, entries))[1]


def test_missing_case_fails(tmp_path):
    entries = _drop(_healthy_entries(),
                    _exec_name("reverb_negative_controls.py"))
    assert g.evaluate(REG, _parse(tmp_path, entries))[1]


def test_needs_oracle_skip_allowed_not_counted_pass(tmp_path):
    lines, bad = g.evaluate(REG, _parse(tmp_path, _healthy_entries()))
    assert bad == []
    assert any(l.startswith("NOT_RUN") and "needs-oracle" in l for l in lines)
    assert not any("PASS" in l and "needs-oracle" in l for l in lines)


def test_missing_or_skipped_sxt025_integration_case_fails(tmp_path):
    key = _exec_name("model/integration/negative_controls.py")
    healthy = _healthy_entries()
    assert any(n == key for _, n, _ in healthy), \
        "registry must carry the SXT-025 integration row"
    assert g.evaluate(REG, _parse(tmp_path, _retype(healthy, key, "skip")))[1]
    assert g.evaluate(REG, _parse(tmp_path, _drop(healthy, key)))[1]


def test_failed_live_control_fails(tmp_path):
    entries = _retype(_healthy_entries(),
                      _exec_name("conditioner_negative_controls.py"), "fail")
    assert g.evaluate(REG, _parse(tmp_path, entries))[1]


# ---- #463: duplicate required identities are rejected, order-independently ----

def _with_duplicate(entries, name, extra_kind):
    """Insert one extra record for `name` before (extra_kind="skip") or after
    (extra_kind="pass") the existing passing record."""
    out = []
    for rec in entries:
        if rec[1] == name and extra_kind == "skip":
            out.append((rec[0], rec[1], "skip"))
        out.append(rec)
        if rec[1] == name and extra_kind == "pass":
            out.append((rec[0], rec[1], "pass"))
    return out


@pytest.mark.parametrize("extra_kind", ["skip", "pass"])
def test_duplicate_required_identity_fails_both_orders(tmp_path, extra_kind):
    key = _exec_name("chorus_negative_controls.py")
    entries = _with_duplicate(_healthy_entries(), key, extra_kind)
    lines, bad = g.evaluate(REG, _parse(tmp_path, entries))
    assert bad
    assert any("AMBIGUOUS" in l for l in lines)


@pytest.mark.parametrize("extra_kind", ["skip", "pass"])
def test_duplicate_required_identity_fails_via_cli(tmp_path, extra_kind):
    key = _exec_name("chorus_negative_controls.py")
    entries = _with_duplicate(_healthy_entries(), key, extra_kind)
    r = _cli(_write_report(tmp_path / "junit.xml", entries))
    assert r.returncode != 0, r.stdout
    assert "AMBIGUOUS" in r.stdout


# ---- #463: a same-name testcase from another module never satisfies ----

def test_wrong_classname_same_name_fails(tmp_path):
    key = _exec_name("chorus_negative_controls.py")
    entries = _reclass(_healthy_entries(), key, "tests.other_module")
    lines, bad = g.evaluate(REG, _parse(tmp_path, entries))
    assert bad and any("chorus_negative_controls.py" in b for b in bad)
    assert any("tests.other_module" in l for l in lines)


def test_wrong_classname_same_name_fails_via_cli(tmp_path):
    key = _exec_name("chorus_negative_controls.py")
    entries = _reclass(_healthy_entries(), key, "tests.other_module")
    r = _cli(_write_report(tmp_path / "junit.xml", entries))
    assert r.returncode != 0, r.stdout
    assert "tests.other_module" in r.stdout


# ---- #463: unsupported JUnit root is refused ----

def test_unsupported_xml_root_refused_by_parser(tmp_path):
    with pytest.raises(g.ReportError):
        _parse(tmp_path, _healthy_entries(), root_tag="report")


def test_unsupported_xml_root_refused_via_cli(tmp_path):
    path = _write_report(tmp_path / "junit.xml", _healthy_entries(),
                         root_tag="report")
    r = _cli(path)
    assert r.returncode != 0
    assert "root" in (r.stdout + r.stderr)
