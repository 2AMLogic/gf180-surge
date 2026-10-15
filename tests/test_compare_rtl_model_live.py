"""Re-run the RTL-vs-model comparators and compare with the committed record.

CLAUDE.md claim (1), "the RTL matches the frozen fixed-point model exactly",
is evidenced by reports/<leaf>/rtl-exactness.json. Leaf tests only re-derive
the record's hashes (STALE on mismatch); they do not re-run the comparator.
This module (#416):

1. Fails if a tools/compare_rtl_model_*.py exists that is not classified in
   tests/comparator_registry.json (or the registry names a missing script).
2. For each LIVE-IN-CI entry, runs the comparator in a scratch tree (tools/ and
   rtl/ copied, everything else symlinked, so nothing is written into the
   checkout -- the chorus comparator writes mutant testbenches next to the
   RTL) and requires its status and per-case exactness to equal the committed
   record. The committed record is never regenerated.
3. Failure control: a text mutation of the scratch RTL must make the scratch
   run report FAIL (a real FAIL record, not a crash) and be rejected by the
   same comparison helper.

Comparator scripts are byte-frozen (docs/byte-frozen-sources.md): they are
only executed, never edited. Slow entries run only with COMPARATOR_LIVE_SLOW=1
(the scheduled slow-controls workflow) and otherwise skip as NOT_RUN -- never
reported as a pass. Skip reasons for slow entries deliberately avoid naming the
simulator so the rtl-sim job's "simulator skips are failures" gate keys only on
real missing-simulator skips.
"""

import glob
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
REGISTRY_PATH = os.path.join(REPO, "tests", "comparator_registry.json")
STATUSES = ("LIVE-IN-CI", "NOT_RUN:needs-oracle", "NOT_RUN:deferred",
            "one-shot (historical)")
SLOW = os.environ.get("COMPARATOR_LIVE_SLOW") == "1"


def _registry():
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)["scripts"]


def _on_disk():
    return sorted(os.path.basename(p) for p in
                  glob.glob(os.path.join(TOOLS, "compare_rtl_model_*.py")))


def _live():
    return sorted(n for n, e in _registry().items()
                  if e["status"] == "LIVE-IN-CI")


def _case_view(doc):
    return [(c.get("case"), bool(c.get("exact"))) for c in doc.get("cases", [])]


def verdict_matches(committed, scratch):
    """(ok, reason): scratch status and per-case exactness equal the record."""
    if scratch.get("status") != committed.get("status"):
        return False, (f"status {scratch.get('status')!r} != committed "
                       f"{committed.get('status')!r}")
    if _case_view(scratch) != _case_view(committed):
        return False, "per-case exactness differs from the committed record"
    return True, ""


def _scratch_repo(root):
    """tools/ and rtl/ copied; every other top-level entry symlinked."""
    repo = os.path.join(str(root), "repo")
    os.makedirs(repo)
    for name in os.listdir(REPO):
        if name in (".git", ".loom", ".claude", "__pycache__", ".pytest_cache"):
            continue
        src = os.path.join(REPO, name)
        dst = os.path.join(repo, name)
        if name in ("tools", "rtl"):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                "__pycache__"))
        else:
            os.symlink(src, dst)
    return repo


def _run(name, ent, root, mutate=None):
    """Run the comparator from the scratch tree; return (rc, out, doc|None)."""
    repo = _scratch_repo(root)
    if mutate:
        path = os.path.join(repo, mutate["file"])
        text = open(path, encoding="utf-8").read()
        assert text.count(mutate["old"]) == mutate["count"], "control anchor moved"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(mutate["old"], mutate["new"]))
    out_json = os.path.join(str(root), "scratch-rtl-exactness.json")
    workdir = os.path.join(str(root), "wd")
    argv = [a.replace("{out}", out_json).replace("{workdir}", workdir)
            for a in ent["argv"]]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, os.path.join(repo, "tools", name)]
                       + argv, cwd=str(root), env=env, capture_output=True,
                       text=True)
    doc = None
    if os.path.exists(out_json):
        with open(out_json, encoding="utf-8") as f:
            doc = json.load(f)
    return p.returncode, (p.stdout + p.stderr)[-2000:], doc


def _need_sim(name):
    for tool in ("iverilog", "vvp"):
        if shutil.which(tool) is None:
            pytest.skip(f"NOT_RUN: {tool} absent; {name} not executed "
                        "(not a pass)")


