#!/usr/bin/env python3
"""#434 -- static RTL lint gate: checker behaviour and failure controls.

PINS: inventory completeness / duplicates / stale / unclassified detection,
argv quoting for paths with spaces, diagnostic parsing and full-multiset
comparison, waiver schema (no wildcard, severe review decision), tool pin
refusal (NOT_RUN, zero groups), and status/exit behaviour.  Tests that need the
real pinned lint tool are skipped (NOT_RUN, reason printed by -rs) when it is
absent; they are never counted as a pass of the lint gate.

DOES NOT: establish synthesis/FPGA/gf180mcu qualification, RTL-vs-model
exactness, model-vs-Surge agreement or preset quality.
"""
import copy
import importlib.util
import json
import os
import shutil
import stat
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "check_rtl_lint", os.path.join(REPO, "tools", "check_rtl_lint.py"))
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)

MANIFEST = os.path.join(REPO, "rtl", "lint_manifest.json")
WAIVERS = os.path.join(REPO, "rtl", "lint_waivers.json")


def _real_tool():
    path = shutil.which("verilator")
    if not path:
        return None
    try:
        lint.probe_tool(path)
    except lint.Refusal:
        return None
    return path


REAL = _real_tool()
needs_real = pytest.mark.skipif(
    REAL is None, reason="NOT_RUN: pinned verilator %s unavailable"
    % lint.PINNED_VERSION)


def _load(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _fake_tool(tmp_path, body, name="verilator"):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


def _mini_repo(tmp_path, files):
    """A real git repo with the given {relpath: text} tracked."""
    r = tmp_path / "repo"
    for rel, txt in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(txt)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    return str(r)


def _mf(files, groups=()):
    return {"schema": 1, "files": [{"path": p, "class": c}
                                   for p, c in files],
            "groups": [{"id": t, "source": s, "top": t, "dependencies": [],
                        "include_dirs": [], "defines": [],
                        "parameter_overrides": []} for s, t in groups]}


# ---------------------------------------------------------------- inventory

def test_committed_manifest_matches_tracked_files():
    groups, cls = lint.validate_manifest(_load(MANIFEST),
                                         lint.tracked_sv(REPO))
    assert len(groups) == 11
    assert sorted(set(cls.values())) == sorted(lint.CLASSES)
    assert sum(1 for v in cls.values() if v == "product") == 11


@pytest.mark.parametrize("mutate,needle", [
    (lambda m: m["files"].append(dict(m["files"][0])), "duplicate manifest"),
    (lambda m: m["files"].append({"path": "rtl/gone.sv",
                                  "class": "testbench"}), "stale manifest"),
    (lambda m: m["files"].pop(0), "unclassified tracked file"),
    (lambda m: m["files"][0].update({"class": "bogus"}), "unknown class"),
    (lambda m: m["groups"].pop(), "product file in no lint group"),
    (lambda m: m["groups"][0].update({"defines": ["X=1"]}), "must be empty"),
])
def test_inventory_refusals(mutate, needle):
    m = _load(MANIFEST)
    mutate(m)
    with pytest.raises(lint.Refusal) as ei:
        lint.validate_manifest(m, lint.tracked_sv(REPO))
    assert ei.value.stage == "inventory"
    assert any(needle in r for r in ei.value.reasons), ei.value.reasons


def test_group_source_must_be_product():
    m = _load(MANIFEST)
    tb = next(f["path"] for f in m["files"] if f["class"] == "testbench")
    m["groups"][0]["source"] = tb
    with pytest.raises(lint.Refusal) as ei:
        lint.validate_manifest(m, lint.tracked_sv(REPO))
    assert any("not classified product" in r for r in ei.value.reasons)


def test_unclassified_new_file_fails_at_inventory_stage(tmp_path):
    repo = _mini_repo(tmp_path, {"rtl/a.sv": "module a; endmodule\n",
                                 "rtl/new_core.sv": "module n; endmodule\n"})
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(_mf([("rtl/a.sv", "testbench")])))
    rep = lint.run_check(repo, str(mp), WAIVERS, "/nonexistent/verilator")
    assert (rep["status"], rep["stage"]) == ("FAIL", "inventory")
    assert "unclassified tracked file: rtl/new_core.sv" in rep["reasons"]
    assert rep["classification_coverage"]["status"] == "FAIL"
    assert rep["diagnostic_agreement"]["status"] == "NOT_RUN"
    assert rep["groups_executed"] == 0


def test_name_is_never_used_to_classify(tmp_path):
    # a file named like a testbench is still unclassified until listed
    repo = _mini_repo(tmp_path, {"rtl/tb_x.sv": "module tb_x; endmodule\n"})
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(_mf([])))
    rep = lint.run_check(repo, str(mp), WAIVERS, "/nonexistent/verilator")
    assert rep["stage"] == "inventory" and rep["status"] == "FAIL"


def test_malformed_manifest_fails(tmp_path):
    mp = tmp_path / "m.json"
    mp.write_text("{not json")
    rep = lint.run_check(REPO, str(mp), WAIVERS, "/nonexistent/verilator")
    assert (rep["status"], rep["stage"]) == ("FAIL", "inventory")
    assert lint.EXIT[rep["status"]] == 1


# ------------------------------------------------------------------ waivers

def _groups():
    return _load(MANIFEST)["groups"]


def test_committed_waivers_validate_and_are_exact_entries():
    w = lint.validate_waivers(_load(WAIVERS), _groups())
    assert len(w) == 776
    assert all(e["verilator_version"] == "5.050" for e in w.values())
    sev = [e for e in w.values() if e["rule"] in lint.SEVERE_RULES]
    assert len(sev) == 82
    assert all(e["review_decision"]["status"] in lint.REVIEW_STATUSES
               for e in sev)


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d["waivers"][0].update({"source": "rtl/*.sv"}), "wildcard"),
    (lambda d: d["waivers"][0].update({"rule": "WIDTH*"}), "wildcard"),
    (lambda d: d["waivers"].append(copy.deepcopy(d["waivers"][0])),
     "duplicate waiver"),
    (lambda d: d["waivers"][0].update({"count": 0}), "positive integer"),
    (lambda d: d["waivers"][0].update({"explanation": ""}), "explanation"),
    (lambda d: d["waivers"][0].update({"line": 9999}), "fingerprint does not"),
    (lambda d: d["waivers"][0].pop("source_sha256"), "bad keys"),
    (lambda d: d.update({"verilator_version": "5.048"}), "!= pinned"),
    (lambda d: d["waivers"][0].update({"source": "rtl/other.sv"}),
     "file-wide/other-file"),
    (lambda d: d["waivers"][0].update({"group": "nope"}), "unknown group"),
])
def test_waiver_schema_refusals(mutate, needle):
    d = _load(WAIVERS)
    mutate(d)
    with pytest.raises(lint.Refusal) as ei:
        lint.validate_waivers(d, _groups())
    assert ei.value.stage == "waivers"
    assert any(needle in r for r in ei.value.reasons), ei.value.reasons


def test_severe_waiver_needs_review_decision():
    d = _load(WAIVERS)
    i = next(i for i, e in enumerate(d["waivers"])
             if e["rule"] in lint.SEVERE_RULES)
    del d["waivers"][i]["review_decision"]
    with pytest.raises(lint.Refusal) as ei:
        lint.validate_waivers(d, _groups())
    assert any("needs review_decision" in r for r in ei.value.reasons)
    d = _load(WAIVERS)
    d["waivers"][i]["review_decision"]["status"] = "auto_granted"
    with pytest.raises(lint.Refusal):
        lint.validate_waivers(d, _groups())


def test_review_decision_on_nonsevere_rejected():
    d = _load(WAIVERS)
    i = next(i for i, e in enumerate(d["waivers"])
             if e["rule"] not in lint.SEVERE_RULES)
    d["waivers"][i]["review_decision"] = {
        "status": "approved", "reviewer": "x", "reference": "y"}
    with pytest.raises(lint.Refusal):
        lint.validate_waivers(d, _groups())


# ------------------------------------------------- parsing and comparison

SAMPLE = (
    "%Warning-LATCH: rtl/a.sv:5:3: Latch inferred for signal 'a.q'\n"
    "                    : ... note\n"
    "  5 | code\n"
    "%Warning-WIDTHTRUNC: rtl/a.sv:9:1: Bit extraction\n"
    "%Warning-WIDTHTRUNC: rtl/a.sv:9:1: Bit extraction\n")


def test_parse_diagnostics_and_multiset_counts(tmp_path):
    diags, errs = lint.parse_diagnostics(SAMPLE, "rtl/a.sv")
    assert errs == [] and len(diags) == 3
    assert [d["rule"] for d in diags] == ["LATCH", "WIDTHTRUNC", "WIDTHTRUNC"]


@pytest.mark.parametrize("text", [
    "%Error: rtl/a.sv:1:1: syntax error",
    "%Error-UNSUPPORTED: rtl/a.sv:1:1: unsupported",
    "%Warning-FOO: no location here",
    "%Warning: rule-less warning rtl/a.sv:1:1: x",
    "%garbage",
])
def test_parse_errors_cannot_be_waived(text):
    diags, errs = lint.parse_diagnostics(text, "rtl/a.sv")
    assert errs and diags == []