def _committed(ent):
    with open(os.path.join(REPO, ent["record"]), encoding="utf-8") as f:
        return json.load(f)


def test_registry_is_well_formed():
    reg = _registry()
    assert reg, "empty registry"
    for name, ent in reg.items():
        assert name.startswith("compare_rtl_model_") and name.endswith(".py")
        assert ent["status"] in STATUSES, (name, ent["status"])
        if ent["status"] != "LIVE-IN-CI":
            assert ent["reason"], f"{name}: needs a recorded reason"
            continue
        assert os.path.exists(os.path.join(REPO, ent["record"])), name
        assert ent["argv"].count("{out}") == 1, name
        assert isinstance(ent["slow"], bool) and ent["reason"], name
        c = ent["control"]
        text = open(os.path.join(REPO, c["file"]), encoding="utf-8").read()
        assert text.count(c["old"]) == c["count"], f"{name}: control anchor"
        assert c["old"] != c["new"], name
    for must in ("compare_rtl_model_chorus.py", "compare_rtl_model_reverb2.py",
                 "compare_rtl_model_distortion_sse.py",
                 "compare_rtl_model_rf_global2.py"):
        assert reg[must]["status"] == "LIVE-IN-CI", must


def test_every_comparator_is_classified():
    on_disk, reg = set(_on_disk()), set(_registry())
    assert len(on_disk) >= 17, "enumeration found too few comparators"
    assert on_disk - reg == set(), (
        "unclassified tools/compare_rtl_model_*.py (add to "
        f"tests/comparator_registry.json): {sorted(on_disk - reg)}")
    assert reg - on_disk == set(), (
        f"registry names missing scripts: {sorted(reg - on_disk)}")


def test_unclassified_comparator_is_rejected():
    """Failure control for discovery: the same set comparison flags a new
    script and a dropped registry row."""
    reg = set(_registry())
    assert (set(_on_disk()) | {"compare_rtl_model_new.py"}) - reg == {
        "compare_rtl_model_new.py"}
    gone = "compare_rtl_model_chorus.py"
    assert set(_on_disk()) - (reg - {gone}) == {gone}


def test_verdict_comparison_rejects_status_and_case_drift():
    rec = {"status": "PASS", "cases": [{"case": "a", "exact": True}]}
    assert verdict_matches(rec, json.loads(json.dumps(rec)))[0]
    assert not verdict_matches(rec, dict(rec, status="FAIL"))[0]
    flipped = {"status": "PASS", "cases": [{"case": "a", "exact": False}]}
    assert not verdict_matches(rec, flipped)[0]
    assert not verdict_matches(rec, {"status": "PASS", "cases": []})[0]


@pytest.mark.parametrize("name", _live())
def test_comparator_reproduces_committed_verdict(name, tmp_path):
    ent = _registry()[name]
    if ent["slow"] and not SLOW:
        pytest.skip(f"NOT_RUN: slow comparator ({ent['reason']}); set "
                    "COMPARATOR_LIVE_SLOW=1 to execute (not a pass)")
    _need_sim(name)
    committed = _committed(ent)
    rc, out, doc = _run(name, ent, tmp_path)
    assert doc is not None, f"{name}: no scratch record written (rc {rc}):\n{out}"
    ok, why = verdict_matches(committed, doc)
    assert ok, (f"STALE/FAIL {ent['leaf']}: {name} does not reproduce "
                f"{ent['record']} ({why}); rc {rc}:\n{out}")
    assert (rc == 0) == (doc.get("status") == "PASS"), (name, rc)
    # the committed record was not touched
    assert _committed(ent) == committed


@pytest.mark.parametrize("name", _live())
def test_failure_control_mutated_rtl_fails_the_scratch_run(name, tmp_path):
    ent = _registry()[name]
    if ent["control_slow"] and not SLOW:
        pytest.skip(f"NOT_RUN: slow failure control ({ent['reason']}); set "
                    "COMPARATOR_LIVE_SLOW=1 to execute (not a pass)")
    _need_sim(name)
    committed = _committed(ent)
    rc, out, doc = _run(name, ent, tmp_path, mutate=ent["control"])
    assert doc is not None, (
        f"{name}: mutated run crashed instead of reporting FAIL "
        f"(rc {rc}); control is not a valid exactness failure:\n{out}")
    assert doc.get("status") == "FAIL" and rc != 0, (
        f"{name}: mutated RTL did not fail the comparator "
        f"(status {doc.get('status')!r}, rc {rc})")
    assert not verdict_matches(committed, doc)[0]