def _og(gid, rows, sha="a" * 64):
    ds = []
    for rule, line, col, msg, cnt in rows:
        ds.append({"rule": rule, "file": "rtl/a.sv", "line": line, "col": col,
                   "message": msg, "count": cnt,
                   "fingerprint": lint.fingerprint(rule, "rtl/a.sv", line,
                                                   col, msg)})
    return {"id": gid, "source_sha256": sha, "diagnostics": ds}


def _w(gid, rule, line, col, msg, cnt, sha="a" * 64, review=None):
    e = {"group": gid, "rule": rule, "source": "rtl/a.sv", "line": line,
         "col": col, "message": msg, "count": cnt, "source_sha256": sha,
         "fingerprint": lint.fingerprint(rule, "rtl/a.sv", line, col, msg)}
    if rule in lint.SEVERE_RULES:
        e["review_decision"] = review or {"status": "approved"}
    return (gid, e["fingerprint"]), e


def test_compare_exact_match_is_clean():
    og = _og("a", [("WIDTHTRUNC", 9, 1, "m", 2)])
    fails, st = lint.compare([og], dict([_w("a", "WIDTHTRUNC", 9, 1, "m", 2)]))
    assert fails == [] and st["observed_diagnostics"] == 2


@pytest.mark.parametrize("obs_n,w_n,needle", [
    (3, 2, "count increased 2 -> 3"),
    (1, 2, "count decreased 2 -> 1"),
])
def test_compare_count_changes_fail(obs_n, w_n, needle):
    og = _og("a", [("WIDTHTRUNC", 9, 1, "m", obs_n)])
    fails, _ = lint.compare([og], dict([_w("a", "WIDTHTRUNC", 9, 1, "m",
                                           w_n)]))
    assert any(needle in f for f in fails)


def test_compare_new_stale_and_hash_drift():
    og = _og("a", [("LATCH", 5, 3, "fresh", 1)])
    w = dict([_w("a", "WIDTHTRUNC", 9, 1, "old", 1, sha="b" * 64)])
    fails, _ = lint.compare([og], w)
    assert any(f.startswith("new SEVERE diagnostic") for f in fails)
    assert any(f.startswith("stale waiver") for f in fails)
    assert any(f.startswith("source hash drift") for f in fails)


def test_latch_control_fails_without_any_latch_waiver():
    # Baseline with no LATCH waiver (as after #480): the new-severe-latch
    # control must still produce a new SEVERE LATCH failure, not abort.
    og = _og("a", [("WIDTHTRUNC", 9, 1, "m", 1)])
    og["source"] = "rtl/a.sv"
    ws = [_w("a", "WIDTHTRUNC", 9, 1, "m", 1)[1]]
    obs, ws2, how = lint.latch_control_case([og], ws)
    assert "no LATCH waiver" in how
    fails, _ = lint.compare(obs, {(w["group"], w["fingerprint"]): w
                                  for w in ws2})
    assert any(f.startswith("new SEVERE diagnostic") and " LATCH " in f
               for f in fails)
    # the unmodified baseline is clean, so the failure is the injection's
    clean, _ = lint.compare([og], {(w["group"], w["fingerprint"]): w
                                   for w in ws})
    assert clean == []
    assert len(og["diagnostics"]) == 1  # input not mutated


def test_latch_control_drops_waiver_when_one_exists():
    og = _og("a", [("LATCH", 5, 3, "l", 1)])
    og["source"] = "rtl/a.sv"
    key, w = _w("a", "LATCH", 5, 3, "l", 1)
    obs, ws2, how = lint.latch_control_case([og], [w])
    assert how == "waiver removed" and ws2 == []
    fails, _ = lint.compare(obs, {})
    assert any(f.startswith("new SEVERE diagnostic") for f in fails)


def test_run_group_keeps_spaced_paths_as_single_argv(tmp_path):
    root = tmp_path / "root"
    (root / "rtl" / "type-reverb 2").mkdir(parents=True)
    src = root / "rtl" / "type-reverb 2" / "x core.sv"
    src.write_text("module x; endmodule\n")
    log = tmp_path / "argv.log"
    tool = _fake_tool(tmp_path, 'for a in "$@"; do printf "%%s\\n" "$a"; '
                      'done > %s\n' % log)
    g = {"id": "x", "top": "x", "source": "rtl/type-reverb 2/x core.sv"}
    og = lint.run_group(tool, g, str(root))
    assert og["errors"] == [] and og["argv"][-1] == g["source"]
    assert log.read_text().splitlines()[-1] == g["source"]
    assert log.read_text().splitlines()[:5] == [
        "--lint-only", "--language", "1800-2017", "-Wall", "-Wno-fatal"]
    assert "--bbox-unsup" not in log.read_text()


def test_nonzero_exit_is_error_even_without_diagnostics(tmp_path):
    root = tmp_path / "root"
    (root / "rtl").mkdir(parents=True)
    (root / "rtl" / "x.sv").write_text("module x; endmodule\n")
    tool = _fake_tool(tmp_path, "exit 3\n")
    og = lint.run_group(tool, {"id": "x", "top": "x", "source": "rtl/x.sv"},
                        str(root))
    assert any("exit status 3" in e for e in og["errors"])


# ------------------------------------------------------- tool / status

def test_missing_tool_is_not_run_with_zero_groups():
    rep = lint.run_check(REPO, MANIFEST, WAIVERS, "/nonexistent/verilator")
    assert (rep["status"], rep["stage"]) == ("NOT_RUN", "tool")
    assert rep["groups_executed"] == 0
    assert any("not found" in r for r in rep["reasons"])
    assert rep["classification_coverage"]["status"] == "PASS"
    assert rep["diagnostic_agreement"]["status"] == "NOT_RUN"
    assert lint.EXIT["NOT_RUN"] != 0


def test_wrong_version_is_not_run_with_zero_groups(tmp_path):
    tool = _fake_tool(tmp_path, "echo 'Verilator 5.048 2026-01-01 rev x'\n")
    rep = lint.run_check(REPO, MANIFEST, WAIVERS, tool)
    assert (rep["status"], rep["stage"]) == ("NOT_RUN", "tool")
    assert rep["groups_executed"] == 0
    assert any("wrong verilator version" in r for r in rep["reasons"])


def test_elaboration_error_cannot_pass_even_with_matching_waivers(tmp_path):
    out = tmp_path / "out.txt"
    tool = _fake_tool(tmp_path, (
        'if [ "$1" = "--version" ]; then echo "%s rev fake"; exit 0; fi\n'
        'echo "%%Error: rtl/x.sv:1:1: syntax error"; exit 1\n')
        % lint.PINNED_VERSION_PREFIX)
    rep = lint.run_check(REPO, MANIFEST, WAIVERS, tool)
    assert (rep["status"], rep["stage"]) == ("FAIL", "run")
    assert any("verilator error" in r for r in rep["reasons"])
    assert lint.EXIT["FAIL"] == 1


def test_cli_exit_codes_and_report(tmp_path):
    rpt = tmp_path / "r.json"
    rc = lint.main(["--verilator", "/nonexistent/verilator",
                    "--report", str(rpt)])
    assert rc == 2
    doc = json.loads(rpt.read_text())
    assert doc["status"] == "NOT_RUN" and "observed" not in doc
    assert "synthesis" in doc["claim_limits"]
    assert "model-vs-Surge" in doc["claim_limits"]


def test_tool_pin_constants():
    assert lint.PINNED_VERSION == "5.050"
    assert len(lint.PIN_SOURCE_COMMIT) == 40
    assert len(lint.PIN_ARCHIVE_SHA256) == 64


# ------------------------------------------------ real pinned verilator

@needs_real
def test_real_baseline_all_eleven_groups_pass(tmp_path):
    rep = lint.run_check(REPO, MANIFEST, WAIVERS, REAL, str(tmp_path / "raw"))
    assert rep["status"] == "PASS", rep["reasons"][:5]
    assert rep["groups_executed"] == 11
    assert all(g["exit_status"] == 0 and g["errors"] == []
               for g in rep["groups"])
    assert len(os.listdir(tmp_path / "raw")) == 11


@needs_real
def test_real_source_edit_is_detected(tmp_path):
    root = tmp_path / "copy"
    shutil.copytree(os.path.join(REPO, "rtl"), str(root / "rtl"))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    p = root / "rtl" / "effects" / "rf-rf-global2" / "rf_global2_core.sv"
    s = p.read_text()
    i = s.rindex("endmodule")
    p.write_text(s[:i] + "  logic nc_en, nc_q;\n"
                 "  always_comb if (nc_en) nc_q = 1'b1;\n" + s[i:])
    rep = lint.run_check(str(root), MANIFEST, WAIVERS, REAL)
    assert (rep["status"], rep["stage"]) == ("FAIL", "compare")
    assert any(r.startswith("new SEVERE diagnostic") and " LATCH " in r
               and "nc_q" in r for r in rep["reasons"])
    assert any("source hash drift" in r for r in rep["reasons"])


@needs_real
def test_real_negative_control_mode_is_healthy(capsys):
    rc = lint.main(["--verilator", REAL, "--negative-control"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "ALL CONTROLS HEALTHY" in out
    for name in ("unclassified-tracked-rtl", "missing-tool",
                 "wrong-version-tool", "injected-latch", "count-increased",
                 "count-decreased", "stale-waiver", "new-warning"):
        assert "CONTROL-OK %s" % name in out, out
    assert "CONTROL-BROKEN" not in out
